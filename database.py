from pathlib import Path
import sqlite3
from datetime import datetime
import secrets
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_FOLDER = PROJECT_ROOT / "data" / "database"
DATABASE_PATH = DATABASE_FOLDER / "recruitment.db"

def get_connection():
    DATABASE_FOLDER.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def generate_public_token():
    return secrets.token_urlsafe(8)

def generate_application_public_token():
    return secrets.token_urlsafe(12)

def generate_unique_hr_public_token(cursor):
    while True:
        token = generate_public_token()
        cursor.execute(
            "SELECT 1 FROM users WHERE public_token = ? LIMIT 1",
            (token,)
        )
        if cursor.fetchone() is None:
            return token

def generate_unique_vacancy_public_token(cursor):
    while True:
        token = generate_public_token()
        cursor.execute(
            "SELECT 1 FROM vacancies WHERE public_token = ? LIMIT 1",
            (token,)
        )
        if cursor.fetchone() is None:
            return token

def generate_unique_application_public_token(cursor):
    while True:
        token = generate_application_public_token()
        cursor.execute(
            "SELECT 1 FROM applications WHERE public_token = ? LIMIT 1",
            (token,)
        )
        if cursor.fetchone() is None:
            return token

def initialize_database():
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'hr',
                public_token TEXT UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_token TEXT UNIQUE,
                job_title TEXT NOT NULL,
                department TEXT,
                employment_type TEXT,
                location TEXT,
                work_mode TEXT,
                experience TEXT,
                salary TEXT,
                description TEXT NOT NULL,
                responsibilities TEXT,
                requirements TEXT,
                required_skills TEXT,
                opening_date TEXT,
                closing_date TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                published_at TEXT,
                jd_processing_status TEXT NOT NULL DEFAULT 'pending',
                jd_structured_data TEXT,
                jd_processing_error TEXT,
                jd_processed_at TEXT,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_token TEXT UNIQUE NOT NULL,
                vacancy_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                resume_path TEXT,
                resume_status TEXT DEFAULT 'Pending',
                pipeline_status TEXT DEFAULT 'pending',
                pipeline_error TEXT,
                structured_cv TEXT,
                structured_at TEXT,
                match_score REAL,
                skills_score REAL,
                experience_score REAL,
                education_score REAL,
                grade TEXT,
                eligibility TEXT,
                rank INTEGER,
                interview_score REAL,
                application_status TEXT DEFAULT 'Submitted',
                applied_at TEXT NOT NULL,
                FOREIGN KEY (vacancy_id) REFERENCES vacancies(id),
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                total_questions INTEGER DEFAULT 5,
                completed_questions INTEGER DEFAULT 0,
                overall_score REAL,
                status TEXT DEFAULT 'Not Started',
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interview_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                question_number INTEGER,
                question TEXT,
                category TEXT,
                answer TEXT,
                score REAL,
                quality TEXT,
                FOREIGN KEY (interview_id) REFERENCES interviews(id) ON DELETE CASCADE
            )
        """)

        connection.commit()
    finally:
        connection.close()

    migrate_vacancy_columns()
    migrate_hr_public_tokens()
    migrate_application_columns()
    migrate_interview_chatbot_columns()
    migrate_selection_email_tables()
    migrate_password_reset_table()

# ============================================================
# SELECTION EMAIL (template + send log)
# ============================================================

def migrate_selection_email_tables():
    """Additive only: creates two new tables, touches no existing data."""
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                hr_id INTEGER PRIMARY KEY,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (hr_id) REFERENCES users(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS selection_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                sent_by INTEGER,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (application_id)
                    REFERENCES applications(id) ON DELETE CASCADE,
                FOREIGN KEY (sent_by) REFERENCES users(id)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_selection_emails_application
            ON selection_emails(application_id, status)
        """)

        connection.commit()
    finally:
        connection.close()


def get_email_template(hr_id):
    """Return the HR's saved template row, or None if they never saved one."""
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT subject, body FROM email_templates WHERE hr_id = ? LIMIT 1",
            (hr_id,)
        ).fetchone()
    finally:
        connection.close()


