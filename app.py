import re
import os
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import qrcode
from twilio.rest import Client  # <--- Added Twilio Import

# Load configuration
from config import config

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(config['default'])

# Initialize security extensions
csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["400 per day", "350 per hour"]
)

# ==========================
# ENTRANCE COORDINATES & CONSTANTS
# ==========================

ENTRANCE_LAT = app.config.get('ENTRANCE_LAT', 15.8497)
ENTRANCE_LNG = app.config.get('ENTRANCE_LNG', 74.4977)

# ==========================================
# TWILIO SMS CONFIGURATION & HELPER FUNCTION
# ==========================================

TWILIO_ACCOUNT_SID = app.config.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = app.config.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = app.config.get('TWILIO_PHONE_NUMBER')
OWNER_PHONE_NUMBER = app.config.get('OWNER_PHONE_NUMBER')

def send_sms(to_number, message_body):
    """Utility function to safely send SMS alerts"""
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        print(f"✅ SMS Sent successfully! Message SID: {message.sid}")
    except Exception as e:
        print(f"❌ Failed to send SMS: {e}")

# ==========================
# SECURITY HELPERS
# ==========================

def sanitize_input(input_string):
    """Sanitize user input to prevent XSS attacks"""
    if not input_string:
        return ""
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>\"\'\&]', '', str(input_string))
    return sanitized.strip()

