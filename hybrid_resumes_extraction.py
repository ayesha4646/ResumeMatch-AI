from pathlib import Path
import io
import re
import traceback
import fitz
import pdfplumber
import pytesseract

from PIL import Image
from pytesseract import Output

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)


# ============================================================
# SETTINGS
# ============================================================

PROJECT_ROOT = Path(
    r"D:\projects\Resume_Screening_AI"
)


# ============================================================
# FINAL 5,000 RESUMES
# ============================================================

INPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "selected_resumes_final"
)


# ============================================================
# SAME EXISTING OUTPUT FOLDER
# ============================================================

OUTPUT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "hybrid_resume_text"
)


# ============================================================
# TESSERACT
# ============================================================

TESSERACT_EXE = Path(
    r"D:\Ayesha\Tesseract\tesseract.exe"
)


# ============================================================
# NATIVE TEXT DECISION
# ============================================================

MIN_NATIVE_TEXT_CHARS = 80


# If native text is below this amount,
# treat the page as probably scanned.
MIN_NATIVE_TEXT_PER_PAGE = 50


# ============================================================
# OCR SETTINGS
# ============================================================

OCR_SCALE = 2.5
OCR_CONFIG = "--psm 3"


# ============================================================
# READING ORDER SETTINGS
# ============================================================

LINE_Y_TOLERANCE = 12

MIN_MAJOR_GAP = 120


# ============================================================
# COMPLEX LAYOUT SETTINGS
# ============================================================

# Minimum number of words required before
# attempting column analysis.
MIN_WORDS_FOR_LAYOUT = 20


# Minimum number of words that should exist
# in a detected column.
MIN_COLUMN_WORDS = 8


# Minimum percentage of page words that should
# belong to each detected column.
MIN_COLUMN_PERCENT = 0.15


# Number of horizontal bands/pages regions in
# which a column pattern should be visible.
#
# This helps avoid declaring a resume complex
# because of ONE accidental large gap.
MIN_COLUMN_BANDS = 3


# ============================================================
# RESUME HEADINGS
# ============================================================

KNOWN_HEADINGS = {

    "summary",
    "professional summary",
    "profile",
    "objective",
    "career objective",

    "highlights",

    "skills",
    "technical skills",
    "core skills",
    "key skills",

    "experience",
    "work experience",
    "professional experience",
    "employment",
    "employment history",

    "education",
    "academic background",
    "qualifications",

    "certifications",
    "certificate",

    "projects",
    "personal projects",

    "achievements",
    "awards",
    "honors",

    "publications",

    "languages",

    "interests",
    "hobbies",

    "references",

    "affiliations",
    "activities",

    "volunteer",
    "volunteering",

    "contact",
    "contact information",
}


# ============================================================
# TESSERACT SETUP
# ============================================================

pytesseract.pytesseract.tesseract_cmd = (
    str(TESSERACT_EXE)
)


# ============================================================
# DOCLING SETUP
# ============================================================

print()
print("=" * 70)
print("LOADING DOCLING")
print("=" * 70)


# ------------------------------------------------------------
# DOCLING FOR COMPLEX TEXT-BASED PDF
#
# OCR OFF
#
# The PDF already contains native text.
# We want Docling's document/layout understanding,
# not another OCR pass.
# ------------------------------------------------------------

text_pipeline_options = PdfPipelineOptions()

text_pipeline_options.do_ocr = False

# Keep table structure ON.
#
# We are not disabling it because resumes can use
# tables for education, skills, experience, etc.
text_pipeline_options.do_table_structure = True

text_pipeline_options.generate_page_images = False
text_pipeline_options.generate_picture_images = False
text_pipeline_options.generate_parsed_pages = False

text_pipeline_options.heading_hierarchy_options.enabled = True


DOCLING_TEXT_CONVERTER = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=text_pipeline_options
        )
    }
)


print(
    "Docling text/layout converter ready."
)


# ------------------------------------------------------------
# DOCLING FOR SCANNED PDF
#
# OCR ON
# ------------------------------------------------------------

ocr_pipeline_options = PdfPipelineOptions()

ocr_pipeline_options.do_ocr = True

# Keep table structure ON here as well.
ocr_pipeline_options.do_table_structure = True

ocr_pipeline_options.generate_page_images = False
ocr_pipeline_options.generate_picture_images = False
ocr_pipeline_options.generate_parsed_pages = False

