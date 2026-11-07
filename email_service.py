"""
Selection-email delivery for ResumeMatch AI.

Uses Python's built-in smtplib. All credentials come from environment
variables and are never stored in source code.

Required environment variables:
    SMTP_HOST         e.g. smtp.gmail.com
    SMTP_USERNAME     SMTP login
    SMTP_PASSWORD     SMTP password / app password
    SMTP_FROM_EMAIL   address the email is sent from

Optional:
    SMTP_PORT         default 587 (starttls) or 465 (ssl)
    SMTP_SECURITY     "starttls" (default) or "ssl"
    SMTP_FROM_NAME    default "ResumeMatch AI"
"""

import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

ALLOWED_PLACEHOLDERS = ("candidate_name", "job_title")

DEFAULT_TEMPLATE_SUBJECT = "Update on your application for {{job_title}}"

DEFAULT_TEMPLATE_BODY = (
    "Dear {{candidate_name}},\n"
    "\n"
    "Thank you for applying for the {{job_title}} position and for the time "
    "you invested in our interview process.\n"
    "\n"
    "We are pleased to let you know that you have been selected to move "
    "forward. Our HR team will contact you shortly with the next steps.\n"
    "\n"
    "Congratulations, and we look forward to speaking with you soon.\n"
    "\n"
    "Best regards,\n"
    "HR Team"
)

SMTP_TIMEOUT_SECONDS = 20

_REQUIRED_SETTINGS = (
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
)

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_EMAIL_PATTERN = re.compile(r"^[^@\s,;<>()\[\]\\\"]+@[^@\s,;<>()\[\]\\\"]+\.[^@\s,;<>()\[\]\\\"]+$")


class EmailConfigError(Exception):
    """Email delivery is not configured correctly on the server."""


class EmailSendError(Exception):
    """The email service did not accept the message."""


# ------------------------------------------------------------
# Placeholders
# ------------------------------------------------------------

def find_unknown_placeholders(text):
    """Return placeholders such as {{candidte_name}} that we do not support."""
    return [
        match.group(0)
        for match in _PLACEHOLDER_PATTERN.finditer(str(text or ""))
        if match.group(1).strip() not in ALLOWED_PLACEHOLDERS
    ]


def fill_placeholders(text, values):
    """Replace {{candidate_name}} and {{job_title}} with real values."""

    def replace(match):
        key = match.group(1).strip()
        if key in ALLOWED_PLACEHOLDERS:
            return str(values.get(key, ""))
        return match.group(0)

    return _PLACEHOLDER_PATTERN.sub(replace, str(text or ""))


# ------------------------------------------------------------
# Validation + configuration
# ------------------------------------------------------------

def is_valid_email(address):
    value = str(address or "").strip()
    return bool(value) and len(value) <= 254 and bool(_EMAIL_PATTERN.match(value))


def get_smtp_config():
    missing = [
        name for name in _REQUIRED_SETTINGS
        if not os.environ.get(name, "").strip()
    ]

    if missing:
        raise EmailConfigError(
            "Email sending is not set up yet. Missing server setting(s): "
            + ", ".join(missing) + "."
        )

    security = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()

    if security not in {"starttls", "ssl"}:
        raise EmailConfigError("SMTP_SECURITY must be 'starttls' or 'ssl'.")

    default_port = "465" if security == "ssl" else "587"

    try:
        port = int(os.environ.get("SMTP_PORT", default_port).strip())
    except ValueError:
        raise EmailConfigError("SMTP_PORT must be a number.")

    from_email = os.environ["SMTP_FROM_EMAIL"].strip()

    if not is_valid_email(from_email):
        raise EmailConfigError("SMTP_FROM_EMAIL is not a valid email address.")

    return {
        "host": os.environ["SMTP_HOST"].strip(),
        "port": port,
        "security": security,
        "username": os.environ["SMTP_USERNAME"].strip(),
        "password": os.environ["SMTP_PASSWORD"],
        "from_email": from_email,
        "from_name": os.environ.get("SMTP_FROM_NAME", "ResumeMatch AI").strip(),
    }


def _single_line(value):
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


# ------------------------------------------------------------
# Sending
# ------------------------------------------------------------

def send_email(to_email, to_name, subject, body, reply_to=None):
    """
    Send one plain-text email.

    Returns normally ONLY when the SMTP server accepted the message.
    Raises EmailConfigError or EmailSendError otherwise.
    """

    config = get_smtp_config()

    if not is_valid_email(to_email):
        raise EmailSendError("The candidate's email address is not valid.")

    message = EmailMessage()

    try:
        message["Subject"] = _single_line(subject)
        message["From"] = formataddr((config["from_name"], config["from_email"]))
        message["To"] = formataddr((_single_line(to_name), to_email.strip()))
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(
            domain=config["from_email"].split("@", 1)[1]
        )

        if reply_to and is_valid_email(reply_to):
            message["Reply-To"] = reply_to.strip()

        message.set_content(str(body).replace("\r\n", "\n"))

    except ValueError as error:
        raise EmailSendError(f"The email could not be prepared: {error}")

    context = ssl.create_default_context()

    try:
        if config["security"] == "ssl":
            server = smtplib.SMTP_SSL(
                config["host"],
                config["port"],
                timeout=SMTP_TIMEOUT_SECONDS,
                context=context,
            )
        else:
            server = smtplib.SMTP(
                config["host"],
                config["port"],
                timeout=SMTP_TIMEOUT_SECONDS,
            )

        with server:
            server.ehlo()

            if config["security"] == "starttls":
                server.starttls(context=context)
                server.ehlo()

            server.login(config["username"], config["password"])
            refused = server.send_message(message)

        if refused:
            raise EmailSendError(
                "The email server rejected the candidate's address."
            )

    except EmailSendError:
        raise

    except smtplib.SMTPAuthenticationError:
        raise EmailSendError(
            "The email server rejected the username or password. "
            "Check SMTP_USERNAME and SMTP_PASSWORD (Gmail needs an app password)."
        )

    except smtplib.SMTPRecipientsRefused:
        raise EmailSendError("The email server rejected the candidate's address.")

    except smtplib.SMTPSenderRefused:
        raise EmailSendError(
            "The email server rejected the sender address. SMTP_FROM_EMAIL must "
            "be an address your email account is allowed to send from."
        )

    except smtplib.SMTPServerDisconnected:
        raise EmailSendError("The email server closed the connection. Please try again.")

    except smtplib.SMTPException as error:
        raise EmailSendError(
            f"The email server reported an error: {str(error)[:150]}"
        )

    except ssl.SSLError:
        raise EmailSendError(
            "A secure connection to the email server could not be made. "
            "Check SMTP_PORT and SMTP_SECURITY."
        )

    except (TimeoutError, socket.timeout):
        raise EmailSendError(
            "The email server did not respond in time. Please try again."
        )

    except OSError as error:
        raise EmailSendError(
            f"Could not connect to the email server ({config['host']}:"
            f"{config['port']}): {str(error)[:120]}"
        )