def save_email_template(hr_id, subject, body):
    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO email_templates (hr_id, subject, body, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(hr_id) DO UPDATE SET
                subject = excluded.subject,
                body = excluded.body,
                updated_at = excluded.updated_at
        """, (
            hr_id,
            subject,
            body,
            datetime.now().isoformat(timespec="seconds")
        ))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_last_selection_email_sent(application_id):
    """Time of the most recent SUCCESSFUL send for this application, or None."""
    connection = get_connection()
    try:
        row = connection.execute("""
            SELECT sent_at FROM selection_emails
            WHERE application_id = ? AND status = 'sent'
            ORDER BY id DESC
            LIMIT 1
        """, (application_id,)).fetchone()
        return row["sent_at"] if row else None
    finally:
        connection.close()


def log_selection_email(
    application_id,
    sent_by,
    recipient,
    subject,
    body,
    status,
    error=None
):
    """Record a send attempt ('sent' or 'failed'). Returns the timestamp."""
    sent_at = datetime.now().isoformat(timespec="seconds")
    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO selection_emails (
                application_id, sent_by, recipient, subject, body,
                status, error, sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            application_id,
            sent_by,
            recipient,
            subject,
            body,
            status,
            error,
            sent_at
        ))
        connection.commit()
        return sent_at
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_vacancy_columns():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA table_info(vacancies)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        new_columns = {
            "jd_processing_status": "TEXT NOT NULL DEFAULT 'pending'",
            "jd_structured_data": "TEXT",
            "jd_processing_error": "TEXT",
            "jd_processed_at": "TEXT",
            "public_token": "TEXT",
            "created_by": "INTEGER"
        }

        for column_name, column_definition in new_columns.items():
            if column_name not in existing_columns:
                cursor.execute(
                    f"ALTER TABLE vacancies ADD COLUMN {column_name} {column_definition}"
                )
                print("[DB] Added vacancies column:", column_name)

        connection.commit()

        cursor.execute("""
            SELECT id FROM vacancies
            WHERE public_token IS NULL OR TRIM(public_token) = ''
        """)
        rows = cursor.fetchall()

        for row in rows:
            token = generate_unique_vacancy_public_token(cursor)
            cursor.execute(
                "UPDATE vacancies SET public_token = ? WHERE id = ?",
                (token, row["id"])
            )

        connection.commit()

        if rows:
            print("[DB] Generated public vacancy tokens:", len(rows))

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_vacancies_public_token
            ON vacancies(public_token)
        """)
        connection.commit()
    finally:
        connection.close()