ocr_pipeline_options.heading_hierarchy_options.enabled = True


DOCLING_OCR_CONVERTER = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=ocr_pipeline_options
        )
    }
)


print(
    "Docling OCR converter ready."
)

print("=" * 70)


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.replace(
        "\x00",
        " "
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    return text.strip()


def is_heading(text):

    cleaned = normalize_text(
        text
    ).lower()

    if not cleaned:
        return False

    if cleaned in KNOWN_HEADINGS:
        return True

    letters = re.sub(
        r"[^A-Za-z]",
        "",
        text
    )

    if len(letters) >= 4:

        uppercase_ratio = (
            sum(
                c.isupper()
                for c in letters
            )
            / len(letters)
        )

        if (
            uppercase_ratio >= 0.85
            and len(text.split()) <= 8
        ):
            return True

    return False


# ============================================================
# PDFPLUMBER EXTRACTION
# ============================================================

def extract_pdfplumber_page(page):

    """
    Extract words from a digital PDF.

    Keeps X/Y coordinates for reading-order
    and layout analysis.
    """

    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=3,
        keep_blank_chars=False,
        use_text_flow=False
    )

    result = []

    for word in words:

        text = normalize_text(
            word.get("text", "")
        )

        if not text:
            continue

        result.append(
            {
                "text": text,

                "x0": float(
                    word.get("x0", 0)
                ),

                "x1": float(
                    word.get("x1", 0)
                ),

                "top": float(
                    word.get("top", 0)
                ),

                "bottom": float(
                    word.get("bottom", 0)
                ),
            }
        )

    return result


# ============================================================
# NATIVE TEXT
# ============================================================

def get_native_text(page):

    try:

        text = (
            page.extract_text()
            or ""
        )

        return text.strip()

    except Exception:

        return ""


# ============================================================
# OCR
# ============================================================

def render_page_to_pil(pdf_page):

    matrix = fitz.Matrix(
        OCR_SCALE,
        OCR_SCALE
    )

    pix = pdf_page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image_bytes = pix.tobytes(
        "png"
    )

    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    return image


def extract_tesseract_page(pdf_page):

    image = render_page_to_pil(
        pdf_page
    )

    data = pytesseract.image_to_data(
        image,
        config=OCR_CONFIG,
        output_type=Output.DICT
    )

    words = []

    total = len(
        data["text"]
    )

    for i in range(total):

        text = normalize_text(
            data["text"][i]
        )

        if not text:
            continue

        try:

            confidence = float(
                data["conf"][i]
            )

        except Exception:

            confidence = -1

        if confidence < 0:
            continue

        left = float(
            data["left"][i]
        )

        top = float(
            data["top"][i]
        )

        width = float(
            data["width"][i]
        )

        height = float(
            data["height"][i]
        )

        words.append(
            {
                "text": text,

                "x0": left,

                "x1": left + width,

                "top": top,

                "bottom": top + height,
            }
        )

    return words


# ============================================================
# GROUP WORDS INTO VISUAL LINES
# ============================================================

def group_lines(words):

    if not words:
        return []

    words = sorted(
        words,
        key=lambda w: (
            w["top"],
            w["x0"]
        )
    )

    lines = []

    for word in words:

        placed = False

        for line in reversed(lines):

            avg_y = (
                sum(
                    w["top"]
                    for w in line
                )
                / len(line)
            )

            if (
                abs(
                    word["top"] - avg_y
                )
                <= LINE_Y_TOLERANCE
            ):

                line.append(word)

                placed = True

                break

        if not placed:

            lines.append(
                [word]
            )

    for line in lines:

        line.sort(
            key=lambda w: w["x0"]
        )

    lines.sort(
        key=lambda line: min(
            w["top"]
            for w in line
        )
    )

    return lines


# ============================================================
# BODY START
# ============================================================

def detect_body_start(lines):

    if not lines:
        return 0

    for i, line in enumerate(lines):

        text = " ".join(
            w["text"]
            for w in line
        ).strip()

        if is_heading(text):

            return i

    return 0


# ============================================================
# X-GAPS
# ============================================================

