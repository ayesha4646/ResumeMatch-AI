from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
import sys
from flask import Blueprint, current_app, jsonify, request, session

from src.database import get_connection
from app.services.interview_chatbot import (
    ChatbotServiceError,
    start_interview,
    submit_answer,
)


interview_api = Blueprint("interview_api", __name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_MATCHER = None
_EMBEDDER = None


# ============================================================
# APPLICATION AND VACANCY
# ============================================================

def application_context(token: str):
    """Find an application using applications.public_token."""
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT
                a.*,
                c.full_name AS candidate_name,
                c.email AS candidate_email
            FROM applications AS a
            JOIN candidates AS c ON c.id = a.candidate_id
            WHERE a.public_token = ?
            LIMIT 1
            """,
            (token,),
        ).fetchone()

        if not row:
            return None, None

        application = dict(row)

        vacancy_row = conn.execute(
            """
            SELECT *
            FROM vacancies
            WHERE id = ?
            LIMIT 1
            """,
            (application["vacancy_id"],),
        ).fetchone()

        vacancy = dict(vacancy_row) if vacancy_row else None
        return application, vacancy

    finally:
        conn.close()


def structured_jd(vacancy: dict) -> dict:
    """Prefer the Gemini-structured JD saved to the vacancy."""
    raw = vacancy.get("jd_structured_data")

    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw

            if isinstance(data, dict):
                data.setdefault("job_title", vacancy.get("job_title", ""))
                return data

        except (json.JSONDecodeError, TypeError):
            pass

    # Basic fallback only. Structured JD data is preferred.
    return {
        "job_title": vacancy.get("job_title", ""),
        "summary": vacancy.get("description", ""),
        "skills": vacancy.get("required_skills") or [],
        "experience": vacancy.get("experience") or [],
        "education": [],
        "responsibilities": vacancy.get("responsibilities") or [],
        "location": vacancy.get("location") or "",
    }


def load_application_row(application_id: int):
    """
    Reload one application straight from the database.

    Used so that final matching always sees the CURRENT state (for example a
    structured CV that was saved while the request was already running),
    never a copy loaded earlier in the request.
    """
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM applications
            WHERE id = ?
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


# ============================================================
# HR QUESTION CONFIGURATION
# ============================================================

def get_question_config(vacancy_id: int):
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

        if not row:
            return None

        try:
            config = json.loads(row["questions_json"])
            return config if isinstance(config, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    finally:
        conn.close()


# ============================================================
# LOAD AND SAVE INTERVIEW SESSION
# ============================================================

def load_session(application_id: int):
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM interviews
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

        if not row:
            return None, None

        interview = dict(row)

        try:
            data = json.loads(interview.get("session_json") or "")
        except (json.JSONDecodeError, TypeError):
            data = None

        return interview, data if isinstance(data, dict) else None

    finally:
        conn.close()


def save_session(
    interview_id: int,
    application_id: int,
    data: dict,
):
    answers = data.get("answers", {})
    response = data.get("response_record") or {}
    education = data.get("education_assessment")

    status = "Completed" if data.get("completed") else "In Progress"

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE interviews
            SET
                session_json = ?,
                total_questions = ?,
                completed_questions = ?,
                overall_score = ?,
                status = ?,
                education_assessment_json = ?,
                candidate_reported_yoe = ?,
                experience_answer = ?,
                completed_at = CASE
                    WHEN ? = 'Completed'
                    THEN COALESCE(completed_at, ?)
                    ELSE completed_at
                END
            WHERE id = ? AND application_id = ?
            """,
            (
                json.dumps(data, ensure_ascii=False),
                len(data.get("questions", [])),
                len(answers),
                response.get("interview_score_10"),
                status,
                json.dumps(education, ensure_ascii=False) if education else None,
                data.get("candidate_reported_yoe"),
                data.get("experience_answer"),
                status,
                datetime.now().isoformat(),
                interview_id,
                application_id,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def save_answer(
    interview_id: int,
    question_id: str,
    data: dict,
):
    item = data.get("answers", {}).get(question_id)

    if not item:
        raise ValueError("The answer was not found in the interview session.")

    question_number = next(
        (
            index + 1
            for index, question in enumerate(data.get("questions", []))
            if question.get("id") == question_id
        ),
        None,
    )

    conn = get_connection()

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM interview_answers
            WHERE interview_id = ? AND question_id = ?
            LIMIT 1
            """,
            (interview_id, question_id),
        ).fetchone()

        values = (
            question_number,
            item.get("question", ""),
            item.get("type", "interview"),
            item.get("answer", ""),
            item.get("score"),
            item.get("feedback", ""),
        )

        if existing:
            conn.execute(
                """
                UPDATE interview_answers
                SET
                    question_number = ?,
                    question = ?,
                    category = ?,
                    answer = ?,
                    score = ?,
                    quality = ?
                WHERE id = ?
                """,
                (*values, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO interview_answers (
                    interview_id,
                    question_id,
                    question_number,
                    question,
                    category,
                    answer,
                    score,
                    quality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interview_id, question_id, *values),
            )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# CANDIDATE-SAFE RESPONSE
# Never expose assessment scores to candidates.
# ============================================================

def public_state(data: dict) -> dict:
    questions = data.get("questions", [])
    answers = data.get("answers", {})

    verification = [
        question
        for question in questions
        if question.get("type") in {
            "education_verification",
            "experience_verification",
        }
    ]

    standard = [
        question for question in questions
        if question.get("type") == "interview"
    ]

    pending_verification = [
        question for question in verification
        if question["id"] not in answers
    ]

    verification_answers = sum(
        question["id"] in answers for question in verification
    )

    standard_answers = sum(
        question["id"] in answers for question in standard
    )

    return {
        "success": True,
        "questions": [
            {
                "id": question["id"],
                "type": question["type"],
                "question": question["question"],
            }
            for question in standard
        ],
        "verification_questions": [
            {
                "id": question["id"],
                "type": question["type"],
                "question": question["question"],
            }
            for question in verification
        ],
        "answers": {
            key: value.get("answer", "")
            for key, value in answers.items()
        },
        "current_question_index": standard_answers,
        "verification_index": verification_answers,
        "phase": "verification" if pending_verification else "standard",
        "interview_completed": bool(data.get("completed")),
        "total_questions": len(questions),
    }


# ============================================================
# START OR RESTORE INTERVIEW
# POST /api/applications/<token>/interview/start
# ============================================================


@interview_api.post("/api/applications/<token>/interview/start")
def interview_start(token):
    application, vacancy = application_context(token)

    if not application or not vacancy:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    interview, data = load_session(application["id"])

    # Keep interviews that already have answers or are completed.
    if data and (data.get("answers") or data.get("completed")):
        return jsonify(public_state(data))

    jd = structured_jd(vacancy)

    if not jd.get("job_title"):
        return jsonify(
            success=False,
            message="This vacancy is not ready for an interview.",
        ), 409

    data = start_interview(
        candidate_id=str(application["candidate_id"]),
        vacancy_id=str(vacancy["id"]),
        jd=jd,
        candidate_name=application.get("candidate_name", ""),
        candidate_file=f"application_{application['id']}.json",
        question_config=get_question_config(vacancy["id"]),
    )

    now = datetime.now().isoformat()
    conn = get_connection()

    try:
        if interview:
            interview_id = interview["id"]

            conn.execute(
                """
                UPDATE interviews
                SET
                    session_json = ?,
                    total_questions = ?,
                    completed_questions = 0,
                    status = 'In Progress',
                    started_at = COALESCE(started_at, ?)
                WHERE id = ? AND application_id = ?
                """,
                (
                    json.dumps(data, ensure_ascii=False),
                    len(data["questions"]),
                    now,
                    interview_id,
                    application["id"],
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO interviews (
                    application_id,
                    total_questions,
                    completed_questions,
                    overall_score,
                    status,
                    started_at,
                    session_json
                )
                VALUES (?, ?, 0, NULL, 'In Progress', ?, ?)
                """,
                (
                    application["id"],
                    len(data["questions"]),
                    now,
                    json.dumps(data, ensure_ascii=False),
                ),
            )

            interview_id = cursor.lastrowid

        conn.execute(
            """
            UPDATE applications
            SET application_status = 'Interview In Progress'
            WHERE id = ?
            """,
            (application["id"],),
        )

        conn.commit()

    finally:
        conn.close()

    return jsonify(public_state(data))


# ============================================================
# SAVE ONE ANSWER
# POST /api/applications/<token>/interview/answer
# ============================================================

@interview_api.post("/api/applications/<token>/interview/answer")
def interview_answer(token):
    application, vacancy = application_context(token)

    if not application or not vacancy:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    interview, data = load_session(application["id"])

    if not interview or not data:
        return jsonify(
            success=False,
            message="Start the interview first.",
        ), 409

    if data.get("completed"):
        return jsonify(
            success=False,
            message="This interview is already complete.",
        ), 409

    body = request.get_json(silent=True) or {}
    question_id = str(body.get("question_id") or "").strip()
    answer = str(body.get("answer") or "").strip()

    if not question_id or not answer or len(answer) > 1500:
        return jsonify(
            success=False,
            message="Enter a non-empty answer of up to 1500 characters.",
        ), 400

    question = next(
        (
            item for item in data.get("questions", [])
            if item.get("id") == question_id
        ),
        None,
    )

    if not question:
        return jsonify(
            success=False,
            message="Invalid interview question.",
        ), 400

    if question.get("type") == "interview":
        pending_verification = [
            item for item in data.get("questions", [])
            if item.get("type") in {
                "education_verification",
                "experience_verification",
            }
            and item.get("id") not in data.get("answers", {})
        ]

        if pending_verification:
            return jsonify(
                success=False,
                message="Complete the verification questions first.",
            ), 409

    previous = data.get("answers", {}).get(question_id)

    if previous:
        if previous.get("answer") == answer:
            return jsonify(success=True, saved=True)
        return jsonify(
            success=False,
            message="This question already has a saved answer.",
        ), 409

    try:
        result = submit_answer(data, question_id, answer)
        data = result["session"]

        save_answer(interview["id"], question_id, data)
        save_session(interview["id"], application["id"], data)

        return jsonify(
            success=True,
            saved=True,
            completed=bool(data.get("completed")),
        )

    except ValueError as error:
        return jsonify(
            success=False,
            message=str(error),
        ), 400

    except ChatbotServiceError:
        current_app.logger.exception("Chatbot assessment failed")
        return jsonify(
            success=False,
            message="We could not assess your answer. Please try again.",
        ), 502

    except Exception:
        current_app.logger.exception("Saving interview answer failed")
        return jsonify(
            success=False,
            message="Your answer could not be saved. Please try again.",
        ), 500


# ============================================================
# VERIFICATION QUESTIONS
# GET /api/applications/<token>/interview/verification
# ============================================================

@interview_api.get("/api/applications/<token>/interview/verification")
def interview_verification(token):
    application, vacancy = application_context(token)

    if not application or not vacancy:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    interview, data = load_session(application["id"])

    if not interview or not data:
        return jsonify(
            success=False,
            message="Interview session not found.",
        ), 404

    answers = data.get("answers", {})

    pending = [
        {
            "id": question["id"],
            "type": question["type"],
            "question": question["question"],
        }
        for question in data.get("questions", [])
        if question.get("type") in {
            "education_verification",
            "experience_verification",
        }
        and question["id"] not in answers
    ]

    return jsonify(
        success=True,
        ready=True,
        questions=pending,
        answers={
            key: value.get("answer", "")
            for key, value in answers.items()
        },
        current_question_index=0,
    )


# ============================================================
# VERIFY REQUIRED QUESTIONS ARE COMPLETE
# POST /api/applications/<token>/interview/verification/complete
# ============================================================

@interview_api.post(
    "/api/applications/<token>/interview/verification/complete"
)
def interview_verification_complete(token):
    application, vacancy = application_context(token)

    if not application or not vacancy:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    interview, data = load_session(application["id"])

    if not interview or not data:
        return jsonify(
            success=False,
            message="Interview session not found.",
        ), 404

    answers = data.get("answers", {})

    pending = [
        question["id"]
        for question in data.get("questions", [])
        if question.get("type") in {
            "education_verification",
            "experience_verification",
        }
        and question["id"] not in answers
    ]

    if pending:
        return jsonify(
            success=False,
            message="Answer all required verification questions first.",
        ), 409

    return jsonify(success=True, next_phase="standard")


# ============================================================
# LOAD THE MATCHING SCRIPT
# ============================================================


def load_matcher():
    global _MATCHER, _EMBEDDER

    if _MATCHER is not None:
        return _MATCHER, _EMBEDDER

    configured_path = os.getenv("RESUMEMATCH_MATCHER_PATH", "").strip()

    if configured_path:
        possible_paths = [Path(configured_path).expanduser()]
    else:
        possible_paths = [
            PROJECT_ROOT / "scripts" / "match_resumes.py",
            PROJECT_ROOT / "ResumeMatch_AI_V21_2_Final_Matching.py",
            PROJECT_ROOT / "scripts" / "ResumeMatch_AI_V21_2_Final_Matching.py",
        ]

    path = next(
        (item.resolve() for item in possible_paths if item.is_file()),
        None,
    )

    if path is None:
        raise FileNotFoundError(
            "Matching script not found. Expected "
            "'scripts/match_resumes.py' in the project."
        )

    spec = importlib.util.spec_from_file_location(
        "resumematch_final_matcher",
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load matching script: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "Embedder") or not hasattr(module, "EMBED_MODEL"):
        raise AttributeError(
            f"The matching script has no Embedder or EMBED_MODEL: {path}"
        )

    if not hasattr(module, "match_one"):
        raise AttributeError(
            f"The matching script has no match_one() function: {path}"
        )

    _MATCHER = module
    _EMBEDDER = module.Embedder(module.EMBED_MODEL)

    return _MATCHER, _EMBEDDER


# ============================================================
# FINAL MATCHING AND VACANCY-SPECIFIC RANKING
# ============================================================

def recalculate_matching(
    application,
    vacancy,
    response_record,
    *,
    final_assessment=True,
):
    raw_cv = application.get("structured_cv")

    if not raw_cv:
        original_path = application.get("resume_path") or ""
        path = Path(original_path)

        if path.suffix.lower() == ".json" and path.is_file():
            raw_cv = path.read_text(encoding="utf-8")

    if not raw_cv:
        conn = get_connection()

        try:
            conn.execute(
                """
                UPDATE applications
                SET matching_status = 'pending_cv_processing'
                WHERE id = ?
                """,
                (application["id"],),
            )
            conn.commit()
        finally:
            conn.close()

        return

    if isinstance(raw_cv, dict):
        resume = raw_cv
    else:
        try:
            resume = json.loads(raw_cv)
        except (json.JSONDecodeError, TypeError):
            path = Path(str(raw_cv))

            if not path.is_absolute():
                path = PROJECT_ROOT / path

            if not path.is_file() or path.suffix.lower() != ".json":
                raise ValueError(
                    "structured_cv must contain JSON or a valid JSON path."
                )

            resume = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(resume, dict):
        raise ValueError("Structured CV must be a JSON object.")

    matcher, embedder = load_matcher()

    result = matcher.match_one(
        structured_jd(vacancy),
        resume,
        f"application_{application['id']}.json",
        embedder,
        response_record,
    )

    # Save preliminary CV results without creating a final assessment.
    if not final_assessment:
        result["assessment_stage"] = "preliminary_cv"
        result["is_provisional"] = True
        result["final_score"] = None
        result["interview_score"] = None

        conn = get_connection()

        try:
            # A provisional result must never overwrite a final result or
            # a pending-final marker. If the interview finished (or was
            # parked as pending_cv_processing) while this preliminary
            # matching was running, the row is left untouched.
            conn.execute(
                """
                UPDATE applications
                SET
                    cv_match_score = ?,
                    skills_score = ?,
                    experience_score = ?,
                    match_explanation = ?,
                    match_result_json = ?,
                    matching_status = 'preliminary_completed'
                WHERE id = ? AND vacancy_id = ?
                  AND LOWER(COALESCE(matching_status, '')) NOT IN (
                      'completed',
                      'pending_education_assessment',
                      'pending_cv_processing'
                  )
                """,
                (
                    result.get("cv_score"),
                    result.get("skills_score"),
                    result.get("experience_score"),
                    result.get("plain_language_explanation", ""),
                    json.dumps(result, ensure_ascii=False, default=str),
                    application["id"],
                    vacancy["id"],
                ),
            )

            conn.commit()

        finally:
            conn.close()

        return result

    # The existing final-scoring logic continues below.
    final_score = result.get("final_score")

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE applications
            SET
                cv_match_score = ?,
                match_score = ?,
                skills_score = ?,
                experience_score = ?,
                education_score = ?,
                grade = ?,
                eligibility = ?,
                match_explanation = ?,
                match_result_json = ?,
                matching_status = ?
            WHERE id = ? AND vacancy_id = ?
            """,
            (
                result.get("cv_score"),
                final_score,
                result.get("skills_score"),
                result.get("experience_score"),
                result.get("education_score"),
                result.get("grade_name"),
                result.get("eligibility"),
                result.get("plain_language_explanation", ""),
                json.dumps(result, ensure_ascii=False, default=str),
                (
                    "completed"
                    if final_score is not None
                    else "pending_education_assessment"
                ),
                application["id"],
                vacancy["id"],
            ),
        )

        # Every vacancy has its own candidate ranking.
        conn.execute(
            "UPDATE applications SET rank = NULL WHERE vacancy_id = ?",
            (vacancy["id"],),
        )

        ranked = conn.execute(
            """
            SELECT id
            FROM applications
            WHERE vacancy_id = ? AND match_score IS NOT NULL
            ORDER BY
                CASE eligibility
                    WHEN 'eligible' THEN 2
                    WHEN 'needs_verification' THEN 1
                    ELSE 0
                END DESC,
                match_score DESC,
                COALESCE(skills_score, 0) DESC,
                COALESCE(experience_score, 0) DESC,
                id ASC
            """,
            (vacancy["id"],),
        ).fetchall()

        for position, row in enumerate(ranked, start=1):
            conn.execute(
                "UPDATE applications SET rank = ? WHERE id = ?",
                (position, row["id"]),
            )

        conn.commit()

    finally:
        conn.close()

def recalculate_preliminary_matching(application_id, vacancy_id):
    """Calculate and save CV-only results before the AI interview."""

    conn = get_connection()

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

        if not application_row:
            raise LookupError(
                f"Application {application_id} was not found."
            )

        if not vacancy_row:
            raise LookupError(
                f"Vacancy {vacancy_id} was not found."
            )

        application = dict(application_row)
        vacancy = dict(vacancy_row)

    finally:
        conn.close()

    # Never run preliminary matching over a completed interview result.
    status = str(
        application.get("application_status") or ""
    ).strip().casefold()

    if status == "interview completed":
        return None

    try:
        return recalculate_matching(
            application,
            vacancy,
            {},
            final_assessment=False,
        )

    except Exception:
        conn = get_connection()

        try:
            conn.execute(
                """
                UPDATE applications
                SET matching_status = 'failed'
                WHERE id = ? AND vacancy_id = ?
                """,
                (application_id, vacancy_id),
            )

            conn.commit()

        finally:
            conn.close()

        raise


def run_final_matching_when_ready(application_id, vacancy, record):
    """
    Run the existing final matching for a completed interview, safely
    regardless of whether CV processing has finished.

    * The application is reloaded from the database first, so a structured
      CV saved while the request was running is used.
    * If the CV is still missing, recalculate_matching() parks the row as
      'pending_cv_processing' (unchanged behavior). The check afterwards
      closes the narrow window where the CV was saved right after that:
      the application is reloaded once more and, if the CV is now there,
      final matching runs again. If the CV is saved even later, the
      post-CV check in process_application_background() (server.py) sees
      the parked status and the completed interview and resumes it.
    * A final result that already exists is never recalculated.
    """

    def _mark_failed():
        conn = get_connection()

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

    try:
        application = load_application_row(application_id)

        if not application:
            return

        recalculate_matching(application, vacancy, record)

        # Re-check: did the CV finish while we were parking the result?
        application = load_application_row(application_id)

        if not application:
            return

        matching_status = str(
            application.get("matching_status") or ""
        ).strip().lower()

        if (
            matching_status == "pending_cv_processing"
            and application.get("structured_cv")
        ):
            recalculate_matching(application, vacancy, record)

    except Exception:
        current_app.logger.exception(
            "Final matching failed for application %s",
            application_id,
        )

        _mark_failed()


# ============================================================
# COMPLETE INTERVIEW
# POST /api/applications/<token>/interview/complete
# ============================================================

@interview_api.post("/api/applications/<token>/interview/complete")
def interview_complete(token):
    application, vacancy = application_context(token)

    if not application or not vacancy:
        return jsonify(
            success=False,
            message="Application not found.",
        ), 404

    interview, data = load_session(application["id"])

    if not interview or not data or not data.get("completed"):
        return jsonify(
            success=False,
            message="Complete all interview questions first.",
        ), 409

    # Already finalized (for example, the candidate reloaded the page and
    # submitted again): keep the existing result and ranking untouched.
    current_application = load_application_row(application["id"])

    if (
        current_application
        and str(
            current_application.get("matching_status") or ""
        ).strip().lower() == "completed"
    ):
        return jsonify(
            success=True,
            interview_completed=True,
            message="Your interview has been submitted successfully.",
        )

    record = data.get("response_record") or {}
    education = record.get("education_assessment") or {}
    interview_score = record.get("interview_score_10")

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE applications
            SET
                interview_score = ?,
                education_score = ?,
                application_status = 'Interview Completed'
            WHERE id = ?
            """,
            (
                interview_score,
                education.get("score"),
                application["id"],
            ),
        )

        conn.execute(
            """
            UPDATE interviews
            SET
                overall_score = ?,
                education_assessment_json = ?,
                candidate_reported_yoe = ?,
                experience_answer = ?,
                status = 'Completed',
                completed_at = COALESCE(completed_at, ?),
                session_json = ?
            WHERE id = ? AND application_id = ?
            """,
            (
                interview_score,
                json.dumps(education, ensure_ascii=False),
                record.get("candidate_reported_yoe"),
                record.get("experience_answer", ""),
                datetime.now().isoformat(),
                json.dumps(data, ensure_ascii=False),
                interview["id"],
                application["id"],
            ),
        )

        conn.commit()

    finally:
        conn.close()

    # Interview answers and completion are now saved. Final matching uses the
    # CURRENT application row and parks as pending_cv_processing if the
    # structured CV is not available yet (resumed after CV processing).
    run_final_matching_when_ready(application["id"], vacancy, record)

    # Never return marks, eligibility, or matching explanations to candidates.
    return jsonify(
        success=True,
        interview_completed=True,
        message="Your interview has been submitted successfully.",
    )


