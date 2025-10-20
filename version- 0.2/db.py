import sqlite3
import os
import json
import qrcode
import base64
from io import BytesIO
from typing import Iterable, Tuple, Any, Optional, Union

DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                photo TEXT,
                name TEXT,
                age INTEGER,
                gender TEXT,
                contact TEXT,
                address TEXT,
                chief_complaint TEXT,
                pain_level TEXT,
                pain_description TEXT,
                additional_symptoms TEXT,
                medical_history TEXT,
                emergency_name TEXT,
                emergency_relation TEXT,
                emergency_gender TEXT,
                emergency_contact TEXT,
                emergency_address TEXT,
                heart_rate REAL,
                spo2 REAL,
                body_temp_f REAL,
                env_temp_f REAL,
                humidity_percent REAL,
                weight_kg REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # patient profiles table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                dob TEXT,
                age INTEGER,
                gender TEXT,
                contact TEXT,
                address TEXT,
                emergency_name TEXT,
                emergency_relation TEXT,
                emergency_contact TEXT,
                emergency_address TEXT,
                medical_history TEXT,
                allergies TEXT,
                medications TEXT,
                prescriptions TEXT,
                test_results TEXT,
                diagnoses TEXT,
                treatment_records TEXT,
                photo TEXT,
                notes TEXT,
                username TEXT,
                patient_id_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # settings/auth
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        # doctors accounts
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id TEXT UNIQUE,
                doctor_pw TEXT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # hospital ids (non-admin limited accounts)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hospitals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hospital_id TEXT UNIQUE,
                hospital_pw TEXT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # archived/store table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stored_patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                photo TEXT,
                name TEXT,
                age INTEGER,
                gender TEXT,
                contact TEXT,
                address TEXT,
                chief_complaint TEXT,
                pain_level TEXT,
                pain_description TEXT,
                additional_symptoms TEXT,
                medical_history TEXT,
                emergency_name TEXT,
                emergency_relation TEXT,
                emergency_gender TEXT,
                emergency_contact TEXT,
                emergency_address TEXT,
                heart_rate REAL,
                spo2 REAL,
                body_temp_f REAL,
                env_temp_f REAL,
                humidity_percent REAL,
                weight_kg REAL,
                created_at TEXT,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Backfill for existing DBs: add missing columns if they don't exist
        cols = {row[1] for row in conn.execute('PRAGMA table_info(patients)').fetchall()}
        if 'humidity_percent' not in cols:
            conn.execute('ALTER TABLE patients ADD COLUMN humidity_percent REAL')
        if 'weight_kg' not in cols:
            conn.execute('ALTER TABLE patients ADD COLUMN weight_kg REAL')
        if 'profile_id' not in cols:
            conn.execute('ALTER TABLE patients ADD COLUMN profile_id INTEGER')

        s_cols = {row[1] for row in conn.execute('PRAGMA table_info(stored_patients)').fetchall()}
        if 'profile_id' not in s_cols:
            conn.execute('ALTER TABLE stored_patients ADD COLUMN profile_id INTEGER')
        
        # Backfill patient_profiles table with new columns
        pp_cols = {row[1] for row in conn.execute('PRAGMA table_info(patient_profiles)').fetchall()}
        new_pp_columns = [
            ('age', 'INTEGER'),
            ('emergency_name', 'TEXT'),
            ('emergency_relation', 'TEXT'),
            ('emergency_contact', 'TEXT'),
            ('emergency_address', 'TEXT'),
            ('prescriptions', 'TEXT'),
            ('test_results', 'TEXT'),
            ('diagnoses', 'TEXT'),
            ('treatment_records', 'TEXT'),
            ('username', 'TEXT'),
            ('patient_id_number', 'TEXT')
        ]
        for col_name, col_type in new_pp_columns:
            if col_name not in pp_cols:
                conn.execute(f'ALTER TABLE patient_profiles ADD COLUMN {col_name} {col_type}')
        
        conn.commit()
    # Backfill profiles after ensuring schemas
    try:
        backfill_profiles()
    except Exception:
        pass