def validate_email(email):
    """Validate email format"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """Validate phone number format (10 digits)"""
    if not phone:
        return True  # Phone is optional
    pattern = r'^[0-9]{10}$'
    return re.match(pattern, phone) is not None

def validate_password_strength(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    return True, "Password is valid"

def add_security_headers(response):
    """Add security headers to HTTP responses"""
    security_headers = app.config.get('SECURITY_HEADERS', {})
    for header, value in security_headers.items():
        response.headers[header] = value
    return response

# ==========================
# REAL-TIME NOTIFICATION HELPER
# ==========================

def notify_realtime_server():
    """Notify Node.js server of parking updates for real-time map updates"""
    try:
        realtime_server_url = "http://localhost:5001/api/broadcast-update"
        response = requests.post(realtime_server_url, json={}, timeout=2)
        if response.status_code == 200:
            print("✅ Real-time server notified of parking update")
        else:
            print(f"⚠️ Real-time server returned status {response.status_code}")
    except Exception as e:
        print(f"⚠️ Could not notify real-time server: {e}")

# ==========================
# DATABASE CONFIGURATION
# ==========================

db = SQLAlchemy(app)

# ==========================
# USER TABLE
# ==========================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    failed_login_attempts = db.Column(db.Integer, default=0)
    account_locked = db.Column(db.Boolean, default=False)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)


# ==========================
# VEHICLE TABLE
# ==========================

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100), nullable=False)
    vehicle_number = db.Column(db.String(30), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(30), nullable=False)


# ==========================
# PARKING AREA TABLE
# ==========================

class ParkingArea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    area_name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    city = db.Column(db.String(50), default="Belagavi")
    state = db.Column(db.String(50), default="Karnataka")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    total_slots = db.Column(db.Integer, default=0)
    available_slots = db.Column(db.Integer, default=0)
    occupied_slots = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="Active")
    description = db.Column(db.Text)
    opening_time = db.Column(db.String(20), default="06:00")
    closing_time = db.Column(db.String(20), default="22:00")
    parking_type = db.Column(db.String(50), default="Public")
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationship with parking slots
    slots = db.relationship('ParkingSlot', backref='parking_area', lazy=True)


# ==========================
# PARKING SLOT TABLE
# ==========================

class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_number = db.Column(db.String(20), unique=True)
    status = db.Column(db.String(20), default="Available")
    owner = db.Column(db.String(100))
    cctv = db.Column(db.Boolean, default=False)
    lighting = db.Column(db.Boolean, default=False)
    near_entrance = db.Column(db.Boolean, default=False)
    safety_score = db.Column(db.Integer, default=0)
    distance = db.Column(db.Integer)
    ai_score = db.Column(db.Integer)
    parking_area_id = db.Column(db.Integer, db.ForeignKey('parking_area.id'), nullable=True)


# ==========================
# PARKING RECORD TABLE
# ==========================

class ParkingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False)
    slot_number = db.Column(db.String(20), nullable=False)
    entry_time = db.Column(db.DateTime)
    exit_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="Inside")
    parking_fee = db.Column(db.Integer, default=0)


# ==========================
# VEHICLE LOCATION TABLE
# ==========================

class VehicleLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100))
    vehicle_number = db.Column(db.String(30))
    slot_number = db.Column(db.String(20))
    zone = db.Column(db.String(30))
    floor = db.Column(db.String(30))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    parking_time = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="Parked")


# ==========================
# NOTIFICATION TABLE
# ==========================

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100))
    title = db.Column(db.String(100))
    message = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default="Unread")


# ==========================
# CORPORATION NOTIFICATION TABLE
# ==========================

class CorporationNotification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False)
    slot_number = db.Column(db.String(20), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(30), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.now)


# ==========================
# THEFT ALERT TABLE
# ==========================

class TheftAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100))
    vehicle_number = db.Column(db.String(30))
    slot_number = db.Column(db.String(20))
    alert_message = db.Column(db.String(300))
    alert_time = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(30), default="Pending")


# ==========================
# CREATE DATABASE TABLES
# ==========================

PARKING_SLOT_DEFINITIONS = [
    ("A1", 10, 95, True, True, True, 98),
    ("A2", 20, 90, True, True, False, 90),
    ("A3", 30, 85, False, True, False, 75),
    ("B1", 40, 80, False, False, False, 45),
    ("B2", 50, 75, True, False, False, 60),
    ("B3", 60, 70, False, True, True, 80),
]


def ensure_parking_slots():
    """Create default parking slots if they do not already exist."""
    for slot_number, distance, ai_score, cctv, lighting, near_entrance, safety_score in PARKING_SLOT_DEFINITIONS:
        slot = ParkingSlot.query.filter_by(slot_number=slot_number).first()
        if slot is None:
            db.session.add(
                ParkingSlot(
                    slot_number=slot_number,
                    status="Available",
                    owner="",
                    distance=distance,
                    ai_score=ai_score,
                    cctv=cctv,
                    lighting=lighting,
                    near_entrance=near_entrance,
                    safety_score=safety_score,
                )
            )
    db.session.commit()


def ensure_parking_areas():
    """Create sample parking areas and assign slots if they do not already exist."""
    
    # Create sample parking areas
    parking_areas_data = [
        {
            'name': 'CBT Parking',
            'area_name': 'CBT Area',
            'address': 'Central Business Terminal, Belagavi',
            'city': 'Belagavi',
            'state': 'Karnataka',
            'latitude': 15.8497,
            'longitude': 74.4977,
            'total_slots': 40,
            'status': 'Active',
            'description': 'Premium parking near Central Business Terminal with 24/7 security and CCTV surveillance.',
            'opening_time': '06:00',
            'closing_time': '22:00',
            'parking_type': 'Public'
        },
        {
            'name': 'Central Bus Stand Parking',
            'area_name': 'Bus Stand Area',
            'address': 'KSRTC Bus Stand, Belagavi',
            'city': 'Belagavi',
            'state': 'Karnataka',
            'latitude': 15.8520,
            'longitude': 74.5000,
            'total_slots': 30,
            'status': 'Active',
            'description': 'Convenient parking for bus travelers with easy access to main bus terminal.',
            'opening_time': '05:00',
            'closing_time': '23:00',
            'parking_type': 'Public'
        },
        {
            'name': 'Market Area Parking',
            'area_name': 'Market Area',
            'address': 'Bogarves Market, Belagavi',
            'city': 'Belagavi',
            'state': 'Karnataka',
            'latitude': 15.8470,
            'longitude': 74.4950,
            'total_slots': 25,
            'status': 'Active',
            'description': 'Affordable parking near main market area, ideal for shoppers and traders.',
            'opening_time': '08:00',
            'closing_time': '21:00',
            'parking_type': 'Public'
        },
        {
            'name': 'Railway Station Parking',
            'area_name': 'Railway Station Area',
            'address': 'Belagavi Railway Station, Belagavi',
            'city': 'Belagavi',
            'state': 'Karnataka',
            'latitude': 15.8450,
            'longitude': 74.4920,
            'total_slots': 35,
            'status': 'Active',
            'description': 'Secure parking for railway passengers with 24-hour access and security.',
            'opening_time': '24 Hours',
            'closing_time': '24 Hours',
            'parking_type': 'Public'
        },
        {
            'name': 'College Area Parking',
            'area_name': 'College Area',
            'address': 'Gogte College Circle, Belagavi',
            'city': 'Belagavi',
            'state': 'Karnataka',
            'latitude': 15.8510,
            'longitude': 74.5020,
            'total_slots': 20,
            'status': 'Active',
            'description': 'Student-friendly parking near major educational institutions with affordable rates.',
            'opening_time': '07:00',
            'closing_time': '20:00',
            'parking_type': 'Public'
        }
    ]
    
    area_id_mapping = {}
    
    # Insert parking areas
    for area in parking_areas_data:
        existing_area = ParkingArea.query.filter_by(name=area['name']).first()
        if not existing_area:
            new_area = ParkingArea(
                name=area['name'],
                area_name=area['area_name'],
                address=area['address'],
                city=area['city'],
                state=area['state'],
                latitude=area['latitude'],
                longitude=area['longitude'],
                total_slots=area['total_slots'],
                available_slots=area['total_slots'],
                occupied_slots=0,
                status=area['status'],
                description=area['description'],
                opening_time=area['opening_time'],
                closing_time=area['closing_time'],
                parking_type=area['parking_type']
            )
            db.session.add(new_area)
            db.session.flush()  # Get the ID without committing
            area_id_mapping[area['name']] = new_area.id
            print(f"[SUCCESS] Created parking area: {area['name']} (ID: {new_area.id})")
        else:
            area_id_mapping[area['name']] = existing_area.id
            print(f"[EXISTS] Parking area already exists: {area['name']}")
    
    db.session.commit()
    
    # Define slot configurations for each parking area
    slot_configurations = {
        'CBT Parking': {
            'prefix': 'A',
            'count': 40,
            'existing_slots': ['A1', 'A2', 'A3']  # Existing slots to reassign
        },
        'Central Bus Stand Parking': {
            'prefix': 'B',
            'count': 30,
            'existing_slots': ['B1', 'B2', 'B3']  # Existing slots to reassign
        },
        'Market Area Parking': {
            'prefix': 'M',
            'count': 25,
            'existing_slots': []
        },
        'Railway Station Parking': {
            'prefix': 'R',
            'count': 35,
            'existing_slots': []
        },
        'College Area Parking': {
            'prefix': 'C',
            'count': 20,
            'existing_slots': []
        }
    }
    
    # Process each parking area's slots
    for area_name, config in slot_configurations.items():
        area_id = area_id_mapping.get(area_name)
        if not area_id:
            print(f"[WARNING] Could not find area ID for {area_name}")
            continue
        
        # Reassign existing slots to this area
        for existing_slot in config['existing_slots']:
            slot = ParkingSlot.query.filter_by(slot_number=existing_slot).first()
            if slot:
                slot.parking_area_id = area_id
                print(f"[UPDATE] Reassigned slot {existing_slot} to {area_name}")
        
        # Create new slots for this area
        prefix = config['prefix']
        count = config['count']
        existing_count = len(config['existing_slots'])
        
        for i in range(existing_count + 1, count + 1):
            slot_number = f"{prefix}{i}"
            
            # Check if slot already exists
            existing_slot = ParkingSlot.query.filter_by(slot_number=slot_number).first()
            if existing_slot:
                print(f"[SKIP] Slot {slot_number} already exists, skipping")
                continue
            
            # Generate slot features
            distance = (i * 10) % 100 + 10  # 10-100 meters
            ai_score = 95 - (i % 30)  # High scores
            cctv = i % 3 == 0  # Every 3rd slot has CCTV
            lighting = i % 2 == 0  # Every 2nd slot has lighting
            near_entrance = i <= 5  # First 5 slots near entrance
            safety_score = ai_score + (5 if cctv else 0) + (3 if lighting else 0)
            
            new_slot = ParkingSlot(
                slot_number=slot_number,
                status='Available',
                owner='',
                cctv=cctv,
                lighting=lighting,
                near_entrance=near_entrance,
                safety_score=safety_score,
                distance=distance,
                ai_score=ai_score,
                parking_area_id=area_id
            )
            db.session.add(new_slot)
            print(f"[CREATE] Created slot {slot_number} in {area_name}")
    
    db.session.commit()
    
    # Update parking area statistics
    for area_name, area_id in area_id_mapping.items():
        total_slots = ParkingSlot.query.filter_by(parking_area_id=area_id).count()
        available_slots = ParkingSlot.query.filter_by(parking_area_id=area_id, status='Available').count()
        occupied_slots = ParkingSlot.query.filter_by(parking_area_id=area_id, status='Occupied').count()
        
        area = db.session.get(ParkingArea, area_id)
        if area:
            area.total_slots = total_slots
            area.available_slots = available_slots
            area.occupied_slots = occupied_slots
            print(f"[STATS] Updated {area_name} stats: {total_slots} total, {available_slots} available, {occupied_slots} occupied")
    
    db.session.commit()
    print("[SUCCESS] Parking areas migration completed!")


with app.app_context():
    db.create_all()
    ensure_parking_slots()
    ensure_parking_areas()
print("Database tables created successfully")


# ==========================
# HOME PAGE
# ==========================

@app.route("/")
def home():
    return redirect(url_for("register"))


# ==========================
# REGISTER
# ==========================

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def register():
    if request.method == "POST":
        # Sanitize and validate inputs
        name = sanitize_input(request.form.get("name", "").strip())
        email = sanitize_input(request.form.get("email", "").strip().lower())
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        phone = sanitize_input(request.form.get("phone", "").strip())

        # Validate inputs
        if not name or len(name) < 3:
            return render_template("register.html", error="Name must be at least 3 characters long.")
        
        if not validate_email(email):
            return render_template("register.html", error="Invalid email format.")
        
        if phone and not validate_phone(phone):
            return render_template("register.html", error="Phone number must be 10 digits.")
        
        # Validate password strength
        is_valid, password_msg = validate_password_strength(password)
        if not is_valid:
            return render_template("register.html", error=password_msg)
        
        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match.")

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            return render_template(
                "register.html",
                error="This email is already registered. Please login instead.",
            )

        new_user = User(name=name, email=email, phone=phone if phone else None)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        session["user"] = new_user.name
        session["email"] = new_user.email

        return redirect(url_for("dashboard"))

    return render_template("register.html")


# ==========================
# LOGIN
# ==========================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("50 per hour")
def login():

    if request.method == "POST":

        # ==========================
        # GET LOGIN DETAILS
        # ==========================

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        print("LOGIN ATTEMPT:", email)

        # ==========================
        # VALIDATE INPUT
        # ==========================

        if not email or not password:
            return render_template(
                "login.html",
                error="Please enter email and password."
            )

        # ==========================
        # FIND USER
        # ==========================

        user = User.query.filter_by(email=email).first()

        if user is None:

            print("USER NOT FOUND:", email)

            return render_template(
                "login.html",
                error="Invalid email or password."
            )

        print("USER FOUND:", user.email)
        print("USER NAME:", user.name)
        print("ADMIN:", user.is_admin)

        # ==========================
        # CHECK ACCOUNT LOCK
        # ==========================

        if user.account_locked:

            return render_template(
                "login.html",
                error="Account is locked. Please unlock your account."
            )

        # ==========================
        # CHECK PASSWORD
        # ==========================

        if not user.check_password(password):

            print("PASSWORD INCORRECT")

            user.failed_login_attempts += 1

            # Lock account after 5 failed attempts
            if user.failed_login_attempts >= 5:

                user.account_locked = True
                db.session.commit()

                return render_template(
                    "login.html",
                    error="Too many failed attempts. Your account has been locked."
                )

            db.session.commit()

            return render_template(
                "login.html",
                error="Invalid email or password."
            )

        # ==========================
        # SUCCESSFUL LOGIN
        # ==========================

        user.failed_login_attempts = 0
        db.session.commit()

        # IMPORTANT:
        # Remove any previous user's session
        session.clear()

        # Store ONLY the CURRENT logged-in user's details
        session["user_id"] = user.id
        session["email"] = user.email
        session["username"] = user.name

        # Optional: store admin status
        session["is_admin"] = bool(user.is_admin)

        print("================================")
        print("LOGIN SUCCESS")
        print("USER ID:", user.id)
        print("USER NAME:", user.name)
        print("USER EMAIL:", user.email)
        print("ADMIN:", user.is_admin)
        print("SESSION USER ID:", session["user_id"])
        print("SESSION EMAIL:", session["email"])
        print("SESSION USERNAME:", session["username"])
        print("================================")

        # ==========================
        # REDIRECT USER
        # ==========================

        if user.is_admin:
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("dashboard"))

    # ==========================
    # OPEN LOGIN PAGE
    # ==========================

    return render_template("login.html")
# ==========================
# SECURITY DECORATORS
# ==========================

@app.before_request
def apply_security_headers():
    """Apply security headers to all requests"""
    if request.endpoint:
        # Skip security headers for static files
        if not request.endpoint.startswith('static'):
            pass  # Headers will be added via after_request

@app.after_request
def apply_headers(response):
    """Apply security headers after request"""
    if not request.path.startswith('/static'):
        response = add_security_headers(response)
    return response

# ==========================
# DASHBOARD
# ==========================

@app.route("/dashboard")
def dashboard():
    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("register"))

    vehicles = Vehicle.query.filter_by(owner=user.name).all()
    my_slot = ParkingSlot.query.filter_by(owner=user.name).first()
    records = ParkingRecord.query.filter_by(owner=user.name).order_by(ParkingRecord.id.desc()).all()
    recommended_slot = ParkingSlot.query.filter_by(status="Available").order_by(ParkingSlot.ai_score.desc()).first()
    vehicle_location = VehicleLocation.query.filter_by(owner=user.name, status="Parked").first()
    notifications = Notification.query.filter_by(owner=user.name).order_by(Notification.created_at.desc()).all()
    theft_alerts = TheftAlert.query.filter_by(owner=user.name).order_by(TheftAlert.alert_time.desc()).all()
    corporation_request = CorporationNotification.query.filter_by(owner=user.name).order_by(CorporationNotification.created_at.desc()).first()
    parking_areas = ParkingArea.query.filter_by(status="Active").all()

    return render_template(
        "dashboard.html",
        username=user.name,
        vehicles=vehicles,
        my_slot=my_slot,
        records=records,
        recommended_slot=recommended_slot,
        vehicle_location=vehicle_location,
        notifications=notifications,
        theft_alerts=theft_alerts,
        corporation_request=corporation_request,
        parking_areas=parking_areas
    )


# ==========================
# ADD VEHICLE
# ==========================

@app.route("/add_vehicle", methods=["GET", "POST"])
def add_vehicle():
    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("register"))

    if request.method == "POST":
        vehicle_number = sanitize_input(request.form.get("vehicle_number", "").strip().upper())
        vehicle_type = sanitize_input(request.form.get("vehicle_type", ""))
        color = sanitize_input(request.form.get("color", "").strip())

        # Validate inputs
        if not vehicle_number or len(vehicle_number) < 5:
            return "Invalid vehicle number format."
        
        if not vehicle_type:
            return "Vehicle type is required."
        
        if not color or len(color) < 2:
            return "Invalid color format."

        existing_vehicle = Vehicle.query.filter_by(vehicle_number=vehicle_number).first()

        if existing_vehicle:
            return "Vehicle already registered!"

        vehicle = Vehicle(
            owner=user.name,
            vehicle_number=vehicle_number,
            vehicle_type=vehicle_type,
            color=color
        )

        db.session.add(vehicle)
        db.session.commit()

        return redirect(url_for("dashboard"))

    return render_template("add_vehicle.html")


# ==========================
# LOGOUT
# ==========================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("register"))


# ==========================
# CREATE SMART PARKING SLOTS
# ==========================

@app.route("/create_slots")
def create_slots():
    ensure_parking_slots()
    return "Parking Slots Created Successfully"


# ==========================
# BOOK SLOT PAGE
# ==========================

@app.route("/book_slot")
def book_slot():
    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("register"))

    vehicles = Vehicle.query.filter_by(owner=user.name).all()
    slots = ParkingSlot.query.order_by(ParkingSlot.slot_number).all()
    recommended_slot = ParkingSlot.query.filter_by(status="Available").order_by(
        ParkingSlot.ai_score.desc()
    ).first()

    return render_template(
        "book_slot.html",
        username=user.name,
        vehicles=vehicles,
        slots=slots,
        recommended_slot=recommended_slot,
        sensor=None,
    )


# ==========================
# BOOK PARKING SLOT
# SEND REQUEST TO CORPORATION
# ==========================

@app.route("/book_slot/<slot_number>", methods=["POST"])
def book_parking(slot_number):
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("login"))

    vehicle = Vehicle.query.filter_by(owner=user.name).first()
    if not vehicle:
        return "No vehicle found. Please add a vehicle first."

    slot = ParkingSlot.query.filter_by(slot_number=slot_number).first()
    if not slot:
        return "Parking slot not found."

    if slot.status == "Occupied":
        return "This parking slot is already occupied."

    corporation_request = CorporationNotification(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        slot_number=slot.slot_number,
        message=(
            f"🚗 Parking request from {user.name}. "
            f"Vehicle {vehicle.vehicle_number} "
            f"has requested Slot {slot.slot_number}. "
            f"Please review and approve the parking request."
        ),
        status="Pending"
    )
    db.session.add(corporation_request)

    owner_notification = Notification(
        owner=user.name,
        title="🅿 Parking Request Sent",
        message=(
            f"Your request for Slot {slot.slot_number} "
            f"has been sent to the Corporation. "
            f"Please wait for approval."
        ),
        status="Unread"
    )
    db.session.add(owner_notification)

    # Mark slot as occupied immediately upon booking
    slot.status = "Occupied"
    slot.owner = user.name

    db.session.commit()
    
    # Notify real-time server of parking update
    notify_realtime_server()

    return redirect(url_for("dashboard"))


# ==========================
# GENERATE QR CODE
# ==========================

@app.route("/generate_qr/<int:id>")
def generate_qr(id):
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    slot = ParkingSlot.query.get_or_404(id)

    # User can generate QR only for their own slot
    if slot.owner != user.name:
        return "Not Allowed"

    # Check corporation approval
    approved_request = CorporationNotification.query.filter_by(
        owner=user.name,
        slot_number=slot.slot_number,
        status="Approved"
    ).order_by(
        CorporationNotification.created_at.desc()
    ).first()

    if not approved_request:
        return """
        <h2>QR Code Not Available</h2>
        <p>Your parking request has not been approved by the Corporation yet.</p>
        <a href="/dashboard">Back to Dashboard</a>
        """

    location = VehicleLocation.query.filter_by(
        owner=user.name,
        slot_number=slot.slot_number,
        status="Parked"
    ).first()

    vehicle = Vehicle.query.filter_by(
        owner=user.name,
        vehicle_number=approved_request.vehicle_number
    ).first()

    vehicle_number = (
        vehicle.vehicle_number
        if vehicle
        else approved_request.vehicle_number
    )

    qr_data = f"""
