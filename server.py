from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from datetime import datetime, timedelta
from typing import Optional
import os
import random
import string
import requests

# ======================
# App setup
# ======================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================
# Environment variables
# ======================
MONGO_URL = os.getenv("MONGO_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

if not MONGO_URL:
    raise Exception("❌ MONGO_URL not set")

if not RESEND_API_KEY:
    raise Exception("❌ RESEND_API_KEY not set")

# ======================
# MongoDB connection
# ======================
client = MongoClient(MONGO_URL)
db = client.get_default_database()

bookings_collection = db["bookings"]
users_collection = db["users"]
otp_collection = db["otp"]

try:
    client.admin.command("ping")
    print("✅ MongoDB connected successfully")
except Exception as e:
    print("❌ MongoDB connection failed:", e)
    raise

# ======================
# Indexes
# ======================
try:
    bookings_collection.create_index("booking_id", unique=True)
    users_collection.create_index("email", unique=True)
    otp_collection.create_index("email")
    otp_collection.create_index("created_at", expireAfterSeconds=600)
    print("✅ Indexes ensured")
except Exception as e:
    print("⚠️ Index creation skipped:", e)

# ======================
# Models
# ======================
class SendOTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

class BookingCreate(BaseModel):
    pickup_location: str = Field(..., min_length=1)
    drop_location: str = Field(..., min_length=1)
    pickup_date: str
    delivery_type: str = Field(default="bag")
    num_bags: int = Field(..., gt=0)
    first_name: str
    last_name: str
    email: EmailStr
    phone: str

class TrackBooking(BaseModel):
    booking_id: str
    email: EmailStr

# ======================
# Helpers
# ======================
def generate_otp():
    return "".join(random.choices(string.digits, k=6))

def generate_booking_id():
    return f"BD-{datetime.now().strftime('%Y%m%d')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"

# ======================
# Resend Email
# ======================
def send_email(to_email: str, subject: str, html: str) -> bool:
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": "Bagdrop <no-reply@bagdrop.co>",
                "to": to_email,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )

        if response.status_code in [200, 201, 202]:
            print(f"✅ Email sent to {to_email}")
            return True
        else:
            print("❌ Resend error:", response.text)
            return False

    except Exception as e:
        print("❌ Email exception:", str(e))
        return False

# ======================
# Health
# ======================
@app.get("/api/health")
def health():
    return {"status": "healthy"}

# ======================
# Auth
# ======================
@app.post("/api/auth/send-otp")
def send_otp(request: SendOTPRequest):
    email = request.email.lower()
    otp = generate_otp()

    otp_collection.delete_many({"email": email})

    otp_collection.insert_one({
        "email": email,
        "otp": otp,
        "created_at": datetime.utcnow()
    })

    email_sent = send_email(
        to_email=email,
        subject="Bagdrop Verification Code",
        html_=f"""
          <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #FF6B35; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h1 style="color: white; margin: 0;">BAGDROP</h1>
                    <p style="color: white; margin: 10px 0 0 0;">BAG. BOX. DELIVERED</p>
                </div>
                
                <div style="background-color: #f9f9f9; padding: 40px; border-radius: 0 0 10px 10px; text-align: center;">
                    <h2 style="color: #FF6B35;">Your Verification Code</h2>
                    
                    <p style="font-size: 16px;">Enter this code to log in to your Bagdrop account:</p>
                    
                    <div style="background-color: white; padding: 30px; border-radius: 10px; margin: 30px 0;">
                        <p style="font-size: 48px; font-weight: bold; color: #FF6B35; margin: 0; letter-spacing: 10px;">{otp}</p>
                    </div>
                    
                    <p style="color: #666; font-size: 14px;">This code will expire in 10 minutes.</p>
                    <p style="color: #666; font-size: 14px;">If you didn't request this code, please ignore this email.</p>
                    
                    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd;">
                        <p style="font-size: 14px; color: #666;">Need help? Contact us at 6357225722</p>
                    </div>
                </div>
            </div>
        """
    )

    if not email_sent:
        raise HTTPException(status_code=500, detail="Failed to send OTP email")

    return {"success": True, "message": "OTP sent successfully"}

@app.post("/api/auth/verify-otp")
def verify_otp(request: VerifyOTPRequest):
    email = request.email.lower()
    otp = request.otp

    otp_doc = otp_collection.find_one({"email": email, "otp": otp})
    if not otp_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    if datetime.utcnow() - otp_doc["created_at"] > timedelta(minutes=10):
        otp_collection.delete_one({"_id": otp_doc["_id"]})
        raise HTTPException(status_code=400, detail="OTP expired")

    user = users_collection.find_one({"email": email})
    if not user:
        users_collection.insert_one({
            "email": email,
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow(),
        })
    else:
        users_collection.update_one(
            {"email": email},
            {"$set": {"last_login": datetime.utcnow()}}
        )

    otp_collection.delete_one({"_id": otp_doc["_id"]})

    return {"success": True, "message": "Login successful"}

# ======================
# Bookings
# ======================
@app.post("/api/bookings")
def create_booking(booking: BookingCreate):
    booking_id = generate_booking_id()

    booking_data = {
        **booking.dict(),
        "booking_id": booking_id,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }

    bookings_collection.insert_one(booking_data)

    send_email(
        to_email=booking.email,
        subject=f"Bagdrop Booking {booking_id}",
        html=f"""
        <h2>Booking Confirmed</h2>
        <p>Your booking ID:</p>
        <h1>{booking_id}</h1>
        """
    )

    return {"success": True, "booking_id": booking_id}

@app.post("/api/bookings/track")
def track_booking(data: TrackBooking):
    booking = bookings_collection.find_one({
        "booking_id": data.booking_id,
        "email": data.email,
    })

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking["_id"] = str(booking["_id"])
    return {"success": True, "booking": booking}
