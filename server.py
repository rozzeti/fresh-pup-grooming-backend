from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, status, BackgroundTasks, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
import shutil
import asyncio
import requests

# Google Calendar imports
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create uploads directory
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'fresh-pup-grooming-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Notification Configuration
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

# Google Calendar Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 
    f"{os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001')}/api/oauth/calendar/callback")

# Frontend URL for redirects
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Create the main app
app = FastAPI(title="Fresh Pup Grooming API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

security = HTTPBearer()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    is_admin: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class Service(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    category: str  # "grooming", "addon"
    base_price: float
    prices_by_size: Optional[dict] = None
    is_mobile: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ServiceCreate(BaseModel):
    name: str
    description: str
    category: str
    base_price: float
    prices_by_size: Optional[dict] = None
    is_mobile: bool = False

class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    base_price: Optional[float] = None
    prices_by_size: Optional[dict] = None
    is_mobile: Optional[bool] = None
    is_active: Optional[bool] = None

class Booking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service_id: str
    service_name: str
    dog_size: str
    price: float
    tip_amount: float = 0.0
    total_amount: float = 0.0
    date: str
    time: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    is_mobile_service: bool = False
    status: str = "pending"
    notes: Optional[str] = None
    reminder_sent: bool = False
    google_event_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BookingCreate(BaseModel):
    service_id: str
    service_name: str
    dog_size: str
    price: float
    tip_amount: float = 0.0
    date: str
    time: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    is_mobile_service: bool = False
    notes: Optional[str] = None

class BookingUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None

class GalleryImage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    url: str
    title: Optional[str] = None
    is_before_after: bool = False
    before_url: Optional[str] = None
    after_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Membership(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    price: float
    frequency: str
    features: List[str]
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MembershipCreate(BaseModel):
    name: str
    description: str
    price: float
    frequency: str
    features: List[str]

class ContactMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    phone: Optional[str] = None
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_read: bool = False

class ContactCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    message: str

class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = "app_settings"
    reminders_enabled: bool = True
    reminder_hours_before: int = 24
    google_calendar_connected: bool = False
    google_calendar_email: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SettingsUpdate(BaseModel):
    reminders_enabled: Optional[bool] = None
    reminder_hours_before: Optional[int] = None

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== NOTIFICATION HELPERS ====================

async def send_email_reminder(booking: dict):
    """Send email reminder using SendGrid"""
    if not booking.get('customer_email'):
        logger.info(f"[EMAIL] No email for booking {booking['id']}")
        return False
    
    if SENDGRID_API_KEY:
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Email, To, Content
            
            sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
            
            html_content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #050505; color: #EDEDED; padding: 30px; border-radius: 12px;">
                    <h1 style="color: #2DD4BF; margin-bottom: 20px;">Fresh Pup Grooming</h1>
                    <h2>Appointment Reminder</h2>
                    <p>Hi {booking['customer_name']},</p>
                    <p>This is a friendly reminder about your upcoming grooming appointment:</p>
                    <div style="background: #1A1A1A; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <p><strong>Service:</strong> {booking['service_name']}</p>
                        <p><strong>Date:</strong> {booking['date']}</p>
                        <p><strong>Time:</strong> {booking['time']}</p>
                        <p><strong>Dog Size:</strong> {booking['dog_size'].capitalize()}</p>
                    </div>
                    <p>Need to reschedule? Give us a call at <strong>(407) 420-3148</strong></p>
                    <p>We look forward to seeing you and your furry friend!</p>
                    <p style="color: #2DD4BF;">— The Fresh Pup Team</p>
                </div>
            </div>
            """
            
            message = Mail(
                from_email=Email("noreply@freshpupgrooming.com", "Fresh Pup Grooming"),
                to_emails=To(booking['customer_email']),
                subject="Reminder: Your Grooming Appointment Tomorrow",
                html_content=Content("text/html", html_content)
            )
            
            response = sg.send(message)
            logger.info(f"[EMAIL] Sent reminder to {booking['customer_email']} - Status: {response.status_code}")
            return response.status_code == 202
        except Exception as e:
            logger.error(f"[EMAIL ERROR] {str(e)}")
            return False
    else:
        # MOCKED email
        logger.info(f"[MOCKED EMAIL] Reminder sent to {booking['customer_email']} for booking on {booking['date']} at {booking['time']}")
        return True

async def send_sms_reminder(booking: dict):
    """Send SMS reminder using Twilio"""
    if not booking.get('customer_phone'):
        logger.info(f"[SMS] No phone for booking {booking['id']}")
        return False
    
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER:
        try:
            from twilio.rest import Client
            
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            
            message_body = f"""Fresh Pup Grooming Reminder!

Hi {booking['customer_name']}, your grooming appointment is tomorrow:

📅 {booking['date']} at {booking['time']}
✂️ {booking['service_name']}

Need to reschedule? Call us: (407) 420-3148

See you soon! 🐾"""
            
            message = client.messages.create(
                body=message_body,
                from_=TWILIO_PHONE_NUMBER,
                to=booking['customer_phone']
            )
            
            logger.info(f"[SMS] Sent reminder to {booking['customer_phone']} - SID: {message.sid}")
            return True
        except Exception as e:
            logger.error(f"[SMS ERROR] {str(e)}")
            return False
    else:
        # MOCKED SMS - fall back to email
        logger.info(f"[MOCKED SMS] Twilio not configured. Would send reminder to {booking['customer_phone']}")
        return False

async def send_booking_reminders():
    """Background task to send reminders for appointments 24 hours away"""
    settings = await db.settings.find_one({"id": "app_settings"}, {"_id": 0})
    if not settings or not settings.get('reminders_enabled', True):
        logger.info("[REMINDERS] Reminders are disabled")
        return
    
    hours_before = settings.get('reminder_hours_before', 24)
    
    # Calculate the target date/time (24 hours from now)
    now = datetime.now(timezone.utc)
    target_date = (now + timedelta(hours=hours_before)).strftime('%Y-%m-%d')
    
    # Find bookings for tomorrow that haven't received reminders
    bookings = await db.bookings.find({
        "date": target_date,
        "status": {"$in": ["pending", "confirmed"]},
        "reminder_sent": {"$ne": True}
    }, {"_id": 0}).to_list(100)
    
    logger.info(f"[REMINDERS] Found {len(bookings)} bookings needing reminders for {target_date}")
    
    for booking in bookings:
        email_sent = await send_email_reminder(booking)
        sms_sent = await send_sms_reminder(booking)
        
        # If SMS failed but email succeeded, or both succeeded, mark as sent
        if email_sent or sms_sent:
            await db.bookings.update_one(
                {"id": booking['id']},
                {"$set": {"reminder_sent": True}}
            )
            logger.info(f"[REMINDERS] Marked booking {booking['id']} as reminded (email: {email_sent}, sms: {sms_sent})")

# ==================== GOOGLE CALENDAR HELPERS ====================

def get_google_flow():
    """Create Google OAuth flow"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/userinfo.email"],
        redirect_uri=GOOGLE_REDIRECT_URI
    )

async def get_google_credentials():
    """Get stored Google credentials"""
    settings = await db.settings.find_one({"id": "app_settings"}, {"_id": 0})
    if not settings or not settings.get('google_tokens'):
        return None
    
    tokens = settings['google_tokens']
    creds = Credentials(
        token=tokens.get('access_token'),
        refresh_token=tokens.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET
    )
    
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            await db.settings.update_one(
                {"id": "app_settings"},
                {"$set": {"google_tokens.access_token": creds.token}}
            )
        except Exception as e:
            logger.error(f"[GOOGLE] Failed to refresh token: {e}")
            return None
    
    return creds

async def create_calendar_event(booking: dict):
    """Create a Google Calendar event for a booking"""
    if not GOOGLE_CALENDAR_AVAILABLE:
        logger.info("[GOOGLE] Google Calendar libraries not available")
        return None
    
    creds = await get_google_credentials()
    if not creds:
        logger.info("[GOOGLE] No Google credentials configured")
        return None
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        
        # Parse date and time
        date_str = booking['date']
        time_str = booking['time']
        
        # Convert time like "10:00 AM" to 24h format
        from datetime import datetime as dt
        time_obj = dt.strptime(time_str, '%I:%M %p')
        start_datetime = f"{date_str}T{time_obj.strftime('%H:%M')}:00"
        
        # Assume 1 hour appointment
        end_time = time_obj + timedelta(hours=1)
        end_datetime = f"{date_str}T{end_time.strftime('%H:%M')}:00"
        
        event = {
            'summary': f"🐕 {booking['customer_name']} - {booking['service_name']}",
            'description': f"""Customer: {booking['customer_name']}
Phone: {booking['customer_phone']}
Email: {booking.get('customer_email', 'N/A')}
Service: {booking['service_name']}
Dog Size: {booking['dog_size'].capitalize()}
Price: ${booking['price']}
{'Address: ' + booking['customer_address'] if booking.get('customer_address') else ''}
Notes: {booking.get('notes', 'None')}""",
            'start': {
                'dateTime': start_datetime,
                'timeZone': 'America/New_York'
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': 'America/New_York'
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 60},
                    {'method': 'popup', 'minutes': 1440}  # 24 hours
                ]
            }
        }
        
        if booking.get('customer_address'):
            event['location'] = booking['customer_address']
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"[GOOGLE] Created calendar event: {created_event.get('id')}")
        return created_event.get('id')
    except Exception as e:
        logger.error(f"[GOOGLE] Failed to create event: {e}")
        return None

