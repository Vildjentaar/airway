"""
llm/tool_dispatch/unknown.py
------------------------------
Fallback handler for unrecognised tool names.
"""

from __future__ import annotations

from typing import Optional


def handle_unknown(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
    **kwargs,
):
    """Append an error message for an unknown tool.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    function_name = getattr(tool_call.function, "name", "???")
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": f"Error: Unknown function '{function_name}'.",
    })
    return report_data, False, False
