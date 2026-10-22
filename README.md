# Face Recognition Attendance System

For a no-cost public demo from your own computer, follow [QUICK_TUNNEL.md](QUICK_TUNNEL.md). It uses a temporary Cloudflare HTTPS tunnel; your computer must stay awake and online.

A FastAPI web dashboard for webcam-based student registration, face recognition, attendance records, and CSV reporting. The user's browser supplies the webcam; the server runs InsightFace inference and stores student data.

## Deploy with Docker Compose

1. Install Docker on a host that supports persistent volumes and has at least 2 GB RAM. The first build downloads Python packages and the first run downloads the InsightFace model.
2. Copy `.env.example` to `.env` and set unique admin and faculty usernames and long random passwords. Keep `.env` private. The example enables local face recognition; the Render free demo disables the model to stay within its memory limit.
3. Run `docker compose up -d --build`.
4. Put the service behind a domain with HTTPS before using the browser camera. Admins can manage the system; faculty sign in with their separate credentials and receive access to the attendance kiosk only. Students do not need accounts; they are marked by the camera during a faculty attendance session.
5. Configure SMTP inside the authenticated Settings page if email reports are needed. Use a new provider app password; never reuse a password that was included in the source project.

The `attendance-data` Docker volume preserves SQLite attendance records, embeddings, student photos, and app configuration across container replacements. Back it up securely. Attendance history is no longer automatically deleted; use the authenticated purge action only when the retention policy calls for it. In the Render free preview, face recognition is disabled to fit the memory limit; local data is also ephemeral. See `DEPLOYMENT.md` before using that demo.

## Security and privacy

All routes except `/api/health` require HTTP Basic authentication. `ADMIN_USERNAME` and `ADMIN_PASSWORD` grant full access. `FACULTY_USERNAME` and `FACULTY_PASSWORD` grant access only to the live recognition kiosk; the server rejects their requests to student management, attendance history, exports, settings, and SQL tools. Keep all credentials private and use HTTPS. Face photos and embeddings are sensitive biometric data: register people only with appropriate notice/consent, restrict access, define retention and deletion procedures, and protect backups.

The system does not perform liveness checks and has not been validated for demographic accuracy or classroom conditions. It should be treated as a demonstration project until those risks are evaluated.

## Local development

Create a Python environment, install `requirements.txt`, set the admin and faculty credentials (`ADMIN_USERNAME`, `ADMIN_PASSWORD`, `FACULTY_USERNAME`, and `FACULTY_PASSWORD`); set `ENABLE_FACE_RECOGNITION=true` to load the model, then run:

```sh
uvicorn web_app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Browsers permit camera access on localhost; remote access requires HTTPS.
