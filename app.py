from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

# ==========================
# SECRET KEY
# ==========================

app.secret_key = "parking123"

# ==========================
# DATABASE CONFIGURATION
# ==========================

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///parking.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==========================
# USER TABLE
# ==========================

class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    email = db.Column(db.String(100), unique=True, nullable=False)

    password = db.Column(db.String(100), nullable=False)


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
# IoT SENSOR TABLE
# ==========================

class IoTSensor(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    sensor_id = db.Column(db.String(20), unique=True)

    slot_number = db.Column(db.String(20))

    status = db.Column(db.String(20), default="Available")

    last_update = db.Column(db.DateTime)


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

    created_at = db.Column(
        db.DateTime,
        default=datetime.now
    )

    status = db.Column(
        db.String(20),
        default="Unread"
    )
# ==========================
# THEFT ALERT TABLE
# ==========================

class TheftAlert(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    owner = db.Column(db.String(100))

    vehicle_number = db.Column(db.String(30))

    slot_number = db.Column(db.String(20))

    alert_message = db.Column(db.String(300))

    alert_time = db.Column(
        db.DateTime,
        default=datetime.now
    )

    status = db.Column(
        db.String(30),
        default="Pending"
    )


# ==========================
# CREATE DATABASE TABLES
# ==========================

with app.app_context():
    db.create_all()

print("Database tables created")
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
def register():

    if request.method == "POST":

        name = request.form["name"].strip()

        email = request.form["email"].strip().lower()

        password = request.form["password"].strip()

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            session["user"] = existing_user.name
            session["email"] = existing_user.email

            return redirect(url_for("dashboard"))

        new_user = User(

            name=name,

            email=email,

            password=password

        )

        db.session.add(new_user)

        db.session.commit()

        session["user"] = new_user.name
        session["email"] = new_user.email

        return redirect(url_for("dashboard"))

    return render_template("register.html")


# ==========================
# DASHBOARD
# ==========================

@app.route("/dashboard")
def dashboard():

    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if user is None:
        session.clear()
        return redirect(url_for("register"))

    # User Vehicles
    vehicles = Vehicle.query.filter_by(
        owner=user.name
    ).all()

    # User Parking Slot
    my_slot = ParkingSlot.query.filter_by(
        owner=user.name
    ).first()

    # Parking Records
    records = ParkingRecord.query.filter_by(
        owner=user.name
    ).order_by(
        ParkingRecord.id.desc()
    ).all()

    # AI Recommended Slot
    recommended_slot = ParkingSlot.query.filter_by(
        status="Available"
    ).order_by(
        ParkingSlot.ai_score.desc()
    ).first()

    # IoT Sensor
    sensor = None

    if my_slot:
        sensor = IoTSensor.query.filter_by(
            slot_number=my_slot.slot_number
        ).first()

    # Vehicle Location
    vehicle_location = VehicleLocation.query.filter_by(
        owner=user.name,
        status="Parked"
    ).first()

    # Notifications
    notifications = Notification.query.filter_by(
        owner=user.name
    ).order_by(
        Notification.created_at.desc()
    ).all()

    # Theft Alerts
    theft_alerts = TheftAlert.query.filter_by(
        owner=user.name
    ).order_by(
        TheftAlert.alert_time.desc()
    ).all()

    return render_template(

        "dashboard.html",

        username=user.name,

        vehicles=vehicles,

        my_slot=my_slot,

        records=records,

        recommended_slot=recommended_slot,

        sensor=sensor,

        vehicle_location=vehicle_location,

        notifications=notifications,

        theft_alerts=theft_alerts

    )


# ==========================
# ADD VEHICLE
# ==========================

@app.route("/add_vehicle", methods=["GET", "POST"])
def add_vehicle():

    if "email" not in session:

        return redirect(url_for("register"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if user is None:

        session.clear()

        return redirect(url_for("register"))

    if request.method == "POST":

        vehicle_number = request.form[
            "vehicle_number"
        ].strip().upper()

        vehicle_type = request.form[
            "vehicle_type"
        ]

        color = request.form[
            "color"
        ].strip()

        existing_vehicle = Vehicle.query.filter_by(
            vehicle_number=vehicle_number
        ).first()

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

    return render_template(
        "add_vehicle.html"
    )


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

    slots = [

        ("A1",10,95,True,True,True,98),
        ("A2",20,90,True,True,False,90),
        ("A3",30,85,False,True,False,75),
        ("B1",40,80,False,False,False,45),
        ("B2",50,75,True,False,False,60),
        ("B3",60,70,False,True,True,80)

    ]

    for slot_number,distance,ai_score,cctv,lighting,near_entrance,safety_score in slots:

        slot = ParkingSlot.query.filter_by(
            slot_number=slot_number
        ).first()

        if slot is None:

            slot = ParkingSlot(

                slot_number=slot_number,

                status="Available",

                owner="",

                distance=distance,

                ai_score=ai_score,

                cctv=cctv,

                lighting=lighting,

                near_entrance=near_entrance,

                safety_score=safety_score

            )

            db.session.add(slot)

    db.session.commit()

    return "Parking Slots Created Successfully"


# ==========================
# CREATE IoT SENSORS
# ==========================

@app.route("/create_sensors")
def create_sensors():

    slots=["A1","A2","A3","B1","B2","B3"]

    for number in slots:

        sensor=IoTSensor.query.filter_by(
            slot_number=number
        ).first()

        if sensor is None:

            sensor=IoTSensor(

                sensor_id="SENSOR_"+number,

                slot_number=number,

                status="Available",

                last_update=datetime.now()

            )

            db.session.add(sensor)

    db.session.commit()

    return "IoT Sensors Created Successfully"


# ==========================
# BOOK SLOT PAGE
# ==========================

@app.route("/book_slot")
def book_slot():

    if "email" not in session:

        return redirect(url_for("register"))

    user=User.query.filter_by(
        email=session["email"]
    ).first()

    if user is None:

        session.clear()

        return redirect(url_for("register"))

    slots=ParkingSlot.query.order_by(
        ParkingSlot.slot_number
    ).all()

    return render_template(

        "book_slot.html",

        username=user.name,

        slots=slots

    )


# ==========================
# BOOK PARKING SLOT
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

    # Update slot
    slot.status = "Occupied"
    slot.owner = user.name

    # Save vehicle location
    new_location = VehicleLocation(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        slot_number=slot.slot_number,
        zone="A",
        floor="Ground Floor",
        latitude=15.8499,
        longitude=74.4979,
        parking_time=datetime.now(),
        status="Parked"
    )

    db.session.add(new_location)
    db.session.commit()

    return redirect(url_for("find_vehicle"))
# ==========================
# GENERATE QR CODE
# ==========================

@app.route("/generate_qr/<int:id>")
def generate_qr(id):

    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    slot = ParkingSlot.query.get_or_404(id)

    if slot.owner != user.name:
        return "Not Allowed"

    qr_data = f"""

Owner : {user.name}

Vehicle Slot : {slot.slot_number}

Status : {slot.status}

Generated : {datetime.now()}

"""

    img = qrcode.make(qr_data)

    folder = os.path.join(
        "static",
        "qrcodes"
    )

    if not os.path.exists(folder):
        os.makedirs(folder)

    filename = slot.slot_number + ".png"

    path = os.path.join(
        folder,
        filename
    )

    img.save(path)

    return render_template(

        "qr_code.html",

        filename=filename

    )
    


# ==========================
# VEHICLE ENTRY
# ==========================

@app.route("/entry/<int:id>")
def entry(id):

    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    slot = ParkingSlot.query.get_or_404(id)

    vehicle = Vehicle.query.filter_by(
        owner=user.name
    ).first()

    if vehicle is None:
        return "Please Register Vehicle First."

    record = ParkingRecord(

        owner=user.name,

        vehicle_number=vehicle.vehicle_number,

        slot_number=slot.slot_number,

        entry_time=datetime.now(),

        status="Inside"

    )

    db.session.add(record)

    sensor = IoTSensor.query.filter_by(
        slot_number=slot.slot_number
    ).first()

    if sensor:

        sensor.status = "Occupied"

        sensor.last_update = datetime.now()

    location = VehicleLocation(

        owner=user.name,

        vehicle_number=vehicle.vehicle_number,

        slot_number=slot.slot_number,

        zone="Zone A",

        floor="Ground Floor",

        latitude=15.8497,

        longitude=74.4977,

        parking_time=datetime.now(),

        status="Parked"

    )

    db.session.add(location)

    notification = Notification(

        owner=user.name,

        title="Vehicle Parked",

        message=f"{vehicle.vehicle_number} parked successfully in Slot {slot.slot_number}"

    )

    db.session.add(notification)

    db.session.commit()

    return redirect(url_for("dashboard"))


# ==========================
# VEHICLE EXIT
# ==========================

@app.route("/exit/<int:id>")
def exit(id):

    record = ParkingRecord.query.get_or_404(id)

    record.exit_time = datetime.now()

    record.status = "Exited"

    minutes = (

        record.exit_time -

        record.entry_time

    ).seconds // 60

    fee = max(minutes * 2, 20)

    record.parking_fee = fee

    slot = ParkingSlot.query.filter_by(

        slot_number=record.slot_number

    ).first()

    if slot:

        slot.status = "Available"

        slot.owner = ""

    sensor = IoTSensor.query.filter_by(

        slot_number=record.slot_number

    ).first()

    if sensor:

        sensor.status = "Available"

        sensor.last_update = datetime.now()

    location = VehicleLocation.query.filter_by(

        vehicle_number=record.vehicle_number,

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

    db.session.commit()

    return redirect(url_for("dashboard"))
# ==========================
# FIND MY VEHICLE
# ==========================

@app.route("/find_vehicle")
def find_vehicle():

    # Check login
    if "email" not in session:
        return redirect(url_for("login"))

    # Get logged in user
    user = User.query.filter_by(
        email=session["email"]
    ).first()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    # Get user's vehicle
    vehicle = Vehicle.query.filter_by(
        owner=user.name
    ).first()

    # If user has no vehicle
    if not vehicle:
        return render_template(
            "find_vehicle.html",
            username=user.name,
            vehicle=None,
            vehicle_location=None,
            notifications=[]
        )

    # Find vehicle location
    vehicle_location = VehicleLocation.query.filter_by(
        owner=user.name,
        vehicle_number=vehicle.vehicle_number,
        status="Parked"
    ).first()

    # Notifications
    notifications = Notification.query.filter_by(
        owner=user.name
    ).order_by(
        Notification.created_at.desc()
    ).limit(5).all()

    return render_template(
        "find_vehicle.html",
        username=user.name,
        vehicle=vehicle,
        vehicle_location=vehicle_location,
        notifications=notifications
    )
# ==========================
# THEFT ALERT
# ==========================

@app.route("/theft_alert/<int:record_id>")
def theft_alert(record_id):

    if "email" not in session:
        return redirect(url_for("register"))

    record = ParkingRecord.query.get_or_404(record_id)

    alert = TheftAlert(

        owner=record.owner,

        vehicle_number=record.vehicle_number,

        slot_number=record.slot_number,

        alert_message=f"🚨 Possible theft detected for vehicle {record.vehicle_number} parked in Slot {record.slot_number}.",

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

    return redirect(url_for("view_theft_alerts"))

# ==========================
# VIEW THEFT ALERTS
# ==========================

@app.route("/theft_alerts")
def view_theft_alerts():

    if "email" not in session:
        return redirect(url_for("register"))

    user = User.query.filter_by(
        email=session["email"]
    ).first()

    alerts = TheftAlert.query.filter_by(
        owner=user.name
    ).order_by(
        TheftAlert.alert_time.desc()
    ).all()

    return render_template(

        "theft_alerts.html",

        username=user.name,

        alerts=alerts

    )
# ==========================
# IoT DASHBOARD
# ==========================

@app.route("/iot_dashboard")
def iot_dashboard():

    if "email" not in session:
        return redirect(url_for("register"))

    total_slots = ParkingSlot.query.count()

    available_slots = ParkingSlot.query.filter_by(
        status="Available"
    ).count()

    occupied_slots = ParkingSlot.query.filter(
        ParkingSlot.status != "Available"
    ).count()

    total_vehicles = ParkingRecord.query.filter_by(
        status="Inside"
    ).count()

    sensors = IoTSensor.query.order_by(
        IoTSensor.slot_number
    ).all()

    records = ParkingRecord.query.all()

    revenue = 0

    for record in records:

        if record.parking_fee:

            revenue += record.parking_fee

    return render_template(

        "iot_dashboard.html",

        total_slots=total_slots,

        available_slots=available_slots,

        occupied_slots=occupied_slots,

        total_vehicles=total_vehicles,

        revenue=revenue,

        sensors=sensors

    )
@app.route("/parking_map")
def parking_map():
    return render_template("parking_map.html")
# ==========================
# RUN APPLICATION
# ==========================

if __name__ == "__main__":
    app.run(debug=True)
    