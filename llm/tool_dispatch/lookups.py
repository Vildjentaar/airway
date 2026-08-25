"""
llm/tool_dispatch/lookups.py
-----------------------------
Passthrough handler for the 9 read-only DB-lookup tools.

All of these tools share the same structural pattern: delegate to
``tool_dispatcher.dispatch_tool`` and return the JSON result.  Rather
than duplicating this logic nine times, a single ``handle_passthrough``
function covers them all; the registry in ``__init__.py`` maps each
tool name to this one handler.
"""

from __future__ import annotations

import json
from typing import Optional


# The canonical list of tool names handled by this module.  The
# registry in ``__init__.py`` iterates over this to build its mapping.
PASSTHROUGH_NAMES = [
    "search_flights",
    "find_flight",
    "get_route_details",
    "list_all_routes",
    "route_catalogue",
    "list_airports",
    "get_airport_info",
    "list_bookings",
    "get_booking_details",
    "find_alternative_routes",
]


def handle_passthrough(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
    *,
    _function_name: str = "",
):
    """Delegate to the existing ``tool_dispatcher`` and append the JSON result.

    The ``_function_name`` keyword argument is injected by the registry's
    ``dispatch_tool_call`` wrapper so the handler knows which tool to call
    (the handler itself is tool-agnostic).

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    from tool_dispatcher import dispatch_tool

    email_sent = False
    skip_followup = False

    result = dispatch_tool(_function_name, tool_args)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(result, ensure_ascii=False),
    })

    return report_data, skip_followup, email_sent