async def delete_calendar_event(event_id: str):
    """Delete a Google Calendar event"""
    if not GOOGLE_CALENDAR_AVAILABLE or not event_id:
        return False
    
    creds = await get_google_credentials()
    if not creds:
        return False
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        logger.info(f"[GOOGLE] Deleted calendar event: {event_id}")
        return True
    except Exception as e:
        logger.error(f"[GOOGLE] Failed to delete event: {e}")
        return False

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(data: UserCreate):
    existing = await db.users.find_one({"email": data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": data.email,
        "name": data.name,
        "password_hash": hash_password(data.password),
        "is_admin": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    token = create_token(user_id)
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user_id, email=data.email, name=data.name)
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(data: UserLogin):
    user = await db.users.find_one({"email": data.email}, {"_id": 0})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"])
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user["id"], email=user["email"], name=user["name"])
    )

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(id=user["id"], email=user["email"], name=user["name"])

# ==================== SETTINGS ROUTES ====================

@api_router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    settings = await db.settings.find_one({"id": "app_settings"}, {"_id": 0})
    if not settings:
        settings = Settings().model_dump()
        settings['updated_at'] = settings['updated_at'].isoformat()
        await db.settings.insert_one(settings)
    
    # Check if Google Calendar is properly configured
    settings['google_calendar_configured'] = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    settings['sendgrid_configured'] = bool(SENDGRID_API_KEY)
    settings['twilio_configured'] = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)
    
    return settings

