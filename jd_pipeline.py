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


# ============================================================
# INPUT / OUTPUT
# ============================================================

INPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "job_description_text"
)

OUTPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "structured_job_descriptions_LLM"
)


# ============================================================
# GEMINI SETTINGS
# ============================================================

MODEL_NAME = "gemini-3.5-flash-lite"

# TEST FIRST
# Change to None only after checking the results.
TEST_LIMIT = None

REQUEST_DELAY = 1.0

MAX_RETRIES = 5


# ============================================================
# PYDANTIC SCHEMA
# ============================================================

class JobDescriptionSchema(BaseModel):

    # --------------------------------------------------------
    # Job title
    # --------------------------------------------------------

    job_title: Optional[str] = None

    # --------------------------------------------------------
    # Main job overview / description
    # --------------------------------------------------------

    summary: Optional[str] = None

    # --------------------------------------------------------
    # Skills
    # --------------------------------------------------------

    skills: List[str] = Field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Experience requirements
    # --------------------------------------------------------

    experience: List[str] = Field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Education requirements
    # --------------------------------------------------------

    education: List[str] = Field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Job responsibilities
    # --------------------------------------------------------

    responsibilities: List[str] = Field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Human language requirements
    # --------------------------------------------------------

    languages: List[str] = Field(
        default_factory=list
    )

    # --------------------------------------------------------
    # Job location
    # --------------------------------------------------------

    location: Optional[str] = None


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


client = genai.Client(
    api_key=API_KEY
)


# ============================================================
# SYSTEM INSTRUCTIONS
# ============================================================

SYSTEM_INSTRUCTIONS = """

You are a professional Job Description Information Extraction System.

Your task is to convert the supplied job description into structured
JSON according to the provided schema.

The job descriptions may come from different industries, job roles,
companies, countries, and document formats.

They may be:

- well formatted
- poorly formatted
- plain paragraphs
- bullet lists
- extracted from PDF
- extracted from Word documents
- OCR text
- missing section headings
- using unusual section headings
- using inline section headings
- using different ordering of information

Your job is to understand the meaning of the supplied text and
extract the information faithfully.

============================================================
GENERAL RULES
============================================================

1. Extract information ONLY from the supplied job description.

2. NEVER invent information.

3. NEVER assume information that is not present.

4. If information is genuinely absent, use null or an empty list.

5. Preserve the original meaning of the job description.

6. Do not add information based on general knowledge.

7. Do not create requirements simply because they are common
   for the particular job title.

8. Do not infer a specific number of years of experience unless
   the JD states it.

9. Do not rewrite the job description into a different meaning.

10. Minor correction of an obvious OCR/extraction error is allowed
    only when the intended word is completely clear.

============================================================
JOB TITLE
============================================================

Extract the actual position title.

Examples:

- Data Analyst
- Graphic Designer
- Software Engineer
- Accountant
- HR Manager
- Marketing Specialist
- Video Editor

Do not invent a job title from the responsibilities.

============================================================
SUMMARY
============================================================

Extract the main overview or description of the position.

Possible source sections include:

- Job Overview
- About the Role
- Position Summary
- Job Summary
- About the Position
- Description
- Profile
- Objective

If there is no explicit summary section, use the main introductory
description of the role if one exists.

Do not create a new summary from unrelated information.

============================================================
SKILLS
============================================================

Extract skills explicitly mentioned in the JD.

Skills may include:

- technical skills
- software
- tools
- programming languages
- frameworks
- analytical skills
- design skills
- business skills
- communication skills
- domain knowledge
- professional skills

Examples:

- Python
- SQL
- Excel
- Power BI
- Adobe Photoshop
- Figma
- Data Analysis
- Project Management
- Communication
- Critical Thinking

Keep each skill as a separate item whenever possible.

Do not put complete sentences into the skills list.

Do not invent skills based only on the job title.

If a technology or tool is mentioned as required or preferred,
it may be included as a skill.

============================================================
EXPERIENCE
============================================================

Extract ALL explicit experience-related requirements.

This field is NOT limited to years.

Capture any of the following when stated:

- years of experience
- required previous experience
- preferred experience
- experience with a technology
- experience with a process
- experience in an industry
- experience performing a particular responsibility
- entry-level requirements
- fresh graduate statements

Examples:

"3+ years of experience"

"1-2 years of experience in accounting"

"Experience with SQL and ETL processes preferred"

"Previous experience managing social media campaigns"

"Experience working with international clients"

"Fresh graduates are encouraged to apply"

"Prior experience in logistics is preferred"

IMPORTANT:

If the JD says:

"Experience with SQL preferred"

extract:

"Experience with SQL preferred"

Do NOT change it to:

"2 years of SQL experience"

because the number was not provided.

Do NOT leave the experience field empty simply because
there is no numerical number of years.

============================================================
EDUCATION
============================================================

Extract explicit education requirements.

Possible examples:

- Bachelor's degree
- Bachelor's degree in Computer Science
- Master's degree
- Diploma in Graphic Design
- Degree in Business Administration
- High school diploma
- Related field

Preserve whether the education is:

- required
- preferred
- optional

Do not invent a degree requirement.

============================================================
RESPONSIBILITIES
============================================================

Extract the actual duties and responsibilities of the position.

Possible section names include:

- Responsibilities
- Key Responsibilities
- Duties
- What You'll Do
- Your Responsibilities
- Role Responsibilities
- Job Duties
- What You Will Do

Keep each responsibility as a separate item whenever possible.

Example:

"Analyze sales data and prepare monthly reports"

should become:

"Analyze sales data and prepare monthly reports"

Do not split one meaningful responsibility into unnecessary fragments.

Do not invent responsibilities from general knowledge.

============================================================
LANGUAGES
============================================================

Extract HUMAN language requirements only when explicitly stated.

Examples:

- English
- Spanish
- Urdu
- French
- Arabic

Preserve whether the language is:

- required
- preferred
- fluent
- conversational
- native

Do NOT put programming languages here.

For example:

Python, Java, SQL, R and JavaScript are NOT human languages
for this field.

============================================================
LOCATION
============================================================

Extract the job location when explicitly stated.

Examples:

- Islamabad, Pakistan
- Laredo, TX 78045
- London, UK
- Remote
- New York, NY

If multiple locations are explicitly provided, preserve them.

Do not invent a location.

If the JD only says "remote" or "work from home",
that may be recorded as the location.

============================================================
SECTION DETECTION
============================================================

Do not depend only on section headings.

A JD may look like:

"Requirements proficient in Excel and Power BI..."

or:

"Key responsibilities analyze data..."

or:

"Qualifications bachelor's degree..."

or:

"About you strong communication skills..."

Understand the meaning of the text and classify it correctly.

Common alternative section names include:

Requirements
Qualifications
Preferred Qualifications
Required Qualifications
Skills
Technical Skills
What You'll Need
What We Need
About You
Your Profile
Duties
Responsibilities
Key Duties
What You'll Do
Experience
Education
Languages
Location

These headings may also appear inline inside a paragraph.

============================================================
REQUIRED VS PREFERRED
============================================================

Preserve the meaning of required versus preferred information.

Examples:

"SQL required"

"SQL preferred"

"Experience with Python is a plus"

"Degree required"

"Knowledge of Tableau preferred"

Do not turn preferred qualifications into mandatory
requirements.

============================================================
IMPORTANT INFORMATION NOT IN SCHEMA
============================================================

The original JD may contain other information such as:

- salary
- employment type
- schedule
- benefits
- work location type
- application instructions
- visa requirements
- travel requirements
- portfolio requirements

Do NOT force these into another field.

Do NOT place them into skills, education, experience,
responsibilities, or summary unless they genuinely belong there.

They can be handled separately later if needed.

============================================================
NO HALLUCINATION
============================================================

If the JD does not mention something, do not create it.

For example, if a Data Analyst JD does not mention Python,
do not add Python simply because Data Analysts commonly use it.

If a Graphic Designer JD does not mention Figma,
do not add Figma simply because designers commonly use it.

Only extract what is supported by the supplied text.

============================================================
FINAL RULE
============================================================

The final JSON must faithfully represent the supplied JD.

Do not add explanations.

Return ONLY the structured JSON matching the provided schema.

"""