Smart Parking Management System

Owner: {user.name}
Vehicle Number: {vehicle_number}
Parking Slot: {slot.slot_number}
Approval Status: Approved
Generated: {datetime.now()}
"""

    folder = os.path.join("static", "qrcodes")

    if not os.path.exists(folder):
        os.makedirs(folder)

    filename = slot.slot_number + ".png"
    path = os.path.join(folder, filename)

    img = qrcode.make(qr_data)
    img.save(path)

    return render_template(
        "qr_code.html",
        filename=filename,
        owner=user.name,
        vehicle_number=vehicle_number,
        slot_number=slot.slot_number,
        status="Approved",
        entry_time=location.parking_time if location else "Not Available"
    )
# ==========================
# VEHICLE ENTRY
# ==========================

@app.route("/entry/<int:id>")
def entry(id):
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    slot = ParkingSlot.query.get_or_404(id)

    # Check whether this slot belongs to the logged-in user
    if slot.owner != user.name:
        return "You are not authorized to use this parking slot."

    # Check corporation approval
    approved_request = CorporationNotification.query.filter_by(
        owner=user.name,
        slot_number=slot.slot_number,
        status="Approved"
    ).order_by(
        CorporationNotification.created_at.desc()
    ).first()

    if not approved_request:
        return """
        <h2>Entry Not Allowed</h2>
        <p>Your parking request has not been approved by the Corporation.</p>
        <a href="/dashboard">Back to Dashboard</a>
        """

    # Find approved vehicle
    vehicle = Vehicle.query.filter_by(
        owner=user.name,
        vehicle_number=approved_request.vehicle_number
    ).first()

    if vehicle is None:
        return "Approved vehicle was not found."

    # Prevent duplicate active parking records
    existing_record = ParkingRecord.query.filter_by(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        status="Inside"
    ).first()

    if existing_record:
        return "This vehicle is already inside the parking area."

    # Create parking record
    record = ParkingRecord(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        slot_number=slot.slot_number,
        entry_time=datetime.now(),
        status="Inside"
    )

    db.session.add(record)

    # Create vehicle location
    location = VehicleLocation(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        slot_number=slot.slot_number,
        zone="Zone A",
        floor="Ground Floor",
        latitude=ENTRANCE_LAT,
        longitude=ENTRANCE_LNG,
        parking_time=datetime.now(),
        status="Parked"
    )

    db.session.add(location)

    # Ensure slot remains occupied
    slot.status = "Occupied"
    slot.owner = user.name

    # Notification
    notification = Notification(
        owner=user.name,
        title="🚗 Vehicle Entry Successful",
        message=(
            f"Vehicle {vehicle.vehicle_number} entered successfully "
            f"and is parked in Slot {slot.slot_number}."
        ),
        status="Unread"
    )

    db.session.add(notification)
    db.session.commit()
    
    # Notify real-time server of parking update
    notify_realtime_server()

    return redirect(url_for("dashboard"))
# ==========================
# VEHICLE EXIT
# ==========================

@app.route("/exit/<int:id>")
def exit(id):
    if "email" not in session:
        return redirect(url_for("login"))

    record = ParkingRecord.query.get_or_404(id)

    record.exit_time = datetime.now()
    record.status = "Exited"

    minutes = (record.exit_time - record.entry_time).seconds // 60
    fee = max(minutes * 2, 20)
    record.parking_fee = fee

    slot = ParkingSlot.query.filter_by(slot_number=record.slot_number).first()
    if slot:
        slot.status = "Available"
        slot.owner = ""

    location = VehicleLocation.query.filter_by(
        vehicle_number=record.vehicle_number,
        owner=record.owner,
        status="Parked"
    ).first()

    if location:
        location.status = "Exited"

    notification = Notification(
        owner=record.owner,
        title="Vehicle Exit",
        message=f"{record.vehicle_number} exited successfully. Parking Fee ₹{fee}"
    )
    db.session.add(notification)

    theft_alert = TheftAlert(
        owner=record.owner,
        vehicle_number=record.vehicle_number,
        slot_number=record.slot_number,
        alert_message="Vehicle exited successfully. No theft detected.",
        status="Safe"
    )
    db.session.add(theft_alert)

    db.session.commit()

    # --- TWILIO SMS NOTIFICATION ON EXIT ---
    sms_msg = f"🚗 SmartParking Alert: Vehicle {record.vehicle_number} exited Slot {record.slot_number}. Total Parking Fee: ₹{fee}."
    send_sms(OWNER_PHONE_NUMBER, sms_msg)
    
    # Notify real-time server of parking update
    notify_realtime_server()

    return redirect(url_for("dashboard"))


# ==========================
# VEHICLE ENTRY (NEW)
# ==========================

@app.route("/vehicle_entry", methods=["GET", "POST"])
def vehicle_entry():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    
    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number", "").strip().upper()
        vehicle_type = request.form.get("vehicle_type", "Car")
        slot_number = request.form.get("slot_number", "").strip()
        
        # Validate inputs
        if not vehicle_number:
            return render_template("vehicle_entry.html", error="Vehicle number is required", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        
        # Check if vehicle exists for this user
        vehicle = Vehicle.query.filter_by(owner=user.name, vehicle_number=vehicle_number).first()
        if not vehicle:
            return render_template("vehicle_entry.html", error="Vehicle not found. Please add your vehicle first.", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        
        # Get parking slot
        if not slot_number:
            # Auto-assign an available slot
            slot = ParkingSlot.query.filter_by(status="Available").first()
            if not slot:
                return render_template("vehicle_entry.html", error="No available parking slots.", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        else:
            slot = ParkingSlot.query.filter_by(slot_number=slot_number, status="Available").first()
            if not slot:
                return render_template("vehicle_entry.html", error="Selected slot is not available.", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        
        # Check for corporation approval
        approved_request = CorporationNotification.query.filter_by(
            owner=user.name,
            slot_number=slot.slot_number,
            status="Approved"
        ).order_by(
            CorporationNotification.created_at.desc()
        ).first()
        
        if not approved_request:
            return render_template("vehicle_entry.html", error="Your parking request for this slot has not been approved by the Corporation.", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        
        # Prevent duplicate active parking records
        existing_record = ParkingRecord.query.filter_by(
            owner=user.name,
            vehicle_number=vehicle.vehicle_number,
            status="Inside"
        ).first()
        
        if existing_record:
            return render_template("vehicle_entry.html", error="This vehicle is already inside the parking area.", vehicles=Vehicle.query.filter_by(owner=user.name).all(), available_slots=ParkingSlot.query.filter_by(status="Available").all())
        
        # Create parking record
        record = ParkingRecord(
            owner=user.name,
            vehicle_number=vehicle.vehicle_number,
            slot_number=slot.slot_number,
            entry_time=datetime.now(),
            status="Inside"
        )
        
        db.session.add(record)
        
        # Create vehicle location
        location = VehicleLocation(
            owner=user.name,
            vehicle_number=vehicle.vehicle_number,
            slot_number=slot.slot_number,
            zone="Zone A",
            floor="Ground Floor",
            latitude=ENTRANCE_LAT,
            longitude=ENTRANCE_LNG,
            parking_time=datetime.now(),
            status="Parked"
        )
        
        db.session.add(location)
        
        # Slot is already marked as occupied during booking, no need to set again
        # slot.status = "Occupied"
        # slot.owner = user.name
        
        # Create notification
        notification = Notification(
            owner=user.name,
            title="🚗 Vehicle Entry Successful",
            message=(
                f"Vehicle {vehicle.vehicle_number} entered successfully "
                f"and is parked in Slot {slot.slot_number}."
            ),
            status="Unread"
        )
        
        db.session.add(notification)
        db.session.commit()
        
        # Notify real-time server of parking update
        notify_realtime_server()
        
        return redirect(url_for("dashboard"))
    
    # GET request - show form
    vehicles = Vehicle.query.filter_by(owner=user.name).all()
    available_slots = ParkingSlot.query.filter_by(status="Available").all()
    
    return render_template("vehicle_entry.html", vehicles=vehicles, available_slots=available_slots)


# ==========================
# VEHICLE EXIT (NEW)
# ==========================

@app.route("/vehicle_exit", methods=["GET", "POST"])
def vehicle_exit():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    
    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number", "").strip().upper()
        
        # Validate input
        if not vehicle_number:
            return render_template("vehicle_exit.html", error="Vehicle number is required", vehicles=Vehicle.query.filter_by(owner=user.name).all())
        
        # Find active parking record
        record = ParkingRecord.query.filter_by(
            owner=user.name,
            vehicle_number=vehicle_number,
            status="Inside"
        ).first()
        
        if not record:
            return render_template("vehicle_exit.html", error="No active parking record found for this vehicle.", vehicles=Vehicle.query.filter_by(owner=user.name).all())
        
        # Calculate parking duration and fee
        exit_time = datetime.now()
        entry_time = record.entry_time
        duration = exit_time - entry_time
        total_minutes = int(duration.total_seconds() / 60)
        fee = max(total_minutes * 2, 20)  # ₹2 per minute, minimum ₹20
        
        # Update parking record
        record.exit_time = exit_time
        record.status = "Exited"
        record.parking_fee = fee
        
        # Mark slot as available
        slot = ParkingSlot.query.filter_by(slot_number=record.slot_number).first()
        if slot:
            slot.status = "Available"
            slot.owner = ""
        
        # Update vehicle location
        location = VehicleLocation.query.filter_by(
            vehicle_number=record.vehicle_number,
            owner=record.owner,
            status="Parked"
        ).first()
        
        if location:
            location.status = "Exited"
        
        # Create notification
        notification = Notification(
            owner=record.owner,
            title="Vehicle Exit",
            message=f"{record.vehicle_number} exited successfully. Parking Fee ₹{fee}",
            status="Unread"
        )
        db.session.add(notification)
        
        # Create theft alert
        theft_alert = TheftAlert(
            owner=record.owner,
            vehicle_number=record.vehicle_number,
            slot_number=record.slot_number,
            alert_message="Vehicle exited successfully. No theft detected.",
            status="Safe"
        )
        db.session.add(theft_alert)
        
        db.session.commit()
        
        # Send SMS notification
        sms_msg = f"🚗 SmartParking Alert: Vehicle {record.vehicle_number} exited Slot {record.slot_number}. Total Parking Fee: ₹{fee}."
        send_sms(OWNER_PHONE_NUMBER, sms_msg)
        
        # Notify real-time server of parking update
        notify_realtime_server()
        
        # Show exit summary
        return render_template("vehicle_exit_summary.html", 
                              record=record, 
                              duration=duration, 
                              total_minutes=total_minutes, 
                              fee=fee)
    
    # GET request - show form
    vehicles = Vehicle.query.filter_by(owner=user.name).all()
    
    return render_template("vehicle_exit.html", vehicles=vehicles)


# ==========================
# FIND MY VEHICLE
# ==========================

@app.route("/find_vehicle")
def find_vehicle():
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    vehicle = Vehicle.query.filter_by(owner=user.name).first()

    if not vehicle:
        return render_template(
            "find_vehicle.html",
            username=user.name,
            vehicle=None,
            vehicle_location=None,
            notifications=[]
        )

    vehicle_location = VehicleLocation.query.filter_by(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        status="Parked"
    ).first()

    notifications = Notification.query.filter_by(
        owner=user.name
    ).order_by(Notification.created_at.desc()).limit(5).all()

    return render_template(
        "find_vehicle.html",
        username=user.name,
        vehicle=vehicle,
        vehicle_location=vehicle_location,
        notifications=notifications
    )


# ==========================
# THEFT ALERT (TRIGGERS EMERGENCY SMS)
# ==========================

@app.route("/theft_alert/<int:record_id>")
def theft_alert(record_id):
    if "email" not in session:
        return redirect(url_for("register"))

    record = ParkingRecord.query.get_or_404(record_id)

    alert_text = f"🚨 SECURITY ALERT: Possible theft detected for vehicle {record.vehicle_number} parked in Slot {record.slot_number}!"

    alert = TheftAlert(
        owner=record.owner,
        vehicle_number=record.vehicle_number,
        slot_number=record.slot_number,
        alert_message=alert_text,
        status="Pending"
    )
    db.session.add(alert)

    notification = Notification(
        owner=record.owner,
        title="Vehicle Theft Alert",
        message=f"Emergency! Possible theft detected for vehicle {record.vehicle_number}."
    )
    db.session.add(notification)

    db.session.commit()

    # --- TWILIO SMS NOTIFICATION FOR THEFT ---
    send_sms(OWNER_PHONE_NUMBER, alert_text)

    return redirect(url_for("view_theft_alerts"))


# ==========================
# VIEW THEFT ALERTS
# ==========================

@app.route("/theft_alerts")
def view_theft_alerts():
    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(email=session["email"]).first()

    alerts = TheftAlert.query.filter_by(owner=user.name).order_by(TheftAlert.alert_time.desc()).all()

    return render_template(
        "theft_alerts.html",
        username=user.name,
        alerts=alerts
    )


# ==========================
# NOTIFICATIONS
# ==========================

@app.route("/notifications")
def notifications():
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("login"))

    user_notifications = Notification.query.filter_by(owner=user.name).order_by(
        Notification.created_at.desc()
    ).all()
    theft_alerts = TheftAlert.query.filter_by(owner=user.name).order_by(
        TheftAlert.alert_time.desc()
    ).all()
    vehicles = Vehicle.query.filter_by(owner=user.name).all()

    return render_template(
        "notifications.html",
        notifications=user_notifications,
        theft_alerts=theft_alerts,
        vehicles=vehicles,
    )


# ==========================
# FIND PARKING
# ==========================

@app.route("/find_parking")
def find_parking():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    
    # Get all parking areas with their slot information
    parking_areas = ParkingArea.query.filter_by(status="Active").all()
    
    # Calculate availability for each parking area
    areas_data = []
    for area in parking_areas:
        total_slots = ParkingSlot.query.filter_by(parking_area_id=area.id).count()
        available_slots = ParkingSlot.query.filter_by(
            parking_area_id=area.id, 
            status="Available"
        ).count()
        occupied_slots = total_slots - available_slots
        
        # Calculate distance from user (simplified - in real app would use actual geolocation)
        user_distance = getattr(area, 'distance', 1.0)  # Placeholder for actual distance calculation
        
        areas_data.append({
            'id': area.id,
            'name': area.name,
            'area_name': area.area_name,
            'address': area.address,
            'city': area.city,
            'latitude': area.latitude,
            'longitude': area.longitude,
            'total_slots': total_slots,
            'available_slots': available_slots,
            'occupied_slots': occupied_slots,
            'status': area.status,
            'description': area.description,
            'opening_time': area.opening_time,
            'closing_time': area.closing_time,
            'parking_type': area.parking_type,
            'distance': user_distance
        })
    
    return render_template("find_parking.html", 
                          username=user.name, 
                          parking_areas=areas_data)


# ==========================
# PARKING AREA MANAGEMENT (ADMIN)
# ==========================

@app.route("/admin/parking_areas")
def admin_parking_areas():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    parking_areas = ParkingArea.query.all()
    return render_template("parking_management.html", 
                          username=user.name, 
                          parking_areas=parking_areas)


@app.route("/admin/add_parking_area", methods=["GET", "POST"])
def add_parking_area():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    if request.method == "POST":
        name = sanitize_input(request.form.get("name", "").strip())
        area_name = sanitize_input(request.form.get("area_name", "").strip())
        address = sanitize_input(request.form.get("address", "").strip())
        city = sanitize_input(request.form.get("city", "Belagavi").strip())
        state = sanitize_input(request.form.get("state", "Karnataka").strip())
        latitude = float(request.form.get("latitude", 15.8497))
        longitude = float(request.form.get("longitude", 74.4977))
        total_slots = int(request.form.get("total_slots", 20))
        description = sanitize_input(request.form.get("description", "").strip())
        opening_time = sanitize_input(request.form.get("opening_time", "06:00").strip())
        closing_time = sanitize_input(request.form.get("closing_time", "22:00").strip())
        parking_type = sanitize_input(request.form.get("parking_type", "Public").strip())
        
        new_area = ParkingArea(
            name=name,
            area_name=area_name,
            address=address,
            city=city,
            state=state,
            latitude=latitude,
            longitude=longitude,
            total_slots=total_slots,
            available_slots=total_slots,
            occupied_slots=0,
            status="Active",
            description=description,
            opening_time=opening_time,
            closing_time=closing_time,
            parking_type=parking_type
        )
        
        db.session.add(new_area)
        db.session.commit()
        
        return redirect(url_for("admin_parking_areas"))
    
    return render_template("parking_management.html", 
                          username=user.name, 
                          editing=False)


@app.route("/admin/edit_parking_area/<int:area_id>", methods=["GET", "POST"])
def edit_parking_area(area_id):
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    area = ParkingArea.query.get_or_404(area_id)
    
    if request.method == "POST":
        area.name = sanitize_input(request.form.get("name", "").strip())
        area.area_name = sanitize_input(request.form.get("area_name", "").strip())
        area.address = sanitize_input(request.form.get("address", "").strip())
        area.city = sanitize_input(request.form.get("city", "Belagavi").strip())
        area.state = sanitize_input(request.form.get("state", "Karnataka").strip())
        area.latitude = float(request.form.get("latitude", 15.8497))
        area.longitude = float(request.form.get("longitude", 74.4977))
        area.description = sanitize_input(request.form.get("description", "").strip())
        area.opening_time = sanitize_input(request.form.get("opening_time", "06:00").strip())
        area.closing_time = sanitize_input(request.form.get("closing_time", "22:00").strip())
        area.parking_type = sanitize_input(request.form.get("parking_type", "Public").strip())
        
        db.session.commit()
        
        return redirect(url_for("admin_parking_areas"))
    
    return render_template("parking_management.html", 
                          username=user.name, 
                          area=area,
                          editing=True)


@app.route("/admin/delete_parking_area/<int:area_id>", methods=["POST"])
def delete_parking_area(area_id):
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    area = ParkingArea.query.get_or_404(area_id)
    
    # Check if area has any occupied slots
    occupied_slots = ParkingSlot.query.filter_by(
        parking_area_id=area_id, 
        status="Occupied"
    ).count()
    
    if occupied_slots > 0:
        return "Cannot delete parking area with occupied slots"
    
    # Delete all slots in this area
    ParkingSlot.query.filter_by(parking_area_id=area_id).delete()
    
    # Delete the area
    db.session.delete(area)
    db.session.commit()
    
    return redirect(url_for("admin_parking_areas"))


# ==========================
# ANALYTICS AND REPORTS
# ==========================

@app.route("/admin/analytics")
def admin_analytics():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    # Get analytics data
    total_users = User.query.count()
    total_vehicles = Vehicle.query.count()
    total_parking_areas = ParkingArea.query.count()
    total_slots = ParkingSlot.query.count()
    available_slots = ParkingSlot.query.filter_by(status="Available").count()
    occupied_slots = ParkingSlot.query.filter_by(status="Occupied").count()
    
    total_records = ParkingRecord.query.count()
    approved_requests = CorporationNotification.query.filter_by(status="Approved").count()
    rejected_requests = CorporationNotification.query.filter_by(status="Rejected").count()
    pending_requests = CorporationNotification.query.filter_by(status="Pending").count()
    
    # Parking area breakdown
    parking_areas = ParkingArea.query.all()
    area_stats = []
    for area in parking_areas:
        area_total = ParkingSlot.query.filter_by(parking_area_id=area.id).count()
        area_available = ParkingSlot.query.filter_by(parking_area_id=area.id, status="Available").count()
        area_occupied = ParkingSlot.query.filter_by(parking_area_id=area.id, status="Occupied").count()
        
        area_stats.append({
            'name': area.name,
            'total': area_total,
            'available': area_available,
            'occupied': area_occupied,
            'occupancy_rate': (area_occupied / area_total * 100) if area_total > 0 else 0
        })
    
    return render_template("analytics.html",
                          username=user.name,
                          total_users=total_users,
                          total_vehicles=total_vehicles,
                          total_parking_areas=total_parking_areas,
                          total_slots=total_slots,
                          available_slots=available_slots,
                          occupied_slots=occupied_slots,
                          total_records=total_records,
                          approved_requests=approved_requests,
                          rejected_requests=rejected_requests,
                          pending_requests=pending_requests,
                          area_stats=area_stats)


@app.route("/admin/reports")
def admin_reports():
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user or not user.is_admin:
        return "Access Denied"
    
    # Get comprehensive report data
    users = User.query.order_by(User.id.desc()).all()
    vehicles = Vehicle.query.order_by(Vehicle.id.desc()).all()
    parking_records = ParkingRecord.query.order_by(ParkingRecord.id.desc()).limit(50).all()
    parking_areas = ParkingArea.query.all()
    
    # Calculate statistics
    total_revenue = sum([record.parking_fee for record in parking_records if record.parking_fee])
    avg_parking_duration = 0  # Would need actual duration calculation
    
    return render_template("reports.html",
                          username=user.name,
                          users=users,
                          vehicles=vehicles,
                          parking_records=parking_records,
                          parking_areas=parking_areas,
                          total_revenue=total_revenue)


# ==========================
# DIGITAL PARKING PASS
# ==========================

@app.route("/parking_pass/<int:request_id>")
def parking_pass(request_id):
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    
    request_data = CorporationNotification.query.get_or_404(request_id)
    
    # Verify this request belongs to the user
    if request_data.owner != user.name:
        return "Access Denied"
    
    # Verify request is approved
    if request_data.status != "Approved":
        return "Parking request not approved"
    
    slot = ParkingSlot.query.filter_by(slot_number=request_data.slot_number).first()
    vehicle = Vehicle.query.filter_by(vehicle_number=request_data.vehicle_number).first()
    
    # Generate booking ID
    booking_id = f"SP-{request_id:06d}"
    
    return render_template("parking_pass.html",
                          username=user.name,
                          booking_id=booking_id,
                          request_data=request_data,
                          slot=slot,
                          vehicle=vehicle)


# ==========================
# PARKING DETAILS
# ==========================

@app.route("/parking_details/<int:area_id>")
def parking_details(area_id):
    if "email" not in session:
        return redirect(url_for("login"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    
    parking_area = ParkingArea.query.get_or_404(area_id)
    slots = ParkingSlot.query.filter_by(parking_area_id=area_id).order_by(ParkingSlot.slot_number).all()
    
    # Get user's vehicles
    vehicles = Vehicle.query.filter_by(owner=user.name).all()
    
    return render_template("parking_details.html",
                          username=user.name,
                          parking_area=parking_area,
                          slots=slots,
                          vehicles=vehicles)


# ==========================
# PARKING MAP
# ==========================

@app.route("/parking_map")
def parking_map():
    if "email" not in session:
        return redirect(url_for("login"))

    try:
        parking_areas = ParkingArea.query.filter_by(status="Active").all()

        areas_data = []

        for area in parking_areas:
            total_slots = ParkingSlot.query.filter_by(
                parking_area_id=area.id
            ).count()

            available_slots = ParkingSlot.query.filter_by(
                parking_area_id=area.id,
                status="Available"
            ).count()

            occupied_slots = total_slots - available_slots

            if total_slots == 0:
                marker_color = "gray"
            elif available_slots == 0:
                marker_color = "red"
            elif available_slots < total_slots * 0.30:
                marker_color = "orange"
            else:
                marker_color = "green"

            try:
                latitude = float(area.latitude)
            except:
                latitude = 15.8497

            try:
                longitude = float(area.longitude)
            except:
                longitude = 74.4977

            # Get detailed slot information with vehicle data
            slots_data = []
            slots = ParkingSlot.query.filter_by(parking_area_id=area.id).all()
            
            for slot in slots:
                vehicle_info = None
                if slot.status == "Occupied" and slot.owner:
                    vehicle = Vehicle.query.filter_by(owner=slot.owner).first()
                    if vehicle:
                        vehicle_info = {
                            "vehicle_number": vehicle.vehicle_number,
                            "vehicle_type": vehicle.vehicle_type,
                            "color": vehicle.color
                        }
                
                # Calculate slot position relative to parking area (spread slots around area)
                slot_index = slots.index(slot)
                offset = 0.0005  # ~50 meters
                slot_lat = latitude + (slot_index % 5) * offset
                slot_lng = longitude + (slot_index // 5) * offset
                
                slots_data.append({
                    "slot_number": slot.slot_number,
                    "status": slot.status,
                    "owner": slot.owner,
                    "vehicle_info": vehicle_info,
                    "lat": slot_lat,
                    "lng": slot_lng,
                    "cctv": slot.cctv,
                    "lighting": slot.lighting
                })

            areas_data.append({
                "id": int(area.id),
                "name": str(area.name or "Parking Area"),
                "area_name": str(area.area_name or ""),
                "address": str(area.address or "Belagavi"),
                "lat": latitude,
                "lng": longitude,
                "total_slots": int(total_slots),
                "available_slots": int(available_slots),
                "occupied_slots": int(occupied_slots),
                "marker_color": marker_color,
                "parking_type": str(area.parking_type or "Public"),
                "slots": slots_data
            })

        print("MAP DATA:", areas_data)

        return render_template(
            "parking_map.html",
            areas_data=areas_data
        )

    except Exception as e:
        print("PARKING MAP ERROR:", e)

        return f"""
        <h2>Parking Map Error</h2>
        <p>{str(e)}</p>
        """, 500

# ==========================
# AI RECOMMENDATION ENGINE
# ==========================

def calculate_parking_recommendation(user_lat=None, user_lng=None, vehicle_type=None):
    """
    AI-inspired parking recommendation engine
    Returns the best parking area and slot based on multiple factors
    """
    parking_areas = ParkingArea.query.filter_by(status="Active").all()
    
    if not parking_areas:
        return None, None
    
    best_area = None
    best_area_score = 0
    
    for area in parking_areas:
        # Calculate availability score
        total_slots = ParkingSlot.query.filter_by(parking_area_id=area.id).count()
        available_slots = ParkingSlot.query.filter_by(
            parking_area_id=area.id, 
            status="Available"
        ).count()
        
        if total_slots == 0:
            availability_score = 0
        else:
            availability_ratio = available_slots / total_slots
            availability_score = availability_ratio * 40  # Max 40 points for availability
        
        # Calculate distance score (if user location provided)
        if user_lat and user_lng and area.latitude and area.longitude:
            distance = ((user_lat - area.latitude)**2 + (user_lng - area.longitude)**2)**0.5
            # Convert to approximate km (simplified)
            distance_km = distance * 111  # Rough conversion
            distance_score = max(0, 30 - distance_km * 10)  # Max 30 points for proximity
        else:
            distance_score = 15  # Default mid score if no location
        
        # Calculate safety score based on available slots with CCTV
        cctv_slots = ParkingSlot.query.filter_by(
            parking_area_id=area.id, 
            cctv=True, 
            status="Available"
        ).count()
        safety_score = (cctv_slots / max(total_slots, 1)) * 30  # Max 30 points for safety
        
        # Total score
        total_score = availability_score + distance_score + safety_score
        
        if total_score > best_area_score:
            best_area_score = total_score
            best_area = area
    
    # Find best slot in the best area
    if best_area:
        available_slots = ParkingSlot.query.filter_by(
            parking_area_id=best_area.id, 
            status="Available"
        ).all()
        
        if available_slots:
            # Sort by AI score, then by safety features
            best_slot = max(available_slots, key=lambda s: (s.ai_score or 0) + (10 if s.cctv else 0) + (5 if s.lighting else 0))
            return best_area, best_slot
    
    return best_area, None


# ==========================
# AI ASSISTANT API
# ==========================

@app.route("/api/ai_assistant", methods=["POST"])
@csrf.exempt  # Exempt CSRF for API endpoint used by AJAX
def ai_assistant():
    data = request.get_json() or {}
    user_query = data.get("query", "").lower().strip()

    if not user_query:
        return jsonify({"reply": "How can I help you? Ask me to find a slot or locate your car.", "target_slot": None})

    slots = ParkingSlot.query.all()

    occupied_slots = [s for s in slots if s.status == "Occupied"]
    for slot in occupied_slots:
        veh = Vehicle.query.filter_by(owner=slot.owner).first()
        veh_num = veh.vehicle_number.lower().replace("-", "").replace(" ", "") if veh else ""
        owner_name = slot.owner.lower() if slot.owner else ""
        clean_query = user_query.replace("-", "").replace(" ", "")

        if (veh_num and veh_num in clean_query) or (owner_name and owner_name in user_query):
            return jsonify({
                "reply": f"Found vehicle! Vehicle {veh.vehicle_number if veh else 'N/A'} (Owner: {slot.owner}) is parked in Slot {slot.slot_number}.",
                "target_slot": str(slot.slot_number)
            })

    available_slots = [s for s in slots if s.status == "Available"]

    if not available_slots:
        return jsonify({"reply": "Sorry, all parking slots are currently occupied.", "target_slot": None})

    # Enhanced AI assistant with parking area support
    if any(w in user_query for w in ["parking area", "which parking", "best parking", "recommend parking", "where should i park"]):
        best_area, best_slot = calculate_parking_recommendation()
        if best_area:
            return jsonify({
                "reply": f"Recommended parking area: {best_area.name} ({best_area.address}). {best_area.description}",
                "target_area": best_area.name,
                "target_slot": best_slot.slot_number if best_slot else None
            })
        else:
            return jsonify({"reply": "No parking areas available at the moment.", "target_slot": None})

    if any(w in user_query for w in ["close", "closest", "near", "entrance", "gate"]):
        best_slot = available_slots[0]
        return jsonify({
            "reply": f"Slot {best_slot.slot_number} is the closest available slot to the main gate entrance.",
            "target_slot": str(best_slot.slot_number)
        })

    if any(w in user_query for w in ["cheap", "cheapest", "lowest", "budget", "price"]):
        best_slot = min(available_slots, key=lambda s: getattr(s, 'price', 50))
        price_val = getattr(best_slot, 'price', 40)
        return jsonify({
            "reply": f"Slot {best_slot.slot_number} is the most affordable option at ₹{price_val}/hr.",
            "target_slot": str(best_slot.slot_number)
        })

    if any(w in user_query for w in ["cctv", "camera", "safe", "security", "monitored"]):
        cctv_slots = [s for s in available_slots if s.cctv]
        if cctv_slots:
            best_slot = max(cctv_slots, key=lambda s: s.ai_score or 0)
            return jsonify({
                "reply": f"Slot {best_slot.slot_number} is equipped with 24/7 CCTV monitoring (Safety Score: {best_slot.ai_score or 90}/100).",
                "target_slot": str(best_slot.slot_number)
            })

    best_slot = max(available_slots, key=lambda s: s.ai_score or 0)
    return jsonify({
        "reply": f"Recommended Slot {best_slot.slot_number} (AI Score: {best_slot.ai_score or 85}/100, CCTV: {'Yes' if best_slot.cctv else 'No'}).",
        "target_slot": str(best_slot.slot_number)
    })


@app.route("/corporation_dashboard")
def corporation_dashboard():

    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("login"))

    if user.is_admin != True:
        return """
        <div style="text-align:center;margin-top:100px;">
            <h1>🚫 Access Denied</h1>
            <p>Corporation Approval is available only to authorized administrators.</p>
            <a href="/dashboard">⬅ Back to Dashboard</a>
        </div>
        """

    requests = CorporationNotification.query.order_by(
        CorporationNotification.created_at.desc()
    ).all()

    for req in requests:
        slot = ParkingSlot.query.filter_by(
            slot_number=req.slot_number
        ).first()

        if slot and slot.parking_area_id:
            area = ParkingArea.query.get(slot.parking_area_id)

            if area:
                req.parking_area = area.name
            else:
                req.parking_area = "N/A"
        else:
            req.parking_area = "N/A"

    return render_template(
        "corporation_dashboard.html",
        requests=requests
    )
@app.route("/approve/<int:id>", methods=["POST"])
def approve(id):

    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if not user or not user.is_admin:
        return "Access Denied", 403

    request_data = CorporationNotification.query.get_or_404(id)

    if request_data.status != "Pending":
        return redirect(url_for("corporation_dashboard"))

    slot = ParkingSlot.query.filter_by(
        slot_number=request_data.slot_number
    ).first()

    if not slot:
        return "Parking slot not found."

    request_data.status = "Approved"

    # Slot is already marked as occupied during booking, no need to set again
    # slot.status = "Occupied"
    # slot.owner = request_data.owner

    notification = Notification(
        owner=request_data.owner,
        title="✅ Parking Request Approved",
        message=(
            f"Your parking request for Slot "
            f"{request_data.slot_number} has been approved by "
            f"the Corporation. Vehicle "
            f"{request_data.vehicle_number} is authorized to park."
        ),
        status="Unread"
    )

    db.session.add(notification)
    db.session.commit()

    # Twilio SMS
    sms_msg = (
        f"SmartParking: Your parking request for "
        f"Slot {request_data.slot_number} "
        f"(Vehicle: {request_data.vehicle_number}) "
        f"has been APPROVED."
    )

    send_sms(OWNER_PHONE_NUMBER, sms_msg)
    
    # Notify real-time server of parking update
    notify_realtime_server()

    return redirect(url_for("corporation_dashboard"))
# ==========================
# REJECT PARKING REQUEST
# ==========================

@app.route("/reject/<int:id>", methods=["POST"])
def reject(id):

    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if not user or not user.is_admin:
        return "Access Denied", 403

    request_data = CorporationNotification.query.get_or_404(id)

    if request_data.status != "Pending":
        return redirect(url_for("corporation_dashboard"))

    request_data.status = "Rejected"

    slot = ParkingSlot.query.filter_by(
        slot_number=request_data.slot_number
    ).first()

    if slot:
        # Mark slot as available when request is rejected
        slot.status = "Available"
        slot.owner = ""

    notification = Notification(
        owner=request_data.owner,
        title="❌ Parking Request Rejected",
        message=(
            f"Your parking request for Slot "
            f"{request_data.slot_number} was rejected "
            f"by the Corporation."
        ),
        status="Unread"
    )

    db.session.add(notification)
    db.session.commit()

    # Twilio SMS
    sms_msg = (
        f"SmartParking: Your booking request for "
        f"Slot {request_data.slot_number} "
        f"was REJECTED by the Corporation."
    )

    send_sms(OWNER_PHONE_NUMBER, sms_msg)
    
    # Notify real-time server of parking update
    notify_realtime_server()

    return redirect(url_for("corporation_dashboard"))

# ==========================================
# MAKE CURRENT ACCOUNT ADMIN
# ==========================================

@app.route("/make_admin")
def make_admin():

    # Check whether someone is logged in
    if "email" not in session:
        return redirect(url_for("login"))

    # Find the currently logged-in user
    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if user is None:
        session.clear()
        return redirect(url_for("login"))

    # Make CURRENT user an administrator
    user.is_admin = True
    db.session.commit()

    # Keep session connected to CURRENT user
    session["email"] = user.email
    session["user_id"] = user.id
    session["username"] = user.name
    session["user"] = user.name
    session["is_admin"] = True

    return """
        <h1>✅ Admin Access Granted!</h1>
        <p>Your account is now an administrator.</p>
        <a href="/admin">Open Admin Dashboard</a>
    """

# ==========================
# ADMIN DASHBOARD
# ==========================

@app.route("/admin")
def admin_dashboard():
    if "email" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(email=session["email"]).first()

    if user is None:
        session.clear()
        return redirect(url_for("login"))

    if not user.is_admin:
        return "Access Denied"

    total_users = User.query.count()
    total_vehicles = Vehicle.query.count()
    total_slots = ParkingSlot.query.count()
    available_slots = ParkingSlot.query.filter_by(status="Available").count()
    occupied_slots = ParkingSlot.query.filter_by(status="Occupied").count()
    total_records = ParkingRecord.query.count()

    parking_records = ParkingRecord.query.order_by(ParkingRecord.id.desc()).limit(10).all()
    users = User.query.order_by(User.id.desc()).all()
    vehicles = Vehicle.query.order_by(Vehicle.id.desc()).all()
    slots = ParkingSlot.query.order_by(ParkingSlot.slot_number).all()
    parking_areas = ParkingArea.query.all()

    return render_template(
        "admin_dashboard.html",
        username=user.name,
        total_users=total_users,
        total_vehicles=total_vehicles,
        total_slots=total_slots,
        available_slots=available_slots,
        occupied_slots=occupied_slots,
        total_records=total_records,
        parking_records=parking_records,
        users=users,
        vehicles=vehicles,
        slots=slots,
        parking_areas=parking_areas
    )
@app.route("/unlock-admin-account")
def unlock_admin_account():
    # Replace with your registered email address
    user_email = "srushti@gmail.com"
    
    user = User.query.filter_by(email=user_email).first()
    if user:
        user.account_locked = False
        user.failed_login_attempts = 0
        db.session.commit()
        return f"✅ Account {user_email} unlocked! Go to <a href='/login'>Login</a>"
    return "❌ User not found."

# ==========================
# RUN APPLICATION
# ==========================

if __name__ == "__main__":
    app.run(debug=True)