"""
ResumeMatch AI V21.3 (+ skill-classification and role-relevance fixes)
Hybrid, explainable CV-to-JD matcher with chatbot verification + interview.

Based on V21.2. Core matching logic is preserved:
- Exact/equivalent skill meaning = 100, parent-suite = 50, semantic can support partial, missing = 0
- Same/equivalent role = 100, clearly related = 50, incompatible = 0
- Primary domain conflict = 0
- Education: required degree level strict; exact/related field = pass; unrelated = fail; unclear = verification
- Candidate-reported relevant YOE is primary, CV-calculated relevant YOE is fallback ("idk" -> CV YOE)
- Matching and interview remain separate; no LLM judge inside the core CV score

CHANGES IN THIS REVISION (weights, thresholds, YOE, education, interview untouched)
-----------------------------------------------------------------------------------
A. Skills: deterministic classification of every JD skill as required / preferred, with
   explicit alternative groups (classify_jd_skills). match_skills scores required skills
   (a group counts once), and preferred skills only add a bounded bonus. Ambiguous -> preferred.
B. Role relevance: title evidence + responsibility coverage + seniority. An unrecognised
   title is "unmapped" (missing evidence), not "different". combine_role() gives the final status.

V21.3 FEATURES (unchanged)
1. Weights: Skills 50 / Experience 30 / Education 10 / Interview 10.
2. Provisional vs final score:
     provisional (cv_score) = weighted CV components re-normalised to 100
     final_score            = 0.90 * cv_score + 0.10 * interview_score   (after interview)
3. Chatbot verification questions are asked ONLY when the JD requires them.
4. Chatbot education verdict accepted; Chatbot only supplies YOE.
5. Interview = 5 questions x 2 marks = 10 marks -> converted to 0-100.
6. HR question config (optional); match_one() is importable from Flask:
   match_one(jd, cv_data, filename, embedder, chatbot_rec, question_config)

OPTIONAL JD FIELDS used by the skill classifier (all optional, old vacancies still work)
  original_text / description / raw_text ... : original JD wording
  skill_requirements: [{"skill": "...", "requirement": "required|preferred", "group": "g1", "reason": "..."}]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

try:
    import numpy as np
except ImportError:
    np = None


# =====================================================================
# PATHS
# =====================================================================

BASE_DIR = Path(r"D:\projects\Resume_Screening_AI")

DEFAULT_RESUME_DIR = (
    BASE_DIR / "data" / "processed" / "structured_resumes_LLM" / "UIUX_Designer_Test"
)
DEFAULT_JD = BASE_DIR / "data" / "processed" / "uiux_test_jd.json"
DEFAULT_OUT = (
    BASE_DIR / "data" / "processed" / "matching_results" / "results_v21_3_uiux.json"
)
DEFAULT_CHATBOT_REQUEST = (
    BASE_DIR / "data" / "processed" / "matching_results" / "chatbot_requests.json"
)

REF_DATE = date(2026, 9, 30)

EMBED_MODEL = "sentence-transformers/all-mpnet-base-v2"


# =====================================================================
# WEIGHTS / THRESHOLDS
# =====================================================================

W_SKILLS = 0.50
W_EXPERIENCE = 0.30
W_EDUCATION = 0.10
W_INTERVIEW = 0.10

STRONG_THRESHOLD = 62.0
MODERATE_THRESHOLD = 40.0

REL_ENTRY_THRESHOLD = 55.0

INTERVIEW_QUESTION_COUNT = 5
MARKS_PER_QUESTION = 2.0
INTERVIEW_MAX_MARKS = INTERVIEW_QUESTION_COUNT * MARKS_PER_QUESTION  # 10


# =====================================================================
# DEFAULT INTERVIEW QUESTIONS (used when HR sets none / to pad HR questions)
# =====================================================================

STANDARD_INTERVIEW_QUESTIONS = [
    {
        "id": "q1_strength",
        "type": "interview",
        "question": "What is your biggest professional strength?",
    },
    {
        "id": "q2_weakness",
        "type": "interview",
        "question": "What is one professional weakness or area you are currently working to improve?",
    },
    {
        "id": "q3_project",
        "type": "interview",
        "question": "What is the best project you have worked on, and what was your contribution?",
    },
    {
        "id": "q4_experience",
        "type": "interview",
        "question": "Tell us about your most relevant experience for this position.",
    },
    {
        "id": "q5_skills",
        "type": "interview",
        "question": "Which skills from your CV are most relevant to this position, and how have you used them?",
    },
]


# =====================================================================
# TEXT UTILITIES
# =====================================================================

def clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v.replace("\x00", " ")).strip()
    if isinstance(v, (list, tuple, set)):
        return " ".join(clean(x) for x in v).strip()
    if isinstance(v, dict):
        return " ".join(clean(x) for x in v.values()).strip()
    return str(v).strip()


def flat(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[\n;|]+", v) if x.strip()]
    if isinstance(v, dict):
        return [clean(v)]
    if isinstance(v, (list, tuple, set)):
        out: list[str] = []
        for x in v:
            out.extend(flat(x))
        return out
    return [str(v)]


ABBR = [
    (r"\ba\s*/\s*p\b", "accounts payable"),
    (r"\ba\s*/\s*r\b", "accounts receivable"),
    (r"\bap\b", "accounts payable"),
    (r"\bar\b", "accounts receivable"),
    (r"\bg\s*/\s*l\b", "general ledger"),
    (r"\bacct\b", "account"),
    (r"\baccts\b", "accounts"),
    (r"\bms\s+(?=excel|office|word|powerpoint)\b", "microsoft "),
]

STOP = set(
    """
    a an and the of to in for with on at by from as is are be or will must should
    have has had was were this that these those it its their our your we you they
    he she i required preferred candidate etc using use used also able including
    such per via into over under within across about year years
    """.split()
)

SUFFIXES = (
    "ations", "ation", "ments", "ment", "ingly", "ing",
    "ies", "ied", "ers", "er", "ed", "es", "s",
)


@lru_cache(maxsize=200_000)
def _norm_str(text: str) -> str:
    s = clean(text).lower().replace("&", " and ")
    for p, r in ABBR:
        s = re.sub(p, r, s)
    s = re.sub(r"[^a-z0-9+#.\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm(t: Any) -> str:
    # Pure function, so results are cached (same output, far fewer regex calls).
    return _norm_str(t if isinstance(t, str) else clean(t))


def stem(w: str) -> str:
    if len(w) <= 3 or w.isdigit():
        return w
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


@lru_cache(maxsize=200_000)
def _tokens_str(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in _norm_str(text).split() if w not in STOP)


def tokens(t: Any) -> list[str]:
    return list(_tokens_str(t if isinstance(t, str) else clean(t)))


def phrase_tokens(t: str) -> tuple[str, ...]:
    return tuple(tokens(t))


def contains_phrase(text: str, phrase: str) -> bool:
    a = tokens(text)
    b = phrase_tokens(phrase)

    if not b:
        return False

    if len(b) == 1:
        return b[0] in a

    if all(x in a for x in b):
        for i in range(len(a) - len(b) + 1):
            if tuple(a[i:i + len(b)]) == b:
                return True

    pos = defaultdict(list)
    for i, x in enumerate(a):
        pos[x].append(i)

    if any(x not in pos for x in b):
        return False

    anchor = min(b, key=lambda x: len(pos[x]))

    for p in pos[anchor]:
        if all(any(abs(q - p) <= len(b) + 2 for q in pos[x]) for x in b):
            return True

    return False


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+|[•▪●]\s*", clean(text))
    out: list[str] = []
    for p in parts:
        p = p.strip(" -\t")
        if p:
            out.append(p)
    return out


def clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def to_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except Exception:
        return None


def to_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("true", "yes", "y", "1", "pass", "meets"):
            return True
        if t in ("false", "no", "n", "0", "fail"):
            return False
    return None


# =====================================================================
# EMBEDDINGS
# =====================================================================

class Embedder:

    def __init__(self, name: str):
        self.model = None
        self.cache: dict[str, Any] = {}

        try:
            from sentence_transformers import SentenceTransformer

            print(f"Loading embedding model: {name}")
            self.model = SentenceTransformer(name)

        except Exception as exc:
            print(f"WARNING: embeddings unavailable ({exc}). Using lexical fallback.")

    @property
    def semantic(self) -> bool:
        return self.model is not None

    def vectors(self, texts: list[str]):
        if not texts:
            if np is not None:
                return np.empty((0, 0), dtype=float)
            return []

        if not self.model:
            return []

        need = [x for x in dict.fromkeys(texts) if x not in self.cache]

        if need:
            enc = self.model.encode(
                need,
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=64,
                show_progress_bar=False,
            )
            for t, v in zip(need, enc):
                self.cache[t] = v

        return np.vstack([self.cache[x] for x in texts])

    def sim(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0

        if self.semantic:
            vectors = self.vectors([a, b])
            return float(vectors[0] @ vectors[1])

        A = set(tokens(a))
        B = set(tokens(b))
        return len(A & B) / max(1, min(len(A), len(B)))


def semantic_score(cos: float) -> float:
    return clamp((cos - 0.35) / 0.25 * 100.0)


# =====================================================================
# SKILLS
# =====================================================================

SKILL_LEX = {
    "accounts payable": [
        "accounts payable", "account payable", "payables",
        "vendor invoices", "vendor payments", "invoice processing",
    ],
    "accounts receivable": [
        "accounts receivable", "account receivable", "receivables",
        "cash receipts", "receivables aging",
    ],
    "bank reconciliation": [
        "bank reconciliation", "bank statement reconciliation",
        "reconcile bank", "bank account reconciliation",
    ],
    "account reconciliation": [
        "account reconciliation", "balance sheet reconciliation",
        "reconcile accounts", "general ledger reconciliation", "gl reconciliation",
    ],
    "general accounting": [
        "general accounting", "accounting", "general ledger", "journal entries",
        "full cycle accounting", "accounting cycle", "month end close",
    ],
    "financial reporting": [
        "financial reporting", "financial reports", "financial statement",
        "financial statements", "profit and loss", "balance sheet", "management reports",
    ],
    "microsoft excel": [
        "microsoft excel", "excel", "ms excel", "spreadsheets", "pivot tables", "vlookup",
    ],
    "quickbooks": ["quickbooks", "quick books", "intuit quickbooks", "qbo"],
    "bookkeeping": ["bookkeeping", "book keeping", "bookkeeper"],
    "gaap": ["gaap", "generally accepted accounting principles", "us gaap"],
    "sql": ["sql", "mysql", "postgresql", "t sql"],
    "python": ["python"],
    "javascript": ["javascript", "js"],
    "machine learning": ["machine learning", "ml"],
    "project management": ["project management", "pmp"],
    "power bi": ["power bi", "powerbi"],
    "tableau": ["tableau"],
    # Data / BI / engineering equivalents
    "data modeling": ["data modeling", "data modelling", "kimball", "star schema", "data models"],
    "etl": ["etl", "elt", "etl elt", "etl elt pipelines", "etl pipelines", "elt pipelines",
            "data pipelines", "data pipeline", "pipeline automation"],
    "data warehousing": ["data warehousing", "data warehouse", "data warehouses",
                         "cloud warehouse", "cloud data warehouse"],
    "version control": ["version control", "git", "github", "gitlab"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    "code review": ["code review", "code reviews", "peer review"],
    "query optimization": ["query optimization", "query optimisation", "query tuning",
                           "performance tuning", "sql optimization"],
    "ctes": ["cte", "ctes", "common table expressions"],
    "data visualization": ["data visualization", "data visualisation", "dashboards", "dashboard",
                           "executive dashboards", "bi dashboards"],
    "statistical analysis": ["statistical analysis", "statistical modeling", "statistics", "statistical"],
}

SOFT_LEX = {
    "attention to detail": [
        "attention to detail", "detail oriented", "detail focused", "meticulous", "thorough",
    ],
    "analytical skills": [
        "analytical skills", "analytical", "analysis", "analyze", "analyse", "problem solving",
    ],
    "communication": ["communication", "communicated", "liaised", "presented"],
    "leadership": [
        "leadership", "led a team", "supervised", "managed a team", "mentored",
    ],
    "teamwork": ["teamwork", "team player", "collaborated", "cross functional"],
    "problem solving": ["problem solving", "resolved issues", "troubleshoot"],
    "time management": [
        "time management", "met deadlines", "deadline", "prioritized",
    ],
    "mentoring": ["mentoring", "mentored", "mentorship", "coaching junior"],
    "stakeholder management": [
        "stakeholder management", "stakeholder collaboration", "stakeholder engagement", "stakeholders",
    ],
}

PARENT = {
    "microsoft excel": ["microsoft office", "ms office", "office suite"],
    "microsoft word": ["microsoft office", "ms office", "office suite"],
    "microsoft powerpoint": ["microsoft office", "ms office", "office suite"],
    # Sub-skills implied by a broader skill that is listed on the CV. Same rule as the
    # Office suite: 50% credit ("partial"), never full credit, and only from the skills list.
    "query optimization": ["sql"],
    "indexing": ["sql"],
    "stored procedures": ["sql"],
    "window functions": ["sql"],
    "ctes": ["sql"],
    "numpy": ["pandas"],
}

# Peer tools: different products that do the same job. A candidate with one of them gets
# PARTIAL credit (50) for another, never full credit, and only from the skills list.
# (Explicit "X or Y" wording in the JD is handled separately by alternative groups.)
EXTRA_EVIDENCE_SCORE = 80.0   # summary / certifications / projects: a bit below experience bullets (90)

PEERS = {
    "airflow": ["dagster", "prefect"], "apache airflow": ["dagster", "prefect"],
    "dagster": ["airflow", "prefect"], "prefect": ["airflow", "dagster"],
    "snowflake": ["bigquery", "redshift", "databricks"],
    "google bigquery": ["snowflake", "redshift", "databricks"], "bigquery": ["snowflake", "redshift", "databricks"],
    "redshift": ["snowflake", "bigquery", "databricks"],
    "tableau": ["power bi", "looker"], "power bi": ["tableau", "looker"], "looker": ["tableau", "power bi"],
}

GENERIC = {
    "skill", "ability", "knowledge", "experience", "professional", "advanced",
    "basic", "strong", "excellent", "good", "management", "business", "work",
    "support", "report", "financial", "microsoft", "office", "system",
    "specialist", "senior", "junior", "general",
}


@lru_cache(maxsize=50_000)
def _canonical_skill_str(s: str) -> str:
    n = norm(s)
    combined = {**SKILL_LEX, **SOFT_LEX}

    for canon, vals in combined.items():
        if n == norm(canon):
            return canon
        if any(n == norm(v) for v in vals):
            return canon

    return n


def canonical_skill(s: str) -> str:
    return _canonical_skill_str(s if isinstance(s, str) else clean(s))


@lru_cache(maxsize=50_000)
def _skill_phrases_str(skill: str) -> tuple[str, ...]:
    c = _canonical_skill_str(skill)
    vals = SKILL_LEX.get(c) or SOFT_LEX.get(c) or [skill]
    return tuple(dict.fromkeys([c] + vals))


def skill_phrases(skill: str) -> list[str]:
    return list(_skill_phrases_str(skill if isinstance(skill, str) else clean(skill)))


def skill_match(
    skill: str,
    resume_skills: list[str],
    exp_sentences: list[str],
    emb: Embedder,
    extra_evidence: Optional[list[tuple[str, str]]] = None,
) -> dict[str, Any]:

    c = canonical_skill(skill)
    soft = c in SOFT_LEX

    out = {
        "skill": skill,
        "type": "soft" if soft else "hard",
        "score": 0.0,
        "status": "missing",
        "source": None,
        "evidence": None,
        "method": "missing",
    }

    phrases = skill_phrases(skill)

    # 1. Exact/equivalent
    for item in resume_skills:

        if canonical_skill(item) == c:
            out.update(
                score=100.0, status="strong", source="skills_section",
                evidence=item, method="equivalent",
            )
            return out

        if any(contains_phrase(item, p) for p in phrases):
            out.update(
                score=100.0, status="strong", source="skills_section",
                evidence=item, method="phrase",
            )
            return out

    # 2. Experience evidence
    for sent in exp_sentences:
        if any(contains_phrase(sent, p) for p in phrases):
            out.update(
                score=90.0 if not soft else 75.0,
                status="strong",
                source="experience",
                evidence=sent[:220],
                method="experience_phrase",
            )
            return out

    # 2b. Other CV sections: summary, certifications, projects, achievements
    for source, text in extra_evidence or []:
        if any(contains_phrase(text, p) for p in phrases):
            out.update(
                score=EXTRA_EVIDENCE_SCORE if not soft else 65.0,
                status="strong",
                source=source,
                evidence=text[:220],
                method=f"{source}_phrase",
            )
            return out

    # 3. Parent suite
    for parent in PARENT.get(c, []):
        for item in resume_skills:
            if contains_phrase(item, parent):
                out.update(
                    score=50.0, status="partial", source="skills_section",
                    evidence=item, method="parent_suite",
                )
                return out

    # 3b. Peer tool: same job, different product -> partial credit only
    for peer in PEERS.get(c, []):
        for item in resume_skills:
            if contains_phrase(item, peer):
                out.update(
                    score=50.0, status="partial", source="skills_section",
                    evidence=item, method="peer_tool",
                )
                return out

    # 4. Lexical evidence
    distinctive = [x for x in set(tokens(skill)) if x not in GENERIC]
    pool = resume_skills + exp_sentences

    if distinctive:
        for text in pool:
            tt = set(tokens(text))
            coverage = sum(x in tt for x in distinctive) / len(distinctive)

            if coverage == 1.0:
                out.update(
                    score=50.0, status="partial", source="lexical",
                    evidence=text[:220], method="partial_lexical",
                )
                return out

    # 5. Semantic evidence
    if emb.semantic and pool and not soft:
        sims = [(emb.sim(skill, x), x) for x in pool]
        best, evidence = max(sims, key=lambda z: z[0])

        if best >= 0.68:
            out.update(
                score=50.0, status="partial", source="semantic",
                evidence=evidence[:220], method=f"semantic_{best:.2f}",
            )
            return out

    return out



# ---------------- V21.4: skill classification + scoring ----------------
# =====================================================================
# V21.4 PATCH — SECTION 1: DETERMINISTIC SKILL CLASSIFICATION + SCORING
# Insert directly AFTER skill_match(); REPLACE the old match_skills().
# skill_match() itself is untouched.
# =====================================================================

PREFERRED_BONUS_WEIGHT = 0.20   # preferred skills can close at most 20% of the gap above the required score

_REQ_CUE = re.compile(
    r"\b(?:must[\s-]+have|must|required|requires?|requirements?|mandatory|essential|minimum)\b", re.I)
_PREF_CUE = re.compile(
    r"\b(?:preferred|preferably|desirable|desired|nice[\s-]+to[\s-]+have|good[\s-]+to[\s-]+have|"
    r"bonus|(?:an?\s+)?advantage|advantageous|a\s+plus|ideally|optional)\b", re.I)
_NEG_REQ = re.compile(
    r"\b(?:not|no|isn't|aren't)\s+(?:strictly\s+|absolutely\s+)?(?:required|necessary|mandatory|essential)\b", re.I)

_PREF_HEAD = re.compile(r"prefer|nice[\s-]+to[\s-]+have|bonus|desir|good[\s-]+to[\s-]+have|optional|a\s+plus|advantage", re.I)
_REQ_HEAD = re.compile(r"required|requirements|must[\s-]+have|essential|mandatory|minimum|what you(?:'|’)?ll need", re.I)
_PREF_HEAD_FULL = re.compile(
    r"(?:(?:preferred|desired|desirable|bonus|optional|nice[\s-]+to[\s-]+have|good[\s-]+to[\s-]+have)"
    r"(?:\s+(?:skills|qualifications|experience|requirements|extras))?|bonus points|pluses)", re.I)
_REQ_HEAD_FULL = re.compile(
    r"(?:(?:required|essential|mandatory|minimum|must[\s-]+have)(?:\s+(?:skills|qualifications|experience|requirements))?"
    r"|requirements|minimum qualifications|what you(?:'|’)?ll need)", re.I)

_OR_GAP = re.compile(r"[\s,/()]*(?:and/or|\bor\b)[\s,/()]*", re.I)
_COMMA_GAP = re.compile(r"\s*,[\s,]*")
_LIST_GAP = re.compile(r"[\s,/&]*(?:,|/|&|\band\b|\bor\b)[\s,/&]*|[\s,]+", re.I)
_EQUIV = re.compile(r"\bor\s+(?:an?\s+)?(?:equivalent|similar|comparable|alternative)\b", re.I)
_ONE_OF = re.compile(r"\b(?:at\s+least\s+)?one\s+of(?:\s+the\s+following)?\b|\bany\s+(?:one\s+)?of\s+the\s+following\b", re.I)
_EQ_MARKER = re.compile(r"\(|\bsuch\s+as\b|\blike\b|\beg\b|\bincluding\b", re.I)

_JD_TEXT_KEYS = ("original_text", "original_description", "description", "raw_text",
                 "job_description_text", "full_text", "jd_text")
_SKIP_FIELDS = set(_JD_TEXT_KEYS) | {"skills", "skill_requirements"}
_PLAIN_FIELDS = {"experience", "responsibilities", "summary", "qualifications", "education"}


def _heading_class(line: str):
    raw = line.strip()
    s = re.sub(r"[:\-•*#\s]+$", "", re.sub(r"^[\-•*#\s]+", "", raw)).lower()
    if not s:
        return False, None
    words = len(s.split())
    letters = re.sub(r"[^A-Za-z]", "", raw)
    if letters and letters.isupper() and words <= 10 and not raw.endswith("."):
        # PDF-style heading such as "ESSENTIAL TECHNICAL REQUIREMENTS & SKILLS"
        if _PREF_HEAD.search(s):
            return True, "preferred"
        if _REQ_HEAD.search(s):
            return True, "required"
        return True, None
    if raw.endswith(":") and words <= 8:
        if _PREF_HEAD.search(s):
            return True, "preferred"
        if _REQ_HEAD.search(s):
            return True, "required"
        return True, None
    if words <= 4 and _PREF_HEAD_FULL.fullmatch(s):
        return True, "preferred"
    if words <= 4 and _REQ_HEAD_FULL.fullmatch(s):
        return True, "required"
    return False, None


def _cue_spans(sent: str):
    neg = [m.span() for m in _NEG_REQ.finditer(sent)]
    cues = [("preferred", a, b) for a, b in neg]
    cues += [("preferred", m.start(), m.end()) for m in _PREF_CUE.finditer(sent)]
    for m in _REQ_CUE.finditer(sent):
        if any(a <= m.start() and m.end() <= b for a, b in neg):
            continue
        cues.append(("required", m.start(), m.end()))
    return cues


def _cue_class(a: int, b: int, cues):
    best = None
    for cls, x, y in cues:
        d = 0 if (x < b and a < y) else min(abs(x - b), abs(a - y))
        key = (d, 0 if cls == "required" else 1)
        if best is None or key < best[0]:
            best = (key, cls)
    return best[1] if best else None


def _jd_segments(jd: dict[str, Any]):
    """(sentence, section_default, one_of_tag) triples from original text + requirement-bearing fields."""
    segs = []
    tag_n = 0

    def protect(t: str) -> str:
        return re.sub(r"\bi\.e\.", "ie", re.sub(r"\be\.g\.", "eg", t, flags=re.I), flags=re.I)

    for k in _JD_TEXT_KEYS:
        v = jd.get(k)
        if not (isinstance(v, str) and v.strip()):
            continue
        section, tag, tag_cls = None, None, None
        merged: list[str] = []
        for raw_line in protect(v).splitlines():
            prev = merged[-1] if merged else ""
            if (
                raw_line.strip()
                and prev.strip()
                and not prev.rstrip().endswith((".", ":", ";", "!", "?"))
                and len(prev.split()) >= 6
                and not _heading_class(prev)[0]
                and not _heading_class(raw_line)[0]
            ):
                merged[-1] = prev.rstrip() + " " + raw_line.strip()   # wrapped line: continue the sentence
            else:
                merged.append(raw_line)
        for line in merged:
            if not line.strip():
                tag = None
                continue
            if _ONE_OF.search(line) and line.strip().endswith(":"):
                tag_n += 1
                tag = f"oneof{tag_n}"
                cues = _cue_spans(line)
                tag_cls = ("required" if any(c[0] == "required" for c in cues)
                           else "preferred" if cues else None)
                continue
            is_h, cls = _heading_class(line)
            if is_h:
                section, tag, tag_cls = cls, None, None
                continue
            for s in sentences(line):
                segs.append((s, (tag_cls or section) if tag else section, tag))

    for k, v in jd.items():
        lk = str(k).lower()
        if k in _SKIP_FIELDS:
            continue
        default = ("preferred" if re.search(r"prefer|nice|bonus|desir", lk)
                   else "required" if re.search(r"required|requirement|must", lk) else None)
        if default is None and lk not in _PLAIN_FIELDS:
            continue
        for item in flat(v):
            for s in sentences(protect(item)):
                segs.append((s, default, None))
    return segs


def _skill_span(sent: str, skill: str):
    for p in dict.fromkeys([skill] + skill_phrases(skill)):
        if not p:
            continue
        pat = r"(?<![A-Za-z0-9+#])" + re.escape(p) + r"(?![A-Za-z0-9+#])"
        m = re.search(pat, sent, re.I)
        if m:
            return m.start(), m.end()
    return None


def _sentence_groups(sent: str, hits: dict[str, tuple[int, int]]) -> list[list[str]]:
    """Explicit alternatives only: 'X or Y', 'X, Y, or Z', 'one of the following', 'X or equivalent (Y, Z)'."""
    items = sorted(hits.items(), key=lambda kv: kv[1][0])
    n = len(items)
    if n < 2:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    kinds = []
    for i in range(n - 1):
        between = sent[items[i][1][1]:items[i + 1][1][0]]
        kinds.append("or" if _OR_GAP.fullmatch(between)
                     else "comma" if _COMMA_GAP.fullmatch(between) else None)

    for i, k in enumerate(kinds):
        if k == "or":
            union(i, i + 1)
        elif k == "comma":
            j = i + 1
            while j < len(kinds) and kinds[j] == "comma":
                j += 1
            if j < len(kinds) and kinds[j] == "or":
                union(i, i + 1)

    m = _ONE_OF.search(sent)
    if m:
        idx = [i for i, (_, (a, _b)) in enumerate(items) if a >= m.end()]
        for i in idx[1:]:
            union(idx[0], i)

    for m in _EQUIV.finditer(sent):
        head = [i for i, (_, (_a, b)) in enumerate(items) if b <= m.start()]
        mk = _EQ_MARKER.search(sent[m.end():m.end() + 80])
        if not head or not mk:
            continue
        tail_start = m.end() + mk.end()
        tail = [i for i, (_, (a, _b)) in enumerate(items) if a >= tail_start]
        if not tail or items[tail[0]][1][0] - tail_start > 15:
            continue
        chain = [tail[0]]
        for i in tail[1:]:
            gap = sent[items[chain[-1]][1][1]:items[i][1][0]]
            if _LIST_GAP.fullmatch(gap):
                chain.append(i)
            else:
                break
        for i in chain:
            union(head[-1], i)

    comps: dict[int, list[str]] = defaultdict(list)
    for i, (s, _) in enumerate(items):
        comps[find(i)].append(s)
    return [v for v in comps.values() if len(v) >= 2]


def _resolve_mentions(ms):
    if any(c == "required" and e for c, e in ms):
        return "required", True, "explicit required wording"
    if any(c == "preferred" and e for c, e in ms):
        return "preferred", True, "explicit preferred/optional wording"
    if any(c == "required" for c, _ in ms):
        return "required", False, "listed under a required section"
    if any(c == "preferred" for c, _ in ms):
        return "preferred", False, "listed under a preferred section"
    return "preferred", False, "ambiguous: no requirement wording found, defaulted to preferred"


def classify_jd_skills(jd: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic required / preferred / alternative-group classification. No LLM.
    Priority: stored jd["skill_requirements"] metadata -> original JD text and
    requirement fields -> default (preferred, with an uncertainty reason).
    Returns {"skills": {skill: info}, "groups": {gid: {...}}, "source": str}.
    """
    skills = list(dict.fromkeys(flat(jd.get("skills", []))))
    meta_map: dict[str, dict] = {}
    meta = jd.get("skill_requirements")
    if isinstance(meta, list):
        for m in meta:
            if isinstance(m, dict) and clean(m.get("skill")):
                meta_map[norm(m["skill"])] = m

    mentions: dict[str, list] = {s: [] for s in skills}
    uf = {s: s for s in skills}

    def find(x):
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    def union(a, b):
        uf[find(a)] = find(b)

    tagged: dict[str, set] = defaultdict(set)
    segs = _jd_segments(jd)

    for sent, default, tag in segs:
        hits = {}
        for s in skills:
            span = _skill_span(sent, s)
            if span:
                hits[s] = span
        if not hits:
            continue
        cues = _cue_spans(sent)
        for s, (a, b) in hits.items():
            cls = _cue_class(a, b, cues)
            mentions[s].append((cls or default, cls is not None))
            if tag:
                tagged[tag].add(s)
        for grp in _sentence_groups(sent, hits):
            for s in grp[1:]:
                union(grp[0], s)

    for members in tagged.values():
        members = sorted(members, key=skills.index)
        for s in members[1:]:
            union(members[0], s)

    info: dict[str, dict] = {}
    for s in skills:
        m = meta_map.get(norm(s))
        if m:
            req = clean(m.get("requirement")).lower()
            if req in ("required", "preferred"):
                info[s] = {"requirement": req, "explicit": True, "ambiguous": False,
                           "group_id": None, "reason": clean(m.get("reason")) or "stored classification"}
                if clean(m.get("group")):
                    info[s]["meta_group"] = clean(m["group"])
                continue
        req, explicit, reason = _resolve_mentions(mentions[s])
        info[s] = {"requirement": req, "explicit": explicit, "ambiguous": reason.startswith("ambiguous"),
                   "group_id": None, "reason": reason}

    comps: dict[str, list[str]] = defaultdict(list)
    for s in skills:
        comps[find(s)].append(s)
    groups: dict[str, dict] = {}
    n = 0
    for members in sorted((v for v in comps.values() if len(v) >= 2), key=lambda v: skills.index(v[0])):
        n += 1
        gid = f"alt{n}"
        req = "required" if any(info[s]["requirement"] == "required" for s in members) else "preferred"
        groups[gid] = {"members": members, "requirement": req}
        for s in members:
            info[s].update(requirement=req, group_id=gid)
            info[s]["reason"] += "; member of an explicit alternative group"
            info[s]["ambiguous"] = False if req == "required" else info[s]["ambiguous"]

    meta_groups: dict[str, list[str]] = defaultdict(list)
    for s, d in info.items():
        if d.get("meta_group"):
            meta_groups[d["meta_group"]].append(s)
    for key, members in meta_groups.items():
        if len(members) < 2:
            continue
        gid = f"meta_{key}"
        req = "required" if any(info[s]["requirement"] == "required" for s in members) else "preferred"
        groups[gid] = {"members": members, "requirement": req}
        for s in members:
            info[s].update(requirement=req, group_id=gid)

    has_original = any(isinstance(jd.get(k), str) and jd[k].strip() for k in _JD_TEXT_KEYS)
    source = ("metadata" if meta_map else "text" if has_original
              else "structured_fields_only" if segs else "default_no_wording")
    return {"skills": info, "groups": groups, "source": source}


