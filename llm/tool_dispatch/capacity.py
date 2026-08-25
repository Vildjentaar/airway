"""
llm/tool_dispatch/capacity.py
------------------------------
Handler for the ``check_capacity`` tool.

Delegates to ``tool_dispatcher.dispatch_tool`` (the existing DB-lookup
dispatcher) and reformats the raw capacity response into a structured
status message for the LLM.
"""

from __future__ import annotations

import json
from typing import Optional


def handle_check_capacity(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Check seat availability for a given flight + passenger count.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    from tool_dispatcher import dispatch_tool

    email_sent = False
    skip_followup = False

    res = dispatch_tool("check_capacity", tool_args)
    if "error" in res:
        result = {"status": "Error", "message": res["error"]}
    else:
        cap_info = res["result"]
        if "error" in cap_info:
            result = {"status": "Error", "message": cap_info["error"]}
        else:
            avail = cap_info.get("seats_remaining", 0)
            pax = tool_args.get("additional_passengers", 1)
            status = "Available" if avail >= pax else "Unavailable"
            result = {"status": status, "remaining_seats": avail}

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(result, ensure_ascii=False),
    })

    return report_data, skip_followup, email_sent
