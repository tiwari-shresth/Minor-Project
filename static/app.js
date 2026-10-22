/**
 * VisionMark AI - Face Recognition Attendance Client
 */

// State
let videoStream = null;
let regVideoStream = null;
let isProcessingFrame = false;
let recognitionLoopId = null;
let lastFrameTime = performance.now();
let fpsCounter = 0;
let capturedPhotos = [];
let audioCtx = null;

// DOM Elements
const webcamVideo = document.getElementById('webcam-video');
const overlayCanvas = document.getElementById('overlay-canvas');
const overlayCtx = overlayCanvas.getContext('2d');
const cameraPlaceholder = document.getElementById('camera-placeholder');
const scanLaser = document.getElementById('scan-laser');
const heroRecognitionCard = document.getElementById('hero-recognition-card');
const heroName = document.getElementById('hero-name');
const heroBadge = document.getElementById('hero-badge');
const heroTime = document.getElementById('hero-time');
const heroAvatar = document.getElementById('hero-avatar');
const activityStream = document.getElementById('activity-stream');
const toastContainer = document.getElementById('toast-container');

// Init the role view before loading any dashboard data. Faculty credentials are
// limited to the live kiosk; the server independently enforces this permission.
let currentUserRole = 'admin';

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch('/api/me');
        if (response.ok) {
            const user = await response.json();
            currentUserRole = user.role === 'faculty' ? 'faculty' : 'admin';
        }
    } catch (error) {
        console.error('Could not determine signed-in role:', error);
    }

    try {
        const healthResponse = await fetch('/api/health');
        const health = await healthResponse.json();
        const modelStatus = document.getElementById('model-status-sub');
        const statusDot = document.querySelector('.status-indicator-dot');
        if (modelStatus) modelStatus.textContent = health.face_recognition === 'enabled'
            ? `${health.model_name || 'Face'} model ready`
            : 'Face model unavailable';
        if (statusDot) statusDot.classList.toggle('online', health.face_recognition === 'enabled');
    } catch (error) {
        console.error('Could not determine face model status:', error);
    }

    document.body.dataset.role = currentUserRole;
    const roleLabel = document.getElementById('signed-in-role');
    if (roleLabel) roleLabel.textContent = `Signed in as ${currentUserRole}`;
    if (currentUserRole === 'faculty') {
        document.getElementById('page-title').textContent = 'Faculty Attendance Kiosk';
        document.getElementById('page-subtitle').textContent = 'Students can mark attendance here; administration tools are restricted.';
    }

    try { initClock(); } catch(e) { console.error('initClock error:', e); }
    try { initTabs(); } catch(e) { console.error('initTabs error:', e); }
    if (currentUserRole === 'admin') {
        try { initStats(); } catch(e) { console.error('initStats error:', e); }
        try { initSettings(); } catch(e) { console.error('initSettings error:', e); }
        try { loadStudents(); } catch(e) { console.error('loadStudents error:', e); }
        try { initAttendanceLogs(); } catch(e) { console.error('initAttendanceLogs error:', e); }
        try { initSqlConsole(); } catch(e) { console.error('initSqlConsole error:', e); }
        try { initModals(); } catch(e) { console.error('initModals error:', e); }
    }

    // Auto-start camera if permissions already granted or on click
    const btnStartCam = document.getElementById('btn-start-camera');
    if (btnStartCam) btnStartCam.addEventListener('click', startMainCamera);

    const btnToggleCam = document.getElementById('btn-toggle-cam');
    if (btnToggleCam) btnToggleCam.addEventListener('click', toggleCamera);

    const btnQuickEmail = document.getElementById('btn-quick-email');
    if (btnQuickEmail && currentUserRole === 'admin') btnQuickEmail.addEventListener('click', triggerQuickEmailReport);

    const btnTriggerEmail = document.getElementById('btn-trigger-email-report');
    if (btnTriggerEmail && currentUserRole === 'admin') btnTriggerEmail.addEventListener('click', triggerQuickEmailReport);

    const logoutButton = document.getElementById('btn-logout');
    if (logoutButton) logoutButton.addEventListener('click', async () => {
        try {
            await fetch('/api/logout', { method: 'POST' });
        } finally {
            window.location.replace('/login');
        }
    });

    // Initial check for camera availability
    startMainCamera();
});