_CLASSIFICATION_CACHE: dict[str, dict[str, Any]] = {}


def collect_extra_evidence(data: dict[str, Any]) -> list[tuple[str, str]]:
    """Skill evidence from CV sections other than the skills list and experience bullets."""
    out: list[tuple[str, str]] = []
    for s in sentences(clean(data.get("summary"))):
        out.append(("summary", s))
    for key, label in (("certifications", "certification"), ("certificates", "certification"),
                       ("projects", "projects"), ("achievements", "achievements")):
        raw = data.get(key)
        items = raw if isinstance(raw, list) else [raw] if raw else []
        for item in items:
            for s in sentences(clean(item)):
                out.append((label, s))
    return out


def classify_jd_skills_cached(jd: dict[str, Any]) -> dict[str, Any]:
    """classify_jd_skills() depends only on the JD, so compute it once per distinct JD."""
    try:
        key = json.dumps(jd, sort_keys=True, default=str)
    except Exception:
        return classify_jd_skills(jd)
    hit = _CLASSIFICATION_CACHE.get(key)
    if hit is None:
        if len(_CLASSIFICATION_CACHE) >= 64:
            _CLASSIFICATION_CACHE.clear()
        hit = _CLASSIFICATION_CACHE[key] = classify_jd_skills(jd)
    return hit


