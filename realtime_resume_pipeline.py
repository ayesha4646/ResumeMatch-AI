from pathlib import Path
import json
import sys


# ============================================================
# PROJECT ROOT
# ============================================================

PROJECT_ROOT = Path(
    r"D:\projects\Resume_Screening_AI"
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# IMPORT REALTIME PIPELINE FUNCTIONS
# ============================================================

from scripts.hybrid_resumes_extraction import (
    extract_uploaded_resume
)

from scripts.clean_resumes import (
    clean_uploaded_resume
)

from scripts.structure_resumes_LLM import (
    structure_uploaded_resume
)


# ============================================================
# REALTIME APPLICATION FOLDER
# ============================================================

REALTIME_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "realtime_applications"
)


# ============================================================
# PROCESS ONE UPLOADED CV
# ============================================================

def process_uploaded_resume(
    pdf_path,
    application_id,
    vacancy_id
):
    """
    Process one candidate CV through the complete
    realtime AI resume pipeline.

    Pipeline:

        PDF
         ↓
        Extraction
         ↓
        Cleaning
         ↓
        LLM Structuring
         ↓
        Structured JSON
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Uploaded resume not found: {pdf_path}"
        )

    # --------------------------------------------------------
    # Application-specific folder
    # --------------------------------------------------------

    application_folder = (
        REALTIME_FOLDER
        / str(application_id)
    )

    application_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # File paths
    # --------------------------------------------------------

    extracted_path = (
        application_folder
        / "extracted.txt"
    )

    cleaned_path = (
        application_folder
        / "cleaned.txt"
    )

    structured_path = (
        application_folder
        / "structured.json"
    )

    # ========================================================
    # STEP 1 — EXTRACTION
    # ========================================================

    print()
    print("=" * 60)
    print("REALTIME RESUME PIPELINE")
    print("=" * 60)

    print()
    print("[1/3] Extracting resume...")

    extraction_result = extract_uploaded_resume(
        pdf_path,
        extracted_path
    )

    print(
        "      Extraction complete."
    )

    # ========================================================
    # STEP 2 — CLEANING
    # ========================================================

    print()
    print("[2/3] Cleaning resume...")

    cleaning_result = clean_uploaded_resume(
        extracted_path,
        cleaned_path
    )

    print(
        "      Cleaning complete."
    )

    # ========================================================
    # STEP 3 — LLM STRUCTURING
    # ========================================================

    print()
    print("[3/3] Structuring resume with Gemini...")

    structuring_result = structure_uploaded_resume(
        cleaned_path,
        structured_path
    )

    print(
        "      Structuring complete."
    )

    # ========================================================
    # LOAD STRUCTURED DATA
    # ========================================================

    structured_data = (
        structuring_result["data"]
    )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    result = {
        "application_id": application_id,
        "vacancy_id": vacancy_id,

        "pdf_path": str(pdf_path),

        "extracted_path": str(
            extracted_path
        ),

        "cleaned_path": str(
            cleaned_path
        ),

        "structured_path": str(
            structured_path
        ),

        "structured_resume": structured_data,

        "extraction": {
            "pages": extraction_result.get(
                "pages"
            ),
            "pdfplumber_pages": extraction_result.get(
                "pdfplumber_pages"
            ),
            "docling_text_pages": extraction_result.get(
                "docling_text_pages"
            ),
            "docling_ocr_pages": extraction_result.get(
                "docling_ocr_pages"
            ),
            "complex_pages": extraction_result.get(
                "complex_pages"
            ),
        },

        "cleaning": {
            "input_characters": cleaning_result.get(
                "input_characters"
            ),
            "output_characters": cleaning_result.get(
                "output_characters"
            ),
        }
    }

    print()
    print("=" * 60)
    print("RESUME PIPELINE COMPLETE")
    print("=" * 60)
    print(
        f"Application ID : {application_id}"
    )
    print(
        f"Vacancy ID     : {vacancy_id}"
    )
    print(
        f"Structured CV  : {structured_path}"
    )
    print("=" * 60)

    return result




if __name__ == "__main__":

    TEST_PDF = Path(
        r"D:\projects\Resume_Screening_AI\data\test_resumes\your_cv.pdf"
    )

    result = process_uploaded_resume(
        pdf_path=TEST_PDF,
        application_id="TEST_002",
        vacancy_id=1
    )

    print()
    print("=" * 60)
    print("RESUME PIPELINE COMPLETE")
    print("=" * 60)

    print("Application ID :", result["application_id"])
    print("Vacancy ID     :", result["vacancy_id"])
    print("Structured CV  :", result["structured_path"])