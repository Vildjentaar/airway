"""
llm/tool_dispatch/context.py
------------------------------
Handler for the ``get_context`` tool.

Routes the ``info_type`` parameter to the appropriate context function
in ``booking_context``.
"""

from __future__ import annotations

import json
from typing import Optional

from booking_context import (
    ctx_get_current_datetime,
    ctx_get_relative_dates,
    ctx_get_booking_window,
)


def handle_get_context(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Resolve a context lookup and append the result.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False
    skip_followup = False

    info_type = tool_args.get("info_type", "")
    try:
        if info_type == "current_datetime":
            result = ctx_get_current_datetime()
        elif info_type == "relative_dates":
            result = ctx_get_relative_dates()
        elif info_type == "booking_window":
            result = ctx_get_booking_window()
        else:
            result = {"error": f"Unknown info_type '{info_type}'."}
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })
    except Exception as ctx_err:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": f"Error fetching '{info_type}': {ctx_err}",
        })

    return report_data, skip_followup, email_sent
