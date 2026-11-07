from pathlib import Path
import pandas as pd
import re

# --------------------------------
# PROJECT PATHS
# --------------------------------

PROJECT_ROOT = Path(r"D:\projects\Resume_Screening_AI")

JD_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "job descriptions"
    / "data.csv"
)

OUTPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "job_description_text"
)

MANIFEST_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "job_description_manifest.csv"
)


# --------------------------------
# CREATE OUTPUT FOLDER
# --------------------------------

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)


# --------------------------------
# FUNCTION TO CLEAN FILE NAMES
# --------------------------------

def clean_filename(name):

    name = str(name).strip()

    # Remove characters Windows does not allow in filenames
    name = re.sub(r'[<>:"/\\|?*]', '', name)

    # Replace multiple spaces with one space
    name = re.sub(r'\s+', ' ', name)

    # If title is empty
    if name == "":
        name = "Unknown Job"

    return name


# --------------------------------
# READ CSV FILE
# --------------------------------

print("Reading Job Description dataset...")

df = pd.read_csv(JD_FILE)

print()
print("Columns found:")
print(df.columns.tolist())

print()
print("Total rows found:", len(df))


# --------------------------------
# CHECK REQUIRED COLUMNS
# --------------------------------

required_columns = ["Job Title", "Description"]

for column in required_columns:

    if column not in df.columns:

        raise ValueError(
            f"\nColumn '{column}' was not found.\n"
            f"Available columns are: {df.columns.tolist()}"
        )


# --------------------------------
# EXTRACT JOB DESCRIPTIONS
# --------------------------------

results = []

print()
print("Starting extraction...")
print()


for index, row in df.iterrows():

    # Get Job Title
    job_title = row["Job Title"]

    if pd.isna(job_title):
        job_title = "Unknown Job"
    else:
        job_title = str(job_title).strip()


    # Get Description
    description = row["Description"]

    if pd.isna(description):
        description = ""
    else:
        description = str(description).strip()


    # --------------------------------
    # EMPTY DESCRIPTION
    # --------------------------------

    if description == "":

        results.append({
            "row_number": index + 2,
            "job_title": job_title,
            "characters": 0,
            "status": "EMPTY",
            "text_file": ""
        })

        print(
            f"[{index + 1}/{len(df)}] "
            f"{job_title} -> EMPTY"
        )

        continue


    # --------------------------------
    # CREATE SAFE FILE NAME
    # --------------------------------

    safe_title = clean_filename(job_title)

    # Row number is added so duplicate job titles
    # do not overwrite each other
    filename = f"{index + 1:04d}_{safe_title}.txt"

    output_path = OUTPUT_FOLDER / filename


    # --------------------------------
    # SAVE DESCRIPTION AS TEXT FILE
    # --------------------------------

    output_path.write_text(
        description,
        encoding="utf-8"
    )


    # Count characters
    character_count = len(description)


    # --------------------------------
    # SAVE INFORMATION TO MANIFEST
    # --------------------------------

    results.append({
        "row_number": index + 2,
        "job_title": job_title,
        "characters": character_count,
        "status": "SUCCESS",
        "text_file": str(output_path)
    })


    print(
        f"[{index + 1}/{len(df)}] "
        f"{job_title} -> "
        f"{character_count} characters -> SUCCESS"
    )


# --------------------------------
# CREATE MANIFEST CSV
# --------------------------------

results_df = pd.DataFrame(results)

results_df.to_csv(
    MANIFEST_FILE,
    index=False,
    encoding="utf-8-sig"
)


# --------------------------------
# FINAL SUMMARY
# --------------------------------

successful = (results_df["status"] == "SUCCESS").sum()

empty = (results_df["status"] == "EMPTY").sum()


print()
print("====================================")
print("JOB DESCRIPTION EXTRACTION COMPLETE")
print("====================================")

print("Total rows:", len(results_df))
print("Successful:", successful)
print("Empty:", empty)

print()
print("JD text files saved in:")
print(OUTPUT_FOLDER)

print()
print("Manifest saved at:")
print(MANIFEST_FILE)