// Clock
function initClock() {
    const clockEl = document.getElementById('clock-display');
    function update() {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString([], { hour12: false });
    }
    update();
    setInterval(update, 1000);
}

// Sound Synthesizer (Chime on mark)
function playSuccessChime() {
    try {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
        const now = audioCtx.currentTime;
        // Tone 1
        const osc1 = audioCtx.createOscillator();
        const gain1 = audioCtx.createGain();
        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(587.33, now); // D5
        osc1.frequency.exponentialRampToValueAtTime(880, now + 0.15); // A5
        gain1.gain.setValueAtTime(0.2, now);
        gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.35);
        osc1.connect(gain1);
        gain1.connect(audioCtx.destination);
        osc1.start(now);
        osc1.stop(now + 0.35);
    } catch (e) {
        console.warn('Audio chime blocked or unsupported:', e);
    }
}

// Toast
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '⚠️';

    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Tabs
function initTabs() {
    const navItems = document.querySelectorAll('.nav-item');
    const panes = document.querySelectorAll('.tab-pane');
    const pageTitle = document.getElementById('page-title');
    const pageSubtitle = document.getElementById('page-subtitle');

    const titles = {
        'tab-kiosk': { title: 'Live Recognition Kiosk', sub: 'Real-time biometric attendance matching & auto-logging' },
        'tab-students': { title: 'Student Directory', sub: 'Manage registered students and their facial biometric profiles' },
        'tab-logs': { title: 'Attendance Log History', sub: 'Complete database records with export and filtering' },
        'tab-settings': { title: 'System & Email Settings', sub: 'Configure SMTP credentials and face detection strictness' },
        'tab-sql': { title: 'Database Console', sub: 'Run direct SQL queries and inspections on attendance.db' }
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetId = item.getAttribute('data-tab');
            navItems.forEach(n => n.classList.remove('active'));
            panes.forEach(p => p.classList.remove('active'));

            item.classList.add('active');
            const targetPane = document.getElementById(targetId);
            if (targetPane) targetPane.classList.add('active');

            if (titles[targetId]) {
                pageTitle.textContent = titles[targetId].title;
                pageSubtitle.textContent = titles[targetId].sub;
            }

            if (targetId === 'tab-students') loadStudents();
            if (targetId === 'tab-logs') loadAttendance();
            if (targetId === 'tab-settings') loadConfig();
            initStats();
        });
    });
}

// Stats
async function initStats() {
    try {
        const res = await fetch('/api/stats');
        if (!res.ok) return;
        const data = await res.json();
        
        document.getElementById('stat-total-students').textContent = data.total_students;
        document.getElementById('stat-present-today').textContent = data.present_today;
        document.getElementById('stat-absent-today').textContent = data.absent_today;
        document.getElementById('stat-attendance-rate').textContent = `${data.attendance_rate}%`;
        document.getElementById('sidebar-student-count').textContent = data.total_students;

        if (data.recent_logs && data.recent_logs.length > 0) {
            renderActivityStream(data.recent_logs);
        }
    } catch (e) {
        console.error('Stats error:', e);
    }
}

function renderActivityStream(logs) {
    if (!logs || logs.length === 0) return;
    activityStream.innerHTML = '';
    logs.forEach(item => {
        const div = document.createElement('div');
        div.className = 'activity-item';
        div.innerHTML = `
            <div class="activity-student">
                <div class="activity-avatar">${item.name.charAt(0)}</div>
                <div>
                    <div class="activity-name">${item.name}</div>
                    <div class="activity-time">${item.date} • ${item.time_in}</div>
                </div>
            </div>
            <span class="badge-tag">Marked</span>
        `;
        activityStream.appendChild(div);
    });
}