def find_large_x_gaps(words):

    if len(words) < 2:
        return []

    sorted_words = sorted(
        words,
        key=lambda w: w["x0"]
    )

    gaps = []

    for i in range(
        len(sorted_words) - 1
    ):

        current = sorted_words[i]

        next_word = (
            sorted_words[i + 1]
        )

        gap = (
            next_word["x0"]
            - current["x1"]
        )

        if gap >= MIN_MAJOR_GAP:

            gaps.append(
                {
                    "gap": gap,

                    "left_end":
                        current["x1"],

                    "right_start":
                        next_word["x0"],
                }
            )

    return gaps


# ============================================================
# BODY SPLIT SCORE
# ============================================================

def score_body_split(
    words,
    split_x
):

    left_count = 0
    right_count = 0

    for word in words:

        center = (
            word["x0"]
            + word["x1"]
        ) / 2

        if center < split_x:

            left_count += 1

        else:

            right_count += 1

    if (
        left_count == 0
        or right_count == 0
    ):
        return 0

    return min(
        left_count,
        right_count
    )


# ============================================================
# NEW: STRONG COLUMN DETECTION
# ============================================================

def detect_complex_columns(words):

    """
    Determine whether the page has a genuinely
    complex multi-column layout.

    This is intentionally stronger than simply
    looking for ONE large X gap.

    We check:

    1. Enough words exist.
    2. A meaningful left/right split exists.
    3. Both columns contain enough words.
    4. Both columns contain a reasonable percentage
       of the page's words.
    5. The split appears across multiple vertical
       regions of the page.

    Returns:

        {
            "complex": True/False,
            "columns": 2,
            "split_x": value,
            "score": value,
            "reason": text
        }
    """

    if len(words) < MIN_WORDS_FOR_LAYOUT:

        return {
            "complex": False,
            "columns": 1,
            "split_x": None,
            "score": 0,
            "reason": "TOO_FEW_WORDS",
        }


    gaps = find_large_x_gaps(
        words
    )

    if not gaps:

        return {
            "complex": False,
            "columns": 1,
            "split_x": None,
            "score": 0,
            "reason": "NO_MAJOR_GAP",
        }


    best_candidate = None


    for gap in gaps:

        split_x = (
            gap["left_end"]
            + gap["right_start"]
        ) / 2


        left = []
        right = []

        for word in words:

            center = (
                word["x0"]
                + word["x1"]
            ) / 2

            if center < split_x:

                left.append(word)

            else:

                right.append(word)


        total = len(words)

        left_count = len(left)
        right_count = len(right)


        # ----------------------------------------------------
        # Minimum words in both columns
        # ----------------------------------------------------

        if (
            left_count < MIN_COLUMN_WORDS
            or right_count < MIN_COLUMN_WORDS
        ):
            continue


        # ----------------------------------------------------
        # Percentage check
        # ----------------------------------------------------

        left_percent = (
            left_count / total
        )

        right_percent = (
            right_count / total
        )


        if (
            left_percent
            < MIN_COLUMN_PERCENT
        ):
            continue

        if (
            right_percent
            < MIN_COLUMN_PERCENT
        ):
            continue


        # ----------------------------------------------------
        # Check vertical distribution
        #
        # Divide page into horizontal bands.
        # A real column layout normally continues
        # across several bands.
        # ----------------------------------------------------

        min_top = min(
            w["top"]
            for w in words
        )

        max_bottom = max(
            w["bottom"]
            for w in words
        )

        height = max(
            max_bottom - min_top,
            1
        )


        band_hits = 0

        band_height = (
            height / 5
        )


        for band_index in range(5):

            band_start = (
                min_top
                + band_index
                * band_height
            )

            band_end = (
                band_start
                + band_height
            )


            band_left = 0
            band_right = 0


            for word in words:

                center_y = (
                    word["top"]
                    + word["bottom"]
                ) / 2


                if (
                    center_y
                    < band_start
                    or center_y
                    > band_end
                ):
                    continue


                center_x = (
                    word["x0"]
                    + word["x1"]
                ) / 2


                if center_x < split_x:

                    band_left += 1

                else:

                    band_right += 1


            if (
                band_left >= 2
                and band_right >= 2
            ):

                band_hits += 1


        # ----------------------------------------------------
        # Strong candidate
        # ----------------------------------------------------

        if band_hits < MIN_COLUMN_BANDS:

            continue


        score = min(
            left_count,
            right_count
        )


        candidate = {
            "complex": True,
            "columns": 2,
            "split_x": split_x,
            "score": score,
            "reason": (
                "MULTI_COLUMN_LAYOUT"
            ),
        }


        if (
            best_candidate is None
            or score
            > best_candidate["score"]
        ):

            best_candidate = candidate


    if best_candidate:

        return best_candidate


    return {
        "complex": False,
        "columns": 1,
        "split_x": None,
        "score": 0,
        "reason": "NO_STRONG_COLUMN_PATTERN",
    }


