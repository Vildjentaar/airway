"""
llm/tool_dispatch/__init__.py
------------------------------
Tool-dispatch registry and public ``dispatch_tool_call`` façade.

Instead of a monolithic if/elif chain, each tool (or group of related
tools) has a dedicated handler module.  The registry maps tool names to
handler callables so adding a new tool is "write a handler + one
registry line".

Public API
~~~~~~~~~~
.. code-block:: python

    from llm.tool_dispatch import dispatch_tool_call

    report_data, skip_followup, email_sent = dispatch_tool_call(
        tool_call, function_name, tool_args,
        messages, flight_data, report_data,
        ancillary_data=ancillary_data,
        user_email=user_email,
    )
"""

from __future__ import annotations

from typing import Optional

from . import cart, capacity, reporting, lookups, context, forms, unknown


# --------------------------------------------------------------------------- #
# Handler registry
# --------------------------------------------------------------------------- #

HANDLERS: dict[str, object] = {
    # Cart mutations
    "generate_flight_widget": cart.handle_generate_flight_widget,
    "remove_flight_from_cart": cart.handle_remove_flight,

    # Capacity check
    "check_capacity": capacity.handle_check_capacity,

    # Booking finalisation & email
    "generate_final_report": reporting.handle_generate_final_report,
    "send_itinerary_email": reporting.handle_send_itinerary_email,

    # Context lookups
    "get_context": context.handle_get_context,

    # Identity & forms
    "validate_tckn": forms.handle_validate_tckn,
    "render_secure_form": forms.handle_render_secure_form,
}

# Register all passthrough DB-lookup tools under a single shared handler.
# Each name maps to the *same* function; the actual tool name is threaded
# through via the ``_function_name`` keyword by ``dispatch_tool_call`` below.
for _name in lookups.PASSTHROUGH_NAMES:
    HANDLERS[_name] = lookups.handle_passthrough


# --------------------------------------------------------------------------- #
# Public façade
# --------------------------------------------------------------------------- #

def dispatch_tool_call(
    tool_call,
    function_name: str,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Dispatch a single tool call to its registered handler.

    Returns ``(report_data, skip_followup: bool, email_sent: bool)``.
    """
    handler = HANDLERS.get(function_name, unknown.handle_unknown)

    # For passthrough handlers we need to inject the tool name so the
    # handler knows which DB function to call.
    if handler is lookups.handle_passthrough:
        return handler(
            tool_call, tool_args, messages, flight_data, report_data,
            ancillary_data, user_email,
            _function_name=function_name,
        )

    return handler(
        tool_call, tool_args, messages, flight_data, report_data,
        ancillary_data, user_email,
    )
