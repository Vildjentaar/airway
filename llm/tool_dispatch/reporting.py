"""
llm/tool_dispatch/reporting.py
-------------------------------
Handlers for the booking-finalisation tools:
  - generate_final_report   (freeze cart → report)
  - send_itinerary_email    (dispatch confirmation email)

Security note
~~~~~~~~~~~~~
``handle_send_itinerary_email`` reads the destination address exclusively
from the ``user_email`` parameter (sourced from the authenticated
session in ``app.py``).  The LLM's ``tool_args`` are intentionally
ignored for the recipient — only ``pnr_code`` and
``passenger_name_summary`` are read.
"""

from __future__ import annotations

import logging
from typing import Optional

from email_service import send_itinerary_email as _send_itinerary_email

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# generate_final_report
# --------------------------------------------------------------------------- #

def handle_generate_final_report(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Freeze the current cart into a final report.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False
    skip_followup = False

    if not flight_data:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": (
                "Error: Cannot generate the final report yet. "
                "The flight summary widget has not been shown to the user. "
                "Continue the booking flow and call generate_flight_widget first."
            ),
        })
        return report_data, skip_followup, email_sent

    report_data = tool_args
    report_data["booked_flights"] = list(flight_data)

    # Inject ancillary selections so the final report can display them
    _anc = ancillary_data or {}
    report_data["seat_selections"] = _anc.get("seat_selections", [])
    report_data["luggage_selections"] = _anc.get("luggage_selections", [])
    report_data["extras_selections"] = _anc.get("extras_selections", [])

    booked_summary = "; ".join(
        f"{f['segments'][0]['flight_number']} {f['segments'][0]['departure_point']}→{f['segments'][-1]['arrival_point']} "
        f"({f.get('ticket_class')}, {f['segments'][0]['departure_date']})"
        for f in report_data["booked_flights"] if f.get("segments")
    )
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": (
            f"Final report generated. Booked flights: {booked_summary}. "
            f"Now call send_itinerary_email immediately (the system will supply the "
            f"destination address — do NOT ask the user for their email). "
            f"Once the email tool returns, tell the user (in THEIR language) that "
            f"their itinerary is confirmed and the summary report is shown below."
        ),
        "report_data": report_data
    })

    return report_data, skip_followup, email_sent


# --------------------------------------------------------------------------- #
# send_itinerary_email
# --------------------------------------------------------------------------- #

def handle_send_itinerary_email(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Dispatch the confirmation email to the authenticated user.

    The LLM is never given the user's email address.  We pull it
    exclusively from the ``user_email`` parameter (sourced from
    ``st.session_state`` in ``app.py``).

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    skip_followup = False

    pnr = tool_args.get("pnr_code", "N/A")
    passenger_summary = tool_args.get("passenger_name_summary", "")

    destination_email = user_email  # server-controlled; never from LLM output

    # report_data may still be None if the LLM jumped the gun before
    # generate_final_report ran. Guard defensively.
    current_report = report_data or {}

    try:
        send_result = _send_itinerary_email(
            to_email=destination_email or "",
            report_data=current_report,
            pnr=pnr,
            passenger_summary=passenger_summary,
        )
    except Exception as unexpected:
        # Belt-and-suspenders: _send_itinerary_email already catches all
        # exceptions internally, but this outer block ensures the chatbot
        # never crashes even if something truly unexpected occurs.
        log.exception(
            "Unexpected error in send_itinerary_email dispatch: %s", unexpected
        )
        send_result = {
            "success": False,
            "error_code": "SERVICE_UNAVAILABLE",
            "detail": str(unexpected),
        }

    if send_result["success"]:
        email_sent = True
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": (
                f"EMAIL_SENT: Itinerary confirmation dispatched to the passenger's "
                f"registered address (PNR: {pnr}, passengers: {passenger_summary}). "
                f"Tell the user their booking confirmation is on its way to their inbox. "
                f"Wish them a great trip."
            ),
        })
    else:
        # Return only the sanitised error code to the LLM;
        # the technical detail stays in the server log.
        error_code = send_result.get("error_code", "SERVICE_UNAVAILABLE")
        email_sent = True  # mark as "attempted" so we don't retry endlessly
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": (
                f"EMAIL_FAILED: status={error_code}. "
                f"Activate the email-failure fallback protocol: reassure the user "
                f"that their booking IS confirmed, display the ticket details directly "
                f"in the chat, and direct them to the My Trips section of the app."
            ),
        })

    return report_data, skip_followup, email_sent
