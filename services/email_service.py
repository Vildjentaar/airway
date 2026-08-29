"""
email_service.py
-----------------
Backend email execution layer. Completely isolated from the LLM — it
never sees or touches a tool call or message history.

The single public function `send_itinerary_email` accepts the recipient
address (always sourced from the authenticated session, NEVER from LLM
output) and the structured report data, then dispatches the email via
the configured provider.

Returns a plain dict:
  {"success": True}                   — email delivered
  {"success": False, "error_code": "SERVICE_UNAVAILABLE", "detail": "..."}

The sanitised `error_code` is what gets returned to the LLM; the full
`detail` string is only logged server-side for debugging.

CONFIGURATION
  Set these environment variables (already loaded via python-dotenv in app.py):
    EMAIL_PROVIDER   = "smtp" | "sendgrid"   (default: "smtp")
    SMTP_HOST        = e.g.  "smtp.gmail.com"
    SMTP_PORT        = e.g.  587
    SMTP_USER        = sender email address
    SMTP_PASSWORD    = sender SMTP password / app-password
    SENDGRID_API_KEY = (only when EMAIL_PROVIDER=sendgrid)
    EMAIL_FROM       = "Thall Lines <noreply@thalllines.com>"
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from .email_templates import build_itinerary_html, build_plain_text

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _send_via_smtp(to_email: str, subject: str, html_body: str, plain_body: str) -> None:
    """Send via SMTP. Raises on any failure so the caller can catch it."""
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("EMAIL_FROM", user)

    if not host or not user or not password:
        raise EnvironmentError(
            "SMTP is not fully configured. "
            "Set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())


def _send_via_sendgrid(to_email: str, subject: str, html_body: str, plain_body: str) -> None:
    """Send via SendGrid. Raises on any failure."""
    try:
        import sendgrid  # type: ignore
        from sendgrid.helpers.mail import Mail  # type: ignore
    except ImportError:
        raise ImportError(
            "sendgrid package is not installed. "
            "Add 'sendgrid' to requirements.txt and reinstall."
        )

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    from_addr = os.environ.get("EMAIL_FROM", "noreply@thalllines.com")
    if not api_key:
        raise EnvironmentError("SENDGRID_API_KEY is not set.")

    mail = Mail(
        from_email=from_addr,
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
        plain_text_content=plain_body,
    )
    sg = sendgrid.SendGridAPIClient(api_key)
    response = sg.send(mail)
    if response.status_code not in (200, 202):
        raise RuntimeError(
            f"SendGrid returned status {response.status_code}: {response.body}"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def send_itinerary_email(
    to_email: str,
    report_data: dict,
    pnr: Optional[str] = None,
    passenger_summary: Optional[str] = None,
) -> dict:
    """
    Send the post-checkout itinerary email to the authenticated user.

    Parameters
    ----------
    to_email    : The recipient address — must come from the server-side
                  authenticated session, NEVER from LLM tool-call output.
    report_data : The finalized report_data dict produced by `generate_final_report`.
    pnr         : Optional booking reference. If omitted, a placeholder is used.

    Returns
    -------
    {"success": True}
    or
    {"success": False, "error_code": "SERVICE_UNAVAILABLE", "detail": "<tech msg>"}
    """
    if not to_email:
        log.error("send_itinerary_email called with empty recipient address.")
        return {
            "success": False,
            "error_code": "SERVICE_UNAVAILABLE",
            "detail": "No recipient email address available in session.",
        }

    pnr_label = pnr or "N/A"
    summary_label = passenger_summary or "1 Passenger"
    subject = f"✈️ Your Booking Confirmation — Ref {pnr_label}"

    try:
        html_body = build_itinerary_html(report_data, pnr_label, summary_label)
        plain_body = build_plain_text(report_data, pnr_label, summary_label)
    except Exception as build_err:
        log.exception("Failed to build email body: %s", build_err)
        return {
            "success": False,
            "error_code": "SERVICE_UNAVAILABLE",
            "detail": f"Email body build failure: {build_err}",
        }

    provider = os.environ.get("EMAIL_PROVIDER", "smtp").lower()

    try:
        if provider == "sendgrid":
            _send_via_sendgrid(to_email, subject, html_body, plain_body)
        else:
            _send_via_smtp(to_email, subject, html_body, plain_body)

        log.info("Itinerary email sent to %s via %s.", to_email, provider)
        return {"success": True}

    except Exception as send_err:
        # Log the real technical error server-side only.
        log.exception(
            "Email delivery failed for %s (provider=%s): %s",
            to_email, provider, send_err,
        )
        return {
            "success": False,
            "error_code": "SERVICE_UNAVAILABLE",
            "detail": str(send_err),
        }
