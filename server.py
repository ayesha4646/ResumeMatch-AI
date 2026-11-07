from pathlib import Path
import sys
from datetime import datetime, timedelta
import os
import sqlite3
import webbrowser
import json
import secrets
from threading import Timer, Thread, Lock
from flask import url_for
from flask import Flask, request, jsonify, session, send_from_directory, redirect, render_template
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename
import re 
import time
import hashlib
import hmac
import math


from flask import Flask, request, jsonify, session, send_from_directory, redirect, render_template, send_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.database import (
    initialize_database,
    get_connection,
    get_user_by_email,
    get_user_by_id,
    create_user,
    create_vacancy,
    get_all_vacancies,
    get_vacancy_by_id,
    get_vacancies_by_hr,
    update_vacancy,
    update_vacancy_status,
    delete_vacancy,
    get_application_count,
    update_jd_processing,
    update_application_pipeline,
    save_structured_cv,
    get_public_vacancy_by_token,
    get_hr_by_public_token,
    get_hr_public_url,
    get_public_vacancies_by_hr,
    create_candidate,
    get_candidate_by_email,
    create_application,
    get_application_by_public_token,
    get_application_by_id,
    get_email_template,
    save_email_template,
    get_last_selection_email_sent,
    log_selection_email,
    save_password_reset_code,
    get_password_reset,
    increment_password_reset_attempts,
    save_password_reset_token,
    delete_password_reset,
    update_user_password,

    # Interview functions
    create_interview,
    get_interview_by_application,
    get_interview_by_id,
    save_interview_answer,
    get_interview_answers,
    update_interview_progress,
    update_application_interview_score,
)

from scripts.structure_job_descriptions_LLM import process_job_description
from src.realtime_resume_pipeline import process_uploaded_resume
from src.auth import hash_password, verify_password

from src.email_service import (
    DEFAULT_TEMPLATE_SUBJECT,
    DEFAULT_TEMPLATE_BODY,
    EmailConfigError,
    EmailSendError,
    find_unknown_placeholders,
    fill_placeholders,
    get_smtp_config,
    is_valid_email,
    send_email,
)

# Interview chatbot integration
from app.services.interview_routes import (
    interview_api,
    application_context,
    recalculate_preliminary_matching,
)

from app.services.interview_chatbot import (
    assess_education_answer,
    extract_reported_years,
    score_interview_answer,
)

app = Flask(__name__, template_folder="html")
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "resumematch-ai-development-secret-change-later"
)

APP_ROOT = Path(__file__).resolve().parent
HTML_FOLDER = APP_ROOT / "html"
CSS_FOLDER = APP_ROOT / "css"
JS_FOLDER = APP_ROOT / "js"
DB_PATH = PROJECT_ROOT / "data" / "database" / "recruitment.db"

UPLOAD_FOLDER = PROJECT_ROOT / "data" / "uploads" / "applications"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.register_blueprint(interview_api)

initialize_database()



def ensure_interview_assessment_schema():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(interview_answers)"
            ).fetchall()
        }

        if "assessment_status" not in columns:
            conn.execute("""
                ALTER TABLE interview_answers
                ADD COLUMN assessment_status TEXT DEFAULT 'pending'
            """)
        conn.execute("""
            UPDATE interview_answers
            SET assessment_status = 'complete'
            WHERE score IS NOT NULL
              AND (
                  assessment_status IS NULL
                  OR assessment_status = 'pending'           )
        """)
        conn.commit()
    finally:
        conn.close()


ensure_interview_assessment_schema()
def hr_logged_in():
    return "user_id" in session and session.get("role") == "hr"


def get_current_hr():
    user_id = session.get("user_id")
    return get_user_by_id(user_id) if user_id else None


def current_hr_owns_vacancy(vacancy):
    if not vacancy:
        return False

    current_user_id = session.get("user_id")
    created_by = vacancy["created_by"] if "created_by" in vacancy.keys() else None

    if current_user_id is None or created_by is None:
        return False

    try:
        return int(created_by) == int(current_user_id)
    except (TypeError, ValueError):
        return False


def normalize_status(status):
    value = str(status or "draft").strip().lower()

    if value in {"active", "published"}:
        return "published"

    if value in {"draft", "processing", "closed"}:
        return value

    return "draft"


def vacancy_to_dict(vacancy):
    vacancy_id = vacancy["id"]
    description = vacancy["description"] or ""
    closing_date = vacancy["closing_date"]

    try:
        applicant_count = get_application_count(vacancy_id)
    except Exception as error:
        print(f"APPLICATION COUNT ERROR for vacancy {vacancy_id}:", repr(error))
        applicant_count = 0

    structured_jd = None
    raw_structured_jd = (
        vacancy["jd_structured_data"]
        if "jd_structured_data" in vacancy.keys()
        else None
    )

    if raw_structured_jd:
        try:
            structured_jd = json.loads(raw_structured_jd)
        except Exception:
            structured_jd = None

    return {
        "id": vacancy_id,
        "job_title": vacancy["job_title"] or "",
        "job_description": description,
        "description": description,
        "location": vacancy["location"] or "",
        "salary": vacancy["salary"] or "",
        "employment_type": vacancy["employment_type"] or "",
        "work_mode": vacancy["work_mode"] or "",
        "experience": vacancy["experience"] or "",
        "department": vacancy["department"] or "",
        "responsibilities": vacancy["responsibilities"] or "",
        "requirements": vacancy["requirements"] or "",
        "required_skills": vacancy["required_skills"] or "",
        "opening_date": vacancy["opening_date"],
        "application_end_date": closing_date,
        "closing_date": closing_date,
        "status": normalize_status(vacancy["status"]),
        "created_at": vacancy["created_at"],
        "published_at": vacancy["published_at"],
        "applicant_count": applicant_count,
        "jd_processing_status": (
            vacancy["jd_processing_status"]
            if "jd_processing_status" in vacancy.keys()
            else "pending"
        ),
        "jd_structured_data": structured_jd,
        "jd_processing_error": (
            vacancy["jd_processing_error"]
            if "jd_processing_error" in vacancy.keys()
            else None
        ),
        "jd_processed_at": (
            vacancy["jd_processed_at"]
            if "jd_processed_at" in vacancy.keys()
            else None
        ),
        "created_by": (
            vacancy["created_by"]
            if "created_by" in vacancy.keys()
            else None
        ),
        "public_token": (
            vacancy["public_token"]
            if "public_token" in vacancy.keys()
            else None
        ),
    }


@app.route("/")
def home():
    return send_from_directory(HTML_FOLDER, "login.html")


@app.route("/css/<path:filename>")
def serve_css(filename):
    response = send_from_directory(CSS_FOLDER, filename)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/js/<path:filename>")
def serve_js(filename):
    response = send_from_directory(JS_FOLDER, filename)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/favicon.gif")
def favicon():
    favicon_path = PROJECT_ROOT / "app" / "favicon.gif"
    return send_from_directory(favicon_path.parent, favicon_path.name)


@app.route("/signup")
def signup_page():
    return send_from_directory(HTML_FOLDER, "signup.html")


@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({"success": False, "message": "Invalid request."}), 400

    if not data:
        return jsonify({
            "success": False,
            "message": "Please enter your email and password."
        }), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    remember = data.get("remember", False)

    if not email or not password:
        return jsonify({
            "success": False,
            "message": "Please enter your email and password."
        }), 400

    user = get_user_by_email(email)

    if user is None:
        return jsonify({
            "success": False,
            "message": "No account found with this email."
        }), 401

    if not user["is_active"]:
        return jsonify({
            "success": False,
            "message": "This account is currently inactive."
        }), 403

    if not verify_password(password, user["password_hash"]):
        return jsonify({
            "success": False,
            "message": "Incorrect password."
        }), 401

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]
    session["role"] = user["role"]
    session.permanent = bool(remember)

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "redirect": "/dashboard" if user["role"] == "hr" else "/"
    })


@app.route("/signup", methods=["POST"])
def signup():
    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({"success": False, "message": "Invalid request."}), 400

    if not data:
        return jsonify({
            "success": False,
            "message": "Please complete the form."
        }), 400

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not name:
        return jsonify({"success": False, "message": "Please enter your name."}), 400

    if not email:
        return jsonify({"success": False, "message": "Please enter your email."}), 400

    if not password:
        return jsonify({"success": False, "message": "Please enter a password."}), 400

    if len(password) < 8:
        return jsonify({
            "success": False,
            "message": "Password must be at least 8 characters."
        }), 400

    if password != confirm_password:
        return jsonify({
            "success": False,
            "message": "Passwords do not match."
        }), 400

    if get_user_by_email(email):
        return jsonify({
            "success": False,
            "message": "An account with this email already exists."
        }), 409

    try:
        user_id = create_user(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role="hr"
        )
    except Exception as error:
        print("SIGNUP DATABASE ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to create account."
        }), 500

    return jsonify({
        "success": True,
        "message": "Account created successfully.",
        "user_id": user_id
    })

# ============================================================
# PASSWORD RESET (email -> 6-digit code -> new password)
# ============================================================

_RESET_CODE_MINUTES = 10
_RESET_TOKEN_MINUTES = 10
_RESET_MAX_ATTEMPTS = 5
_RESET_COOLDOWN_SECONDS = 60
_RESET_MAX_PER_EMAIL_PER_HOUR = 5
_RESET_MAX_PER_IP_PER_HOUR = 20

# In-memory request history: key -> list of timestamps.
# Applies to every email, whether or not an account exists, so the
# responses never reveal which emails are registered.
_RESET_REQUESTS = {}
_RESET_REQUESTS_LOCK = Lock()


