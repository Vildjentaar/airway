"""
UI/export.py
-------------
Session export utilities: build a human-readable markdown transcript and
a raw JSON debug log from session data.

No Streamlit imports — these are pure data transforms.
"""

import json
from datetime import datetime


def build_transcript(
    messages: list,
    flight_data: list,
    report_data: dict,
    is_valid_flight_data,
) -> str:
    """
    Human-readable markdown transcript of the conversation.

    `is_valid_flight_data` is injected (rather than imported) so this module
    has no dependency on llm_engine — it just needs a predicate function.
    """
    lines = [
        "# Airline Booking Transcript",
        f"_Exported: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
    ]
    for msg in messages or []:
        if msg.get("hidden"):
            continue

        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "system":
            continue
        elif role == "user":
            lines.append(f"**User:** {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                continue
            elif content:
                lines.append(f"**Assistant:** {content}")
        elif role == "tool":
            continue

        lines.append("")

    if flight_data and is_valid_flight_data(flight_data):
        lines += [
            "---",
            "## 🛫 Booked Flights",
        ]
        total_price = 0
        for fd in flight_data:
            lines += [
                f"- **Route:** {fd.get('departure_point')} → {fd.get('arrival_point')}",
                f"- **Trip type:** {fd.get('trip_type')}",
                f"- **Departure:** {fd.get('departure_date')} at {fd.get('departure_time')}",
                f"- **Arrival:** {fd.get('arrival_time')} | Duration: {fd.get('flight_duration')}",
                f"- **Flight:** {fd.get('airline_name')} {fd.get('flight_number')} ({fd.get('transfer_status')})",
                f"- **Price:** {fd.get('price_tl')} TL",
            ]
            if fd.get("return_date"):
                lines.append(f"- **Return:** {fd.get('return_date')}")
            total_price += fd.get("price_tl", 0)

        _rep = report_data or {}
        if _rep.get("seat_selections"):
            lines.append("### 💺 Seat Selections")
            for s in _rep["seat_selections"]:
                lines.append(f"- Passenger {s['passenger_idx']+1}: Seat **{s['seat_id']}** ({s['type']}) — {s['price_tl']} TL")
                total_price += s.get("price_tl", 0)

        if _rep.get("luggage_selections"):
            lines.append("### 🧳 Luggage")
            for l in _rep["luggage_selections"]:
                lines.append(f"- Passenger {l['passenger_idx']+1}: {l['tier']} — {l['price_tl']} TL")
                total_price += l.get("price_tl", 0)

        if _rep.get("extras_selections"):
            lines.append("### ✨ Extra Services")
            for e in _rep["extras_selections"]:
                lines.append(f"- {e['service']} — {e['price_tl']} TL")
                total_price += e.get("price_tl", 0)

        lines.append(f"- **Total Price:** {total_price} TL")

    if report_data and not report_data.get("render_form"):
        lines += [
            "",
            "---",
            "## 📊 Session Report",
            f"- **Summary:** {report_data.get('passenger_summary', 'N/A')}",
            f"- **Flow:** {report_data.get('process_smoothness', 'N/A')}",
            f"- **Evaluation:** {report_data.get('overall_evaluation', 'N/A')}",
        ]
        issues = report_data.get("issues_encountered", [])
        if isinstance(issues, list) and issues:
            lines.append("- **Issues:**")
            for iss in issues:
                lines.append(f"  - {iss}")

    return "\n".join(lines)


def _make_serializable(obj):
    """Recursively convert any non-JSON-native value to a safe primitive."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {
            k: _make_serializable(v)
            for k, v in obj.items()
            # Skip the raw SDK object stored for thought_signature preservation —
            # it is not JSON-serializable and is an internal engine detail only.
            if k != "_raw_response_message"
        }
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    # datetime.date, datetime.datetime, Decimal, Enum, custom objects, etc.
    return str(obj)


def build_raw_log(
    messages: list,
    flight_data: list,
    report_data: dict,
) -> str:
    """Full JSON dump of session state for debugging."""
    payload = {
        "messages": messages,
        "flight_data": flight_data,
        "report_data": report_data,
    }
    return json.dumps(_make_serializable(payload), indent=2, ensure_ascii=False)