# ============================================================
# SPLIT WORDS
# ============================================================

def split_words(
    words,
    split_x
):

    left = []
    right = []

    if split_x is None:

        return (
            words,
            []
        )

    for word in words:

        center = (
            word["x0"]
            + word["x1"]
        ) / 2

        if center < split_x:

            left.append(word)

        else:

            right.append(word)

    return (
        left,
        right
    )


# ============================================================
# NORMAL READING
# ============================================================

def normal_reading(words):

    lines = group_lines(
        words
    )

    output = []

    for line in lines:

        text = " ".join(
            w["text"]
            for w in line
        ).strip()

        if text:

            output.append(
                text
            )

    return output


# ============================================================
# LOCAL COLUMN DETECTION
# ============================================================

def detect_local_columns(words):

    if len(words) < 10:

        return None

    gaps = find_large_x_gaps(
        words
    )

    if not gaps:

        return None

    best = max(
        gaps,
        key=lambda x: x["gap"]
    )

    split_x = (
        best["left_end"]
        + best["right_start"]
    ) / 2

    score = score_body_split(
        words,
        split_x
    )

    if score < 3:

        return None

    return split_x


# ============================================================
# BODY REGION READING
# ============================================================

def read_body_region(words):

    if not words:

        return []

    local_split = (
        detect_local_columns(words)
    )

    if local_split is None:

        return normal_reading(
            words
        )

    left, right = split_words(
        words,
        local_split
    )

    output = []

    if left:

        output.extend(
            normal_reading(
                left
            )
        )

    if right:

        output.extend(
            normal_reading(
                right
            )
        )

    return output


# ============================================================
# PDFPLUMBER V4 READING ORDER
# ============================================================

def build_reading_order(words):

    if not words:

        return []

    lines = group_lines(
        words
    )

    body_start = (
        detect_body_start(
            lines
        )
    )

    header_lines = (
        lines[:body_start]
    )

    body_lines = (
        lines[body_start:]
    )

    output = []


    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    for line in header_lines:

        text = " ".join(
            w["text"]
            for w in line
        ).strip()

        if text:

            output.append(
                text
            )


    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    body_words = []

    for line in body_lines:

        body_words.extend(
            line
        )


    if not body_words:

        return output


    layout_info = (
        detect_complex_columns(
            body_words
        )
    )


    if not layout_info["complex"]:

        output.extend(
            read_body_region(
                body_words
            )
        )

    else:

        left, right = (
            split_words(
                body_words,
                layout_info["split_x"]
            )
        )


        if left:

            output.append(
                "[BODY - LEFT COLUMN]"
            )

            output.extend(
                read_body_region(
                    left
                )
            )


        if right:

            output.append(
                "[BODY - RIGHT COLUMN]"
            )

            output.extend(
                read_body_region(
                    right
                )
            )


    return output


# ============================================================
# CLEAN OUTPUT
# ============================================================

def clean_output_lines(lines):

    cleaned = []

    previous_blank = False

    for line in lines:

        line = line.strip()

        if not line:

            if not previous_blank:

                cleaned.append("")

            previous_blank = True

            continue

        cleaned.append(
            line
        )

        previous_blank = False

    return cleaned


# ============================================================
# FAST PAGE QUALITY DECISION
# ============================================================

def decide_page_method(
    native_text,
    words
):

    native_chars = len(
        native_text
    )


    # --------------------------------------------------------
    # Very little/no native text
    #
    # This is likely a scanned page.
    # --------------------------------------------------------

    if native_chars < MIN_NATIVE_TEXT_CHARS:

        return (
            "DOCLING_OCR",
            "LOW_NATIVE_TEXT"
        )


    if len(words) == 0:

        return (
            "DOCLING_OCR",
            "NO_PDFPLUMBER_WORDS"
        )


    # --------------------------------------------------------
    # Complex multi-column native PDF
    # --------------------------------------------------------

    layout_info = (
        detect_complex_columns(
            words
        )
    )


    if layout_info["complex"]:

        return (
            "DOCLING_NO_OCR",
            layout_info["reason"]
        )


    # --------------------------------------------------------
    # Normal native text PDF
    # --------------------------------------------------------

    return (
        "PDFPLUMBER",
        "NATIVE_TEXT_SIMPLE_LAYOUT"
    )