def _reset_hash(value):
    """Keyed hash, so a leaked database cannot be used to read codes."""
    return hmac.new(
        str(app.secret_key).encode("utf-8"),
        str(value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _reset_time(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _reset_rate_limit(key, cooldown, max_per_hour):
    """Return 0 if allowed (and record it), else seconds to wait."""
    now = time.time()

    with _RESET_REQUESTS_LOCK:
        history = [
            stamp for stamp in _RESET_REQUESTS.get(key, [])
            if now - stamp < 3600
        ]

        if history and cooldown and now - history[-1] < cooldown:
            _RESET_REQUESTS[key] = history
            return max(1, math.ceil(cooldown - (now - history[-1])))

        if len(history) >= max_per_hour:
            _RESET_REQUESTS[key] = history
            return max(1, math.ceil(3600 - (now - history[0])))

        history.append(now)
        _RESET_REQUESTS[key] = history
        return 0


def _send_reset_code_email(to_email, to_name, code):
    """Runs in a background thread so response time never reveals accounts."""
    body = (
        f"Hello {to_name or 'there'},\n"
        "\n"
        "We received a request to reset your ResumeMatch AI password.\n"
        "\n"
        f"Your verification code is: {code}\n"
        "\n"
        f"This code expires in {_RESET_CODE_MINUTES} minutes. "
        "Never share it with anyone.\n"
        "\n"
        "If you did not request a password reset, you can safely ignore "
        "this email. Your password will not change.\n"
        "\n"
        "ResumeMatch AI"
    )

    try:
        send_email(
            to_email=to_email,
            to_name=to_name,
            subject="Your ResumeMatch AI password reset code",
            body=body,
        )
    except (EmailConfigError, EmailSendError) as error:
        app.logger.error("Password reset email was not sent: %s", error)
    except Exception:
        app.logger.exception("Unexpected error sending password reset email")


@app.route("/api/password-reset/request", methods=["POST"])
def api_password_reset_request():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()

    if not is_valid_email(email):
        return jsonify(
            success=False,
            message="Please enter a valid email address.",
        ), 400

    # A server setting problem is the same for everyone, so it is safe to report.
    try:
        get_smtp_config()
    except EmailConfigError as config_error:
        app.logger.error("Password reset unavailable: %s", config_error)
        return jsonify(
            success=False,
            message="Password reset email is not set up on the server yet.",
        ), 503

    wait = _reset_rate_limit(
        "email:" + email,
        _RESET_COOLDOWN_SECONDS,
        _RESET_MAX_PER_EMAIL_PER_HOUR,
    ) or _reset_rate_limit(
        "ip:" + str(request.remote_addr),
        0,
        _RESET_MAX_PER_IP_PER_HOUR,
    )

    if wait:
        return jsonify(
            success=False,
            message=(
                f"Please wait {wait} seconds before requesting another code."
                if wait <= _RESET_COOLDOWN_SECONDS
                else "Too many requests. Please try again later."
            ),
            retry_after=wait,
        ), 429

    try:
        user = get_user_by_email(email)

        if user and user["is_active"]:
            code = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = (
                datetime.now() + timedelta(minutes=_RESET_CODE_MINUTES)
            ).isoformat(timespec="seconds")

            save_password_reset_code(
                user["id"],
                _reset_hash(f"code:{user['id']}:{code}"),
                expires_at,
            )

            Thread(
                target=_send_reset_code_email,
                args=(user["email"], user["name"], code),
                daemon=True,
            ).start()

    except Exception:
        app.logger.exception("Password reset request failed")
        return jsonify(
            success=False,
            message="Something went wrong. Please try again.",
        ), 500

    # Same answer whether or not the account exists.
    return jsonify(
        success=True,
        message="If an account exists for that email, a code has been sent.",
        retry_after=_RESET_COOLDOWN_SECONDS,
    )


@app.route("/api/password-reset/verify", methods=["POST"])
def api_password_reset_verify():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    code = str(data.get("code", "")).strip()

    generic = jsonify(
        success=False,
        message="That code is not correct or has expired. Please try again.",
    ), 400

    if not is_valid_email(email) or not re.fullmatch(r"\d{6}", code):
        return generic

    try:
        user = get_user_by_email(email)

        if not user or not user["is_active"]:
            return generic

        reset = get_password_reset(user["id"])

        if not reset or not reset["code_hash"]:
            return generic

        expires_at = _reset_time(reset["code_expires_at"])

        if expires_at is None or datetime.now() > expires_at:
            delete_password_reset(user["id"])
            return generic

        # Count the attempt BEFORE checking, so parallel guesses cannot
        # exceed the limit.
        attempts = increment_password_reset_attempts(user["id"])

        if attempts is None or attempts > _RESET_MAX_ATTEMPTS:
            return jsonify(
                success=False,
                message="Too many incorrect attempts. Please request a new code.",
            ), 429

        expected = _reset_hash(f"code:{user['id']}:{code}")

        if not hmac.compare_digest(expected, reset["code_hash"]):
            left = _RESET_MAX_ATTEMPTS - attempts

            if left <= 0:
                message = "Too many incorrect attempts. Please request a new code."
            else:
                message = (
                    f"That code is not correct. {left} "
                    f"attempt{'s' if left != 1 else ''} left."
                )

            return jsonify(success=False, message=message), 400

        token = secrets.token_urlsafe(32)
        token_expires = (
            datetime.now() + timedelta(minutes=_RESET_TOKEN_MINUTES)
        ).isoformat(timespec="seconds")

        saved = save_password_reset_token(
            user["id"],
            _reset_hash(f"token:{user['id']}:{token}"),
            token_expires,
        )

        if not saved:
            return generic

        return jsonify(success=True, reset_token=token)

    except Exception:
        app.logger.exception("Password reset verification failed")
        return jsonify(
            success=False,
            message="Something went wrong. Please try again.",
        ), 500


@app.route("/api/password-reset/complete", methods=["POST"])
def api_password_reset_complete():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    token = str(data.get("reset_token", ""))
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not isinstance(password, str) or not password:
        return jsonify(
            success=False,
            message="Please enter a new password.",
        ), 400

    if len(password) < 8:
        return jsonify(
            success=False,
            message="Password must be at least 8 characters.",
        ), 400

    if password != confirm_password:
        return jsonify(
            success=False,
            message="Passwords do not match.",
        ), 400

    expired = jsonify(
        success=False,
        restart=True,
        message="Your reset session has expired. Please request a new code.",
    ), 400

    if not token or not is_valid_email(email):
        return expired

    try:
        user = get_user_by_email(email)

        if not user or not user["is_active"]:
            return expired

        reset = get_password_reset(user["id"])

        if not reset or not reset["token_hash"]:
            return expired

        token_expires = _reset_time(reset["token_expires_at"])

        if token_expires is None or datetime.now() > token_expires:
            delete_password_reset(user["id"])
            return expired

        expected = _reset_hash(f"token:{user['id']}:{token}")

        if not hmac.compare_digest(expected, reset["token_hash"]):
            return expired

        update_user_password(user["id"], hash_password(password))
        delete_password_reset(user["id"])

        return jsonify(success=True, message="Password updated.")

    except Exception:
        app.logger.exception("Password reset completion failed")
        return jsonify(
            success=False,
            message="Unable to update the password. Please try again.",
        ), 500

@app.route("/dashboard")
def dashboard():
    if not hr_logged_in():
        return redirect("/")

    hr = get_current_hr()

    if not hr:
        session.clear()
        return redirect("/")

    return render_template("dashboard.html", user_name=hr["name"])


@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    conn = None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM vacancies WHERE created_by = ?",
            (user_id,)
        )
        total_vacancies = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COUNT(*) FROM vacancies
            WHERE created_by = ?
            AND LOWER(TRIM(status)) IN ('published', 'active')
            """,
            (user_id,)
        )
        active_vacancies = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COUNT(DISTINCT a.candidate_id)
            FROM applications a
            INNER JOIN vacancies v ON v.id = a.vacancy_id
            WHERE v.created_by = ? AND a.candidate_id IS NOT NULL
            """,
            (user_id,)
        )
        total_candidates = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COUNT(DISTINCT a.candidate_id)
            FROM applications a
            INNER JOIN vacancies v ON v.id = a.vacancy_id
            WHERE v.created_by = ?
            AND a.candidate_id IS NOT NULL
            AND a.match_score IS NOT NULL
            AND CAST(a.match_score AS REAL) >= 62
            """,
            (user_id,)
        )
        strong_candidates = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM applications a
            INNER JOIN vacancies v ON v.id = a.vacancy_id
            WHERE v.created_by = ?
            """,
            (user_id,)
        )
        total_applications = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM applications a
            INNER JOIN vacancies v ON v.id = a.vacancy_id
            WHERE v.created_by = ?
            AND a.interview_score IS NOT NULL
            """,
            (user_id,)
        )
        interviews_completed = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT v.id, v.job_title, v.opening_date, v.status,
                   v.created_at, COUNT(a.id) AS applications
            FROM vacancies v
            LEFT JOIN applications a ON a.vacancy_id = v.id
            WHERE v.created_by = ?
            GROUP BY v.id, v.job_title, v.opening_date,
                     v.status, v.created_at
            ORDER BY v.created_at DESC
            LIMIT 5
            """,
            (user_id,)
        )

        recent_vacancies = [
            {
                "id": row["id"],
                "job_title": row["job_title"] or "",
                "opening_date": row["opening_date"] or "",
                "status": row["status"] or "",
                "created_at": row["created_at"] or "",
                "applications": int(row["applications"] or 0)
            }
            for row in cursor.fetchall()
        ]

        response = jsonify({
            "success": True,
            "stats": {
                "total_vacancies": total_vacancies,
                "active_vacancies": active_vacancies,
                "total_candidates": total_candidates,
                "strong_candidates": strong_candidates,
                "total_applications": total_applications,
                "interviews_completed": interviews_completed
            },
            "recent_vacancies": recent_vacancies
        })

        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except Exception as error:
        print("DASHBOARD SUMMARY ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to load dashboard data.",
            "error": str(error)
        }), 500

    finally:
        if conn is not None:
            conn.close()


@app.route("/vacancies")
def vacancies_page():
    if not hr_logged_in():
        return redirect("/")

    hr = get_current_hr()

    if not hr:
        session.clear()
        return redirect("/")

    public_token = hr["public_token"]

    if not public_token:
        return "HR public token is missing.", 500

    public_link = get_hr_public_url(public_token)
    vacancies = get_vacancies_by_hr(hr["id"])

    return render_template(
        "vacancies.html",
        user_name=hr["name"],
        public_link=public_link,
        vacancies=vacancies
    )


@app.route("/applicants")
def applicants_page():
    if not hr_logged_in():
        return redirect("/")

    hr = get_current_hr()

    if not hr:
        session.clear()
        return redirect("/")

    try:
        vacancy_id = int(request.args.get("vacancy_id", ""))
    except (TypeError, ValueError):
        return "Invalid vacancy ID.", 400

    conn = None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        # Verify that this vacancy belongs to the logged-in HR.
        vacancy = conn.execute(
            """
            SELECT id, job_title, jd_structured_data
            FROM vacancies
            WHERE id = ? AND created_by = ?
            """,
            (vacancy_id, hr["id"]),
        ).fetchone()

        if not vacancy:
            return "Vacancy not found.", 404

        # Load applicants for this vacancy only, in rank order.
        rows = conn.execute(
            """
            SELECT
                a.id AS application_id,
                c.full_name,
                c.email,
                c.phone,
                a.applied_at,
                a.application_status,
                a.matching_status,
                a.cv_match_score,
                a.match_score,
                a.skills_score,
                a.experience_score,
                a.education_score,
                a.interview_score,
                a.grade,
                a.eligibility,
                a.rank,
                                a.rank,
                a.match_explanation,
                (
                    SELECT MAX(se.sent_at)
                    FROM selection_emails AS se
                    WHERE se.application_id = a.id
                      AND se.status = 'sent'
                ) AS selection_email_sent_at
            FROM applications AS a
            JOIN candidates AS c ON c.id = a.candidate_id
            WHERE a.vacancy_id = ?
            ORDER BY
                CASE WHEN a.rank IS NULL THEN 1 ELSE 0 END,
                a.rank ASC,
                a.match_score DESC,
                a.applied_at ASC
            """,
            (vacancy_id,),
        ).fetchall()

        return render_template(
            "applicants.html",
            user_name=hr["name"],
            vacancy_id=vacancy_id,
            job_title=vacancy["job_title"] or "Untitled Vacancy",
            applicants=[dict(row) for row in rows],
            requirements=_jd_requirements(vacancy),
        )

    except Exception as error:
        print("APPLICANTS PAGE ERROR:", repr(error))
        return "Unable to load applicants. Check the server log.", 500

    finally:
        if conn is not None:
            conn.close()