// CAMERA & LIVE RECOGNITION
async function startMainCamera() {
    const startBtn = document.getElementById('btn-start-camera');
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<span>Requesting Camera...</span>';
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Camera access requires HTTPS or localhost context.', 'error');
        cameraPlaceholder.style.display = 'flex';
        document.getElementById('camera-status-tag').innerHTML = '<span style="color:var(--danger)">●</span> Insecure Context';
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span>Start Live Camera</span>
            `;
        }
        return;
    }

    try {
        if (videoStream) {
            videoStream.getTracks().forEach(t => t.stop());
        }

        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: 'user'
            },
            audio: false
        });

        videoStream = stream;
        webcamVideo.srcObject = stream;
        cameraPlaceholder.style.display = 'none';
        scanLaser.classList.add('active');

        webcamVideo.onloadedmetadata = () => {
            overlayCanvas.width = webcamVideo.videoWidth || 640;
            overlayCanvas.height = webcamVideo.videoHeight || 480;
            startRecognitionLoop();
            document.getElementById('camera-status-tag').innerHTML = '<span class="pulse-dot"></span> Camera Live';
            showToast('Camera connected and live recognition started!', 'success');
        };
    } catch (err) {
        console.warn('Webcam access error:', err);
        cameraPlaceholder.style.display = 'flex';
        scanLaser.classList.remove('active');
        document.getElementById('camera-status-tag').innerHTML = '<span style="color:var(--danger)">●</span> Camera Inactive';

        let errorMsg = 'Could not access camera.';
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            errorMsg = 'Camera permission blocked. Click the lock/camera icon in your address bar and select "Allow".';
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
            errorMsg = 'No camera device found on this system.';
        } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
            errorMsg = 'Camera is currently in use by another app or permissions are missing in macOS System Settings > Privacy > Camera.';
        }
        showToast(errorMsg, 'error');
    } finally {
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span>Start Live Camera</span>
            `;
        }
    }
}

function toggleCamera() {
    if (videoStream && videoStream.active) {
        videoStream.getTracks().forEach(t => t.stop());
        videoStream = null;
        cameraPlaceholder.style.display = 'flex';
        scanLaser.classList.remove('active');
        stopRecognitionLoop();
        document.getElementById('camera-status-tag').innerHTML = '<span style="color:var(--warning)">●</span> Paused';
    } else {
        startMainCamera();
    }
}

function startRecognitionLoop() {
    if (recognitionLoopId) clearInterval(recognitionLoopId);
    // Send frame every 280ms
    recognitionLoopId = setInterval(processCurrentFrame, 280);
}

function stopRecognitionLoop() {
    if (recognitionLoopId) {
        clearInterval(recognitionLoopId);
        recognitionLoopId = null;
    }
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
}

// Grab frame and send to FastAPI
async function processCurrentFrame() {
    if (isProcessingFrame || !videoStream || webcamVideo.paused || webcamVideo.ended) return;
    if (webcamVideo.videoWidth === 0 || webcamVideo.videoHeight === 0) return;

    isProcessingFrame = true;

    try {
        // Compute FPS
        const now = performance.now();
        const delta = now - lastFrameTime;
        lastFrameTime = now;
        fpsCounter = Math.round(1000 / delta);
        document.getElementById('fps-counter').textContent = `${fpsCounter} FPS`;

        // Draw video frame to offscreen canvas
        const offCanvas = document.createElement('canvas');
        offCanvas.width = webcamVideo.videoWidth;
        offCanvas.height = webcamVideo.videoHeight;
        const offCtx = offCanvas.getContext('2d');
        offCtx.drawImage(webcamVideo, 0, 0, offCanvas.width, offCanvas.height);

        const b64 = offCanvas.toDataURL('image/jpeg', 0.85);

        const res = await fetch('/api/recognize_frame', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: b64 })
        });

        if (!res.ok) {
            isProcessingFrame = false;
            return;
        }

        const data = await res.json();
        drawBoundingBoxes(data.faces || []);

    } catch (e) {
        console.warn('Frame processing error:', e);
    } finally {
        isProcessingFrame = false;
    }
}

