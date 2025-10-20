# Doctor-only access decorator
def doctor_required(f):
    # Avoid using @wraps here since imports are defined below
    def decorated(*args, **kwargs):
        if not session.get('doctor_ok'):
            return redirect(url_for('doctor_login'))
        return f(*args, **kwargs)
    try:
        # Assign original name for Flask routing/debug friendliness
        decorated.__name__ = f.__name__
    except Exception:
        pass
    return decorated

from flask import Flask, render_template, request, redirect, jsonify, Response, send_from_directory, session, url_for
from camera import camera, generate_frames
from db import (
    init_db, insert_patient, query_patients, get_patient, update_patient, delete_patient,
    store_patient, query_stored, get_stored, get_setting, set_setting,
    add_doctor, list_doctors, delete_doctor, verify_doctor,
    add_hospital, list_hospitals, delete_hospital, verify_hospital, delete_stored,
    get_or_create_profile, get_profile, get_profile_visits, get_conn,
    create_patient_profile, update_patient_profile, get_all_patient_profiles, verify_patient_login,
    generate_patient_qr_code, verify_patient_qr_code, parse_qr_code_data
)
import serial
import json
import threading
import time
from datetime import datetime
from functools import wraps
import os
import queue
import threading as _threading

init_db()  # <-- Initialize DB and create tables before anything else

app = Flask(__name__)
# Use a static secret key at startup to avoid DB access before init
app.secret_key = 'dev_secret_key'

# ESP32 Serial Configuration
SERIAL_PORT = 'COM3'  # Change to your ESP32 port
BAUD_RATE = 115200

# Store latest sensor data
latest_sensor_data = {
    'temperature': 0,
    'heart_rate': 0,
    'spo2': 0,
    'weight': 0,
    'env_temperature': 0,
    'humidity': 0,
    'status': 'normal',
    'measurements': 0,
    'timestamp': datetime.now().strftime('%H:%M:%S')
}

# History for charts (last 50 readings)
sensor_history = {
    'temperature': [],
    'heart_rate': [],
    'spo2': [],
    'weight': [],
    'env_temperature': [],
    'humidity': [],
    'timestamps': []
}

ser = None

def read_esp32_serial():
    """Background thread to read ESP32 serial data"""
    global latest_sensor_data, sensor_history, ser
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"✅ Connected to ESP32 on {SERIAL_PORT}")
        time.sleep(2)  # Wait for ESP32 to initialize
        
        while True:
            try:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8').strip()
                    
                    # Look for JSON data from ESP32
                    if line.startswith("JSON:"):
                        json_str = line.replace("JSON:", "")
                        data = json.loads(json_str)
                        
                        # Update latest data
                        latest_sensor_data = {
                            'temperature': data.get('temperature', 0),
                            'heart_rate': data.get('heartRate', 0),
                            'spo2': data.get('spo2', 0),
                            'weight': data.get('weight', 0),
                            'env_temperature': data.get('envTemperature', 0),
                            'humidity': data.get('humidity', 0),
                            'status': data.get('status', 'normal'),
                            'measurements': data.get('measurements', 0),
                            'timestamp': datetime.now().strftime('%H:%M:%S')
                        }
                        
                        # Update history for charts
                        sensor_history['timestamps'].append(latest_sensor_data['timestamp'])
                        sensor_history['temperature'].append(latest_sensor_data['temperature'])
                        sensor_history['heart_rate'].append(latest_sensor_data['heart_rate'])
                        sensor_history['spo2'].append(latest_sensor_data['spo2'])
                        sensor_history['weight'].append(latest_sensor_data['weight'])
                        sensor_history['env_temperature'].append(latest_sensor_data['env_temperature'])
                        sensor_history['humidity'].append(latest_sensor_data['humidity'])
                        
                        # Keep only last 50 readings
                        if len(sensor_history['timestamps']) > 50:
                            for key in sensor_history:
                                sensor_history[key].pop(0)
                        
                        print(f"📊 ESP32 Data: Temp={latest_sensor_data['temperature']}°C, HR={latest_sensor_data['heart_rate']}bpm, SpO2={latest_sensor_data['spo2']}%, Weight={latest_sensor_data['weight']}kg, EnvTemp={latest_sensor_data['env_temperature']}°C, Humidity={latest_sensor_data['humidity']}%")
                    
                    else:
                        # Print other serial output (debug messages)
                        print(line)
                        
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"Error reading ESP32 serial: {e}")
                
    except serial.SerialException as e:
        print(f"❌ Could not connect to ESP32 on {SERIAL_PORT}: {e}")
        print("   Make sure:")
        print("   1. ESP32 is connected via USB")
        print("   2. Correct COM port is selected")
        print("   3. No other program is using the port")
        print("   Continuing without ESP32 connection...")
        # Continue running without ESP32
        while True:
            time.sleep(10)  # Keep thread alive but don't try to reconnect

# Start ESP32 serial reading thread
esp32_thread = threading.Thread(target=read_esp32_serial, daemon=True)
esp32_thread.start()

# -------------------
# Real-time SSE Broker
# -------------------
_sse_subscribers = []  # list[queue.Queue]
_sse_lock = _threading.Lock()

def sse_publish(event: str, data: dict):
    try:
        import json as _json
        payload = f"event: {event}\ndata: {_json.dumps(data)}\n\n"
    except Exception:
        payload = f"event: {event}\ndata: {{}}\n\n"
    with _sse_lock:
        subs = list(_sse_subscribers)
    for q in subs:
        try:
            q.put_nowait(payload)
        except Exception:
            pass

