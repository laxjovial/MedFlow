import sqlite3
from pathlib import Path


class PatientDatabase:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent / "medflow.db"

        self.db_path = str(db_path)
        self._create_table()
        self._seed_if_empty()

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    age TEXT,
                    bp TEXT,
                    hr TEXT,
                    history TEXT,
                    diag TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _seed_if_empty(self):
        if self.count_patients() > 0:
            return

        initial_patients = [
            (
                "Patient 001",
                "John Doe",
                "32",
                "120/80 mmHg",
                "72 bpm",
                "No major surgeries. Penicillin allergy.",
                "Mild Concussion / Rest prescribed.",
            ),
            (
                "Patient 002",
                "Alice Smith",
                "45",
                "145/95 mmHg",
                "84 bpm",
                "Family history of chronic hypertension.",
                "Hypertension / Monitor BP daily.",
            ),
            (
                "Patient 003",
                "Victor K.",
                "29",
                "118/75 mmHg",
                "90 bpm",
                "Appendectomy scheduled.",
                "Acute Appendicitis / Pre-op fasting.",
            ),
        ]

        with self._connect() as conn:
            conn.executemany("""
                INSERT INTO patients
                (patient_id, name, age, bp, hr, history, diag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, initial_patients)
            conn.commit()

    def count_patients(self):
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM patients").fetchone()
            return row["count"]

    def get_patient(self, patient_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM patients WHERE patient_id = ?",
                (patient_id,),
            ).fetchone()

        return dict(row) if row else None

    def search_patients(self, query=""):
        query = query.strip()

        with self._connect() as conn:
            if not query:
                rows = conn.execute("""
                    SELECT patient_id, name
                    FROM patients
                    ORDER BY CAST(SUBSTR(patient_id, 9) AS INTEGER)
                """).fetchall()
            else:
                like = f"%{query}%"
                rows = conn.execute("""
                    SELECT patient_id, name
                    FROM patients
                    WHERE patient_id LIKE ?
                       OR name LIKE ?
                    ORDER BY CAST(SUBSTR(patient_id, 9) AS INTEGER)
                """, (like, like)).fetchall()

        return [dict(row) for row in rows]

    def _next_patient_id(self):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT MAX(CAST(SUBSTR(patient_id, 9) AS INTEGER)) AS max_num
                FROM patients
                WHERE patient_id LIKE 'Patient %'
            """).fetchone()

        next_number = (row["max_num"] or 0) + 1
        return f"Patient {next_number:03d}"

    def add_patient(self, patient):
        patient_id = self._next_patient_id()

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO patients
                (patient_id, name, age, bp, hr, history, diag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                patient_id,
                patient["name"],
                patient["age"],
                patient["bp"],
                patient["hr"],
                patient["history"],
                patient["diag"],
            ))
            conn.commit()

        return patient_id

    def delete_patient(self, patient_id):
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM patients WHERE patient_id = ?",
                (patient_id,),
            )
            conn.commit()

        return cursor.rowcount > 0
