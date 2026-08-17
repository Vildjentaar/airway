"""
llm_engine.py
-------------
The "brain" of the chatbot. Handles all communication with the Gemini API
(via the OpenAI-compatible endpoint), message-history sanitization, and
tool-call dispatch.

DELIBERATELY INDEPENDENT OF STREAMLIT. Nothing in this module imports or
touches `st.session_state`. Functions take plain Python data in and return
plain Python data out, which means this exact file can later be dropped
into a FastAPI/Flask route and served to a React/Vue frontend with zero
changes.

Public entry point: `call_llm(client, messages, flight_data, report_data, ancillary_data)`
"""

import json
import re as _re
from datetime import datetime
from typing import Optional

from thall_lines_db import (
    find_flight, AIRLINE_NAME,
)
from pricing import calculate_total_price
from booking_context import ctx_get_current_datetime, ctx_get_relative_dates, ctx_get_booking_window
from accounts import validate_tckn

# Attempt to import check_capacity if it was added to thall_lines_db
try:
    from thall_lines_db import db_check_capacity
except ImportError:
    db_check_capacity = None

from tools_schema import (
    flight_widget_tool, final_report_tool, check_capacity_tool,
    remove_flight_tool, db_tools, context_tool,
    PRE_CART_TOOLS, POST_CART_TOOLS,
)

MODEL_NAME = "gemini-3.5-flash-lite"
MAX_HISTORY_MESSAGES = 100
MAX_TOOL_RESULT_CHARS = 800

FLIGHT_REQUIRED = [
    "departure_point", "arrival_point", "departure_date",
    "departure_time", "arrival_time", "flight_duration", "flight_number",
]


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def is_valid_flight_data(data) -> bool:
    """Returns True only when all required fields are non-empty and price > 0 for all flights in the cart."""
    if not data or not isinstance(data, list):
        return False
    for flight in data:
        all_filled = all(str(flight.get(f, "")).strip() for f in FLIGHT_REQUIRED)
        price_ok = bool(flight.get("price_tl", 0))
        if not (all_filled and price_ok):
            return False
    return True


def _truncate_tool_results(messages: list) -> list:
    """
    Return a copy of `messages` where any tool-role message whose content
    exceeds MAX_TOOL_RESULT_CHARS is replaced with a short summary.
    """
    out = []
    for msg in messages:
        if msg.get("role") == "tool":
            content = msg.get("content") or ""
            if len(content) > MAX_TOOL_RESULT_CHARS:
                preview = content[:MAX_TOOL_RESULT_CHARS]
                truncated = dict(msg)
                truncated["content"] = (
                    preview
                    + f"\n... [truncated — {len(content) - MAX_TOOL_RESULT_CHARS} chars omitted to stay within context limit]"
                )
                out.append(truncated)
                continue
        out.append(msg)
    return out


def _extract_code(value: str) -> str:
    """Extract an IATA code or city name from strings like 'Ankara (ESB)' or 'istanbul (ist)'."""
    m = _re.search(r'\(([A-Za-z]{3})\)', value)
    if m:
        return m.group(1).upper()
    return value.strip()




