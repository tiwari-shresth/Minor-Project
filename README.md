# Face Recognition Attendance

A web-based attendance demo for classroom use. Faculty signs in and opens a camera kiosk; students do not need accounts. The server compares faces against students registered by an administrator and records attendance matches.

- **Live demo:** [Open the app](https://minor-project-attendance.onrender.com)
- **Sign in:** [Open the login page](https://minor-project-attendance.onrender.com/login)
- **Project guide:** [Read the simple project guide](PROJECT_GUIDE.md) or [open the PDF](output/pdf/PROJECT_GUIDE.pdf)

> This is a learning/demo project. The free hosting setup uses temporary storage. Use sample records only; do not use it for official attendance or real biometric data.

## What happens in a class

1. An Admin registers each student and their face photos.
2. Faculty signs in and opens the attendance kiosk.
3. The browser asks permission to use its camera and sends frames securely to the app.
4. The server-side InsightFace model detects a face and creates a numerical face embedding.
5. The app compares it with the registered embeddings. A match above the configured threshold is recorded in SQLite.
6. Faculty sees the result; Admin can review records and export attendance.

Students do not sign in or edit records. The server enforces separate Admin and Faculty permissions.

## Design decisions and trade-offs

| Decision | Why it was chosen | Trade-off |
| --- | --- | --- |
| Faculty-run kiosk instead of student accounts | Students can mark attendance in class without managing individual logins. | Faculty must supervise the camera and the kiosk must be available during class. |
| Recognition runs on the server | One model setup is managed with the app; students only need a browser with a camera. | The server needs memory and CPU, and camera frames travel to the server over HTTPS. |
| Smaller InsightFace `buffalo_sc` pack for the hosted demo | The larger model was not a good fit for the free host's memory. The smaller pack loaded successfully in the hosted startup logs. | A smaller model is a resource trade-off; this project has no published accuracy benchmark. |
| Signed eight-hour sessions with Admin and Faculty roles | Keeps account checks on the server and restricts Faculty to the attendance kiosk. | Credentials and a stable `SESSION_SECRET` must be configured securely in the host settings. |
| SQLite plus files for demo data | Simple to run locally and on a small single service. | Render's free filesystem is temporary, so records, photos, and embeddings can disappear after restarts or redeploys. |

## Problems encountered and how they were handled

- **The recognition model was unavailable when registration or attendance was attempted.** The hosted service was configured to use the smaller `buffalo_sc` model, and startup logs were checked to confirm that the model initialized. A cold start can still take time, so allow the service to wake before using the kiosk.
- **Admin and Faculty need different abilities.** The app uses signed sessions and server-side role checks. Faculty is limited to the kiosk and recognition endpoint; Admin manages student and attendance records.
- **A free deployment can look persistent even when it is not.** The free Render service has no persistent disk. This is documented as a demo limitation; durable storage and backups have not been added to the free setup.

## What the system does not guarantee

- Face matching can produce false matches or miss a student. Lighting, camera quality, pose, and registration photos affect results.
- There is no liveness check. A photo or screen may fool the recognition flow.
- No accuracy percentage is claimed: the repository does not contain a controlled evaluation or benchmark.
- Free hosting can sleep between visits and uses temporary storage.
- InsightFace's pretrained model packs are restricted to non-commercial research use. Check the model license before using them for any other purpose.

## Good next improvements

1. Evaluate recognition on a consented, representative set of classroom images. Report the sample size, false accepts, and missed matches instead of claiming an unsupported accuracy figure.
2. Add persistent protected storage, encrypted backups, retention/deletion rules, and a non-biometric attendance option before any real deployment.
3. Add a liveness check and test it against printed photos and screens.
4. Measure startup time, memory use, and recognition latency on the intended hosting plan.
5. Rotate demo credentials if they have been shared, and store all live secrets only in the hosting provider's secret settings.

## Run locally

1. Install Python and create a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`; set private Admin and Faculty credentials and a random `SESSION_SECRET`.
4. Start the app: `uvicorn web_app:app --host 127.0.0.1 --port 8000`.
5. Visit [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login).

Never commit `.env`, real passwords, student photos, face embeddings, databases, or runtime data.

## Project files

- `web_app.py` — FastAPI server, model startup, sessions, role checks, registration, attendance, exports, and email.
- `static/login.html` — sign-in page.
- `static/index.html`, `static/app.js`, `static/style.css` — dashboard structure, browser behavior, and styling.
- `attendance_system.py` — earlier command-line version.
- `render.yaml`, `Dockerfile`, `docker-compose.yml` — hosting and container setup.
- `PROJECT_GUIDE.md` — simple workflow, architecture, and file guide.
- `DEPLOYMENT.md` — deployment configuration and operational limitations.

## Explain it in an interview

> “I built a classroom attendance demo where faculty supervises one camera kiosk instead of each student needing an account. I kept Admin and Faculty permissions separate on the server. The main deployment trade-off was model size: I selected the smaller InsightFace pack for the free host and checked that it loaded at startup. The demo still has important limits: free storage is temporary, face matching can be wrong, and there is no liveness detection or measured accuracy benchmark. My next step would be to evaluate it responsibly and add persistent, protected storage before real use.”

