from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from datetime import datetime, timedelta
from typing import Optional
import os
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ------------------- APP -------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------- MONGO -------------------
MONGO_URL = os.getenv("MONGO_URL")

if not MONGO_URL:
    raise RuntimeError("MONGO_URL environment variable not set")

client = MongoClient(
    MONGO_URL,
    serverSelectionTimeoutMS=5000
)

db = client.get_database()
bookings_collection = db["bookings"]
users_collection = db["users"]
otp_collection = db["otp"]

try:
    client.admin.command("ping")
    print("✅ MongoDB connected")
except Exception as e:
    print("❌ MongoDB connection failed:", e)

# TTL index (10 minutes)
try:
    otp_collection.create_index("created_at", expireAfterSeconds=600)
except Exception:
    pass

# ------------------- MODELS -------------------
class SendOTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

class BookingCreate(BaseModel):
    pickup_location: str
    drop_location: str
    pickup_date: str
    delivery_type: str = "bag"
    num_bags: int
    first_name: str
    last_name: str
    email: EmailStr
    phone: str

class TrackBooking(BaseModel):
    booking_id: str
    email: EmailStr

# ------------------- HELPERS -------------------
def generate_otp():
    return "".join(random.choices(string.digits, k=6))

def generate_booking_id():
    return f"BD-{datetime.utcnow().strftime('%Y%m%d')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"

def send_email(to_email, subject, html):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_PASSWORD")

    if not gmail_user or not gmail_pass:
        print("❌ Gmail credentials missing")
        return False

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
        return True
    except Exception as e:
        print("❌ Email error:", e)
        return False

# ------------------- HEALTH -------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}

# ------------------- AUTH -------------------
@app.post("/api/auth/send-otp")
def send_otp(data: SendOTPRequest):
    email = data.email.lower()
    otp = generate_otp()

    # UPSERT OTP (SAFE FOR RENDER)
    otp_collection.update_one(
        {"email": email},
        {
            "$set": {
                "email": email,
                "otp": otp,
                "created_at": datetime.utcnow()
            }
        },
        upsert=True
    )

    email_sent = send_email(
        email,
        "Bagdrop Login OTP",
        f"<h2>Your OTP is</h2><h1>{otp}</h1><p>Valid for 10 minutes</p>"
    )

    if not email_sent:
        raise HTTPException(status_code=500, detail="Failed to send OTP")

    return {"success": True, "message": "OTP sent successfully"}

@app.post("/api/auth/verify-otp")
def verify_otp(data: VerifyOTPRequest):
    email = data.email.lower()

    otp_doc = otp_collection.find_one({"email": email, "otp": data.otp})

    if not otp_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    if datetime.utcnow() - otp_doc["created_at"] > timedelta(minutes=10):
        raise HTTPException(status_code=400, detail="OTP expired")

    users_collection.update_one(
        {"email": email},
        {"$set": {"email": email, "last_login": datetime.utcnow()}},
        upsert=True
    )

    otp_collection.delete_one({"_id": otp_doc["_id"]})

    return {"success": True, "message": "Login successful"}

# ------------------- BOOKINGS -------------------
@app.post("/api/bookings")
def create_booking(data: BookingCreate):
    booking_id = generate_booking_id()

    booking = {
        **data.dict(),
        "booking_id": booking_id,
        "status": "pending",
        "created_at": datetime.utcnow()
    }

    bookings_collection.insert_one(booking)
    return {"success": True, "booking_id": booking_id}

@app.post("/api/bookings/track")
def track_booking(data: TrackBooking):
    booking = bookings_collection.find_one({
        "booking_id": data.booking_id,
        "email": data.email
    })

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking["_id"] = str(booking["_id"])
    return {"success": True, "booking": booking}

# ------------------- RUN -------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