@api_router.put("/settings")
async def update_settings(data: SettingsUpdate, user: dict = Depends(get_current_user)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
    
    await db.settings.update_one(
        {"id": "app_settings"},
        {"$set": update_data},
        upsert=True
    )
    
    return await get_settings(user)

# ==================== GOOGLE CALENDAR ROUTES ====================

@api_router.get("/oauth/calendar/login")
async def google_calendar_login(user: dict = Depends(get_current_user)):
    """Start Google Calendar OAuth flow"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Google Calendar not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env")
    
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true'
    )
    
    return {"authorization_url": authorization_url}

@api_router.get("/oauth/calendar/callback")
async def google_calendar_callback(code: str, state: str = None):
    """Handle Google Calendar OAuth callback"""
    try:
        # Exchange code for tokens
        token_resp = requests.post('https://oauth2.googleapis.com/token', data={
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }).json()
        
        if 'error' in token_resp:
            logger.error(f"[GOOGLE] Token error: {token_resp}")
            return RedirectResponse(f"{FRONTEND_URL}/admin/settings?error=auth_failed")
        
        # Get user email
        user_info = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {token_resp["access_token"]}'}
        ).json()
        
        # Save tokens to settings
        await db.settings.update_one(
            {"id": "app_settings"},
            {"$set": {
                "google_tokens": token_resp,
                "google_calendar_connected": True,
                "google_calendar_email": user_info.get('email'),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        logger.info(f"[GOOGLE] Connected calendar for {user_info.get('email')}")
        return RedirectResponse(f"{FRONTEND_URL}/admin/settings?success=calendar_connected")
    except Exception as e:
        logger.error(f"[GOOGLE] Callback error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/admin/settings?error=callback_failed")

@api_router.post("/oauth/calendar/disconnect")
async def disconnect_google_calendar(user: dict = Depends(get_current_user)):
    """Disconnect Google Calendar"""
    await db.settings.update_one(
        {"id": "app_settings"},
        {"$set": {
            "google_tokens": None,
            "google_calendar_connected": False,
            "google_calendar_email": None,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    return {"message": "Google Calendar disconnected"}

# ==================== SERVICES ROUTES ====================

@api_router.get("/services", response_model=List[Service])
async def get_services():
    services = await db.services.find({"is_active": True}, {"_id": 0}).to_list(100)
    for s in services:
        if isinstance(s.get('created_at'), str):
            s['created_at'] = datetime.fromisoformat(s['created_at'])
    return services

@api_router.get("/services/all", response_model=List[Service])
async def get_all_services(user: dict = Depends(get_current_user)):
    services = await db.services.find({}, {"_id": 0}).to_list(100)
    for s in services:
        if isinstance(s.get('created_at'), str):
            s['created_at'] = datetime.fromisoformat(s['created_at'])
    return services

@api_router.post("/services", response_model=Service)
async def create_service(data: ServiceCreate, user: dict = Depends(get_current_user)):
    service = Service(**data.model_dump())
    doc = service.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.services.insert_one(doc)
    return service

@api_router.put("/services/{service_id}", response_model=Service)
async def update_service(service_id: str, data: ServiceUpdate, user: dict = Depends(get_current_user)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")
    
    result = await db.services.update_one({"id": service_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    
    service = await db.services.find_one({"id": service_id}, {"_id": 0})
    if isinstance(service.get('created_at'), str):
        service['created_at'] = datetime.fromisoformat(service['created_at'])
    return Service(**service)

@api_router.delete("/services/{service_id}")
async def delete_service(service_id: str, user: dict = Depends(get_current_user)):
    result = await db.services.delete_one({"id": service_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"message": "Service deleted"}

# ==================== BOOKINGS ROUTES ====================

@api_router.post("/bookings", response_model=Booking)
async def create_booking(data: BookingCreate, background_tasks: BackgroundTasks):
    # Calculate total amount with tip
    total_amount = data.price + data.tip_amount
    
    booking = Booking(
        **data.model_dump(),
        total_amount=total_amount
    )
    doc = booking.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.bookings.insert_one(doc)
    
    # Create Google Calendar event in background
    async def create_event_task():
        event_id = await create_calendar_event(doc)
        if event_id:
            await db.bookings.update_one(
                {"id": booking.id},
                {"$set": {"google_event_id": event_id}}
            )
    
    background_tasks.add_task(create_event_task)
    
    # MOCKED: Send confirmation notifications
    logger.info(f"[MOCKED EMAIL] Booking confirmation sent to {data.customer_name}")
    logger.info(f"[MOCKED SMS] Booking confirmation sent to {data.customer_phone}")
    
    return booking

@api_router.get("/bookings", response_model=List[Booking])
async def get_bookings(user: dict = Depends(get_current_user)):
    bookings = await db.bookings.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for b in bookings:
        if isinstance(b.get('created_at'), str):
            b['created_at'] = datetime.fromisoformat(b['created_at'])
    return bookings

@api_router.get("/bookings/{booking_id}", response_model=Booking)
async def get_booking(booking_id: str):
    booking = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if isinstance(booking.get('created_at'), str):
        booking['created_at'] = datetime.fromisoformat(booking['created_at'])
    return Booking(**booking)

@api_router.put("/bookings/{booking_id}", response_model=Booking)
async def update_booking(booking_id: str, data: BookingUpdate, user: dict = Depends(get_current_user)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")
    
    # If cancelling, delete calendar event
    if update_data.get('status') == 'cancelled':
        booking = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
        if booking and booking.get('google_event_id'):
            await delete_calendar_event(booking['google_event_id'])
    
    result = await db.bookings.update_one({"id": booking_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    booking = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if isinstance(booking.get('created_at'), str):
        booking['created_at'] = datetime.fromisoformat(booking['created_at'])
    return Booking(**booking)

# ==================== REMINDERS ROUTE ====================

@api_router.post("/reminders/send")
async def trigger_reminders(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Manually trigger reminder sending"""
    background_tasks.add_task(send_booking_reminders)
    return {"message": "Reminder task started"}

@api_router.get("/reminders/preview")
async def preview_reminders(user: dict = Depends(get_current_user)):
    """Preview which bookings would receive reminders"""
    settings = await db.settings.find_one({"id": "app_settings"}, {"_id": 0})
    hours_before = settings.get('reminder_hours_before', 24) if settings else 24
    
    now = datetime.now(timezone.utc)
    target_date = (now + timedelta(hours=hours_before)).strftime('%Y-%m-%d')
    
    bookings = await db.bookings.find({
        "date": target_date,
        "status": {"$in": ["pending", "confirmed"]},
        "reminder_sent": {"$ne": True}
    }, {"_id": 0}).to_list(100)
    
    return {
        "target_date": target_date,
        "pending_reminders": len(bookings),
        "bookings": bookings
    }

# ==================== GALLERY ROUTES ====================

@api_router.get("/gallery", response_model=List[GalleryImage])
async def get_gallery():
    images = await db.gallery.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    for img in images:
        if isinstance(img.get('created_at'), str):
            img['created_at'] = datetime.fromisoformat(img['created_at'])
    return images

@api_router.post("/gallery/upload")
async def upload_gallery_image(
    file: UploadFile = File(...),
    title: str = "",
    is_before_after: bool = False,
    user: dict = Depends(get_current_user)
):
    ext = Path(file.filename).suffix
    filename = f"{uuid.uuid4()}{ext}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    image = GalleryImage(
        filename=filename,
        url=f"/api/uploads/{filename}",
        title=title,
        is_before_after=is_before_after
    )
    doc = image.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.gallery.insert_one(doc)
    
    return image