def migrate_hr_public_tokens():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA table_info(users)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "public_token" not in existing_columns:
            cursor.execute("ALTER TABLE users ADD COLUMN public_token TEXT")
            print("[DB] Added users.public_token")

        connection.commit()

        cursor.execute("""
            SELECT id FROM users
            WHERE LOWER(role) = 'hr'
            AND (public_token IS NULL OR TRIM(public_token) = '')
        """)
        rows = cursor.fetchall()

        for row in rows:
            token = generate_unique_hr_public_token(cursor)
            cursor.execute(
                "UPDATE users SET public_token = ? WHERE id = ?",
                (token, row["id"])
            )

        connection.commit()

        if rows:
            print("[DB] Generated HR public tokens:", len(rows))

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_users_public_token
            ON users(public_token)
        """)
        connection.commit()
    finally:
        connection.close()

def migrate_application_columns():
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                created_at TEXT NOT NULL
            )
        """)
        connection.commit()

        cursor.execute("PRAGMA table_info(applications)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        new_columns = {
            "public_token": "TEXT",
            "application_status": "TEXT DEFAULT 'Submitted'",
            "applied_at": "TEXT",
            "pipeline_status": "TEXT DEFAULT 'pending'",
            "pipeline_error": "TEXT",
            "structured_cv": "TEXT",
            "structured_at": "TEXT",
            "skills_score": "REAL",
            "experience_score": "REAL",
            "education_score": "REAL",
            "grade": "TEXT",
            "eligibility": "TEXT",
            "rank": "INTEGER"
        }

        for column_name, column_definition in new_columns.items():
            if column_name not in existing_columns:
                cursor.execute(
                    f"ALTER TABLE applications ADD COLUMN {column_name} {column_definition}"
                )
                print("[DB] Added applications column:", column_name)

        if "applied_at" not in existing_columns:
            now = datetime.now().isoformat(timespec="seconds")
            cursor.execute(
                "UPDATE applications SET applied_at = ? WHERE applied_at IS NULL",
                (now,)
            )

        connection.commit()

        cursor.execute("""
            SELECT id FROM applications
            WHERE public_token IS NULL OR TRIM(public_token) = ''
        """)
        rows = cursor.fetchall()

        for row in rows:
            token = generate_unique_application_public_token(cursor)
            cursor.execute(
                "UPDATE applications SET public_token = ? WHERE id = ?",
                (token, row["id"])
            )

        connection.commit()

        if rows:
            print("[DB] Generated application tokens:", len(rows))

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_applications_public_token
            ON applications(public_token)
        """)
        connection.commit()
    finally:
        connection.close()

# ============================================================
# INTERVIEW CHATBOT MIGRATION
# ============================================================

def migrate_interview_chatbot_columns():
    """Add chatbot fields safely to the existing database."""
    conn = get_connection()

    try:
        def ensure_column(table, column, definition):
            existing = {
                row["name"]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }

            if column not in existing:
                conn.execute(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN {column} {definition}"
                )

        # Application matching results
        ensure_column("applications", "cv_match_score", "REAL")
        ensure_column("applications", "match_explanation", "TEXT")
        ensure_column(
            "applications",
            "matching_status",
            "TEXT DEFAULT 'pending'"
        )
        ensure_column("applications", "match_result_json", "TEXT")

        # Persistent interview state
        ensure_column("interviews", "session_json", "TEXT")
        ensure_column("interviews", "education_assessment_json", "TEXT")
        ensure_column("interviews", "candidate_reported_yoe", "REAL")
        ensure_column("interviews", "experience_answer", "TEXT")

        # Stable question IDs
        ensure_column("interview_answers", "question_id", "TEXT")

        # HR interview settings per vacancy
        conn.execute("""
          CREATE TABLE IF NOT EXISTS vacancy_interview_settings (
    vacancy_id INTEGER PRIMARY KEY,
    questions_json TEXT NOT NULL DEFAULT '[]',
    updated_by INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vacancy_id)
                    REFERENCES vacancies(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (updated_by)
                    REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_interviews_application_id
            ON interviews(application_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_interview_answers_interview_id
            ON interview_answers(interview_id)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_interview_answers_question
            ON interview_answers(interview_id, question_id)
        """)

        conn.commit()

    finally:
        conn.close()

# ============================================================
# PASSWORD RESET (one active reset per user)
# ============================================================

def migrate_password_reset_table():
    """Additive only: creates one new table, touches no existing data."""
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                user_id INTEGER PRIMARY KEY,
                code_hash TEXT,
                code_expires_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                token_hash TEXT,
                token_expires_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        connection.commit()
    finally:
        connection.close()


def save_password_reset_code(user_id, code_hash, code_expires_at):
    """Start (or restart) a reset: new code, attempts back to 0, old token voided."""
    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO password_resets (
                user_id, code_hash, code_expires_at,
                attempts, token_hash, token_expires_at, created_at
            )
            VALUES (?, ?, ?, 0, NULL, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                code_hash = excluded.code_hash,
                code_expires_at = excluded.code_expires_at,
                attempts = 0,
                token_hash = NULL,
                token_expires_at = NULL,
                created_at = excluded.created_at
        """, (
            user_id,
            code_hash,
            code_expires_at,
            datetime.now().isoformat(timespec="seconds")
        ))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_password_reset(user_id):
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT * FROM password_resets WHERE user_id = ? LIMIT 1",
            (user_id,)
        ).fetchone()
    finally:
        connection.close()


