from pathlib import Path
import json
import os
import time

from google import genai
from pydantic import BaseModel, Field
from typing import Optional, List


# ============================================================
# SETTINGS
# ============================================================

PROJECT_ROOT = Path(r"D:\projects\Resume_Screening_AI")

INPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "cleaned_resume_text"
)

OUTPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "structured_resumes_LLM"
)

MODEL_NAME = "gemini-3.5-flash-lite"

# IMPORTANT:
# None = process ALL resumes
TEST_LIMIT = None

# Wait between successful API requests.
# Keep this small for now.
REQUEST_DELAY = 1.0

# Number of retries for temporary API failures
MAX_RETRIES = 5


# ============================================================
# PYDANTIC SCHEMA
# ============================================================

class Experience(BaseModel):
    job_title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)


class Education(BaseModel):
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    institution: Optional[str] = None
    location: Optional[str] = None
    graduation_year: Optional[str] = None
    gpa: Optional[str] = None


class ResumeSchema(BaseModel):
    name: Optional[str] = None

    email: List[str] = Field(default_factory=list)
    phone: List[str] = Field(default_factory=list)

    location: Optional[str] = None

    linkedin: Optional[str] = None
    github: Optional[str] = None

    summary: Optional[str] = None

    skills: List[str] = Field(default_factory=list)

    experience: List[Experience] = Field(default_factory=list)

    education: List[Education] = Field(default_factory=list)

    certifications: List[str] = Field(default_factory=list)

    languages: List[str] = Field(default_factory=list)

    projects: List[str] = Field(default_factory=list)

    achievements: List[str] = Field(default_factory=list)

    interests: List[str] = Field(default_factory=list)


# ============================================================
# GEMINI CLIENT
# ============================================================

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY was not found.\n"
        "Load it in PowerShell first using:\n"
        '$env:GEMINI_API_KEY = '
        '[Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")'
    )

client = genai.Client(api_key=API_KEY)


# ============================================================
# PROMPT
# ============================================================

SYSTEM_INSTRUCTIONS = """
You are a professional resume information extraction system.

Your task is to convert the supplied cleaned resume text into
structured JSON according to the provided schema.

IMPORTANT RULES:

1. Extract information ONLY from the supplied resume.
2. NEVER invent information.
3. If information is not present, use null or an empty list.
4. Preserve multiple jobs as separate experience records.
5. Keep each job's responsibilities with the correct job.
6. Do NOT combine different jobs into one experience record.
7. Do NOT confuse a person's name with a company name.
8. Do NOT confuse education with employment.
9. Do NOT treat references as the candidate's own phone number,
   email, job or experience.
10. The summary field should contain the actual professional summary,
    objective, profile, or introductory paragraph if present.
11. Do NOT put a skills list or HIGHLIGHTS section into summary.
12. Extract meaningful professional and technical skills into skills.
13. Keep skills as short individual items, not paragraphs.
14. Extract every identifiable work experience.
15. Preserve job titles.
16. Preserve company names.
17. Preserve locations when available.
18. Preserve dates as they appear in the resume.
19. If a date is missing, use null.
20. If only one side of a date range exists, preserve the available side.
21. Keep responsibilities as separate items whenever possible.
22. Education records must be separate from experience.
23. Preserve degree, field of study, institution, location, graduation
    year and GPA when available.
24. Certifications should contain actual certifications only.
25. Languages should contain HUMAN LANGUAGES only.
    Examples: English, Spanish, French, Urdu.
26. Do NOT classify programming languages, software, accounting standards,
    or technologies as human languages.
    For example:
    Python, Java, SQL, GAAP, SAP, Excel are NOT human languages.
27. Projects should contain actual projects mentioned in the resume.
28. Achievements should contain actual achievements, awards or honors.
29. Interests should contain actual hobbies/interests if clearly stated.
30. LinkedIn and GitHub should only be populated when clearly present.
31. Correct only obvious OCR mistakes when the intended text is clear.
32. Do not rewrite or embellish the candidate's information.
33. Do not hallucinate missing names, companies, dates, degrees,
    skills, certifications or other information.
34. When uncertain, prefer null or an empty list.
35. Keep the extracted information faithful to the source.
"""


# ============================================================
# BUILD PROMPT
# ============================================================

def build_prompt(resume_text: str) -> str:

    return f"""
{SYSTEM_INSTRUCTIONS}

Now extract the following resume.

---------------- RESUME TEXT ----------------

{resume_text}

-------------- END RESUME TEXT --------------

Return ONLY the structured JSON matching the provided schema.
"""


# ============================================================
# GEMINI EXTRACTION
# ============================================================