def insert_patient(values: Tuple[Any, ...]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO patients (
                profile_id, photo, name, age, gender, contact, address,
                chief_complaint, pain_level, pain_description, additional_symptoms,
                medical_history, emergency_name, emergency_relation, emergency_gender,
                emergency_contact, emergency_address, heart_rate, spo2,
                body_temp_f, env_temp_f, humidity_percent, weight_kg
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            values,
        )
        conn.commit()
        return cur.lastrowid


def query_patients(search: Optional[str] = None) -> Iterable[sqlite3.Row]:
    with get_conn() as conn:
        if search:
            like = f"%{search}%"
            cur = conn.execute(
                """
                SELECT * FROM patients
                WHERE COALESCE(name,'') LIKE ?
                   OR COALESCE(age,'') LIKE ?
                   OR COALESCE(chief_complaint,'') LIKE ?
                ORDER BY datetime(created_at) DESC
                """,
                (like, like, like),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM patients ORDER BY datetime(created_at) DESC"
            )
        return cur.fetchall()


def get_patient(patient_id: int):
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
        return cur.fetchone()


def store_patient(patient_id: int) -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not row:
            return None
        cols = [
            'profile_id','photo','name','age','gender','contact','address','chief_complaint','pain_level','pain_description',
            'additional_symptoms','medical_history','emergency_name','emergency_relation','emergency_gender',
            'emergency_contact','emergency_address','heart_rate','spo2','body_temp_f','env_temp_f','humidity_percent','weight_kg','created_at'
        ]
        values = tuple(row[c] for c in cols)
        cur = conn.execute(
            f"INSERT INTO stored_patients ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})",
            values
        )
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()
        return cur.lastrowid


def get_or_create_profile(name: Optional[str], contact: Optional[str], gender: Optional[str] = None,
                          address: Optional[str] = None, medical_history: Optional[str] = None,
                          photo: Optional[str] = None) -> int:
    name = (name or '').strip()
    contact = (contact or '').strip()
    with get_conn() as conn:
        # Try to find existing profile by name + contact
        row = None
        if name or contact:
            row = conn.execute(
                "SELECT id FROM patient_profiles WHERE COALESCE(name,'') = ? AND COALESCE(contact,'') = ?",
                (name, contact)
            ).fetchone()
        if row:
            pid = int(row['id'])
            # optionally update missing basics
            conn.execute(
                "UPDATE patient_profiles SET gender=COALESCE(gender,?), address=COALESCE(address,?), medical_history=COALESCE(medical_history,?), photo=COALESCE(photo,?) WHERE id=?",
                (gender, address, medical_history, photo, pid)
            )
            conn.commit()
            return pid
        # Create new profile
        cur = conn.execute(
            "INSERT INTO patient_profiles(name, contact, gender, address, medical_history, photo) VALUES(?,?,?,?,?,?)",
            (name or None, contact or None, gender, address, medical_history, photo)
        )
        conn.commit()
        return cur.lastrowid


def get_profile(profile_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM patient_profiles WHERE id = ?", (profile_id,)).fetchone()


def get_profile_visits(profile_id: int):
    with get_conn() as conn:
        current = conn.execute(
            "SELECT *, 'current' AS source FROM patients WHERE profile_id = ? ORDER BY datetime(created_at) DESC",
            (profile_id,)
        ).fetchall()
        archived = conn.execute(
            "SELECT *, 'archived' AS source FROM stored_patients WHERE profile_id = ? ORDER BY datetime(archived_at) DESC",
            (profile_id,)
        ).fetchall()
        return current, archived


def backfill_profiles() -> None:
    """Populate missing profile_id for existing rows based on name+contact."""
    from typing import List
    with get_conn() as conn:
        # Load candidates from both tables where profile_id missing
        for table in ['patients', 'stored_patients']:
            rows: List[sqlite3.Row] = conn.execute(
                f"SELECT id, profile_id, name, contact, gender, address, medical_history, photo FROM {table} WHERE COALESCE(profile_id, 0) = 0"
            ).fetchall()
            for r in rows:
                pid = get_or_create_profile(
                    r['name'], r['contact'], r['gender'], r['address'], r['medical_history'], r['photo']
                )
                conn.execute(
                    f"UPDATE {table} SET profile_id = ? WHERE id = ?",
                    (pid, r['id'])
                )
        conn.commit()


def query_stored(search: Optional[str] = None) -> Iterable[sqlite3.Row]:
    with get_conn() as conn:
        if search:
            like = f"%{search}%"
            cur = conn.execute(
                """
                SELECT * FROM stored_patients
                WHERE COALESCE(name,'') LIKE ?
                   OR COALESCE(age,'') LIKE ?
                   OR COALESCE(chief_complaint,'') LIKE ?
                ORDER BY datetime(archived_at) DESC
                """,
                (like, like, like),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM stored_patients ORDER BY datetime(archived_at) DESC"
            )
        return cur.fetchall()


def get_stored(stored_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM stored_patients WHERE id = ?", (stored_id,)).fetchone()


def delete_stored(stored_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM stored_patients WHERE id = ?", (stored_id,))
        conn.commit()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return (row['value'] if row else default)


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()


def add_doctor(doctor_id: str, doctor_pw: str, name: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO doctors(doctor_id, doctor_pw, name) VALUES(?,?,?)",
            (doctor_id, doctor_pw, name)
        )
        conn.commit()
        return cur.lastrowid


def list_doctors():
    with get_conn() as conn:
        return conn.execute("SELECT id, doctor_id, name, created_at FROM doctors ORDER BY created_at DESC").fetchall()


def delete_doctor(doc_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM doctors WHERE id = ?", (doc_id,))
        conn.commit()


def verify_doctor(doctor_id: str, doctor_pw: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM doctors WHERE doctor_id = ? AND doctor_pw = ?", (doctor_id, doctor_pw)).fetchone()
        return bool(row)


def add_hospital(hospital_id: str, hospital_pw: str, name: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO hospitals(hospital_id, hospital_pw, name) VALUES(?,?,?)",
            (hospital_id, hospital_pw, name)
        )
        conn.commit()
        return cur.lastrowid


def list_hospitals():
    with get_conn() as conn:
        return conn.execute("SELECT id, hospital_id, name, created_at FROM hospitals ORDER BY created_at DESC").fetchall()


def delete_hospital(hosp_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM hospitals WHERE id = ?", (hosp_id,))
        conn.commit()


def verify_hospital(hospital_id: str, hospital_pw: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM hospitals WHERE hospital_id = ? AND hospital_pw = ?", (hospital_id, hospital_pw)).fetchone()
        return bool(row)


def update_patient(patient_id: int, data: dict) -> None:
    keys = [
        'photo','name','age','gender','contact','address','chief_complaint','pain_level','pain_description',
        'additional_symptoms','medical_history','emergency_name','emergency_relation','emergency_gender',
        'emergency_contact','emergency_address','heart_rate','spo2','body_temp_f','env_temp_f','humidity_percent','weight_kg'
    ]
    set_parts = []
    values = []
    for k in keys:
        if k in data:
            set_parts.append(f"{k} = ?")
            values.append(data[k])
    if not set_parts:
        return
    values.append(patient_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE patients SET {', '.join(set_parts)} WHERE id = ?", tuple(values))
        conn.commit()


def delete_patient(patient_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()


# Patient Profile Management Functions

def update_patient_profile(profile_id: int, data: dict) -> None:
    """Update patient profile with new data"""
    keys = [
        'name', 'dob', 'age', 'gender', 'contact', 'address',
        'emergency_name', 'emergency_relation', 'emergency_contact', 'emergency_address',
        'medical_history', 'allergies', 'medications', 'prescriptions',
        'test_results', 'diagnoses', 'treatment_records', 'photo', 'notes',
        'username', 'patient_id_number'
    ]
    set_parts = []
    values = []
    for k in keys:
        if k in data:
            set_parts.append(f"{k} = ?")
            values.append(data[k])
    if not set_parts:
        return
    values.append(profile_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE patient_profiles SET {', '.join(set_parts)} WHERE id = ?", tuple(values))
        conn.commit()


def create_patient_profile(data: dict) -> int:
    """Create a new patient profile"""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO patient_profiles (
                name, dob, age, gender, contact, address,
                emergency_name, emergency_relation, emergency_contact, emergency_address,
                medical_history, allergies, medications, prescriptions,
                test_results, diagnoses, treatment_records, photo, notes,
                username, patient_id_number
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data.get('name'), data.get('dob'), data.get('age'), data.get('gender'),
                data.get('contact'), data.get('address'), data.get('emergency_name'),
                data.get('emergency_relation'), data.get('emergency_contact'), data.get('emergency_address'),
                data.get('medical_history'), data.get('allergies'), data.get('medications'),
                data.get('prescriptions'), data.get('test_results'), data.get('diagnoses'),
                data.get('treatment_records'), data.get('photo'), data.get('notes'),
                data.get('username'), data.get('patient_id_number')
            )
        )
        conn.commit()
        return cur.lastrowid


def get_all_patient_profiles(search: Optional[str] = None) -> Iterable[sqlite3.Row]:
    """Get all patient profiles with optional search"""
    with get_conn() as conn:
        if search:
            like = f"%{search}%"
            cur = conn.execute(
                """
                SELECT pp.*, 
                       COUNT(DISTINCT p.id) + COUNT(DISTINCT sp.id) as visit_count,
                       MAX(COALESCE(p.created_at, sp.archived_at)) as last_visit
                FROM patient_profiles pp
                LEFT JOIN patients p ON pp.id = p.profile_id
                LEFT JOIN stored_patients sp ON pp.id = sp.profile_id
                WHERE pp.name LIKE ? OR pp.contact LIKE ? OR pp.id LIKE ?
                GROUP BY pp.id
                ORDER BY pp.created_at DESC
                """,
                (like, like, like),
            )
        else:
            cur = conn.execute(
                """
                SELECT pp.*, 
                       COUNT(DISTINCT p.id) + COUNT(DISTINCT sp.id) as visit_count,
                       MAX(COALESCE(p.created_at, sp.archived_at)) as last_visit
                FROM patient_profiles pp
                LEFT JOIN patients p ON pp.id = p.profile_id
                LEFT JOIN stored_patients sp ON pp.id = sp.profile_id
                GROUP BY pp.id
                ORDER BY pp.created_at DESC
                """
            )
        return cur.fetchall()


def verify_patient_login(username: str, patient_id_number: str) -> Optional[sqlite3.Row]:
    """Verify patient login credentials"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM patient_profiles WHERE username = ? AND patient_id_number = ?", 
            (username, patient_id_number)
        ).fetchone()
        return row


# QR Code Generation Functions

def generate_qr_code_data(patient_id: int, name: str, age: Optional[int] = None, gender: Optional[str] = None) -> str:
    """Generate QR code data string for patient"""
    qr_data = {
        "patient_id": patient_id,
        "name": name,
        "age": age,
        "gender": gender,
        "type": "patient_id"
    }
    return json.dumps(qr_data)


def generate_qr_code_image(qr_data: str) -> str:
    """Generate QR code image and return as base64 string"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64 string
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return img_str


def generate_patient_qr_code(patient_id: int) -> str:
    """Generate QR code for a patient profile"""
    profile = get_profile(patient_id)
    if not profile:
        raise ValueError(f"Patient profile with ID {patient_id} not found")
    
    qr_data = generate_qr_code_data(
        patient_id=patient_id,
        name=profile['name'] if profile['name'] else '',
        age=profile['age'] if profile['age'] else None,
        gender=profile['gender'] if profile['gender'] else None
    )
    
    return generate_qr_code_image(qr_data)


def parse_qr_code_data(qr_data: str) -> dict:
    """Parse QR code data and return patient information"""
    try:
        data = json.loads(qr_data)
        if data.get('type') != 'patient_id':
            raise ValueError("Invalid QR code type")
        return data
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(f"Invalid QR code data: {e}")


def verify_patient_qr_code(qr_data: str) -> Optional[dict]:
    """Verify QR code data and return patient profile if valid"""
    try:
        parsed_data = parse_qr_code_data(qr_data)
        patient_id = parsed_data.get('patient_id')
        
        if not patient_id:
            return None
            
        profile = get_profile(int(patient_id))
        if not profile:
            return None
            
        return {
            'profile': profile,
            'qr_data': parsed_data
        }
    except (ValueError, TypeError):
        return None

