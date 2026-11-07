from datetime import datetime
import json

from src.database import (
    initialize_database,
    get_all_vacancies,
    update_jd_processing,
)

from scripts.structure_job_descriptions_LLM import (
    process_job_description,
)


def process_existing_vacancies():

    print("=" * 60)
    print("PROCESSING EXISTING VACANCIES")
    print("=" * 60)

    initialize_database()

    vacancies = get_all_vacancies()

    if not vacancies:
        print("No vacancies found.")
        return

    print(f"Found {len(vacancies)} vacancy/vacancies.")

    for vacancy in vacancies:

        vacancy_id = vacancy["id"]
        job_title = vacancy["job_title"]
        description = vacancy["description"]
        current_status = vacancy["status"]
        jd_status = vacancy["jd_processing_status"]

        print()
        print("-" * 60)
        print(f"Vacancy ID : {vacancy_id}")
        print(f"Job Title  : {job_title}")
        print(f"Status     : {current_status}")
        print(f"JD Status  : {jd_status}")

        # --------------------------------------------------
        # SKIP ALREADY PROCESSED JDs
        # --------------------------------------------------

        if jd_status == "ready":
            print("Already processed. Skipping.")
            continue

        # --------------------------------------------------
        # VALIDATE JD
        # --------------------------------------------------

        if not description or not description.strip():
            print("ERROR: Vacancy has no JD description.")

            update_jd_processing(
                vacancy_id=vacancy_id,
                processing_status="failed",
                structured_data=None,
                processing_error="Job description is empty.",
                processed_at=None,
            )

            continue

        try:

            # --------------------------------------------------
            # MARK AS PROCESSING
            # --------------------------------------------------

            update_jd_processing(
                vacancy_id=vacancy_id,
                processing_status="processing",
                structured_data=None,
                processing_error=None,
                processed_at=None,
            )

            print("Sending JD to Gemini...")

            # --------------------------------------------------
            # RUN EXISTING JD AI PIPELINE
            # --------------------------------------------------

            structured_jd = process_job_description(
                description
            )

            # --------------------------------------------------
            # VALIDATE RESULT
            # --------------------------------------------------

            if not structured_jd:
                raise ValueError(
                    "Gemini returned an empty structured JD."
                )

            # --------------------------------------------------
            # SAVE STRUCTURED JD
            # --------------------------------------------------

            structured_json = json.dumps(
                structured_jd,
                ensure_ascii=False,
            )

            processed_at = datetime.now().isoformat(
                timespec="seconds"
            )

            update_jd_processing(
                vacancy_id=vacancy_id,
                processing_status="ready",
                structured_data=structured_json,
                processing_error=None,
                processed_at=processed_at,
            )

            print("SUCCESS: JD structured and saved.")
            print("JD Status: ready")

        except Exception as error:

            error_message = str(error)

            print(
                f"ERROR processing vacancy {vacancy_id}: "
                f"{error_message}"
            )

            update_jd_processing(
                vacancy_id=vacancy_id,
                processing_status="failed",
                structured_data=None,
                processing_error=error_message,
                processed_at=None,
            )

            print("JD Status: failed")

    print()
    print("=" * 60)
    print("EXISTING VACANCY PROCESSING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    process_existing_vacancies()