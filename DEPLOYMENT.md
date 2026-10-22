# Internet deployment checklist

- Build the Docker image from this directory and deploy it to the hosting provider selected by the project owner.
- Configure `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `FACULTY_USERNAME`, and `FACULTY_PASSWORD` as host-managed secrets. Never store filled credentials in Git.
- Mount a persistent volume at `/data`; the app stores the SQLite database, face embeddings, student photos, and runtime SMTP configuration there.
- Route public HTTPS traffic to port 8000. The browser camera requires HTTPS outside localhost.
- Verify `/api/health` responds, unauthenticated requests receive HTTP 401, and a faculty account receives HTTP 403 from admin endpoints such as `/api/stats` while the kiosk remains available.
- Configure SMTP only after deployment using a newly issued app password. Set up encrypted backups and retention/deletion controls for biometric and attendance data.
- Do not import the original downloaded `attendance.db`, `encodings.json`, `known_faces/`, `config.json`, `debug.log`, or bundled tunnel binary into production.

## Render free demo

`render.yaml` is configured for Render's free 512 MB web-service plan in Singapore and sets `ENABLE_FACE_RECOGNITION=false`. The dashboard starts without downloading the 326 MB `buffalo_l` pack; model-backed registration and recognition return HTTP 503 in this free demo. Docker Compose enables recognition by default. A paid hosted service must set `ENABLE_FACE_RECOGNITION=true` explicitly. The free service has no persistent disk or database: local SQLite records, student photos, embeddings, and SMTP settings can disappear after a restart, redeploy, or spin-down. Free services sleep after 15 minutes without traffic and can take about a minute to wake. Do not use real student or biometric data on this demo.

This is a zero-compute-cost preview configuration, not a durable attendance deployment. Render's free plan has included usage limits; check the workspace billing and usage settings so exceeding any included limits cannot create charges. For durable use, move to paid compute and persistent storage, which this zero-cost deployment intentionally does not provision.

A Git repository connected to Render is required. Use a private repository and include only this sanitized application copy. Do not include the report PDF or any original database, student photo, face encoding, or credential files.
