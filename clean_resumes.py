
from pathlib import Path
import re
import html
import unicodedata
from collections import Counter


# ============================================================
# SETTINGS
# ============================================================

PROJECT_ROOT = Path(r"D:\projects\Resume_Screening_AI")


# ------------------------------------------------------------
# INPUT
# ------------------------------------------------------------
# Already extracted TXT files.
# NO PDFs are processed here.
# ------------------------------------------------------------

INPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "hybrid_resume_text"
)


# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

OUTPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "cleaned_resume_text"
)


# ------------------------------------------------------------
# CLEANING MODE
# ------------------------------------------------------------
# FIRST RUN:
#     MAX_FILES = 20
#
# AFTER CHECKING RESULTS:
#     MAX_FILES = None
# ------------------------------------------------------------

MAX_FILES = None

# If cleaned TXT already exists and is not empty,
# skip it.
SKIP_EXISTING = True


# ------------------------------------------------------------
# REPORT
# ------------------------------------------------------------

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "cleaning_report.csv"
)


# ============================================================
# SECTION HEADINGS
# ============================================================
#
# We NEVER use:
#
#     ALL CAPS = heading
#
# because names, companies and job titles can also be uppercase.
#
# Only known resume headings are normalized.
# ============================================================

HEADING_VARIANTS = {

    "SUMMARY": {
        "summary",
        "professional summary",
        "career summary",
        "executive summary",
    },

    "PROFILE": {
        "profile",
        "professional profile",
        "professional overview",
        "career profile",
        "personal profile",
    },

    "OBJECTIVE": {
        "objective",
        "career objective",
        "professional objective",
        "resume objective",
    },

    "SKILLS": {
        "skills",
        "skill",
        "key skills",
        "core skills",
        "additional skills",
    },

    "TECHNICAL SKILLS": {
        "technical skills",
        "technical skill",
        "computer skills",
        "it skills",
        "technical abilities",
    },

    "SOFT SKILLS": {
        "soft skills",
        "soft skill",
        "interpersonal skills",
    },

    "EXPERIENCE": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "work experience history",
    },

    "EDUCATION": {
        "education",
        "educational background",
        "academic background",
        "academic history",
        "educational history",
    },

    "CERTIFICATIONS": {
        "certifications",
        "certification",
        "professional certifications",
        "professional certification",
    },

    "PROJECTS": {
        "projects",
        "project",
        "academic projects",
        "personal projects",
        "professional projects",
        "key projects",
    },

    "ACHIEVEMENTS": {
        "achievements",
        "achievement",
        "accomplishments",
        "accomplishment",
    },

    "AWARDS": {
        "awards",
        "award",
        "honors",
        "honours",
    },

    "LANGUAGES": {
        "languages",
        "language",
    },

    "INTERESTS": {
        "interests",
        "interest",
        "hobbies",
        "hobby",
    },

    "REFERENCES": {
        "references",
        "reference",
    },

    "PUBLICATIONS": {
        "publications",
        "publication",
        "research publications",
        "research publication",
    },

    "VOLUNTEER EXPERIENCE": {
        "volunteer experience",
        "volunteer",
        "volunteering",
        "voluntary experience",
    },

    "AFFILIATIONS": {
        "affiliations",
        "professional affiliations",
        "affiliation",
        "professional affiliation",
    },

    "ADDITIONAL INFORMATION": {
        "additional information",
        "additional details",
        "additional information and skills",
    },

    "TRAINING": {
        "training",
        "professional training",
    },

    "COURSES": {
        "courses",
        "course",
        "coursework",
    },

    "CONTACT": {
        "contact",
        "contact information",
        "contact details",
    },

    "SOCIAL": {
        "social",
        "social media",
        "social profiles",
        "social profile",
    },

    "INTERNSHIPS": {
        "internships",
        "internship",
        "internship experience",
    },

    "KEY QUALIFICATIONS": {
        "key qualifications",
        "qualifications",
        "professional qualifications",
        "qualification",
    },

    "AREAS OF EXPERTISE": {
        "areas of expertise",
        "area of expertise",
    },

    "HIGHLIGHTS": {
        "highlights",
        "career highlights",
        "professional highlights",
    },

    "CAREER HIGHLIGHTS": {
        "career highlights",
    },

    "DUTIES": {
        "duties",
        "job duties",
        "responsibilities",
        "job responsibilities",
    },

}


