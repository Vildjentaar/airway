"""
llm/tool_dispatch/cart.py
--------------------------
Handlers for cart-mutation tools:
  - generate_flight_widget  (validate + add to cart)
  - remove_flight_from_cart (remove by flight number)

Both handlers mutate ``flight_data`` in place (matching the legacy
``_dispatch_tool_call`` contract) and append their tool-response message
to ``messages``.
"""

from __future__ import annotations

from typing import Optional

from llm.flight_validation import build_verified_flight


def handle_generate_flight_widget(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Validate & price a flight, then append it to the cart.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False
    skip_followup = False

    result = build_verified_flight(tool_args, flight_data)

    if "error" in result:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": f"Error: {result['error']}",
        })
        return report_data, skip_followup, email_sent

    verified = result["flight"]
    flight_data.append(verified)

    pricing = verified.get("pricing_details", {})
    first_seg = verified["segments"][0]
    last_seg = verified["segments"][-1]

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": (
            f"Flight {first_seg['flight_number']} ({first_seg['departure_point']} → {last_seg['arrival_point']}, "
            f"{verified['ticket_class']}, {first_seg['departure_date']}) added to cart. "
            f"Price breakdown — subtotal: {pricing.get('subtotal_tl', 'N/A')} TL, "
            f"tax: {pricing.get('tax_tl', 'N/A')} TL, "
            f"fees: {pricing.get('fees_tl', 'N/A')} TL, "
            f"total: {pricing.get('total_tl', verified.get('price_tl', 'N/A'))} TL. "
            f"Confirm to the user in THEIR language. "
            f"Remind them they can add more flights or proceed to checkout."
        ),
    })

    return report_data, skip_followup, email_sent


def handle_remove_flight(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Remove a flight from the cart by its flight number.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False
    skip_followup = False

    fn_to_remove = tool_args.get("flight_number")
    original_len = len(flight_data)
    flight_data[:] = [
        f for f in flight_data
        if not (f.get("segments") and f["segments"][0]["flight_number"] == fn_to_remove)
    ]
    if len(flight_data) < original_len:
        content = f"Successfully removed {fn_to_remove} from cart."
    else:
        content = f"Flight {fn_to_remove} not found in cart."

    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})
    return report_data, skip_followup, email_sent
