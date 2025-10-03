# backend/app.py
import os
import io
import base64
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.message import EmailMessage
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -----------------------
# Config
# -----------------------
app = Flask(__name__)
CORS(app)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(BASE_DIR, "data", "sales_data.csv")

# Use DB URI from env or fallback to SQLite
DB_URI = os.environ.get("DASH_DB_URI", f"sqlite:///{os.path.join(BASE_DIR, 'dashboard.db')}")
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

JWT_SECRET = os.environ.get("DASH_JWT_SECRET", "change_this_secret_in_prod")
JWT_ALGO = "HS256"

SMTP_HOST = os.environ.get("DASH_SMTP_HOST")  # e.g. smtp.gmail.com
SMTP_PORT = int(os.environ.get("DASH_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("DASH_SMTP_USER")
SMTP_PASS = os.environ.get("DASH_SMTP_PASS")
SENDER_EMAIL = os.environ.get("DASH_SENDER_EMAIL", SMTP_USER)

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# -----------------------
# Models
# -----------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScheduledEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(120), nullable=False)
    target_email = db.Column(db.String(120), nullable=False)
    region = db.Column(db.String(50))
    product = db.Column(db.String(50))
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    freq = db.Column(db.String(20), default="weekly")
    next_run = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# -----------------------
# JWT helpers
# -----------------------
def create_jwt(payload, exp_minutes=60*24):
    payload = payload.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=exp_minutes)
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token

def decode_jwt(token):
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return data
    except Exception:
        return None

# -----------------------
# Database helpers
# -----------------------
def add_scheduled_email_to_db(entry):
    scheduled = ScheduledEmail(
        user_email=entry.get("user_email"),
        target_email=entry.get("target_email"),
        region=entry.get("region"),
        product=entry.get("product"),
        start_date=datetime.fromisoformat(entry["start_date"]) if entry.get("start_date") else None,
        end_date=datetime.fromisoformat(entry["end_date"]) if entry.get("end_date") else None,
        freq=entry.get("freq", "weekly"),
        next_run=datetime.fromisoformat(entry["next_run"]) if entry.get("next_run") else None,
        created_at=datetime.fromisoformat(entry["created_at"])
    )
    db.session.add(scheduled)
    db.session.commit()
    return scheduled.id

def get_all_schedules():
    schedules = ScheduledEmail.query.all()
    return [
        {
            "id": s.id,
            "user_email": s.user_email,
            "target_email": s.target_email,
            "region": s.region,
            "product": s.product,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "freq": s.freq,
            "next_run": s.next_run.isoformat() if s.next_run else None
        }
        for s in schedules
    ]

# -----------------------
# Data helpers
# -----------------------
def load_data():
    df = pd.read_csv(DATA_FILE, parse_dates=["date"])
    return df

def aggregate_stats(df):
    total_sales = int(df["sales"].sum())
    total_revenue = int(df["revenue"].sum())
    sales_by_product = df.groupby("product")["sales"].sum().reset_index().to_dict(orient="records")
    sales_by_region = df.groupby("region")["sales"].sum().reset_index().to_dict(orient="records")
    daily_sales = df.groupby(df["date"].dt.strftime('%Y-%m-%d'))["sales"].sum().reset_index().rename(columns={'date':'date'}).to_dict(orient="records")
    return {
        "total_sales": total_sales,
        "total_revenue": total_revenue,
        "sales_by_product": sales_by_product,
        "sales_by_region": sales_by_region,
        "daily_sales": daily_sales
    }

# -----------------------
# PDF generator
# -----------------------
def build_pdf_buffer(charts_b64: dict, summary: dict, title="Dashboard Report"):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    elements.append(Paragraph(f"<b><font size=16>{title}</font></b>", None))
    elements.append(Spacer(1, 0.2 * inch))

    summary_table_data = [
        ["Total Sales", f"{summary.get('total_sales', 0):,}"],
        ["Total Revenue", f"${summary.get('total_revenue', 0):,}"]
    ]
    summary_table = Table(summary_table_data, hAlign='LEFT', colWidths=[2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1, -1), 11),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3 * inch))

    for title, b64_img in charts_b64.items():
        elements.append(Paragraph(f"<b>{title}</b>", None))
        elements.append(Spacer(1, 0.1 * inch))
        if "," in b64_img:
            b64_img = b64_img.split(",",1)[1]
        try:
            image_data = base64.b64decode(b64_img)
            img_buffer = io.BytesIO(image_data)
            img = Image(img_buffer, width=5.8*inch, height=3.2*inch)
            elements.append(img)
            elements.append(Spacer(1, 0.3 * inch))
        except Exception:
            elements.append(Paragraph("Could not embed chart image.", None))
            elements.append(Spacer(1, 0.2 * inch))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# -----------------------
# Email sender
# -----------------------
def send_email_with_pdf(to_email, subject, body_text, pdf_buffer, filename="report.pdf"):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SENDER_EMAIL]):
        print("SMTP not configured - cannot send email.")
        return False, "SMTP not configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg.set_content(body_text)

    pdf_bytes = pdf_buffer.getvalue()
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        return True, "Sent"
    except Exception as e:
        print("Email send failed:", e)
        return False, str(e)