// Draw bounding boxes on Canvas overlay
function drawBoundingBoxes(faces) {
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    if (!faces || faces.length === 0) {
        return;
    }

    faces.forEach(face => {
        // Because the selfie camera preview is horizontally mirrored, mirror the x-coordinates:
        const raw_x1 = face.bbox[0];
        const raw_y1 = face.bbox[1];
        const raw_x2 = face.bbox[2];
        const raw_y2 = face.bbox[3];

        const x1 = Math.max(0, overlayCanvas.width - raw_x2);
        const x2 = Math.min(overlayCanvas.width, overlayCanvas.width - raw_x1);
        const y1 = raw_y1;
        const y2 = raw_y2;

        const width = x2 - x1;
        const height = y2 - y1;
        const isKnown = face.name !== 'Unknown';

        // Styling
        const strokeColor = isKnown ? '#10b981' : '#f59e0b';
        overlayCtx.strokeStyle = strokeColor;
        overlayCtx.lineWidth = 3;
        overlayCtx.shadowColor = strokeColor;
        overlayCtx.shadowBlur = 10;

        // Draw rectangle
        overlayCtx.strokeRect(x1, y1, width, height);

        // Corner accents
        const cornerLen = 14;
        overlayCtx.lineWidth = 4;
        // Top Left
        overlayCtx.beginPath();
        overlayCtx.moveTo(x1, y1 + cornerLen);
        overlayCtx.lineTo(x1, y1);
        overlayCtx.lineTo(x1 + cornerLen, y1);
        overlayCtx.stroke();
        // Top Right
        overlayCtx.beginPath();
        overlayCtx.moveTo(x2 - cornerLen, y1);
        overlayCtx.lineTo(x2, y1);
        overlayCtx.lineTo(x2, y1 + cornerLen);
        overlayCtx.stroke();
        // Bottom Left
        overlayCtx.beginPath();
        overlayCtx.moveTo(x1, y2 - cornerLen);
        overlayCtx.lineTo(x1, y2);
        overlayCtx.lineTo(x1 + cornerLen, y2);
        overlayCtx.stroke();
        // Bottom Right
        overlayCtx.beginPath();
        overlayCtx.moveTo(x2 - cornerLen, y2);
        overlayCtx.lineTo(x2, y2);
        overlayCtx.lineTo(x2, y2 - cornerLen);
        overlayCtx.stroke();

        // Label Tag
        overlayCtx.shadowBlur = 0;
        const labelText = isKnown ? `${face.name} (${face.confidence}%)` : 'Unknown Face';
        overlayCtx.font = 'bold 15px Inter, sans-serif';
        const textMetrics = overlayCtx.measureText(labelText);
        const tagHeight = 26;
        const tagWidth = textMetrics.width + 18;
        const tagY = Math.max(0, y1 - tagHeight - 6);

        overlayCtx.fillStyle = isKnown ? 'rgba(16, 185, 129, 0.9)' : 'rgba(245, 158, 11, 0.9)';
        roundRect(overlayCtx, x1, tagY, tagWidth, tagHeight, 6);
        overlayCtx.fill();

        overlayCtx.fillStyle = '#ffffff';
        overlayCtx.fillText(labelText, x1 + 9, tagY + 18);

        // If newly marked or recognized
        if (isKnown) {
            updateHeroCard(face);
            if (face.logged_now) {
                playSuccessChime();
                showToast(`Attendance marked for ${face.name}!`, 'success');
                initStats();
            }
        }
    });
}

function roundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function updateHeroCard(face) {
    heroRecognitionCard.classList.add('match');
    heroName.textContent = face.name;
    heroBadge.textContent = face.logged_now ? 'Just Marked Present!' : (face.already_logged ? 'Already Present Today' : 'Recognized');
    heroTime.textContent = `Match Confidence: ${face.confidence}% • Time: ${new Date().toLocaleTimeString()}`;
    heroAvatar.innerHTML = `<img src="/api/students/${face.name}/photo" onerror="this.parentElement.textContent='${face.name.charAt(0).toUpperCase()}'">`;
}

