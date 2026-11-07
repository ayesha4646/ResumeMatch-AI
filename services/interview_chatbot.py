"""
ResumeMatch AI — Chatbot Service

Responsibilities:
- Ask JD-required education and experience verification questions.
- Assess education using Gemini, out of 10 marks.
- Collect experience answers without scoring experience.
- Ask five interview questions, each scored out of 2.
- Return structured results for the matching system.

Flask routes, database persistence, and page UI are integrated separately.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")



# ============================================================
# DEFAULT INTERVIEW QUESTIONS
# ============================================================

DEFAULT_QUESTIONS = [
    {
        "id": "q1_strength",
        "question": "What is your biggest strength?",
    },
    {
        "id": "q2_weakness",
        "question": "What is one weakness you are improving?",
    },
    {
        "id": "q3_project",
        "question": "What project are you most proud of?",
    },
    {
        "id": "q4_experience",
        "question": "How do you handle disagreements with others?",
    },
    {
        "id": "q5_skills",
        "question": "What skills have you used in your projects or work?",
    },
]

# ============================================================
# PREDEFINED FIELD-RELATED QUESTIONS FOR HR
# ============================================================

# These are interview questions, not matching-score rules.
# HR can select these questions and add custom questions.

QUESTION_BANK: dict[str, list[tuple[str, str]]] = {}


class ChatbotServiceError(RuntimeError):
    """Chatbot configuration, API, or response error."""


# ============================================================
# BASIC UTILITIES
# ============================================================

def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _flat(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [
            x.strip()
            for x in re.split(r"[\n;|]+", value)
            if x.strip()
        ]

    if isinstance(value, dict):
        return [
            _text(x)
            for x in value.values()
            if _text(x)
        ]

    if isinstance(value, (list, tuple, set)):
        return [
            item
            for value_item in value
            for item in _flat(value_item)
        ]

    return [_text(value)] if _text(value) else []


# ============================================================
# GEMINI CONNECTION
# ============================================================

def _ask_json(prompt: str) -> dict[str, Any]:
    """Ask Gemini for a JSON response."""

    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise ChatbotServiceError(
            "GEMINI_API_KEY is missing from your environment or .env."
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

    except ImportError as exc:
        raise ChatbotServiceError(
            "Install the Gemini SDK using: pip install google-genai"
        ) from exc

    except Exception as exc:
        raise ChatbotServiceError(
            f"Gemini request failed: {exc}"
        ) from exc

    raw = (getattr(response, "text", "") or "").strip()

    raw = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw,
        flags=re.I,
    )

    start = raw.find("{")
    end = raw.rfind("}")

    try:
        result = (
            json.loads(raw[start:end + 1])
            if start >= 0 and end > start
            else None
        )
    except json.JSONDecodeError as exc:
        raise ChatbotServiceError(
            "Gemini returned malformed JSON. Please retry."
        ) from exc

    if not isinstance(result, dict):
        raise ChatbotServiceError(
            "Gemini did not return a valid JSON object."
        )

    return result


# ============================================================
# DETERMINE WHICH VERIFICATION QUESTIONS ARE REQUIRED
# ============================================================

def _education_requirements(jd: dict[str, Any]) -> list[str]:
    not_required = {
        "none",
        "n/a",
        "na",
        "not required",
        "no education required",
        "education not required",
    }

    return [
        item
        for item in _flat(jd.get("education"))
        if item.casefold() not in not_required
    ]


def _experience_requirements(jd: dict[str, Any]) -> list[str]:
    values = _flat(jd.get("experience"))

    text = " ".join(
        values + [_text(jd.get("summary"))]
    )

    explicitly_not_required = re.search(
        r"\b(no experience required|experience not required|not required)\b",
        text,
        re.I,
    )

    has_years = re.search(
        r"\b\d+(?:\.\d+)?\s*\+?\s*years?\b",
        text,
        re.I,
    )

    if explicitly_not_required and not has_years:
        return []

    if has_years:
        return values or [text]

    if values and not all(
        re.search(
            r"\b(preferred|nice to have|not required)\b",
            item,
            re.I,
        )
        for item in values
    ):
        return values

    return []


# ============================================================
# FIELD-RELATED QUESTION BANK
# ============================================================

def _field(jd: dict[str, Any]) -> str:
    text = " ".join([
        _text(jd.get("job_title")),
        _text(jd.get("title")),
        _text(jd.get("department")),
        " ".join(_flat(jd.get("skills"))),
    ]).lower()

    groups = {
        "accounting": (
            "accountant", "accounting", "bookkeep",
            "accounts payable", "accounts receivable",
        ),
        "software": (
            "software", "developer", "programmer",
            "web engineer", "devops",
        ),
        "data": (
            "data scientist", "data analyst", "data engineer",
            "machine learning", "analytics",
        ),
        "design": (
            "designer", "ui/ux", "user experience",
            "product design", "graphic design",
        ),
        "hr": (
            "human resources", "hr specialist",
            "recruiter", "talent acquisition",
        ),
        "marketing": (
            "marketing", "seo", "content strategist",
            "digital marketer",
        ),
    }

    for name, terms in groups.items():
        if any(term in text for term in terms):
            return name

    return "general"


def question_bank_for_jd(
    jd: dict[str, Any],
) -> dict[str, dict[str, str]]:
    bank = {
        question["id"]: dict(question)
        for question in DEFAULT_QUESTIONS
    }

    bank.update({
        question_id: {
            "id": question_id,
            "question": text,
        }
        for question_id, text in QUESTION_BANK.get(
            _field(jd), []
        )
    })

    return bank


def resolve_interview_questions(
    jd: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    """
    Return exactly five interview questions.

    Expected HR configuration:
    {
        "selected_ids": ["design_process"],
        "custom_questions": ["Your exact custom question?"]
    }

    If HR has not configured questions, use the five defaults.
    """

    if not config:
        return [dict(q) for q in DEFAULT_QUESTIONS]

    bank = question_bank_for_jd(jd)

    selected = config.get(
        "selected_ids",
        config.get("selected_questions", []),
    )

    custom = config.get("custom_questions", [])

    if isinstance(selected, (str, dict)):
        selected = [selected]

    if isinstance(custom, (str, dict)):
        custom = [custom]

    chosen = []
    seen = set()

    for item in selected if isinstance(selected, list) else []:
        if isinstance(item, dict):
            qid = _text(item.get("id"))
            text = _text(
                item.get("question") or item.get("text")
            )

            question = (
                dict(bank[qid])
                if qid in bank
                else {
                    "id": qid or f"custom_{len(chosen)+1}",
                    "question": text,
                }
            )

        else:
            key = _text(item)

            question = (
                dict(bank[key])
                if key in bank
                else {
                    "id": f"custom_{len(chosen)+1}",
                    "question": key,
                }
            )

        qid = _text(question.get("id"))
        text = _text(question.get("question"))

        if text and qid not in seen:
            chosen.append({
                "id": qid or f"custom_{len(chosen)+1}",
                "question": text,
            })
            seen.add(qid)

    for item in custom if isinstance(custom, list) else []:
        text = (
            _text(item.get("question") or item.get("text"))
            if isinstance(item, dict)
            else _text(item)
        )

        qid = (
            _text(item.get("id"))
            if isinstance(item, dict)
            else ""
        ) or f"custom_{len(chosen)+1}"

        if text and qid not in seen:
            chosen.append({"id": qid, "question": text})
            seen.add(qid)

    for question in DEFAULT_QUESTIONS:
        if len(chosen) == 5:
            break

        if question["id"] not in seen:
            chosen.append(dict(question))
            seen.add(question["id"])

    return chosen[:5] or [
        dict(q) for q in DEFAULT_QUESTIONS
    ]


# ============================================================
# BUILD THE COMPLETE QUESTION SEQUENCE
# ============================================================

def build_questions(
    jd: dict[str, Any],
    question_config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Verification questions come first.
    Only five interview questions receive interview marks.
    """

    questions = []

    education = _education_requirements(jd)
    experience = _experience_requirements(jd)

  

    if education:
        questions.append({
            "id": "verify_education",
            "type": "education_verification",
            "question": (
                "What is your highest completed degree and field of study? "
            ),
            "required_information": education,
            "score_max": 10,
        })

    if experience:
        questions.append({
            "id": "verify_experience_years",
            "type": "experience_verification",
      
"question":   "How many years of relevant professional experience do you have "
    "for this role?",

               
              
            
            "required_information": experience,
            "score_max": None,
        })

    for number, question in enumerate(
        resolve_interview_questions(jd, question_config),
        1,
    ):
        questions.append({
            "id": question["id"],
            "type": "interview",
            "question": question["question"],
            "question_number": number,
            "score_max": 2,
        })

    return questions