def _sanitize_for_gemini(messages: list) -> list:
    """
    Clean up the message list so it conforms to Gemini's strict turn-sequence rules:
    1. Merge consecutive messages with the same role (user+user -> single user).
    2. If an assistant message has tool_calls but its corresponding tool responses
       were lost (e.g. due to truncation), drop that orphaned assistant message.
    3. Ensure the conversation never has two user turns in a row.
    """
    if not messages:
        return messages

    out = [messages[0]]

    for msg in messages[1:]:
        role = msg.get("role")
        prev = out[-1]
        prev_role = prev.get("role")

        if role == "user" and prev_role == "user":
            out[-1] = dict(prev)
            out[-1]["content"] = (prev.get("content") or "") + "\n" + (msg.get("content") or "")
            continue

        if role == "assistant" and prev_role == "assistant" and not msg.get("tool_calls"):
            out[-1] = dict(prev)
            out[-1]["content"] = (prev.get("content") or "") + "\n" + (msg.get("content") or "")
            continue

        out.append(msg)

    cleaned = []
    i = 0
    while i < len(out):
        msg = out[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tool_call_ids = set()
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    tool_call_ids.add(tc_id)

            j = i + 1
            found_any = False
            while j < len(out) and out[j].get("role") == "tool":
                if out[j].get("tool_call_id") in tool_call_ids:
                    found_any = True
                j += 1

            if not found_any:
                i += 1
                continue

        cleaned.append(msg)
        i += 1

    # Final pass: The conversation MUST start with a user message (after the system message).
    # If MAX_HISTORY_MESSAGES sliced the history, inject a placeholder to prevent context wipeout.
    if len(cleaned) > 1:
        system_msg = cleaned[0]
        rest = cleaned[1:]
        if rest[0].get("role") != "user":
            rest.insert(0, {
                "role": "user",
                "content": "[System Note: Earlier conversation was truncated to preserve memory context.]",
                "hidden": True
            })
        cleaned = [system_msg] + rest

    return cleaned


def _build_verified_flight(tool_args: dict, flight_data: list) -> dict:
    """
    Validates a `generate_flight_widget` call and, if valid, prices it and
    returns the flight record ready to add to the cart.

    Deliberately kept separate from `_dispatch_tool_call`: this function
    only knows about booking rules (passenger counts, dates, route
    existence, pricing, duplicates) and returns plain data. It has no idea
    a `tool_call` or a `messages` list exists. That split means the
    validation/pricing logic here can be tested or reused (e.g. from a
    future non-chat booking form) without dragging tool-call plumbing
    along with it, and adding a new validation rule never requires
    touching the tool-call bookkeeping in `_dispatch_tool_call`.

    Returns {"error": "..."} or {"flight": {...}}.
    """
    dep = _extract_code(tool_args.get("departure_point", ""))
    arr = _extract_code(tool_args.get("arrival_point", ""))
    trip_type = tool_args.get("trip_type", "One-way")

    adult_count = int(tool_args.get("adult_count", 0))
    child_count = int(tool_args.get("child_count", 0))
    baby_count = int(tool_args.get("baby_count", 0))
    ticket_class = tool_args.get("ticket_class", "Economy")

    # Fallback if old passenger_count is used by the model
    passenger_count = int(tool_args.get("passenger_count", 0))
    if passenger_count > 0 and adult_count == 0 and child_count == 0 and baby_count == 0:
        adult_count = passenger_count

    passengers = adult_count + child_count + baby_count
    passengers_breakdown = {"Adult": adult_count, "Child": child_count, "Baby": baby_count}

    if passengers <= 0 or passengers > 9:
        return {"error": "Invalid passenger count. Cannot book more than 9 passengers per transaction."}

    dep_date_str = tool_args.get("departure_date", "")
    try:
        dep_date_parsed = datetime.strptime(dep_date_str, "%Y-%m-%d")
        if dep_date_parsed.date() < datetime.now().date():
            return {"error": "Departure date cannot be in the past."}
    except ValueError:
        return {"error": "Invalid departure_date format. Must be YYYY-MM-DD."}

    missing_user_fields = [
        f for f in ["departure_point", "arrival_point", "departure_date"]
        if not str(tool_args.get(f, "")).strip()
    ]
    if missing_user_fields:
        return {"error": (
            f"Cannot render the flight widget yet. "
            f"Still missing: {', '.join(missing_user_fields)}. "
            f"Resume the booking sequence."
        )}

    outbound = find_flight(dep, arr)
    if not outbound:
        return {"error": (
            f"No route found from '{dep}' to '{arr}'. "
            f"{AIRLINE_NAME} does not operate that route. "
            f"Inform the user and offer available alternatives."
        )}

    inbound = find_flight(arr, dep) if trip_type == "Round-trip" else None
    if trip_type == "Round-trip" and not inbound:
        return {"error": (
            f"No return route found from '{arr}' to '{dep}'. "
            f"{AIRLINE_NAME} does not operate that return route. Inform the user."
        )}

    pricing_details = calculate_total_price(
        outbound, passengers, trip_type, inbound,
        detailed=True, ticket_class=ticket_class, passengers_breakdown=passengers_breakdown
    )
    verified = {
        "departure_point": dep,
        "arrival_point": arr,
        "trip_type": trip_type,
        "departure_date": tool_args.get("departure_date", ""),
        "return_date": tool_args.get("return_date", ""),
        "passenger_count": passengers,
        "adult_count": adult_count,
        "child_count": child_count,
        "baby_count": baby_count,
        "ticket_class": ticket_class,
        "departure_time": outbound["departure_time"],
        "arrival_time": outbound["arrival_time"],
        "flight_duration": outbound["duration"],
        "transfer_status": outbound["transfer_status"].value if hasattr(outbound["transfer_status"], "value") else outbound["transfer_status"],
        "airline_name": AIRLINE_NAME,
        "flight_number": outbound["flight_number"],
        "price_tl": pricing_details["total_tl"],
        "pricing_details": pricing_details,
    }

    if trip_type == "Round-trip" and inbound:
        verified["return_flight_number"] = inbound["flight_number"]
        verified["return_departure_time"] = inbound["departure_time"]
        verified["return_arrival_time"] = inbound["arrival_time"]
        verified["return_duration"] = inbound["duration"]
        verified["return_transfer_status"] = inbound["transfer_status"].value if hasattr(inbound["transfer_status"], "value") else inbound["transfer_status"]

    is_duplicate = any(
        f["flight_number"] == verified["flight_number"]
        and f["departure_date"] == verified["departure_date"]
        for f in flight_data
    )
    if is_duplicate:
        return {"error": f"Flight {verified['flight_number']} on {verified['departure_date']} is already in the cart."}

    return {"flight": verified}


def _select_active_tools(messages: list, flight_data: list, report_data):
    """Decide which tools (if any) should be offered to the model on this turn."""
    if report_data is not None:
        return [], "none"
    if len(messages) <= 2 and messages[-1].get("hidden"):
        return [], "none"
    if flight_data:
        return POST_CART_TOOLS, "auto"
    return PRE_CART_TOOLS, "auto"


# --------------------------------------------------------------------------
# Tool dispatch (one function call handled at a time)
# --------------------------------------------------------------------------

def _dispatch_tool_call(tool_call, function_name, tool_args, messages: list, flight_data: list, report_data, ancillary_data: Optional[dict] = None):
    """
    Executes a single tool call, appending the resulting tool message(s) to
    `messages` in place and mutating `flight_data` in place where relevant.

    Returns (new_report_data, skip_followup: bool).
    """
    skip_followup = False

    if function_name == "generate_flight_widget":
        result = _build_verified_flight(tool_args, flight_data)

        if "error" in result:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Error: {result['error']}",
            })
            return report_data, skip_followup

        verified = result["flight"]
        flight_data.append(verified)

        pricing = verified.get("pricing_details", {})
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": (
                f"Flight {verified['flight_number']} ({verified['departure_point']} → {verified['arrival_point']}, "
                f"{verified['ticket_class']}, {verified['departure_date']}) added to cart. "
                f"Price breakdown — subtotal: {pricing.get('subtotal_tl', 'N/A')} TL, "
                f"tax: {pricing.get('tax_tl', 'N/A')} TL, "
                f"fees: {pricing.get('fees_tl', 'N/A')} TL, "
                f"total: {pricing.get('total_tl', verified.get('price_tl', 'N/A'))} TL. "
                f"Confirm to the user in THEIR language. "
                f"Remind them they can add more flights or proceed to checkout."
            ),
        })

    elif function_name == "remove_flight_from_cart":
        fn_to_remove = tool_args.get("flight_number")
        original_len = len(flight_data)
        flight_data[:] = [f for f in flight_data if f["flight_number"] != fn_to_remove]
        if len(flight_data) < original_len:
            content = f"Successfully removed {fn_to_remove} from cart."
        else:
            content = f"Flight {fn_to_remove} not found in cart."
        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})

    elif function_name == "check_capacity":
        from tool_dispatcher import dispatch_tool
        res = dispatch_tool(function_name, tool_args)
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
            "content": json.dumps(result, ensure_ascii=False)
        })

    elif function_name == "generate_final_report":
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
        else:
            report_data = tool_args
            report_data["booked_flights"] = list(flight_data)

            # Inject ancillary selections so the final report can display them
            _anc = ancillary_data or {}
            report_data["seat_selections"] = _anc.get("seat_selections", [])
            report_data["luggage_selections"] = _anc.get("luggage_selections", [])
            report_data["extras_selections"] = _anc.get("extras_selections", [])

            flight_data.clear()

            booked_summary = "; ".join(
                f"{f.get('flight_number')} {f.get('departure_point')}→{f.get('arrival_point')} "
                f"({f.get('ticket_class')}, {f.get('departure_date')})"
                for f in report_data["booked_flights"]
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": (
                    f"Final report generated. Booked flights: {booked_summary}. "
                    f"Tell the user (in THEIR language) that the itinerary is finalized "
                    f"and the summary report is shown below. Wish them a great trip."
                ),
                "report_data": report_data
            })

    elif function_name in [
        "search_flights", "find_flight", "get_route_details", "list_all_routes",
        "route_catalogue", "list_airports", "get_airport_info", "list_bookings", "get_booking_details"
    ]:
        from tool_dispatcher import dispatch_tool
        result = dispatch_tool(function_name, tool_args)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    elif function_name == "get_context":
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

    elif function_name == "validate_tckn":
        tckn_str = tool_args.get("tckn", "")
        result = validate_tckn(tckn_str)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    elif function_name == "render_secure_form":
        form_type = tool_args.get("form_type", "auth")
        if report_data is None:
            # We use report_data as a generic dict to signal the UI
            report_data = {}
        report_data["render_form"] = form_type
        
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": f"Form '{form_type}' rendered. Waiting for user submission...",
            "report_data": report_data
        })
        skip_followup = True

    else:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": f"Error: Unknown function '{function_name}'.",
        })

    return report_data, skip_followup


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def call_llm(client, messages: list, flight_data: list, report_data, ancillary_data: Optional[dict] = None):
    """
    Sends the current message history to the model, handles any tool calls
    it requests, and returns the updated state.

    Pure(ish) function: `messages` and `flight_data` are copied before
    mutation, so the caller's original objects are left untouched — the
    caller is expected to persist the returned state (e.g. back into
    st.session_state, or a database row, or an HTTP response body).

    Returns a dict:
        {
            "messages": [...],       # updated message history
            "flight_data": [...],    # updated cart
            "report_data": {...} | None,
            "success": bool,
            "error": str | None,     # human-readable error, if any
        }
    """
    messages = [dict(m) for m in messages]
    flight_data = [dict(f) for f in flight_data] if flight_data else []
    last_error = None

    system_msg = [messages[0]]
    recent = messages[1:][-MAX_HISTORY_MESSAGES:]
    trimmed = _sanitize_for_gemini(_truncate_tool_results(system_msg + recent))

    active_tools, active_tool_choice = _select_active_tools(messages, flight_data, report_data)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=trimmed,
            temperature=0.4,
            tools=active_tools if active_tools else None,
            tool_choice=active_tool_choice if active_tools else "none",
        )
    except Exception as e:
        return {
            "messages": messages,
            "flight_data": flight_data,
            "report_data": report_data,
            "success": False,
            "error": str(e),
        }

    response_message = response.choices[0].message

    if response_message.tool_calls:
        messages.append(response_message.model_dump(exclude_none=True))

        skip_followup = False
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as parse_err:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Error: Malformed JSON in tool arguments — {parse_err}",
                })
                last_error = f"`{function_name}` returned malformed JSON: {parse_err}"
                continue

            report_data, call_skip = _dispatch_tool_call(
                tool_call, function_name, tool_args, messages, flight_data, report_data,
                ancillary_data=ancillary_data,
            )
            skip_followup = skip_followup or call_skip

        if not skip_followup:
            print("\n[DEBUG] --- TOOL OUTPUTS BEFORE FOLLOW-UP ---")
            for msg in messages:
                if msg.get("role") == "tool" and msg.get("tool_call_id") in [tc.id for tc in response_message.tool_calls]:
                    print(f"Tool {msg.get('tool_call_id')}: {msg.get('content')}")
            print("[DEBUG] ---------------------------------------")

            followup_trimmed = _sanitize_for_gemini(_truncate_tool_results(
                [messages[0]] + messages[1:][-MAX_HISTORY_MESSAGES:]
            ))
            try:
                followup = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=followup_trimmed,
                    temperature=0.3,
                    tools=None,
                    tool_choice="none",
                )
                followup_text = (followup.choices[0].message.content or "").strip()
                print(f"[DEBUG] Follow-up text from model: {repr(followup_text)}")
                
                if followup_text:
                    messages.append({"role": "assistant", "content": followup_text})
                else:
                    messages.append({
                        "role": "assistant",
                        "content": "I've processed your request, but I'm having trouble formatting the response. Could you let me know how you'd like to proceed?"
                    })
            except Exception as follow_err:
                last_error = str(follow_err)
                messages.append({
                    "role": "assistant",
                    "content": "I encountered an error connecting to the server. Please try again.",
                })

    else:
        bot_reply = response_message.content or ""
        stripped = bot_reply.strip()
        looks_like_text_tool_call = (
            ('{"name":' in stripped or '{"function":' in stripped or '{"tool":' in stripped)
            and '"parameters":' in stripped
        )
        if looks_like_text_tool_call:
            last_error = (
                "The model tried to perform an action but used the wrong format. "
                "Please repeat your last message and it will be handled correctly."
            )
        else:
            if not stripped:
                bot_reply = "I'm sorry, There was a connection glitch and I couldn't process that. Could you please repeat?"
            messages.append({"role": "assistant", "content": bot_reply})

    return {
        "messages": messages,
        "flight_data": flight_data,
        "report_data": report_data,
        "success": True,
        "error": last_error,
    }