@api_router.post("/gallery/upload-before-after")
async def upload_before_after(
    before_file: UploadFile = File(...),
    after_file: UploadFile = File(...),
    title: str = "",
    user: dict = Depends(get_current_user)
):
    before_ext = Path(before_file.filename).suffix
    before_filename = f"{uuid.uuid4()}{before_ext}"
    before_filepath = UPLOAD_DIR / before_filename
    with open(before_filepath, "wb") as buffer:
        shutil.copyfileobj(before_file.file, buffer)
    
    after_ext = Path(after_file.filename).suffix
    after_filename = f"{uuid.uuid4()}{after_ext}"
    after_filepath = UPLOAD_DIR / after_filename
    with open(after_filepath, "wb") as buffer:
        shutil.copyfileobj(after_file.file, buffer)
    
    image = GalleryImage(
        filename=after_filename,
        url=f"/api/uploads/{after_filename}",
        title=title,
        is_before_after=True,
        before_url=f"/api/uploads/{before_filename}",
        after_url=f"/api/uploads/{after_filename}"
    )
    doc = image.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.gallery.insert_one(doc)
    
    return image

@api_router.delete("/gallery/{image_id}")
async def delete_gallery_image(image_id: str, user: dict = Depends(get_current_user)):
    image = await db.gallery.find_one({"id": image_id}, {"_id": 0})
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    
    try:
        filepath = UPLOAD_DIR / image["filename"]
        if filepath.exists():
            filepath.unlink()
        if image.get("before_url"):
            before_filename = image["before_url"].split("/")[-1]
            before_path = UPLOAD_DIR / before_filename
            if before_path.exists():
                before_path.unlink()
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
    
    await db.gallery.delete_one({"id": image_id})
    return {"message": "Image deleted"}