@app.route(
    "/api/vacancies/<int:vacancy_id>/applicants",
    methods=["GET"],
)
def api_vacancy_applicants(vacancy_id):
    if not hr_logged_in():
        return jsonify(
            success=False,
            message="Please log in as HR.",
        ), 401

    hr = get_current_hr()

    if not hr:
        return jsonify(
            success=False,
            message="HR account not found.",
        ), 401

    conn = None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        # Only allow HR to see applicants for their own vacancy.
        vacancy = conn.execute(
            """
            SELECT id, jd_structured_data
            FROM vacancies
            WHERE id = ? AND created_by = ?
            """,
            (vacancy_id, hr["id"]),
        ).fetchone()

        if not vacancy:
            return jsonify(
                success=False,
                message="Vacancy not found.",
            ), 404

        rows = conn.execute(
            """
            SELECT
                a.id AS application_id,
                c.full_name,
                c.email,
                c.phone,
                a.applied_at,
                a.application_status,
                a.matching_status,
                a.cv_match_score,
                a.match_score,
                a.skills_score,
                a.experience_score,
                a.education_score,
                a.interview_score,
                a.grade,
                a.eligibility,
                                a.rank,
                a.match_explanation,
                (
                    SELECT MAX(se.sent_at)
                    FROM selection_emails AS se
                    WHERE se.application_id = a.id
                      AND se.status = 'sent'
                ) AS selection_email_sent_at
            FROM applications AS a
            JOIN candidates AS c ON c.id = a.candidate_id
            WHERE a.vacancy_id = ?
          
ORDER BY
    CASE
        WHEN a.match_score IS NOT NULL
         AND LOWER(COALESCE(a.matching_status, '')) = 'completed'
        THEN 0
        ELSE 1
    END,
    CASE
        WHEN a.match_score IS NOT NULL
         AND LOWER(COALESCE(a.matching_status, '')) = 'completed'
        THEN a.match_score
    END DESC,
    a.applied_at ASC

            """,
            (vacancy_id,),
        ).fetchall()

        response = jsonify(
            success=True,
            applicants=[dict(row) for row in rows],
            requirements=_jd_requirements(vacancy),
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception:
        app.logger.exception(
            "Unable to refresh applicants for vacancy %s",
            vacancy_id,
        )
        return jsonify(
            success=False,
            message="Unable to refresh applicant results.",
        ), 500

    finally:
        if conn is not None:
            conn.close()

_EDUCATION_NOT_REQUIRED = {
    "not required", "no education required", "education not required",
    "none", "n a", "na",
}


def _education_requirement_items(value):
    if value is None:
        return []

    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[\n;|]+", value) if p.strip()]

    if isinstance(value, dict):
        return _education_requirement_items(
            " ".join(str(v) for v in value.values())
        )

    if isinstance(value, (list, tuple, set)):
        items = []
        for entry in value:
            items.extend(_education_requirement_items(entry))
        return items

    return [str(value)]


def _jd_requirements(vacancy):
    """Mirror the matcher: is an education requirement actually set?"""

    raw = (
        vacancy["jd_structured_data"]
        if "jd_structured_data" in vacancy.keys()
        else None
    )

    jd = _parse_interview_json(raw)

    def normalize(text):
        t = str(text).lower().replace("&", " and ")
        t = re.sub(r"[^a-z0-9+#.\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    education = any(
        normalize(item) not in _EDUCATION_NOT_REQUIRED
        for item in _education_requirement_items(jd.get("education"))
    )

    return {
        "education": education,
        "experience": _has_interview_content(jd.get("experience")),
    }


def _score_breakdown(result):
    """Rebuild weighted score contributions from a stored matcher result."""

    if not isinstance(result, dict) or result.get("final_score") is None:
        return None

    education = (
        result.get("education")
        if isinstance(result.get("education"), dict)
        else {}
    )

    edu_component = education.get("component_score")
    edu_applies = edu_component is not None

    if edu_applies:
        w_skills, w_exp, w_edu = 0.50, 0.30, 0.10
    else:
        w_skills = 0.50 / 0.8 * 0.9
        w_exp = 0.30 / 0.8 * 0.9
        w_edu = 0.0

    w_interview = 0.10

    def row(label, score, weight, score_scale=100):
        if score is None:
            return None

        score = float(score)
        normalized_score = score / score_scale * 100

        return {
            "label": label,
            "score": round(normalized_score, 2),
            "weight": round(weight * 100, 2),
            "points": round(score / score_scale * weight * 100, 2),
            "max_points": round(weight * 100, 2),
        }

    rows = [
        row("Skills", result.get("skills_score"), w_skills),
        row("Experience", result.get("experience_score"), w_exp),
        row("Education", edu_component, w_edu, score_scale=10)
        if edu_applies else None,
        row("Interview", result.get("interview_score"), w_interview),
    ]

    return {
        "rows": [r for r in rows if r is not None],
        "final_score": result.get("final_score"),
        "education_applies": edu_applies,
    }



def _resolve_application_resume(resume_path):
    """
    Return the stored CV as a Path only if it is a real PDF inside the
    applications upload folder. Anything else returns None.
    """

    if not resume_path:
        return None

    try:
        resolved = Path(str(resume_path)).resolve()
        resolved.relative_to(UPLOAD_FOLDER.resolve())
    except (OSError, ValueError):
        return None

    if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
        return None

    return resolved


def _get_hr_application(conn, application_id, hr_id):
    """Load an application only if it belongs to one of this HR's vacancies."""

    return conn.execute(
        """
        SELECT a.*, c.full_name, c.email, c.phone
        FROM applications AS a
        JOIN vacancies AS v ON v.id = a.vacancy_id
        JOIN candidates AS c ON c.id = a.candidate_id
        WHERE a.id = ? AND v.created_by = ?
        LIMIT 1
        """,
        (application_id, hr_id),
    ).fetchone()


@app.route(
    "/api/applications/<int:application_id>/details",
    methods=["GET"],
)
def api_application_details(application_id):
    if not hr_logged_in():
        return jsonify(
            success=False,
            message="Please log in as HR.",
        ), 401

    hr = get_current_hr()

    if not hr:
        return jsonify(
            success=False,
            message="HR account not found.",
        ), 401

    conn = None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        application = _get_hr_application(conn, application_id, hr["id"])

        if not application:
            return jsonify(
                success=False,
                message="Application not found.",
            ), 404

        interview = conn.execute(
            """
            SELECT id
            FROM interviews
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

        answers = []

        if interview:
            rows = conn.execute(
                """
                SELECT question_number, question, category, answer,
                       score, quality, assessment_status
                FROM interview_answers
                WHERE interview_id = ?
                ORDER BY question_number ASC, id ASC
                """,
                (interview["id"],),
            ).fetchall()

            for row in rows:
                category = str(row["category"] or "").strip().lower()
                is_verification = "verification" in category

                answers.append({
                    "question_number": row["question_number"],
                    "question": row["question"] or "",
                    "category": category,
                    "answer": row["answer"] or "",
                    "score": row["score"],
                    "max_score": None if is_verification else 2,
                    "feedback": row["quality"] or "",
                    "status": str(
                        row["assessment_status"] or ""
                    ).strip().lower(),
                })

        match_result = None
        raw_result = application["match_result_json"]

        if raw_result:
            try:
                parsed = json.loads(raw_result)
                match_result = parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                match_result = None

       
        response = jsonify(
    success=True,
    answers=answers,
    match_result=match_result,
    score_breakdown=_score_breakdown(match_result),
    has_cv=_resolve_application_resume(
        application["resume_path"]
    ) is not None,
)

        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception:
        app.logger.exception(
            "Unable to load details for application %s",
            application_id,
        )
        return jsonify(
            success=False,
            message="Unable to load applicant details.",
        ), 500

    finally:
        if conn is not None:
            conn.close()


@app.route(
    "/api/applications/<int:application_id>/resume",
    methods=["GET"],
)
def api_application_resume(application_id):
    if not hr_logged_in():
        return jsonify(
            success=False,
            message="Please log in as HR.",
        ), 401

    hr = get_current_hr()

    if not hr:
        return jsonify(
            success=False,
            message="HR account not found.",
        ), 401

    conn = None

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        application = _get_hr_application(conn, application_id, hr["id"])

    finally:
        if conn is not None:
            conn.close()

    if not application:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    resume_file = _resolve_application_resume(application["resume_path"])

    if resume_file is None:
        return jsonify(
            success=False,
            message="The original CV file is not available.",
        ), 404

    # Uploads are stored as "<24 hex chars>_<original name>.pdf".
    download_name = resume_file.name
    prefix, _, rest = download_name.partition("_")

    if (
        rest
        and len(prefix) == 24
        and all(char in "0123456789abcdef" for char in prefix.lower())
    ):
        download_name = rest

    return send_file(
        str(resume_file),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )

# ============================================================
# SELECTION EMAIL
# ============================================================

_SE_SUBJECT_MAX = 200
_SE_BODY_MAX = 5000

# Applications with a send running right now (blocks double-clicks that
# arrive at the server at the same time).
_SELECTION_EMAIL_IN_PROGRESS = set()
_SELECTION_EMAIL_LOCK = Lock()


def _selection_email_hr():
    """Return (hr, None) or (None, error_response)."""

    if not hr_logged_in():
        return None, (
            jsonify(success=False, message="Please log in as HR."),
            401,
        )

    hr = get_current_hr()

    if not hr:
        return None, (
            jsonify(success=False, message="HR account not found."),
            401,
        )

    return hr, None


def _current_template(hr_id):
    """The HR's saved template, or the built-in default."""

    row = get_email_template(hr_id)

    if row:
        return row["subject"], row["body"]

    return DEFAULT_TEMPLATE_SUBJECT, DEFAULT_TEMPLATE_BODY


def _clean_email_text(subject, body):
    """Return (subject, body, problem). problem is None when valid."""

    subject = re.sub(r"[\r\n]+", " ", str(subject or "")).strip()
    body = str(body or "").replace("\r\n", "\n").strip()

    if not subject:
        return subject, body, "Please enter a subject."

    if not body:
        return subject, body, "Please enter the email message."

    if len(subject) > _SE_SUBJECT_MAX:
        return subject, body, f"The subject must be {_SE_SUBJECT_MAX} characters or fewer."

    if len(body) > _SE_BODY_MAX:
        return subject, body, f"The message must be {_SE_BODY_MAX} characters or fewer."

    unknown = find_unknown_placeholders(subject + "\n" + body)

    if unknown:
        return subject, body, (
            "Unknown placeholder " + unknown[0]
            + ". Use {{candidate_name}} or {{job_title}}."
        )

    return subject, body, None


def _selection_email_context(application_id, hr_id):
    """Candidate and vacancy details, only for this HR's own applications."""

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        application = _get_hr_application(conn, application_id, hr_id)

        if not application:
            return None

        vacancy = conn.execute(
            "SELECT job_title FROM vacancies WHERE id = ?",
            (application["vacancy_id"],),
        ).fetchone()

    finally:
        conn.close()

    return {
        "application_id": application_id,
        "to_name": (application["full_name"] or "").strip(),
        "to_email": (application["email"] or "").strip(),
        "job_title": ((vacancy["job_title"] if vacancy else "") or "").strip(),
    }


def _placeholder_values(context):
    return {
        "candidate_name": context["to_name"] or "Candidate",
        "job_title": context["job_title"],
    }


@app.route("/api/selection-email/template", methods=["GET"])
def api_get_selection_email_template():
    hr, error = _selection_email_hr()

    if error:
        return error

    try:
        subject, body = _current_template(hr["id"])
    except Exception:
        app.logger.exception("Unable to load the selection email template")
        return jsonify(
            success=False,
            message="Unable to load the email template.",
        ), 500

    response = jsonify(success=True, subject=subject, body=body)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/selection-email/template", methods=["PUT"])
def api_save_selection_email_template():
    hr, error = _selection_email_hr()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    subject, body, problem = _clean_email_text(
        data.get("subject"),
        data.get("body"),
    )

    if problem:
        return jsonify(success=False, message=problem), 400

    try:
        save_email_template(hr["id"], subject, body)
    except Exception:
        app.logger.exception("Unable to save the selection email template")
        return jsonify(
            success=False,
            message="Unable to save the email template.",
        ), 500

    return jsonify(success=True, message="Email template saved.")


@app.route(
    "/api/applications/<int:application_id>/selection-email/preview",
    methods=["GET"],
)
def api_selection_email_preview(application_id):
    hr, error = _selection_email_hr()

    if error:
        return error

    try:
        context = _selection_email_context(application_id, hr["id"])

        if not context:
            return jsonify(
                success=False,
                message="Application not found.",
            ), 404

        subject, body = _current_template(hr["id"])
        values = _placeholder_values(context)
        can_send = is_valid_email(context["to_email"])

        response = jsonify(
            success=True,
            to_name=context["to_name"],
            to_email=context["to_email"],
            job_title=context["job_title"],
            subject=fill_placeholders(subject, values),
            body=fill_placeholders(body, values),
            sent_at=get_last_selection_email_sent(application_id),
            can_send=can_send,
            problem=(
                None if can_send
                else "This candidate does not have a usable email address."
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception:
        app.logger.exception(
            "Unable to prepare selection email for application %s",
            application_id,
        )
        return jsonify(
            success=False,
            message="Unable to prepare the email.",
        ), 500


@app.route(
    "/api/applications/<int:application_id>/selection-email/send",
    methods=["POST"],
)
def api_send_selection_email(application_id):
    hr, error = _selection_email_hr()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    try:
        context = _selection_email_context(application_id, hr["id"])

        if not context:
            return jsonify(
                success=False,
                message="Application not found.",
            ), 404

        # The recipient always comes from the database, never the browser.
        if not is_valid_email(context["to_email"]):
            return jsonify(
                success=False,
                message="This candidate does not have a usable email address.",
            ), 422

        try:
            get_smtp_config()
        except EmailConfigError as config_error:
            return jsonify(success=False, message=str(config_error)), 503

        # Edit & Send supplies its own text; Send Email uses the template.
        if "subject" in data or "body" in data:
            subject, body, problem = _clean_email_text(
                data.get("subject"),
                data.get("body"),
            )

            if problem:
                return jsonify(success=False, message=problem), 400
        else:
            subject, body = _current_template(hr["id"])

        values = _placeholder_values(context)
        subject = fill_placeholders(subject, values)
        body = fill_placeholders(body, values)

        confirm_resend = data.get("confirm_resend") is True

        with _SELECTION_EMAIL_LOCK:
            if application_id in _SELECTION_EMAIL_IN_PROGRESS:
                return jsonify(
                    success=False,
                    message="This email is already being sent. Please wait.",
                ), 409

            _SELECTION_EMAIL_IN_PROGRESS.add(application_id)

        try:
            already_sent_at = get_last_selection_email_sent(application_id)

            if already_sent_at and not confirm_resend:
                return jsonify(
                    success=False,
                    already_sent=True,
                    sent_at=already_sent_at,
                    message="A selection email was already sent to this candidate.",
                ), 409

            try:
                send_email(
                    to_email=context["to_email"],
                    to_name=context["to_name"],
                    subject=subject,
                    body=body,
                    reply_to=hr["email"],
                )

            except EmailConfigError as config_error:
                return jsonify(success=False, message=str(config_error)), 503

            except EmailSendError as send_error:
                try:
                    log_selection_email(
                        application_id, hr["id"], context["to_email"],
                        subject, body, "failed", str(send_error)[:300],
                    )
                except Exception:
                    app.logger.exception("Could not log the failed email")

                return jsonify(success=False, message=str(send_error)), 502

            # The SMTP server accepted the message.
            try:
                sent_at = log_selection_email(
                    application_id, hr["id"], context["to_email"],
                    subject, body, "sent",
                )
            except Exception:
                app.logger.exception("Email was sent but could not be logged")
                sent_at = datetime.now().isoformat(timespec="seconds")

            return jsonify(
                success=True,
                message=f"Email accepted for delivery to {context['to_email']}.",
                sent_at=sent_at,
            )

        finally:
            with _SELECTION_EMAIL_LOCK:
                _SELECTION_EMAIL_IN_PROGRESS.discard(application_id)

    except Exception:
        app.logger.exception(
            "Unexpected error sending selection email for application %s",
            application_id,
        )
        return jsonify(
            success=False,
            message="Something went wrong while sending the email.",
        ), 500

@app.route("/interview-questions")
@app.route("/chatbot")
@app.route("/Chatbot")
def interview_questions_page():
    if not hr_logged_in():
        return redirect("/")

    hr = get_current_hr()

    if not hr:
        return redirect("/")

    raw_vacancy_id = request.args.get("vacancy_id")

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        # No vacancy selected: display the HR's vacancy list.
        if not raw_vacancy_id:
            rows = conn.execute(
                """
                SELECT id, job_title, status, created_at
                FROM vacancies
                WHERE created_by = ?
                ORDER BY created_at DESC
                """,
                (hr["id"],),
            ).fetchall()

            return render_template(
                "chatbot_select.html",
                user_name=hr["name"],
                vacancies=[dict(row) for row in rows],
            )

        # Vacancy selected: display its question editor.
        try:
            vacancy_id = int(raw_vacancy_id)
        except (TypeError, ValueError):
            return "A valid vacancy ID is required.", 400

        vacancy = conn.execute(
            """
            SELECT id, job_title
            FROM vacancies
            WHERE id = ? AND created_by = ?
            """,
            (vacancy_id, hr["id"]),
        ).fetchone()

        if not vacancy:
            return "Vacancy not found.", 404

        return render_template(
            "chatbot.html",
            user_name=hr["name"],
            vacancy_id=vacancy_id,
            job_title=vacancy["job_title"] or "Untitled Vacancy",
        )

    finally:
        conn.close()



@app.route("/jobs/<string:hr_public_token>")
def public_hr_jobs(hr_public_token):
    try:
        hr = get_hr_by_public_token(hr_public_token)

        if hr is None:
            return "Jobs page not found.", 404

        return render_template("candidate_vacancy.html", hr=hr)

    except Exception as error:
        print("[PUBLIC JOBS ERROR]:", repr(error))
        return "Unable to load candidate page.", 500


@app.route("/api/public/jobs/<string:hr_public_token>", methods=["GET"])
def api_public_hr_jobs(hr_public_token):
    try:
        hr = get_hr_by_public_token(hr_public_token)

        if hr is None:
            return jsonify({
                "success": False,
                "message": "Jobs page not found."
            }), 404

        vacancies = get_public_vacancies_by_hr(hr["id"])

        result = [
            {
                "id": vacancy["id"],
                "public_token": vacancy["public_token"],
                "job_title": vacancy["job_title"] or "",
                "description": vacancy["description"] or "",
                "location": vacancy["location"] or "",
                "salary": vacancy["salary"] or "",
                "employment_type": vacancy["employment_type"] or "",
                "work_mode": vacancy["work_mode"] or "",
                "experience": vacancy["experience"] or "",
                "department": vacancy["department"] or "",
                "responsibilities": vacancy["responsibilities"] or "",
                "requirements": vacancy["requirements"] or "",
                "required_skills": vacancy["required_skills"] or "",
                "opening_date": vacancy["opening_date"] or "",
                "closing_date": vacancy["closing_date"] or "",
                "published_at": vacancy["published_at"] or ""
            }
            for vacancy in vacancies
        ]

        response = jsonify({
            "success": True,
            "hr": {
                "id": hr["id"],
                "name": hr["name"]
            },
            "vacancies": result
        })

        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except Exception as error:
        print("[PUBLIC JOBS API ERROR]:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to load vacancies."
        }), 500


@app.route("/careers/<string:public_token>")
def candidate_vacancy(public_token):
    vacancy = get_public_vacancy_by_token(public_token)

    if not vacancy:
        return "Job vacancy not found.", 404

    if normalize_status(vacancy["status"]) != "published":
        return "This vacancy is not currently accepting applications.", 403

    return render_template("candidate_vacancy.html")


@app.route("/api/public/vacancies/<string:public_token>", methods=["GET"])
def api_public_vacancy(public_token):
    vacancy = get_public_vacancy_by_token(public_token)

    if not vacancy:
        return jsonify({
            "success": False,
            "error": "Job vacancy not found."
        }), 404

    if normalize_status(vacancy["status"]) != "published":
        return jsonify({
            "success": False,
            "error": "This vacancy is not currently accepting applications."
        }), 403

    return jsonify({
        "success": True,
        "vacancy": vacancy_to_dict(vacancy)
    })


@app.route("/careers/<string:public_token>/apply", methods=["GET"])
def candidate_apply(public_token):
    vacancy = get_public_vacancy_by_token(public_token)

    if not vacancy:
        return "Job vacancy not found.", 404

    if normalize_status(vacancy["status"]) != "published":
        return "This vacancy is no longer accepting applications.", 403

    return render_template("candidate_apply.html")

def _load_completed_interview_response(application_id):
    """Return saved interview results only when every answer is assessed."""

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        interview = conn.execute(
            """
            SELECT id, session_json
            FROM interviews
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

        if not interview:
            return None

        try:
            session = json.loads(interview["session_json"] or "")
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(session, dict) or not session.get("completed"):
            return None

        questions = session.get("questions", [])
        answers = session.get("answers", {})

        if not questions or not isinstance(answers, dict):
            return None

        if len(answers) != len(questions):
            return None

        response_record = session.get("response_record")

        if (
            not isinstance(response_record, dict)
            or response_record.get("interview_completed") is not True
            or response_record.get("interview_score_10") is None
        ):
            return None

        # Check the persisted assessment status of every question.
        rows = conn.execute(
            """
            SELECT question_id, assessment_status
            FROM interview_answers
            WHERE interview_id = ?
            """,
            (interview["id"],),
        ).fetchall()

        statuses = {
            str(row["question_id"]): str(
                row["assessment_status"] or ""
            ).strip().lower()
            for row in rows
        }

        for question in questions:
            question_id = question.get("id")

            if not question_id or statuses.get(question_id) != "complete":
                return None

        return response_record

    finally:
        conn.close()


# Applications whose post-CV finalization check is running right now.
# Both background threads (CV processing and interview completion) can reach
# the finalization step at nearly the same time; this prevents running the
# same final matching twice inside this process.
_FINALIZATION_IN_PROGRESS = set()
_FINALIZATION_LOCK = Lock()


def resume_interview_finalization_after_cv(application_id, vacancy_id):
    """
    Readiness check that runs after CV processing and preliminary matching.

    It reads the stored database state (never browser state) and resumes the
    EXISTING finalization workflow only when the interview was already
    completed before the structured CV became available:

    * Interview status 'Scoring' (answers submitted, assessments pending or
      done): call the existing _try_finalize_candidate_interview(), which
      verifies every required assessment and atomically claims finalization,
      so a running, failed, pending, or completed assessment is never
      restarted or treated as complete.

    * Interview already completed by the interview route, but its final
      matching was parked as 'pending_cv_processing' because the CV was not
      ready: re-run the existing recalculate_matching() once, using the
      saved response record.

    Anything else (interview not completed, already finalized, a
    failed matching, assessments still outstanding) is left unchanged.
    Returns a short string describing the outcome, for logging only.
    """

    with _FINALIZATION_LOCK:
        if application_id in _FINALIZATION_IN_PROGRESS:
            return "already_running"

        _FINALIZATION_IN_PROGRESS.add(application_id)

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row

        try:
            application_row = conn.execute(
                """
                SELECT *
                FROM applications
                WHERE id = ? AND vacancy_id = ?
                LIMIT 1
                """,
                (application_id, vacancy_id),
            ).fetchone()

            vacancy_row = conn.execute(
                """
                SELECT *
                FROM vacancies
                WHERE id = ?
                LIMIT 1
                """,
                (vacancy_id,),
            ).fetchone()

            interview_row = conn.execute(
                """
                SELECT *
                FROM interviews
                WHERE application_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (application_id,),
            ).fetchone()

        finally:
            conn.close()

        if not application_row or not vacancy_row:
            return "application_or_vacancy_missing"

        if not interview_row:
            return "no_interview"

        application = dict(application_row)
        vacancy = dict(vacancy_row)
        interview = dict(interview_row)

        matching_status = str(
            application.get("matching_status") or ""
        ).strip().lower()

        # Already finalized: never recalculate or re-rank unnecessarily.
        if matching_status == "completed":
            return "already_final"

        pipeline_status = str(
            application.get("pipeline_status") or ""
        ).strip().lower()

        if (
            pipeline_status not in {"completed", "complete", "success"}
            or not application.get("structured_cv")
        ):
            return "cv_not_ready"

        interview_status = str(
            interview.get("status") or ""
        ).strip().lower()

        # Case 1: answers submitted, waiting only on prerequisites.
        if interview_status == "scoring":
            finalized = _try_finalize_candidate_interview(
                application_id,
                interview["id"],
            )

            return (
                "finalized"
                if finalized
                else "waiting_for_assessments"
            )

        # Case 2: interview completed while the CV was still processing,
        # and final matching was parked as pending_cv_processing.
        if (
            interview_status == "completed"
            and matching_status == "pending_cv_processing"
        ):
            session_data = _parse_interview_json(
                interview.get("session_json")
            )

            record = session_data.get("response_record")

            if (
                not session_data.get("completed")
                or not isinstance(record, dict)
                or record.get("interview_completed") is not True
                or record.get("interview_score_10") is None
            ):
                return "no_final_record"

            try:
                from app.services.interview_routes import (
                    recalculate_matching,
                )

                recalculate_matching(application, vacancy, record)

            except Exception:
                app.logger.exception(
                    "Resumed final matching failed for application %s",
                    application_id,
                )

                conn = sqlite3.connect(str(DB_PATH), timeout=10)

                try:
                    conn.execute(
                        """
                        UPDATE applications
                        SET matching_status = 'failed'
                        WHERE id = ?
                        """,
                        (application_id,),
                    )
                    conn.commit()

                finally:
                    conn.close()

                return "matching_failed"

            return "finalized"

        return "nothing_to_resume"

    finally:
        with _FINALIZATION_LOCK:
            _FINALIZATION_IN_PROGRESS.discard(application_id)


def process_application_background(application_id, vacancy_id, resume_path):
    try:
        update_application_pipeline(
            application_id,
            "processing",
            None
        )

        print(f"[PIPELINE] Application {application_id} started.")

        result = process_uploaded_resume(
            resume_path,
            application_id,
            vacancy_id
        )

        save_structured_cv(
            application_id,
            result["structured_resume"]
        )

        update_application_pipeline(
            application_id,
            "completed",
            None
        )

        print(f"[PIPELINE] Application {application_id} completed.")
        print(f"[PIPELINE] Structured CV: {result['structured_path']}")

        # PRELIMINARY CV MATCHING — BEFORE THE INTERVIEW
        try:
            preliminary_result = recalculate_preliminary_matching(
                application_id,
                vacancy_id,
            )

            if preliminary_result is not None:
                print(
                    f"[MATCHING] Preliminary matching completed "
                    f"for application {application_id}."
                )

                print(
                    f"[MATCHING] Provisional CV score: "
                    f"{preliminary_result.get('cv_score')}"
                )

        except Exception as matching_error:
            # CV processing is still complete even if matching fails.
            print(
                f"[PRELIMINARY MATCHING ERROR] "
                f"Application {application_id}: {matching_error}"
            )

        # READINESS CHECK — RESUME FINALIZATION IF THE INTERVIEW
        # WAS COMPLETED BEFORE CV PROCESSING FINISHED
        try:
            resume_outcome = resume_interview_finalization_after_cv(
                application_id,
                vacancy_id,
            )

            print(
                f"[FINALIZATION] Application {application_id}: "
                f"{resume_outcome}"
            )

        except Exception as resume_error:
            # CV processing and preliminary matching remain valid.
            print(
                f"[FINALIZATION RESUME ERROR] "
                f"Application {application_id}: {resume_error}"
            )

    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"

        try:
            update_application_pipeline(
                application_id,
                "failed",
                error_message
            )
        except Exception as db_error:
            print("[PIPELINE STATUS ERROR]:", repr(db_error))

        print(
            f"[PIPELINE] Application {application_id} failed:",
            error_message
        )


@app.route("/api/public/vacancies/<string:public_token>/apply", methods=["POST"])
def api_submit_candidate_application(public_token):
    vacancy = get_public_vacancy_by_token(public_token)

    if not vacancy:
        return jsonify({
            "success": False,
            "error": "Job vacancy not found."
        }), 404

    if normalize_status(vacancy["status"]) != "published":
        return jsonify({
            "success": False,
            "error": "This vacancy is not accepting applications."
        }), 403

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    resume = request.files.get("resume")

    if not full_name:
        return jsonify({"success": False, "error": "Full name is required."}), 400

    if len(full_name) < 2:
        return jsonify({"success": False, "error": "Please enter a valid full name."}), 400

    if not email:
        return jsonify({"success": False, "error": "Email address is required."}), 400

    if "@" not in email or "." not in email:
        return jsonify({"success": False, "error": "Please enter a valid email address."}), 400

    if not phone:
        return jsonify({"success": False, "error": "Phone number is required."}), 400

    if not resume or not resume.filename:
        return jsonify({"success": False, "error": "Please upload your resume."}), 400

    original_filename = secure_filename(resume.filename) or "resume.pdf"

    if Path(original_filename).suffix.lower() != ".pdf":
        return jsonify({
            "success": False,
            "error": "Only PDF resumes are accepted."
        }), 400

    try:
        resume.stream.seek(0)
        header = resume.stream.read(5)
        resume.stream.seek(0)
    except Exception:
        return jsonify({
            "success": False,
            "error": "Unable to read the uploaded resume."
        }), 400

    if header != b"%PDF-":
        return jsonify({
            "success": False,
            "error": "The uploaded file is not a valid PDF."
        }), 400

    try:
        resume.stream.seek(0, 2)
        file_size = resume.stream.tell()
        resume.stream.seek(0)
    except Exception:
        return jsonify({
            "success": False,
            "error": "Unable to read the uploaded resume size."
        }), 400

    if file_size > 10 * 1024 * 1024:
        return jsonify({
            "success": False,
            "error": "Resume must be 10 MB or smaller."
        }), 400

    if file_size == 0:
        return jsonify({
            "success": False,
            "error": "The uploaded resume is empty."
        }), 400

    candidate = get_candidate_by_email(email)

    if candidate:
        candidate_id = candidate["id"]
    else:
        try:
            candidate_id = create_candidate(
                full_name,
                email,
                phone
            )
        except Exception as error:
            print("CREATE CANDIDATE ERROR:", repr(error))
            return jsonify({
                "success": False,
                "error": "Unable to create candidate record."
            }), 500

    vacancy_folder = UPLOAD_FOLDER / f"vacancy_{vacancy['id']}"

    try:
        vacancy_folder.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        print("CREATE UPLOAD FOLDER ERROR:", repr(error))
        return jsonify({
            "success": False,
            "error": "Unable to prepare resume storage."
        }), 500

    unique_filename = secrets.token_hex(12) + "_" + original_filename
    resume_path = vacancy_folder / unique_filename

    try:
        resume.save(str(resume_path))
    except Exception as error:
        print("RESUME SAVE ERROR:", repr(error))
        return jsonify({
            "success": False,
            "error": "Unable to save the uploaded resume."
        }), 500

    try:
        result = create_application(
            vacancy_id=vacancy["id"],
            candidate_id=candidate_id,
            resume_path=str(resume_path)
        )

    except sqlite3.IntegrityError as error:
        print("APPLICATION DATABASE CONSTRAINT:", repr(error))

        try:
            if resume_path.exists():
                resume_path.unlink()
        except Exception:
            pass

        return jsonify({
            "success": False,
            "error": "You have already applied for this vacancy."
        }), 409

    except Exception as error:
        print("CREATE APPLICATION ERROR:", repr(error))

        try:
            if resume_path.exists():
                resume_path.unlink()
        except Exception:
            pass

        return jsonify({
            "success": False,
            "error": "Unable to submit your application."
        }), 500

    application_id = None
    application_token = None
    existing_application = False

    if isinstance(result, dict):
        application_id = result.get("id") or result.get("application_id")
        application_token = (
            result.get("public_token")
            or result.get("application_token")
        )
        existing_application = bool(result.get("existing"))

        if result.get("duplicate") is True:
            try:
                if resume_path.exists():
                    resume_path.unlink()
            except Exception:
                pass

            return jsonify({
                "success": False,
                "error": "You have already applied for this vacancy."
            }), 409
    else:
        application_id = result

    application = (
        get_application_by_id(application_id)
        if application_id
        else None
    )

    if application and not application_token:
        application_token = application["public_token"]

    if not application_token:
        try:
            if resume_path.exists():
                resume_path.unlink()
        except Exception:
            pass

        return jsonify({
            "success": False,
            "error": "Application was created but the interview link could not be generated."
        }), 500

    if application_id and not existing_application:
        Thread(
            target=process_application_background,
            args=(
                application_id,
                vacancy["id"],
                str(resume_path)
            ),
            daemon=True
        ).start()

    interview_url = (
        f"/careers/{public_token}/interview/{application_token}"
    )

    return jsonify({
        "success": True,
        "message": "Application submitted successfully.",
        "application_token": application_token,
        "interview_url": interview_url
    }), 201



@app.route(
    "/careers/<string:public_token>/interview/<string:application_token>",
    methods=["GET"]
)
def candidate_interview(public_token, application_token):

    vacancy = get_public_vacancy_by_token(public_token)

    if not vacancy:
        return "Job vacancy not found.", 404

    application = get_application_by_public_token(application_token)

    if not application:
        return "Application not found.", 404

    try:
        application_vacancy_id = int(application["vacancy_id"])
        vacancy_id = int(vacancy["id"])
    except (TypeError, ValueError):
        return "Invalid application.", 403

    # Verify that the application belongs to this vacancy.
    if application_vacancy_id != vacancy_id:
        return "Invalid application link.", 403

    # Get the public token of the HR who owns this vacancy.
    hr_public_token = ""

    try:
        created_by = (
            vacancy["created_by"]
            if "created_by" in vacancy.keys()
            else None
        )

        owner = get_user_by_id(created_by) if created_by else None

        if owner and owner["public_token"]:
            hr_public_token = owner["public_token"]

    except Exception as error:
        print("[INTERVIEW BACK LINK ERROR]:", repr(error))

    return render_template(
        "candidate_interview.html",
        vacancy_token=public_token,
        application_token=application_token,
        job_title=vacancy["job_title"] or "",
        hr_public_token=hr_public_token,
    )




@app.route("/create-vacancy")
def create_vacancy_page():
    if not hr_logged_in():
        return redirect("/")

    hr = get_current_hr()

    if not hr:
        session.clear()
        return redirect("/")

    return render_template(
        "create_vacancy.html",
        user_name=hr["name"]
    )


@app.route("/api/vacancies", methods=["GET"])
def api_get_vacancies():
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        vacancies = get_vacancies_by_hr(user_id)

        return jsonify({
            "success": True,
            "vacancies": [
                vacancy_to_dict(vacancy)
                for vacancy in vacancies
            ]
        })

    except Exception as error:
        print("GET VACANCIES ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to load vacancies."
        }), 500


@app.route("/api/vacancies/<int:vacancy_id>", methods=["GET"])
def api_get_vacancy(vacancy_id):
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        vacancy = get_vacancy_by_id(vacancy_id)

        if vacancy is None:
            return jsonify({
                "success": False,
                "message": "Vacancy not found."
            }), 404

        if not current_hr_owns_vacancy(vacancy):
            return jsonify({
                "success": False,
                "message": "You do not have access to this vacancy."
            }), 403

        return jsonify({
            "success": True,
            "vacancy": vacancy_to_dict(vacancy)
        })

    except Exception as error:
        print("GET VACANCY ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to load vacancy."
        }), 500


@app.route("/api/vacancies", methods=["POST"])
def api_create_vacancy():
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    current_user_id = session.get("user_id")

    if not current_user_id:
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({
            "success": False,
            "message": "Invalid JSON request."
        }), 400

    if not data:
        return jsonify({
            "success": False,
            "message": "No vacancy data received."
        }), 400

    job_title = str(data.get("job_title", "")).strip()
    job_description = str(
        data.get("job_description", data.get("description", ""))
    ).strip()
    location = str(data.get("location", "")).strip()
    salary = str(data.get("salary", "")).strip()
    employment_type = str(data.get("employment_type", "")).strip()
    work_mode = str(data.get("work_mode", "")).strip()
    opening_date = str(data.get("opening_date", "")).strip()
    application_end_date = str(
        data.get(
            "application_end_date",
            data.get("closing_date", "")
        )
    ).strip()
    requested_status = normalize_status(data.get("status", "draft"))

    if not job_title:
        return jsonify({
            "success": False,
            "message": "Job title is required."
        }), 400

    if not job_description:
        return jsonify({
            "success": False,
            "message": "Job description is required."
        }), 400

    if (
        opening_date
        and application_end_date
        and application_end_date < opening_date
    ):
        return jsonify({
            "success": False,
            "message": "Application end date cannot be before opening date."
        }), 400

    vacancy_id = None

    try:
        vacancy_id = create_vacancy(
            job_title=job_title,
            job_description=job_description,
            location=location or None,
            salary=salary or None,
            employment_type=employment_type or None,
            work_mode=work_mode or None,
            opening_date=opening_date or None,
            application_end_date=application_end_date or None,
            status="draft",
            created_by=current_user_id
        )

        update_jd_processing(
            vacancy_id=vacancy_id,
            processing_status="processing",
            structured_data=None,
            processing_error=None,
            processed_at=None
        )

        print(f"[JD AI] Processing vacancy {vacancy_id}: {job_title}")

        structured_jd = process_job_description(job_description)

        update_jd_processing(
            vacancy_id=vacancy_id,
            processing_status="ready",
            structured_data=json.dumps(
                structured_jd,
                ensure_ascii=False
            ),
            processing_error=None,
            processed_at=datetime.now().isoformat(timespec="seconds")
        )

        if requested_status == "published":
            update_vacancy_status(vacancy_id, "published")
            final_status = "published"
            message = "Vacancy published successfully."
        else:
            final_status = "draft"
            message = "Vacancy saved as draft successfully."

        return jsonify({
            "success": True,
            "message": message,
            "vacancy_id": vacancy_id,
            "status": final_status,
            "jd_processing_status": "ready"
        }), 201

    except Exception as error:
        print("CREATE VACANCY / JD AI ERROR:", repr(error))

        if vacancy_id is not None:
            try:
                update_jd_processing(
                    vacancy_id=vacancy_id,
                    processing_status="failed",
                    structured_data=None,
                    processing_error=str(error),
                    processed_at=None
                )
                update_vacancy_status(vacancy_id, "draft")
            except Exception as cleanup_error:
                print("JD FAILURE CLEANUP ERROR:", repr(cleanup_error))

        return jsonify({
            "success": False,
            "message": (
                "Vacancy was saved as draft, but ResumeMatch AI "
                "could not process the Job Description."
            ),
            "vacancy_id": vacancy_id
        }), 422


@app.route("/api/vacancies/<int:vacancy_id>", methods=["PUT"])
def api_update_vacancy(vacancy_id):
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({
            "success": False,
            "message": "Invalid JSON request."
        }), 400

    if not data:
        return jsonify({
            "success": False,
            "message": "No vacancy data received."
        }), 400

    existing_vacancy = get_vacancy_by_id(vacancy_id)

    if existing_vacancy is None:
        return jsonify({
            "success": False,
            "message": "Vacancy not found."
        }), 404

    if not current_hr_owns_vacancy(existing_vacancy):
        return jsonify({
            "success": False,
            "message": "You do not have permission to edit this vacancy."
        }), 403

    job_title = str(data.get("job_title", "")).strip()
    job_description = str(
        data.get("job_description", data.get("description", ""))
    ).strip()
    location = str(data.get("location", "")).strip()
    salary = str(data.get("salary", "")).strip()
    employment_type = str(data.get("employment_type", "")).strip()
    work_mode = str(data.get("work_mode", "")).strip()
    opening_date = str(data.get("opening_date", "")).strip()
    application_end_date = str(
        data.get(
            "application_end_date",
            data.get("closing_date", "")
        )
    ).strip()

    if not job_title:
        return jsonify({
            "success": False,
            "message": "Job title is required."
        }), 400

    if not job_description:
        return jsonify({
            "success": False,
            "message": "Job description is required."
        }), 400

    if (
        opening_date
        and application_end_date
        and application_end_date < opening_date
    ):
        return jsonify({
            "success": False,
            "message": "Application end date cannot be before opening date."
        }), 400

    old_description = (existing_vacancy["description"] or "").strip()
    jd_changed = old_description != job_description

    try:
        updated = update_vacancy(
            vacancy_id=vacancy_id,
            job_title=job_title,
            job_description=job_description,
            location=location or None,
            salary=salary or None,
            employment_type=employment_type or None,
            work_mode=work_mode or None,
            opening_date=opening_date or None,
            application_end_date=application_end_date or None
        )

        if not updated:
            return jsonify({
                "success": False,
                "message": "Vacancy not found."
            }), 404

        if not jd_changed:
            return jsonify({
                "success": True,
                "message": "Vacancy updated successfully.",
                "vacancy_id": vacancy_id,
                "jd_changed": False,
                "jd_processing_status": existing_vacancy[
                    "jd_processing_status"
                ]
            })

        update_jd_processing(
            vacancy_id=vacancy_id,
            processing_status="processing",
            structured_data=None,
            processing_error=None,
            processed_at=None
        )

        print(f"[JD AI] Re-processing vacancy {vacancy_id}")

        structured_jd = process_job_description(job_description)

        update_jd_processing(
            vacancy_id=vacancy_id,
            processing_status="ready",
            structured_data=json.dumps(
                structured_jd,
                ensure_ascii=False
            ),
            processing_error=None,
            processed_at=datetime.now().isoformat(timespec="seconds")
        )

        return jsonify({
            "success": True,
            "message": "Vacancy and Job Description updated successfully.",
            "vacancy_id": vacancy_id,
            "jd_changed": True,
            "jd_processing_status": "ready"
        })

    except Exception as error:
        print("UPDATE VACANCY / JD AI ERROR:", repr(error))

        if jd_changed:
            try:
                update_jd_processing(
                    vacancy_id=vacancy_id,
                    processing_status="failed",
                    structured_data=None,
                    processing_error=str(error),
                    processed_at=None
                )
            except Exception as cleanup_error:
                print("UPDATE JD FAILURE ERROR:", repr(cleanup_error))

        return jsonify({
            "success": False,
            "message": (
                "Vacancy fields were updated, but the Job Description "
                "could not be processed."
            ),
            "vacancy_id": vacancy_id,
            "jd_changed": jd_changed
        }), 422


@app.route("/api/vacancies/<int:vacancy_id>/status", methods=["PATCH"])
def api_change_vacancy_status(vacancy_id):
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({
            "success": False,
            "message": "Invalid JSON request."
        }), 400

    if not data:
        return jsonify({
            "success": False,
            "message": "No status data received."
        }), 400

    status = normalize_status(data.get("status", ""))

    if status not in {"draft", "processing", "published", "closed"}:
        return jsonify({
            "success": False,
            "message": "Invalid vacancy status."
        }), 400

    vacancy = get_vacancy_by_id(vacancy_id)

    if vacancy is None:
        return jsonify({
            "success": False,
            "message": "Vacancy not found."
        }), 404

    if not current_hr_owns_vacancy(vacancy):
        return jsonify({
            "success": False,
            "message": "You do not have permission to change this vacancy."
        }), 403

    if status == "published":
        jd_status = (
            vacancy["jd_processing_status"]
            if "jd_processing_status" in vacancy.keys()
            else "pending"
        )

        if jd_status != "ready":
            return jsonify({
                "success": False,
                "message": (
                    "This vacancy cannot be published until the "
                    "Job Description has been successfully processed."
                ),
                "jd_processing_status": jd_status
            }), 422

    try:
        updated = update_vacancy_status(vacancy_id, status)

        if not updated:
            return jsonify({
                "success": False,
                "message": "Vacancy not found."
            }), 404

        return jsonify({
            "success": True,
            "message": "Vacancy status updated.",
            "status": status
        })

    except Exception as error:
        print("STATUS UPDATE ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to update vacancy status."
        }), 500