# -----------------------
# Scheduler job
# -----------------------
def scheduled_job_send(id, target_email, region, product, start_date, end_date):
    try:
        df = load_data()
        if region:
            df = df[df["region"].str.lower()==region.lower()]
        if product:df = df[df["product"].str.lower()==product.lower()]
        if start_date:
            df = df[df["date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["date"] <= pd.to_datetime(end_date)]
        stats = aggregate_stats(df)
        pdf_buffer = build_pdf_buffer({}, stats, title="Scheduled Dashboard Report")
        success, msg = send_email_with_pdf(target_email, "Scheduled Dashboard Report", "Attached is your scheduled report.", pdf_buffer, filename="scheduled_report.pdf")
        print("Scheduled send:", success, msg)
    except Exception as e:
        print("Scheduled job error:", e)

# -----------------------
# Routes
# -----------------------
@app.route("/")
def home():
    return jsonify({"message": "Dashboard API is running ✅"})

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error":"Email and password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error":"User already exists"}), 400
    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    token = create_jwt({"email": email})
    return jsonify({"message":"registered","token": token})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error":"Invalid credentials"}), 401
    token = create_jwt({"email": email})
    return jsonify({"message":"logged_in","token": token})

# Data endpoint (raw)
@app.route("/api/data", methods=["GET"])
def get_data():
    df = load_data()
    return jsonify(df.to_dict(orient="records"))

# Stats endpoint with filters (start_date, end_date, region, product)
@app.route("/api/stats", methods=["GET"])
def get_stats():
    df = load_data()
    # optional filters
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    region = request.args.get("region")
    product = request.args.get("product")
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]
    if region:
        df = df[df["region"].str.lower() == region.lower()]
    if product:
        df = df[df["product"].str.lower() == product.lower()]

    stats = aggregate_stats(df)
    return jsonify({**stats, "table_data": df.sort_values("date").to_dict(orient="records")})

# Exports: CSV
@app.route("/api/export/csv", methods=["GET"])
def export_csv():
    df = load_data()
    region = request.args.get("region")
    product = request.args.get("product")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if region:
        df = df[df["region"].str.lower() == region.lower()]
    if product:
        df = df[df["product"].str.lower() == product.lower()]
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")), mimetype="text/csv", as_attachment=True, download_name="dashboard_data.csv")

# Exports: Excel
@app.route("/api/export/excel", methods=["GET"])
def export_excel():
    import pandas as pd
    df = load_data()
    region = request.args.get("region")
    product = request.args.get("product")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if region:
        df = df[df["region"].str.lower() == region.lower()]
    if product:
        df = df[df["product"].str.lower() == product.lower()]
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Dashboard Data")
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="dashboard_data.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# PDF export (POST): expects charts (base64) + summary
@app.route("/api/export/pdf", methods=["POST"])
def export_pdf():
    payload = request.get_json() or {}
    charts = payload.get("charts", {})
    summary = payload.get("summary", {})
    buffer = build_pdf_buffer(charts, summary)
    return send_file(buffer, as_attachment=True, download_name="dashboard_report.pdf", mimetype="application/pdf")

# Schedule an email (protected route: requires JWT)
@app.route("/api/schedule-email", methods=["POST"])
def schedule_email():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = decode_jwt(token)
    if not user:
        return jsonify({"error":"Unauthorized"}), 401
    data = request.json or {}
    target_email = data.get("target_email")
    region = data.get("region")
    product = data.get("product")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    freq = data.get("freq", "weekly")
    if not target_email:
        return jsonify({"error":"target_email required"}), 400

    # calculate next_run (simple: next week)
    next_run = (datetime.utcnow() + timedelta(days=7)).isoformat()

    entry = {
        "user_email": user.get("email"),
        "target_email": target_email,
        "region": region,
        "product": product,
        "start_date": start_date,
        "end_date": end_date,
        "freq": freq,
        "next_run": next_run,
        "created_at": datetime.utcnow().isoformat()
    }
    rowid = add_scheduled_email_to_db(entry)

    # schedule immediate APScheduler job (for weekly)
    job_id = f"scheduled_email_{rowid}"
    scheduler.add_job(
        scheduled_job_send,
        'interval',
        weeks=1,
        next_run_time=datetime.utcnow() + timedelta(seconds=10),  # for demo11s run
        id=job_id,
        args=[rowid, target_email, region, product, start_date, end_date]
    )

    return jsonify({"message":"scheduled", "id": rowid})

# Get schedules (admin / user can fetch their schedules)
@app.route("/api/schedules", methods=["GET"])
def api_schedules():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = decode_jwt(token)
    if not user:
        return jsonify({"error":"Unauthorized"}), 401
    schedules = get_all_schedules()
    # filter to user's email for safety
    schedules = [s for s in schedules if s["user_email"] == user.get("email")]
    return jsonify({"schedules": schedules})

# Initialize DB & load existing scheduled jobs
def load_existing_schedules_into_jobs():
    schedules = get_all_schedules()
    for s in schedules:
        job_id = f"scheduled_email_{s['id']}"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                scheduled_job_send,
                'interval',
                weeks=1,
                next_run_time=datetime.fromisoformat(s['next_run']) if s['next_run'] else datetime.utcnow() + timedelta(seconds=10),
                id=job_id,
                args=[s['id'], s['target_email'], s['region'], s['product'], s['start_date'], s['end_date']]
            )

# -----------------------
# Run app
# -----------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all() 
        load_existing_schedules_into_jobs()
    app.run(host="0.0.0.0", port=5000, debug=False)