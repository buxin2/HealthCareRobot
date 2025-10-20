import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), '..', 'app.db')
DB = os.path.abspath(DB)
print('Using DB:', DB)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

username = 'buxin'
password = '7741187'

profile = {
    'name': 'buxin jabbi',
    'dob': None,
    'age': 23,
    'gender': 'Male',
    'contact': '09319038312',
    'address': 'ASERRWH',
    'emergency_name': 'SAaAAC',
    'emergency_relation': 'Parent',
    'emergency_contact': '09319038312',
    'emergency_address': 'ASERRWH',
    'medical_history': None,
    'allergies': None,
    'medications': None,
    'prescriptions': None,
    'test_results': None,
    'diagnoses': None,
    'treatment_records': None,
    'photo': None,
    'notes': 'wERAS',
    'username': username,
    'patient_id_number': password,
}

row = cur.execute('SELECT id FROM patient_profiles WHERE username=?', (username,)).fetchone()
if row:
    pid = int(row['id'])
    sets = ', '.join([f"{k}=?" for k in profile.keys()])
    cur.execute(f'UPDATE patient_profiles SET {sets} WHERE id=?', (*profile.values(), pid))
else:
    cols = ', '.join(profile.keys())
    qs = ', '.join(['?'] * len(profile))
    cur.execute(f'INSERT INTO patient_profiles({cols}) VALUES({qs})', tuple(profile.values()))
    pid = int(cur.lastrowid)

conn.commit()
print('Profile ID:', pid)

visit = {
    'profile_id': pid,
    'photo': None,
    'name': profile['name'],
    'age': profile['age'],
    'gender': profile['gender'],
    'contact': profile['contact'],
    'address': profile['address'],
    'chief_complaint': 'my head is paining in birthday',
    'pain_level': None,
    'pain_description': 'the head is born in actually',
    'additional_symptoms': 'I am ok',
    'medical_history': profile['medical_history'],
    'emergency_name': profile['emergency_name'],
    'emergency_relation': profile['emergency_relation'],
    'emergency_gender': None,
    'emergency_contact': profile['emergency_contact'],
    'emergency_address': profile['emergency_address'],
    'heart_rate': 107.0,
    'spo2': 100.0,
    'body_temp_f': 91.94,
    'env_temp_f': 87.44,
    'humidity_percent': 59.5,
    'weight_kg': 4.483,
}

cols = ', '.join(visit.keys())
qs = ', '.join(['?'] * len(visit))
cur.execute(f'INSERT INTO patients({cols}) VALUES({qs})', tuple(visit.values()))

# Set created_at to the requested timestamp
cur.execute(
    'UPDATE patients SET created_at=? WHERE id=(SELECT MAX(id) FROM patients WHERE profile_id=?)',
    ('2025-10-20 00:35:52', pid)
)

conn.commit()
print('Seeded visit for profile:', pid)