@app.route("/api/vacancies/<int:vacancy_id>", methods=["DELETE"])
def api_delete_vacancy(vacancy_id):
    if not hr_logged_in():
        return jsonify({
            "success": False,
            "message": "Authentication required."
        }), 401

    try:
        vacancy = get_vacancy_by_id(vacancy_id)

        if vacancy is None:
            return jsonify({
                "success": False,
                "message": "Vacancy not found."
            }), 404

        if not current_hr_owns_vacancy(vacancy):
            return jsonify({
                "success": False,
                "message": "You do not have permission to delete this vacancy."
            }), 403

        deleted = delete_vacancy(vacancy_id)

        if not deleted:
            return jsonify({
                "success": False,
                "message": "Vacancy could not be deleted."
            }), 404

        return jsonify({
            "success": True,
            "message": "Vacancy deleted successfully."
        })

    except Exception as error:
        print("DELETE VACANCY ERROR:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to delete vacancy."
        }), 500


@app.errorhandler(413)
def file_too_large(error):
    if request.path.startswith("/api/public/vacancies/"):
        return jsonify({
            "success": False,
            "error": "Resume must be 10 MB or smaller."
        }), 413

    return "Uploaded file is too large.", 413


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def open_browser():
    webbrowser.open("http://127.0.0.1:5050/")


