"""
Face Recognition Attendance System - Web Application Server
Powered by FastAPI, InsightFace, OpenCV, and SQLite.
"""

import os
import io
import json
import base64
import sqlite3
import smtplib
import logging
import traceback
import asyncio
import base64
import hmac
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional

import cv2
import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine
from insightface.app import FaceAnalysis
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import Response as StarletteResponse

# Suppress albumentations check
os.environ["ALBUMENTATIONS_NO_VERSION_CHECK"] = "1"

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
KNOWN_FACES_DIR = os.path.join(DATA_DIR, "known_faces")
ENCODINGS_PATH = os.path.join(DATA_DIR, "encodings.json")
DB_PATH = os.path.join(DATA_DIR, "attendance.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Logger setup
logger = logging.getLogger("attendance_web")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # Render containers run as a non-root user with an immutable /app tree.
    # Keep local file logging for development; stream hosted logs to stdout.
    if DATA_DIR == BASE_DIR:
        log_handler = logging.FileHandler(os.path.join(BASE_DIR, "debug.log"))
    else:
        log_handler = logging.StreamHandler()
    log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(log_handler)

app = FastAPI(
    title="Face Recognition Attendance System",
    description="Automated AI-powered attendance tracking with real-time recognition and email reporting",
    version="2.0.0"
)

@app.middleware("http")
async def require_role_auth(request, call_next):
    """Authenticate admins and faculty; enforce faculty's kiosk-only access."""
    path = request.url.path
    if path == "/api/health":
        return await call_next(request)

    admin_username = os.environ.get("ADMIN_USERNAME", "")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    faculty_username = os.environ.get("FACULTY_USERNAME", "")
    faculty_password = os.environ.get("FACULTY_PASSWORD", "")
    if not admin_username or not admin_password:
        return StarletteResponse("Admin credentials are not configured.", status_code=503)

    auth = request.headers.get("authorization", "")
    try:
        scheme, token = auth.split(" ", 1)
        supplied_user, supplied_pass = base64.b64decode(token, validate=True).decode("utf-8").split(":", 1)
    except Exception:
        scheme, supplied_user, supplied_pass = "", "", ""

    role = None
    if scheme.lower() == "basic":
        if (hmac.compare_digest(supplied_user, admin_username)
                and hmac.compare_digest(supplied_pass, admin_password)):
            role = "admin"
        elif (faculty_username and faculty_password
                and hmac.compare_digest(supplied_user, faculty_username)
                and hmac.compare_digest(supplied_pass, faculty_password)):
            role = "faculty"

    if role is None:
        return StarletteResponse(
            "Authentication required.", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Attendance System", charset="UTF-8"'},
        )

    request.state.user_role = role
    if role == "faculty":
        allowed = (
            path == "/"
            or path == "/api/me"
            or path == "/api/recognize_frame"
            or path.startswith("/static/")
        )
        if not allowed:
            return JSONResponse({"detail": "Faculty accounts can only use the attendance kiosk."}, status_code=403)
    return await call_next(request)

# Global model state
face_app: Optional[FaceAnalysis] = None
encodings_cache = {"names": [], "embeddings": []}

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attendance
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  date TEXT NOT NULL,
                  time_in TEXT NOT NULL,
                  UNIQUE(name, date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (name TEXT PRIMARY KEY,
                  email TEXT NOT NULL UNIQUE)''')
    conn.commit()
    conn.close()

def load_encodings():
    global encodings_cache
    if os.path.exists(ENCODINGS_PATH):
        try:
            with open(ENCODINGS_PATH, "r") as f:
                data = json.load(f)
                data["embeddings"] = [np.array(emb, dtype=np.float32) for emb in data.get("embeddings", [])]
                encodings_cache = data
                logger.info(f"Loaded {len(data['names'])} embeddings from {ENCODINGS_PATH}")
                return data
        except Exception as e:
            logger.error(f"Error loading {ENCODINGS_PATH}: {e}")
    encodings_cache = {"names": [], "embeddings": []}
    return encodings_cache

def save_encodings(data):
    global encodings_cache
    try:
        data_to_save = {
            "names": data["names"],
            "embeddings": [emb.tolist() if isinstance(emb, np.ndarray) else emb for emb in data["embeddings"]]
        }
        with open(ENCODINGS_PATH, "w") as f:
            json.dump(data_to_save, f)
        encodings_cache = {
            "names": data["names"],
            "embeddings": [np.array(emb, dtype=np.float32) for emb in data["embeddings"]]
        }
        logger.info(f"Saved {len(data['names'])} embeddings to {ENCODINGS_PATH}")
    except Exception as e:
        logger.error(f"Error saving {ENCODINGS_PATH}: {e}")
        raise e

def load_email_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading config.json: {e}")
    return {
        "SENDER_EMAIL": "",
        "SENDER_PASSWORD": "",
        "FACULTY_EMAIL": "",
        "SMTP_SERVER": "smtp.gmail.com",
        "SMTP_PORT": 587,
        "COSINE_THRESHOLD": 0.40
    }

def save_email_config(config_dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config_dict, f, indent=2)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Error saving config.json: {e}")
        raise e

def purge_old_attendance(hours: int = 24) -> int:
    """Delete attendance records older than specified hours (default 24h)."""
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM attendance WHERE (date || ' ' || time_in) < ?", (cutoff_str,))
        deleted_count = c.rowcount
        conn.commit()
        conn.close()
        if deleted_count > 0:
            logger.info(f"Purged {deleted_count} attendance records older than {hours}h (cutoff: {cutoff_str}).")
        return deleted_count
    except Exception as e:
        logger.error(f"Error purging old attendance records: {e}")
        return 0

# Startup event
@app.on_event("startup")
async def startup_event():
    global face_app
    init_db()
    load_encodings()
    recognition_setting = os.environ.get("ENABLE_FACE_RECOGNITION")
    if recognition_setting is None:
        enabled = DATA_DIR == BASE_DIR  # local development defaults on; hosted /data deployments default off
    else:
        enabled = recognition_setting.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.warning("Face recognition is disabled by deployment configuration.")
        return
    logger.info("Initializing InsightFace engine...")
    try:
        face_app = FaceAnalysis(providers=['CPUExecutionProvider'])
        face_app.prepare(ctx_id=0, det_size=(160, 160))
        logger.info("InsightFace ready.")
    except Exception as e:
        logger.error(f"Failed to initialize InsightFace: {e}\n{traceback.format_exc()}")

# Models
class FrameRecognitionRequest(BaseModel):
    image: str  # data:image/jpeg;base64,...
    threshold: Optional[float] = None

class RegisterStudentRequest(BaseModel):
    name: str
    email: str
    images: List[str]  # list of base64 data URLs

class ConfigUpdateRequest(BaseModel):
    SENDER_EMAIL: str
    SENDER_PASSWORD: Optional[str] = None
    FACULTY_EMAIL: str
    SMTP_SERVER: Optional[str] = "smtp.gmail.com"
    SMTP_PORT: Optional[int] = 587
    COSINE_THRESHOLD: Optional[float] = 0.40

class ManualAttendanceRequest(BaseModel):
    name: str
    date: Optional[str] = None
    time_in: Optional[str] = None

class SQLQueryRequest(BaseModel):
    query: str

class TestEmailRequest(BaseModel):
    recipient: str

def decode_base64_image(b64_str: str) -> np.ndarray:
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_str)
    np_arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return img

# Endpoints

@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "face_recognition": "enabled" if face_app is not None else "disabled",
    }

@app.get("/api/me")
def current_user(request: Request):
    """Return the signed-in role so the browser can show the correct dashboard."""
    return {"role": getattr(request.state, "user_role", "admin")}

@app.post("/api/attendance/purge")
def api_purge_attendance(hours: Optional[int] = 24):
    count = purge_old_attendance(hours=hours or 24)
    return {
        "success": True,
        "deleted_count": count,
        "message": f"Successfully purged {count} attendance records older than {hours or 24} hours."
    }

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Total students registered
    c.execute("SELECT COUNT(*) FROM students")
    total_students = c.fetchone()[0]
    
    # Present today
    c.execute("SELECT COUNT(DISTINCT name) FROM attendance WHERE date = ?", (today,))
    present_today = c.fetchone()[0]
    
    # All-time logs
    c.execute("SELECT COUNT(*) FROM attendance")
    total_records = c.fetchone()[0]
    
    # Recent logs
    c.execute("SELECT name, date, time_in FROM attendance ORDER BY id DESC LIMIT 5")
    recent = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    rate = round((present_today / total_students * 100), 1) if total_students > 0 else 0
    return {
        "total_students": total_students,
        "present_today": present_today,
        "absent_today": max(0, total_students - present_today),
        "attendance_rate": rate,
        "total_records": total_records,
        "recent_logs": recent
    }

@app.post("/api/recognize_frame")
def recognize_frame(payload: FrameRecognitionRequest):
    global face_app, encodings_cache
    if face_app is None:
        raise HTTPException(status_code=503, detail="Face recognition model not loaded yet.")

    try:
        frame = decode_base64_image(payload.image)
        if frame is None:
            raise HTTPException(status_code=400, detail="Invalid image payload.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image decoding failed: {e}")

    # Downscale for fast detection
    h, w = frame.shape[:2]
    small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)

    try:
        faces = face_app.get(small_frame)
    except Exception as e:
        logger.error(f"Inference error: {e}")
        return {"faces": [], "error": str(e)}

    config = load_email_config()
    threshold = payload.threshold or config.get("COSINE_THRESHOLD", 0.40)

    results = []
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")

    conn = get_db()
    c = conn.cursor()

    for face in faces:
        bbox = face.bbox.astype(int)
        # Scale bbox back to original frame coordinates
        x1, y1, x2, y2 = [int(v * 2) for v in bbox]
        x1 = max(0, min(x1, w))
        y1 = max(0, min(y1, h))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))

        emb = face.embedding
        name = "Unknown"
        min_dist = 1.0

        if encodings_cache["names"]:
            for j, known_emb in enumerate(encodings_cache["embeddings"]):
                dist = cosine(emb, known_emb)
                if dist < min_dist and dist < threshold:
                    min_dist = float(dist)
                    name = encodings_cache["names"][j]

        logged_now = False
        already_logged = False

        if name != "Unknown":
            # Check SQLite
            c.execute("SELECT id, time_in FROM attendance WHERE name = ? AND date = ?", (name, today))
            existing = c.fetchone()
            if existing:
                already_logged = True
            else:
                try:
                    c.execute("INSERT INTO attendance (name, date, time_in) VALUES (?, ?, ?)", (name, today, now_time))
                    conn.commit()
                    logged_now = True
                    logger.info(f"Logged attendance via web for {name} at {now_time}")
                except sqlite3.IntegrityError:
                    already_logged = True
                except Exception as e:
                    logger.error(f"DB error logging attendance for {name}: {e}")

        confidence = round(max(0.0, (1.0 - min_dist) * 100), 1) if name != "Unknown" else 0.0

        results.append({
            "name": name,
            "bbox": [x1, y1, x2, y2],
            "distance": round(min_dist, 4) if min_dist != 1.0 else None,
            "confidence": confidence,
            "logged_now": logged_now,
            "already_logged": already_logged,
            "time_in": now_time if logged_now else None
        })

    conn.close()
    return {"faces": results, "timestamp": now_time}

@app.post("/api/register_student")
def register_student(payload: RegisterStudentRequest):
    global face_app, encodings_cache
    if face_app is None:
        raise HTTPException(status_code=503, detail="Face recognition model not loaded yet.")

    name = payload.name.strip()
    email = payload.email.strip().lower()

    if not name or " " in name:
        raise HTTPException(status_code=400, detail="Student name must not be empty or contain spaces.")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if not payload.images or len(payload.images) == 0:
        raise HTTPException(status_code=400, detail="At least one face image is required.")

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO students (name, email) VALUES (?, ?)", (name, email))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error registering student: {e}")
    conn.close()

    # Save images and extract embeddings
    student_dir = os.path.join(KNOWN_FACES_DIR, name)
    os.makedirs(student_dir, exist_ok=True)

    data = load_encodings()
    new_names = list(data["names"])
    new_embeddings = list(data["embeddings"])

    encoded_count = 0
    errors = []

    for idx, img_b64 in enumerate(payload.images):
        try:
            frame = decode_base64_image(img_b64)
            if frame is None:
                errors.append(f"Image {idx+1} could not be decoded.")
                continue

            # Save full image file
            filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx+1}.jpg"
            img_path = os.path.join(student_dir, filename)
            cv2.imwrite(img_path, frame)

            faces = face_app.get(frame)
            if not faces:
                # Try with 1.5x scale
                faces = face_app.get(cv2.resize(frame, (0, 0), fx=1.5, fy=1.5))

            if faces:
                # Pick the largest face if multiple
                best_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                new_names.append(name)
                new_embeddings.append(best_face.embedding)
                encoded_count += 1
            else:
                errors.append(f"No face detected in capture {idx+1}.")
        except Exception as e:
            errors.append(f"Error on capture {idx+1}: {str(e)}")

    if encoded_count > 0:
        data["names"] = new_names
        data["embeddings"] = new_embeddings
        save_encodings(data)
        logger.info(f"Registered student {name} with {encoded_count} face embeddings.")
        return {
            "success": True,
            "name": name,
            "email": email,
            "embeddings_added": encoded_count,
            "total_student_embeddings": new_names.count(name),
            "warnings": errors
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"No faces could be detected in any of the provided images. {', '.join(errors)}"
        )

@app.get("/api/students")
def list_students():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, email FROM students ORDER BY name ASC")
    students = [dict(row) for row in c.fetchall()]
    today = datetime.now().strftime("%Y-%m-%d")

    data = load_encodings()
    names_list = data.get("names", [])

    results = []
    for s in students:
        s_name = s["name"]
        # Check today's attendance
        c.execute("SELECT time_in FROM attendance WHERE name = ? AND date = ?", (s_name, today))
        att_row = c.fetchone()
        
        # Check sample photo
        student_dir = os.path.join(KNOWN_FACES_DIR, s_name)
        photo_url = None
        if os.path.exists(student_dir):
            files = [f for f in os.listdir(student_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if files:
                photo_url = f"/api/students/{s_name}/photo"

        results.append({
            "name": s_name,
            "email": s["email"],
            "embeddings_count": names_list.count(s_name),
            "present_today": att_row is not None,
            "time_in": att_row["time_in"] if att_row else None,
            "photo_url": photo_url
        })

    conn.close()
    return results

@app.get("/api/students/{name}/photo")
def get_student_photo(name: str):
    student_dir = os.path.join(KNOWN_FACES_DIR, name)
    if os.path.exists(student_dir):
        files = sorted([f for f in os.listdir(student_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if files:
            return FileResponse(os.path.join(student_dir, files[0]))
    raise HTTPException(status_code=404, detail="Photo not found")

@app.delete("/api/students/{name}")
def remove_student(name: str):
    student_name = name.strip()
    data = load_encodings()

    new_names = []
    new_embeddings = []
    removed = False

    for n, emb in zip(data["names"], data["embeddings"]):
        if n.lower() != student_name.lower():
            new_names.append(n)
            new_embeddings.append(emb)
        else:
            removed = True

    if removed:
        data["names"] = new_names
        data["embeddings"] = new_embeddings
        save_encodings(data)

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE LOWER(name) = LOWER(?)", (student_name,))
    conn.commit()
    conn.close()

    # Also remove known_faces folder if exists
    student_dir = os.path.join(KNOWN_FACES_DIR, student_name)
    if os.path.exists(student_dir):
        try:
            for f in os.listdir(student_dir):
                os.remove(os.path.join(student_dir, f))
            os.rmdir(student_dir)
        except Exception as e:
            logger.warning(f"Could not remove directory {student_dir}: {e}")

    logger.info(f"Student {student_name} removed.")
    return {"success": True, "message": f"Student '{student_name}' successfully removed."}

@app.get("/api/attendance")
def get_attendance(
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    name: Optional[str] = None
):
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT a.id, a.name, s.email, a.date, a.time_in 
        FROM attendance a 
        LEFT JOIN students s ON a.name = s.name 
        WHERE 1=1
    """
    params = []
    if date:
        query += " AND a.date = ?"
        params.append(date)
    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)
    if name:
        query += " AND LOWER(a.name) LIKE ?"
        params.append(f"%{name.lower()}%")

    query += " ORDER BY a.date DESC, a.time_in DESC"
    c.execute(query, params)
    records = [dict(row) for row in c.fetchall()]
    conn.close()
    return records

@app.post("/api/attendance/manual")
def manual_attendance(payload: ManualAttendanceRequest):
    name = payload.name.strip()
    date_val = payload.date or datetime.now().strftime("%Y-%m-%d")
    time_val = payload.time_in or datetime.now().strftime("%H:%M:%S")

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO attendance (name, date, time_in) VALUES (?, ?, ?)", (name, date_val, time_val))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Attendance logged for {name} on {date_val} at {time_val}"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail=f"{name} already has attendance logged for {date_val}.")
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/attendance/{record_id}")
def delete_attendance_record(record_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM attendance WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/attendance/export")
def export_attendance_csv(date: Optional[str] = None):
    conn = get_db()
    query = """
        SELECT a.id, a.name, COALESCE(s.email, '') as email, a.date, a.time_in 
        FROM attendance a 
        LEFT JOIN students s ON a.name = s.name 
    """
    params = []
    if date:
        query += " WHERE a.date = ?"
        params.append(date)
    query += " ORDER BY a.date DESC, a.time_in DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode('utf-8')

    filename = f"attendance_report_{date or 'all'}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/config")
def get_config():
    cfg = load_email_config()
    # Mask password for safety
    masked_pw = "********" if cfg.get("SENDER_PASSWORD") else ""
    return {
        "SENDER_EMAIL": cfg.get("SENDER_EMAIL", ""),
        "SENDER_PASSWORD_SET": bool(cfg.get("SENDER_PASSWORD")),
        "SENDER_PASSWORD_MASKED": masked_pw,
        "FACULTY_EMAIL": cfg.get("FACULTY_EMAIL", ""),
        "SMTP_SERVER": cfg.get("SMTP_SERVER", "smtp.gmail.com"),
        "SMTP_PORT": int(cfg.get("SMTP_PORT", 587)),
        "COSINE_THRESHOLD": float(cfg.get("COSINE_THRESHOLD", 0.40))
    }

@app.post("/api/config")
def update_config(payload: ConfigUpdateRequest):
    existing = load_email_config()
    pw = payload.SENDER_PASSWORD if payload.SENDER_PASSWORD and payload.SENDER_PASSWORD.strip() != "********" else existing.get("SENDER_PASSWORD", "")

    new_cfg = {
        "SENDER_EMAIL": payload.SENDER_EMAIL.strip(),
        "SENDER_PASSWORD": pw,
        "FACULTY_EMAIL": payload.FACULTY_EMAIL.strip(),
        "SMTP_SERVER": payload.SMTP_SERVER.strip() or "smtp.gmail.com",
        "SMTP_PORT": int(payload.SMTP_PORT or 587),
        "COSINE_THRESHOLD": float(payload.COSINE_THRESHOLD or 0.40)
    }
    save_email_config(new_cfg)
    return {"success": True, "message": "Email settings saved successfully."}

def send_smtp_email(sender, password, receiver, subject, body, attachment_content=None, attachment_name=None, smtp_server="smtp.gmail.com", smtp_port=587):
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    if attachment_content and attachment_name:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_content)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{attachment_name}"')
        msg.attach(part)

    with smtplib.SMTP(smtp_server, smtp_port, timeout=12) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())

@app.post("/api/email/test")
def test_email(payload: TestEmailRequest):
    cfg = load_email_config()
    sender = cfg.get("SENDER_EMAIL")
    password = cfg.get("SENDER_PASSWORD")
    server = cfg.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(cfg.get("SMTP_PORT", 587))

    if not sender or not password:
        raise HTTPException(status_code=400, detail="Sender email and password are not configured.")

    recipient = payload.recipient.strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=400, detail="Invalid test recipient email.")

    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_smtp_email(
            sender=sender,
            password=password,
            receiver=recipient,
            subject=f"Face Attendance System - Test Email ({now_str})",
            body=f"Hello!\n\nThis is a verification email from the Face Recognition Attendance System.\nSMTP configuration is working correctly!\n\nTimestamp: {now_str}",
            smtp_server=server,
            smtp_port=port
        )
        return {"success": True, "message": f"Test email sent successfully to {recipient}."}
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Auth error: {e}")
        raise HTTPException(status_code=401, detail=f"SMTP Authentication failed. For Gmail, please use an App Password instead of regular password.")
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@app.post("/api/email/report")
def send_attendance_report(date: Optional[str] = None):
    cfg = load_email_config()
    sender = cfg.get("SENDER_EMAIL")
    password = cfg.get("SENDER_PASSWORD")
    receiver = cfg.get("FACULTY_EMAIL")
    server = cfg.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(cfg.get("SMTP_PORT", 587))

    if not sender or not password or not receiver:
        raise HTTPException(status_code=400, detail="Incomplete email configuration (Sender, Password, or Faculty receiver email missing).")

    report_date = date or datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT a.name, s.email, a.date, a.time_in 
        FROM attendance a 
        LEFT JOIN students s ON a.name = s.name 
        WHERE a.date = ? 
        ORDER BY a.time_in ASC
    """, (report_date,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No attendance records found for {report_date}.")

    df = pd.DataFrame([dict(r) for r in rows], columns=["name", "email", "date", "time_in"])
    df.columns = ["Student Name", "Email", "Date", "Check-in Time"]

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode('utf-8')

    subject = f"Daily Attendance Report - {report_date}"
    body = (
        f"Dear Faculty,\n\n"
        f"Attached is the daily attendance report for {report_date}.\n"
        f"Total attendees marked: {len(rows)}\n\n"
        f"Best regards,\n"
        f"Face Recognition Attendance System"
    )

    try:
        send_smtp_email(
            sender=sender,
            password=password,
            receiver=receiver,
            subject=subject,
            body=body,
            attachment_content=csv_bytes,
            attachment_name=f"attendance_report_{report_date}.csv",
            smtp_server=server,
            smtp_port=port
        )
        logger.info(f"Attendance report for {report_date} emailed to {receiver}")
        return {
            "success": True,
            "message": f"Attendance report for {report_date} successfully sent to {receiver} ({len(rows)} records)."
        }
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Auth error: {e}")
        raise HTTPException(status_code=401, detail="SMTP Authentication failed. For Gmail, please use an App Password.")
    except Exception as e:
        logger.error(f"Email report failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@app.post("/api/query")
def execute_sql(payload: SQLQueryRequest):
    q = payload.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query.")
    
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(q)
        if q.upper().startswith("SELECT") or q.upper().startswith("PRAGMA") or q.upper().startswith("EXPLAIN"):
            columns = [desc[0] for desc in c.description] if c.description else []
            rows = [dict(zip(columns, row)) for row in c.fetchall()]
            conn.close()
            return {"type": "select", "columns": columns, "rows": rows, "count": len(rows)}
        else:
            affected = c.rowcount
            conn.commit()
            conn.close()
            return {"type": "mutation", "affected_rows": affected, "message": "Query executed successfully."}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"SQL Execution Error: {str(e)}")

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Face Recognition Attendance API is running. UI loading..."}