# ============================================================
# HR QUESTION SETTINGS
# GET/POST /api/vacancies/<id>/interview-settings
# ============================================================

# ============================================================
# HR QUESTION SETTINGS
# GET/POST/DELETE /api/vacancies/<id>/interview-settings
# ============================================================

@interview_api.route(
    "/api/vacancies/<int:vacancy_id>/interview-settings",
    methods=["GET", "POST", "DELETE"],
)
def interview_settings(vacancy_id):
    if "user_id" not in session or session.get("role") != "hr":
        return jsonify(
            success=False,
            message="Authentication required.",
        ), 401

    conn = get_connection()

    try:
        vacancy = conn.execute(
            """
            SELECT id, created_by
            FROM vacancies
            WHERE id = ?
            """,
            (vacancy_id,),
        ).fetchone()

        if (
            not vacancy
            or int(vacancy["created_by"]) != int(session["user_id"])
        ):
            return jsonify(
                success=False,
                message="Vacancy not found.",
            ), 404

        # LOAD SAVED QUESTIONS
        if request.method == "GET":
            row = conn.execute(
                """
                SELECT questions_json
                FROM vacancy_interview_settings
                WHERE vacancy_id = ?
                """,
                (vacancy_id,),
            ).fetchone()

            try:
                config = json.loads(row["questions_json"]) if row else None
            except (json.JSONDecodeError, TypeError):
                config = None

            return jsonify(
                success=True,
                question_config=config,
            )

        # RESET THIS VACANCY TO BUILT-IN DEFAULTS
        if request.method == "DELETE":
            conn.execute(
                """
                DELETE FROM vacancy_interview_settings
                WHERE vacancy_id = ?
                """,
                (vacancy_id,),
            )
            conn.commit()

            return jsonify(
                success=True,
                message="Questions reset to default.",
            )

        # SAVE EDITED QUESTION TEXT
        body = request.get_json(silent=True) or {}
        questions = body.get("questions")

        if questions is not None:
            if not isinstance(questions, list) or len(questions) != 5:
                return jsonify(
                    success=False,
                    message="Exactly five interview questions are required.",
                ), 400

            cleaned_questions = []

            for index, item in enumerate(questions, start=1):
                if not isinstance(item, str):
                    return jsonify(
                        success=False,
                        message=f"Question {index} must be text.",
                    ), 400

                question_text = item.strip()

                if not question_text:
                    return jsonify(
                        success=False,
                        message=f"Question {index} cannot be empty.",
                    ), 400

                if len(question_text) > 500:
                    return jsonify(
                        success=False,
                        message=f"Question {index} must be 500 characters or fewer.",
                    ), 400

                cleaned_questions.append({
                    "id": f"hr_saved_question_{index}",
                    "question": question_text,
                })

            # The current question resolver already understands this format.
            config = {
                "selected_ids": cleaned_questions,
                "custom_questions": [],
            }

        else:
            # Retain compatibility with the previous question-selection API.
            config = {
                "selected_ids": body.get("selected_ids", []),
                "custom_questions": body.get("custom_questions", []),
            }

            if (
                not isinstance(config["selected_ids"], list)
                or not isinstance(config["custom_questions"], list)
            ):
                return jsonify(
                    success=False,
                    message="Question selections must be lists.",
                ), 400

        conn.execute(
            """
            INSERT INTO vacancy_interview_settings (
                vacancy_id,
                questions_json,
                updated_by
            )
            VALUES (?, ?, ?)
            ON CONFLICT(vacancy_id)
            DO UPDATE SET
                questions_json = excluded.questions_json,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                vacancy_id,
                json.dumps(config, ensure_ascii=False),
                session.get("user_id"),
            ),
        )

        conn.commit()

        return jsonify(
            success=True,
            message="Interview questions saved successfully.",
        )

    finally:
        conn.close()