# ============================================================
# AI INTERVIEW
# ============================================================

DEFAULT_INTERVIEW_QUESTIONS = [
    {
        "id": "q1",
        "type": "standard",
        "question": "What are your strengths?"
    },
    {
        "id": "q2",
        "type": "standard",
        "question": "What is one weakness you are currently working on?"
    },
    {
        "id": "q3",
        "type": "standard",
        "question": "What is the best project you have worked on, and what did you learn from it?"
    },
    {
        "id": "q4",
        "type": "standard",
        "question": "What interests you most about this position, and why do you think it is a good fit for you?"
    },
    {
        "id": "q5",
        "type": "standard",
        "question": "What difficulties have you faced in your work or projects, and how did you handle them?"
    }
]


def get_candidate_interview_questions(vacancy_id):
    """Load saved HR questions for this vacancy, or use defaults."""
    default_questions = [
        dict(question) for question in DEFAULT_INTERVIEW_QUESTIONS
    ]

    if not vacancy_id:
        return default_questions

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT questions_json
            FROM vacancy_interview_settings
            WHERE vacancy_id = ?
            """,
            (vacancy_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return default_questions

    try:
        config = json.loads(row["questions_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return default_questions

    custom_questions = config.get("custom_questions", [])

    if (
        not isinstance(custom_questions, list)
        or len(custom_questions) != 5
        or any(
            not isinstance(question, str) or not question.strip()
            for question in custom_questions
        )
    ):
        return default_questions

    return [
        {
            **default_questions[index],
            "question": question.strip(),
        }
        for index, question in enumerate(custom_questions)
    ]


def _get_interview_application(application_token):
    """
    Safely retrieve an application using its public token.
    """

    application = get_application_by_public_token(application_token)

    if not application:
        return None, None

    interview = get_interview_by_application(application["id"])

    return application, interview


def _get_saved_interview_answers(interview_id):
    """
    Convert saved interview answers into a dictionary
    that the frontend can easily use.

    Example:
        {
            "q1": "My answer...",
            "q2": "Another answer..."
        }
    """

    rows = get_interview_answers(interview_id)

    answers = {}

    for row in rows:
        question_number = row["question_number"]

        if question_number is None:
            continue

        if question_number <= 5:
            question_id = f"q{question_number}"
        elif question_number == 6:
            question_id = "v1"
        elif question_number == 7:
            question_id = "v2"
        else:
            question_id = f"q{question_number}"

        answers[question_id] = row["answer"] or ""

    return answers


def _find_first_unanswered_question(questions, answers):
    """
    Find the first unanswered question.
    """

    for index, question in enumerate(questions):
        question_id = question["id"]

        if not str(answers.get(question_id, "")).strip():
            return index

    return len(questions)





def start_candidate_interview(application_token):
    application = get_application_by_public_token(application_token)

    if not application:
        return jsonify({
            "success": False,
            "message": "Application not found."
        }), 404

    application_id = application["id"]

    # --------------------------------------------------------
    # Load default questions and HR-customized questions
    # --------------------------------------------------------

    candidate_questions = [
        dict(question)
        for question in DEFAULT_INTERVIEW_QUESTIONS
    ]

    conn = get_connection()

    try:
        settings = conn.execute(
            """
            SELECT questions_json
            FROM vacancy_interview_settings
            WHERE vacancy_id = ?
            """,
            (application["vacancy_id"],),
        ).fetchone()
    finally:
        conn.close()

    if settings:
        try:
            config = json.loads(settings["questions_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}

        custom_questions = config.get("custom_questions", [])

        if (
            isinstance(custom_questions, list)
            and len(custom_questions) == len(candidate_questions)
            and all(
                isinstance(question, str) and question.strip()
                for question in custom_questions
            )
        ):
            candidate_questions = [
                {
                    **candidate_questions[index],
                    "question": question.strip(),
                }
                for index, question in enumerate(custom_questions)
            ]

    # --------------------------------------------------------
    # Find the existing interview
    # --------------------------------------------------------

    interview = get_interview_by_application(application_id)

    # --------------------------------------------------------
    # Return the correct state for completed/scoring interviews
    # --------------------------------------------------------

    if interview:
        status = str(
            interview["status"] or ""
        ).strip().lower()

        if status in {"completed", "scoring", "finalizing"}:
            answers = _get_saved_interview_answers(interview["id"])
            scoring_pending = status != "completed"

            return jsonify({
                "success": True,
                "interview_completed": True,
                "scoring_pending": scoring_pending,
                "phase": "completed",
                "questions": candidate_questions,
                "answers": answers,
                "current_question_index": len(candidate_questions),
                "message": (
                    "Your interview has been submitted. "
                    "Your results are being finalized."
                    if scoring_pending
                    else "Your interview is complete."
                ),
            })

    # --------------------------------------------------------
    # Create an interview on the candidate's first visit
    # --------------------------------------------------------

    if not interview:
        interview_id = create_interview(
            application_id,
            total_questions=len(candidate_questions),
        )

        interview = get_interview_by_id(interview_id)

        if not interview:
            return jsonify({
                "success": False,
                "message": "Unable to initialize your interview.",
            }), 500

    # --------------------------------------------------------
    # Restore saved answers
    # --------------------------------------------------------

    answers = _get_saved_interview_answers(interview["id"])

    # --------------------------------------------------------
    # Find the first unanswered core question
    # --------------------------------------------------------

    current_question_index = _find_first_unanswered_question(
        candidate_questions,
        answers,
    )

    # --------------------------------------------------------
    # Core interview complete: proceed to verification
    # --------------------------------------------------------

    if current_question_index >= len(candidate_questions):
        return jsonify({
            "success": True,
            "interview_completed": False,
            "scoring_pending": False,
            "phase": "verification",
            "questions": candidate_questions,
            "answers": answers,
            "current_question_index": len(candidate_questions),
        })

    # --------------------------------------------------------
    # Continue the core interview
    # --------------------------------------------------------

    return jsonify({
        "success": True,
        "interview_completed": False,
        "scoring_pending": False,
        "phase": "standard",
        "questions": candidate_questions,
        "answers": answers,
        "current_question_index": current_question_index,
    })


def _parse_interview_json(value):
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, TypeError):
            pass

    return {}


def _has_interview_content(value):
    if value is None:
        return False

    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)

    return bool(str(value).strip())


def _required_verification_numbers(application, vacancy):
    """Return required question numbers, or None if CV processing isn't ready."""

    pipeline_status = str(
        application["pipeline_status"] or ""
    ).strip().lower()

    if pipeline_status not in {"completed", "complete", "success"}:
        return None

    jd = _parse_interview_json(vacancy["jd_structured_data"])
    cv = _parse_interview_json(application["structured_cv"])

    required = {1, 2, 3, 4, 5}

    if (
        _has_interview_content(jd.get("education"))
        and not _has_interview_content(cv.get("education"))
    ):
        required.add(6)

    if (
        _has_interview_content(jd.get("experience"))
        and not _has_interview_content(cv.get("experience"))
    ):
        required.add(7)

    return required