# ============================================================
# START AND TRACK ONE INTERVIEW
# ============================================================



 
def start_interview(
    *,
    candidate_id: str,
    vacancy_id: str,
    jd: dict[str, Any],
    candidate_name: str = "",
    candidate_file: str = "",
    question_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create a serializable interview session."""

    if not _text(candidate_id) or not _text(vacancy_id):
        raise ValueError(
            "candidate_id and vacancy_id are required."
        )

    questions = build_questions(jd, question_config)
    education_assessment = None

    if not _education_requirements(jd):
        education_assessment = {
            "score": 10.0,
            "status": "not_required",
            "reason": "The JD has no education requirement.",
            "candidate_answer": "",
        }

    return {
        "schema_version": "1.0",
        "candidate_id": str(candidate_id),
        "vacancy_id": str(vacancy_id),
        "candidate_name": _text(candidate_name),
        "candidate_file": _text(candidate_file),
        "jd": jd,
        "questions": questions,
        "next_index": 0,
        "answers": {},
        "education_assessment": education_assessment,
        "experience_answer": None,
        "candidate_reported_yoe": None,
        "completed": False,
        "response_record": None,
    }



def current_question(
    session: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if session.get("completed"):
        return None

    index = int(session.get("next_index", 0))
    questions = session.get("questions", [])

    return (
        questions[index]
        if 0 <= index < len(questions)
        else None
    )


def _idk(answer: str) -> bool:
    return bool(re.fullmatch(
        r"\s*(idk|i\s+do\s+not\s+know|i\s+don't\s+know|"
        r"dont\s+know|unknown|n/?a|not sure|prefer not to say)"
        r"\s*[.!]?\s*",
        answer,
        re.I,
    ))


# ============================================================
# EDUCATION ASSESSMENT — GEMINI RETURNS 0 TO 10
# ============================================================


def assess_education_answer(
    jd: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    """Score mandatory education requirements as 10/10 or 0/10."""

    requirements = _education_requirements(jd)
    answer = _text(answer)

    if not requirements:
        return {
            "score": 10.0,
            "status": "not_required",
            "reason": "The JD has no education requirement.",
            "candidate_answer": answer,
        }

    if not answer or _idk(answer):
        return {
            "score": 0.0,
            "status": "failed",
            "reason": "The candidate did not provide the required education information.",
            "recognized_degree": "",
            "recognized_field": "",
            "evidence": [],
            "candidate_answer": answer,
        }

    prompt = f"""
Assess the candidate's education against ALL mandatory JD requirements.

JD requirements:
{json.dumps(requirements, ensure_ascii=False)}

Candidate's answer:
{json.dumps(answer, ensure_ascii=False)}

Rules:
- Return passed only if both the required degree level and required field
  are satisfied.
- A degree below a mandatory minimum is failed.
- A required field that is not satisfied is failed.
- Accept a related field only when appropriate for this job.
- Do not treat preferred criteria as mandatory.
- Never invent qualifications or fields.
- Return unclear if evidence is insufficient or contradictory.
- Do not use protected characteristics.

Return JSON only:
{{
  "status": "passed|failed|unclear",
  "reason": "brief explanation",
  "recognized_degree": "",
  "recognized_field": "",
  "evidence": []
}}
"""

    result = _ask_json(prompt)
    status = _text(result.get("status")).casefold()

    # Ignore Gemini's numeric score and enforce binary marks in Python.
    if status == "passed":
        score = 10.0
    elif status == "failed":
        score = 0.0
    else:
        status = "unclear"
        score = 0.0

    return {
        "score": score,
        "status": status,
        "reason": _text(result.get("reason"))[:700],
        "recognized_degree": _text(
            result.get("recognized_degree")
        )[:160],
        "recognized_field": _text(
            result.get("recognized_field")
        )[:160],
        "evidence": (
            result.get("evidence", [])
            if isinstance(result.get("evidence"), list)
            else []
        ),
        "candidate_answer": answer,
    }
# ============================================================
# EXPERIENCE — EXTRACT REPORTED YEARS, NEVER SCORE THEM HERE
# ============================================================

def extract_reported_years(
    answer: str,
) -> Optional[float]:
    """Extract a reported duration only; experience scoring stays in matcher."""

    if not answer.strip() or _idk(answer):
        return None

    for pattern in (
        r"(\d+(?:\.\d+)?)\s*\+?\s*years?\b",
        r"(\d+(?:\.\d+)?)\s*yrs?\b",
    ):
        match = re.search(pattern, answer.lower())

        if match:
            years = float(match.group(1))
            months = re.search(
                r"and\s+(\d+)\s*months?",
                answer.lower(),
            )

            if months:
                years += min(11, int(months.group(1))) / 12

            return round(max(0, min(60, years)), 2)

    match = re.search(r"(\d+)\s*months?\b", answer.lower())

    if match:
        return round(
            max(0, min(60, int(match.group(1)) / 12)),
            2,
        )

    # For written durations, extract a number only.
    # No fit assessment or experience scoring is requested.
    try:
        result = _ask_json(f"""
Extract only the years of relevant work experience
explicitly reported. Do not grade, evaluate, or score.
If no duration is clearly stated, return null.

Answer: {json.dumps(answer, ensure_ascii=False)}

Return JSON only:
{{"reported_years": null}}
""")

        value = result.get("reported_years")

        return (
            round(max(0, min(60, float(value))), 2)
            if value is not None
            else None
        )

    except (ChatbotServiceError, TypeError, ValueError):
        return None


# ============================================================
# INTERVIEW — GEMINI RETURNS 0, 1, OR 2 MARKS PER ANSWER
# ============================================================

def score_interview_answer(
    question: str,
    answer: str,
    question_id: str,
) -> dict[str, Any]:
    if not answer.strip() or _idk(answer):
        return {
            "score": 0.0,
            "max_score": 2.0,
            "feedback": "No assessable answer was provided.",
        }

    prompt = f"""
Grade one candidate interview answer.

Question ID: {question_id}
Question: {json.dumps(question, ensure_ascii=False)}
Answer: {json.dumps(answer, ensure_ascii=False)}

Award exactly 0, 1, or 2 marks:
0 = no meaningful or relevant answer.
1 = partly relevant but vague.
2 = relevant, with a reasonable explanation,
    example, or clear thought.

For strengths and weaknesses, reward thoughtful answers
without requiring one objectively correct answer.
Do not penalize grammar, accent, language style,
disability, or protected characteristics.
Do not infer unstated details.

Return JSON only:
{{"score": 0, "feedback": "one brief sentence"}}
"""

    result = _ask_json(prompt)

    try:
        score = float(result.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    # Force the result to the allowed marks.
    score = (
        2.0 if score >= 1.5
        else 1.0 if score >= 0.5
        else 0.0
    )

    return {
        "score": score,
        "max_score": 2.0,
        "feedback": _text(result.get("feedback"))[:350],
    }


# ============================================================
# BUILD MATCHER-COMPATIBLE RESPONSE
# ============================================================

def _response_record(
    session: dict[str, Any],
) -> dict[str, Any]:
    answers = session.get("answers", {})

    interview = {
        qid: {
            key: item.get(key)
            for key in (
                "question",
                "answer",
                "score",
                "max_score",
                "feedback",
            )
        }
        for qid, item in answers.items()
        if item.get("type") == "interview"
    }

    marks = [
        float(item.get("score") or 0)
        for item in interview.values()
    ]

    education_answer = next(
        (
            item["answer"]
            for item in answers.values()
            if item.get("type") == "education_verification"
        ),
        "",
    )

    return {
        "candidate_id": session["candidate_id"],
        "vacancy_id": session["vacancy_id"],
        "candidate_file": session.get("candidate_file", ""),
        "education_answer": education_answer,
        "education_assessment": session.get("education_assessment"),
        "experience_answer": session.get("experience_answer") or "",
        "candidate_reported_yoe": session.get("candidate_reported_yoe"),
        "interview_answers": interview,
        "interview_score_10": (
            round(sum(marks), 2)
            if len(marks) == 5
            else None
        ),
        "interview_completed": len(marks) == 5,
    }


# ============================================================
# SUBMIT ONE ANSWER AND MOVE TO THE NEXT QUESTION
# ============================================================


def submit_answer(
    session: dict[str, Any],
    question_id: str,
    answer: str,
) -> dict[str, Any]:
    """Assess one current answer and return the next question/result."""

    if session.get("completed"):
        raise ValueError("This interview is already complete.")

    question = current_question(session)

    if not question:
        raise ValueError("No unanswered question is available.")

    if question_id != question["id"]:
        raise ValueError("Please answer the current question first.")

    answer = _text(answer)
    kind = question["type"]

    # An empty education answer is allowed and receives 0/10.
    # Other question types still require an answer or "I don't know".
    if not answer and kind != "education_verification":
        raise ValueError(
            "Please answer this question or enter 'I don't know'."
        )

    item = {
        "type": kind,
        "question": question["question"],
        "answer": answer,
        "score": None,
        "max_score": question.get("score_max"),
    }

    if kind == "education_verification":
        result = assess_education_answer(session["jd"], answer)
        session["education_assessment"] = result

        item.update(
            score=result.get("score"),
            feedback=result.get("reason", ""),
        )

    elif kind == "experience_verification":
        # Preserve the answer. The matcher calculates experience score.
        years = extract_reported_years(answer)

        session["experience_answer"] = answer
        session["candidate_reported_yoe"] = years

        item.update(
            reported_years=years,
            feedback=(
                "Experience score is calculated by the matching system."
            ),
        )

    elif kind == "interview":
        item.update(
            score_interview_answer(
                question["question"],
                answer,
                question_id,
            )
        )

    else:
        raise ValueError(f"Unsupported question type: {kind}")

    session.setdefault("answers", {})[question_id] = item
    session["next_index"] = int(session.get("next_index", 0)) + 1
    session["completed"] = (
        session["next_index"] >= len(session.get("questions", []))
    )

    if session["completed"]:
        session["response_record"] = _response_record(session)

    return {
        "session": session,
        "answered_question": question_id,
        "next_question": current_question(session),
        "completed": session["completed"],
        "response_record": (
            session.get("response_record")
            if session["completed"]
            else None
        ),
    }



# ============================================================
# OPTIONAL JSON BRIDGE FOR MATCHER CLI TESTS
# ============================================================

def save_matching_response(
    session: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """
    Save completed response in the format read by the matching script.
    The integrated website should persist results to SQLite instead.
    """

    if (
        not session.get("completed")
        or not isinstance(session.get("response_record"), dict)
    ):
        raise ValueError(
            "Finish the interview before saving its response."
        )

    filename = _text(session.get("candidate_file"))

    if not filename:
        raise ValueError(
            "candidate_file (structured CV JSON filename) "
            "is required for this file bridge."
        )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"candidates": {}}

    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))

            if (
                isinstance(previous, dict)
                and isinstance(previous.get("candidates"), dict)
            ):
                payload = previous
            elif isinstance(previous, dict):
                payload["candidates"] = previous

        except (OSError, json.JSONDecodeError):
            pass

    payload.setdefault("candidates", {})[filename] = (
        session["response_record"]
    )

    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return path


def session_summary(
    session: dict[str, Any],
) -> dict[str, Any]:
    """Return a concise summary for the future candidate/HR interface."""

    interview = [
        answer
        for answer in session.get("answers", {}).values()
        if answer.get("type") == "interview"
    ]

    marks = sum(
        float(answer.get("score") or 0)
        for answer in interview
    )

    return {
        "candidate_id": session.get("candidate_id"),
        "vacancy_id": session.get("vacancy_id"),
        "answered_questions": len(session.get("answers", {})),
        "total_questions": len(session.get("questions", [])),
        "interview_questions_answered": len(interview),
        "interview_marks_so_far": round(marks, 2),
        "interview_max_so_far": 2 * len(interview),
        "completed": bool(session.get("completed")),
        "current_question": current_question(session),
    }