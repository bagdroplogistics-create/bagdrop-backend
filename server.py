from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from datetime import datetime, timedelta
from typing import Optional
import os
from dotenv import load_dotenv
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URL = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URL)
db = client[os.getenv("DB_NAME", "bagdrop_db")]
bookings_collection = db["bookings"]
users_collection = db["users"]
otp_collection = db["otps"]

# Create indexes with error handling for production environments
# where the user may not have index creation permissions
try:
    bookings_collection.create_index("booking_id", unique=True)
    users_collection.create_index("email", unique=True)
    otp_collection.create_index("email")
    otp_collection.create_index("created_at", expireAfterSeconds=600)
    print("✅ Database indexes created successfully")
except Exception as e:
    print(f"⚠️ Could not create indexes (this is normal in production): {str(e)}")
    # Indexes might already exist or user doesn't have permissions - continue anyway

# Models
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
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=10)

class BookingUpdate(BaseModel):
    pickup_location: Optional[str] = None
    drop_location: Optional[str] = None
    pickup_date: Optional[str] = None
    num_bags: Optional[int] = None

class TrackBooking(BaseModel):
    booking_id: str
    email: str

# Helper function to generate unique booking ID
def generate_booking_id():
    date_str = datetime.now().strftime("%Y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BD-{date_str}-{random_str}"

# Helper function to generate OTP
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

# Send OTP email function
def send_otp_email(email, otp):
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_PASSWORD")
        
        if not gmail_user or not gmail_password:
            print("⚠️ Gmail credentials not configured. Email not sent.")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Bagdrop Login - Verification Code"
        msg['From'] = gmail_user
        msg['To'] = email
        
        # Create HTML email body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
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
        </body>
        </html>
        """
        
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, email, msg.as_string())
        
        print(f"✅ OTP email sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending OTP email: {str(e)}")
        return False

# Real Gmail SMTP email function
def send_booking_email(booking_data):
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_PASSWORD")
        
        if not gmail_user or not gmail_password:
            print("⚠️ Gmail credentials not configured. Email not sent.")
            return
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Bagdrop Booking Received - {booking_data['booking_id']}"
        msg['From'] = gmail_user
        msg['To'] = booking_data['email']
        msg['Cc'] = "info@bagdrop.co"
        
        # Create HTML email body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #FF6B35; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h1 style="color: white; margin: 0;">BAGDROP</h1>
                    <p style="color: white; margin: 10px 0 0 0;">BAG. BOX. DELIVERED</p>
                </div>
                
                <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h2 style="color: #FF6B35;">Booking Received! ✓</h2>
                    
                    <p>Dear {booking_data['first_name']} {booking_data['last_name']},</p>
                    
                    <p>Thank you for your inquiry! Bagdrop has received your request and our team will confirm your baggage delivery service at the earliest, or within 24 hours of receiving your message.</p>
                    
                    <div style="background-color: white; padding: 20px; border-left: 4px solid #FF6B35; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #FF6B35;">Booking Reference</h3>
                        <p style="font-size: 24px; font-weight: bold; margin: 10px 0;">{booking_data['booking_id']}</p>
                    </div>
                    
                    <h3 style="color: #FF6B35;">Delivery Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 10px; background-color: white;"><strong>Delivery Type:</strong></td>
                            <td style="padding: 10px; background-color: white;">{booking_data['delivery_type'].title()} Delivery</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background-color: #f5f5f5;"><strong>Pickup Location:</strong></td>
                            <td style="padding: 10px; background-color: #f5f5f5;">{booking_data['pickup_location']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background-color: white;"><strong>Drop Location:</strong></td>
                            <td style="padding: 10px; background-color: white;">{booking_data['drop_location']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background-color: #f5f5f5;"><strong>Pickup Date:</strong></td>
                            <td style="padding: 10px; background-color: #f5f5f5;">{booking_data['pickup_date']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background-color: white;"><strong>Number of {booking_data['delivery_type'].title()}s:</strong></td>
                            <td style="padding: 10px; background-color: white;">{booking_data['num_bags']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background-color: #f5f5f5;"><strong>Phone Number:</strong></td>
                            <td style="padding: 10px; background-color: #f5f5f5;">{booking_data['phone']}</td>
                        </tr>
                    </table>
                    
                    <div style="background-color: #FFF5F2; padding: 15px; border-radius: 8px; margin-top: 20px;">
                        <p style="margin: 0;"><strong>Need Assistance?</strong></p>
                        <p style="margin: 5px 0;">📞 Call us at: <strong>6357115711</strong> | <strong>6357225722</strong> | <strong>6357335733</strong></p>
                        <p style="margin: 5px 0;">📧 Email: <strong>info@bagdrop.co</strong></p>
                    </div>
                    
                    <p style="margin-top: 30px;">Thank you for choosing Bagdrop!</p>
                    <p style="color: #666; font-size: 14px;">Bagdrop Logistics Solutions - Premium Baggage Delivery Service</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Attach HTML body
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send email via Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            recipients = [booking_data['email'], 'info@bagdrop.co']
            server.sendmail(gmail_user, recipients, msg.as_string())
        
        print(f"✅ Email sent successfully to {booking_data['email']} and info@bagdrop.co")
        print(f"   Booking ID: {booking_data['booking_id']}")
        
    except Exception as e:
        print(f"❌ Error sending email: {str(e)}")
        # Don't fail the booking if email fails
        pass

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Bagdrop API"}

# Authentication Endpoints
@app.post("/api/auth/send-otp")
def send_otp(request: SendOTPRequest):
    try:
        email = request.email.lower()
        
        # Generate OTP
        otp = generate_otp()
        
        # Store OTP in database
        otp_data = {
            "email": email,
            "otp": otp,
            "created_at": datetime.now()
        }
        
        # Try to delete any existing OTPs for this email (may fail in production due to permissions)
        try:
            otp_collection.delete_many({"email": email})
        except Exception as delete_error:
            print(f"⚠️ Could not delete old OTPs (continuing anyway): {str(delete_error)}")
        
        # Insert new OTP
        try:
            otp_collection.insert_one(otp_data)
        except Exception as insert_error:
            # If insert fails, try to update existing document instead
            print(f"⚠️ Insert failed, trying update instead: {str(insert_error)}")
            try:
                otp_collection.update_one(
                    {"email": email},
                    {"$set": otp_data},
                    upsert=True
                )
            except Exception as update_error:
                print(f"❌ Both insert and update failed: {str(update_error)}")
                raise HTTPException(status_code=500, detail="Could not store OTP")
        
        # Send OTP email
        email_sent = send_otp_email(email, otp)
        
        if not email_sent:
            raise HTTPException(status_code=500, detail="Failed to send OTP email")
        
        return {
            "success": True,
            "message": "OTP sent to your email"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error sending OTP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/verify-otp")
def verify_otp(request: VerifyOTPRequest):
    try:
        email = request.email.lower()
        otp = request.otp
        
        # Find OTP in database
        otp_doc = otp_collection.find_one({"email": email, "otp": otp})
        
        if not otp_doc:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Check if OTP is expired (10 minutes)
        created_at = otp_doc["created_at"]
        if datetime.now() - created_at > timedelta(minutes=10):
            # Try to delete expired OTP (may fail in production)
            try:
                otp_collection.delete_one({"_id": otp_doc["_id"]})
            except Exception:
                pass  # Continue even if delete fails
            raise HTTPException(status_code=400, detail="OTP has expired")
        
        # OTP is valid - create or update user
        user = users_collection.find_one({"email": email})
        
        if not user:
            # Create new user
            user_data = {
                "email": email,
                "created_at": datetime.now().isoformat(),
                "last_login": datetime.now().isoformat()
            }
            try:
                result = users_collection.insert_one(user_data)
                user_data["_id"] = str(result.inserted_id)
            except Exception as e:
                print(f"⚠️ Could not create user (may already exist): {str(e)}")
                # Try to fetch existing user
                user = users_collection.find_one({"email": email})
                if user:
                    user["_id"] = str(user["_id"])
                    user_data = user
                else:
                    raise HTTPException(status_code=500, detail="Could not create or fetch user")
        else:
            # Update last login (with permission handling)
            try:
                users_collection.update_one(
                    {"email": email},
                    {"$set": {"last_login": datetime.now().isoformat()}}
                )
            except Exception as e:
                print(f"⚠️ Could not update last login (continuing anyway): {str(e)}")
            user["_id"] = str(user["_id"])
            user_data = user
        
        # Try to delete used OTP (may fail in production due to permissions)
        try:
            otp_collection.delete_one({"_id": otp_doc["_id"]})
        except Exception as e:
            print(f"⚠️ Could not delete used OTP (continuing anyway): {str(e)}")
        
        return {
            "success": True,
            "message": "Login successful",
            "user": {
                "email": email,
                "created_at": user_data.get("created_at") if isinstance(user_data, dict) else user.get("created_at")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error verifying OTP: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bookings")
def create_booking(booking: BookingCreate):
    try:
        # Generate unique booking ID
        booking_id = generate_booking_id()
        
        # Create booking document
        booking_data = {
            "booking_id": booking_id,
            "pickup_location": booking.pickup_location,
            "drop_location": booking.drop_location,
            "pickup_date": booking.pickup_date,
            "delivery_type": booking.delivery_type,
            "num_bags": booking.num_bags,
            "first_name": booking.first_name,
            "last_name": booking.last_name,
            "email": booking.email,
            "phone": booking.phone,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        # Insert into database
        result = bookings_collection.insert_one(booking_data)
        
        # Send mock email
        send_booking_email(booking_data)
        
        # Return booking confirmation
        booking_data["_id"] = str(result.inserted_id)
        return {
            "success": True,
            "message": "Booking created successfully",
            "booking": booking_data
        }
    except Exception as e:
        print(f"Error creating booking: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bookings")
def get_user_bookings(email: str):
    try:
        # Find all bookings for the user, sorted by created_at (newest first)
        bookings = list(bookings_collection.find({"email": email}).sort("created_at", -1))
        
        # Convert ObjectId to string for all bookings
        for booking in bookings:
            booking["_id"] = str(booking["_id"])
        
        return {
            "success": True,
            "bookings": bookings,
            "count": len(bookings)
        }
    except Exception as e:
        print(f"Error fetching bookings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/locations")
def get_locations():
    return {
        "cities": [
            "Mumbai",
            "Delhi",
            "Ahmedabad",
            "Goa",
            "Pune",
            "Surat",
            "Vadodara",
            "Rajkot"
        ],
        "airports": [
            "Mumbai Airport (BOM)",
            "Delhi Airport (DEL)",
            "Ahmedabad Airport (AMD)",
            "Goa Airport (GOI)"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