def _update_optional_interview_fields(interview_id, **values):
    """Update only fields that exist in the current interviews schema."""

    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(interviews)"
            ).fetchall()
        }

        updates = {
            key: value
            for key, value in values.items()
            if key in columns
        }

        if not updates:
            return

        assignments = ", ".join(
            f'"{column}" = ?' for column in updates
        )

        conn.execute(
            f"""
            UPDATE interviews
            SET {assignments}
            WHERE id = ?
            """,
            (*updates.values(), interview_id),
        )

        conn.commit()

    finally:
        conn.close()


def _assess_candidate_answer_background(
    application_id,
    interview_id,
    question_number,
    question,
    question_type,
    answer,
):
    """
    Assess an already-saved answer in a background thread.

    The request that saves an answer does not wait for Gemini.
    """

    with app.app_context():
        result = None
        error_message = None

        try:
            application = get_application_by_id(application_id)

            if not application:
                raise ValueError("Application no longer exists.")

            vacancy = get_vacancy_by_id(application["vacancy_id"])

            if not vacancy:
                raise ValueError("Vacancy no longer exists.")

            jd = _parse_interview_json(vacancy["jd_structured_data"])
            category = str(question_type or "").lower()

            for attempt in range(3):
                try:
                    if (
                        question_number == 6
                        or "education" in category
                    ):
                        assessment = assess_education_answer(jd, answer)

                        result = {
                            "score": assessment.get("score"),
                            "quality": (
                                assessment.get("reason")
                                or assessment.get("status")
                                or ""
                            ),
                            "status": "complete",
                            "extra_fields": {
                                "education_assessment_json": json.dumps(
                                    assessment,
                                    ensure_ascii=False,
                                ),
                            },
                        }

                    elif (
                        question_number == 7
                        or "experience" in category
                    ):
                        years = extract_reported_years(answer)

                        result = {
                            # Years of experience are not a mark out of 2.
                            "score": None,
                            "quality": (
                                f"Reported years of experience: {years}"
                                if years is not None
                                else "Answer assessed; years could not be extracted."
                            ),
                            "status": "complete",
                            "extra_fields": {
                                "experience_answer": answer,
                                "candidate_reported_yoe": years,
                            },
                        }

                    else:
                        assessment = score_interview_answer(
                            question,
                            answer,
                            f"q{question_number}",
                        )

                        score = assessment.get("score")

                        if score is None:
                            raise ValueError(
                                "The interview assessor returned no score."
                            )

                        result = {
                            "score": float(score),
                            "quality": str(
                                assessment.get("feedback")
                                or assessment.get("quality")
                                or assessment.get("reason")
                                or ""
                            ),
                            "status": "complete",
                            "extra_fields": {},
                        }

                    break

                except Exception:
                    if attempt == 2:
                        raise

                    time.sleep(0.5)

            # Write to the existing answer record.
            conn = sqlite3.connect(str(DB_PATH), timeout=10)

            try:
                conn.execute("BEGIN IMMEDIATE")

                cursor = conn.execute(
                    """
                    UPDATE interview_answers
                    SET score = ?,
                        quality = ?,
                        assessment_status = ?
                    WHERE interview_id = ?
                      AND question_number = ?
                      AND answer = ?
                    """,
                    (
                        result["score"],
                        result["quality"],
                        result["status"],
                        interview_id,
                        question_number,
                        answer,
                    ),
                )

                if cursor.rowcount == 0:
                    conn.rollback()
                    return

                conn.commit()

            finally:
                conn.close()

            _update_optional_interview_fields(
                interview_id,
                **result["extra_fields"],
            )

        except Exception as error:
            error_message = str(error)
            app.logger.exception(
                "Assessment failed for interview %s, question %s",
                interview_id,
                question_number,
            )

            conn = sqlite3.connect(str(DB_PATH), timeout=10)

            try:
                conn.execute(
                    """
                    UPDATE interview_answers
                    SET assessment_status = 'failed',
                        quality = ?
                    WHERE interview_id = ?
                      AND question_number = ?
                      AND answer = ?
                    """,
                    (
                        f"Assessment failed: {error_message[:200]}",
                        interview_id,
                        question_number,
                        answer,
                    ),
                )
                conn.commit()

            finally:
                conn.close()

        # If the candidate has already submitted the interview, this
        # attempts finalization after the latest assessment result.
        _try_finalize_candidate_interview(
            application_id,
            interview_id,
        )


