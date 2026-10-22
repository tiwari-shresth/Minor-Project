# No-cost public demo from your computer

This option runs the app on your own computer and gives it a temporary public HTTPS URL using Cloudflare Quick Tunnel. It costs $0 for the tunnel and does not require a domain, but it is for demos/testing: the computer must stay awake and online, and the URL changes whenever the tunnel restarts. Anyone who has the URL can reach the sign-in prompt. Admin and faculty have separate credentials; faculty credentials open the attendance kiosk only. Keep both private. Do not use real student biometric data for an internet demo.

## One-time setup on macOS

Install the app dependencies and Cloudflare's tunnel client:

```sh
cd /path/to/face-recognition-attendance
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
brew install cloudflared
```

The first run downloads the InsightFace model pack into your user cache and may take several minutes. The app's dependencies must support your Mac's processor and Python version.

## Start the public demo

In Terminal window 1, start the app with fresh admin and faculty passwords:

```sh
cd /path/to/face-recognition-attendance
source .venv/bin/activate
export ADMIN_USERNAME='demo-admin'
export ADMIN_PASSWORD='replace-with-a-long-random-secret'
export FACULTY_USERNAME='faculty'
export FACULTY_PASSWORD='use-a-different-long-random-secret'
export DATA_DIR="$PWD/data/public-demo"
export ENABLE_FACE_RECOGNITION=true
export PORT=8010
python run_web.py
```

In Terminal window 2, start the temporary HTTPS tunnel:

```sh
./cloudflared tunnel --url http://127.0.0.1:8010
```

Cloudflare prints a `https://….trycloudflare.com` URL. Open that link on the device where you want to use the demo and sign in with the username and password from Terminal window 1. The camera API requires HTTPS, which the tunnel URL provides.

Keep both terminal windows open and prevent the computer from sleeping while the demo is in use. Stop the service and tunnel with Ctrl+C in each window. On restart, use the newly printed tunnel URL. Attendance data is stored in the local `data/` folder, not in Cloudflare.

## Limitations

- This is a public demo forwarded from your computer, not an always-on cloud deployment. Power loss, sleep, internet outages, or stopping either process takes it offline.
- The URL is temporary and changes on restart. Cloudflare says Quick Tunnels are for testing and development and do not provide an uptime guarantee.
- Model startup and registration performance depend on your computer. Keep the Mac plugged in and allow sufficient free memory.
- A browser reaching the app can submit face photos and attendance records to the local machine. Share the URL and credentials only with intended testers, and use test data.
- Keep both passwords available in your password manager. They are read from the shell environment and must be set again after opening a new terminal session.
