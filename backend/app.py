# backend/app.py
import os
import io
import re
import base64
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.message import EmailMessage
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dashboard")


def env(*names, default=None):
    """Return the first non-empty value among several variable names, trimmed.

    The README listed different variable names than the code used, so both spellings
    are accepted. Trimming also guards against a space pasted at either end."""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return default


def utcnow():
    """Naive UTC time, which is what the DateTime columns store."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -----------------------
# Config
# -----------------------
app = Flask(__name__)
CORS(app)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(BASE_DIR, "data", "sales_data.csv")
DATE_FORMAT = "%Y-%m-%d"


def database_uri():
    # Use DB URI from env or fall back to SQLite
    uri = env("DASH_DB_URI", "DATABASE_URL")
    if not uri:
        return f"sqlite:///{os.path.join(BASE_DIR, 'dashboard.db')}"
    # Hosts often hand out postgres:// links, which SQLAlchemy no longer accepts
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    return uri


DB_URI = database_uri()
engine_options = {"pool_pre_ping": True}
if DB_URI.startswith("postgresql"):
    # Hosted Postgres closes idle connections, and a database that can't be reached
    # should fail quickly instead of hanging the server while it starts
    engine_options["pool_recycle"] = 300
    engine_options["connect_args"] = {"connect_timeout": 10}

app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# The PDF export posts three chart images; nothing legitimate comes close to this
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

db = SQLAlchemy(app)
migrate = Migrate(app, db)

JWT_SECRET = env("DASH_JWT_SECRET", "SECRET_KEY")
if not JWT_SECRET:
    # A fixed fallback secret would let anyone forge a login token, so use a random one.
    # Logins then reset whenever the server restarts until DASH_JWT_SECRET is set.
    JWT_SECRET = secrets.token_urlsafe(48)
    logger.warning("DASH_JWT_SECRET is not set, so logins reset whenever the server restarts")
JWT_ALGO = "HS256"

SMTP_HOST = env("DASH_SMTP_HOST", "MAIL_SERVER")  # e.g. smtp.gmail.com
try:
    SMTP_PORT = int(env("DASH_SMTP_PORT", "MAIL_PORT", default="587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USER = env("DASH_SMTP_USER", "MAIL_USERNAME")
SMTP_PASS = env("DASH_SMTP_PASS", "MAIL_PASSWORD")
SENDER_EMAIL = env("DASH_SENDER_EMAIL", default=SMTP_USER)
EMAIL_ENABLED = all([SMTP_HOST, SMTP_USER, SMTP_PASS, SENDER_EMAIL])

# Limits that stop the schedule feature from being used to flood an inbox
MAX_SCHEDULES_PER_USER = 3
MAX_SCHEDULES_PER_TARGET = 3

# Scheduler
scheduler = BackgroundScheduler(timezone="UTC")
scheduler.start()

# -----------------------
# Models
# -----------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

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
    created_at = db.Column(db.DateTime, default=utcnow)

# -----------------------
# JWT helpers
# -----------------------
def create_jwt(payload, exp_minutes=60*24):
    payload = payload.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token

def decode_jwt(token):
    if not token:
        return None
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO], options={"require": ["exp"]})
        return data
    except Exception:
        return None

def current_user():
    """The logged-in user for this request, or None.

    Raises SQLAlchemyError when the database can't be reached."""
    header = request.headers.get("Authorization", "")
    token = header[len("Bearer "):] if header.startswith("Bearer ") else ""
    claims = decode_jwt(token)
    if not claims or not claims.get("email"):
        return None
    # The account has to still exist, not just the token
    return User.query.filter_by(email=claims["email"]).first()

# -----------------------
# Request helpers
# -----------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def clean_email(value):
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if len(email) > 120 or not EMAIL_RE.match(email):
        return None
    return email

def client_ip():
    # Render sits in front of the app, so the visitor's address is in X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or "unknown"

def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def error(message, status):
    return jsonify({"error": message}), status

def unauthorized():
    return error("Please log in again.", 401)

def database_unavailable():
    return error("Accounts are unavailable right now because the server can't reach its database. Please try again later.", 503)

def too_many_attempts():
    return error("Too many attempts. Please wait a few minutes and try again.", 429)