# ==================== MEMBERSHIPS ROUTES ====================

@api_router.get("/memberships", response_model=List[Membership])
async def get_memberships():
    memberships = await db.memberships.find({"is_active": True}, {"_id": 0}).to_list(20)
    for m in memberships:
        if isinstance(m.get('created_at'), str):
            m['created_at'] = datetime.fromisoformat(m['created_at'])
    return memberships

@api_router.post("/memberships", response_model=Membership)
async def create_membership(data: MembershipCreate, user: dict = Depends(get_current_user)):
    membership = Membership(**data.model_dump())
    doc = membership.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.memberships.insert_one(doc)
    return membership

@api_router.delete("/memberships/{membership_id}")
async def delete_membership(membership_id: str, user: dict = Depends(get_current_user)):
    result = await db.memberships.delete_one({"id": membership_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"message": "Membership deleted"}

# ==================== CONTACT ROUTES ====================

@api_router.post("/contact", response_model=ContactMessage)
async def submit_contact(data: ContactCreate):
    message = ContactMessage(**data.model_dump())
    doc = message.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.contacts.insert_one(doc)
    
    logger.info(f"[MOCKED EMAIL] New contact message from {data.name}: {data.message[:50]}...")
    
    return message

@api_router.get("/contacts", response_model=List[ContactMessage])
async def get_contacts(user: dict = Depends(get_current_user)):
    contacts = await db.contacts.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    for c in contacts:
        if isinstance(c.get('created_at'), str):
            c['created_at'] = datetime.fromisoformat(c['created_at'])
    return contacts

@api_router.put("/contacts/{contact_id}/read")
async def mark_contact_read(contact_id: str, user: dict = Depends(get_current_user)):
    result = await db.contacts.update_one({"id": contact_id}, {"$set": {"is_read": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"message": "Marked as read"}

# ==================== STATS ROUTES ====================

@api_router.get("/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    total_bookings = await db.bookings.count_documents({})
    pending_bookings = await db.bookings.count_documents({"status": "pending"})
    confirmed_bookings = await db.bookings.count_documents({"status": "confirmed"})
    total_services = await db.services.count_documents({"is_active": True})
    total_contacts = await db.contacts.count_documents({"is_read": False})
    
    # Calculate total revenue
    bookings = await db.bookings.find({"status": {"$in": ["confirmed", "completed"]}}, {"_id": 0, "total_amount": 1, "price": 1, "tip_amount": 1}).to_list(1000)
    total_revenue = sum(b.get('total_amount', b.get('price', 0)) for b in bookings)
    total_tips = sum(b.get('tip_amount', 0) for b in bookings)
    
    return {
        "total_bookings": total_bookings,
        "pending_bookings": pending_bookings,
        "confirmed_bookings": confirmed_bookings,
        "total_services": total_services,
        "unread_contacts": total_contacts,
        "total_revenue": round(total_revenue, 2),
        "total_tips": round(total_tips, 2)
    }

# ==================== SEED DATA ====================

@api_router.post("/seed")
async def seed_data():
    existing = await db.services.count_documents({})
    if existing > 0:
        return {"message": "Data already seeded"}
    
    services = [
        {
            "id": str(uuid.uuid4()),
            "name": "Full Groom",
            "description": "Complete grooming package including bath, haircut, nail trim, and ear cleaning",
            "category": "grooming",
            "base_price": 40,
            "prices_by_size": {"small": 40, "medium": 55, "large": 70, "xlarge": 85},
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Mobile Grooming",
            "description": "Full grooming service at your doorstep - we come to you!",
            "category": "grooming",
            "base_price": 55,
            "prices_by_size": {"small": 55, "medium": 70, "large": 90, "xlarge": 110},
            "is_mobile": True,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Bath & Brush",
            "description": "Refreshing bath with brushing and blow dry",
            "category": "grooming",
            "base_price": 25,
            "prices_by_size": {"small": 25, "medium": 35, "large": 45, "xlarge": 55},
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Deshedding Treatment",
            "description": "Deep deshedding to reduce shedding up to 80%",
            "category": "addon",
            "base_price": 15,
            "prices_by_size": None,
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Nail Trim & Grind",
            "description": "Professional nail trimming and smoothing",
            "category": "addon",
            "base_price": 12,
            "prices_by_size": None,
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Teeth Brushing",
            "description": "Fresh breath dental cleaning",
            "category": "addon",
            "base_price": 10,
            "prices_by_size": None,
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Cologne & Bandana",
            "description": "Finishing touch with premium cologne and cute bandana/bow",
            "category": "addon",
            "base_price": 8,
            "prices_by_size": None,
            "is_mobile": False,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    await db.services.insert_many(services)
    
    memberships = [
        {
            "id": str(uuid.uuid4()),
            "name": "Pup Essential",
            "description": "Perfect for maintaining your pup's fresh look",
            "price": 79,
            "frequency": "monthly",
            "features": [
                "1 Full Groom per month",
                "10% off add-ons",
                "Priority booking",
                "Free nail trim"
            ],
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Pup Premium",
            "description": "The ultimate care package for your furry friend",
            "price": 149,
            "frequency": "monthly",
            "features": [
                "2 Full Grooms per month",
                "20% off all add-ons",
                "Priority booking",
                "Free deshedding treatment",
                "Free teeth brushing",
                "Complimentary cologne & bandana"
            ],
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Pup VIP",
            "description": "Exclusive mobile grooming membership",
            "price": 199,
            "frequency": "monthly",
            "features": [
                "2 Mobile Grooms per month",
                "25% off all add-ons",
                "Same-day booking priority",
                "All add-ons included",
                "Monthly wellness check",
                "Exclusive member discounts"
            ],
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    await db.memberships.insert_many(memberships)
    
    # Initialize settings
    settings = {
        "id": "app_settings",
        "reminders_enabled": True,
        "reminder_hours_before": 24,
        "google_calendar_connected": False,
        "google_calendar_email": None,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await db.settings.insert_one(settings)
    
    return {"message": "Data seeded successfully"}

# Root endpoint
@api_router.get("/")
async def root():
    return {"message": "Fresh Pup Grooming API", "status": "running"}

# Include the router in the main app
app.include_router(api_router)

# Mount static files for uploads
app.mount("/api/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