# ============================================================
# BUILD PROMPT
# ============================================================

def build_prompt(job_description_text: str) -> str:

    return f"""
{SYSTEM_INSTRUCTIONS}

Now extract the following job description.

---------------- JOB DESCRIPTION ----------------

{job_description_text}

-------------- END JOB DESCRIPTION --------------
"""


# ============================================================
# STRUCTURE ONE JD
# ============================================================

def structure_job_description(
    job_description_text: str
):

    prompt = build_prompt(
        job_description_text
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": JobDescriptionSchema,
                    "temperature": 0,
                },
            )

            # ==================================================
            # STRUCTURED RESPONSE
            # ==================================================

            if getattr(
                response,
                "parsed",
                None
            ) is not None:

                parsed = response.parsed

                if isinstance(
                    parsed,
                    JobDescriptionSchema
                ):
                    return parsed.model_dump()

                if hasattr(
                    parsed,
                    "model_dump"
                ):
                    return parsed.model_dump()

                if isinstance(
                    parsed,
                    dict
                ):
                    return parsed

            # ==================================================
            # FALLBACK JSON TEXT
            # ==================================================

            text = getattr(
                response,
                "text",
                None
            )

            if text:

                text = text.strip()

                if text.startswith(
                    "```json"
                ):
                    text = text[7:]

                elif text.startswith(
                    "```"
                ):
                    text = text[3:]

                if text.endswith(
                    "```"
                ):
                    text = text[:-3]

                text = text.strip()

                data = json.loads(text)

                validated = (
                    JobDescriptionSchema
                    .model_validate(data)
                )

                return validated.model_dump()

            raise ValueError(
                "Gemini returned no usable structured response."
            )

        except Exception as e:

            last_error = e

            print(
                f"      Attempt "
                f"{attempt}/{MAX_RETRIES} failed: "
                f"{type(e).__name__}: {e}"
            )

            if attempt < MAX_RETRIES:

                wait_time = min(
                    5 * attempt,
                    30
                )

                print(
                    f"      Waiting "
                    f"{wait_time} seconds..."
                )

                time.sleep(
                    wait_time
                )

    raise RuntimeError(
        f"Gemini failed after "
        f"{MAX_RETRIES} attempts: "
        f"{last_error}"
    )



# ============================================================
# APPLICATION PIPELINE ENTRY POINT
# ============================================================
def process_job_description(job_description_text: str):
    """Run the same JD structuring pipeline used by the batch script.

    The Flask application passes the raw JD text directly here.
    """
    if not isinstance(job_description_text, str):
        raise TypeError("job_description_text must be a string")

    cleaned_text = job_description_text.strip()

    if not cleaned_text:
        raise ValueError("Job description is empty.")

    return structure_job_description(cleaned_text)