class AttemptLimiter:
    """Counts attempts per key within a time window.

    It lives in memory, so it resets when the server restarts. That is enough to slow
    down password guessing on a single small server."""

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def _prune(self, key, now):
        attempts = self.hits.get(key)
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()
        if attempts is not None and not attempts:
            del self.hits[key]

    def blocked(self, key):
        now = time.monotonic()
        with self.lock:
            self._prune(key, now)
            return len(self.hits.get(key, ())) >= self.limit

    def add(self, key):
        now = time.monotonic()
        with self.lock:
            if len(self.hits) > 10000:
                for stale in list(self.hits):
                    self._prune(stale, now)
            self.hits[key].append(now)

    def reset(self, key=None):
        with self.lock:
            if key is None:
                self.hits.clear()
            else:
                self.hits.pop(key, None)


auth_requests_by_ip = AttemptLimiter(limit=20, window_seconds=600)
failed_logins_by_email = AttemptLimiter(limit=8, window_seconds=900)

# -----------------------
# Database helpers
# -----------------------
def to_datetime_or_none(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)

def add_scheduled_email_to_db(entry):
    scheduled = ScheduledEmail(
        user_email=entry.get("user_email"),
        target_email=entry.get("target_email"),
        region=entry.get("region"),
        product=entry.get("product"),
        start_date=to_datetime_or_none(entry.get("start_date")),
        end_date=to_datetime_or_none(entry.get("end_date")),
        freq=entry.get("freq", "weekly"),
        next_run=to_datetime_or_none(entry.get("next_run")),
        created_at=to_datetime_or_none(entry.get("created_at")) or utcnow(),
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
class InvalidFilter(ValueError):
    pass

def load_data():
    df = pd.read_csv(DATA_FILE, parse_dates=["date"])
    return df

def parse_date_arg(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = pd.to_datetime(str(value).strip())
    except (ValueError, TypeError, OverflowError):
        raise InvalidFilter("Dates must be written like 2025-01-31.")
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(None)
    return parsed

def apply_filters(df, start_date=None, end_date=None, region=None, product=None):
    start = parse_date_arg(start_date)
    end = parse_date_arg(end_date)
    region = (region or "").strip()
    product = (product or "").strip()
    if start is not None:
        df = df[df["date"] >= start]
    if end is not None:
        df = df[df["date"] <= end]
    if region:
        df = df[df["region"].str.lower() == region.lower()]
    if product:
        df = df[df["product"].str.lower() == product.lower()]
    return df

def filtered_from_request():
    args = request.args
    return apply_filters(
        load_data(),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        region=args.get("region"),
        product=args.get("product"),
    )

def to_records(df):
    """Rows for JSON, with dates as YYYY-MM-DD.

    Without this, Flask turns dates into text like "Wed, 01 Jan 2025 00:00:00 GMT",
    which the date filters and the table sorting in the frontend can't use."""
    out = df.sort_values("date").copy()
    out["date"] = out["date"].dt.strftime(DATE_FORMAT)
    return out.to_dict(orient="records")

def aggregate_stats(df):
    total_sales = int(df["sales"].sum())
    total_revenue = int(df["revenue"].sum())
    sales_by_product = df.groupby("product")["sales"].sum().reset_index().to_dict(orient="records")
    sales_by_region = df.groupby("region")["sales"].sum().reset_index().to_dict(orient="records")
    daily_sales = df.groupby(df["date"].dt.strftime(DATE_FORMAT))["sales"].sum().reset_index().to_dict(orient="records")
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
MAX_CHART_PIXELS = 4_000_000

def as_number(value):
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0

def build_pdf_buffer(charts_b64: dict, summary: dict, title="Dashboard Report"):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    elements.append(Paragraph(f"<b><font size=16>{escape(title)}</font></b>", None))
    elements.append(Spacer(1, 0.2 * inch))

    summary_table_data = [
        ["Total Sales", f"{as_number(summary.get('total_sales', 0)):,}"],
        ["Total Revenue", f"${as_number(summary.get('total_revenue', 0)):,}"]
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

    for chart_title, b64_img in list(charts_b64.items())[:5]:
        # Chart titles come from the browser, so they are escaped before ReportLab reads
        # them as markup (its <img> tag could otherwise pull files off the server)
        elements.append(Paragraph(f"<b>{escape(str(chart_title)[:120])}</b>", None))
        elements.append(Spacer(1, 0.1 * inch))
        try:
            if not isinstance(b64_img, str):
                raise ValueError("chart image must be a string")
            if "," in b64_img:
                b64_img = b64_img.split(",", 1)[1]
            image_data = base64.b64decode(b64_img, validate=True)
            # Read only the image header first, so a tiny file that claims to be a huge
            # image can't exhaust the server's memory
            width, height = ImageReader(io.BytesIO(image_data)).getSize()
            if width * height > MAX_CHART_PIXELS:
                raise ValueError("chart image is too large")
            img = Image(io.BytesIO(image_data), width=5.8*inch, height=3.2*inch)
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
    if not EMAIL_ENABLED:
        logger.info("SMTP not configured - cannot send email.")
        return False, "SMTP not configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg.set_content(body_text)

    pdf_bytes = pdf_buffer.getvalue()
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        return True, "Sent"
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False, str(e)

# -----------------------
# Scheduler job
# -----------------------
def scheduled_job_send(id, target_email, region, product, start_date, end_date):
    try:
        df = apply_filters(load_data(), start_date=start_date, end_date=end_date, region=region, product=product)
        stats = aggregate_stats(df)
        pdf_buffer = build_pdf_buffer({}, stats, title="Scheduled Dashboard Report")
        success, msg = send_email_with_pdf(target_email, "Scheduled Dashboard Report", "Attached is your scheduled report.", pdf_buffer, filename="scheduled_report.pdf")
        logger.info("Scheduled send %s: %s %s", id, success, msg)
    except Exception:
        logger.exception("Scheduled job error")

def add_schedule_job(schedule_id, target_email, region, product, start_date, end_date, first_run):
    scheduler.add_job(
        scheduled_job_send,
        'interval',
        weeks=1,
        next_run_time=first_run,
        id=f"scheduled_email_{schedule_id}",
        replace_existing=True,
        args=[schedule_id, target_email, region, product, start_date, end_date]
    )

# -----------------------
# Error responses
# -----------------------
@app.errorhandler(InvalidFilter)
def handle_invalid_filter(e):
    return error(str(e), 400)

@app.errorhandler(413)
def handle_too_large(e):
    return error("That request was too large.", 413)

@app.errorhandler(500)
def handle_server_error(e):
    return error("Something went wrong on the server. Please try again.", 500)

# -----------------------
# Routes
# -----------------------
@app.route("/")
def home():
    return jsonify({"message": "Dashboard API is running ✅"})

@app.route("/api/health", methods=["GET"])
def health():
    database = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        database = "unavailable"
    return jsonify({"status": "ok", "database": database, "email_enabled": EMAIL_ENABLED})

@app.route("/api/register", methods=["POST"])
def register():
    data = json_body()
    email = clean_email(data.get("email"))
    password = data.get("password")
    if not email:
        return error("Please enter a valid email address.", 400)
    if not isinstance(password, str) or len(password) < 8:
        return error("Your password needs at least 8 characters.", 400)
    if len(password) > 128:
        return error("Your password can be at most 128 characters.", 400)

    ip = client_ip()
    if auth_requests_by_ip.blocked(ip):
        return too_many_attempts()
    auth_requests_by_ip.add(ip)

    try:
        if User.query.filter_by(email=email).first():
            return error("An account with this email already exists. Try logging in instead.", 409)
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("An account with this email already exists. Try logging in instead.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Register failed")
        return database_unavailable()

    token = create_jwt({"email": email})
    return jsonify({"message": "registered", "token": token, "email": email})

@app.route("/api/login", methods=["POST"])
def login():
    data = json_body()
    email = clean_email(data.get("email"))
    password = data.get("password")
    if not email:
        return error("Please enter a valid email address.", 400)
    if not isinstance(password, str) or not password:
        return error("Please enter your password.", 400)

    ip = client_ip()
    if auth_requests_by_ip.blocked(ip) or failed_logins_by_email.blocked(email):
        return too_many_attempts()
    auth_requests_by_ip.add(ip)

    try:
        user = User.query.filter_by(email=email).first()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Login failed")
        return database_unavailable()

    if not user or len(password) > 128 or not check_password_hash(user.password_hash, password):
        failed_logins_by_email.add(email)
        return error("That email and password don't match an account.", 401)

    failed_logins_by_email.reset(email)
    token = create_jwt({"email": email})
    return jsonify({"message": "logged_in", "token": token, "email": email})

@app.route("/api/me", methods=["GET"])
def me():
    try:
        user = current_user()
    except SQLAlchemyError:
        db.session.rollback()
        return database_unavailable()
    if not user:
        return unauthorized()
    return jsonify({"email": user.email})

# Data endpoint (raw)
@app.route("/api/data", methods=["GET"])
def get_data():
    df = load_data()
    return jsonify(to_records(df))

# Stats endpoint with filters (start_date, end_date, region, product)
@app.route("/api/stats", methods=["GET"])
def get_stats():
    df = filtered_from_request()
    stats = aggregate_stats(df)
    return jsonify({**stats, "table_data": to_records(df)})

# Exports: CSV
@app.route("/api/export/csv", methods=["GET"])
def export_csv():
    df = filtered_from_request()
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")), mimetype="text/csv", as_attachment=True, download_name="dashboard_data.csv")

# Exports: Excel
@app.route("/api/export/excel", methods=["GET"])
def export_excel():
    df = filtered_from_request()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Dashboard Data")
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="dashboard_data.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# PDF export (POST): expects charts (base64) + summary
@app.route("/api/export/pdf", methods=["POST"])
def export_pdf():
    payload = json_body()
    charts = payload.get("charts") if isinstance(payload.get("charts"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    buffer = build_pdf_buffer(charts, summary)
    return send_file(buffer, as_attachment=True, download_name="dashboard_report.pdf", mimetype="application/pdf")

# Schedule an email (protected route: requires JWT)
@app.route("/api/schedule-email", methods=["POST"])
def schedule_email():
    try:
        user = current_user()
    except SQLAlchemyError:
        db.session.rollback()
        return database_unavailable()
    if not user:
        return unauthorized()

    data = json_body()
    target_email = clean_email(data.get("target_email"))
    if not target_email:
        return error("Please enter a valid email address to send the report to.", 400)
    region = str(data.get("region") or "").strip()[:50] or None
    product = str(data.get("product") or "").strip()[:50] or None
    start = parse_date_arg(data.get("start_date"))
    end = parse_date_arg(data.get("end_date"))
    start_date = start.date().isoformat() if start is not None else None
    end_date = end.date().isoformat() if end is not None else None
    freq = "weekly"  # the only frequency the scheduler supports

    try:
        if ScheduledEmail.query.filter_by(user_email=user.email).count() >= MAX_SCHEDULES_PER_USER:
            return error(f"You already have {MAX_SCHEDULES_PER_USER} scheduled reports, which is the limit.", 400)
        if ScheduledEmail.query.filter_by(target_email=target_email).count() >= MAX_SCHEDULES_PER_TARGET:
            return error("That address already gets the maximum number of scheduled reports.", 400)

        # calculate next_run (simple: next week)
        now = utcnow()
        entry = {
            "user_email": user.email,
            "target_email": target_email,
            "region": region,
            "product": product,
            "start_date": start_date,
            "end_date": end_date,
            "freq": freq,
            "next_run": (now + timedelta(days=7)).isoformat(),
            "created_at": now.isoformat()
        }
        rowid = add_scheduled_email_to_db(entry)
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Saving a schedule failed")
        return database_unavailable()

    # First report shortly after scheduling (demo), then weekly
    add_schedule_job(rowid, target_email, region, product, start_date, end_date,
                     first_run=datetime.now(timezone.utc) + timedelta(seconds=10))

    return jsonify({"message": "scheduled", "id": rowid, "email_enabled": EMAIL_ENABLED})

# Get schedules (admin / user can fetch their schedules)
@app.route("/api/schedules", methods=["GET"])
def api_schedules():
    try:
        user = current_user()
    except SQLAlchemyError:
        db.session.rollback()
        return database_unavailable()
    if not user:
        return unauthorized()
    schedules = get_all_schedules()
    # filter to user's email for safety
    schedules = [s for s in schedules if s["user_email"] == user.email]
    return jsonify({"schedules": schedules})

# Initialize DB & load existing scheduled jobs
def load_existing_schedules_into_jobs():
    for s in get_all_schedules():
        if scheduler.get_job(f"scheduled_email_{s['id']}"):
            continue
        # A next_run in the past is skipped by the scheduler and the job carries on weekly
        # from there, so restarting the server doesn't send everyone an extra email
        if s["next_run"]:
            next_run = datetime.fromisoformat(s["next_run"]).replace(tzinfo=timezone.utc)
        else:
            next_run = datetime.now(timezone.utc) + timedelta(seconds=10)
        add_schedule_job(s["id"], s["target_email"], s["region"], s["product"],
                         s["start_date"], s["end_date"], first_run=next_run)

def init_database():
    """Create the tables if they don't exist yet.

    This used to run only under `python app.py`, so on Render (which starts the app
    another way) the user table was never created and sign up and login failed."""
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database ready (%s)", DB_URI.split(":", 1)[0])
        except Exception:
            logger.exception("Database setup failed, so sign up and login won't work until the database can be reached")
            return
        try:
            load_existing_schedules_into_jobs()
        except Exception:
            logger.exception("Could not load saved email schedules")

init_database()

# -----------------------
# Run app
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