// STUDENTS MANAGEMENT
async function loadStudents() {
    const tbody = document.getElementById('students-table-body');
    try {
        const res = await fetch('/api/students');
        const students = await res.json();

        if (students.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center">No students registered yet. Click "+ Add New Student" to get started.</td></tr>`;
            return;
        }

        renderStudentsTable(students);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error loading students: ${e}</td></tr>`;
    }
}

function renderStudentsTable(students) {
    const tbody = document.getElementById('students-table-body');
    const searchVal = document.getElementById('search-students').value.toLowerCase().trim();

    const filtered = students.filter(s => 
        s.name.toLowerCase().includes(searchVal) || s.email.toLowerCase().includes(searchVal)
    );

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center">No students match your search filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(s => `
        <tr>
            <td>
                ${s.photo_url 
                    ? `<img class="thumb-cell" src="${s.photo_url}" alt="${s.name}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'44\' height=\'44\'><circle cx=\'22\' cy=\'22\' r=\'22\' fill=\'%236366f1\'/></svg>'">`
                    : `<div class="thumb-cell" style="display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;">${s.name.charAt(0).toUpperCase()}</div>`
                }
            </td>
            <td><strong>${s.name}</strong></td>
            <td>${s.email}</td>
            <td><span class="badge-tag">${s.embeddings_count} vectors</span></td>
            <td>
                ${s.present_today 
                    ? `<span class="status-badge present">● Present (${s.time_in})</span>`
                    : `<span class="status-badge absent">○ Not Logged</span>`
                }
            </td>
            <td>
                <button class="btn btn-outline" style="padding:4px 10px;font-size:0.75rem;" onclick="removeStudentPrompt('${s.name}')">Remove</button>
            </td>
        </tr>
    `).join('');
}

window.removeStudentPrompt = async function(name) {
    if (!confirm(`Are you sure you want to remove student '${name}'? This will delete their biometric vectors and profile.`)) return;

    try {
        const res = await fetch(`/api/students/${name}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message, 'success');
            loadStudents();
            initStats();
        } else {
            showToast(data.detail || 'Failed to remove student', 'error');
        }
    } catch (e) {
        showToast('Error removing student: ' + e, 'error');
    }
};

document.getElementById('search-students').addEventListener('input', () => {
    loadStudents();
});

// ATTENDANCE LOGS
async function loadAttendance() {
    const tbody = document.getElementById('attendance-table-body');
    const dateVal = document.getElementById('filter-date').value;
    const nameVal = document.getElementById('filter-student-name').value.trim();

    let url = '/api/attendance?';
    if (dateVal) url += `date=${encodeURIComponent(dateVal)}&`;
    if (nameVal) url += `name=${encodeURIComponent(nameVal)}&`;

    try {
        const res = await fetch(url);
        const records = await res.json();

        if (records.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center">No attendance records found for this filter.</td></tr>`;
            return;
        }

        tbody.innerHTML = records.map(r => `
            <tr>
                <td>#${r.id}</td>
                <td><strong>${r.name}</strong></td>
                <td>${r.email || '-'}</td>
                <td>${r.date}</td>
                <td style="font-family:var(--font-mono);">${r.time_in}</td>
                <td><span class="status-badge present">● Present</span></td>
                <td>
                    <button class="btn-icon" style="width:28px;height:28px;" onclick="deleteAttendanceRecord(${r.id})" title="Delete record">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error: ${e}</td></tr>`;
    }
}

window.deleteAttendanceRecord = async function(id) {
    if (!confirm('Delete this attendance entry?')) return;
    try {
        const res = await fetch(`/api/attendance/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Attendance record deleted', 'info');
            loadAttendance();
            initStats();
        }
    } catch (e) {
        showToast('Error: ' + e, 'error');
    }
};

function initAttendanceLogs() {
    document.getElementById('filter-date').addEventListener('change', loadAttendance);
    document.getElementById('filter-student-name').addEventListener('input', loadAttendance);
    document.getElementById('btn-clear-filters').addEventListener('click', () => {
        document.getElementById('filter-date').value = '';
        document.getElementById('filter-student-name').value = '';
        loadAttendance();
    });

    document.getElementById('btn-export-csv').addEventListener('click', () => {
        const dateVal = document.getElementById('filter-date').value;
        let url = '/api/attendance/export';
        if (dateVal) url += `?date=${encodeURIComponent(dateVal)}`;
        window.open(url, '_blank');
    });

    const btnPurgeOld = document.getElementById('btn-purge-old');
    if (btnPurgeOld) {
        btnPurgeOld.addEventListener('click', triggerPurgeOldAttendance);
    }
}

async function triggerPurgeOldAttendance() {
    if (!confirm('Are you sure you want to purge all attendance records older than 24 hours? Registered students and embeddings will remain completely intact.')) return;

    showToast('Purging records older than 24 hours...', 'info');
    try {
        const res = await fetch('/api/attendance/purge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hours: 24 })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Purged ${data.deleted_count} old records.`, 'success');
            loadAttendance();
            initStats();
        } else {
            showToast(data.detail || 'Purge failed', 'error');
        }
    } catch (e) {
        showToast('Error during purge: ' + e, 'error');
    }
}