def _blend(units: list[dict[str, Any]]) -> Optional[float]:
    """Same hard 85% / soft 15% blend the old match_skills used."""
    if not units:
        return None
    hard = [u["score"] for u in units if u["type"] == "hard"]
    soft = [u["score"] for u in units if u["type"] == "soft"]
    h = sum(hard) / len(hard) if hard else None
    s = sum(soft) / len(soft) if soft else None
    if s is None:
        return h
    if h is None:
        return s
    return 0.85 * h + 0.15 * s


def _build_units(details: list[dict[str, Any]], requirement: str) -> list[dict[str, Any]]:
    units, seen = [], set()
    for d in details:
        if d["requirement"] != requirement:
            continue
        gid = d.get("group_id")
        if gid:
            if gid in seen:
                continue
            seen.add(gid)
            members = [x for x in details if x.get("group_id") == gid]
            best = max(members, key=lambda x: x["score"])
            for x in members:
                x["group_satisfied_by"] = best["skill"] if best["score"] > 0 else None
            units.append({"name": " / ".join(x["skill"] for x in members), "kind": "group",
                          "group_id": gid, "members": [x["skill"] for x in members],
                          "requirement": requirement, "type": best["type"], "score": best["score"],
                          "status": best["status"],
                          "satisfied_by": best["skill"] if best["score"] > 0 else None})
        else:
            units.append({"name": d["skill"], "kind": "skill", "group_id": None, "members": [d["skill"]],
                          "requirement": requirement, "type": d["type"], "score": d["score"],
                          "status": d["status"], "satisfied_by": d["skill"] if d["score"] > 0 else None})
    return units


def match_skills(
    jd_skills: list[str],
    resume_skills: list[str],
    exp_sentences: list[str],
    emb: Embedder,
    classification: Optional[dict[str, Any]] = None,
    extra_evidence: Optional[list[tuple[str, str]]] = None,
) -> dict[str, Any]:
    """
    classification=None keeps the legacy behaviour (every listed skill required),
    so direct callers of the old signature are unaffected. match_one passes
    classify_jd_skills(jd) so scoring, reasons and explanations share one classification.
    Total stays 0-100: required_score + (100 - required_score) * 0.20 * preferred_coverage.
    With no required skills the preferred coverage is the score (what old vacancies got).
    """
    empty = {"score": 100.0, "hard_score": None, "soft_score": None, "required_score": None,
             "preferred_score": None, "strong": 0, "partial": 0, "missing": 0,
             "preferred_strong": 0, "preferred_partial": 0, "preferred_missing": 0,
             "units": [], "groups": [], "missing_required": [], "not_demonstrated_preferred": [],
             "classification_source": None, "details": []}
    if not jd_skills:
        return empty

    cls_skills = (classification or {}).get("skills", {})
    details = []
    for s in jd_skills:
        d = skill_match(s, resume_skills, exp_sentences, emb, extra_evidence)
        c = cls_skills.get(s)
        if c is None:
            c = {"requirement": "required" if classification is None else "preferred",
                 "group_id": None, "ambiguous": classification is not None,
                 "reason": "legacy: all skills required" if classification is None
                 else "ambiguous: not found in classification, defaulted to preferred"}
        d.update(requirement=c["requirement"], group_id=c.get("group_id"),
                 ambiguous=bool(c.get("ambiguous")), classification_reason=c.get("reason"))
        details.append(d)

    req_units = _build_units(details, "required")
    pref_units = _build_units(details, "preferred")
    req_score, pref_score = _blend(req_units), _blend(pref_units)

    if req_score is not None and pref_score is not None:
        score = req_score + (100.0 - req_score) * PREFERRED_BONUS_WEIGHT * (pref_score / 100.0)
    elif req_score is not None:
        score = req_score
    else:
        score = pref_score if pref_score is not None else 100.0

    def count(units, st):
        return sum(u["status"] == st for u in units)

    return {
        "score": round(clamp(score), 2),
        "hard_score": req_score if req_units else pref_score,
        "soft_score": None,
        "required_score": round(req_score, 2) if req_score is not None else None,
        "preferred_score": round(pref_score, 2) if pref_score is not None else None,
        "strong": count(req_units, "strong"), "partial": count(req_units, "partial"),
        "missing": count(req_units, "missing"),
        "preferred_strong": count(pref_units, "strong"), "preferred_partial": count(pref_units, "partial"),
        "preferred_missing": count(pref_units, "missing"),
        "units": req_units + pref_units,
        "groups": [{"group_id": u["group_id"], "members": u["members"], "requirement": u["requirement"],
                    "satisfied": u["score"] > 0, "satisfied_by": u["satisfied_by"], "status": u["status"]}
                   for u in req_units + pref_units if u["kind"] == "group"],
        "missing_required": [u["name"] for u in req_units if u["status"] == "missing"],
        "not_demonstrated_preferred": [u["name"] for u in pref_units if u["status"] == "missing"],
        "classification_source": (classification or {}).get("source", "legacy_all_required"),
        "details": details,
    }


