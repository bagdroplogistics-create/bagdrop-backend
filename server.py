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

FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY")

if not FAST2SMS_API_KEY:
    raise Exception("❌ FAST2SMS_API_KEY not set")

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
    otp_collection.create_index("phone")
    otp_collection.create_index("created_at", expireAfterSeconds=600)
    print("✅ Indexes ensured")
except Exception as e:
    print("⚠️ Index creation skipped:", e)

# ======================
# Models
# ======================
class SendOTPRequest(BaseModel):
    phone: str

class VerifyOTPRequest(BaseModel):
    phone: str
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

class BookingUpdate(BaseModel):
    pickup_location: Optional[str] = None
    drop_location: Optional[str] = None
    pickup_date: Optional[str] = None
    num_bags: Optional[int] = None

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

# ======================
# SMS
# ======================
def send_sms(phone: str, otp: str) -> bool:
    try:
        url = "https://www.fast2sms.com/dev/bulkV2"

        payload = {
            "authorization": FAST2SMS_API_KEY,
            "route": "otp",
            "variables_values": otp,
            "numbers": phone,
            "flash": "0"
        }

        headers = {
            "cache-control": "no-cache"
        }

        response = requests.get(url, params=payload, headers=headers)

        print("Fast2SMS response:", response.text)

        return response.status_code == 200

    except Exception as e:
        print("SMS error:", str(e))
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
# ======================
# Auth
# ======================
@app.post("/api/auth/send-otp")
async def send_otp(request: SendOTPRequest):
    try:
        phone = request.phone

        otp = generate_otp()

        # save OTP in DB
        otp_collection.insert_one({
            "phone": phone,
            "otp": otp,
            "created_at": datetime.utcnow()
        })

        # send SMS
        send_sms(phone, otp)

        return {
            "success": True,
            "message": "OTP sent successfully"
        }

    except Exception as e:
        return {
            "success": False,
            "detail": str(e)
        }
@app.post("/api/auth/verify-otp")
async def verify_otp(request: VerifyOTPRequest):
    try:
        phone = request.phone
        otp = request.otp

        record = otp_collection.find_one({
            "phone": phone,
            "otp": otp
        })

        if not record:
            return {
                "success": False,
                "detail": "Invalid OTP"
            }

        return {"success": True}

    except Exception as e:
        return {
            "success": False,
            "detail": str(e)
        }

# ======================
# Bookings
# ======================
@app.post("/api/bookings")
def create_booking(booking: BookingCreate):
    # 1. Generate booking ID
    booking_id = generate_booking_id()

    # 2. Save booking to DB
    booking_data = {
        **booking.dict(),
        "booking_id": booking_id,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }

    bookings_collection.insert_one(booking_data)

    # 3. Email customer
    send_email(
        to_email=booking.email,
        subject=f"Bagdrop Booking {booking_id}",
        html=f"""
        <h2>Booking Confirmed</h2>
        <p>Your booking ID:</p>
        <h1>{booking_id}</h1>
        <p>Thank you for choosing Bagdrop.</p>
        """
    )

    # 4. Email admin
    send_email(
        to_email="info@bagdrop.co",
        subject=f"New Booking Inquiry {booking_id}",
        html=f"""
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #FF6B35; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0;">BAGDROP</h1>
                <p style="color: white; margin: 10px 0 0 0;">BAG. BOX. DELIVERED</p>
            </div>

            <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <h2 style="color: #FF6B35;">Booking Received! ✓</h2>

                <p>Dear {booking_data['first_name']} {booking_data['last_name']},</p>

                <div style="background-color: white; padding: 20px; border-left: 4px solid #FF6B35; margin: 20px 0;">
                    <h3 style="margin-top: 0; color: #FF6B35;">Booking Reference</h3>
                    <p style="font-size: 24px; font-weight: bold;">{booking_id}</p>
                </div>

                <p><strong>Pickup:</strong> {booking_data['pickup_location']}</p>
                <p><strong>Drop:</strong> {booking_data['drop_location']}</p>
                <p><strong>Date:</strong> {booking_data['pickup_date']}</p>
                <p><strong>Bags:</strong> {booking_data['num_bags']}</p>
                <p><strong>Phone:</strong> {booking_data['phone']}</p>
                <p><strong>Email:</strong> {booking_data['email']}</p>

                <p style="margin-top: 30px;">Thank you for choosing Bagdrop.</p>
            </div>
        </div>
        """
    )

    # 5. Return success
    return {
        "success": True,
        "booking_id": booking_id
    }

@app.get("/api/bookings")
def get_bookings(email: str):
    bookings = list(
        bookings_collection.find(
            {"email": email},
            {"_id": 0}  # hide Mongo _id
        ).sort("created_at", -1)
    )

    return {
        "success": True,
        "bookings": bookings
    }
        

@app.post("/api/bookings/track")
def track_booking(track_data: TrackBooking):
    try:
        # Find booking by ID and email
        booking = bookings_collection.find_one({
            "booking_id": track_data.booking_id,
            "email": track_data.email
        })
        
        if not booking:
            raise HTTPException(
                status_code=404,
                detail="Booking not found. Please check your booking ID and email."
            )
        
        # Convert ObjectId to string
        booking["_id"] = str(booking["_id"])
        
        return {
            "success": True,
            "booking": booking
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error tracking booking: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/bookings/{booking_id}")
def update_booking(booking_id: str, update_data: BookingUpdate, email: str):
    try:
        # Verify booking belongs to user
        booking = bookings_collection.find_one({
            "booking_id": booking_id,
            "email": email
        })
        
        if not booking:
            raise HTTPException(
                status_code=404,
                detail="Booking not found or unauthorized"
            )
        
        if booking["status"] == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Cannot modify cancelled booking"
            )
        
        # Prepare update data
        update_fields = {k: v for k, v in update_data.dict().items() if v is not None}
        update_fields["updated_at"] = datetime.now().isoformat()
        
        # Update booking
        bookings_collection.update_one(
            {"booking_id": booking_id},
            {"$set": update_fields}
        )
        
        # Get updated booking
        updated_booking = bookings_collection.find_one({"booking_id": booking_id})
        updated_booking["_id"] = str(updated_booking["_id"])
        
        return {
            "success": True,
            "message": "Booking updated successfully",
            "booking": updated_booking
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating booking: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/bookings/{booking_id}")
def cancel_booking(booking_id: str, email: str):
    try:
        # Verify booking belongs to user
        booking = bookings_collection.find_one({
            "booking_id": booking_id,
            "email": email
        })
        
        if not booking:
            raise HTTPException(
                status_code=404,
                detail="Booking not found or unauthorized"
            )
        
        if booking["status"] == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Booking is already cancelled"
            )
        
        # Update status to cancelled
        bookings_collection.update_one(
            {"booking_id": booking_id},
            {"$set": {
                "status": "cancelled",
                "updated_at": datetime.now().isoformat()
            }}
        )
        
        return {
            "success": True,
            "message": "Booking cancelled successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error cancelling booking: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
