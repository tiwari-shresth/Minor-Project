#!/usr/bin/env python3
"""
Launcher for VisionMark AI Attendance Web Application
Starts Uvicorn server and automatically opens browser.
"""

import sys
import os
import time
import webbrowser
import threading
import uvicorn

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8000"))
URL = f"http://{HOST}:{PORT}"

def open_browser():
    time.sleep(1.2)
    print(f"\n🚀 Opening attendance dashboard in browser at {URL} ...")
    webbrowser.open(URL)

if __name__ == "__main__":
    print("=" * 60)
    print("  VisionMark AI - Face Recognition Attendance System")
    print(f"  Web Server starting on {URL}")
    print("=" * 60)

    # Launch browser in separate thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start FastAPI server via Uvicorn
    uvicorn.run("web_app:app", host=HOST, port=PORT, reload=False, log_level="info")
