print("Starting script execution...")
import cv2
print("Imported cv2")
import pandas as pd
import os
import json
import numpy as np
from datetime import datetime, timedelta
from insightface.app import FaceAnalysis
from scipy.spatial.distance import cosine
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
import io
import queue
import traceback

# Suppress albumentations SSL version check
print("Setting ALBUMENTATIONS_NO_VERSION_CHECK...")
os.environ["ALBUMENTATIONS_NO_VERSION_CHECK"] = "1"

# Setup logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Paths
KNOWN_FACES_DIR = "known_faces"
ENCODINGS_PATH = "encodings.json"
DB_PATH = "attendance.db"
CONFIG_PATH = "config.json"

class AttendanceSystem:
    def __init__(self):
        print("Initializing AttendanceSystem...")
        self.cap = None
        self.data = {"names": [], "embeddings": []}
        self.conn = self.initialize_db()
        self.attendance_queue = queue.Queue()
        self.sender_email = None
        self.sender_password = None
        self.faculty_email = None
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 587
        self.load_email_config()

    def load_email_config(self):
        """Load email config from config.json or prompt if missing."""
        print("Loading email configuration...")
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                    self.sender_email = config.get('SENDER_EMAIL')
                    self.sender_password = config.get('SENDER_PASSWORD')
                    self.faculty_email = config.get('FACULTY_EMAIL')
                    self.smtp_server = config.get('SMTP_SERVER', 'smtp.gmail.com')
                    self.smtp_port = int(config.get('SMTP_PORT', 587))
                    if not self.sender_email or not self.sender_password or not self.faculty_email:
                        logging.warning("Invalid or incomplete config.json. Prompting for new details.")
                        print("Warning: config.json is invalid or incomplete.")
                        self.update_email_config()
                    else:
                        print(f"Current email settings:\nSender: {self.sender_email}\nFaculty/Receiver: {self.faculty_email}\nSMTP: {self.smtp_server}:{self.smtp_port}")
                        confirm = input("Use these settings? (y/n): ").strip().lower()
                        if confirm != 'y':
                            self.update_email_config()
                        else:
                            logging.info(f"Loaded email config from {CONFIG_PATH}: Sender={self.sender_email}, Receiver={self.faculty_email}, SMTP={self.smtp_server}:{self.smtp_port}")
                            print(f"Loaded email config from {CONFIG_PATH}")
            else:
                logging.info("No config.json found. Prompting for email details.")
                print("No config.json found. Prompting for email details.")
                self.update_email_config()
        except Exception as e:
            logging.error(f"Error loading config.json: {e}")
            print(f"Error loading config.json: {e}. Prompting for email details.")
            self.update_email_config()

    def update_email_config(self):
        """Prompt for email details and save to config.json."""
        print("Updating email configuration...")
        try:
            self.sender_email = input("Sender Email (e.g., sender@example.com): ").strip()
            self.sender_password = input("Sender Password (e.g., Gmail app-specific password): ").strip()
            self.faculty_email = input("Faculty/Receiver Email (e.g., faculty@example.com): ").strip()
            self.smtp_server = input("SMTP Server (e.g., smtp.gmail.com): ").strip() or 'smtp.gmail.com'
            self.smtp_port = input("SMTP Port (e.g., 587): ").strip() or '587'
            try:
                self.smtp_port = int(self.smtp_port)
            except ValueError:
                logging.error("Invalid SMTP_PORT. Using default 587.")
                print("Error: Invalid SMTP_PORT. Using default 587.")
                self.smtp_port = 587

            if not self.sender_email or not self.sender_password or not self.faculty_email:
                logging.error("SENDER_EMAIL, SENDER_PASSWORD, or FACULTY_EMAIL not provided.")
                print("Error: SENDER_EMAIL, SENDER_PASSWORD, or FACULTY_EMAIL not provided.")
                exit(1)

            config = {
                "SENDER_EMAIL": self.sender_email,
                "SENDER_PASSWORD": self.sender_password,
                "FACULTY_EMAIL": self.faculty_email,
                "SMTP_SERVER": self.smtp_server,
                "SMTP_PORT": self.smtp_port
            }
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
            os.chmod(CONFIG_PATH, 0o600)
            logging.info(f"Saved email config to {CONFIG_PATH}")
            print(f"Saved email config to {CONFIG_PATH}")
        except Exception as e:
            logging.error(f"Error saving email config: {e}")
            print(f"Error saving email config: {e}")
            exit(1)

    def initialize_db(self):
        """Create or load SQLite database with attendance and students tables."""
        print("Initializing database...")
        try:
            db_dir = os.path.dirname(DB_PATH) or '.'
            if not os.access(db_dir, os.W_OK):
                os.chmod(db_dir, 0o700)
                logging.warning(f"Updated permissions for directory {db_dir}")
                print(f"Updated permissions for {db_dir}")

            if os.path.exists(DB_PATH) and not os.access(DB_PATH, os.W_OK):
                os.chmod(DB_PATH, 0o600)
                logging.warning(f"Updated permissions for {DB_PATH}")
                print(f"Updated permissions for {DB_PATH}")

            conn = sqlite3.connect(DB_PATH, timeout=10)
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
            
            # Automatically delete previous records older than 24 hours
            try:
                cutoff = datetime.now() - timedelta(hours=24)
                cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
                c.execute("DELETE FROM attendance WHERE (date || ' ' || time_in) < ?", (cutoff_str,))
                deleted = c.rowcount
                conn.commit()
                if deleted > 0:
                    logging.info(f"Purged {deleted} attendance records older than 24 hours.")
                    print(f"Auto-purged {deleted} attendance records older than 24 hours.")
            except Exception as e:
                logging.warning(f"Could not purge old records: {e}")

            logging.info(f"Initialized database at {DB_PATH}")
            print(f"Initialized database at {DB_PATH}")
            return conn
        except Exception as e:
            logging.error(f"Error initializing database: {e}")
            print(f"Error initializing database: {e}")
            exit(1)

    def purge_old_attendance(self, hours=24):
        """Purge attendance records older than specified hours (default 24h)."""
        try:
            cutoff = datetime.now() - timedelta(hours=hours)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
            c = self.conn.cursor()
            c.execute("DELETE FROM attendance WHERE (date || ' ' || time_in) < ?", (cutoff_str,))
            deleted = c.rowcount
            self.conn.commit()
            if deleted > 0:
                print(f"Purged {deleted} attendance records older than {hours} hours.")
                logging.info(f"Purged {deleted} attendance records older than {hours} hours.")
            return deleted
        except Exception as e:
            logging.error(f"Error purging old attendance: {e}")
            return 0

    def load_encodings(self):
        """Load face embeddings from JSON file."""
        print("Loading encodings...")
        try:
            if os.path.exists(ENCODINGS_PATH):
                with open(ENCODINGS_PATH, "r") as f:
                    data = json.load(f)
                    data["embeddings"] = [np.array(emb) for emb in data["embeddings"]]
                    logging.info(f"Loaded {len(data['names'])} embeddings from {ENCODINGS_PATH}")
                    print(f"Loaded {len(data['names'])} embeddings from {ENCODINGS_PATH}")
                    return data
            logging.info(f"No existing {ENCODINGS_PATH}. Starting fresh.")
            print(f"No existing {ENCODINGS_PATH}. Starting fresh.")
            return {"names": [], "embeddings": []}
        except Exception as e:
            logging.error(f"Error loading {ENCODINGS_PATH}: {e}")
            print(f"Error loading {ENCODINGS_PATH}: {e}")
            return {"names": [], "embeddings": []}

    def save_encodings(self, data):
        """Save embeddings to JSON file."""
        print("Saving encodings...")
        try:
            data_to_save = {
                "names": data["names"],
                "embeddings": [emb.tolist() for emb in data["embeddings"]]
            }
            with open(ENCODINGS_PATH, "w") as f:
                json.dump(data_to_save, f)
            logging.info(f"Saved {len(data['names'])} embeddings to {ENCODINGS_PATH}")
            print(f"Saved {len(data['names'])} embeddings to {ENCODINGS_PATH}")
        except Exception as e:
            logging.error(f"Error saving {ENCODINGS_PATH}: {e}")
            print(f"Error saving encodings: {e}")

    def remove_student(self, student_name):
        """Remove student from encodings.json and students table."""
        print(f"Removing student: {student_name}")
        try:
            self.data = self.load_encodings()
            if not self.data["names"]:
                print(f"No students registered in {ENCODINGS_PATH}.")
                logging.info(f"No students registered in {ENCODINGS_PATH}.")
                return False

            new_names = []
            new_embeddings = []
            removed = False
            for name, embedding in zip(self.data["names"], self.data["embeddings"]):
                if name.lower() != student_name.lower():
                    new_names.append(name)
                    new_embeddings.append(embedding)
                else:
                    removed = True

            if not removed:
                print(f"No encodings found for student '{student_name}'.")
                logging.info(f"No encodings found for student '{student_name}'.")
                return False

            self.data["names"] = new_names
            self.data["embeddings"] = new_embeddings
            self.save_encodings(self.data)

            c = self.conn.cursor()
            c.execute("DELETE FROM students WHERE name = ?", (student_name,))
            self.conn.commit()
            print(f"Successfully removed '{student_name}' from encodings and students table.")
            logging.info(f"Removed '{student_name}' from encodings and students table.")
            return True
        except Exception as e:
            logging.error(f"Error removing student {student_name}: {e}")
            print(f"Error removing student {student_name}: {e}")
            return False

    def run_sql_query(self, query):
        """Execute a custom SQL query on the database."""
        print(f"Executing SQL query: {query}")
        try:
            c = self.conn.cursor()
            c.execute(query)
            if query.strip().upper().startswith("SELECT"):
                rows = c.fetchall()
                if not rows:
                    print("No results found.")
                    logging.info("SQL query returned no results.")
                    return []
                print("\nQuery Results:")
                for row in rows:
                    print(row)
                logging.info(f"Executed SELECT query: {query}")
                return rows
            else:
                self.conn.commit()
                print("Query executed successfully.")
                logging.info(f"Executed query: {query}")
                return True
        except Exception as e:
            logging.error(f"Error executing query '{query}': {e}")
            print(f"Error executing query: {e}")
            return False

    def log_attendance(self, name, login_time):
        """Log attendance to SQLite, avoiding duplicates for the same day."""
        print(f"Logging attendance for {name}...")
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            c = self.conn.cursor()
            c.execute("SELECT * FROM attendance WHERE name = ? AND date = ?", (name, today))
            if c.fetchone():
                logging.info(f"{name} already logged today.")
                print(f"{name} already logged today.")
                return False
            c.execute("INSERT INTO attendance (name, date, time_in) VALUES (?, ?, ?)",
                      (name, today, login_time.strftime("%H:%M:%S")))
            self.conn.commit()
            logging.info(f"Logged attendance for {name} at {login_time.strftime('%H:%M:%S')}")
            print(f"Logged attendance for {name} at {login_time.strftime('%H:%M:%S')}")
            return True
        except Exception as e:
            logging.error(f"Error logging attendance for {name}: {e}")
            print(f"Error logging attendance: {e}")
            return False

    def try_open_webcam(self):
        """Try opening webcam with different indices and macOS-specific backend."""
        print("Trying to open webcam...")
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            cv2.destroyAllWindows()
            logging.info("Released previous webcam and windows.")
        indices = [0, 1, -1, 2, 3, 4, 5, 6, 7, 8]
        backends = [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
        for backend in backends:
            backend_name = "CAP_AVFOUNDATION" if backend == cv2.CAP_AVFOUNDATION else "CAP_ANY"
            for index in indices:
                print(f"Attempting to open webcam with index {index} and backend {backend_name}...")
                logging.info(f"Attempting webcam index {index} with backend {backend_name}")
                cap = cv2.VideoCapture(index, backend)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        logging.info(f"Webcam opened successfully with index {index} and backend {backend_name}")
                        print(f"Webcam opened with index {index} and backend {backend_name}")
                        logging.info(f"Webcam properties: FPS={cap.get(cv2.CAP_PROP_FPS)}, Width={cap.get(cv2.CAP_PROP_FRAME_WIDTH)}, Height={cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
                        return cap
                    else:
                        logging.warning(f"Failed to capture test frame with index {index} and backend {backend_name}")
                        print(f"Failed to capture test frame with index {index} and backend {backend_name}")
                        cap.release()
                else:
                    logging.warning(f"Failed to open webcam with index {index} and backend {backend_name}")
                    print(f"Failed to open webcam with index {index} and backend {backend_name}")
                    cap.release()
        logging.error("Failed to open webcam with any index or backend.")
        print("Error: Could not open webcam with any index or backend.")
        return None

    def cleanup(self):
        """Clean up webcam and OpenCV resources."""
        print("Cleaning up resources...")
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        cv2.destroyAllWindows()
        logging.info("Cleaned up webcam and OpenCV resources.")
        print("Cleaned up webcam and OpenCV resources.")

    def register_student(self, student_name):
        """Register a student by capturing face images and storing email."""
        print(f"Registering student: {student_name}")
        if not student_name or ' ' in student_name:
            print("Error: Student name must not be empty or contain spaces.")
            logging.warning("Invalid student name entered.")
            return

        student_email = input("Enter student's email (e.g., student@example.com): ").strip()
        if not student_email or '@' not in student_email:
            print("Error: Invalid email format.")
            logging.warning(f"Invalid email format for {student_name}: {student_email}")
            return

        try:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO students (name, email) VALUES (?, ?)", (student_name, student_email))
            self.conn.commit()
            logging.info(f"Registered student {student_name} with email {student_email}")
            print(f"Registered student {student_name} with email {student_email}")
        except sqlite3.IntegrityError as e:
            logging.error(f"Email {student_email} already registered for another student: {e}")
            print(f"Error: Email {student_email} is already registered for another student.")
            return
        except Exception as e:
            logging.error(f"Error registering student {student_name} with email {student_email}: {e}")
            print(f"Error registering student with email: {e}")
            return

        student_dir = os.path.join(KNOWN_FACES_DIR, student_name)
        try:
            if not os.path.exists(student_dir):
                os.makedirs(student_dir)
                logging.info(f"Created directory: {student_dir}")
                print(f"Created directory: {student_dir}")
        except OSError as e:
            logging.error(f"Error creating directory {student_dir}: {e}")
            print(f"Error creating directory: {e}")
            return

        app = FaceAnalysis(providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(160, 160))
        self.cap = self.try_open_webcam()
        if not self.cap:
            logging.error("Webcam initialization failed for registration.")
            print("Error: Webcam initialization failed.")
            return

        print("Press 'c' to capture face, 'q' to stop registration.")
        frame_count = 0
        while True:
            ret, frame = self.cap.read()
            frame_count += 1
            if not ret or frame is None:
                logging.error(f"Failed to capture frame {frame_count}. Ret: {ret}, Frame: {frame}")
                print(f"Error: Failed to capture frame {frame_count}.")
                break

            small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            try:
                faces = app.get(small_frame)
                for face in faces:
                    bbox = face.bbox.astype(int)
                    bbox = [int(x * 2) for x in bbox]
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                    cv2.putText(frame, "Face Detected", (bbox[0], bbox[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                if not faces:
                    print("No face detected. Ensure clear face and good lighting.")

                cv2.imshow("Register Student", frame)
                key = cv2.waitKey(10) & 0xFF
                if key == ord('c') and faces:
                    img_path = os.path.join(student_dir, f"{student_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
                    try:
                        cv2.imwrite(img_path, frame)
                        reloaded_frame = cv2.imread(img_path)
                        if reloaded_frame is None:
                            print(f"Error: Failed to reload image {img_path}")
                            logging.error(f"Failed to reload image {img_path}")
                            continue
                        faces = app.get(reloaded_frame)
                        if faces:
                            self.data["names"].append(student_name)
                            self.data["embeddings"].append(faces[0].embedding)
                            print(f"Encoded image for {student_name}")
                            logging.info(f"Encoded image for {student_name}")
                        else:
                            print("No face detected in saved image.")
                            logging.warning("No face detected in saved image.")
                    except Exception as e:
                        print(f"Error processing image: {e}")
                        logging.error(f"Error processing image {img_path}: {e}")
                elif key == ord('q'):
                    if self.data["names"]:
                        self.save_encodings(self.data)
                        print(f"Registered {student_name} with embeddings.")
                    break
            except Exception as e:
                print(f"Error processing frame {frame_count}: {e}")
                logging.error(f"Error processing frame {frame_count}: {e}")
                break

        self.cleanup()

    def recognize_faces(self):
        """Recognize multiple faces in real-time video and queue attendance logging."""
        print("Starting face recognition...")
        self.data = self.load_encodings()
        if not self.data["names"]:
            print("Error: No registered students. Register students first.")
            logging.warning("No registered students found.")
            return

        app = FaceAnalysis(providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(160, 160))
        self.cap = self.try_open_webcam()
        if not self.cap:
            logging.error("Webcam initialization failed for recognition.")
            print("Error: Webcam initialization failed. Entering debug mode for manual attendance.")
            debug_mode = input("Use debug mode to manually log attendance? (y/n): ").strip().lower()
            if debug_mode == 'y':
                c = self.conn.cursor()
                c.execute("SELECT name FROM students")
                students = [row[0] for row in c.fetchall()]
                if not students:
                    print("No students registered in database.")
                    logging.warning("No students registered in database.")
                    return
                print("Registered students:", students)
                student_name = input("Enter student name to log attendance: ").strip()
                if student_name in students:
                    self.log_attendance(student_name, datetime.now())
                    self.email_report(auto=True)
                else:
                    print(f"Student '{student_name}' not found.")
                    logging.warning(f"Student '{student_name}' not found.")
                return
            else:
                print("Exiting recognition due to webcam failure.")
                return

        print("Recognizing faces... Press 'q' to stop.")
        frame_count = 0
        while True:
            ret, frame = self.cap.read()
            frame_count += 1
            if not ret or frame is None:
                logging.error(f"Failed to capture frame {frame_count}. Ret: {ret}, Frame: {frame}")
                print(f"Error: Failed to capture frame {frame_count}.")
                break

            display_frame = frame.copy()
            if frame_count % 5 == 0:
                small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
                try:
                    faces = app.get(small_frame)
                    logging.info(f"Detected {len(faces)} faces in frame {frame_count}")
                    print(f"Detected {len(faces)} faces in frame {frame_count}")
                    for i, face in enumerate(faces):
                        bbox = face.bbox.astype(int)
                        bbox = [int(x * 2) for x in bbox]
                        name = "Unknown"
                        face_embedding = face.embedding
                        min_distance = float("inf")
                        for j, known_embedding in enumerate(self.data["embeddings"]):
                            distance = cosine(face_embedding, known_embedding)
                            if distance < min_distance and distance < 0.4:
                                min_distance = distance
                                name = self.data["names"][j]
                        if name != "Unknown":
                            self.attendance_queue.put((name, datetime.now()))
                            print(f"Recognized {name} in frame {frame_count}")
                        cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                        cv2.putText(display_frame, name, (bbox[0], bbox[1]-10-(i*30)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                    if not faces:
                        print("No faces detected in frame.")
                        logging.info("No faces detected in frame.")
                except Exception as e:
                    print(f"Error processing frame {frame_count}: {e}")
                    logging.error(f"Error processing frame {frame_count}: {e}")

            while not self.attendance_queue.empty():
                name, login_time = self.attendance_queue.get()
                self.log_attendance(name, login_time)

            cv2.imshow("Recognize Faces", display_frame)
            if cv2.waitKey(10) & 0xFF == ord('q'):
                break

        while not self.attendance_queue.empty():
            name, login_time = self.attendance_queue.get()
            self.log_attendance(name, login_time)

        self.email_report(auto=True)
        self.cleanup()

    def view_log(self):
        """Display attendance records from SQLite."""
        print("Viewing attendance log...")
        try:
            c = self.conn.cursor()
            c.execute("SELECT name, date, time_in FROM attendance ORDER BY date DESC, time_in DESC")
            rows = c.fetchall()
            if not rows:
                print("No attendance records found.")
                logging.info("No attendance records found.")
                return
            print("\nAttendance Records:")
            print("Name\t\tDate\t\tTime In")
            print("-" * 40)
            for row in rows:
                print(f"{row[0]:<15}\t{row[1]}\t{row[2]}")
            logging.info("Displayed attendance records.")
        except Exception as e:
            logging.error(f"Error viewing log: {e}")
            print(f"Error viewing log: {e}")

    def email_report(self, auto=False):
        """Email attendance report to the faculty."""
        print("Preparing email report...")
        try:
            if not self.sender_email or not self.sender_password or not self.faculty_email:
                logging.error("SENDER_EMAIL, SENDER_PASSWORD, or FACULTY_EMAIL not set.")
                print(f"Error: Email settings incomplete. Update via option 6.")
                return

            c = self.conn.cursor()
            today_date = datetime.now().strftime("%Y-%m-%d")
            c.execute("SELECT name, date, time_in FROM attendance WHERE date = ?", (today_date,))
            df = pd.DataFrame(c.fetchall(), columns=["Name", "Date", "Time In"])
            if df.empty:
                print("No attendance data for today to email.")
                logging.warning("No attendance data for today to email.")
                return

            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)
            
            email = self.faculty_email
            print(f"Sending report to faculty email: {email}")
            logging.info(f"Sending report to faculty email: {email}")

            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = email
            msg['Subject'] = f"Daily Attendance Report - {today_date}"

            body = f"Dear Faculty,\n\nAttached is the attendance report for {today_date}.\n\nBest regards,\nAttendance System"
            msg.attach(MIMEText(body, 'plain'))

            part = MIMEBase('application', 'octet-stream')
            part.set_payload(csv_buffer.getvalue().encode('utf-8'))
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename=attendance_report.csv')
            msg.attach(part)

            try:
                print(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")
                logging.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}")
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                    server.ehlo()
                    print("Starting TLS...")
                    logging.info("Starting TLS")
                    server.starttls()
                    server.ehlo()
                    print(f"Logging in as {self.sender_email}...")
                    logging.info(f"Logging in as {self.sender_email}")
                    server.login(self.sender_email, self.sender_password)
                    print(f"Sending email to {email}...")
                    logging.info(f"Sending email to {email}")
                    server.sendmail(self.sender_email, email, msg.as_string())
                print(f"Attendance report emailed to {email}")
                logging.info(f"Attendance report emailed to {email}")
            except smtplib.SMTPAuthenticationError as e:
                print(f"Authentication failed. Check SENDER_EMAIL and SENDER_PASSWORD in {CONFIG_PATH}. Error: {e}")
                logging.error(f"SMTP authentication failed: {e}\n{traceback.format_exc()}")
            except smtplib.SMTPException as e:
                print(f"SMTP error: {e}")
                logging.error(f"SMTP error: {e}\n{traceback.format_exc()}")
            except Exception as e:
                print(f"Failed to send email to {email}: {e}")
                logging.error(f"Failed to send email to {email}: {e}\n{traceback.format_exc()}")

        except Exception as e:
            logging.error(f"Error preparing email report: {e}\n{traceback.format_exc()}")
            print(f"Error preparing email report: {e}")

    def test_email(self):
        """Send a test email to verify SMTP configuration."""
        print("Sending test email...")
        try:
            if not self.sender_email or not self.sender_password:
                logging.error("SENDER_EMAIL or SENDER_PASSWORD not set.")
                print(f"Error: SENDER_EMAIL or SENDER_PASSWORD not set. Update via option 6.")
                return

            recipient = input("Enter recipient email for test (e.g., recipient@example.com): ").strip()
            if not recipient or '@' not in recipient:
                print("Error: Invalid email format.")
                logging.warning(f"Invalid test email format: {recipient}")
                return

            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = recipient
            msg['Subject'] = f"Test Email - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            body = "This is a test email from the Attendance System to verify SMTP configuration."
            msg.attach(MIMEText(body, 'plain'))

            print(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")
            logging.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}")
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                server.ehlo()
                print("Starting TLS...")
                logging.info("Starting TLS")
                server.starttls()
                server.ehlo()
                print(f"Logging in as {self.sender_email}...")
                logging.info(f"Logging in as {self.sender_email}")
                server.login(self.sender_email, self.sender_password)
                print(f"Sending test email to {recipient}...")
                logging.info(f"Sending test email to {recipient}")
                server.sendmail(self.sender_email, recipient, msg.as_string())
            print(f"Test email sent to {recipient}")
            logging.info(f"Test email sent to {recipient}")
        except smtplib.SMTPAuthenticationError as e:
            print(f"Authentication failed. Check SENDER_EMAIL and SENDER_PASSWORD in {CONFIG_PATH}. Error: {e}")
            logging.error(f"SMTP authentication failed for test email: {e}\n{traceback.format_exc()}")
        except smtplib.SMTPException as e:
            print(f"SMTP error: {e}")
            logging.error(f"SMTP error for test email: {e}\n{traceback.format_exc()}")
        except Exception as e:
            print(f"Failed to send test email: {e}")
            logging.error(f"Failed to send test email: {e}\n{traceback.format_exc()}")

    def run(self):
        """Main loop for console interface."""
        print("Starting main loop...")
        self.data = self.load_encodings()
        while True:
            print("\nAttendance System Menu:")
            print("1. Register Student")
            print("2. Start Recognition (Auto-Email Report)")
            print("3. View Attendance Log")
            print("4. Email Attendance Report (Manual)")
            print("5. Remove Student")
            print("6. Update Email Settings")
            print("7. Run SQL Query")
            print("8. Quit")
            print("9. Send Test Email")
            choice = input("Enter choice (1-9): ").strip()
            if choice == '1':
                student_name = input("Enter student's name (letters/numbers, no spaces): ").strip()
                self.register_student(student_name)
            elif choice == '2':
                self.recognize_faces()
            elif choice == '3':
                self.view_log()
            elif choice == '4':
                self.email_report(auto=False)
            elif choice == '5':
                student_name = input("Enter student's name to remove (e.g., sahil): ").strip()
                self.remove_student(student_name)
            elif choice == '6':
                self.update_email_config()
            elif choice == '7':
                query = input("Enter SQL query (e.g., SELECT * FROM attendance): ").strip()
                self.run_sql_query(query)
            elif choice == '8':
                print("Exiting Attendance System.")
                logging.info("Application closed.")
                self.conn.close()
                self.cleanup()
                break
            elif choice == '9':
                self.test_email()
            else:
                print("Invalid choice. Please enter 1-9.")

if __name__ == "__main__":
    print("Starting script execution...")
    print("Entering main block...")
    try:
        system = AttendanceSystem()
        system.run()
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        print(f"Unexpected error: {e}")