// SETTINGS & EMAIL
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        const cfg = await res.json();
        
        document.getElementById('cfg-sender-email').value = cfg.SENDER_EMAIL || '';
        document.getElementById('cfg-sender-password').placeholder = cfg.SENDER_PASSWORD_SET ? '•••••••• (Stored securely - leave blank to keep)' : 'Enter password';
        document.getElementById('cfg-faculty-email').value = cfg.FACULTY_EMAIL || '';
        document.getElementById('cfg-smtp-server').value = cfg.SMTP_SERVER || 'smtp.gmail.com';
        document.getElementById('cfg-smtp-port').value = cfg.SMTP_PORT || 587;
        document.getElementById('cfg-threshold').value = cfg.COSINE_THRESHOLD || 0.40;
        document.getElementById('cfg-threshold-val').textContent = (cfg.COSINE_THRESHOLD || 0.40).toFixed(2);
        document.getElementById('active-threshold-val').textContent = (cfg.COSINE_THRESHOLD || 0.40).toFixed(2);
        document.getElementById('test-email-recipient').value = cfg.FACULTY_EMAIL || '';
    } catch (e) {
        console.error('Config load error:', e);
    }
}

function initSettings() {
    const range = document.getElementById('cfg-threshold');
    range.addEventListener('input', () => {
        document.getElementById('cfg-threshold-val').textContent = parseFloat(range.value).toFixed(2);
        document.getElementById('active-threshold-val').textContent = parseFloat(range.value).toFixed(2);
    });

    document.getElementById('settings-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            SENDER_EMAIL: document.getElementById('cfg-sender-email').value.trim(),
            SENDER_PASSWORD: document.getElementById('cfg-sender-password').value.trim() || undefined,
            FACULTY_EMAIL: document.getElementById('cfg-faculty-email').value.trim(),
            SMTP_SERVER: document.getElementById('cfg-smtp-server').value.trim(),
            SMTP_PORT: parseInt(document.getElementById('cfg-smtp-port').value) || 587,
            COSINE_THRESHOLD: parseFloat(range.value)
        };

        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                showToast('Email settings updated successfully!', 'success');
            } else {
                showToast(data.detail || 'Failed to update settings', 'error');
            }
        } catch (err) {
            showToast('Error saving settings: ' + err, 'error');
        }
    });

    document.getElementById('btn-send-test-email').addEventListener('click', async () => {
        const recipient = document.getElementById('test-email-recipient').value.trim();
        if (!recipient) {
            showToast('Enter recipient email for test', 'error');
            return;
        }

        showToast('Sending test email via SMTP...', 'info');
        try {
            const res = await fetch('/api/email/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ recipient })
            });
            const data = await res.json();
            if (res.ok) {
                showToast(data.message, 'success');
            } else {
                showToast(data.detail || 'Test email failed', 'error');
            }
        } catch (err) {
            showToast('Error sending test email: ' + err, 'error');
        }
    });

    const btnSettingsPurge = document.getElementById('btn-settings-purge');
    if (btnSettingsPurge) {
        btnSettingsPurge.addEventListener('click', triggerPurgeOldAttendance);
    }
}

async function triggerQuickEmailReport() {
    if (!confirm("Send today's attendance CSV report to Faculty email now?")) return;

    showToast('Generating and emailing CSV report...', 'info');
    try {
        const res = await fetch('/api/email/report', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message, 'success');
        } else {
            showToast(data.detail || 'Failed to send report email', 'error');
        }
    } catch (e) {
        showToast('Error sending report email: ' + e, 'error');
    }
}