def _try_finalize_candidate_interview(application_id, interview_id):
    """
    Finalize the interview only after all required answers have
    been assessed. Then publish scores and recalculate matching.
    """

    application = get_application_by_id(application_id)
    interview = get_interview_by_id(interview_id)

    if not application or not interview:
        return False

    status = str(interview["status"] or "").strip().lower()

    # Only finalize an interview explicitly submitted for scoring.
    if status != "scoring":
        return False

    vacancy = get_vacancy_by_id(application["vacancy_id"])

    if not vacancy:
        return False

    required = _required_verification_numbers(application, vacancy)

    if required is None:
        return False

    saved_answers = get_interview_answers(interview_id)

    answers_by_number = {
        int(row["question_number"]): row
        for row in saved_answers
        if row["question_number"] is not None
    }

    # Verify every required answer and its assessment.
    for number in required:
        row = answers_by_number.get(number)

        if row is None:
            return False

        assessment_status = str(
            row["assessment_status"] or ""
        ).strip().lower()

        if assessment_status != "complete":
            return False

        if number <= 5 and row["score"] is None:
            return False

    # Validate all five standard interview questions.
    standard_scores = []

    for number in range(1, 6):
        row = answers_by_number.get(number)

        if row is None:
            return False

        try:
            assessment_status = str(
                row["assessment_status"] or ""
            ).strip().lower()

            score = float(row["score"])

        except (KeyError, IndexError, TypeError, ValueError):
            return False

        if assessment_status != "complete":
            return False

        if not 0 <= score <= 2:
            return False

        standard_scores.append(score)

    # Five questions × two marks = maximum 10.
    interview_score = round(sum(standard_scores), 2)

    completed_at = datetime.now().isoformat(timespec="seconds")

    # Atomically claim finalization to avoid duplicate processing.
    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    try:
        conn.execute("BEGIN IMMEDIATE")

        cursor = conn.execute(
            """
            UPDATE interviews
            SET status = 'Finalizing',
                overall_score = ?,
                completed_at = ?
            WHERE id = ?
              AND LOWER(TRIM(status)) = 'scoring'
            """,
            (interview_score, completed_at, interview_id),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return False

        conn.commit()

    except Exception:
        conn.rollback()
        app.logger.exception(
            "Could not claim interview finalization: %s",
            interview_id,
        )
        return False

    finally:
        conn.close()

    education_row = answers_by_number.get(6)

    education_score = (
        education_row["score"] if education_row else None
    )

    # Publish the interview score to the application.
    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    try:
        application_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(applications)"
            ).fetchall()
        }

        values = {"interview_score": interview_score}

        if "education_score" in application_columns:
            values["education_score"] = education_score

        assignments = ", ".join(
            f'"{column}" = ?' for column in values
        )

        conn.execute(
            f"""
            UPDATE applications
            SET {assignments}
            WHERE id = ?
            """,
            (*values.values(), application_id),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        app.logger.exception(
            "Could not save interview scores for application %s",
            application_id,
        )
        return False

    finally:
        conn.close()

    # Prepare the record expected by the existing matcher.
    standard_answers = {}

    for number in range(1, 6):
        row = answers_by_number[number]

        standard_answers[f"q{number}"] = {
            "question": row["question"] or "",
            "answer": row["answer"] or "",
            "score": row["score"],
            "max_score": 2,
            "feedback": row["quality"] or "",
        }

    education_assessment = _parse_interview_json(
        interview["education_assessment_json"]
        if "education_assessment_json" in interview.keys()
        else None
    )

    record = {
        "candidate_id": str(application["candidate_id"]),
        "vacancy_id": str(application["vacancy_id"]),
        "candidate_file": application["resume_path"],
        "interview_answers": standard_answers,
        "education_answer": (
            education_row["answer"] if education_row else ""
        ),
        "education_assessment": education_assessment or None,
        "experience_answer": (
            answers_by_number[7]["answer"]
            if 7 in answers_by_number
            else ""
        ),
        "candidate_reported_yoe": (
            interview["candidate_reported_yoe"]
            if "candidate_reported_yoe" in interview.keys()
            else None
        ),
        "interview_score_10": interview_score,
        "interview_completed": True,
    }

    try:
        from app.services.interview_routes import recalculate_matching

        # recalculate_matching() reads these with .get(), so pass
        # plain dictionaries (dict() also accepts sqlite3.Row objects).
        recalculate_matching(dict(application), dict(vacancy), record)

    except Exception:
        app.logger.exception(
            "Final matching recalculation failed for application %s",
            application_id,
        )

        conn = sqlite3.connect(str(DB_PATH), timeout=10)

        try:
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(applications)"
                ).fetchall()
            }

            if "matching_status" in columns:
                conn.execute(
                    """
                    UPDATE applications
                    SET matching_status = 'failed'
                    WHERE id = ?
                    """,
                    (application_id,),
                )
                conn.commit()

        finally:
            conn.close()

        # The interview answers and score are saved, but matching failed.
        # Do not publish the application as fully completed.
        return False

    # Matching succeeded; now mark the interview completed.
    update_interview_progress(
        interview_id=interview_id,
        completed_questions=len(answers_by_number),
        status="Completed",
        overall_score=interview_score,
        completed_at=completed_at,
    )

    return True

    """
    Publish the final interview score and recalculate matching only
    when the candidate has submitted all required answers and their
    assessments have finished.
    """

    application = get_application_by_id(application_id)
    interview = get_interview_by_id(interview_id)

    if not application or not interview:
        return False

    status = str(interview["status"] or "").strip().lower()

    # The candidate must explicitly submit the completed interview.
    if status != "scoring":
        return False

    vacancy = get_vacancy_by_id(application["vacancy_id"])

    if not vacancy:
        return False

    required = _required_verification_numbers(application, vacancy)

    if required is None:
        return False

    saved_answers = get_interview_answers(interview_id)

    answers_by_number = {
        int(row["question_number"]): row
        for row in saved_answers
        if row["question_number"] is not None
    }

    # Every required answer must exist and its assessment must finish.
    for number in required:
        row = answers_by_number.get(number)

        if not row:
            return False

        assessment_status = str(
            row["assessment_status"] or ""
        ).lower()

        if assessment_status != "complete":
            return False

        # All five standard questions need actual numeric scores.
        if number <= 5 and row["score"] is None:
            return False

  


