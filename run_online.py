#!/usr/bin/env python3
"""
One-click script to start the Face Recognition Attendance Web System
and create an online public HTTPS URL via Cloudflare Tunnel.
"""

import os
import sys
import time
import subprocess
import webbrowser
import re
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8000"))
URL = f"http://{HOST}:{PORT}"

def main():
    print("=" * 65)
    print("  VisionMark AI - Launching Online Public Deployment")
    print("=" * 65)

    # Require authentication before exposing the app through a public tunnel.
    if not all(os.environ.get(key) for key in (
        "ADMIN_USERNAME", "ADMIN_PASSWORD", "FACULTY_USERNAME", "FACULTY_PASSWORD"
    )):
        print("Set admin and faculty credentials (ADMIN_USERNAME/PASSWORD and FACULTY_USERNAME/PASSWORD) before starting.")
        sys.exit(1)

    # Prefer an installed cloudflared client; accept the old bundled binary too.
    cloudflared_bin = shutil.which("cloudflared") or os.path.join(BASE_DIR, "cloudflared")
    if not os.path.isfile(cloudflared_bin):
        print("cloudflared is required. On macOS, install it with: brew install cloudflared")
        sys.exit(1)

    os.environ.setdefault("DATA_DIR", os.path.join(BASE_DIR, "data"))
    os.environ.setdefault("ENABLE_FACE_RECOGNITION", "true")

    # 1. Start FastAPI server
    print(f"\n[1/3] Starting backend server on {URL} ...")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web_app:app", "--host", HOST, "--port", str(PORT)],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    # 2. Start Cloudflare Tunnel
    print("[2/3] Launching Cloudflare Tunnel for secure HTTPS access...")
    tunnel_proc = subprocess.Popen(
        [cloudflared_bin, "tunnel", "--url", URL],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    public_url = None
    start_time = time.time()
    while time.time() - start_time < 30:
        line = tunnel_proc.stdout.readline()
        if not line:
            break
        match = re.search(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com', line)
        if match:
            public_url = match.group(0)
            break

    if public_url:
        print("\n" + "=" * 65)
        print("🎉 SUCCESS! Your Attendance System is live online:")
        print(f"👉 Public HTTPS URL: {public_url}")
        print(f"👉 Local URL:        {URL}")
        print("=" * 65)
        print("\nOpening online dashboard in browser...")
        webbrowser.open(public_url)
        print("\nPress Ctrl+C to shut down the server and tunnel.\n")
        try:
            tunnel_proc.wait()
        except KeyboardInterrupt:
            print("\nShutting down server and tunnel...")
            tunnel_proc.terminate()
            server_proc.terminate()
    else:
        print("Failed to acquire public URL. Server is still running at http://localhost:8000")

if __name__ == "__main__":
    main()
