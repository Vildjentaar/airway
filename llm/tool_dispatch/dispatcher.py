"""
tool_dispatcher.py

Secure dispatcher for LLM tools.

The LLM never sees SQL.
The LLM never imports Python modules.
The LLM can only call named tools that we explicitly expose.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import db


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowlisted tools
# ---------------------------------------------------------------------------
SAFE_TOOLS: dict[str, Callable[..., Any]] = {
    # Flight/route tools
    "search_flights": db.search_flights,
    "find_flight": db.find_flight,
    "find_alternative_routes": db.db_find_alternative_routes,
    "search_itinerary": db.db_search_itinerary,
    "get_route_details": db.db_get_route_details,
    "list_all_routes": db.db_list_all_routes,
    "route_catalogue": db.route_catalogue,

    # Airport tools
    "list_airports": db.db_list_airports,
    "get_airport_info": db.db_get_airport_info,

    # Booking tools
    "list_bookings": db.db_list_bookings,
    "get_booking_details": db.get_booking_details,

    # Capacity tools
    "check_capacity": db.db_check_capacity,
}


def dispatch_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """
    Execute an allowlisted tool.

    This function should be called only by your backend after receiving
    a structured tool-call from the LLM provider.
    """
    if not isinstance(tool_name, str):
        return {"error": "Tool name must be a string."}

    if tool_name not in SAFE_TOOLS:
        return {"error": f"Unknown tool: {tool_name}"}

    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be an object."}

    tool_fn = SAFE_TOOLS[tool_name]

    try:
        result = tool_fn(**arguments)
        return {"success": True, "result": result}

    except TypeError as exc:
        return {"error": f"Invalid arguments for tool '{tool_name}': {exc}"}

    except Exception:
        # Log full details internally.
        # Do not leak raw DB errors to the LLM/user.
        logger.exception("Tool execution failed: %s", tool_name)
        return {"error": "Tool execution failed."}