# ============================================================
# DOCLING EXTRACTION
# ============================================================

def extract_with_docling(
    pdf_path,
    use_ocr
):

    if use_ocr:

        result = (
            DOCLING_OCR_CONVERTER.convert(
                str(pdf_path)
            )
        )

    else:

        result = (
            DOCLING_TEXT_CONVERTER.convert(
                str(pdf_path)
            )
        )


    text = (
        result.document
        .export_to_markdown()
    )


    return normalize_text(
        text
    )


# ============================================================
# PROCESS ONE PDF
# ============================================================

def process_pdf(
    pdf_path,
    output_path
):

    """
    Process one complete PDF.

    Decision:

        Page has little/no native text
            -> Docling OCR

        Page has native text + complex columns
            -> Docling without OCR

        Page has simple native text
            -> PDFplumber coordinate extraction

    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    # --------------------------------------------------------
    # RESUME SUPPORT
    # --------------------------------------------------------

    if (
        output_path.exists()
        and output_path.stat().st_size > 0
    ):

        return {
            "status": "SKIPPED",
            "pages": 0,
            "pdfplumber_pages": 0,
            "docling_text_pages": 0,
            "docling_ocr_pages": 0,
            "complex_pages": 0,
            "error": "",
        }


    pdf_document = None


    pdfplumber_count = 0
    docling_text_count = 0
    docling_ocr_count = 0
    complex_count = 0


    all_output = []


    try:

        # ----------------------------------------------------
        # Open both libraries
        # ----------------------------------------------------

        pdf_document = fitz.open(
            pdf_path
        )


        with pdfplumber.open(
            pdf_path
        ) as plumber_pdf:


            page_count = len(
                pdf_document
            )


            for page_index in range(
                page_count
            ):


                pdf_page = (
                    pdf_document[
                        page_index
                    ]
                )


                plumber_page = (
                    plumber_pdf.pages[
                        page_index
                    ]
                )


                print(
                    f"      Page "
                    f"{page_index + 1}/"
                    f"{page_count}"
                )


                # =================================================
                # STEP 1
                # NATIVE TEXT
                # =================================================

                native_text = (
                    get_native_text(
                        plumber_page
                    )
                )


                # =================================================
                # STEP 2
                # PDFPLUMBER WORD COORDINATES
                #
                # We need these to inspect layout.
                # =================================================

                words = []


                if (
                    len(native_text)
                    >= MIN_NATIVE_TEXT_CHARS
                ):

                    try:

                        words = (
                            extract_pdfplumber_page(
                                plumber_page
                            )
                        )

                    except Exception:

                        words = []


                # =================================================
                # STEP 3
                # DECIDE
                # =================================================

                method, reason = (
                    decide_page_method(
                        native_text,
                        words
                    )
                )


                # =================================================
                # CASE A
                # PDFPLUMBER
                # =================================================

                if method == "PDFPLUMBER":

                    page_lines = (
                        build_reading_order(
                            words
                        )
                    )


                    page_lines = (
                        clean_output_lines(
                            page_lines
                        )
                    )


                    pdfplumber_count += 1


                    print(
                        f"          "
                        f"PDFPLUMBER "
                        f"| {len(words)} words"
                    )


                # =================================================
                # CASE B
                # COMPLEX TEXT PDF
                # DOCLING WITHOUT OCR
                # =================================================

                elif method == "DOCLING_NO_OCR":

                    complex_count += 1

                    print(
                        "          "
                        "DOCLING "
                        "| OCR OFF "
                        "| COMPLEX LAYOUT"
                    )


                    # ------------------------------------------------
                    # Important:
                    #
                    # Docling works on the whole PDF, not page-by-page.
                    #
                    # We handle this outside the page loop below.
                    # ------------------------------------------------

                    docling_text = (
                        extract_with_docling(
                            pdf_path,
                            use_ocr=False
                        )
                    )


                    # We already extracted the complete document.
                    # Stop processing individual pages.
                    #
                    # The complete Docling output will be saved.
                    #

                    all_output = [
                        docling_text
                    ]


                    docling_text_count = 1


                    # Mark this special state.
                    method = (
                        "DOCLING_NO_OCR_FULL_PDF"
                    )


                    break


                # =================================================
                # CASE C
                # SCANNED PAGE
                # =================================================

                elif method == "DOCLING_OCR":

                    print(
                        "          "
                        "DOCLING "
                        "| OCR ON "
                        "| SCANNED"
                    )


                    # ------------------------------------------------
                    # Same issue:
                    # Docling OCR works on complete PDF.
                    # ------------------------------------------------

                    docling_text = (
                        extract_with_docling(
                            pdf_path,
                            use_ocr=True
                        )
                    )


                    all_output = [
                        docling_text
                    ]


                    docling_ocr_count = 1


                    method = (
                        "DOCLING_OCR_FULL_PDF"
                    )


                    break


                # =================================================
                # PAGE OUTPUT FOR PDFPLUMBER
                # =================================================

                all_output.append(
                    f"===== PAGE "
                    f"{page_index + 1} ====="
                )


                all_output.extend(
                    page_lines
                )


                all_output.append("")


        # --------------------------------------------------------
        # Close PyMuPDF
        # --------------------------------------------------------

        if pdf_document is not None:

            pdf_document.close()

            pdf_document = None


        # ========================================================
        # SAVE TXT
        # ========================================================

        final_text = "\n".join(
            all_output
        )


        final_text = (
            final_text.strip()
        )


        if not final_text:

            return {
                "status": "ERROR",
                "pages": page_count,
                "pdfplumber_pages": pdfplumber_count,
                "docling_text_pages": docling_text_count,
                "docling_ocr_pages": docling_ocr_count,
                "complex_pages": complex_count,
                "error": "EMPTY_OUTPUT",
            }


        output_path.write_text(
            final_text,
            encoding="utf-8"
        )


        return {
            "status": "SUCCESS",
            "pages": page_count,
            "pdfplumber_pages": pdfplumber_count,
            "docling_text_pages": docling_text_count,
            "docling_ocr_pages": docling_ocr_count,
            "complex_pages": complex_count,
            "error": "",
        }


    except Exception as e:

        if pdf_document is not None:

            try:
                pdf_document.close()
            except Exception:
                pass


        return {
            "status": "ERROR",
            "pages": 0,
            "pdfplumber_pages": pdfplumber_count,
            "docling_text_pages": docling_text_count,
            "docling_ocr_pages": docling_ocr_count,
            "complex_pages": complex_count,
            "error": str(e),
        }


# ============================================================
# FIND ALL PDFs
# ============================================================

def get_all_pdfs():

    pdfs = list(
        INPUT_FOLDER.rglob(
            "*.pdf"
        )
    )

    pdfs.sort()

    return pdfs


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print(
        "HYBRID RESUME EXTRACTION"
    )
    print(
        "PDFplumber + Layout Check + Docling"
    )
    print("=" * 70)

    print()

    print(
        f"Input : {INPUT_FOLDER}"
    )

    print(
        f"Output: {OUTPUT_FOLDER}"
    )

    print()


    # --------------------------------------------------------
    # Check input
    # --------------------------------------------------------

    if not INPUT_FOLDER.exists():

        print(
            "ERROR: Input folder does not exist."
        )

        print(
            INPUT_FOLDER
        )

        return


    # --------------------------------------------------------
    # Check Tesseract
    # --------------------------------------------------------

    if not TESSERACT_EXE.exists():

        print(
            "ERROR: Tesseract executable not found."
        )

        print(
            TESSERACT_EXE
        )

        return


    # --------------------------------------------------------
    # Find PDFs
    # --------------------------------------------------------

    pdf_files = get_all_pdfs()


    print(
        f"Found {len(pdf_files):,} PDF files."
    )

    print()


    if not pdf_files:

        print(
            "No PDF files found."
        )

        return


    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------

    if len(pdf_files) != 5000:

        print(
            "ERROR: Expected exactly 5,000 PDFs."
        )

        print(
            f"Found: {len(pdf_files):,}"
        )

        print()

        print(
            "Extraction will NOT start."
        )

        return


    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    successful = 0

    skipped = 0

    failed = 0

    total_pdfplumber_pages = 0

    total_docling_text = 0

    total_docling_ocr = 0

    total_complex_pages = 0


    # --------------------------------------------------------
    # Process
    # --------------------------------------------------------

    for index, pdf_path in enumerate(
        pdf_files,
        start=1
    ):


        # ----------------------------------------------------
        # Preserve category structure
        # ----------------------------------------------------

        relative_path = (
            pdf_path.relative_to(
                INPUT_FOLDER
            )
        )


        output_path = (
            OUTPUT_FOLDER
            / relative_path
        ).with_suffix(
            ".txt"
        )


        category = (
            pdf_path.parent.name
        )


        print()
        print("=" * 70)

        print(
            f"[{index:,}/"
            f"{len(pdf_files):,}] "
            f"{category} "
            f"-> "
            f"{pdf_path.name}"
        )

        print("-" * 70)


        # ----------------------------------------------------
        # Process
        # ----------------------------------------------------

        result = process_pdf(
            pdf_path,
            output_path
        )


        # ----------------------------------------------------
        # Statistics
        # ----------------------------------------------------

        total_pdfplumber_pages += (
            result[
                "pdfplumber_pages"
            ]
        )


        total_docling_text += (
            result[
                "docling_text_pages"
            ]
        )


        total_docling_ocr += (
            result[
                "docling_ocr_pages"
            ]
        )


        total_complex_pages += (
            result[
                "complex_pages"
            ]
        )


        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        if (
            result["status"]
            == "SUCCESS"
        ):

            successful += 1

            print(
                "      SUCCESS"
            )


            print(
                f"      TXT: "
                f"{output_path}"
            )


        elif (
            result["status"]
            == "SKIPPED"
        ):

            skipped += 1

            print(
                "      SKIPPED "
                "(TXT already exists)"
            )


        else:

            failed += 1

            print(
                f"      ERROR: "
                f"{result['error']}"
            )


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print()
    print("=" * 70)
    print(
        "FINAL SUMMARY"
    )
    print("=" * 70)

    print(
        f"Total PDFs found      : "
        f"{len(pdf_files):,}"
    )

    print(
        f"Successfully processed: "
        f"{successful:,}"
    )

    print(
        f"Skipped               : "
        f"{skipped:,}"
    )

    print(
        f"Failed                : "
        f"{failed:,}"
    )

    print()

    print(
        f"PDFplumber pages      : "
        f"{total_pdfplumber_pages:,}"
    )

    print(
        f"Docling text PDFs     : "
        f"{total_docling_text:,}"
    )

    print(
        f"Docling OCR PDFs      : "
        f"{total_docling_ocr:,}"
    )

    print(
        f"Complex layouts       : "
        f"{total_complex_pages:,}"
    )

    print()

    print(
        "Output folder:"
    )

    print(
        OUTPUT_FOLDER
    )

    print("=" * 70)


# ============================================================
# START
# ============================================================

# ============================================================
# REALTIME SINGLE CV EXTRACTION
# ============================================================


def extract_uploaded_resume(pdf_path, output_path):
    """
    Extract one realtime uploaded CV.

    Reuses existing extraction output when process_pdf returns SKIPPED.
    Does NOT run the 5,000-resume batch.
    """

    pdf_path = Path(pdf_path)
    output_path = Path(output_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Resume PDF not found: {pdf_path}"
        )

    result = process_pdf(pdf_path, output_path)
    extraction_status = result.get("status")

    # SUCCESS means extraction ran; SKIPPED means existing output is reused.
    if extraction_status not in {"SUCCESS", "SKIPPED"}:
        raise RuntimeError(
            "Resume extraction failed: "
            f"Full extraction result:\n{result.get('error') or result!r}"
        )

    if not output_path.is_file():
        raise RuntimeError(
            f"Extraction output file was not created: {output_path}"
        )

    extracted_text = output_path.read_text(encoding="utf-8")

    if not extracted_text.strip():
        raise RuntimeError(
            "Resume extraction produced empty text."
        )

    return {
        "text": extracted_text,
        "output_path": str(output_path),
        "pages": result.get("pages", 0),
        "pdfplumber_pages": result.get("pdfplumber_pages", 0),
        "docling_text_pages": result.get("docling_text_pages", 0),
        "docling_ocr_pages": result.get("docling_ocr_pages", 0),
        "complex_pages": result.get("complex_pages", 0),
    }



if __name__ == "__main__":

    main()