def increment_password_reset_attempts(user_id):
    """Count one code attempt and return the new total (None if no reset)."""
    connection = get_connection()
    try:
        connection.execute(
            "UPDATE password_resets SET attempts = attempts + 1 WHERE user_id = ?",
            (user_id,)
        )
        connection.commit()
        row = connection.execute(
            "SELECT attempts FROM password_resets WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["attempts"] if row else None
    finally:
        connection.close()


def save_password_reset_token(user_id, token_hash, token_expires_at):
    """
    Swap a verified code for a one-time reset token. The code is erased, so it
    can never be used twice. Returns False if the code was already used.
    """
    connection = get_connection()
    try:
        cursor = connection.execute("""
            UPDATE password_resets
            SET token_hash = ?, token_expires_at = ?, code_hash = NULL
            WHERE user_id = ? AND code_hash IS NOT NULL
        """, (token_hash, token_expires_at, user_id))
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def delete_password_reset(user_id):
    connection = get_connection()
    try:
        connection.execute(
            "DELETE FROM password_resets WHERE user_id = ?",
            (user_id,)
        )
        connection.commit()
    finally:
        connection.close()


def update_user_password(user_id, password_hash):
    connection = get_connection()
    try:
        cursor = connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_user_by_email(email):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE LOWER(email) = ? LIMIT 1",
            (email.strip().lower(),)
        )
        return cursor.fetchone()
    finally:
        connection.close()

def get_user_by_id(user_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE id = ? LIMIT 1",
            (user_id,)
        )
        return cursor.fetchone()
    finally:
        connection.close()

def create_user(name, email, password_hash, role="hr"):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        public_token = None

        if str(role).strip().lower() == "hr":
            public_token = generate_unique_hr_public_token(cursor)

        cursor.execute("""
            INSERT INTO users (
                name, email, password_hash, role,
                public_token, is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
        """, (
            name.strip(),
            email.strip().lower(),
            password_hash,
            role,
            public_token
        ))

        connection.commit()
        return cursor.lastrowid
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def get_hr_by_public_token(public_token):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT * FROM users
            WHERE public_token = ?
            AND LOWER(role) = 'hr'
            AND is_active = 1
            LIMIT 1
        """, (public_token,))
        return cursor.fetchone()
    finally:
        connection.close()

def get_hr_public_url(public_token):
    return f"/jobs/{public_token}"

def normalize_status(status):
    value = str(status or "").strip().lower()
    mapping = {
        "active": "published",
        "published": "published",
        "publish": "published",
        "draft": "draft",
        "processing": "processing",
        "closed": "closed"
    }
    return mapping.get(value, "draft")

def create_vacancy(
    job_title,
    job_description,
    location=None,
    salary=None,
    employment_type=None,
    work_mode=None,
    opening_date=None,
    application_end_date=None,
    status="draft",
    created_by=None,
    department=None,
    experience=None,
    responsibilities=None,
    requirements=None,
    required_skills=None
):
    normalized_status = normalize_status(status)
    connection = get_connection()

    try:
        cursor = connection.cursor()
        public_token = generate_unique_vacancy_public_token(cursor)
        created_at = datetime.now().isoformat(timespec="seconds")
        published_at = created_at if normalized_status == "published" else None

        cursor.execute("""
            INSERT INTO vacancies (
                public_token, job_title, department,
                employment_type, location, work_mode,
                experience, salary, description,
                responsibilities, requirements,
                required_skills, opening_date,
                closing_date, status, created_at,
                published_at, jd_processing_status,
                jd_structured_data, jd_processing_error,
                jd_processed_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            public_token, job_title.strip(), department,
            employment_type, location, work_mode,
            experience, salary, job_description.strip(),
            responsibilities, requirements, required_skills,
            opening_date, application_end_date,
            normalized_status, created_at, published_at,
            "pending", None, None, None, created_by
        ))

        vacancy_id = cursor.lastrowid
        connection.commit()
        return vacancy_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def get_all_vacancies():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT v.*,
                (SELECT COUNT(*) FROM applications a
                 WHERE a.vacancy_id = v.id) AS applicant_count
            FROM vacancies v
            ORDER BY v.created_at DESC, v.id DESC
        """)
        return cursor.fetchall()
    finally:
        connection.close()

def get_vacancies_by_hr(hr_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT v.*,
                (SELECT COUNT(*) FROM applications a
                 WHERE a.vacancy_id = v.id) AS applicant_count
            FROM vacancies v
            WHERE v.created_by = ?
            ORDER BY v.created_at DESC, v.id DESC
        """, (hr_id,))
        return cursor.fetchall()
    finally:
        connection.close()