def skill_explanation_parts(skills: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(strengths, concerns) wording for generate_explanation, from the SAME units used for scoring."""
    units = skills.get("units")
    if units is None:                       # saved result from before this patch
        return [], []
    strengths, concerns = [], []
    req = [u for u in units if u["requirement"] == "required"]
    pref = [u for u in units if u["requirement"] == "preferred"]

    def label(u):
        return f"one of {u['name']}" if u["kind"] == "group" else u["name"]

    got = [label(u) for u in req if u["status"] == "strong"]
    part = [label(u) for u in req if u["status"] == "partial"]
    miss = [label(u) for u in req if u["status"] == "missing"]
    if got:
        strengths.append(f"Clear evidence for {len(got)} of the {len(req)} required skill requirements, including {_names(got)}.")
    if part:
        strengths.append(f"Partial evidence for {_names(part)}.")
    if miss:
        concerns.append(f"Not demonstrated in the CV for {len(miss)} required skill "
                        f"requirement{'s' if len(miss) != 1 else ''}: {_names(miss)}.")
    pgot = [label(u) for u in pref if u["status"] in ("strong", "partial")]
    pmiss = [label(u) for u in pref if u["status"] == "missing"]
    if pgot:
        strengths.append(f"Also demonstrates preferred skills: {_names(pgot)}.")
    if pmiss:
        concerns.append(f"Optional skills not demonstrated: {_names(pmiss)} (these are preferred, not mandatory).")
    return strengths, concerns


# =====================================================================
# ROLE / DOMAIN
# =====================================================================

ROLE_GROUPS = {
    "accounting": {
        "accountant", "senior accountant", "staff accountant",
        "accounting specialist", "accounting officer", "bookkeeper",
        "accounts payable specialist", "accounts receivable specialist",
        "financial accountant",
    },
    "finance_analysis": {
        "financial analyst", "finance analyst", "investment analyst",
        "fp&a analyst", "financial planning analyst",
    },
    "human_resources": {
        "hr", "hr specialist", "hr manager", "human resources specialist",
        "recruiter", "talent acquisition",
    },
    "software_engineering": {
        "software engineer", "software developer", "backend developer",
        "frontend developer", "full stack developer", "python developer",
        "web developer",
    },
    "data": {
        "data scientist", "data analyst", "machine learning engineer",
        "ml engineer", "data engineer", "ai engineer",
    },
    "design": {
        "graphic designer", "ui designer", "ux designer", "ui/ux designer",
        "product designer", "web designer",
    },
    "marketing": {
        "marketing specialist", "digital marketer", "marketing manager",
        "seo specialist", "content marketer",
    },
    "sales": {
        "sales representative", "sales executive", "account executive",
        "business development executive", "sales manager",
    },
    "administration": {
        "administrative assistant", "office administrator",
        "administrative officer", "office manager",
    },
}

RELATED_ROLE_GROUPS = {
    frozenset(("accounting", "finance_analysis")): 50.0,
    frozenset(("software_engineering", "data")): 50.0,
    frozenset(("design", "marketing")): 50.0,
    frozenset(("marketing", "sales")): 50.0,
    frozenset(("human_resources", "administration")): 50.0,
}


def normalized_title(t: str) -> str:
    x = norm(t)
    x = re.sub(r"\b(junior|senior|lead|principal|associate|intern|i|ii|iii)\b", " ", x)
    return re.sub(r"\s+", " ", x).strip()


@lru_cache(maxsize=1)
def _normalized_role_groups() -> dict[str, frozenset[str]]:
    return {g: frozenset(normalized_title(x) for x in titles) for g, titles in ROLE_GROUPS.items()}


@lru_cache(maxsize=50_000)
def _role_group_str(title: str) -> Optional[str]:
    n = normalized_title(title)

    for g, normalized_titles in _normalized_role_groups().items():
        if n in normalized_titles:
            return g

    return None


def role_group(title: str) -> Optional[str]:
    return _role_group_str(title if isinstance(title, str) else clean(title))


def domain_from_text(text: str) -> set[str]:

    n = norm(text)
    found = set()

    anchors = {
        "banking": [
            "banking", "branch banking", "commercial bank", "retail bank", "loan",
            "credit", "mortgage", "financial institution", "deposit account", "bank branch",
        ],
        "insurance": ["insurance", "claims", "underwriting", "policyholder"],
        "healthcare": ["healthcare", "hospital", "clinic", "patient", "medical"],
        "retail": ["retail", "store", "merchandise", "point of sale", "inventory"],
        "manufacturing": ["manufacturing", "production line", "plant", "factory"],
        "technology": [
            "software", "saas", "technology", "cloud", "application development",
        ],
        "education": ["school", "university", "education", "student", "academic"],
        "government": [
            "government", "public sector", "municipal", "federal", "state agency",
        ],
        "accounting": [
            "accounting firm", "public accounting", "bookkeeping", "audit",
            "tax accounting", "general ledger",
        ],
    }

    for d, words in anchors.items():
        if any(contains_phrase(n, w) for w in words):
            found.add(d)

    return found


def domain_match(
    jd: dict[str, Any],
    entries: list[dict[str, Any]],
    role_titles: list[str],
) -> dict[str, Any]:

    jd_text = " ".join(
        [
            clean(jd.get("job_title")),
            clean(jd.get("summary")),
            *flat(jd.get("responsibilities", [])),
            *flat(jd.get("skills", [])),
        ]
    )

    jd_domains = domain_from_text(jd_text)

    cand_text = " ".join(
        role_titles
        + [clean(e.get("title")) + " " + clean(e.get("description")) for e in entries]
    )

    cand_domains = domain_from_text(cand_text)

    if "banking" in cand_domains and "accounting" in jd_domains and "banking" not in jd_domains:
        return {
            "score": 0.0,
            "status": "conflict",
            "jd_domains": sorted(jd_domains),
            "candidate_domains": sorted(cand_domains),
            "primary_candidate_domain": "banking",
        }

    if jd_domains & cand_domains:
        return {
            "score": 100.0,
            "status": "same",
            "jd_domains": sorted(jd_domains),
            "candidate_domains": sorted(cand_domains),
            "primary_candidate_domain": sorted(jd_domains & cand_domains)[0],
        }

    if not jd_domains or not cand_domains:
        return {
            "score": None,
            "status": "unknown",
            "jd_domains": sorted(jd_domains),
            "candidate_domains": sorted(cand_domains),
            "primary_candidate_domain": None,
        }

    return {
        "score": 0.0,
        "status": "different",
        "jd_domains": sorted(jd_domains),
        "candidate_domains": sorted(cand_domains),
        "primary_candidate_domain": sorted(cand_domains)[0],
    }


# =====================================================================
# EXPERIENCE
# =====================================================================

MONTHS = {
    m: i + 1
    for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())
}


def parse_date(v: Any, end: bool = False) -> Optional[date]:

    t = clean(v).lower()

    if not t:
        return None

    if re.search(r"\b(present|current|currently|now|ongoing|today|to date|till date)\b", t):
        return REF_DATE

    m = re.search(r"\b((?:19|20)\d{2})[-/]?([01]?\d)[-/]?([0-3]?\d)?\b", t)

    if m:
        try:
            return date(int(m.group(1)), max(1, min(12, int(m.group(2) or 1))), 1)
        except ValueError:
            pass

    m = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
        r"[a-z]*[ ,.-]+((?:19|20)\d{2})\b",
        t,
    )

    if m:
        return date(int(m.group(2)), MONTHS[m.group(1)[:3]], 1)

    m = re.search(r"\b((?:19|20)\d{2})\b", t)

    if m:
        return date(int(m.group(1)), 12 if end else 1, 1)

    return None


def get_entries(data: dict[str, Any]) -> list[dict[str, Any]]:

    raw = data.get("experience", [])

    if isinstance(raw, (dict, str)):
        raw = [raw]

    out = []

    for item in raw if isinstance(raw, list) else []:

        if isinstance(item, str):
            item = {"title": "", "description": item}

        if not isinstance(item, dict):
            continue

        title = clean(
            item.get("title") or item.get("job_title")
            or item.get("position") or item.get("role")
        )

        desc = clean(
            item.get("description") or item.get("responsibilities")
            or item.get("duties") or item.get("details") or item.get("achievements")
        )

        start = parse_date(item.get("start_date") or item.get("start") or item.get("from"))

        end = parse_date(item.get("end_date") or item.get("end") or item.get("to"), True)

        if not start or not end:

            period = clean(
                item.get("dates") or item.get("date")
                or item.get("duration") or item.get("period")
            )

            parts = re.split(r"\s+(?:-|–|—|to|until)\s+", period, maxsplit=1)

            if len(parts) == 2:
                start = start or parse_date(parts[0])
                end = end or parse_date(parts[1], True)

            elif period:
                start = start or parse_date(period)

                if re.search(r"present|current|now", period, re.I):
                    end = REF_DATE

        out.append(
            {
                "title": title,
                "description": desc,
                "start": start,
                "end": end,
                "sentences": sentences(desc),
            }
        )

    return out


def merge_years(intervals: list[tuple[date, date]]) -> float:

    good = sorted((a, b) for a, b in intervals if a and b and b >= a)

    if not good:
        return 0.0

    merged = [list(good[0])]

    for a, b in good[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    return sum((b - a).days for a, b in merged) / 365.25


def required_yoe(jd: dict[str, Any]) -> Optional[float]:

    text = " ".join(flat(jd.get("experience", [])) + [clean(jd.get("summary"))])

    nums = []

    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*\+?\s*years?\b", text.lower()):
        nums.append(float(m.group(1)))

    return min(nums) if nums else None



# ---------------- V21.4: role relevance + experience ----------------
# =====================================================================
# V21.4 PATCH — SECTION 2: ROLE RELEVANCE
# REPLACE role_match() and experience_match(); ADD the helpers and combine_role().
# role_group / normalized_title / domain_match / merge_years are untouched.
# =====================================================================

USE_SEMANTIC_TITLES = False   # title embeddings are off: slower, and responsibilities already add semantic evidence
GENERIC_TITLE_WORDS = {"engineer", "developer", "specialist", "manager", "officer", "executive",
                       "consultant", "coordinator", "assistant", "associate", "analyst"}
W_ENTRY_TITLE, W_ENTRY_RESP, W_ENTRY_SENIORITY = 0.25, 0.55, 0.10
MISSING_RESP_DISCOUNT = 0.60      # title/seniority-only evidence counts at 60%
UNCORROBORATED_RESP_CAP = 70.0    # semantic-only responsibility evidence is capped

_SENIORITY = [
    (r"\b(intern|trainee|apprentice)\b", 0),
    (r"\b(junior|jr|entry)\b", 1),
    (r"\b(senior|sr)\b", 3),
    (r"\b(lead|principal|staff)\b", 4),
    (r"\b(head|director|vp|chief|manager)\b", 5),
]
_LEAD_CUES = re.compile(r"\b(led|lead|leading|managed|owned|architected|mentored|supervised|spearheaded)\b", re.I)


def title_variants(title: str) -> list[str]:
    """Whole title plus its alternatives ('A / B', 'A or B'). Split only when every part is a multi-word title,
    so 'UI/UX Designer' stays whole."""
    t = clean(title)
    if not t:
        return []
    parts = [x.strip() for x in re.split(r"\s*(?:/|\||;|,|\bor\b)\s*", t, flags=re.I) if x.strip()]
    if len(parts) > 1 and all(len(tokens(x)) >= 2 for x in parts):
        return list(dict.fromkeys([t] + parts))
    return [t]


def seniority_level(text: str) -> Optional[int]:
    t = norm(text)
    lvl = None
    for pat, l in _SENIORITY:
        if re.search(pat, t):
            lvl = l if lvl is None else max(lvl, l)
    return lvl


def _title_pair(jd_v: str, cand: str, emb: Optional[Embedder]) -> tuple[float, str]:
    jg, cg = role_group(jd_v), role_group(cand)
    if jg and cg:
        if jg == cg:
            return 100.0, "same_family"
        if frozenset((jg, cg)) in RELATED_ROLE_GROUPS:
            return 50.0, "related_family"
        return 0.0, "different_family"
    nj, nc = normalized_title(jd_v), normalized_title(cand)
    if nj and nj == nc:
        return 100.0, "normalized_title"
    if norm(jd_v) and norm(jd_v) == norm(cand):
        return 100.0, "exact_title"
    a = set(tokens(nj)) - GENERIC_TITLE_WORDS
    b = set(tokens(nc)) - GENERIC_TITLE_WORDS
    if a and b and (a & b) and len(a & b) / min(len(a), len(b)) >= 1.0:
        return 50.0, "partial_title_overlap"
    if USE_SEMANTIC_TITLES and emb is not None and getattr(emb, "semantic", False) and nj and nc and emb.sim(nj, nc) >= 0.75:
        return 50.0, "semantic_title"        # embeddings never give more than "related"
    return 0.0, "unmapped_title"


def role_match(jd_title: str, candidate_titles: list[str], emb: Optional[Embedder] = None) -> dict[str, Any]:
    """
    TITLE evidence only. 'different' now means every candidate title mapped to a
    confirmed different role family; an unrecognised title is 'unmapped'
    (missing evidence, not incompatibility). combine_role() turns this plus the
    responsibility evidence into the final status.
    """
    if not candidate_titles:
        return {"score": 0.0, "title_score": 0.0, "status": "unknown", "evidence": None, "method": "no_title"}
    variants = title_variants(jd_title)
    best, evidence, method = 0.0, None, "none"
    methods = []
    for title in candidate_titles:
        for v in variants:
            s, m = _title_pair(v, title, emb)
            methods.append(m)
            if s > best:
                best, evidence, method = s, title, m
    if best == 0.0:
        method = "different_family" if all(m == "different_family" for m in methods) else "unmapped_title"
        status = "different" if method == "different_family" else "unmapped"
    else:
        status = "same" if best == 100 else "related"
    return {"score": best, "title_score": best, "status": status, "evidence": evidence, "method": method}


def _responsibility_evidence(jd_resp: list[str], sents: list[str], emb: Embedder):
    """(best single pair, mean best-match per JD responsibility) or None if no evidence."""
    jd_resp = [r for r in jd_resp if r]
    if not jd_resp or not sents:
        return None
    if getattr(emb, "semantic", False):
        emb.vectors(jd_resp + sents)      # one batched encode; sim() below then hits the cache
    per = [max(semantic_score(emb.sim(a, b)) for b in sents) for a in jd_resp]
    return max(per), sum(per) / len(per)


def _tool_corroboration(jd_skills: list[str], text: str) -> Optional[float]:
    hard = [s for s in jd_skills if canonical_skill(s) not in SOFT_LEX]
    if not hard:
        return None
    hits = sum(any(contains_phrase(text, p) for p in skill_phrases(s)) for s in hard)
    return 100.0 * hits / len(hard)


def _seniority_score(jd_level: Optional[int], title: str, desc: str) -> tuple[Optional[float], Optional[int]]:
    if jd_level is None:
        return None, None
    lvl = seniority_level(title)
    lvl = 2 if lvl is None else lvl
    if len(_LEAD_CUES.findall(desc)) >= 2:
        lvl = max(lvl, 3)               # scope/ownership evidence
    gap = jd_level - lvl
    return (100.0 if gap <= 0 else {1: 60.0, 2: 30.0}.get(gap, 0.0)), lvl


def experience_match(
    jd: dict[str, Any],
    entries: list[dict[str, Any]],
    emb: Embedder,
    interview_yoe: Optional[float],
) -> dict[str, Any]:

    jd_title = clean(jd.get("job_title") or jd.get("title"))
    resp = (
        flat(jd.get("responsibilities", []))
        or flat(jd.get("experience", []))
        or [clean(jd.get("summary"))]
    )
    jd_skills = flat(jd.get("skills", []))
    jd_level = seniority_level(jd_title)

    details = []
    relevant_intervals = []
    all_intervals = []

    for e in entries:
        text = f"{e['title']} {e['description']}"
        role = role_match(jd_title, [e["title"]] if e["title"] else [], emb)
        ev = _responsibility_evidence(resp, e["sentences"], emb)
        corr = _tool_corroboration(jd_skills, text)
        sen, ent_level = _seniority_score(jd_level, e["title"], e["description"])

        # title evidence: confirmed/partial/same count; unmapped or missing = no evidence (not a penalty)
        t = None if role["status"] in ("unmapped", "unknown") else role["score"]

        r_final = None
        if ev is not None:
            pair, cover = ev
            r = 0.35 * pair + 0.65 * cover
            if (t is None or t == 0) and (corr is None or corr < 20):
                r = min(r, UNCORROBORATED_RESP_CAP)   # semantic alone is not proof
            r_final = 0.8 * r + 0.2 * corr if corr is not None else r

        if r_final is not None:
            parts = [(W_ENTRY_RESP, r_final)]
            if t is not None:
                parts.append((W_ENTRY_TITLE, t))
            if sen is not None:
                parts.append((W_ENTRY_SENIORITY, sen))
            relevance = sum(w * s for w, s in parts) / sum(w for w, _ in parts)
            note = "title+responsibilities" if t is not None else "responsibilities (title not mapped)"
        else:
            parts = []
            if t is not None:
                parts.append((W_ENTRY_TITLE, t))
            if sen is not None and t is not None:
                parts.append((W_ENTRY_SENIORITY, sen))
            relevance = (sum(w * s for w, s in parts) / sum(w for w, _ in parts) * MISSING_RESP_DISCOUNT
                         if parts else 0.0)
            note = "responsibility evidence missing; title/seniority only"

        details.append(
            {
                "title": e["title"],
                "role_score": role["score"],
                "role_status": role["status"],
                "role_evidence": role["evidence"],
                "responsibility_semantic": round(ev[0], 2) if ev else 0.0,
                "responsibility_coverage": round(ev[1], 2) if ev else None,
                "responsibility_evidence": ev is not None,
                "tool_corroboration": round(corr, 2) if corr is not None else None,
                "seniority_score": sen,
                "entry_seniority_level": ent_level,
                "relevance": round(clamp(relevance), 2),
                "relevance_basis": note,
                "start": e["start"].isoformat() if e["start"] else None,
                "end": e["end"].isoformat() if e["end"] else None,
            }
        )

        if e["start"] and e["end"]:
            all_intervals.append((e["start"], e["end"]))
            if relevance >= REL_ENTRY_THRESHOLD:
                relevant_intervals.append((e["start"], e["end"]))

    ranked = sorted(details, key=lambda x: x["relevance"], reverse=True)
    top = ranked[:3]
    weights = [0.5, 0.3, 0.2]

    if top:
        quality = sum(d["relevance"] * w for d, w in zip(top, weights)) / sum(weights[: len(top)])
    else:
        quality = 0.0

    cv_total = merge_years(all_intervals) if all_intervals else None
    cv_rel = merge_years(relevant_intervals) if relevant_intervals else None

    # ---- experience-years block: UNCHANGED from V21.3 ----
    # Candidate-reported YOE is primary. CV relevant YOE is fallback.
    effective = interview_yoe if interview_yoe is not None else cv_rel

    source = (
        "candidate" if interview_yoe is not None
        else "cv" if cv_rel is not None
        else "unknown"
    )

    req = required_yoe(jd)

    if req is None or effective is None:
        yoe_score = None
    else:
        yoe_score = clamp(effective / req * 100) if req else 100.0

    if req is None:
        yoe_status = "not_required"
    elif effective is None:
        yoe_status = "unknown"
    elif effective >= req:
        yoe_status = "meets"
    else:
        yoe_status = "below"

    if yoe_score is None:
        score = quality
    else:
        score = 0.75 * quality + 0.25 * yoe_score

    return {
        "score": round(clamp(score), 2),
        "cv_total_yoe": round(cv_total, 2) if cv_total is not None else None,
        "cv_relevant_yoe": round(cv_rel, 2) if cv_rel is not None else None,
        "effective_yoe": round(effective, 2) if effective is not None else None,
        "yoe_source": source,
        "candidate_reported_yoe": round(interview_yoe, 2) if interview_yoe is not None else None,
        "required_yoe": req,
        "yoe_score": round(yoe_score, 2) if yoe_score is not None else None,
        "yoe_status": yoe_status,
        "max_relevance": ranked[0]["relevance"] if ranked else 0.0,
        "details": details,
    }


def combine_role(title_role: dict[str, Any], ex: dict[str, Any]) -> dict[str, Any]:
    """Final role verdict from title evidence + per-entry relevance. Status is always same/related/different/unknown."""
    out = dict(title_role)
    out["title_score"] = title_role.get("title_score", title_role["score"])
    out["title_status"] = title_role["status"]
    details = ex.get("details") or []
    if not details:
        out["score"] = 0.0
        out["relevance_score"] = 0.0
        if out["status"] == "unmapped":
            out["status"] = "unknown"
        return out

    best = max(details, key=lambda d: d["relevance"])
    rel = best["relevance"]
    has_resp = any(d["responsibility_evidence"] for d in details)
    ts = title_role["status"]

    if rel >= REL_ENTRY_THRESHOLD:
        status = "same" if ts == "same" else "related"
        method = "title_and_responsibilities" if ts in ("same", "related") else "responsibility_supported"
        evidence = best["title"] or title_role.get("evidence")
    elif ts == "different":
        status, method, evidence = "different", title_role["method"], title_role.get("evidence")
    elif not has_resp:
        status = ts if ts in ("same", "related") else "unknown"
        method, evidence = "responsibility_evidence_missing", title_role.get("evidence")
    elif ts in ("same", "related"):
        status, method, evidence = "related", "title_without_responsibility_support", title_role.get("evidence")
    else:
        status, method, evidence = "different", "no_title_or_responsibility_match", None

    out.update(score=round(rel, 2), relevance_score=round(rel, 2), status=status, method=method, evidence=evidence)
    return out


# =====================================================================
# EDUCATION
# =====================================================================

LEVELS = {
    "unknown": 0,
    "high_school": 1,
    "certificate": 2,
    "associate": 3,
    "bachelor": 4,
    "master": 5,
    "doctorate": 6,
}


def education_level(text: str) -> int:

    t = norm(text)

    if re.search(r"\b(phd|ph d|doctorate|doctoral)\b", t):
        return 6

    if re.search(
        r"\b(master|masters|mba|m phil|mcom|msc|ms|ma)\b"
        r"|\bm\.\s*(sc|com|phil|eng)\b",
        t,
    ):
        return 5

    if re.search(
        r"\b(bachelor|bachelors|b sc|bsc|b com|bcom|bba|ba|bs)\b"
        r"|\bb\.\s*(sc|com|a)\b",
        t,
    ):
        return 4

    if re.search(r"\b(associate|associates|aas|a a s)\b", t):
        return 3

    if re.search(r"\b(certificate|certification|diploma)\b", t):
        return 2

    if re.search(r"\b(high school|secondary school)\b", t):
        return 1

    return 0


EDUCATION_FIELD_PATTERNS = {
    "accounting": [r"\baccount(?:ing|ancy|ant)\b", r"\bbookkeep", r"\bcontab", r"\bcontador"],
    "finance": [r"\bfinance\b", r"\bfinancial\b", r"\bbanking\b", r"\btreasury\b"],
    "commerce": [r"\bcommerce\b", r"\bb\s*com\b", r"\bcomercio\b"],
    "business": [
        r"\bbusiness\b", r"\bmanagement\b", r"\badministration\b",
        r"\borganizational management\b",
    ],
    "economics": [r"\beconomics?\b"],
    "computer_science": [
        r"\bcomputer science\b", r"\bcomputing\b", r"\bsoftware engineering\b",
        r"\binformation technology\b", r"\binformation systems\b",
        r"\bcomputer engineering\b",
    ],
    "engineering": [
        r"\bengineering\b", r"\belectrical engineering\b",
        r"\bmechanical engineering\b", r"\bcivil engineering\b",
    ],
    "design": [
        r"\bdesign\b", r"\bgraphic design\b", r"\bvisual design\b",
        r"\bvisual arts\b", r"\bindustrial design\b", r"\bfashion design\b",
    ],
    "hci": [
        r"\bhuman computer interaction\b", r"\bhci\b", r"\binteraction design\b",
        r"\buser experience\b", r"\bux design\b",
    ],
    "marketing": [
        r"\bmarketing\b", r"\bdigital marketing\b", r"\badvertising\b",
        r"\bpublic relations\b", r"\bcommunications\b",
    ],
    "human_resources": [r"\bhuman resources\b", r"\bhr\b", r"\bhuman resource management\b"],
    "data": [
        r"\bdata science\b", r"\bdata analytics\b", r"\bdata analysis\b",
        r"\bstatistics\b", r"\bstatistical\b",
    ],
    "mathematics": [r"\bmathematics\b", r"\bmath\b"],
    "science": [r"\bscience\b", r"\bphysics\b", r"\bchemistry\b", r"\bbiology\b"],
    "healthcare": [
        r"\bmedicine\b", r"\bnursing\b", r"\bhealthcare\b",
        r"\bmedical\b", r"\bpublic health\b",
    ],
    "law": [r"\blaw\b", r"\blegal\b", r"\bjurisprudence\b"],
    "education": [r"\beducation\b", r"\bteaching\b", r"\bpedagogy\b"],
}


def education_fields(text: str) -> set[str]:

    t = norm(text)
    fields = set()

    for field, patterns in EDUCATION_FIELD_PATTERNS.items():
        if any(re.search(pattern, t) for pattern in patterns):
            fields.add(field)

    return fields


RELATED_EDUCATION_GROUPS = {
    "accounting": {"accounting", "finance", "commerce", "business", "economics"},
    "finance": {"finance", "accounting", "commerce", "business", "economics"},
    "commerce": {"commerce", "accounting", "finance", "business", "economics"},
    "business": {
        "business", "accounting", "finance", "commerce", "economics",
        "human_resources", "marketing",
    },
    "economics": {"economics", "finance", "accounting", "commerce", "business"},
    "computer_science": {
        "computer_science", "engineering", "data", "mathematics", "hci", "design",
    },
    "engineering": {"engineering", "computer_science", "data", "mathematics", "science"},
    "design": {"design", "hci", "computer_science", "marketing"},
    "hci": {"hci", "design", "computer_science", "engineering"},
    "data": {"data", "computer_science", "mathematics", "statistics", "engineering"},
    "marketing": {"marketing", "business", "design", "communications"},
    "human_resources": {"human_resources", "business", "management"},
    "healthcare": {"healthcare", "science"},
}


def education_fields_related(
    candidate_fields: set[str],
    required_fields: set[str],
) -> tuple[str, Optional[str], Optional[str]]:

    if not required_fields:
        return "pass", None, "no_field_requirement"

    if not candidate_fields:
        return "unknown", None, "candidate_field_unknown"

    exact = candidate_fields & required_fields

    if exact:
        return "pass", sorted(exact)[0], "exact_field"

    for required in required_fields:
        related = RELATED_EDUCATION_GROUPS.get(required, {required})
        overlap = candidate_fields & related

        if overlap:
            return "pass", sorted(overlap)[0], "related_field"

    return "fail", None, "unrelated_field"


def education_entries(data: dict[str, Any]) -> list[dict[str, Any]]:

    out = []

    for key in ("education", "certifications", "certificates"):

        raw = data.get(key, [])

        if isinstance(raw, dict):
            raw = [raw]

        if isinstance(raw, str):
            raw = [raw]

        if not isinstance(raw, list):
            continue

        for item in raw:

            if isinstance(item, dict):

                degree = clean(
                    item.get("degree") or item.get("qualification")
                    or item.get("title") or item.get("program")
                )
                field = clean(
                    item.get("field") or item.get("major") or item.get("specialization")
                )
                institution = clean(
                    item.get("institution") or item.get("school") or item.get("university")
                )
                year = clean(item.get("year") or item.get("graduation_year"))

                text = " ".join(x for x in [degree, field, institution, year] if x)

            else:
                text = clean(item)

            if not text:
                continue

            lvl = education_level(text)

            out.append(
                {
                    "text": text,
                    "level": lvl,
                    "level_name": next(
                        (k for k, v in LEVELS.items() if v == lvl), "unknown"
                    ),
                    "fields": sorted(education_fields(text)),
                    "kind": key,
                }
            )

    return out


def required_education_level(text: str) -> int:
    return education_level(text)


# ---------------------------------------------------------------------
# NEW: chatbot LLM education verdict
# ---------------------------------------------------------------------

_PASS_WORDS = {"pass", "passed", "meets", "met", "eligible", "yes"}
_FAIL_WORDS = {"fail", "failed", "does not meet", "not met", "ineligible", "no"}
_UNKNOWN_WORDS = {"unclear", "unknown", "uncertain", "insufficient"}
_UNRELATED_WORDS = {"unrelated", "different", "none", "wrong_field", "not related"}
_RELATED_WORDS = {"exact", "related", "same", "equivalent", "relevant"}


def parse_education_verdict(record: Any) -> Optional[dict[str, Any]]:
    """
    Reads the chatbot LLM's education judgement from a chatbot record.
    Returns None when the record carries only a raw answer (degree/field text),
    in which case the rule-based education matcher is used instead.
    """

    if not isinstance(record, dict):
        return None

    edu = record.get("education")

    if isinstance(record.get("education_verdict"), dict):
        src = record["education_verdict"]
    elif isinstance(edu, dict):
        nested = edu.get("verdict")
        src = nested if isinstance(nested, dict) else edu
    else:
        return None

    verdict = clean(src.get("verdict") or src.get("status")).lower()
    relation = clean(src.get("field_relation") or src.get("relation")).lower()
    meets_level = to_bool(src.get("meets_level"))
    raw_score = src.get("score")
    if raw_score is None:
        raw_score = src.get("education_score")
    score = to_float(raw_score)

    if not (verdict or relation or meets_level is not None or score is not None):
        return None

    if verdict in _PASS_WORDS:
        status = "pass"
    elif verdict in _FAIL_WORDS:
        status = "below_minimum" if meets_level is False else "wrong_field"
    elif verdict in _UNKNOWN_WORDS:
        status = "unknown"
    elif meets_level is False:
        status = "below_minimum"
    elif relation in _UNRELATED_WORDS:
        status = "wrong_field"
    elif relation in _RELATED_WORDS:
        status = "pass"
    elif score is not None:
        status = "pass" if score >= 50 else "wrong_field"
    else:
        status = "unknown"

    # Explicit hard facts win over a loose verdict word.
    if status == "pass" and meets_level is False:
        status = "below_minimum"
    elif status == "pass" and relation in _UNRELATED_WORDS:
        status = "wrong_field"

    if status == "pass":
        final_score: Optional[float] = clamp(score) if score is not None else 100.0
    elif status == "unknown":
        final_score = None
    else:
        final_score = 0.0

    return {
        "status": status,
        "score": final_score,
        "relation": relation or None,
        "degree": clean(edu.get("degree")) if isinstance(edu, dict) else "",
        "field": clean(edu.get("field")) if isinstance(edu, dict) else "",
        "level": clean(src.get("level") or src.get("degree_level")) or None,
        "reason": clean(src.get("reason")) or None,
    }


def match_education(
    jd: dict[str, Any],
    data: dict[str, Any],
    chatbot_rec: Any = None,
) -> dict[str, Any]:
    """Binary education marks out of 10, with a normalized matcher score."""

    requirements = [
        item for item in flat(jd.get("education", []))
        if norm(item) not in {
            "not required", "no education required",
            "education not required", "none", "n a", "na",
        }
    ]

    if not requirements:
        return {
            "score": None,
            "component_score": None,
            "max_score": 10.0,
            "status": "not_required",
            "hard_fail": False,
            "unknown": False,
            "source": "not_required",
            "details": [],
            "reason": "The JD does not require a specific education qualification.",
        }

    record = chatbot_rec if isinstance(chatbot_rec, dict) else {}
    assessment = record.get("education_assessment")

    if not isinstance(assessment, dict):
        assessment = record.get("education_evaluation")

    if not isinstance(assessment, dict):
        assessment = {}

    answer = clean(
        record.get("education_answer")
        or record.get("education_response")
        or assessment.get("candidate_answer")
    )

    answer_key = re.sub(
        r"[^a-z0-9]+", " ", answer.casefold()
    ).strip()

    no_answer_values = {
        "", "idk", "i dont know", "i do not know",
        "dont know", "do not know", "unknown",
        "n a", "na", "not sure", "prefer not to say",
    }

    no_answer = answer_key in no_answer_values

    def make_result(
        status: str,
        marks: Optional[float],
        component_score: Optional[float],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "score": marks,
            "component_score": component_score,
            "max_score": 10.0,
            "status": status,
            "hard_fail": status == "failed",
            "unknown": status == "unknown",
            "source": "chatbot_llm",
            "reason": reason,
            "candidate_answer": answer,
            "requirements": requirements,
            "details": [{
                "requirements": requirements,
                "status": "pass" if status == "passed" else status,
                "score": marks,
                "candidate_answer": answer,
                "field_method": "chatbot_llm",
                "reason": reason,
            }],
        }

    # No assessment yet: keep it pending during preliminary matching.
    if not assessment:
        if no_answer and (
            answer or record.get("interview_completed")
            or record.get("completed")
        ):
            return make_result(
                "failed", 0.0, 0.0,
                "The candidate did not provide the required education answer.",
            )

        if record.get("interview_completed") and not answer:
            return make_result(
                "failed", 0.0, 0.0,
                "The candidate completed the interview without providing the required education answer.",
            )

        return make_result(
            "unknown", None, None,
            "Education assessment is awaiting a chatbot response.",
        )

    # An explicit non-answer receives zero.
    if no_answer:
        return make_result(
            "failed", 0.0, 0.0,
            "The candidate did not provide the required education answer.",
        )

    raw_status = norm(assessment.get("status", ""))

    pass_statuses = {
        "pass", "passed", "meets", "met",
        "satisfied", "eligible",
    }

    fail_statuses = {
        "fail", "failed", "wrong field", "wrong_field",
        "below minimum", "below_minimum",
        "below requirement", "not met", "does not meet",
        "mismatch", "no answer", "not provided",
    }

    unknown_statuses = {
        "unclear", "unknown", "pending",
        "insufficient information", "not assessed",
    }

    reason = clean(
        assessment.get("reason")
        or assessment.get("explanation")
        or assessment.get("assessment")
    )

    # Binary education scoring: status determines marks, not Gemini's
    # numeric score. Only a confirmed pass can earn 10/10.
    if raw_status in pass_statuses:
        return make_result(
            "passed", 10.0, 100.0,
            reason or "The required degree level and field are satisfied.",
        )

    if raw_status in fail_statuses:
        return make_result(
            "failed", 0.0, 0.0,
            reason or "A mandatory education requirement was not satisfied.",
        )

    if raw_status in unknown_statuses:
        return make_result(
            "unknown", 0.0, 0.0,
            reason or "The education answer could not be assessed reliably.",
        )

    # Never turn an unexpected chatbot status into a passing result.
    return make_result(
        "unknown", 0.0, 0.0,
        "The chatbot returned an unrecognized education assessment status.",
    )


# =====================================================================
# INTERVIEW / CHATBOT RESPONSE PARSING
# =====================================================================

def _mark(v: Any) -> Optional[float]:
    f = to_float(v)
    if f is None:
        return None
    return max(0.0, min(MARKS_PER_QUESTION, f))



def parse_interview_breakdown(record: Any) -> dict[str, Any]:
    """
    Interview = 5 questions x 2 marks = 10 marks -> 0-100.
    Supports saved chatbot interview_answers as well as legacy formats.
    """
    out: dict[str, Any] = {
        "score": None,
        "marks": {},
        "total_marks": None,
    }

    if not isinstance(record, dict):
        return out

    iv = record.get("interview")

    if isinstance(iv, dict):
        raw = iv.get("scores") or iv.get("marks") or iv.get("answers")
        total = iv.get("total_marks")
        direct = iv.get("interview_score", iv.get("score"))
    else:
        raw = record.get("interview_marks") or record.get("interview_scores")
        total = record.get("interview_total_marks")
        direct = None

    # Actual live-chatbot response format.
    if raw is None:
        saved_answers = record.get("interview_answers")
        if isinstance(saved_answers, dict):
            raw = {
                key: value
                for key, value in saved_answers.items()
                if isinstance(value, dict)
                and value.get("score") is not None
            }

    if direct is None:
        direct = record.get("interview_score")

    marks: dict[str, float] = {}

    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                value = value.get("marks", value.get("score"))
            mark = _mark(value)
            if mark is not None:
                marks[str(key)] = mark

    elif isinstance(raw, list):
        for index, item in enumerate(raw, 1):
            if isinstance(item, dict):
                key = clean(item.get("id")) or f"q{index}"
                mark = _mark(item.get("marks", item.get("score")))
            else:
                key = f"q{index}"
                mark = _mark(item)

            if mark is not None:
                marks[key] = mark

    if marks:
        total_marks = min(INTERVIEW_MAX_MARKS, sum(marks.values()))
    else:
        total_marks = to_float(total)
        if total_marks is not None:
            total_marks = max(0.0, min(INTERVIEW_MAX_MARKS, total_marks))

    if total_marks is not None:
        score = total_marks / INTERVIEW_MAX_MARKS * 100.0
    else:
        direct_score = to_float(direct)
        score = clamp(direct_score) if direct_score is not None else None
        if score is not None:
            total_marks = score / 100.0 * INTERVIEW_MAX_MARKS

    out["score"] = round(score, 2) if score is not None else None
    out["marks"] = marks
    out["total_marks"] = (
        round(total_marks, 2) if total_marks is not None else None
    )

    return out


def parse_interview(record: Any) -> tuple[Optional[float], Optional[float]]:

    if not isinstance(record, dict):
        return None, None

    score = parse_interview_breakdown(record)["score"]

    yoe = record.get(
        "candidate_reported_yoe",
        record.get(
            "interview_yoe",
            record.get("reported_yoe", record.get("experience_years")),
        ),
    )

    if isinstance(yoe, dict):
        yoe = yoe.get("years", yoe.get("yoe"))

    if isinstance(yoe, str):

        if re.search(r"\b(idk|i don't know|unknown|n/a|none)\b", yoe, re.I):
            yoe = None
        else:
            m = re.search(r"\d+(?:\.\d+)?", yoe)
            yoe = float(m.group()) if m else None

    try:
        yoe = float(yoe) if yoe is not None and float(yoe) >= 0 else None
    except Exception:
        yoe = None

    return score, yoe


def parse_candidate_education(record: Any) -> Optional[dict[str, Any]]:

    if not isinstance(record, dict):
        return None

    education = record.get("education")

    if not education:
        education = record.get("education_answer")

    if isinstance(education, dict):

        degree = clean(
            education.get("degree") or education.get("qualification")
            or education.get("highest_degree")
        )
        field = clean(
            education.get("field") or education.get("major") or education.get("specialization")
        )
        institution = clean(education.get("institution") or "Candidate provided")
        year = clean(education.get("year") or education.get("graduation_year"))

        if not degree and not field:
            return None

        return {
            "degree": degree,
            "field": field,
            "institution": institution,
            "year": year,
            "source": "chatbot",
        }

    if isinstance(education, str):

        answer = clean(education)

        if not answer:
            return None

        return {
            "degree": answer,
            "field": "",
            "institution": "Candidate provided",
            "year": "",
            "source": "chatbot",
        }

    return None


def apply_chatbot_education(data: dict[str, Any], record: Any) -> dict[str, Any]:

    education = parse_candidate_education(record)

    if not education:
        return data

    updated = dict(data)

    old_education = updated.get("education", [])

    if isinstance(old_education, list):
        new_education = list(old_education)
    elif old_education:
        new_education = [old_education]
    else:
        new_education = []

    new_education.append(
        {
            "degree": education["degree"],
            "field": education["field"],
            "institution": education["institution"],
            "year": education["year"],
            "source": "chatbot",
        }
    )

    updated["education"] = new_education

    return updated


# =====================================================================
# HR QUESTION CONFIG
# =====================================================================

def load_question_config(path: Optional[str]) -> dict[str, Any]:
    """
    Optional per-job HR config:
    {
      "focus_domain": "UI/UX design, user research",
      "interview_questions": ["Fixed HR question 1", {"id": "hr_q2", "question": "..."}]
    }
    """

    if not path:
        return {}

    p = Path(path)

    if not p.exists():
        return {}

    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: could not load question config: {exc}")
        return {}

    if not isinstance(cfg, dict):
        return {}

    if "interview_questions" not in cfg and isinstance(cfg.get("questions"), list):
        cfg["interview_questions"] = cfg["questions"]

    return cfg


def build_interview_questions(config: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """HR fixed questions first (max 5), padded with the default questions up to 5."""

    config = config or {}

    out: list[dict[str, Any]] = []

    for i, q in enumerate(config.get("interview_questions") or [], 1):

        if isinstance(q, dict):
            text = clean(q.get("question"))
            qid = clean(q.get("id")) or f"hr_q{i}"
        else:
            text = clean(q)
            qid = f"hr_q{i}"

        if text:
            out.append(
                {
                    "id": qid,
                    "type": "interview",
                    "question": text,
                    "source": "hr",
                    "max_marks": MARKS_PER_QUESTION,
                }
            )

    out = out[:INTERVIEW_QUESTION_COUNT]

    for q in STANDARD_INTERVIEW_QUESTIONS:
        if len(out) >= INTERVIEW_QUESTION_COUNT:
            break
        out.append({**q, "source": "default", "max_marks": MARKS_PER_QUESTION})

    return out


# =====================================================================
# CHATBOT QUESTION GENERATION
# =====================================================================

def jd_requires_education(jd: dict[str, Any]) -> bool:
    return bool(flat(jd.get("education")))


def jd_requires_experience(jd: dict[str, Any]) -> bool:
    return required_yoe(jd) is not None


def jd_context(jd: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_title": clean(jd.get("job_title") or jd.get("title")),
        "summary": clean(jd.get("summary")),
        "skills": flat(jd.get("skills", [])),
        "responsibilities": flat(jd.get("responsibilities", [])),
        "education_requirement": flat(jd.get("education", [])),
        "experience_requirement": flat(jd.get("experience", [])),
        "required_yoe": required_yoe(jd),
    }


def build_verification_questions(
    jd: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Verification questions are asked ONLY when the JD actually requires
    education / years of experience. They are asked even if the CV already
    contains the information, because the candidate's answer is authoritative.
    """

    questions = []

    experience = result.get("experience", {})

    if jd_requires_education(jd):

        questions.append(
            {
                "id": "verify_education",
                "type": "education_verification",
                "field": "education",
                "question": "What is your highest completed degree and field of study?",
                "reason": "Confirm education against the JD requirement.",
                "required_information": flat(jd.get("education")),
            }
        )

    if jd_requires_experience(jd):

        job_title = clean(jd.get("job_title") or jd.get("title"))

        if job_title:
            question = (
                f"How many years of relevant professional experience do you have "
                f"in {job_title} or a closely related role?"
            )
        else:
            question = (
                "How many years of relevant professional experience do you have "
                "for this role?"
            )

        questions.append(
            {
                "id": "verify_experience_years",
                "type": "experience_verification",
                "field": "experience_years",
                "question": question,
                "reason": "Candidate-reported relevant experience replaces the CV estimate.",
                "internal_only": {
                    "cv_calculated_yoe": experience.get("cv_relevant_yoe"),
                    "required_yoe": experience.get("required_yoe"),
                },
            }
        )

    return questions


def build_chatbot_questions(
    jd: dict[str, Any],
    result: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:

    return build_verification_questions(jd, result) + build_interview_questions(config)


def build_chatbot_request(
    jd: dict[str, Any],
    result: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:

    questions = build_chatbot_questions(jd, result, config)

    verification = [q for q in questions if q["type"] != "interview"]

    return {
        "candidate_file": result["file"],
        "candidate_name": result["candidate_name"],
        "job_title": clean(jd.get("job_title") or jd.get("title")),
        "jd_context": jd_context(jd),
        "focus_domain": clean((config or {}).get("focus_domain")),
        "verification_required": bool(verification),
        "verification_questions": verification,
        "interview_questions": [q for q in questions if q["type"] == "interview"],
        "questions": questions,
        "scoring": {
            "interview_questions": INTERVIEW_QUESTION_COUNT,
            "marks_per_question": MARKS_PER_QUESTION,
            "max_marks": INTERVIEW_MAX_MARKS,
        },
        "current_matching": {
            "cv_score": result["cv_score"],
            "grade": result["grade_name"],
            "eligibility": result["eligibility"],
            "education_score": result["education_score"],
            "experience_score": result["experience_score"],
            "cv_relevant_yoe": result["experience"].get("cv_relevant_yoe"),
            "required_yoe": result["experience"].get("required_yoe"),
        },
    }


# =====================================================================
# CHATBOT RESPONSE FILE
# =====================================================================

def load_chatbot_responses(path: Optional[str]) -> dict[str, Any]:

    if not path:
        return {}

    p = Path(path)

    if not p.exists():
        return {}

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return {}

        if isinstance(data.get("candidates"), dict):
            return data["candidates"]

        return data

    except Exception as exc:
        print(f"WARNING: could not load chatbot response file: {exc}")
        return {}


def get_chatbot_record(responses: dict[str, Any], filename: str) -> dict[str, Any]:

    rec = responses.get(filename, {})

    if isinstance(rec, dict):
        return rec

    return {}


# =====================================================================
# SCORE COMPONENTS
# =====================================================================

def score_components(sk: float, ex: float, ed: Optional[float]) -> float:
    """
    Provisional CV score on a 0-100 scale. Weights are re-normalised over the
    components that apply (education is dropped when the JD has none).
    With education: (0.5*S + 0.3*E + 0.1*Ed) / 0.9
    Without:        (0.5*S + 0.3*E) / 0.8
    """

    parts = [(W_SKILLS, sk), (W_EXPERIENCE, ex)]

    if ed is not None:
        parts.append((W_EDUCATION, ed))

    return sum(w * s for w, s in parts) / sum(w for w, _ in parts)


# =====================================================================
# DECISION
# =====================================================================

def decide(
    cv_score: float,
    education: dict[str, Any],
    exp: dict[str, Any],
    role: dict[str, Any],
    domain: dict[str, Any],
) -> tuple[int, str, str]:

    explicit_fail = (
        education.get("hard_fail")
        or exp.get("yoe_status") == "below"
        or role.get("status") == "different"
        or domain.get("status") == "conflict"
    )

    verify = (
        education.get("unknown")
        or exp.get("yoe_status") == "unknown"
        or role.get("status") == "unknown"
        or domain.get("status") == "unknown"
    )

    if explicit_fail:
        grade = 1 if cv_score >= MODERATE_THRESHOLD else 0
        return grade, "ineligible", "Explicit minimum requirement failure."

    if verify:
        grade = (
            2 if cv_score >= STRONG_THRESHOLD
            else 1 if cv_score >= MODERATE_THRESHOLD
            else 0
        )
        return (
            grade,
            "needs_verification",
            "No explicit failure, but required information is unknown.",
        )

    grade = (
        2 if cv_score >= STRONG_THRESHOLD
        else 1 if cv_score >= MODERATE_THRESHOLD
        else 0
    )

    return grade, "eligible", "All evaluated hard requirements passed."


# =====================================================================
# MISSING INFORMATION
# =====================================================================

def missing_info(ed: dict[str, Any], ex: dict[str, Any]) -> list[dict[str, str]]:

    out = []

    if ed.get("unknown"):
        out.append(
            {
                "field": "education",
                "reason": "Education requirement could not be verified from the CV.",
                "question": "What is your highest completed degree and field of study?",
            }
        )

    if ex.get("yoe_status") == "unknown":
        out.append(
            {
                "field": "experience_years",
                "reason": "Relevant experience dates are insufficient.",
                "question": (
                    "How many years of relevant professional experience "
                    "do you have for this role?"
                ),
            }
        )

    return out


# =====================================================================
# PLAIN-LANGUAGE EXPLANATION
# =====================================================================

def _names(items: list[str], limit: int = 4) -> str:
    items = [clean(x) for x in items if clean(x)]
    shown = items[:limit]

    if not shown:
        return ""

    if len(shown) == 1:
        text = shown[0]
    else:
        text = ", ".join(shown[:-1]) + " and " + shown[-1]

    extra = len(items) - len(shown)

    if extra > 0:
        text += f" (and {extra} more)"

    return text


def _years(value: float) -> str:
    return f"{value:g}"


def _sentence(text: str) -> str:
    text = clean(text)
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def generate_explanation(jd: dict[str, Any], result: dict[str, Any]) -> str:
    """
    Plain-language summary of the grade and eligibility decision.
    Text only: it never changes a score, grade or eligibility.
    """

    grade = result["grade_name"]
    eligibility = result["eligibility"]
    title = clean(jd.get("job_title") or jd.get("title")) or "this role"

    skills = result.get("skills") or {}
    experience = result.get("experience") or {}
    education = result.get("education") or {}
    role = result.get("role_match") or {}
    domain = result.get("domain_match") or {}

    final = result.get("final_score")
    score = final if final is not None else result.get("cv_score")
    interview_done = bool(result.get("interview_completed"))

    strengths: list[str] = []
    concerns: list[str] = []
    blockers: list[str] = []
    to_confirm: list[str] = []

    # SKILLS (uses the same required / preferred / group classification as the score)
    s_strengths, s_concerns = skill_explanation_parts(skills)
    strengths.extend(s_strengths)
    concerns.extend(s_concerns)

    # EXPERIENCE (years)
    effective = experience.get("effective_yoe")
    required = experience.get("required_yoe")
    source_text = (
        "as stated by the candidate"
        if experience.get("yoe_source") == "candidate"
        else "calculated from the CV"
    )

    if required is not None and effective is not None:
        if effective >= required:
            strengths.append(
                f"Has about {_years(effective)} years of relevant experience "
                f"({source_text}); the job asks for {_years(required)}."
            )
        else:
            blockers.append(
                f"Has about {_years(effective)} years of relevant experience "
                f"({source_text}), below the {_years(required)} the job requires."
            )
    elif required is not None:
        to_confirm.append("how many years of relevant experience the candidate has")
    elif effective is not None:
        strengths.append(
            f"Has about {_years(effective)} years of relevant experience "
            f"({source_text})."
        )

    # ROLE
    role_status = role.get("status")

    if role_status == "same":
        evidence = clean(role.get("evidence"))
        strengths.append(
            f"Has held the same kind of role as {title}"
            + (f" ({evidence})." if evidence else ".")
        )
    elif role_status == "related":
        if role.get("method") == "responsibility_supported":
            strengths.append(
                f"Job titles differ from {title}, but the described responsibilities are relevant to it."
            )
        elif role.get("method") == "title_without_responsibility_support":
            concerns.append(
                "A similar job title is listed, but the described responsibilities do not clearly support it."
            )
        else:
            strengths.append("Has held a closely related role, though not exactly this one.")
    elif role_status == "different":
        blockers.append(
            f"Neither the job titles nor the described responsibilities match the {title} role."
        )
    elif role_status == "unknown":
        to_confirm.append(
            "the candidate's previous job titles or responsibilities, which are missing or unclear in the CV"
        )

    # INDUSTRY
    domain_status = domain.get("status")

    if domain_status == "same":
        strengths.append("Industry background matches the job.")
    elif domain_status == "conflict":
        blockers.append(
            f"Main industry background ({clean(domain.get('primary_candidate_domain'))}) "
            "does not fit this job's industry."
        )
    elif domain_status == "different":
        concerns.append("Industry background is different from the job's industry.")
    elif domain_status == "unknown":
        to_confirm.append("the candidate's industry background, which could not be worked out from the CV")

    # EDUCATION
    ed_status = education.get("status")
    ed_reason = clean(education.get("reason"))

    if ed_status == "passed":
        strengths.append(f"Meets the education requirement. {ed_reason}".strip())
    elif ed_status == "failed":
        blockers.append(f"Does not meet the education requirement. {ed_reason}".strip())
    elif ed_status == "unknown":
        to_confirm.append(
            "the education answer, which could not be assessed reliably"
            if interview_done
            else "education, which is checked during the interview"
        )

    # INTERVIEW
    marks = result.get("interview_total_marks")
    interview_score = result.get("interview_score")

    if interview_done and marks is not None and interview_score is not None:
        line = f"Scored {marks:.1f} out of 10 in the interview"

        if interview_score >= 75:
            strengths.append(line + ", a strong result.")
        elif interview_score >= 50:
            strengths.append(line + ", a moderate result.")
        else:
            concerns.append(line + ", a weak result.")

    # HEADLINE
    fit = grade.capitalize()
    score_text = f"{score:.1f}"

    if eligibility == "ineligible":
        headline = (
            f"Not eligible for {title}. At least one mandatory requirement is "
            f"not met, so this candidate ranks below every eligible candidate "
            f"(score {score_text} out of 100)."
        )
    elif eligibility == "needs_verification":
        headline = (
            f"{fit} fit for {title}, but some required information still has "
            f"to be confirmed before eligibility can be decided "
            f"(score {score_text} out of 100)."
        )
    else:
        headline = (
            f"{fit} fit for {title}. This candidate meets every requirement "
            f"checked and scores {score_text} out of 100."
        )

    # GRADE EXPLANATION
    if eligibility == "ineligible" and score >= STRONG_THRESHOLD:
        grade_note = (
            f"The score alone would be Strong ({STRONG_THRESHOLD:g} or above), "
            "but the grade is capped at Moderate because a mandatory "
            "requirement is not met."
        )
    elif grade == "STRONG":
        grade_note = f"Graded Strong because the score is {STRONG_THRESHOLD:g} or above."
    elif grade == "MODERATE":
        grade_note = (
            f"Graded Moderate because the score is between "
            f"{MODERATE_THRESHOLD:g} and {STRONG_THRESHOLD:g}."
        )
    else:
        grade_note = f"Graded Weak because the score is below {MODERATE_THRESHOLD:g}."

    lines = [headline, ""]

    def block(title_text: str, items: list[str]) -> None:
        if items:
            lines.append(title_text)
            lines.extend(f"- {_sentence(x)}" for x in items)
            lines.append("")

    block("Why not eligible:", blockers)
    block("What counts in their favour:", strengths)
    block("What counts against them:", concerns)
    block("Still to be confirmed:", to_confirm)

    if len(lines) == 2:
        lines.append("The CV contains limited evidence for evaluating this position.")
        lines.append("")

    lines.append(grade_note)

    if not interview_done:
        lines.append(
            "This score is provisional and based on the CV only. The final "
            "score is worked out after the interview."
        )

    return "\n".join(lines).strip()


# =====================================================================
# MAIN MATCHING
# =====================================================================

def match_one(
    jd: dict[str, Any],
    data: dict[str, Any],
    fname: str,
    emb: Embedder,
    chatbot_rec: Any = None,
    question_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Pass 1 (no chatbot_rec):  provisional CV score, final_score = None.
    Pass 2 (with chatbot_rec): candidate YOE + LLM education verdict + interview marks
                               are applied and final_score is computed.
    """

    chatbot_rec = chatbot_rec if isinstance(chatbot_rec, dict) else {}

    # Candidate's raw education answer is appended (used only when no LLM verdict exists).
    data = apply_chatbot_education(data, chatbot_rec)

    entries = get_entries(data)

    resume_skills = flat(data.get("skills", []))

    exp_text = [s for e in entries for s in e["sentences"]]

    candidate_titles = [e["title"] for e in entries if e["title"]]

    # SKILLS (deterministic required / preferred / alternative-group classification)
    skill_cls = classify_jd_skills_cached(jd)
    sk = match_skills(
        flat(jd.get("skills", [])), resume_skills, exp_text, emb, skill_cls,
        collect_extra_evidence(data),
    )

    # ROLE (title evidence only here; combined with responsibilities after experience_match)
    role_title = role_match(
        clean(jd.get("job_title") or jd.get("title")), candidate_titles, emb
    )

    # DOMAIN
    dom = domain_match(jd, entries, candidate_titles)

    # CHATBOT: interview score + candidate YOE
    i_score, interview_yoe = parse_interview(chatbot_rec)
    interview_breakdown = parse_interview_breakdown(chatbot_rec)

    # EXPERIENCE
    ex = experience_match(jd, entries, emb, interview_yoe)

    # ROLE: final verdict from title + responsibility + seniority evidence
    role = combine_role(role_title, ex)

    # Role/domain remain explicit dimensions.
    exp_score = (
        0.75 * ex["score"]
        + 0.15 * role["score"]
        + 0.10 * (dom["score"] if dom["score"] is not None else 50.0)
    )
    exp_score = clamp(exp_score)


    # EDUCATION — use the chatbot's complete response record
    ed = match_education(jd, data, chatbot_rec)

    # PROVISIONAL CV SCORE
    cv = score_components(
        sk["score"],
        exp_score,
        ed["component_score"],
    )


    # FINAL SCORE (after interview)
    final = 0.90 * cv + 0.10 * i_score if i_score is not None else None

    interview_completed = i_score is not None

    # DECISION (grade follows final score once the interview exists)
    grade, eligibility, decision_reason = decide(
        final if final is not None else cv,
        ed,
        ex,
        role,
        dom,
    )

    # REASONS
    reasons = []

    if role["status"] == "different":
        reasons.append("Candidate role is not compatible with the JD role.")

    if dom["status"] == "conflict":
        reasons.append("Candidate primary domain conflicts with the JD domain.")

    if ed["hard_fail"]:
        reasons.append("Education does not meet the required degree level/field.")

    if ex["yoe_status"] == "below":
        reasons.append(
            f"Relevant experience {ex['effective_yoe']} years is below "
            f"the required {ex['required_yoe']} years."
        )

    if sk["missing"]:
        reasons.append(
            f"{sk['missing']} required skill requirement(s) not demonstrated: "
            f"{_names(sk['missing_required'])}."
        )

    if (
        sk.get("classification_source") in ("default_no_wording", "structured_fields_only")
        and sk.get("required_score") is None
    ):
        reasons.append(
            "Original JD wording was not available to the matcher, so skills could not be "
            "classified as required or preferred (all treated as preferred)."
        )

    if sk.get("preferred_missing"):
        reasons.append(
            f"{sk['preferred_missing']} preferred skill(s) not demonstrated "
            "(optional; not counted as failures)."
        )

    if ed["unknown"]:
        reasons.append("Education needs verification.")

    if ex["yoe_status"] == "unknown":
        reasons.append("Relevant years of experience need verification.")

    if interview_yoe is not None:
        reasons.append(
            "Relevant YOE was provided by the candidate through chatbot verification."
        )

    if ed.get("source") == "chatbot_llm":
        reasons.append("Education was evaluated against the JD by the chatbot.")

    result = {
        "file": fname,
        "candidate_name": clean(data.get("name") or data.get("full_name")) or "Unknown",
        "grade": grade,
        "grade_name": {2: "STRONG", 1: "MODERATE", 0: "WEAK"}[grade],
        "eligibility": eligibility,
        "decision_reason": decision_reason,
        "cv_score": round(cv, 2),
        "final_score": round(final, 2) if final is not None else None,
        "score_type": "final" if final is not None else "provisional",
        "skills_score": round(sk["score"], 2),
        "experience_score": round(exp_score, 2),
        "education_score": round(ed["score"], 2) if ed["score"] is not None else None,
        "education_score_max": ed["max_score"],
        "education_source": ed.get("source"),
        "interview_score": i_score,
        "interview_marks": interview_breakdown["marks"],
        "interview_total_marks": interview_breakdown["total_marks"],
        "interview_completed": interview_completed,
        "interview_pending": not interview_completed,
        "role_match": role,
        "domain_match": dom,
        "skills": sk,
        "skill_classification": skill_cls,
        "experience": ex,
        "education": ed,
        "reasons": reasons,
        "missing_information": missing_info(ed, ex),
        "interview_yoe_used": interview_yoe,
        "cv_yoe_retained": ex["cv_relevant_yoe"],
        "yoe_source": ex["yoe_source"],
        "candidate_reported_yoe": ex["candidate_reported_yoe"],
        "chatbot_verification_applied": bool(
            isinstance(chatbot_rec.get("education_assessment"), dict)
            or parse_candidate_education(chatbot_rec)
            or interview_yoe is not None
        ),
        "plain_language_explanation": "",
    }

    result["plain_language_explanation"] = generate_explanation(jd, result)

    result["chatbot_request"] = build_chatbot_request(jd, result, question_config)

    return result


# Public alias for Flask / chatbot integration.
match_candidate = match_one


# =====================================================================
# EVALUATION
# =====================================================================

def load_labels(path: str) -> dict[str, int]:

    labels = {}

    with open(path, newline="", encoding="utf-8") as f:

        for row in csv.DictReader(f):

            fn = (row.get("file") or "").strip()
            lab = (row.get("label") or "").strip()

            if fn and lab:
                labels[fn if fn.endswith(".json") else fn + ".json"] = int(lab)

    return labels


def macro_f1(y, p):

    vals = []

    for c in (0, 1, 2):

        tp = sum(a == c and b == c for a, b in zip(y, p))
        fp = sum(a != c and b == c for a, b in zip(y, p))
        fn = sum(a == c and b != c for a, b in zip(y, p))

        pr = tp / (tp + fp) if tp + fp else 0
        rc = tp / (tp + fn) if tp + fn else 0

        vals.append(2 * pr * rc / (pr + rc) if pr + rc else 0)

    return sum(vals) / 3


def auc(scores, positives):

    pos = [s for s, p in zip(scores, positives) if p]
    neg = [s for s, p in zip(scores, positives) if not p]

    if not pos or not neg:
        return float("nan")

    return sum(
        1 if a > b else 0.5 if a == b else 0
        for a in pos
        for b in neg
    ) / (len(pos) * len(neg))


def evaluate(results: list[dict[str, Any]], labels: dict[str, int]) -> None:

    rows = [r for r in results if r["file"] in labels]

    if not rows:
        print("No label filenames matched.")
        return

    y = [labels[r["file"]] for r in rows]
    p = [r["grade"] for r in rows]

    n = len(rows)

    conf = [
        [sum(a == i and b == j for a, b in zip(y, p)) for j in range(3)]
        for i in range(3)
    ]

    acc = sum(a == b for a, b in zip(y, p)) / n
    within = sum(abs(a - b) <= 1 for a, b in zip(y, p)) / n

    scores = [
        r["final_score"] if r["final_score"] is not None else r["cv_score"]
        for r in rows
    ]

    print("\n" + "=" * 82)
    print(f"RESUMEMATCH AI V21.3 EVALUATION (n={n})")
    print("=" * 82)
    print(f"Exact accuracy (3-class)    : {acc:.1%}")
    print(f"Within one level             : {within:.1%}")
    print(f"Macro F1                     : {macro_f1(y, p):.3f}")
    print(f"AUC Strong vs Rest           : {auc(scores, [v == 2 for v in y]):.3f}")
    print(f"AUC Acceptable vs Weak       : {auc(scores, [v >= 1 for v in y]):.3f}")
    print("Confusion matrix (rows=human, cols=system)")
    print("             Sys0 Sys1 Sys2")

    for i, row in enumerate(conf):
        print(f"Human{i:<5}     {row[0]:>4} {row[1]:>4} {row[2]:>4}")

    for c, name in ((2, "Strong"), (1, "Moderate"), (0, "Weak")):

        tp = conf[c][c]

        pr = tp / max(1, sum(conf[i][c] for i in range(3)))
        rc = tp / max(1, sum(conf[c]))

        f = 2 * pr * rc / (pr + rc) if pr + rc else 0

        print(f"{name:<12} precision={pr:.1%} recall={rc:.1%} F1={f:.1%}")

    print("\nTop disagreements:")

    for r in sorted(rows, key=lambda x: -abs(x["grade"] - labels[x["file"]]))[:10]:

        h = labels[r["file"]]

        if h != r["grade"]:
            print(
                f"  {r['file']}: human={h}, system={r['grade']} "
                f"({r['grade_name']}), score={r['cv_score']:.1f}, "
                f"eligibility={r['eligibility']}"
            )


# =====================================================================
# RANKING
# =====================================================================

def rank_key(r: dict[str, Any]):

    status_order = {"eligible": 2, "needs_verification": 1, "ineligible": 0}

    score = r["final_score"] if r["final_score"] is not None else r["cv_score"]

    return (
        status_order.get(r["eligibility"], 0),
        score,
        r["skills_score"],
        r["experience_score"],
        r["education_score"] if r["education_score"] is not None else -1,
    )


# =====================================================================
# WRITE CHATBOT REQUESTS
# =====================================================================

def write_chatbot_requests(requests: list[dict[str, Any]], path: str) -> None:

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": "V21.3",
        "purpose": "Verification and interview questions for ResumeMatch AI",
        "requests": requests,
    }

    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved chatbot requests: {p}")


# =====================================================================
# RUN
# =====================================================================

def run(args):

    jd = json.loads(Path(args.jd).read_text(encoding="utf-8"))

    emb = Embedder(args.model)

    chatbot_responses = load_chatbot_responses(args.chatbot_response)

    question_config = load_question_config(args.question_config)

    paths = sorted(Path(args.resumes).glob("*.json"))

    if args.limit:
        paths = paths[: args.limit]

    results = []
    chatbot_requests = []

    for i, p in enumerate(paths, 1):

        try:

            data = json.loads(p.read_text(encoding="utf-8"))

            chatbot_rec = get_chatbot_record(chatbot_responses, p.name)

            r = match_one(jd, data, p.name, emb, chatbot_rec, question_config)

            results.append(r)

            # Chatbot request only for candidates who have not interviewed yet.
            request = r["chatbot_request"]

            if request["questions"] and not r["interview_completed"]:
                chatbot_requests.append(request)

            score_for_display = (
                r["final_score"] if r["final_score"] is not None else r["cv_score"]
            )

            print(
                f"[{i}/{len(paths)}] {p.name} -> {r['grade_name']} | "
                f"{r['eligibility']} | CV={r['cv_score']:.1f} | "
                f"Score={score_for_display:.1f} ({r['score_type']})"
            )

        except Exception as exc:
            print(f"[{i}/{len(paths)}] ERROR {p.name}: {exc}")

    # Ranking
    results.sort(key=rank_key, reverse=True)

    for i, r in enumerate(results, 1):
        r["rank"] = i

    write_chatbot_requests(chatbot_requests, args.chatbot_request)

    out = {
        "version": "V21.3",
        "embedding_model": args.model,
        "semantic_embeddings": emb.semantic,
        "weights": {
            "skills": W_SKILLS,
            "experience": W_EXPERIENCE,
            "education": W_EDUCATION,
            "interview": W_INTERVIEW,
        },
        "thresholds": {
            "strong": STRONG_THRESHOLD,
            "moderate": MODERATE_THRESHOLD,
        },
        "rules": {
            "missing_education": "verification",
            "related_education_field": "accepted",
            "wrong_education_field": "fail",
            "below_required_degree": "fail",
            "candidate_reported_yoe": "primary",
            "cv_relevant_yoe": "fallback",
            "idk_yoe": "cv_fallback",
            "interview": "5 questions x 2 marks = 10 marks -> 0-100",
            "verification_questions": "asked only when the JD requires education / experience",
            "education_source": "chatbot_llm verdict when provided, else cv_rules",
            "score_before_interview": "provisional (cv_score)",
            "score_after_interview": "0.90 * cv_score + 0.10 * interview_score",
            "llm_core_score": False,
        },
        "job_description": jd,
        "chatbot_request_file": str(args.chatbot_request),
        "chatbot_response_file": str(args.chatbot_response) if args.chatbot_response else None,
        "results": results,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    csv_path = Path(args.out).with_suffix(".csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:

        w = csv.writer(f)

        w.writerow(
            [
                "rank", "file", "candidate", "eligibility", "grade", "score_type",
                "cv_score", "interview_score", "final_score", "skills", "experience",
                "education", "education_source", "role", "domain", "yoe_source",
                "cv_yoe", "candidate_yoe", "reasons", "verify", "plain_explanation",
            ]
        )

        for r in results:
            w.writerow(
                [
                    r["rank"],
                    r["file"],
                    r["candidate_name"],
                    r["eligibility"],
                    r["grade_name"],
                    r["score_type"],
                    r["cv_score"],
                    r["interview_score"],
                    r["final_score"],
                    r["skills_score"],
                    r["experience_score"],
                    r["education_score"],
                    r["education_source"],
                    r["role_match"]["status"],
                    r["domain_match"]["status"],
                    r["yoe_source"],
                    r["cv_yoe_retained"],
                    r["candidate_reported_yoe"],
                    " | ".join(r["reasons"]),
                    ",".join(x["field"] for x in r["missing_information"]),
                    r["plain_language_explanation"],
                ]
            )

    print(f"\nSaved JSON: {args.out}")
    print(f"Saved CSV : {csv_path}")
    print(f"Chatbot requests: {len(chatbot_requests)}")

    if args.labels:
        evaluate(results, load_labels(args.labels))


# =====================================================================
# CLI
# =====================================================================

def main():

    ap = argparse.ArgumentParser(
        description="ResumeMatch AI V21.3 - matching + chatbot verification + interview"
    )

    ap.add_argument("--jd", default=str(DEFAULT_JD))
    ap.add_argument("--resumes", default=str(DEFAULT_RESUME_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--labels", default=None)

    ap.add_argument(
        "--chatbot-response",
        default=None,
        help="JSON file returned by the chatbot with verification/interview results.",
    )

    ap.add_argument(
        "--chatbot-request",
        default=str(DEFAULT_CHATBOT_REQUEST),
        help="Where the matcher writes questions for the chatbot.",
    )

    ap.add_argument(
        "--question-config",
        default=None,
        help="Optional HR question config JSON (focus_domain + fixed interview questions).",
    )

    ap.add_argument("--model", default=EMBED_MODEL)

    args = ap.parse_args()

    run(args)


if __name__ == "__main__":
    main()