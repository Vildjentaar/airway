"""
llm/tool_policy.py
------------------
Decides which tools (if any) the LLM is allowed to use on a given turn,
based on the current state of the cart, the final report, and email dispatch.

Three distinct tool-availability phases:

1. **Pre-cart** (no flights selected yet): full search + booking tools.
2. **Post-cart** (flights in cart, no report yet): adds report + removal tools.
3. **Post-report** (report generated): only `send_itinerary_email` is offered
   (with `tool_choice="required"` so the model *must* fire it), and once the
   email has been sent (or attempted), all tools are locked.

Public API:
    select_active_tools(messages, flight_data, report_data, email_sent)
        -> (tools: list, tool_choice: str)
"""

from .schemas import (
    PRE_CART_TOOLS,
    POST_CART_TOOLS,
    send_itinerary_email_tool,
)

# A minimal tool list offered to the LLM in the brief window immediately
# after `generate_final_report` succeeds. It contains only the email tool
# so the model can fire it once and then be told to produce a text reply.
POST_REPORT_TOOLS = send_itinerary_email_tool


def select_active_tools(
    messages: list,
    flight_data: list,
    report_data,
    email_sent: bool,
):
    """Decide which tools (if any) should be offered to the model on this turn.

    Returns
    -------
    tuple[list, str]
        (tool_definitions, tool_choice) ready to pass straight into the
        ``client.chat.completions.create()`` call.
    """
    if report_data is not None:
        # After generate_final_report, give the LLM exactly one chance to
        # call send_itinerary_email. Once the email has been sent (or if no
        # report exists), lock down to no tools.
        if not email_sent:
            return POST_REPORT_TOOLS, "required"
        return [], "none"
    if flight_data:
        return POST_CART_TOOLS, "auto"
    return PRE_CART_TOOLS, "auto"