def get_public_vacancies_by_hr(hr_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT * FROM vacancies
            WHERE created_by = ?
            AND LOWER(status) = 'published'
            ORDER BY published_at DESC, created_at DESC, id DESC
        """, (hr_id,))
        return cursor.fetchall()
    finally:
        connection.close()

def get_vacancy_by_id(vacancy_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT v.*,
                (SELECT COUNT(*) FROM applications a
                 WHERE a.vacancy_id = v.id) AS applicant_count
            FROM vacancies v
            WHERE v.id = ?
            LIMIT 1
        """, (vacancy_id,))
        return cursor.fetchone()
    finally:
        connection.close()

def get_public_vacancy_by_token(public_token):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT v.*,
                (SELECT COUNT(*) FROM applications a
                 WHERE a.vacancy_id = v.id) AS applicant_count
            FROM vacancies v
            WHERE v.public_token = ?
            AND LOWER(v.status) = 'published'
            LIMIT 1
        """, (public_token,))
        return cursor.fetchone()
    finally:
        connection.close()

def get_public_vacancy_url(public_token):
    return f"/careers/{public_token}"

def get_application_count(vacancy_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM applications WHERE vacancy_id = ?",
            (vacancy_id,)
        )
        return cursor.fetchone()[0]
    finally:
        connection.close()

def get_candidate_by_email(email):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT * FROM candidates
            WHERE LOWER(TRIM(email)) = LOWER(TRIM(?))
            LIMIT 1
        """, (email,))
        return cursor.fetchone()
    finally:
        connection.close()

def create_candidate(full_name, email, phone):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        now = datetime.now().isoformat(timespec="seconds")

        cursor.execute("""
            INSERT INTO candidates (
                full_name, email, phone, created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            full_name.strip(),
            email.strip().lower(),
            phone.strip() if phone else None,
            now
        ))

        candidate_id = cursor.lastrowid
        connection.commit()
        return candidate_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def create_application(vacancy_id, candidate_id, resume_path):
    connection = get_connection()
    try:
        cursor = connection.cursor()

        existing = cursor.execute("""
            SELECT * FROM applications
            WHERE vacancy_id = ? AND candidate_id = ?
            LIMIT 1
        """, (vacancy_id, candidate_id)).fetchone()

        if existing:
            return {
                "application_id": existing["id"],
                "public_token": existing["public_token"],
                "existing": True
            }

        public_token = generate_unique_application_public_token(cursor)
        applied_at = datetime.now().isoformat(timespec="seconds")

        cursor.execute("""
            INSERT INTO applications (
                public_token, vacancy_id, candidate_id,
                resume_path, resume_status,
                pipeline_status, application_status, applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            public_token,
            vacancy_id,
            candidate_id,
            resume_path,
            "Processing",
            "processing",
            "Submitted",
            applied_at
        ))

        application_id = cursor.lastrowid
        connection.commit()

        return {
            "application_id": application_id,
            "public_token": public_token,
            "existing": False
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def get_application_by_public_token(public_token):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT a.*, c.full_name, c.email, c.phone,
                   v.job_title,
                   v.public_token AS vacancy_public_token
            FROM applications a
            JOIN candidates c ON c.id = a.candidate_id
            JOIN vacancies v ON v.id = a.vacancy_id
            WHERE a.public_token = ?
            LIMIT 1
        """, (public_token,))
        return cursor.fetchone()
    finally:
        connection.close()

def get_application_by_id(application_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM applications WHERE id = ? LIMIT 1",
            (application_id,)
        )
        return cursor.fetchone()
    finally:
        connection.close()

def get_applications_for_vacancy(vacancy_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT
                a.id AS application_id,
                a.public_token AS application_token,
                c.full_name,
                c.email,
                c.phone,
                a.resume_path,
                a.resume_status,
                a.pipeline_status,
                a.pipeline_error,
                a.structured_at,
                a.match_score,
                a.skills_score,
                a.experience_score,
                a.education_score,
                a.grade,
                a.eligibility,
                a.rank,
                a.interview_score,
                a.application_status,
                a.applied_at
            FROM applications a
            JOIN candidates c ON c.id = a.candidate_id
            WHERE a.vacancy_id = ?
            ORDER BY
                CASE WHEN a.rank IS NULL THEN 1 ELSE 0 END,
                a.rank ASC,
                a.applied_at DESC
        """, (vacancy_id,))
        return cursor.fetchall()
    finally:
        connection.close()