// SQL CONSOLE
function initSqlConsole() {
    document.querySelectorAll('.preset-queries .chip').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('sql-query-input').value = btn.getAttribute('data-query');
        });
    });

    document.getElementById('btn-run-sql').addEventListener('click', async () => {
        const query = document.getElementById('sql-query-input').value.trim();
        const resContainer = document.getElementById('sql-result-container');
        if (!query) return;

        resContainer.innerHTML = '<div class="empty-state-small">Executing query...</div>';

        try {
            const res = await fetch('/api/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            const data = await res.json();

            if (!res.ok) {
                resContainer.innerHTML = `<div style="padding:16px;color:var(--danger);font-family:var(--font-mono);font-size:0.85rem;">${data.detail || 'Query error'}</div>`;
                return;
            }

            if (data.type === 'select') {
                if (data.rows.length === 0) {
                    resContainer.innerHTML = `<div class="empty-state-small">Query executed successfully. 0 rows returned.</div>`;
                    return;
                }
                const headers = data.columns.map(c => `<th>${c}</th>`).join('');
                const rows = data.rows.map(r => `
                    <tr>${data.columns.map(c => `<td>${r[c] !== null ? r[c] : '<em>NULL</em>'}</td>`).join('')}</tr>
                `).join('');
                resContainer.innerHTML = `
                    <div style="font-size:0.75rem;color:var(--text-muted);padding:6px 10px;">Returned ${data.count} rows:</div>
                    <table class="data-table"><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>
                `;
            } else {
                resContainer.innerHTML = `<div style="padding:16px;color:var(--success);font-family:var(--font-mono);font-size:0.85rem;">${data.message} (Rows affected: ${data.affected_rows})</div>`;
                initStats();
            }
        } catch (e) {
            resContainer.innerHTML = `<div style="padding:16px;color:var(--danger);">Error executing query: ${e}</div>`;
        }
    });
}

// MODALS (REGISTRATION & MANUAL ENTRY)
function initModals() {
    const regModal = document.getElementById('register-modal');
    const manualModal = document.getElementById('manual-modal');

    // Open Register Modal
    document.getElementById('btn-open-register').addEventListener('click', () => openRegisterModal());
    document.getElementById('btn-add-student-modal').addEventListener('click', () => openRegisterModal());
    document.getElementById('btn-close-register').addEventListener('click', () => closeRegisterModal());
    document.getElementById('btn-cancel-register').addEventListener('click', () => closeRegisterModal());

    // Registration Mode Switch (Cam vs Upload)
    document.querySelectorAll('input[name="reg-mode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const val = e.target.value;
            document.querySelectorAll('.radio-pill').forEach(p => p.classList.remove('active'));
            e.target.parentElement.classList.add('active');

            if (val === 'cam') {
                document.getElementById('reg-cam-section').style.display = 'block';
                document.getElementById('reg-upload-section').style.display = 'none';
                startRegCamera();
            } else {
                document.getElementById('reg-cam-section').style.display = 'none';
                document.getElementById('reg-upload-section').style.display = 'block';
                stopRegCamera();
            }
        });
    });

    // Snap Photos in Modal
    document.getElementById('btn-snap-photo').addEventListener('click', () => {
        const regVideo = document.getElementById('reg-webcam-video');
        const snapCanvas = document.getElementById('reg-snapshot-canvas');
        if (!regVideo || regVideo.videoWidth === 0) return;

        snapCanvas.width = regVideo.videoWidth;
        snapCanvas.height = regVideo.videoHeight;
        const ctx = snapCanvas.getContext('2d');
        ctx.drawImage(regVideo, 0, 0, snapCanvas.width, snapCanvas.height);

        const b64 = snapCanvas.toDataURL('image/jpeg', 0.9);
        capturedPhotos.push(b64);
        renderSnapThumbnails();
    });

    document.getElementById('btn-clear-snaps').addEventListener('click', () => {
        capturedPhotos = [];
        renderSnapThumbnails();
    });

    // File Dropzone
    const dropzone = document.getElementById('file-dropzone');
    const fileInput = document.getElementById('reg-file-input');
    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.style.borderColor = 'var(--accent)'; });
    dropzone.addEventListener('dragleave', () => { dropzone.style.borderColor = ''; });
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.style.borderColor = '';
        if (e.dataTransfer.files) handleImageFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files) handleImageFiles(fileInput.files);
    });

    // Submit Registration Form
    document.getElementById('register-student-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('reg-student-name').value.trim();
        const email = document.getElementById('reg-student-email').value.trim();

        if (capturedPhotos.length === 0) {
            showToast('Please capture or upload at least 1 face photo.', 'error');
            return;
        }

        const submitBtn = document.getElementById('btn-submit-register');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing & Extracting Biometrics...';

        try {
            const res = await fetch('/api/register_student', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, images: capturedPhotos })
            });
            const data = await res.json();

            if (res.ok) {
                showToast(`Student ${name} successfully registered with ${data.embeddings_added} biometric vectors!`, 'success');
                closeRegisterModal();
                loadStudents();
                initStats();
            } else {
                showToast(data.detail || 'Registration failed', 'error');
            }
        } catch (err) {
            showToast('Error registering: ' + err, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Register & Compute Embeddings';
        }
    });

    // Open Manual Entry Modal
    document.getElementById('btn-manual-mark-modal').addEventListener('click', async () => {
        const select = document.getElementById('manual-student-select');
        select.innerHTML = '<option value="">Loading students...</option>';

        try {
            const res = await fetch('/api/students');
            const students = await res.json();
            select.innerHTML = students.map(s => `<option value="${s.name}">${s.name} (${s.email})</option>`).join('');
        } catch (e) {
            select.innerHTML = '<option value="">Failed to load</option>';
        }

        const today = new Date().toISOString().split('T')[0];
        const now = new Date().toTimeString().split(' ')[0];
        document.getElementById('manual-date').value = today;
        document.getElementById('manual-time').value = now;

        manualModal.showModal();
    });

    document.getElementById('btn-close-manual').addEventListener('click', () => manualModal.close());
    document.getElementById('btn-cancel-manual').addEventListener('click', () => manualModal.close());

    document.getElementById('manual-attendance-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('manual-student-select').value;
        const date = document.getElementById('manual-date').value;
        const time_in = document.getElementById('manual-time').value;

        try {
            const res = await fetch('/api/attendance/manual', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, date, time_in })
            });
            const data = await res.json();
            if (res.ok) {
                showToast(data.message, 'success');
                manualModal.close();
                loadAttendance();
                initStats();
            } else {
                showToast(data.detail || 'Error logging manual entry', 'error');
            }
        } catch (err) {
            showToast('Error: ' + err, 'error');
        }
    });
}