def structure_resume(resume_text: str):

    prompt = build_prompt(resume_text)

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ResumeSchema,
                    "temperature": 0,
                },
            )

            # ------------------------------------------------
            # Preferred structured response
            # ------------------------------------------------

            if getattr(response, "parsed", None) is not None:

                parsed = response.parsed

                if isinstance(parsed, ResumeSchema):
                    return parsed.model_dump()

                if hasattr(parsed, "model_dump"):
                    return parsed.model_dump()

                if isinstance(parsed, dict):
                    return parsed

            # ------------------------------------------------
            # Fallback: parse JSON text
            # ------------------------------------------------

            text = getattr(response, "text", None)

            if text:

                text = text.strip()

                # Remove accidental markdown fences
                if text.startswith("```json"):
                    text = text[7:]

                elif text.startswith("```"):
                    text = text[3:]

                if text.endswith("```"):
                    text = text[:-3]

                text = text.strip()

                data = json.loads(text)

                # Validate against schema
                validated = ResumeSchema.model_validate(data)

                return validated.model_dump()

            raise ValueError("Gemini returned no usable structured response.")

        except Exception as e:

            last_error = e

            print(
                f"      Attempt {attempt}/{MAX_RETRIES} failed: "
                f"{type(e).__name__}: {e}"
            )

            if attempt < MAX_RETRIES:

                # Increasing wait time
                wait_time = min(5 * attempt, 30)

                print(f"      Waiting {wait_time} seconds...")

                time.sleep(wait_time)

    raise RuntimeError(
        f"Gemini failed after {MAX_RETRIES} attempts: {last_error}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GEMINI RESUME STRUCTURING")
    print("=" * 70)

    print(f"Input : {INPUT_FOLDER}")
    print(f"Output: {OUTPUT_FOLDER}")
    print(f"Model : {MODEL_NAME}")
    print()

    if not INPUT_FOLDER.exists():

        raise FileNotFoundError(
            f"Input folder does not exist:\n{INPUT_FOLDER}"
        )

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # rglob because TXT files are inside category folders
    # --------------------------------------------------------

    txt_files = sorted(
        INPUT_FOLDER.rglob("*.txt")
    )

    print(f"Found {len(txt_files)} TXT files.")

    if not txt_files:

        print("No TXT files found.")
        return

    # --------------------------------------------------------
    # Optional test limit
    # --------------------------------------------------------

    if TEST_LIMIT is not None:

        txt_files = txt_files[:TEST_LIMIT]

        print(
            f"TEST_LIMIT enabled: processing "
            f"{len(txt_files)} files."
        )

    else:

        print(
            f"Processing ALL {len(txt_files)} resumes."
        )

    print()

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    processed = 0
    skipped = 0
    failed = 0

    start_time = time.time()

    # --------------------------------------------------------
    # Process files
    # --------------------------------------------------------

    for index, txt_path in enumerate(txt_files, start=1):

        relative_path = txt_path.relative_to(INPUT_FOLDER)

        # Keep category folder structure
        output_path = (
            OUTPUT_FOLDER
            / relative_path
        ).with_suffix(".json")

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        print(
            f"[{index}/{len(txt_files)}] "
            f"{relative_path}"
        )

        # ----------------------------------------------------
        # Skip already processed
        # ----------------------------------------------------

        if output_path.exists():

            print("    SKIPPED - JSON already exists")

            skipped += 1

            continue

        # ----------------------------------------------------
        # Read TXT
        # ----------------------------------------------------

        try:

            resume_text = txt_path.read_text(
                encoding="utf-8",
                errors="replace"
            )

        except Exception as e:

            print(f"    ERROR reading TXT: {e}")

            failed += 1

            continue

        if not resume_text.strip():

            print("    SKIPPED - empty TXT")

            failed += 1

            continue

        print(
            f"    Characters: {len(resume_text):,}"
        )

        # ----------------------------------------------------
        # Gemini
        # ----------------------------------------------------

        try:

            structured = structure_resume(
                resume_text
            )

            # ------------------------------------------------
            # Save JSON
            # ------------------------------------------------

            with output_path.open(
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    structured,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            processed += 1

            print(
                f"    SAVED -> {output_path.relative_to(PROJECT_ROOT)}"
            )

        except Exception as e:

            print(
                f"    FAILED: {type(e).__name__}: {e}"
            )

            failed += 1

        # ----------------------------------------------------
        # Delay
        # ----------------------------------------------------

        if index < len(txt_files):

            time.sleep(REQUEST_DELAY)

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    elapsed = time.time() - start_time

    minutes = elapsed / 60

    print()
    print("=" * 70)
    print("STRUCTURING COMPLETE")
    print("=" * 70)

    print(f"Total found : {len(txt_files)}")
    print(f"Processed   : {processed}")
    print(f"Skipped     : {skipped}")
    print(f"Failed      : {failed}")

    print(
        f"Time        : {minutes:.1f} minutes"
    )

    print()
    print(f"JSON output:")
    print(OUTPUT_FOLDER)

    print("=" * 70)


# ============================================================
# REALTIME SINGLE CV STRUCTURING
# ============================================================

def structure_uploaded_resume(
    input_path,
    output_path
):
    """
    Structure one realtime cleaned resume TXT.

    Used by the recruitment application.
    Does NOT run the batch structuring process.
    """

    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Cleaned resume file not found: {input_path}"
        )

    resume_text = input_path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    if not resume_text.strip():
        raise ValueError(
            "Cleaned resume text is empty."
        )

    # --------------------------------------------------------
    # Send one resume to Gemini
    # --------------------------------------------------------

    structured = structure_resume(
        resume_text
    )

    if not structured:
        raise RuntimeError(
            "Gemini returned empty structured resume."
        )

    # --------------------------------------------------------
    # Save JSON
    # --------------------------------------------------------

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            structured,
            f,
            indent=2,
            ensure_ascii=False
        )

    return {
        "data": structured,
        "output_path": str(output_path)
    }


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()