"""
email_templates.py
-------------------
HTML and plain-text builders for the itinerary confirmation email.

These functions are pure: given `report_data` plus a PNR and passenger
summary, they return a string body. No I/O, no provider logic — that
lives in `email_service.py`.
"""

import textwrap

from db import AIRLINE_NAME


def build_itinerary_html(report_data: dict, pnr: str, passenger_summary: str) -> str:
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


def build_plain_text(report_data: dict, pnr: str, passenger_summary: str) -> str:
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
