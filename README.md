# Face Recognition Attendance

- **Live site:** [Open the attendance app](https://minor-project-attendance.onrender.com)
- **Login page:** [Sign in](https://minor-project-attendance.onrender.com/login)
- **Public code:** [GitHub repository](https://github.com/tiwari-shresth/Minor-Project)

## In simple words

- Admin registers students and manages attendance.
- Faculty signs in and opens the camera kiosk.
- Students do not sign in; they stand in front of the camera to mark attendance.
- The app compares faces and records a match in its attendance register.
- Admin and Faculty use separate credentials and receive different access.

## Quick file guide

- `web_app.py` — app server, roles, face model, and attendance actions.
- `static/login.html` — sign-in page.
- `static/index.html`, `static/app.js`, `static/style.css` — dashboard page and its behavior/design.
- `attendance_system.py` — earlier command-line version.
- `render.yaml`, `Dockerfile`, `docker-compose.yml` — hosting and container setup.
- `PROJECT_GUIDE.md` — full project explanation in simple pointers.
- `output/pdf/PROJECT_GUIDE.pdf` — printable version of that guide.
- `DEPLOYMENT.md` — hosting notes and known limits.

## Run locally

1. Install Python and create a virtual environment.
2. Install packages: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set private Admin and Faculty credentials plus a random `SESSION_SECRET`.
4. Start the app: `uvicorn web_app:app --host 127.0.0.1 --port 8000`.
5. Open `http://127.0.0.1:8000/login`.

The live Render demo uses the small InsightFace `buffalo_sc` model. It is enabled and was confirmed loaded at startup. The free service has temporary storage, so data can disappear after a restart. Use sample records only; do not use the free demo for official attendance or real biometric data. InsightFace model packs are licensed for non-commercial research use.

For the workflow, architecture, file list, privacy notes, and presentation summary, read [PROJECT_GUIDE.md](PROJECT_GUIDE.md) or [PROJECT_GUIDE.pdf](output/pdf/PROJECT_GUIDE.pdf).