function openRegisterModal() {
    const modal = document.getElementById('register-modal');
    modal.showModal();
    capturedPhotos = [];
    renderSnapThumbnails();
    document.getElementById('register-student-form').reset();
    startRegCamera();
}

function closeRegisterModal() {
    const modal = document.getElementById('register-modal');
    modal.close();
    stopRegCamera();
}

async function startRegCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 480, height: 360, facingMode: 'user' },
            audio: false
        });
        regVideoStream = stream;
        document.getElementById('reg-webcam-video').srcObject = stream;
    } catch (e) {
        console.warn('Registration camera error:', e);
    }
}

function stopRegCamera() {
    if (regVideoStream) {
        regVideoStream.getTracks().forEach(t => t.stop());
        regVideoStream = null;
    }
}

function renderSnapThumbnails() {
    const container = document.getElementById('snap-thumbnails');
    const uploadContainer = document.getElementById('upload-thumbnails');
    document.getElementById('snap-count').textContent = capturedPhotos.length;

    const html = capturedPhotos.map((src, i) => `
        <div style="position:relative;display:inline-block;">
            <img class="snap-thumb" src="${src}" alt="Snap ${i+1}">
            <button type="button" onclick="removeSnap(${i})" style="position:absolute;top:-4px;right:-4px;background:var(--danger);color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:11px;cursor:pointer;">&times;</button>
        </div>
    `).join('');

    container.innerHTML = html;
    uploadContainer.innerHTML = html;
}

window.removeSnap = function(index) {
    capturedPhotos.splice(index, 1);
    renderSnapThumbnails();
};

function handleImageFiles(fileList) {
    Array.from(fileList).forEach(file => {
        if (!file.type.startsWith('image/')) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            capturedPhotos.push(e.target.result);
            renderSnapThumbnails();
        };
        reader.readAsDataURL(file);
    });
}
