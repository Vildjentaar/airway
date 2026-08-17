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
        segments = flight.get("segments", [])
        if not segments:
            return False
        for segment in segments:
            all_filled = all(str(segment.get(f, "")).strip() for f in FLIGHT_REQUIRED)
            if not all_filled:
                return False
        price_ok = bool(flight.get("price_tl", 0))
        if not price_ok:
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

        # Only merge two consecutive assistant messages if NEITHER has tool_calls.
        # Merging into a message that has tool_calls would produce a muddled entry
        # with both tool_calls and unrelated free text.
        if (role == "assistant" and prev_role == "assistant"
                and not msg.get("tool_calls") and not prev.get("tool_calls")):
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
            found_ids = set()
            while j < len(out) and out[j].get("role") == "tool":
                if out[j].get("tool_call_id") in tool_call_ids:
                    found_ids.add(out[j].get("tool_call_id"))
                j += 1

            # Every tool_call_id must have a matching tool response;
            # otherwise the API will reject the malformed history.
            if found_ids != tool_call_ids:
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
    segments = tool_args.get("segments", [])
    if not segments:
        return {"error": "No flight segments provided."}

    trip_type = tool_args.get("trip_type", "One-way")
    adult_count = int(tool_args.get("adult_count", 0))
    child_count = int(tool_args.get("child_count", 0))
    baby_count = int(tool_args.get("baby_count", 0))
    ticket_class = tool_args.get("ticket_class", "Economy")

    # Fallback if old passenger_count is used by the model
    passenger_count = int(tool_args.get("passenger_count", 0))
    if passenger_count > 0 and adult_count == 0 and child_count == 0 and baby_count == 0:
        adult_count = passenger_count

    if adult_count < 0 or child_count < 0 or baby_count < 0:
        return {"error": "Passenger counts cannot be negative."}

    passengers = adult_count + child_count + baby_count
    passengers_breakdown = {"Adult": adult_count, "Child": child_count, "Baby": baby_count}

    if passengers <= 0 or passengers > 9:
        return {"error": "Invalid passenger count. Cannot book more than 9 passengers per transaction."}

    verified_segments = []
    prev_dep_date = None

    for seg_idx, seg in enumerate(segments):
        dep = _extract_code(seg.get("departure_point", ""))
        arr = _extract_code(seg.get("arrival_point", ""))
        dep_date_str = seg.get("departure_date", "")

        try:
            dep_date_parsed = datetime.strptime(dep_date_str, "%Y-%m-%d")
            if dep_date_parsed.date() < datetime.now().date():
                return {"error": f"Departure date {dep_date_str} cannot be in the past."}
        except ValueError:
            return {"error": f"Invalid departure_date format: {dep_date_str}. Must be YYYY-MM-DD."}

        # Cross-segment chronological ordering: each segment must depart
        # on or after the previous segment's departure date.
        if prev_dep_date is not None and dep_date_parsed.date() < prev_dep_date:
            return {"error": (
                f"Segment {seg_idx + 1} departs on {dep_date_str}, which is before "
                f"the previous segment's departure date ({prev_dep_date.isoformat()}). "
                f"Segments must be in chronological order."
            )}
        prev_dep_date = dep_date_parsed.date()

        flight_number_provided = seg.get("flight_number")
        if flight_number_provided:
            from thall_lines_db import get_flight_by_number
            found = get_flight_by_number(flight_number_provided)
            if not found or found["origin_code"] != dep or found["dest_code"] != arr:
                return {"error": f"Invalid flight number '{flight_number_provided}' for route {dep} to {arr}."}
        else:
            found = find_flight(dep, arr)
            if not found:
                return {"error": (
                    f"No route found from '{dep}' to '{arr}'. "
                    f"{AIRLINE_NAME} does not operate that route."
                )}

        verified_segments.append({
            "departure_point": dep,
            "arrival_point": arr,
            "departure_date": dep_date_str,
            "departure_time": found["departure_time"],
            "arrival_time": found["arrival_time"],
            "flight_duration": found["duration"],
            "transfer_status": found["transfer_status"].value if hasattr(found["transfer_status"], "value") else found["transfer_status"],
            "airline_name": AIRLINE_NAME,
            "flight_number": found["flight_number"],
            "base_price_tl": found["base_price_tl"]
        })

    pricing_details = calculate_total_price(
        verified_segments, passengers, trip_type,
        detailed=True, ticket_class=ticket_class, passengers_breakdown=passengers_breakdown
    )
    
    first_seg = verified_segments[0]
    
    verified = {
        "trip_type": trip_type,
        "passenger_count": passengers,
        "adult_count": adult_count,
        "child_count": child_count,
        "baby_count": baby_count,
        "ticket_class": ticket_class,
        "price_tl": pricing_details["total_tl"],
        "pricing_details": pricing_details,
        "segments": verified_segments,
    }

    # Compare ALL segments for duplicate detection, not just the first.
    # Two bookings sharing only the outbound but differing on return are
    # distinct, and vice versa.
    new_seg_keys = tuple(
        (s["flight_number"], s["departure_date"]) for s in verified_segments
    )
    is_duplicate = any(
        f.get("segments")
        and tuple(
            (s["flight_number"], s["departure_date"]) for s in f["segments"]
        ) == new_seg_keys
        for f in flight_data
    )
    if is_duplicate:
        return {"error": f"This itinerary is already in the cart."}

    return {"flight": verified}