def update_application_resume_status(application_id, resume_status):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE applications SET resume_status = ? WHERE id = ?",
            (resume_status, application_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_application_pipeline(
    application_id,
    pipeline_status,
    pipeline_error=None
):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE applications
            SET pipeline_status = ?, pipeline_error = ?
            WHERE id = ?
        """, (
            pipeline_status,
            pipeline_error,
            application_id
        ))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def save_structured_cv(application_id, structured_cv):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        structured_json = json.dumps(
            structured_cv,
            ensure_ascii=False
        )
        processed_at = datetime.now().isoformat(timespec="seconds")

        cursor.execute("""
            UPDATE applications
            SET structured_cv = ?, structured_at = ?
            WHERE id = ?
        """, (
            structured_json,
            processed_at,
            application_id
        ))

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_application_match_score(application_id, match_score):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE applications SET match_score = ? WHERE id = ?",
            (match_score, application_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def save_application_matching_result(
    application_id,
    match_score,
    skills_score=None,
    experience_score=None,
    education_score=None,
    grade=None,
    eligibility=None,
    rank=None
):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE applications
            SET
                match_score = ?,
                skills_score = ?,
                experience_score = ?,
                education_score = ?,
                grade = ?,
                eligibility = ?,
                rank = ?
            WHERE id = ?
        """, (
            match_score,
            skills_score,
            experience_score,
            education_score,
            grade,
            eligibility,
            rank,
            application_id
        ))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_application_interview_score(
    application_id,
    interview_score
):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE applications SET interview_score = ? WHERE id = ?",
            (interview_score, application_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_application_status(application_id, status):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE applications SET application_status = ? WHERE id = ?",
            (status, application_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def create_interview(application_id, total_questions=5):
    connection = get_connection()
    try:
        cursor = connection.cursor()

        existing = cursor.execute("""
            SELECT * FROM interviews
            WHERE application_id = ?
            LIMIT 1
        """, (application_id,)).fetchone()

        if existing:
            return existing["id"]

        started_at = datetime.now().isoformat(timespec="seconds")

        cursor.execute("""
            INSERT INTO interviews (
                application_id, total_questions,
                completed_questions, status, started_at
            )
            VALUES (?, ?, 0, ?, ?)
        """, (
            application_id,
            total_questions,
            "In Progress",
            started_at
        ))

        interview_id = cursor.lastrowid
        connection.commit()
        return interview_id
    finally:
        connection.close()

def get_interview_by_application(application_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM interviews WHERE application_id = ? LIMIT 1",
            (application_id,)
        )
        return cursor.fetchone()
    finally:
        connection.close()

def get_interview_by_id(interview_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM interviews WHERE id = ? LIMIT 1",
            (interview_id,)
        )
        return cursor.fetchone()
    finally:
        connection.close()

def save_interview_answer(
    interview_id,
    question_number,
    question,
    category,
    answer,
    score=None,
    quality=None
):
    connection = get_connection()
    try:
        cursor = connection.cursor()

        existing = cursor.execute("""
            SELECT id FROM interview_answers
            WHERE interview_id = ? AND question_number = ?
            LIMIT 1
        """, (
            interview_id,
            question_number
        )).fetchone()

        if existing:
            cursor.execute("""
                UPDATE interview_answers
                SET question = ?, category = ?, answer = ?,
                    score = ?, quality = ?
                WHERE id = ?
            """, (
                question,
                category,
                answer,
                score,
                quality,
                existing["id"]
            ))
            answer_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO interview_answers (
                    interview_id, question_number,
                    question, category, answer,
                    score, quality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                interview_id,
                question_number,
                question,
                category,
                answer,
                score,
                quality
            ))
            answer_id = cursor.lastrowid

        connection.commit()
        return answer_id
    finally:
        connection.close()

def get_interview_answers(interview_id):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT * FROM interview_answers
            WHERE interview_id = ?
            ORDER BY question_number ASC
        """, (interview_id,))
        return cursor.fetchall()
    finally:
        connection.close()

def update_interview_progress(
    interview_id,
    completed_questions,
    status=None,
    overall_score=None,
    completed_at=None
):
    connection = get_connection()
    try:
        cursor = connection.cursor()

        if status is None:
            cursor.execute("""
                UPDATE interviews
                SET completed_questions = ?
                WHERE id = ?
            """, (
                completed_questions,
                interview_id
            ))
        else:
            cursor.execute("""
                UPDATE interviews
                SET completed_questions = ?,
                    status = ?,
                    overall_score = ?,
                    completed_at = ?
                WHERE id = ?
            """, (
                completed_questions,
                status,
                overall_score,
                completed_at,
                interview_id
            ))

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_vacancy_status(vacancy_id, status):
    normalized_status = normalize_status(status)
    connection = get_connection()

    try:
        cursor = connection.cursor()

        if normalized_status == "published":
            cursor.execute("""
                UPDATE vacancies
                SET status = 'published',
                    published_at = COALESCE(published_at, ?)
                WHERE id = ?
            """, (
                datetime.now().isoformat(timespec="seconds"),
                vacancy_id
            ))
        else:
            cursor.execute("""
                UPDATE vacancies
                SET status = ?
                WHERE id = ?
            """, (
                normalized_status,
                vacancy_id
            ))

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_vacancy(
    vacancy_id,
    job_title,
    job_description,
    location=None,
    salary=None,
    employment_type=None,
    work_mode=None,
    opening_date=None,
    application_end_date=None,
    department=None,
    experience=None,
    responsibilities=None,
    requirements=None,
    required_skills=None
):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE vacancies
            SET
                job_title = ?,
                department = ?,
                employment_type = ?,
                location = ?,
                work_mode = ?,
                experience = ?,
                salary = ?,
                description = ?,
                responsibilities = ?,
                requirements = ?,
                required_skills = ?,
                opening_date = ?,
                closing_date = ?
            WHERE id = ?
        """, (
            job_title.strip(),
            department,
            employment_type,
            location,
            work_mode,
            experience,
            salary,
            job_description.strip(),
            responsibilities,
            requirements,
            required_skills,
            opening_date,
            application_end_date,
            vacancy_id
        ))

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def update_jd_processing(
    vacancy_id,
    processing_status,
    structured_data=None,
    processing_error=None,
    processed_at=None
):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE vacancies
            SET
                jd_processing_status = ?,
                jd_structured_data = ?,
                jd_processing_error = ?,
                jd_processed_at = ?
            WHERE id = ?
        """, (
            processing_status,
            structured_data,
            processing_error,
            processed_at,
            vacancy_id
        ))

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

def get_dashboard_stats():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM vacancies
            WHERE LOWER(status) = 'published'
        """)
        active_jobs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vacancies")
        total_jobs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM applications")
        applications = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM interviews
            WHERE status = 'Completed'
        """)
        interviews = cursor.fetchone()[0]

        return {
            "active_jobs": active_jobs,
            "total_jobs": total_jobs,
            "applications": applications,
            "completed_interviews": interviews
        }
    finally:
        connection.close()

def delete_vacancy(vacancy_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM interview_answers
            WHERE interview_id IN (
                SELECT id FROM interviews
                WHERE application_id IN (
                    SELECT id FROM applications
                    WHERE vacancy_id = ?
                )
            )
        """, (vacancy_id,))

        cursor.execute("""
            DELETE FROM interviews
            WHERE application_id IN (
                SELECT id FROM applications
                WHERE vacancy_id = ?
            )
        """, (vacancy_id,))

        cursor.execute(
            "DELETE FROM applications WHERE vacancy_id = ?",
            (vacancy_id,)
        )

        cursor.execute(
            "DELETE FROM vacancies WHERE id = ?",
            (vacancy_id,)
        )

        deleted = cursor.rowcount > 0
        connection.commit()
        return deleted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def update_expired_vacancies():
    today = datetime.now().date().isoformat()
    connection = get_connection()

    try:
        connection.execute("""
            UPDATE vacancies
            SET status = 'closed'
            WHERE LOWER(status) = 'published'
            AND closing_date IS NOT NULL
            AND closing_date < ?
        """, (today,))
        connection.commit()
    finally:
        connection.close()

initialize_database()