def save_candidate_interview_answer(application_token):

    # --------------------------------------------------------
    # Save answer first — do not wait for AI scoring
    # --------------------------------------------------------

    save_interview_answer(
        interview_id=interview["id"],
        question_number=question_number,
        question=question,
        category=question_type,
        answer=answer,
        score=None,
        quality=None,
    )

    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    try:
        conn.execute(
            """
            UPDATE interview_answers
            SET assessment_status = 'pending'
            WHERE interview_id = ?
              AND question_number = ?
              AND answer = ?
            """,
            (interview["id"], question_number, answer),
        )
        conn.commit()

    finally:
        conn.close()

    # --------------------------------------------------------
    # Launch assessment in the background
    # --------------------------------------------------------

    Thread(
        target=_assess_candidate_answer_background,
        args=(
            application["id"],
            interview["id"],
            question_number,
            question,
            question_type,
            answer,
        ),
        daemon=True,
    ).start()

    # --------------------------------------------------------
    # Count saved answers and return immediately
    # --------------------------------------------------------

    saved_answers = get_interview_answers(interview["id"])

    completed_questions = len({
        row["question_number"]
        for row in saved_answers
        if str(row["answer"] or "").strip()
    })

    update_interview_progress(
        interview_id=interview["id"],
        completed_questions=completed_questions,
    )

    return jsonify({
        "success": True,
        "saved": True,
        "scoring_pending": True,
        "completed_questions": completed_questions,
    })




 
def get_candidate_verification_questions(application_token):

    application = get_application_by_public_token(application_token)

    if not application:
        return jsonify({
            "success": False,
            "message": "Application not found."
        }), 404

    interview = get_interview_by_application(application["id"])

    if not interview:
        return jsonify({
            "success": False,
            "message": "Interview has not been started."
        }), 400

    answers = _get_saved_interview_answers(interview["id"])

    # --------------------------------------------------------
    # Core interview must be completed first
    # --------------------------------------------------------

    core_complete = all(
        str(answers.get(f"q{i}", "")).strip()
        for i in range(1, 6)
    )

    if not core_complete:
        return jsonify({
            "success": True,
            "ready": False,
            "questions": [],
            "message": "Please complete the core interview first."
        })

    # --------------------------------------------------------
    # CV processing may still be running.
    #
    # IMPORTANT:
    # We intentionally do not expose pipeline details
    # to the candidate.
    # --------------------------------------------------------

    pipeline_status = str(
        application["pipeline_status"] or ""
    ).lower().strip()

    if pipeline_status not in ("completed", "complete", "success"):

        return jsonify({
            "success": True,
            "ready": False,
            "questions": [],
           "message": "Please continue shortly."
        })

    # --------------------------------------------------------
    # Load structured JD and CV
    # --------------------------------------------------------

    structured_cv = {}

    if application["structured_cv"]:
        try:
            structured_cv = json.loads(
                application["structured_cv"]
            )
        except Exception:
            structured_cv = {}

    vacancy = get_vacancy_by_id(application["vacancy_id"])

    structured_jd = {}

    if vacancy and vacancy["jd_structured_data"]:
        try:
            structured_jd = json.loads(
                vacancy["jd_structured_data"]
            )
        except Exception:
            structured_jd = {}

    verification_questions = []

    # ========================================================
    # EDUCATION VERIFICATION
    # ========================================================

    jd_education = structured_jd.get("education")

    cv_education = structured_cv.get("education")

    has_jd_education = bool(
        str(jd_education or "").strip()
    )

    has_cv_education = bool(
        str(cv_education or "").strip()
    )

    if has_jd_education and not has_cv_education:

        verification_questions.append({
            "id": "v1",
            "type": "education_verification",
            "question": (
               "What is your highest completed degree and field of study?"
            )
        })

    # ========================================================
    # EXPERIENCE VERIFICATION
    # ========================================================

    jd_experience = structured_jd.get("experience")

    cv_experience = structured_cv.get("experience")

    has_jd_experience = bool(
        str(jd_experience or "").strip()
    )

    has_cv_experience = bool(
        str(cv_experience or "").strip()
    )

    if has_jd_experience and not has_cv_experience:

        verification_questions.append({
            "id": "v2",
            "type": "experience_verification",
            "question": (
               "How many years of relevant work experience do you have?"
            )
        })

    # --------------------------------------------------------
    # Determine current verification question
    # --------------------------------------------------------

    current_question_index = 0

    for index, question in enumerate(verification_questions):

        if not str(
            answers.get(question["id"], "")
        ).strip():

            current_question_index = index
            break
    else:
        current_question_index = len(verification_questions)

    return jsonify({
        "success": True,
        "ready": True,
        "questions": verification_questions,
        "answers": answers,
        "current_question_index": current_question_index
    })


 
def complete_candidate_verification(application_token):

    application = get_application_by_public_token(application_token)

    if not application:
        return jsonify({
            "success": False,
            "message": "Application not found."
        }), 404

    interview = get_interview_by_application(application["id"])

    if not interview:
        return jsonify({
            "success": False,
            "message": "Interview has not been started."
        }), 400

    answers = _get_saved_interview_answers(interview["id"])

    # Verification is allowed to have:
    # - no questions
    # - education only
    # - experience only
    # - both

    return jsonify({
        "success": True,
        "verification_completed": True,
        "answers": answers
    })



def complete_candidate_interview(application_token):
    application = get_application_by_public_token(application_token)

    if not application:
        return jsonify({
            "success": False,
            "message": "Application not found."
        }), 404

    interview = get_interview_by_application(application["id"])

    if not interview:
        return jsonify({
            "success": False,
            "message": "Interview has not been started."
        }), 400

    status = str(interview["status"] or "").strip().lower()

    if status == "completed":
        return jsonify({
            "success": True,
            "interview_completed": True,
            "scoring_pending": False,
        })

    if status == "finalizing":
        return jsonify({
            "success": True,
            "interview_completed": True,
            "scoring_pending": True,
        })

    vacancy = get_vacancy_by_id(application["vacancy_id"])

    if not vacancy:
        return jsonify({
            "success": False,
            "message": "Vacancy not found."
        }), 404

    required = _required_verification_numbers(application, vacancy)

    if required is None:
        return jsonify({
            "success": False,
            "message": "Your interview questions are not ready yet. Please try again."
        }), 409

    saved_answers = get_interview_answers(interview["id"])

    answers_by_number = {
        int(row["question_number"]): row
        for row in saved_answers
        if row["question_number"] is not None
    }

    missing = [
        number for number in sorted(required)
        if number not in answers_by_number
        or not str(
            answers_by_number[number]["answer"] or ""
        ).strip()
    ]

    if missing:
        return jsonify({
            "success": False,
            "message": "Please answer all interview questions first."
        }), 409

    # All answers exist. Assessments may still be running.
    update_interview_progress(
        interview_id=interview["id"],
        completed_questions=len(answers_by_number),
        status="Scoring",
        overall_score=None,
    )

    # Attempt finalization in the background, so this endpoint does not
    # make the candidate wait for matching to finish.
    Thread(
        target=_try_finalize_candidate_interview,
        args=(application["id"], interview["id"]),
        daemon=True,
    ).start()

    return jsonify({
        "success": True,
        "interview_completed": True,
        "scoring_pending": True,
        "message": "Your interview answers have been submitted successfully.",
    })


if __name__ == "__main__":
    print("=" * 60)
    print("ResumeMatch AI")
    print("=" * 60)
    print("Project root:", PROJECT_ROOT)
    print("Database:", DB_PATH)
    print("Login exists:", (HTML_FOLDER / "login.html").exists())
    print("Signup exists:", (HTML_FOLDER / "signup.html").exists())
    print("Dashboard exists:", (HTML_FOLDER / "dashboard.html").exists())
    print("Vacancies exists:", (HTML_FOLDER / "vacancies.html").exists())
    print("Create Vacancy exists:", (HTML_FOLDER / "create_vacancy.html").exists())
    print("Candidate Apply exists:", (HTML_FOLDER / "candidate_apply.html").exists())
    print("Candidate Interview exists:", (HTML_FOLDER / "candidate_interview.html").exists())
    print("=" * 60)

    app.config["TEMPLATES_AUTO_RELOAD"] = True

    Timer(1, open_browser).start()

    app.run(
        host="127.0.0.1",
        port=5050,
        debug=True,
        use_reloader=False
    )