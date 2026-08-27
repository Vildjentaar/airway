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
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template builder
# ---------------------------------------------------------------------------

def _build_itinerary_html(report_data: dict, pnr: str, passenger_summary: str) -> str:
    """Return a self-contained HTML email body from the report_data dict."""
    booked = report_data.get("booked_flights", [])
    seat_sel = report_data.get("seat_selections", [])
    luggage_sel = report_data.get("luggage_selections", [])
    extras_sel = report_data.get("extras_selections", [])
    passenger_details = report_data.get("passenger_details", [])
    ticket_number = report_data.get("ticket_number", "N/A")

    if passenger_details:
        names = [f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() for p in passenger_details]
        passenger_summary_display = f"{len(names)} passenger(s) — " + ", ".join(names)
    else:
        passenger_summary_display = passenger_summary

    grand_total = 0.0


    flights_html = ""
    for flight_idx, flight in enumerate(booked):
        segs = flight.get("segments", [])
        if not segs:
            continue
        
        pricing = flight.get("pricing_details", {})
        
        for seg_idx, seg in enumerate(segs):
            flights_html += textwrap.dedent(f"""
            <tr>
              <td style="padding:12px 0; border-bottom:1px solid #e5e7eb;">
                <strong>{seg.get('flight_number', '')} &nbsp;
                {seg.get('departure_point', '')} → {seg.get('arrival_point', '')}</strong><br/>
                <span style="color:#6b7280;font-size:13px;">
                  {seg.get('departure_date', '')} &nbsp;|&nbsp;
                  {seg.get('departure_time', '')} – {seg.get('arrival_time', '')} &nbsp;|&nbsp;
                  {flight.get('ticket_class', 'Economy')} &nbsp;|&nbsp;
                  Gate TBA
                </span><br/>
                <span style="font-size:13px;">
                  Passengers: {flight.get('passenger_count', 1)}
                </span>
              </td>
            </tr>
            """)
            
        flights_html += textwrap.dedent(f"""
        <tr>
          <td style="padding:8px 0 16px 0; border-bottom:2px solid #d1d5db;">
            <span style="font-size:13px; color:#4b5563;">
              <strong>Fare Breakdown:</strong> 
              Base: {pricing.get('subtotal_tl', '—')} TL &nbsp;|&nbsp;
              Taxes: {pricing.get('tax_tl', '—')} TL &nbsp;|&nbsp;
              Fees: {pricing.get('fees_tl', '—')} TL &nbsp;|&nbsp;
              <strong>Total: {pricing.get('total_tl', flight.get('price_tl', '—'))} TL</strong>
            </span>
          </td>
        </tr>
        """)
        try:
            grand_total += float(pricing.get('total_tl', flight.get('price_tl', 0)))
        except (ValueError, TypeError):
            pass

    ancillary_rows = ""
    for s in seat_sel:
        price = s.get('price_tl', 0)
        ancillary_rows += f"<li>Seat {s.get('seat_id', '?')} ({s.get('type','')}) — {price} TL</li>"
        try: grand_total += float(price)
        except (ValueError, TypeError): pass
    if not seat_sel:
        ancillary_rows += "<li>Seat Assignment: Unassigned (Selected at check-in)</li>"
    
    for l in luggage_sel:
        price = l.get('price_tl', 0)
        ancillary_rows += f"<li>Luggage: {l.get('tier','')} — {price} TL</li>"
        try: grand_total += float(price)
        except (ValueError, TypeError): pass
    if not luggage_sel:
        ancillary_rows += "<li>Luggage: Standard Cabin Bag Included</li>"
        
    for e in extras_sel:
        price = e.get('price_tl', 0)
        ancillary_rows += f"<li>{e.get('service','')} — {price} TL</li>"
        try: grand_total += float(price)
        except (ValueError, TypeError): pass

    ancillary_section = ""
    if ancillary_rows:
        ancillary_section = f"""
        <h3 style="color:#1d4ed8;margin-top:24px;">Add-ons &amp; Services</h3>
        <ul style="padding-left:20px;color:#374151;font-size:14px;">{ancillary_rows}</ul>
        """
        
    grand_total_section = f"""
        <div style="margin-top:24px; padding:16px; background:#f3f4f6; border-radius:8px; text-align:right;">
            <strong style="font-size:16px; color:#111827;">Grand Total: {grand_total:,.2f} TL</strong>
        </div>
    """

    from thall_lines_db import AIRLINE_NAME  # local import to keep module lean at import time

    return textwrap.dedent(f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"/></head>
    <body style="font-family:Arial,sans-serif;background:#f9fafb;padding:0;margin:0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:32px 0;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0"
                 style="background:#ffffff;border-radius:12px;overflow:hidden;
                        box-shadow:0 4px 24px rgba(0,0,0,0.07);">
            <!-- Header -->
            <tr>
              <td style="background:linear-gradient(135deg,#1d4ed8,#7c3aed);
                         padding:32px;text-align:center;color:#ffffff;">
                <h1 style="margin:0;font-size:26px;letter-spacing:-0.5px;">✈️ {AIRLINE_NAME}</h1>
                <p style="margin:8px 0 0;font-size:15px;opacity:0.9;">
                  Your booking is confirmed — have a great trip!
                </p>
                <p style="margin:8px 0 0;font-size:15px;opacity:0.9;">
                  <strong>Booking Reference (PNR):</strong> {pnr}
                </p>
                <p style="margin:8px 0 0;font-size:15px;opacity:0.9;">
                  <strong>Ticket Number:</strong> {ticket_number}
                </p>
                <p style="margin:8px 0 0;font-size:15px;opacity:0.9;">
                  <strong>Passengers:</strong> {passenger_summary_display}
                </p>
              </td>
            </tr>
            <!-- Body -->
            <tr>
              <td style="padding:32px;">
                <h2 style="color:#111827;margin-top:0;">Your Itinerary</h2>
                <table width="100%" cellpadding="0" cellspacing="0">
                  {flights_html}
                </table>
                {ancillary_section}
                {grand_total_section}
                <p style="margin-top:32px;font-size:13px;color:#9ca3af;border-top:1px solid #e5e7eb;
                           padding-top:16px;">
                  You can view or manage your trips any time in the
                  <strong>My Trips</strong> section of the app.<br/>
                  Questions? Our support team is always on deck.
                </p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """).strip()


def _build_plain_text(report_data: dict, pnr: str, passenger_summary: str) -> str:
    """Fallback plain-text version of the itinerary email."""
    booked = report_data.get("booked_flights", [])
    ticket_number = report_data.get("ticket_number", "N/A")
    passenger_details = report_data.get("passenger_details", [])
    
    if passenger_details:
        names = [f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() for p in passenger_details]
        passenger_summary_display = f"{len(names)} passenger(s) — " + ", ".join(names)
    else:
        passenger_summary_display = passenger_summary

    lines = [
        "Your booking is confirmed!\n", 
        f"Booking Reference (PNR): {pnr}",
        f"Ticket Number: {ticket_number}",
        f"Passengers: {passenger_summary_display}\n",
        "=== ITINERARY ==="
    ]
    for flight in booked:
        segs = flight.get("segments", [])
        if not segs:
            continue
        pricing = flight.get("pricing_details", {})
        
        for seg in segs:
            lines.append(
                f"\n• {seg.get('flight_number')}  "
                f"{seg.get('departure_point')} → {seg.get('arrival_point')}\n"
                f"  Date : {seg.get('departure_date')}  "
                f"{seg.get('departure_time')} – {seg.get('arrival_time')}\n"
                f"  Class: {flight.get('ticket_class', 'Economy')}\n"
                f"  Gate TBA"
            )
            
        lines.append(
            f"\n  Fare Breakdown:\n"
            f"  Base: {pricing.get('subtotal_tl', '—')} TL\n"
            f"  Taxes: {pricing.get('tax_tl', '—')} TL\n"
            f"  Fees: {pricing.get('fees_tl', '—')} TL\n"
            f"  Total: {pricing.get('total_tl', flight.get('price_tl', '—'))} TL"
        )
        
    seat_sel = report_data.get("seat_selections", [])
    if not seat_sel:
        lines.append("\n  Seat Assignment: Unassigned (Selected at check-in)")
    else:
        for s in seat_sel:
            lines.append(f"\n  Seat {s.get('seat_id', '?')} ({s.get('type','')}) — {s.get('price_tl', 0)} TL")
            
    luggage_sel = report_data.get("luggage_selections", [])
    if not luggage_sel:
        lines.append("\n  Luggage: Standard Cabin Bag Included")
    else:
        for l in luggage_sel:
            lines.append(f"\n  Luggage: {l.get('tier','')} — {l.get('price_tl', 0)} TL")

    extras_sel = report_data.get("extras_selections", [])
    for e in extras_sel:
        lines.append(f"\n  {e.get('service','')} — {e.get('price_tl', 0)} TL")

    lines.append(
        "\nManage your trip any time from the My Trips section of the app."
    )
    return "\n".join(lines)


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
        html_body = _build_itinerary_html(report_data, pnr_label, summary_label)
        plain_body = _build_plain_text(report_data, pnr_label, summary_label)
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