# ============================================================
# OCR HEADING CORRECTIONS
# ============================================================
#
# ONLY heading corrections.
#
# We intentionally do NOT make global OCR word corrections.
# ============================================================

OCR_HEADING_FIXES = {

    "hiclights": "HIGHLIGHTS",

    "epucarion": "EDUCATION",
    "epucation": "EDUCATION",
    "educarion": "EDUCATION",

    "experlence": "EXPERIENCE",
    "experlences": "EXPERIENCE",

    "affliations": "AFFILIATIONS",
    "affliation": "AFFILIATIONS",

    "certlfications": "CERTIFICATIONS",
    "certlfication": "CERTIFICATIONS",

    "qualiflcations": "KEY QUALIFICATIONS",

    "skllls": "SKILLS",

    "professlonal experience": "EXPERIENCE",

    "professlonal summary": "SUMMARY",

}


# ============================================================
# BUILD HEADING LOOKUP
# ============================================================

def normalize_heading_key(text):
    text = text.strip().lower()

    # Remove Markdown heading symbols.
    text = re.sub(r"^#{1,6}\s*", "", text)

    # Remove decorative characters at beginning.
    text = re.sub(
        r"^[\s\-_=|:•●○▪▫◦‣⁃◉*+»►▸·]+",
        "",
        text,
    )

    # Remove decorative characters at end.
    text = re.sub(
        r"[\s\-_=|:•●○▪▫◦‣⁃◉*+»►▸·]+$",
        "",
        text,
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


HEADING_LOOKUP = {}

for canonical, variants in HEADING_VARIANTS.items():

    for variant in variants:

        HEADING_LOOKUP[
            normalize_heading_key(variant)
        ] = canonical


for wrong_heading, correct_heading in OCR_HEADING_FIXES.items():

    HEADING_LOOKUP[
        normalize_heading_key(wrong_heading)
    ] = correct_heading


# ============================================================
# PAGE MARKERS
# ============================================================

PAGE_MARKER_RE = re.compile(
    r"^\s*=+\s*PAGE\s+(\d+)\s*=+\s*$",
    flags=re.IGNORECASE,
)


def normalize_page_marker(line):

    match = PAGE_MARKER_RE.fullmatch(
        line.strip()
    )

    if match:

        return (
            f"===== PAGE "
            f"{match.group(1)} ====="
        )

    return line


# ============================================================
# UNICODE NORMALIZATION
# ============================================================

def normalize_unicode(text):

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    replacements = {

        "\ufeff": "",

        "\u00a0": " ",

        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",

        "\u2018": "'",
        "\u2019": "'",

        "\u201c": '"',
        "\u201d": '"',

        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",

        "\u2026": "...",

        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
    }

    for old, new in replacements.items():

        text = text.replace(
            old,
            new,
        )

    # Remove control characters except
    # newline and tab.
    text = "".join(
        ch
        for ch in text
        if ch in "\n\t"
        or not unicodedata.category(ch).startswith("C")
    )

    return text


# ============================================================
# HTML / WEB ARTIFACT CLEANING
# ============================================================

def clean_html_artifacts(text):

    # Remove HTML comments such as:
    #
    # <!-- image -->
    # <!-- image: something -->
    #
    text = re.sub(
        r"<!--.*?-->",
        "",
        text,
        flags=re.DOTALL,
    )

    # Decode entities:
    #
    # &amp;  -> &
    # &lt;   -> <
    # &gt;   -> >
    # &quot; -> "
    #
    text = html.unescape(text)

    # Remove remaining simple HTML tags.
    text = re.sub(
        r"<\s*/?\s*(?:br|div|span|p|img|table|tr|td|font)[^>]*>",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    return text


# ============================================================
# REMOVE PDF / MARKDOWN ARTIFACTS
# ============================================================

def clean_markdown_artifacts(line):

    stripped = line.strip()

    if not stripped:
        return ""

    # Remove Markdown headings:
    #
    # ## EDUCATION
    # ### EXPERIENCE
    #
    # BUT:
    #
    # C#
    #
    # is preserved because this only removes
    # hashes at the beginning of the line.

    line = re.sub(
        r"^\s*#{1,6}\s+",
        "",
        line,
    )

    # Remove Markdown code fences.
    if re.fullmatch(
        r"\s*```+\s*(?:\w+)?\s*",
        line,
    ):
        return ""

    # Remove standalone image placeholders.
    if re.fullmatch(
        r"\s*(?:image|img|photo|picture)\s*",
        line,
        flags=re.IGNORECASE,
    ):
        return ""

    return line


# ============================================================
# OCR / GRAPHICAL ARTIFACTS
# ============================================================

def normalize_ocr_artifacts(line):

    # Normalize vertical separators.
    line = re.sub(
        r"\s*\|\s*",
        " | ",
        line,
    )

    # Convert long decorative separators.
    line = re.sub(
        r"[=_]{4,}",
        "---",
        line,
    )

    # Remove excessive repeated punctuation.
    line = re.sub(
        r"\.{5,}",
        "...",
        line,
    )

    return line


# ============================================================
# BULLET NORMALIZATION
# ============================================================

def normalize_bullet(line):

    line = line.strip()

    if not line:
        return ""

    bullet_pattern = (
        r"^(?:"
        r"[•●○▪▫◦‣⁃◉]"
        r"|[-*]"
        r"|[»►▸]"
        r"|[+]"
        r"|·"
        r")"
        r"\s*"
    )

    if re.match(
        bullet_pattern,
        line,
    ):

        line = re.sub(
            bullet_pattern,
            "- ",
            line,
            count=1,
        )

    return line


# ============================================================
# REPAIR HYPHENATED LINE BREAKS
# ============================================================

def repair_hyphenated_line_breaks(text):

    """
    Example:

        experi-
        ence

    becomes:

        experience

    But:

        2020-
        2022

    remains unchanged.
    """

    pattern = (
        r"([A-Za-z])-\s*\n\s*([a-z])"
    )

    return re.sub(
        pattern,
        r"\1\2",
        text,
    )


# ============================================================
# SPACE CLEANING
# ============================================================

def clean_spaces(line):

    line = line.replace(
        "\t",
        " ",
    )

    # Multiple spaces.
    line = re.sub(
        r"[ ]{2,}",
        " ",
        line,
    )

    # Spaces before punctuation.
    line = re.sub(
        r"\s+([,.;:!?])",
        r"\1",
        line,
    )

    # Missing space after comma.
    line = re.sub(
        r",([A-Za-z])",
        r", \1",
        line,
    )

    # Normalize spaces around slash.
    line = re.sub(
        r"\s*/\s*",
        "/",
        line,
    )

    return line.strip()


# ============================================================
# GRAPHICAL GARBAGE DETECTION
# ============================================================

def is_graphical_garbage(line):

    stripped = line.strip()

    if not stripped:
        return False

    # Page markers are always kept.
    if PAGE_MARKER_RE.fullmatch(
        stripped
    ):
        return False

    compact = re.sub(
        r"\s+",
        "",
        stripped,
    )

    if len(compact) < 5:
        return False

    # --------------------------------------------------------
    # HTML/image artifacts.
    # --------------------------------------------------------

    if re.fullmatch(
        r"(?:image|img|photo|picture)",
        compact,
        flags=re.IGNORECASE,
    ):
        return True

    # --------------------------------------------------------
    # Mostly symbols.
    # --------------------------------------------------------

    alnum_count = sum(
        ch.isalnum()
        for ch in compact
    )

    symbol_count = (
        len(compact)
        - alnum_count
    )

    if len(compact) >= 8:

        symbol_ratio = (
            symbol_count
            / len(compact)
        )

        if symbol_ratio >= 0.80:
            return True

    # --------------------------------------------------------
    # Same character repeated.
    # --------------------------------------------------------

    if (
        len(set(compact)) == 1
        and len(compact) >= 6
    ):
        return True

    # --------------------------------------------------------
    # Graphical OCR characters.
    # --------------------------------------------------------

    graphical_chars = set(
        "IEFG_|-+=~^"
    )

    graphical_count = sum(
        1
        for ch in compact
        if ch.upper()
        in graphical_chars
    )

    if len(compact) >= 8:

        graphical_ratio = (
            graphical_count
            / len(compact)
        )

        if graphical_ratio >= 0.85:
            return True

    return False


# ============================================================
# HEADING DETECTION
# ============================================================

def is_known_heading(line):

    normalized = normalize_heading_key(
        line
    )

    if normalized in HEADING_LOOKUP:
        return True

    # Handle:
    #
    # SKILLS SKILLS
    #
    words = normalized.split()

    if (
        len(words) >= 2
        and len(words) % 2 == 0
    ):

        half = len(words) // 2

        first_half = " ".join(
            words[:half]
        )

        second_half = " ".join(
            words[half:]
        )

        if (
            first_half == second_half
            and first_half in HEADING_LOOKUP
        ):
            return True

    return False


# ============================================================
# SECTION HEADING NORMALIZATION
# ============================================================

def normalize_section_heading(line):

    original = line.strip()

    if not original:
        return original

    # Remove Markdown heading prefix.
    cleaned = re.sub(
        r"^\s*#{1,6}\s+",
        "",
        original,
    )

    # Remove decorative characters.
    cleaned = re.sub(
        r"^[\s\-_=|:•●○▪▫◦‣⁃◉*+»►▸·]+",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"[\s\-_=|:•●○▪▫◦‣⁃◉*+»►▸·]+$",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()

    key = normalize_heading_key(
        cleaned
    )

    # Exact heading.
    if key in HEADING_LOOKUP:
        return HEADING_LOOKUP[key]

    # OCR heading.
    if key in OCR_HEADING_FIXES:
        return OCR_HEADING_FIXES[key]

    # Handle:
    #
    # SKILLS: Python, SQL
    #
    for heading_key, canonical in HEADING_LOOKUP.items():

        if cleaned.lower().startswith(
            heading_key + ":"
        ):

            remaining = cleaned[
                len(heading_key):
            ]

            return (
                canonical
                + remaining
            )

    # Handle:
    #
    # SKILLS SKILLS
    #
    words = key.split()

    if (
        len(words) >= 2
        and len(words) % 2 == 0
    ):

        half = len(words) // 2

        first_half = " ".join(
            words[:half]
        )

        second_half = " ".join(
            words[half:]
        )

        if (
            first_half == second_half
            and first_half in HEADING_LOOKUP
        ):

            return HEADING_LOOKUP[
                first_half
            ]

    return original


# ============================================================
# DUPLICATE HEADING REMOVAL
# ============================================================

def remove_duplicate_heading(
    line,
    previous_line,
):

    if not previous_line:
        return line

    if (
        is_known_heading(line)
        and is_known_heading(previous_line)
    ):

        current = normalize_heading_key(
            line
        )

        previous = normalize_heading_key(
            previous_line
        )

        if current == previous:
            return ""

    return line


# ============================================================
# DUPLICATE DATE REMOVAL
# ============================================================

def remove_repeated_date(line):

    """
    Handles cases such as:

        2015-2019 2015-2019

    and:

        08/2015-12/2019 08/2015-12/2019

    """

    date_pattern = (
        r"("
        r"\b\d{1,2}[/-]\d{4}"
        r"\s*[-–]\s*"
        r"(?:\d{1,2}[/-]\d{4}|present|current)"
        r"|"
        r"\b\d{4}\s*[-–]\s*\d{4}"
        r"|"
        r"\b\d{4}\s*[-–]\s*(?:present|current)"
        r")"
    )

    pattern = re.compile(
        rf"^\s*({date_pattern})\s+\1\s*$",
        flags=re.IGNORECASE,
    )

    match = pattern.fullmatch(line)

    if match:
        return match.group(1)

    return line


# ============================================================
# DUPLICATE SHORT PHRASE REMOVAL
# ============================================================

def remove_obvious_same_phrase_duplicate(line):

    """
    Handles obvious cases such as:

        Python Python

        2015-2019 2015-2019

    But does NOT attempt aggressive semantic
    deduplication of long sentences.
    """

    words = line.split()

    if len(words) < 2:
        return line

    if len(words) % 2 != 0:
        return line

    half = len(words) // 2

    first = words[:half]
    second = words[half:]

    if first == second:

        # Only remove if phrase is reasonably short.
        if half <= 12:
            return " ".join(first)

    return line


# ============================================================
# DATE + TEXT SEPARATION
# ============================================================

def separate_date_from_following_word(line):

    """
    Handles obvious extraction cases such as:

        10/2011 to 04/2013Accountant

    becomes:

        10/2011 to 04/2013 Accountant

    We only insert a space where a date/range
    is immediately followed by a letter.
    """

    line = re.sub(
        r"(\b\d{1,2}/\d{4}\s+to\s+\d{1,2}/\d{4})(?=[A-Za-z])",
        r"\1 ",
        line,
        flags=re.IGNORECASE,
    )

    line = re.sub(
        r"(\b\d{4}\s*[-–]\s*\d{4})(?=[A-Za-z])",
        r"\1 ",
        line,
    )

    line = re.sub(
        r"(\b\d{1,2}/\d{4}\s*[-–]\s*(?:\d{1,2}/\d{4}|Present|Current))(?=[A-Za-z])",
        r"\1 ",
        line,
        flags=re.IGNORECASE,
    )

    return line


# ============================================================
# CLEAN ONE LINE
# ============================================================

def clean_line(line):

    # Page marker.
    line = normalize_page_marker(
        line
    )

    if PAGE_MARKER_RE.fullmatch(
        line.strip()
    ):
        return line.strip()

    # HTML / image artifacts.
    line = clean_markdown_artifacts(
        line
    )

    if not line:
        return ""

    # OCR formatting.
    line = normalize_ocr_artifacts(
        line
    )

    # Date/text separation.
    line = separate_date_from_following_word(
        line
    )

    # Bullets.
    line = normalize_bullet(
        line
    )

    # Spaces.
    line = clean_spaces(
        line
    )

    if not line:
        return ""

    # Obvious repeated date.
    line = remove_repeated_date(
        line
    )

    # Obvious duplicated short phrase.
    line = remove_obvious_same_phrase_duplicate(
        line
    )

    # Graphical garbage.
    if is_graphical_garbage(
        line
    ):
        return ""

    # Section heading.
    line = normalize_section_heading(
        line
    )

    return line


# ============================================================
# REPEATED HEADER / FOOTER DETECTION
# ============================================================

def remove_repeated_page_headers(lines):

    """
    Some PDFs repeat the same header/footer on every page.

    We only remove a line if:
      - it appears multiple times
      - it is relatively short
      - it is NOT an important heading
      - it is NOT an email/phone/date
      - it is NOT a bullet line

    This is intentionally conservative.
    """

    counts = Counter()

    for line in lines:

        stripped = line.strip()

        if not stripped:
            continue

        if is_known_heading(stripped):
            continue

        if stripped.startswith("- "):
            continue

        if len(stripped) > 100:
            continue

        counts[stripped.lower()] += 1

    repeated = {
        text
        for text, count in counts.items()
        if count >= 3
    }

    cleaned = []

    for line in lines:

        stripped = line.strip()

        if (
            stripped
            and stripped.lower() in repeated
            and not is_known_heading(stripped)
            and "@" not in stripped
        ):
            # Keep dates and contact-like lines.
            if re.search(
                r"\d{4}",
                stripped,
            ):
                cleaned.append(line)
                continue

            if re.search(
                r"\+?\d[\d\s().-]{7,}",
                stripped,
            ):
                cleaned.append(line)
                continue

            # Remove likely repeated header/footer.
            continue

        cleaned.append(line)

    return cleaned


# ============================================================
# CLEAN COMPLETE RESUME
# ============================================================

def clean_resume_text(text):

    # --------------------------------------------------------
    # 1. Unicode
    # --------------------------------------------------------

    text = normalize_unicode(
        text
    )

    # --------------------------------------------------------
    # 2. HTML / web artifacts
    # --------------------------------------------------------

    text = clean_html_artifacts(
        text
    )

    # --------------------------------------------------------
    # 3. Safe hyphen repair
    # --------------------------------------------------------

    text = repair_hyphenated_line_breaks(
        text
    )

    # --------------------------------------------------------
    # 4. Split into lines
    # --------------------------------------------------------

    raw_lines = text.splitlines()

    cleaned_lines = []

    # --------------------------------------------------------
    # 5. Clean individual lines
    # --------------------------------------------------------

    for raw_line in raw_lines:

        cleaned = clean_line(
            raw_line
        )

        # Find previous meaningful line.
        previous_line = ""

        for previous in reversed(
            cleaned_lines
        ):

            if previous.strip():

                previous_line = previous

                break

        # Remove only consecutive
        # duplicate known headings.
        cleaned = remove_duplicate_heading(
            cleaned,
            previous_line,
        )

        if cleaned:

            cleaned_lines.append(
                cleaned
            )

        else:

            # Keep at most one blank line.
            if (
                cleaned_lines
                and cleaned_lines[-1] != ""
            ):
                cleaned_lines.append("")

    # --------------------------------------------------------
    # 6. Remove obvious repeated headers/footers
    # --------------------------------------------------------

    cleaned_lines = remove_repeated_page_headers(
        cleaned_lines
    )

    # --------------------------------------------------------
    # 7. Final blank-line cleanup
    # --------------------------------------------------------

    final_lines = []

    for line in cleaned_lines:

        # Page marker.
        if PAGE_MARKER_RE.fullmatch(
            line.strip()
        ):

            if (
                final_lines
                and final_lines[-1] != ""
            ):
                final_lines.append("")

            final_lines.append(
                line.strip()
            )

            final_lines.append("")

            continue

        # Blank line.
        if line == "":

            if (
                final_lines
                and final_lines[-1] != ""
            ):
                final_lines.append("")

        else:

            final_lines.append(
                line
            )

    # --------------------------------------------------------
    # 8. Remove leading blanks
    # --------------------------------------------------------

    while (
        final_lines
        and final_lines[0] == ""
    ):
        final_lines.pop(0)

    # --------------------------------------------------------
    # 9. Remove trailing blanks
    # --------------------------------------------------------

    while (
        final_lines
        and final_lines[-1] == ""
    ):
        final_lines.pop()

    # --------------------------------------------------------
    # 10. Final protection against
    #     double blank lines
    # --------------------------------------------------------

    result = []

    for line in final_lines:

        if line == "":

            if (
                result
                and result[-1] != ""
            ):
                result.append("")

        else:

            result.append(
                line
            )

    return "\n".join(
        result
    )


# ============================================================
# PROCESS ONE FILE
# ============================================================

def process_file(input_file):

    relative_path = (
        input_file.relative_to(
            INPUT_FOLDER
        )
    )

    output_file = (
        OUTPUT_FOLDER
        / relative_path
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Resume support
    # --------------------------------------------------------

    if (
        SKIP_EXISTING
        and output_file.exists()
        and output_file.stat().st_size > 0
    ):

        return (
            "SKIPPED",
            0,
            0,
            "",
        )

    try:

        text = input_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        cleaned_text = clean_resume_text(
            text
        )

        output_file.write_text(
            cleaned_text,
            encoding="utf-8",
        )

        return (
            "OK",
            len(text),
            len(cleaned_text),
            "",
        )

    except Exception as e:

        return (
            "ERROR",
            0,
            0,
            str(e),
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 72)
    print("RESUME TEXT CLEANING")
    print("=" * 72)

    print(
        f"Input :  {INPUT_FOLDER}"
    )

    print(
        f"Output:  {OUTPUT_FOLDER}"
    )

    print()

    # --------------------------------------------------------
    # Check input
    # --------------------------------------------------------

    if not INPUT_FOLDER.exists():

        print(
            "ERROR: Input folder does not exist."
        )

        return

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Find TXT files
    # --------------------------------------------------------

    files = sorted(
        INPUT_FOLDER.rglob(
            "*.txt"
        )
    )

    print(
        f"Found TXT files: {len(files)}"
    )

    if not files:

        print(
            "ERROR: No TXT files found."
        )

        return

    # --------------------------------------------------------
    # Select files
    # --------------------------------------------------------

    if MAX_FILES is not None:

        files_to_process = files[
            :MAX_FILES
        ]

        print(
            f"TEST MODE: "
            f"{len(files_to_process)} files."
        )

    else:

        files_to_process = files

        print(
            "FULL MODE: processing ALL files."
        )

    print()

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    success = 0
    skipped = 0
    failed = 0

    total_input_chars = 0
    total_output_chars = 0

    report_rows = []

    # --------------------------------------------------------
    # Process
    # --------------------------------------------------------

    for index, input_file in enumerate(
        files_to_process,
        start=1,
    ):

        status, input_chars, output_chars, error = (
            process_file(
                input_file
            )
        )

        relative = (
            input_file.relative_to(
                INPUT_FOLDER
            )
        )

        if status == "OK":

            success += 1

            total_input_chars += (
                input_chars
            )

            total_output_chars += (
                output_chars
            )

            print(
                f"[{index}/{len(files_to_process)}] "
                f"OK: {relative}"
            )

        elif status == "SKIPPED":

            skipped += 1

            print(
                f"[{index}/{len(files_to_process)}] "
                f"SKIP: {relative}"
            )

        else:

            failed += 1

            print(
                f"[{index}/{len(files_to_process)}] "
                f"ERROR: {relative}"
            )

            print(
                f"    {error}"
            )

        report_rows.append({
            "file": str(relative),
            "status": status,
            "input_characters": input_chars,
            "output_characters": output_chars,
            "error": error,
        })

    # --------------------------------------------------------
    # Write report
    # --------------------------------------------------------

    try:

        import csv

        REPORT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with REPORT_FILE.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "file",
                    "status",
                    "input_characters",
                    "output_characters",
                    "error",
                ],
            )

            writer.writeheader()

            writer.writerows(
                report_rows
            )

    except Exception as e:

        print()
        print(
            f"WARNING: Could not write report: {e}"
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()

    print("=" * 72)
    print("CLEANING COMPLETE")
    print("=" * 72)

    print(
        f"Files considered : "
        f"{len(files_to_process)}"
    )

    print(
        f"Cleaned          : "
        f"{success}"
    )

    print(
        f"Skipped existing : "
        f"{skipped}"
    )

    print(
        f"Failed           : "
        f"{failed}"
    )

    print(
        f"Input characters : "
        f"{total_input_chars:,}"
    )

    print(
        f"Output characters: "
        f"{total_output_chars:,}"
    )

    if total_input_chars > 0:

        reduction = (
            (
                total_input_chars
                - total_output_chars
            )
            / total_input_chars
        ) * 100

        print(
            f"Character reduction: "
            f"{reduction:.2f}%"
        )

    print()

    print(
        "Cleaned files saved to:"
    )

    print(
        OUTPUT_FOLDER
    )

    print()

    print(
        "Cleaning report saved to:"
    )

    print(
        REPORT_FILE
    )

    print("=" * 72)


# ============================================================
# RUN
# ============================================================

# ============================================================
# REALTIME SINGLE CV CLEANING
# ============================================================

def clean_uploaded_resume(input_path, output_path):
    """
    Clean one realtime extracted resume TXT.

    Used by the recruitment application.
    Does NOT run the batch cleaning process.
    """

    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Extracted resume file not found: {input_path}"
        )

    text = input_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    if not text.strip():
        raise ValueError(
            "Extracted resume text is empty."
        )

    cleaned_text = clean_resume_text(
        text
    )

    if not cleaned_text.strip():
        raise ValueError(
            "Cleaning produced empty resume text."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        cleaned_text,
        encoding="utf-8",
    )

    return {
        "text": cleaned_text,
        "output_path": str(output_path),
        "input_characters": len(text),
        "output_characters": len(cleaned_text),
    }



if __name__ == "__main__":
    main()