@app.route('/events/patients')
def sse_events():
    def stream():
        q = queue.Queue()
        with _sse_lock:
            _sse_subscribers.append(q)
        try:
            # Initial hello to open the stream
            yield 'event: hello\ndata: {}\n\n'
            while True:
                msg = q.get()
                yield msg
        finally:
            with _sse_lock:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)
    return Response(stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# Access control gateway
@app.before_request
def enforce_access_rules():
    path = request.path or '/'
    # Always allow static and uploaded assets
    if path.startswith('/static') or path.startswith('/uploads'):
        return None
    # Always allow auth routes
    if path in ('/login/hospital', '/hospital_login', '/login/doctor', '/logout'):
        return None
    # Allow patient sign-in page without auth; restrict other patient pages
    if path.startswith('/PatientSignin'):
        return None
    if path == '/patient/signin':
        return None
    if path == '/patient_signin':
        return None
    if path.startswith('/qr/scan'):
        return None
    # Admin: full access
    if session.get('hospital_ok'):
        return None
    # Doctor: only dashboard/store related
    if session.get('doctor_ok'):
        allowed_prefixes = (
            '/dashboard', '/store', '/export.csv', '/store.csv', '/view/', '/stored/', '/doctor', '/PatientProfiles.html', '/PatientAccount.html', '/qr/', '/api/qr/',
            '/events', '/api/patients', '/api/stored', '/api/profiles'
        )
        if any(path == p or path.startswith(p) for p in allowed_prefixes):
            return None
        # Block everything else
        return redirect(url_for('dashboard'))
    # Patient session: allow only their own account and QR
    if session.get('patient_ok'):
        allowed_prefixes = ('/PatientAccount.html', '/PatientSignin.html', '/qr/', '/logout', '/upload_photo', '/patient/photo')
        if any(path == p or path.startswith(p) for p in allowed_prefixes):
            return None
        # Redirect patient to their account by default
        pid = session.get('patient_id')
        if pid:
            return redirect(url_for('patient_account') + f'?patient_id={pid}')
        return redirect(url_for('patient_signin'))
    # Hospital limited: only QA and camera feed
    if session.get('hospital_limited'):
        allowed_prefixes = (
            '/qa', '/camera', '/camera/video_feed', '/api/patient', '/api/sensor', '/take_picture', '/upload_photo', '/api/verify-qr'
        )
        if any(path == p or path.startswith(p) for p in allowed_prefixes):
            return None
        return redirect(url_for('qa_intake'))
    # Unauthenticated: send to login
    if not path.startswith('/login') and path not in ('/hospital_login','/doctor_login'):
        return redirect(url_for('hospital_login'))
    return None

@app.route('/')
def home():
    # Admin sees home; doctors limited to dashboard/store; hospital limited to QA only
    if session.get('doctor_ok'):
        return redirect(url_for('dashboard'))
    if session.get('hospital_limited'):
        return redirect(url_for('qa_intake'))
    if not session.get('hospital_ok'):
        return redirect(url_for('hospital_login'))
    return render_template('index.html')

@app.route('/sensor')
def sensor():
    if not session.get('hospital_ok'):
        return redirect(url_for('hospital_login'))
    return render_template('sensor.html', data=latest_sensor_data)

@app.route('/port')
def port_page():
    if not session.get('hospital_ok'):
        return redirect(url_for('hospital_login'))
    return render_template('port.html', ports=[SERIAL_PORT], selected_port=SERIAL_PORT)

# JSON sensor snapshot
@app.route('/api/sensor')
def api_sensor():
    return jsonify(latest_sensor_data)

@app.route('/api/sensor/history')
def api_sensor_history():
    return jsonify(sensor_history)

@app.route('/set_port', methods=['POST'])
def set_port():
    global SERIAL_PORT
    port = request.form.get('port')
    SERIAL_PORT = port
    return redirect('/sensor')

# Q&A Integration Routes
@app.route('/qa')
def qa_intake():
    # accessible by admin and limited hospital account
    if not (session.get('hospital_ok') or session.get('hospital_limited')):
        return redirect(url_for('hospital_login'))
    return render_template('qa.html')

@app.route('/camera')
def camera_page():
    if not (session.get('hospital_ok') or session.get('hospital_limited')):
        return redirect(url_for('hospital_login'))
    return render_template('camera.html')

@app.route('/camera/video_feed')
def video_feed():
    if not (session.get('hospital_ok') or session.get('hospital_limited')):
        return redirect(url_for('hospital_login'))
    if not camera.running:
        try:
            camera.start()
        except Exception as e:
            return f"Camera error: {e}", 503, {'Content-Type': 'text/plain'}
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/take_picture')
def take_picture():
    if not camera.running:
        try:
            camera.start()
            print("✅ Camera started for photo capture")
        except Exception as e:
            print(f"❌ Camera start error: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 503
    filename = camera.take_picture()
    if not filename:
        print("❌ No frame available for photo capture")
        return jsonify({'status': 'error', 'message': 'No frame available'}), 500
    print(f"✅ Photo captured: {filename}")
    return jsonify({'status': 'success', 'filename': filename})

@app.route('/camera_status')
def camera_status():
    return jsonify({
        'running': camera.running,
        'has_frame': camera.frame is not None,
        'camera_index': camera.camera_index
    })

@app.route('/test_photo')
def test_photo():
    """Test route to verify photo capture is working"""
    if not camera.running:
        try:
            camera.start()
            print("✅ Camera started for test photo")
        except Exception as e:
            print(f"❌ Camera start error: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 503
    
    filename = camera.take_picture()
    if not filename:
        print("❌ No frame available for test photo")
        return jsonify({'status': 'error', 'message': 'No frame available'}), 500
    
    print(f"✅ Test photo captured: {filename}")
    return jsonify({'status': 'success', 'filename': filename})

@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    print(f"📸 Photo upload request received")
    print(f"📸 Request files: {list(request.files.keys())}")
    
    if 'photo' not in request.files:
        print("❌ No photo file in request")
        return jsonify({'status': 'error', 'message': 'No photo uploaded'}), 400
    
    photo = request.files['photo']
    print(f"📸 Photo file: {photo.filename}, size: {photo.content_length}")
    
    if photo.filename == '':
        print("❌ Empty photo filename")
        return jsonify({'status': 'error', 'message': 'No photo selected'}), 400
    
    # Generate unique filename
    import uuid
    filename = f"patient_{uuid.uuid4().hex[:8]}.jpg"
    print(f"📸 Generated filename: {filename}")
    
    # Save photo to uploads directory
    try:
        # Ensure uploads directory exists at absolute path
        uploads_dir = os.path.join(app.root_path, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)

        filepath = os.path.join(uploads_dir, filename)
        photo.save(filepath)

        # Verify file was created
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            print(f"✅ Photo saved successfully: {filename} ({file_size} bytes)")
            return jsonify({'status': 'success', 'filename': filename})
        else:
            print(f"❌ Photo file was not created: {filepath}")
            return jsonify({'status': 'error', 'message': 'File not created'}), 500
            
    except Exception as e:
        print(f"❌ Photo save error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Robot Interview Data Submission (links to existing patient profiles)
@app.route('/api/robot-patient', methods=['POST'])
def save_robot_patient():
    """Save robot interview data and link to existing patient profile"""
    data = request.get_json(silent=True) or {}
    
    # Debug: Print received data
    print(f"🤖 Received robot interview data: {data}")
    print(f"🆔 Patient ID: {data.get('patient_id')}")
    
    # Get patient ID from robot interview
    patient_id = data.get('patient_id')
    if not patient_id:
        return jsonify({'status': 'error', 'message': 'Patient ID is required'}), 400
    
    try:
        patient_id = int(patient_id)
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid Patient ID format'}), 400
    
    # Check if patient profile exists
    profile = get_profile(patient_id)
    if not profile:
        return jsonify({'status': 'error', 'message': f'Patient profile with ID {patient_id} not found'}), 404
    
    # Prefer captured values sent by client; fallback to latest_sensor_data
    temp_c = latest_sensor_data.get('temperature', 0)
    temp_f_latest = (temp_c * 9/5 + 32) if temp_c > 0 else None
    env_temp_c = latest_sensor_data.get('env_temperature', 0)
    env_temp_f_latest = (env_temp_c * 9/5 + 32) if env_temp_c > 0 else None
    
    def num_or_none(v):
        try:
            return float(v) if v is not None and v != '' else None
        except Exception:
            return None
    
    heart_rate = num_or_none(data.get('heart_rate'))
    if heart_rate is None:
        heart_rate = num_or_none(latest_sensor_data.get('heart_rate'))
    
    spo2 = num_or_none(data.get('spo2'))
    if spo2 is None:
        spo2 = num_or_none(latest_sensor_data.get('spo2'))
    
    body_temp_f = num_or_none(data.get('body_temp_f'))
    if body_temp_f is None:
        body_temp_f = temp_f_latest
    
    env_temp_f = num_or_none(data.get('env_temp_f'))
    if env_temp_f is None:
        env_temp_f = env_temp_f_latest
    
    humidity_percent = num_or_none(data.get('humidity_percent'))
    if humidity_percent is None:
        humidity_percent = num_or_none(latest_sensor_data.get('humidity'))
    
    weight_kg = num_or_none(data.get('weight_kg'))
    if weight_kg is None:
        weight_kg = num_or_none(latest_sensor_data.get('weight'))
    
    # Save robot interview data as a new patient visit linked to existing profile
    values = (
        patient_id, data.get('photo'), data.get('name'), data.get('age'), data.get('gender'), 
        data.get('contact'), data.get('address'),
        data.get('chief_complaint'), data.get('pain_level'), data.get('pain_description'), 
        data.get('additional_symptoms'),
        data.get('medical_history'), data.get('emergency_name'), data.get('emergency_relation'), 
        data.get('emergency_gender'),
        data.get('emergency_contact'), data.get('emergency_address'), 
        heart_rate, spo2,
        body_temp_f, env_temp_f, humidity_percent, weight_kg
    )
    
    print(f"🤖 Saving robot interview data for patient profile {patient_id}")
    row_id = insert_patient(values)
    print(f"✅ Robot interview data saved with ID: {row_id}")
    # Publish SSE event for real-time updates
    try:
        sse_publish('patient_added', {'id': int(row_id), 'profile_id': int(patient_id)})
    except Exception:
        pass
    
    return jsonify({
        'status': 'ok', 
        'id': row_id, 
        'profile_id': patient_id,
        'message': f'Robot interview data successfully linked to patient profile {patient_id}'
    })

# Save patient and vitals (expects JSON)
@app.route('/api/patient', methods=['POST'])
def save_patient():
    data = request.get_json(silent=True) or {}
    
    # Debug: Print received data
    print(f"📊 Received patient data: {data}")
    print(f"📸 Photo field: {data.get('photo')}")
    
    # Prefer captured values sent by client; fallback to latest_sensor_data
    temp_c = latest_sensor_data.get('temperature', 0)
    temp_f_latest = (temp_c * 9/5 + 32) if temp_c > 0 else None
    env_temp_c = latest_sensor_data.get('env_temperature', 0)
    env_temp_f_latest = (env_temp_c * 9/5 + 32) if env_temp_c > 0 else None
    
    def num_or_none(v):
        try:
            return float(v) if v is not None and v != '' else None
        except Exception:
            return None
    
    heart_rate = num_or_none(data.get('heart_rate'))
    if heart_rate is None:
        heart_rate = num_or_none(latest_sensor_data.get('heart_rate'))
    
    spo2 = num_or_none(data.get('spo2'))
    if spo2 is None:
        spo2 = num_or_none(latest_sensor_data.get('spo2'))
    
    body_temp_f = num_or_none(data.get('body_temp_f'))
    if body_temp_f is None:
        body_temp_f = temp_f_latest
    
    env_temp_f = num_or_none(data.get('env_temp_f'))
    if env_temp_f is None:
        env_temp_f = env_temp_f_latest
    
    humidity_percent = num_or_none(data.get('humidity_percent'))
    if humidity_percent is None:
        humidity_percent = num_or_none(latest_sensor_data.get('humidity'))
    
    weight_kg = num_or_none(data.get('weight_kg'))
    if weight_kg is None:
        weight_kg = num_or_none(latest_sensor_data.get('weight'))
    
    profile_id = get_or_create_profile(
        data.get('name'), data.get('contact'), data.get('gender'), data.get('address'), data.get('medical_history'), data.get('photo')
    )

    values = (
        profile_id, data.get('photo'), data.get('name'), data.get('age'), data.get('gender'), data.get('contact'), data.get('address'),
        data.get('chief_complaint'), data.get('pain_level'), data.get('pain_description'), data.get('additional_symptoms'),
        data.get('medical_history'), data.get('emergency_name'), data.get('emergency_relation'), data.get('emergency_gender'),
        data.get('emergency_contact'), data.get('emergency_address'), 
        heart_rate, spo2,
        body_temp_f, env_temp_f, humidity_percent, weight_kg
    )
    print(f"💾 Saving patient with photo: {values[0]}")
    row_id = insert_patient(values)
    print(f"✅ Patient saved with ID: {row_id}")
    # Publish SSE event for real-time updates
    try:
        sse_publish('patient_added', {'id': int(row_id), 'profile_id': int(profile_id)})
    except Exception:
        pass
    return jsonify({'status': 'ok', 'id': row_id})

# Dashboard
@app.route('/dashboard')
@doctor_required
def dashboard():
    # Doctor-only
    q = request.args.get('q')
    rows = query_patients(q)
    return render_template('dashboard.html', rows=rows, q=q)

# CSV export
@app.route('/export.csv')
def export_csv():
    q = request.args.get('q')
    rows = query_patients(q)
    headers = [
        'photo','name','age','gender','contact','address','chief_complaint','pain_level','pain_description','additional_symptoms',
        'medical_history','emergency_name','emergency_relation','emergency_gender','emergency_contact','emergency_address',
        'heart_rate','spo2','body_temp_f','env_temp_f','humidity_percent','weight_kg','created_at'
    ]
    def generate():
        yield ','.join(headers) + '\n'
        for r in rows:
            vals = [str(r[h] if h in r.keys() else '') for h in headers]
            vals = ['"' + v.replace('"','""') + '"' if (',' in v or '"' in v or '\n' in v) else v for v in vals]
            yield ','.join(vals) + '\n'
    return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="patients.csv"'})

# Store page (archived list)
@app.route('/store')
@doctor_required
def store_page():
    # Doctor-only
    q = request.args.get('q')
    rows = query_stored(q)
    return render_template('store.html', rows=rows, q=q)

@app.route('/store/delete/<int:stored_id>', methods=['POST'])
@doctor_required
def store_delete(stored_id: int):
    delete_stored(stored_id)
    return redirect(url_for('store_page'))

@app.route('/store.csv')
@doctor_required
def export_store_csv():
    q = request.args.get('q')
    rows = query_stored(q)
    headers = [
        'photo','name','age','gender','contact','address','chief_complaint','pain_level','pain_description','additional_symptoms',
        'medical_history','emergency_name','emergency_relation','emergency_gender','emergency_contact','emergency_address',
        'heart_rate','spo2','body_temp_f','env_temp_f','humidity_percent','weight_kg','created_at','archived_at'
    ]
    def generate():
        yield ','.join(headers) + '\n'
        for r in rows:
            vals = [str(r[h] if h in r.keys() else '') for h in headers]
            vals = ['"' + v.replace('"','""') + '"' if (',' in v or '"' in v or '\n' in v) else v for v in vals]
            yield ','.join(vals) + '\n'
    return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="store.csv"'})

# Archive on view: move to store then show report
@app.route('/view/<int:patient_id>')
def archive_and_view(patient_id: int):
    if not session.get('doctor_ok'):
        return redirect(url_for('doctor_login'))
    stored_id = store_patient(patient_id)
    if not stored_id:
        return redirect('/dashboard')
    try:
        sse_publish('patient_archived', {'stored_id': int(stored_id)})
    except Exception:
        pass
    return redirect(f'/stored/{stored_id}')

# -------------------
# Realtime JSON APIs
# -------------------
@app.route('/api/patients/recent')
def api_patients_recent():
    try:
        limit = int(request.args.get('limit', 25))
    except Exception:
        limit = 25
    q = request.args.get('q')
    rows = query_patients(q)
    out = []
    for r in rows[:limit]:
        out.append({k: r[k] for k in r.keys()})
    return jsonify(out)

@app.route('/api/stored/recent')
def api_stored_recent():
    try:
        limit = int(request.args.get('limit', 25))
    except Exception:
        limit = 25
    q = request.args.get('q')
    rows = query_stored(q)
    out = []
    for r in rows[:limit]:
        out.append({k: r[k] for k in r.keys()})
    return jsonify(out)

@app.route('/api/profiles/list')
def api_profiles_list():
    search = request.args.get('search')
    rows = get_all_patient_profiles(search)
    out = []
    for r in rows:
        out.append({k: r[k] for k in r.keys()})
    return jsonify(out)

# Serve uploaded photos
@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(os.path.join(app.root_path, 'uploads'), filename)

# Patient report page
@app.route('/report/<int:patient_id>')
def report(patient_id: int):
    row = get_patient(patient_id)
    if not row:
        return "Not found", 404
    return render_template('report.html', r=row)

# Stored report page (archived)
@app.route('/stored/<int:stored_id>')
def stored_report(stored_id: int):
    row = get_stored(stored_id)
    if not row:
        return "Not found", 404
    return render_template('report.html', r=row)

@app.route('/PatientSignin.html', methods=['GET'])
def patient_signin():
    return render_template('PatientSignin.html')


@app.route('/patient/signin', methods=['POST'])
def patient_signin_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    qr_pid = request.form.get('patient_id') or request.args.get('patient_id')

    profile = verify_patient_login(username, password)
    if not profile:
        return render_template('PatientSignin.html', error='Invalid Username or Password')
    # If coming from QR, enforce patient_id matches the QR
    try:
        if qr_pid is not None and int(qr_pid) != int(profile['id']):
            return render_template('PatientSignin.html', error='This QR belongs to a different patient. Please check and try again.', patient_id=qr_pid)
    except Exception:
        pass

    session.clear()
    session['patient_ok'] = True
    session['patient_id'] = int(profile['id'])
    session.permanent = True

    return redirect(url_for('patient_account') + f'?patient_id={profile["id"]}')

@app.route('/patient/photo', methods=['POST'])
def patient_set_photo():
    if not session.get('patient_ok'):
        return redirect(url_for('patient_signin'))
    filename = request.form.get('filename')
    if not filename:
        return jsonify({'error': 'filename required'}), 400
    try:
        with get_conn() as conn:
            conn.execute('UPDATE patient_profiles SET photo = ? WHERE id = ?', (filename, int(session.get('patient_id'))))
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return redirect(url_for('patient_account') + f'?patient_id={int(session.get("patient_id"))}')


def _get_representative_photo(profile_row):
    try:
        if profile_row and profile_row['photo']:
            return profile_row['photo']
    except Exception:
        pass
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT photo FROM (
                  SELECT photo, datetime(created_at) AS ts FROM patients WHERE profile_id = ? AND photo IS NOT NULL
                  UNION ALL
                  SELECT photo, datetime(archived_at) AS ts FROM stored_patients WHERE profile_id = ? AND photo IS NOT NULL
                )
                WHERE photo IS NOT NULL
                ORDER BY ts DESC
                LIMIT 1
                """,
                (profile_row['id'], profile_row['id'])
            ).fetchone()
            return row['photo'] if row else None
    except Exception:
        return None


@app.route('/PatientAccount.html', methods=['GET'])
def patient_account():
    # If doctor or hospital staff is logged in, allow viewing any patient by query param
    if session.get('doctor_ok') or session.get('hospital_ok') or session.get('hospital_limited'):
        q_id = request.args.get('patient_id')
        try:
            patient_id = int(q_id) if q_id is not None else None
        except (ValueError, TypeError):
            patient_id = None
        if not patient_id:
            return render_template('PatientAccount.html', patient=None)
        profile = get_profile(patient_id)
        if not profile:
            return render_template('PatientAccount.html', patient=None)
        current_visits, archived_visits = get_profile_visits(patient_id)
        visits = list(current_visits) + list(archived_visits)
        representative_photo = _get_representative_photo(profile)
        return render_template('PatientAccount.html', patient=profile, visits=visits, representative_photo=representative_photo)

    # If patient is logged in, enforce self-access only
    if session.get('patient_ok'):
        q_id = request.args.get('patient_id')
        try:
            q_id_int = int(q_id) if q_id is not None else None
        except (ValueError, TypeError):
            q_id_int = None

        current_pid = session.get('patient_id')
        if not current_pid:
            return redirect(url_for('patient_signin'))
        if q_id_int is None or q_id_int != int(current_pid):
            return redirect(url_for('patient_account') + f'?patient_id={current_pid}')

        profile = get_profile(current_pid)
        if not profile:
            return render_template('PatientAccount.html', patient=None)

        current_visits, archived_visits = get_profile_visits(current_pid)
        visits = list(current_visits) + list(archived_visits)

        representative_photo = _get_representative_photo(profile)
        return render_template('PatientAccount.html', patient=profile, visits=visits, representative_photo=representative_photo)

    # Otherwise, require doctor login for this page
    return redirect(url_for('doctor_login'))


@app.route('/patient_profile/<int:patient_id>', methods=['GET'])
def patient_profile_alias(patient_id: int):
    if not session.get('patient_ok'):
        return redirect(url_for('patient_signin'))
    if int(session.get('patient_id') or 0) != int(patient_id):
        return redirect(url_for('patient_account') + f'?patient_id={session.get("patient_id")}')
    return redirect(url_for('patient_account') + f'?patient_id={patient_id}')

@app.route('/patient_signin', methods=['GET','POST'])
def patient_signin_compat():
    if request.method == 'GET':
        return render_template('PatientSignin.html', patient_id=request.args.get('patient_id'))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    qr_pid = request.form.get('patient_id') or request.args.get('patient_id')
    profile = verify_patient_login(username, password)
    if not profile:
        return render_template('PatientSignin.html', error='Invalid Username or Password')
    try:
        if qr_pid is not None and int(qr_pid) != int(profile['id']):
            return render_template('PatientSignin.html', error='This QR belongs to a different patient. Please check and try again.', patient_id=qr_pid)
    except Exception:
        pass
    session.clear()
    session['patient_ok'] = True
    session['patient_id'] = int(profile['id'])
    session.permanent = True
    return redirect(url_for('patient_account') + f'?patient_id={profile["id"]}')

@app.route('/qr/scan')
def qr_scan_entry():
    # Accept either raw JSON in 'data' or 'patient_id' directly in query
    raw = request.args.get('data')
    pid_param = request.args.get('patient_id')
    pid = None
    if pid_param:
        try:
            pid = int(pid_param)
        except Exception:
            pid = None
    elif raw:
        try:
            parsed = parse_qr_code_data(raw)
            pid = int(parsed.get('patient_id')) if parsed and parsed.get('patient_id') is not None else None
        except Exception:
            pid = None

    if not pid:
        return redirect(url_for('patient_signin'))

    # If a doctor or hospital staff is logged in, go straight to the patient account
    if session.get('doctor_ok') or session.get('hospital_ok') or session.get('hospital_limited'):
        return redirect(url_for('patient_account') + f'?patient_id={pid}')

    # If a patient is logged in
    if session.get('patient_ok'):
        own_id = session.get('patient_id')
        if own_id and int(own_id) == int(pid):
            return redirect(url_for('patient_account') + f'?patient_id={pid}')
        # Different patient: require sign-in for the scanned patient
        session.clear()
        return redirect(url_for('patient_signin_compat', patient_id=pid))

    # Unauthenticated: go to patient sign-in with patient_id propagated
    return redirect(url_for('patient_signin_compat', patient_id=pid))

# Patient profile page
@app.route('/profile/<int:profile_id>')
def profile_page(profile_id: int):
    # Both doctor and hospital_limited can view profile if logged in
    if not (session.get('doctor_ok') or session.get('hospital_ok') or session.get('hospital_limited')):
        return redirect(url_for('hospital_login'))
    profile = get_profile(profile_id)
    if not profile:
        return "Not found", 404
    current_visits, archived_visits = get_profile_visits(profile_id)
    
    return render_template('doctor_patient_visits.html', profile=profile, current_visits=current_visits, archived_visits=archived_visits)

# Delete a patient profile (and related visits)
@app.route('/doctor/delete_profile/<int:profile_id>', methods=['POST'])
@doctor_required
def doctor_delete_profile(profile_id: int):
    try:
        with get_conn() as conn:
            # Remove visits referencing this profile to avoid orphaned rows
            conn.execute('DELETE FROM patients WHERE profile_id = ?', (profile_id,))
            conn.execute('DELETE FROM stored_patients WHERE profile_id = ?', (profile_id,))
            # Delete the patient profile itself
            conn.execute('DELETE FROM patient_profiles WHERE id = ?', (profile_id,))
        return redirect(url_for('patient_profiles'))
    except Exception as e:
        # On error, redirect back with a basic message (could be improved with flash)
        return redirect(url_for('patient_profiles'))

# Edit patient
@app.route('/edit/<int:patient_id>', methods=['GET', 'POST'])
def edit(patient_id: int):
    if not session.get('doctor_ok'):
        return redirect(url_for('doctor_login'))
    row = get_patient(patient_id)
    if not row:
        return "Not found", 404
    if request.method == 'POST':
        data = request.form.to_dict()
        update_patient(patient_id, data)
        return redirect(f'/report/{patient_id}')
    return render_template('edit.html', r=row)

# Delete patient
@app.route('/delete/<int:patient_id>', methods=['POST'])
def delete(patient_id: int):
    if not session.get('doctor_ok'):
        return redirect(url_for('doctor_login'))
    delete_patient(patient_id)
    return redirect('/dashboard')

@app.route('/hospital_login', methods=['GET', 'POST'])
@app.route('/login/hospital', methods=['GET', 'POST'])
def hospital_login():
    if request.method == 'POST':
        hid = request.form.get('hospital_id','')
        hpw = request.form.get('hospital_pw','')
        # Admin (hospital) login
        if hid == (get_setting('hospital_id') or '') and hpw == (get_setting('hospital_pw') or ''):
            session.clear()
            session['hospital_ok'] = True
            return redirect(url_for('home'))
        # hospital id (limited, QA only)
        if verify_hospital(hid, hpw):
            session.clear()
            session['hospital_limited'] = True
            return redirect(url_for('qa_intake'))
        # Accept doctor credentials here too for convenience
        if verify_doctor(hid, hpw) or (hid == (get_setting('doctor_id') or '') and hpw == (get_setting('doctor_pw') or '')):
            session.clear()
            session['doctor_ok'] = True
            session.permanent = True
            return redirect(url_for('dashboard'))
        return render_template('login_hospital.html', error='Invalid credentials')
    return render_template('login_hospital.html')

@app.route('/doctor_login', methods=['GET', 'POST'])
@app.route('/login/doctor', methods=['GET', 'POST'])
def doctor_login():
    if request.method == 'POST':
        did = request.form.get('doctor_id','')
        dpw = request.form.get('doctor_pw','')
        # accept either single doctor in settings or any in doctors table
        if (did == (get_setting('doctor_id') or '') and dpw == (get_setting('doctor_pw') or '')) or verify_doctor(did, dpw):
            session.clear()
            session['doctor_ok'] = True
            session.permanent = True
            return redirect(url_for('dashboard'))
        return render_template('login_doctor.html', error='Invalid credentials')
    return render_template('login_doctor.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('hospital_login'))

@app.route('/settings', methods=['GET','POST'])
def settings_page():
    if not session.get('hospital_ok'):
        return redirect(url_for('hospital_login'))
    if request.method == 'POST':
        sk = request.form.get('secret_key')
        hid = request.form.get('hospital_id')
        hpw = request.form.get('hospital_pw')
        did = request.form.get('doctor_id')
        dpw = request.form.get('doctor_pw')
        # add doctor action
        new_doc_id = request.form.get('new_doctor_id')
        new_doc_pw = request.form.get('new_doctor_pw')
        new_doc_name = request.form.get('new_doctor_name')
        del_doc = request.form.get('delete_doctor_id')
        # add hospital action (limited accounts)
        new_hosp_id = request.form.get('new_hospital_id')
        new_hosp_pw = request.form.get('new_hospital_pw')
        new_hosp_name = request.form.get('new_hospital_name')
        del_hosp = request.form.get('delete_hospital_id')
        if sk: set_setting('secret_key', sk)
        if hid is not None: set_setting('hospital_id', hid)
        if hpw is not None: set_setting('hospital_pw', hpw)
        if did is not None: set_setting('doctor_id', did)
        if dpw is not None: set_setting('doctor_pw', dpw)
        if new_doc_id and new_doc_pw:
            try:
                add_doctor(new_doc_id, new_doc_pw, new_doc_name)
            except Exception:
                pass
        if del_doc:
            try:
                delete_doctor(int(del_doc))
            except Exception:
                pass
        if new_hosp_id and new_hosp_pw:
            try:
                add_hospital(new_hosp_id, new_hosp_pw, new_hosp_name)
            except Exception:
                pass
        if del_hosp:
            try:
                delete_hospital(int(del_hosp))
            except Exception:
                pass
        return redirect(url_for('settings_page'))
    return render_template('settings.html',
        secret_key=get_setting('secret_key') or '',
        hospital_id=get_setting('hospital_id') or '',
        hospital_pw=get_setting('hospital_pw') or '',
        doctor_id=get_setting('doctor_id') or '',
        doctor_pw=get_setting('doctor_pw') or '',
        doctors=list_doctors(),
        hospitals=list_hospitals()
    )

# Patient Profile Management System Routes (No access restrictions)

@app.route('/PatientProfiles.html')
@doctor_required
def patient_profiles():
    """Display all registered patients with links to their accounts"""
    search_query = request.args.get('search', '')
    
    # Get all unique patient profiles with visit counts
    with get_conn() as conn:
        try:
            # Enriched query with representative photo
            query = """
                SELECT 
                    pp.id,
                    pp.name,
                    pp.gender,
                    pp.contact,
                    pp.address,
                    pp.photo,
                    COALESCE(pp.photo, lp.photo, lsp.photo) AS representative_photo,
                    pp.medical_history,
                    pp.allergies,
                    pp.medications,
                    pp.notes,
                    pp.created_at,
                    COUNT(DISTINCT p.id) + COUNT(DISTINCT sp.id) as visit_count,
                    MAX(COALESCE(p.created_at, sp.archived_at)) as last_visit
                FROM patient_profiles pp
                LEFT JOIN patients p ON pp.id = p.profile_id
                LEFT JOIN stored_patients sp ON pp.id = sp.profile_id
                LEFT JOIN (
                    SELECT p1.profile_id, p1.photo
                    FROM patients p1
                    INNER JOIN (
                        SELECT profile_id, MAX(created_at) AS max_created
                        FROM patients
                        WHERE profile_id IS NOT NULL AND photo IS NOT NULL
                        GROUP BY profile_id
                    ) pm ON pm.profile_id = p1.profile_id AND pm.max_created = p1.created_at
                ) lp ON lp.profile_id = pp.id
                LEFT JOIN (
                    SELECT sp1.profile_id, sp1.photo
                    FROM stored_patients sp1
                    INNER JOIN (
                        SELECT profile_id, MAX(archived_at) AS max_archived
                        FROM stored_patients
                        WHERE profile_id IS NOT NULL AND photo IS NOT NULL
                        GROUP BY profile_id
                    ) spm ON spm.profile_id = sp1.profile_id AND spm.max_archived = sp1.archived_at
                ) lsp ON lsp.profile_id = pp.id
            """
            params = []
            if search_query:
                query += " WHERE pp.name LIKE ? OR pp.contact LIKE ? OR pp.id LIKE ?"
                like_query = f"%{search_query}%"
                params = [like_query, like_query, like_query]
            query += " GROUP BY pp.id ORDER BY pp.created_at DESC"
            patients = conn.execute(query, params).fetchall()
        except Exception:
            # Fallback: basic query with representative_photo as pp.photo
            query = """
                SELECT 
                    pp.id,
                    pp.name,
                    pp.gender,
                    pp.contact,
                    pp.address,
                    pp.photo,
                    pp.photo AS representative_photo,
                    pp.medical_history,
                    pp.allergies,
                    pp.medications,
                    pp.notes,
                    pp.created_at,
                    0 as visit_count,
                    NULL as last_visit
                FROM patient_profiles pp
            """
            params = []
            if search_query:
                query += " WHERE pp.name LIKE ? OR pp.contact LIKE ? OR CAST(pp.id AS TEXT) LIKE ?"
                like_query = f"%{search_query}%"
                params = [like_query, like_query, like_query]
            query += " ORDER BY pp.created_at DESC"
            patients = conn.execute(query, params).fetchall()

        # Get statistics (guard if tables/columns missing)
        try:
            total_patients = conn.execute("SELECT COUNT(*) as count FROM patient_profiles").fetchone()['count']
        except Exception:
            total_patients = len(patients)
        try:
            active_patients = conn.execute("SELECT COUNT(DISTINCT profile_id) as count FROM patients WHERE profile_id IS NOT NULL").fetchone()['count']
        except Exception:
            active_patients = 0
        try:
            total_visits = conn.execute("SELECT COUNT(*) as count FROM patients").fetchone()['count']
            total_visits += conn.execute("SELECT COUNT(*) as count FROM stored_patients").fetchone()['count']
        except Exception:
            total_visits = 0
    
    return render_template('PatientProfiles.html',
        patients=patients,
        search_query=search_query,
        total_patients=total_patients,
        active_patients=active_patients,
        total_visits=total_visits
    )


# QR Code Routes

@app.route('/qr/<int:patient_id>')
def patient_qr_code(patient_id):
    """Generate and display QR code for a patient"""
    # Patients may only access their own QR
    if session.get('patient_ok'):
        own_id = session.get('patient_id')
        if not own_id or int(patient_id) != int(own_id):
            return redirect(url_for('patient_account') + f'?patient_id={own_id}')
    try:
        qr_image_base64 = generate_patient_qr_code(patient_id)
        profile = get_profile(patient_id)
        if not profile:
            return "Patient not found", 404
        
        return render_template('qr_display.html', 
                             qr_image=qr_image_base64, 
                             patient=profile)
    except Exception as e:
        return f"Error generating QR code: {str(e)}", 500

@app.route('/api/qr/<int:patient_id>')
def api_patient_qr_code(patient_id):
    """API endpoint to get QR code image as base64"""
    # Patients may only access their own QR
    if session.get('patient_ok'):
        own_id = session.get('patient_id')
        if not own_id or int(patient_id) != int(own_id):
            return jsonify({'error': 'Forbidden'}), 403
    try:
        qr_image_base64 = generate_patient_qr_code(patient_id)
        profile = get_profile(patient_id)
        if not profile:
            return jsonify({'error': 'Patient not found'}), 404
        
        return jsonify({
            'status': 'success',
            'qr_image': qr_image_base64,
            'patient_id': patient_id,
            'patient_name': profile['name'] if profile['name'] else 'Unknown'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify-qr', methods=['POST'])
def verify_qr_code():
    """API endpoint to verify QR code data"""
    data = request.get_json(silent=True) or {}
    qr_data = data.get('qr_data')
    
    if not qr_data:
        return jsonify({'error': 'QR code data is required'}), 400
    
    try:
        result = verify_patient_qr_code(qr_data)
        if result:
            return jsonify({
                'status': 'success',
                'patient_id': result['profile']['id'],
                'patient_name': result['profile']['name'] if result['profile']['name'] else 'Unknown',
                'profile': dict(result['profile'])
            })
        else:
            return jsonify({'error': 'Invalid QR code or patient not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Doctor Account Management Routes

@app.route('/doctor/create_patient', methods=['GET', 'POST'])
@doctor_required
def doctor_create_patient():
    """Doctors can create new patient accounts"""
    if not session.get('doctor_ok') and not session.get('hospital_ok'):
        return redirect(url_for('doctor_login'))
    
    if request.method == 'POST':
        data = request.form.to_dict()
        try:
            # Create new patient profile
            profile_id = create_patient_profile(data)
            return jsonify({'status': 'success', 'message': f'Patient account created successfully with ID: {profile_id}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error creating patient account: {str(e)}'}), 400
    
    return render_template('doctor_create_patient.html')

@app.route('/doctor/manage_patients')
@doctor_required
def doctor_manage_patients():
    """Doctors can view and manage all patient accounts"""
    if not session.get('doctor_ok') and not session.get('hospital_ok'):
        return redirect(url_for('doctor_login'))
    
    search_query = request.args.get('search', '')
    patients = get_all_patient_profiles(search_query)
    
    return render_template('doctor_manage_patients.html', 
                         patients=patients, 
                         search_query=search_query)

@app.route('/doctor/edit_patient/<int:profile_id>', methods=['GET', 'POST'])
@doctor_required
def doctor_edit_patient(profile_id):
    """Doctors can edit patient profile information"""
    if not session.get('doctor_ok') and not session.get('hospital_ok'):
        return redirect(url_for('doctor_login'))
    
    profile = get_profile(profile_id)
    if not profile:
        return "Patient profile not found", 404
    
    if request.method == 'POST':
        data = request.form.to_dict()
        try:
            update_patient_profile(profile_id, data)
            return jsonify({'status': 'success', 'message': 'Patient profile updated successfully'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error updating patient profile: {str(e)}'}), 400
    
    return render_template('doctor_edit_patient.html', profile=profile)

@app.route('/doctor/patient_visits/<int:profile_id>')
@doctor_required
def doctor_patient_visits(profile_id):
    """Doctors can view patient visit history"""
    if not session.get('doctor_ok') and not session.get('hospital_ok'):
        return redirect(url_for('doctor_login'))
    
    profile = get_profile(profile_id)
    if not profile:
        return "Patient profile not found", 404
    
    current_visits, archived_visits = get_profile_visits(profile_id)
    visits = list(current_visits) + list(archived_visits)
    visits.sort(key=lambda x: x['created_at'] or x['archived_at'], reverse=True)
    
    return render_template('doctor_patient_visits.html', 
                         profile=profile, 
                         visits=visits)


if __name__ == '__main__':
    # Ensure DB (including settings table) is initialized before first request
    init_db()
    # Seed default admin credentials if missing
    try:
        if not (get_setting('hospital_id') or ''):
            set_setting('hospital_id', 'buxin')
        if not (get_setting('hospital_pw') or ''):
            set_setting('hospital_pw', 'buxin')
        if not (get_setting('doctor_id') or ''):
            set_setting('doctor_id', 'buxin')
        if not (get_setting('doctor_pw') or ''):
            set_setting('doctor_pw', 'buxin')
        if not (get_setting('secret_key') or ''):
            set_setting('secret_key', 'sharda1')
    except Exception:
        pass
    
    # Start camera automatically (commented out for testing without hardware)
    # try:
    #     camera.start()
    #     print("✅ Camera started successfully")
    # except Exception as e:
    #     print(f"❌ Camera start failed: {e}")
    #     print("Camera will be started on first use")
    
    app.run(host='0.0.0.0', port=5000, debug=False)