def _select_active_tools(messages: list, flight_data: list, report_data):
    """Decide which tools (if any) should be offered to the model on this turn."""
    if report_data is not None:
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

    elif function_name == "remove_flight_from_cart":
        fn_to_remove = tool_args.get("flight_number")
        original_len = len(flight_data)
        flight_data[:] = [f for f in flight_data if not (f.get("segments") and f["segments"][0]["flight_number"] == fn_to_remove)]
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
                f"{f['segments'][0]['flight_number']} {f['segments'][0]['departure_point']}→{f['segments'][-1]['arrival_point']} "
                f"({f.get('ticket_class')}, {f['segments'][0]['departure_date']})"
                for f in report_data["booked_flights"] if f.get("segments")
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
    """
    messages = [dict(m) for m in messages]
    flight_data = [dict(f) for f in flight_data] if flight_data else []
    last_error = None

    max_turns = 5
    for turn in range(max_turns):
        # Recompute available tools each iteration — flight_data and
        # report_data are mutated inside the loop (e.g. generate_final_report
        # clears flight_data and sets report_data), so the tool list must
        # reflect the *current* state, not the state at call_llm entry.
        active_tools, active_tool_choice = _select_active_tools(
            messages, flight_data, report_data
        )

        system_msg = [messages[0]]
        recent = messages[1:][-MAX_HISTORY_MESSAGES:]
        
        # Flatten the history to strip Gemini-incompatible fields (thought_signature, etc.)
        # while keeping the structural integrity of assistant <-> tool turns.
        # IMPORTANT: assistant tool-call messages must NOT be omitted — if the model
        # can't see that it already called a tool, it will call it again every turn
        # until max_turns is exhausted.
        trimmed_recent = _truncate_tool_results(recent)

        # Map tool_call_id -> function name for labelling tool results.
        tool_id_to_name = {}
        for msg in recent:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg.get("tool_calls", []):
                    name = tc.get("function", {}).get("name") if isinstance(tc, dict) else getattr(tc.function, "name", "tool")
                    tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                    if tid and name:
                        tool_id_to_name[tid] = name

        flattened_messages = []
        for msg in trimmed_recent:
            if msg.get("role") == "tool":
                # Convert tool responses to user messages with XML tags so Gemini
                # can parse them without native tool-call schema.
                tid = msg.get("tool_call_id", "")
                name = tool_id_to_name.get(tid, "unknown_tool")
                flattened_messages.append({
                    "role": "user",
                    "content": f"<tool_result tool_name=\"{name}\">\n{msg.get('content', '')}\n</tool_result>"
                })
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Represent tool-call turns as a terse assistant stub so the model
                # knows it already acted on this turn. Omitting this entirely causes
                # the model to re-invoke the same tools on every subsequent turn.
                tool_calls = msg.get("tool_calls", [])
                call_labels = []
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name") if isinstance(tc, dict) else getattr(tc.function, "name", "tool")
                    call_labels.append(f"[Called: {fn_name}]")
                stub_text = (msg.get("content") or "").strip()
                if call_labels:
                    stub_text = (stub_text + "\n" if stub_text else "") + " ".join(call_labels)
                flattened_messages.append({"role": "assistant", "content": stub_text.strip() or "[Tool call]"})
            else:
                flattened_messages.append(dict(msg))

        flattened_history = _sanitize_for_gemini(system_msg + flattened_messages)

        # Circuit-breaker: if the model has already used several turns calling tools
        # without producing a text reply, inject a one-shot nudge (not persisted to
        # `messages`) asking it to stop and respond in natural language.
        CIRCUIT_BREAK_TURN = 3
        if turn >= CIRCUIT_BREAK_TURN and active_tools:
            nudge = {
                "role": "user",
                "content": (
                    "[System: You have already called tools multiple times. "
                    "Stop calling tools now and reply to the user in natural language, "
                    "summarising what you found or what action was taken.]"
                )
            }
            flattened_history = flattened_history + [nudge]

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=flattened_history,
                temperature=0.3,
                tools=active_tools if active_tools else None,
                tool_choice=active_tool_choice if active_tools else "none",
            )
        except Exception as e:
            last_error = str(e)
            break

        response_message = response.choices[0].message

        if response_message.tool_calls:
            # We append the original tool call to our permanent messages array
            messages.append(response_message.model_dump(exclude_none=True))

            skip_followup = False
            forms_called_this_turn = 0
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                
                if function_name == "render_secure_form":
                    if forms_called_this_turn > 0:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "Error: You can only call render_secure_form ONCE per turn. Please wait for the user to submit the current form before calling the next one."
                        })
                        continue
                    forms_called_this_turn += 1

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

            if skip_followup:
                break
            # Otherwise, loop around to make the follow-up request with the new tool results

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
                # Still append a user-visible reply so the conversation doesn't dead-end.
                messages.append({
                    "role": "assistant",
                    "content": "I'm sorry, I ran into a formatting issue. Could you please repeat your last request?",
                })
            else:
                # A clean assistant reply clears any residual last_error from
                # an earlier failed tool call that the model has since recovered from.
                last_error = None
                if not stripped:
                    bot_reply = "I'm sorry, There was a connection glitch and I couldn't process that. Could you please repeat?"
                messages.append({"role": "assistant", "content": bot_reply})
            break
    else:
        # If we exhausted max_turns without breaking, the LLM got stuck in a tool loop.
        messages.append({
            "role": "assistant", 
            "content": "I apologize, but I'm having trouble processing that request right now. Could you please rephrase it?"
        })
        last_error = "LLM exhausted max tool turns."

    return {
        "messages": messages,
        "flight_data": flight_data,
        "report_data": report_data,
        "success": last_error is None,
        "error": last_error,
    }
