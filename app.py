import streamlit as st
from openai import OpenAI
from system_prompt import SYSTEM_PROMPT
import json
import os
import re as _re
from datetime import datetime
from dotenv import load_dotenv
from thall_lines_db import (
    AIRLINE_NAME, find_flight, calculate_total_price,
    AIRPORTS, _resolve_code,
    db_list_all_routes, db_get_route_details,
    db_list_airports, db_get_airport_info, db_list_bookings,
    ctx_get_current_datetime, ctx_get_relative_dates, ctx_get_booking_window,
)

# Attempt to import check_capacity if it was added to thall_lines_db
try:
    from thall_lines_db import db_check_capacity
except ImportError:
    db_check_capacity = None

load_dotenv()

flight_widget_tool = [
    {
        "type": "function",
        "function": {
            "name": "generate_flight_widget",
            "description": "Trigger this function ONLY when the user has confirmed their trip details and you are ready to generate the final visual summary card for the flight.",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure_point": {
                        "type": "string",
                        "description": "The city or airport code the user is flying from (e.g., Istanbul, IST)."
                    },
                    "arrival_point": {
                        "type": "string",
                        "description": "The city or airport code the user is flying to (e.g., Baku, GYD)."
                    },
                    "trip_type": {
                        "type": "string",
                        "enum": ["One-way", "Round-trip"],
                        "description": "Whether the flight is one-way or round-trip."
                    },
                    "departure_date": {
                        "type": "string",
                        "description": "The departure date agreed upon (format MUST be YYYY-MM-DD)."
                    },
                    "return_date": {
                        "type": "string",
                        "description": "The return date, if applicable. Leave blank if One-way."
                    },
                    "departure_time": {
                        "type": "string",
                        "description": "Generate a realistic mock departure time (e.g., 08:15)."
                    },
                    "arrival_time": {
                        "type": "string",
                        "description": "Generate a realistic mock arrival time based on the distance (e.g., 10:30)."
                    },
                    "flight_duration": {
                        "type": "string",
                        "description": "Generate a realistic mock flight duration (e.g., 2h 15m)."
                    },
                    "transfer_status": {
                        "type": "string",
                        "enum": ["Direct", "Connecting"],
                        "description": "Transfer status from the flight database."
                    },
                    "airline_name": {
                        "type": "string",
                        "description": f"The airline name (always {AIRLINE_NAME})."
                    },
                    "flight_number": {
                        "type": "string",
                        "description": "Flight number from the flight database (e.g., PX-0752)."
                    },
                    "price_tl": {
                        "type": "integer",
                        "description": "Total trip price in TL from the database (base price × passenger count)."
                    },
                    "passenger_count": {
                        "type": "integer",
                        "description": "Number of passengers the user specified."
                    }
                },
                "required": [
                    "departure_point", "arrival_point", "trip_type", "departure_date",
                    "departure_time", "arrival_time", "flight_duration",
                    "transfer_status", "airline_name", "flight_number", "price_tl",
                    "passenger_count"
                ]
            }
        }
    }
]

final_report_tool = [
    {
        "type": "function",
        "function": {
            "name": "generate_final_report",
            "description": "Trigger this ONLY after the user confirms their flight details from the widget. This generates the final analytical report of the chat session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "passenger_summary": {
                        "type": "string",
                        "description": "A short summary of the passenger's travel data."
                    },
                    "process_smoothness": {
                        "type": "string",
                        "enum": ["Smooth", "Minor Issues", "Problematic"],
                        "description": "Rate how easily the transaction was completed."
                    },
                    "issues_encountered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List any missing info, skipped steps, or off-topic questions the user attempted. If none, return an empty array."
                    },
                    "overall_evaluation": {
                        "type": "string",
                        "description": "A brief, final evaluation of the AI's performance and user experience."
                    }
                },
                "required": ["passenger_summary", "process_smoothness", "issues_encountered", "overall_evaluation"]
            }
        }
    }
]

check_availability_tool = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if a flight has enough capacity for the requested number of passengers. Must be called before booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": "string"},
                    "date": {"type": "string", "description": "Date of departure (YYYY-MM-DD)"},
                    "passengers": {"type": "integer"}
                },
                "required": ["flight_number", "date", "passengers"]
            }
        }
    }
]

remove_flight_tool = [
    {
        "type": "function",
        "function": {
            "name": "remove_flight_from_cart",
            "description": "Remove a specific flight from the user's cart if they change their mind or make a mistake.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": "string", "description": "The flight number to remove."}
                },
                "required": ["flight_number"]
            }
        }
    }
]

db_query_tool = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Query the flight database to look up route information, airport details, "
                "schedules, or booking status. Use this to answer user questions. "
                "This is READ-ONLY — you cannot insert, update, or delete any data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "list_all_routes",
                            "get_route_details",
                            "list_airports",
                            "get_airport_info",
                            "list_bookings",
                        ],
                        "description": (
                            "The specific read-only operation to run. "
                            "list_all_routes: all operated routes. "
                            "get_route_details: one specific route (requires departure + arrival). "
                            "list_airports: all serviced airports. "
                            "get_airport_info: details for one airport (requires airport_code). "
                            "list_bookings: existing booking records."
                        ),
                    },
                    "departure": {
                        "type": "string",
                        "description": "Departure city or IATA code. Required for get_route_details.",
                    },
                    "arrival": {
                        "type": "string",
                        "description": "Arrival city or IATA code. Required for get_route_details.",
                    },
                    "airport_code": {
                        "type": "string",
                        "description": "IATA code or city name. Required for get_airport_info.",
                    },
                },
                "required": ["operation"],
            },
        },
    }
]

context_tool = [
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": (
                "Retrieve live contextual information such as the current date/time, "
                "pre-computed relative dates (today, tomorrow, this weekend, etc.), "
                "or the allowed booking window. Call this BEFORE asking the user to "
                "confirm a date whenever they use relative language like 'today', "
                "'tomorrow', 'next Monday', or 'this weekend'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": [
                            "current_datetime",
                            "relative_dates",
                            "booking_window",
                        ],
                        "description": (
                            "current_datetime: today's date, current time, day of week. "
                            "relative_dates: pre-computed dates for tomorrow, this weekend, next Monday, etc. "
                            "booking_window: earliest and latest allowed departure dates."
                        ),
                    },
                },
                "required": ["info_type"],
            },
        },
    }
]

def render_flight_card(flight_cart: list):
    """Renders the flight summary card. Called from the persistent widget section."""
    with st.container(border=True):
        st.markdown("### 🛒 Your Flight Cart")
        
        total_price = 0
        for i, flight_data in enumerate(flight_cart):
            trip_type = flight_data.get("trip_type", "")
            return_date = flight_data.get("return_date", "")

            if i > 0:
                st.divider()

            st.markdown(
                f"**✈️ {flight_data.get('departure_point', '')} ➔ {flight_data.get('arrival_point', '')}**"
            )

            caption = f"Departure: {flight_data.get('departure_date', '')}"
            if trip_type == "Round-trip" and return_date:
                caption += f" | Return: {return_date}"
            st.caption(caption)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    label="Outbound",
                    value=flight_data.get("departure_time", "08:15"),
                    delta=flight_data.get("transfer_status", "Direct"),
                )
                st.text(flight_data.get("departure_point", ""))
            with col2:
                st.metric(label="Duration", value=flight_data.get("flight_duration", ""), delta_color="off")
            with col3:
                st.metric(
                    label="Arrival",
                    value=flight_data.get("arrival_time", ""),
                    delta=flight_data.get("transfer_status", "Direct"),
                )
                st.text(flight_data.get("arrival_point", ""))

            pax = flight_data.get("passenger_count", 1)
            fn  = flight_data.get("flight_number", "")
            price = flight_data.get("price_tl", 0)
            total_price += price
            st.caption(f"{fn} · {pax} passenger{'s' if pax != 1 else ''} · {price:,} TL")

        st.divider()

        price_col, button_col = st.columns([2, 1])
        with price_col:
            st.subheader(f"Total: {total_price:,} TL")
        with button_col:
            st.button(
                "🛒 Checkout & Finalize",
                use_container_width=True,
                key="confirm_booking_btn",
                on_click=_on_confirm_booking,
            )

def render_final_report(report_data: dict):
    st.divider()
    st.markdown("### 📊 Session Analytics Report")

    smoothness = report_data.get("process_smoothness", "Unknown")
    summary = report_data.get("passenger_summary", "N/A")
    raw_issues = report_data.get("issues_encountered", [])
    evaluation = report_data.get("overall_evaluation", "N/A")

    if isinstance(raw_issues, str):
        try:
            parsed = json.loads(raw_issues)
            issues = parsed if isinstance(parsed, list) else [str(parsed)]
        except (json.JSONDecodeError, ValueError):
            issues = [raw_issues] if raw_issues.strip() else []
    else:
        issues = raw_issues if isinstance(raw_issues, list) else []

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Passenger Summary:**\n{summary}")
    with col2:
        if smoothness == "Smooth":
            st.success(f"**Flow Status:** {smoothness}")
        else:
            st.warning(f"**Flow Status:** {smoothness}")

    st.markdown("#### 🚨 Edge Cases & Issues")
    if issues:
        for issue in issues:
            st.error(f"- {issue}")
    else:
        st.success("- No off-topic attempts, invalid data, or bypassed steps detected.")

    st.markdown("#### 📝 General Evaluation")
    st.markdown(f"> {evaluation}")

def _on_confirm_booking():
    """Runs before the next script rerun when the user clicks Checkout & Finalize."""
    st.session_state.pending_user_message = "I'm completely done adding flights. Please check out and finalize my itinerary."

MAX_HISTORY_MESSAGES = 100
MAX_TOOL_RESULT_CHARS = 800

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

def _call_llm():
    """
    Sends the current message history to the model, then handles the response
    by updating st.session_state. No direct Streamlit rendering happens here.
    Returns True on success, False on failure.
    """
    history = st.session_state.messages
    system_msg = [history[0]]
    recent = history[1:][-MAX_HISTORY_MESSAGES:]
    trimmed = _sanitize_for_gemini(_truncate_tool_results(system_msg + recent))

    if st.session_state.report_data is not None:
        active_tools      = []
        active_tool_choice = "none"
    elif len(st.session_state.messages) <= 2 and st.session_state.messages[-1].get("hidden"):
        active_tools      = []
        active_tool_choice = "none"
    elif st.session_state.flight_data:
        active_tools      = flight_widget_tool + final_report_tool + db_query_tool + context_tool + check_availability_tool + remove_flight_tool
        active_tool_choice = "auto"
    else:
        active_tools      = flight_widget_tool + db_query_tool + context_tool + check_availability_tool
        active_tool_choice = "auto"

    try:
        response = client.chat.completions.create(
            model="gemini-3.5-flash-lite",
            messages=trimmed,
            temperature=0.4,
            tools=active_tools if active_tools else None,
            tool_choice=active_tool_choice if active_tools else "none",
        )
    except Exception as e:
        st.session_state.last_error = str(e)
        return False

    response_message = response.choices[0].message

    if response_message.tool_calls:
        st.session_state.messages.append(response_message.model_dump(exclude_none=True))

        skip_followup = False
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as parse_err:
                st.session_state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Error: Malformed JSON in tool arguments — {parse_err}",
                })
                st.session_state.last_error = (
                    f"`{function_name}` returned malformed JSON: {parse_err}"
                )
                continue

            if function_name == "generate_flight_widget":
                dep = _extract_code(tool_args.get("departure_point", ""))
                arr = _extract_code(tool_args.get("arrival_point", ""))
                passengers = int(tool_args.get("passenger_count", 1) or 1)
                trip_type = tool_args.get("trip_type", "One-way")

                # Validate passengers
                if passengers <= 0 or passengers > 9:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Error: Invalid passenger count. Cannot book more than 9 passengers per transaction."
                    })
                    continue

                # Validate Date format and logic
                dep_date_str = tool_args.get("departure_date", "")
                try:
                    dep_date_parsed = datetime.strptime(dep_date_str, "%Y-%m-%d")
                    if dep_date_parsed.date() < datetime.now().date():
                        st.session_state.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "Error: Departure date cannot be in the past."
                        })
                        continue
                except ValueError:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Error: Invalid departure_date format. Must be YYYY-MM-DD."
                    })
                    continue

                missing_user_fields = [
                    f for f in ["departure_point", "arrival_point", "departure_date"]
                    if not str(tool_args.get(f, "")).strip()
                ]
                if missing_user_fields:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": (
                            f"Error: Cannot render the flight widget yet. "
                            f"Still missing: {', '.join(missing_user_fields)}. "
                            f"Resume the booking sequence."
                        ),
                    })
                    continue

                outbound = find_flight(dep, arr)
                if not outbound:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": (
                            f"Error: No route found from '{dep}' to '{arr}'. "
                            f"{AIRLINE_NAME} does not operate that route. "
                            f"Inform the user and offer available alternatives."
                        ),
                    })
                    continue

                inbound = find_flight(arr, dep) if trip_type == "Round-trip" else None
                if trip_type == "Round-trip" and not inbound:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": (
                            f"Error: No return route found from '{arr}' to '{dep}'. "
                            f"{AIRLINE_NAME} does not operate that return route. Inform the user."
                        )
                    })
                    continue

                total_price = calculate_total_price(outbound, passengers, trip_type, inbound)
                verified = {
                    "departure_point":  dep,
                    "arrival_point":    arr,
                    "trip_type":        trip_type,
                    "departure_date":   tool_args.get("departure_date", ""),
                    "return_date":      tool_args.get("return_date", ""),
                    "passenger_count":  passengers,
                    "departure_time":   outbound["departure_time"],
                    "arrival_time":     outbound["arrival_time"],
                    "flight_duration":  outbound["duration"],
                    "transfer_status":  outbound["transfer_status"],
                    "airline_name":     AIRLINE_NAME,
                    "flight_number":    outbound["flight_number"],
                    "price_tl":         total_price,
                }
                
                # Check for duplicate
                is_duplicate = any(
                    f["flight_number"] == verified["flight_number"] and 
                    f["departure_date"] == verified["departure_date"] 
                    for f in st.session_state.flight_data
                )
                if is_duplicate:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: Flight {verified['flight_number']} on {verified['departure_date']} is already in the cart."
                    })
                    continue

                if not isinstance(st.session_state.flight_data, list):
                    st.session_state.flight_data = []
                st.session_state.flight_data.append(verified)
                
                # Optimization: skip followup for widget rendering, emit directly
                st.session_state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": "Flight card successfully appended to cart UI."
                })
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"I've added flight {outbound['flight_number']} to your cart. Please check the summary above!"
                })
                skip_followup = True

            elif function_name == "remove_flight_from_cart":
                fn_to_remove = tool_args.get("flight_number")
                original_len = len(st.session_state.flight_data)
                st.session_state.flight_data = [f for f in st.session_state.flight_data if f["flight_number"] != fn_to_remove]
                if len(st.session_state.flight_data) < original_len:
                    content = f"Successfully removed {fn_to_remove} from cart."
                else:
                    content = f"Flight {fn_to_remove} not found in cart."
                st.session_state.messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})

            elif function_name == "check_availability":
                fn = tool_args.get("flight_number")
                dt = tool_args.get("date")
                pax = tool_args.get("passengers", 1)
                
                if db_check_capacity:
                    avail = db_check_capacity(fn, dt)
                    status = "Available" if avail >= pax else "Unavailable"
                    result = {"status": status, "remaining_seats": avail}
                else:
                    # Fallback if DB tool wasn't truly injected
                    result = {"status": "Available", "message": "Capacity constraints unverified via DB, assuming available."}

                st.session_state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })

            elif function_name == "generate_final_report":
                if not st.session_state.flight_data:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": (
                            "Error: Cannot generate the final report yet. "
                            "The flight summary widget has not been shown to the user. "
                            "Continue the booking flow and call generate_flight_widget first."
                        ),
                    })
                else:
                    st.session_state.report_data = tool_args
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Session report generated. Interaction complete.",
                        "report_data": tool_args
                    })
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "I've finalized your itinerary and generated a summary report below. Have a great trip!"
                    })
                    skip_followup = True

            elif function_name == "query_database":
                operation = tool_args.get("operation", "")
                try:
                    if operation == "list_all_routes":
                        result = db_list_all_routes()
                    elif operation == "get_route_details":
                        dep_q = tool_args.get("departure", "")
                        arr_q = tool_args.get("arrival", "")
                        if not dep_q or not arr_q:
                            result = {"error": "Both 'departure' and 'arrival' are required."}
                        else:
                            result = db_get_route_details(dep_q, arr_q)
                    elif operation == "list_airports":
                        result = db_list_airports()
                    elif operation == "get_airport_info":
                        code_q = tool_args.get("airport_code", "")
                        if not code_q:
                            result = {"error": "'airport_code' is required."}
                        else:
                            result = db_get_airport_info(code_q)
                    elif operation == "list_bookings":
                        result = db_list_bookings()
                    else:
                        result = {"error": f"Unknown operation '{operation}'."}
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                except Exception as db_err:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error executing '{operation}': {db_err}",
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
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                except Exception as ctx_err:
                    st.session_state.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error fetching '{info_type}': {ctx_err}",
                    })

            else:
                st.session_state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Error: Unknown function '{function_name}'.",
                })

        if not skip_followup:
            history = st.session_state.messages
            followup_trimmed = _sanitize_for_gemini(_truncate_tool_results(
                [history[0]] + history[1:][-MAX_HISTORY_MESSAGES:]
            ))
            try:
                followup = client.chat.completions.create(
                    model="gemini-3.5-flash-lite",
                    messages=followup_trimmed,
                    temperature=0.3,
                    tools=None,
                    tool_choice="none",
                )
                followup_text = followup.choices[0].message.content or ""
                if followup_text:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": followup_text,
                    })
                else:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Processing complete.",
                        "hidden": True
                    })
            except Exception as follow_err:
                st.session_state.last_error = str(follow_err)
                st.session_state.messages.append({
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
            st.session_state.last_error = (
                "The model tried to perform an action but used the wrong format. "
                "Please repeat your last message and it will be handled correctly."
            )
        else:
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})

    return True

FLIGHT_REQUIRED = [
    "departure_point", "arrival_point", "departure_date",
    "departure_time", "arrival_time", "flight_duration", "flight_number",
]

def _is_valid_flight_data(data) -> bool:
    """Returns True only when all required fields are non-empty and price > 0 for all flights in the cart."""
    if not data or not isinstance(data, list):
        return False
    for flight in data:
        all_filled = all(str(flight.get(f, "")).strip() for f in FLIGHT_REQUIRED)
        price_ok = bool(flight.get("price_tl", 0))
        if not (all_filled and price_ok):
            return False
    return True

def _build_transcript() -> str:
    """Human-readable markdown transcript of the conversation."""
    lines = [
        f"# Airline Booking Transcript",
        f"_Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
    ]
    for msg in st.session_state.get("messages", []):
        if msg.get("hidden"):
            continue

        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "system":
            continue

        elif role == "user":
            lines.append(f"**User:** {content}")

        elif role == "assistant":
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    lines.append(f"_[Action: called `{tc['function']['name']}`]_")
            elif content:
                lines.append(f"**Assistant:** {content}")

        elif role == "tool":
            tc_content = content or ""
            label = "✅ Tool result" if not tc_content.startswith("Error") else "⚠️ Tool rejected"
            lines.append(f"> {label}: {tc_content}")

        lines.append("")

    fd_list = st.session_state.get("flight_data")
    if fd_list and _is_valid_flight_data(fd_list):
        lines += [
            "---",
            "## 🛫 Booked Flights",
        ]
        total_price = 0
        for fd in fd_list:
            lines += [
                f"- **Route:** {fd.get('departure_point')} → {fd.get('arrival_point')}",
                f"- **Trip type:** {fd.get('trip_type')}",
                f"- **Departure:** {fd.get('departure_date')} at {fd.get('departure_time')}",
                f"- **Arrival:** {fd.get('arrival_time')} | Duration: {fd.get('flight_duration')}",
                f"- **Flight:** {fd.get('airline_name')} {fd.get('flight_number')} ({fd.get('transfer_status')})",
                f"- **Price:** {fd.get('price_tl')} TL",
            ]
            if fd.get("return_date"):
                lines.append(f"- **Return:** {fd.get('return_date')}")
            total_price += fd.get("price_tl", 0)
        lines.append(f"- **Total Price:** {total_price} TL")

    rd = st.session_state.get("report_data")
    if rd:
        lines += [
            "",
            "---",
            "## 📊 Session Report",
            f"- **Summary:** {rd.get('passenger_summary', 'N/A')}",
            f"- **Flow:** {rd.get('process_smoothness', 'N/A')}",
            f"- **Evaluation:** {rd.get('overall_evaluation', 'N/A')}",
        ]
        issues = rd.get("issues_encountered", [])
        if isinstance(issues, list) and issues:
            lines.append("- **Issues:**")
            for iss in issues:
                lines.append(f"  - {iss}")

    return "\n".join(lines)

def _build_raw_log() -> str:
    """Full JSON dump of session state for debugging."""
    import json as _json
    payload = {
        "messages": st.session_state.get("messages", []),
        "flight_data": st.session_state.get("flight_data"),
        "report_data": st.session_state.get("report_data"),
    }
    return _json.dumps(payload, indent=2, ensure_ascii=False)

st.set_page_config(page_title="Airline Chatbot", page_icon="✈️", layout="centered")
st.title("Airline Ticket Assistant")

with st.sidebar:
    if st.session_state.get("flight_data") and _is_valid_flight_data(st.session_state.flight_data) and not st.session_state.get("report_data"):
        render_flight_card(st.session_state.flight_data)

    st.markdown("### 🛠️ Session Controls")

    if st.button("🔄 Start Over", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.divider()
    st.markdown("### 📥 Export")

    has_convo = any(
        m.get("role") == "user" and not m.get("hidden")
        for m in st.session_state.get("messages", [])
    )

    st.download_button(
        label="📄 Download Transcript",
        data=_build_transcript(),
        file_name="airway_transcript.md",
        mime="text/markdown",
        use_container_width=True,
        disabled=not has_convo,
        help="Human-readable markdown log of the conversation.",
    )

    st.download_button(
        label="🔍 Download Raw Log (JSON)",
        data=_build_raw_log(),
        file_name="airway_debug_log.json",
        mime="application/json",
        use_container_width=True,
        disabled=not has_convo,
        help="Full session state including tool calls and tool results.",
    )

client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=os.getenv("GEMINI_API_KEY"))

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user", 
            "content": "In English, greet and briefly introduce yourself with the airline, and ask the customer their request without exaggeration.", 
            "hidden": True
        }
    ]
    if "flight_data" not in st.session_state:
        st.session_state.flight_data = []
    if "report_data" not in st.session_state:
        st.session_state.report_data = None
    if "last_error" not in st.session_state:
        st.session_state.last_error = None
    if "pending_user_message" not in st.session_state:
        st.session_state.pending_user_message = None

    with st.spinner("Connecting to terminal..."):
        if not _call_llm():
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Welcome to {AIRLINE_NAME}. I'm currently experiencing connection issues. Please try again or click 'Start Over'."
            })
    st.rerun()
if "flight_data" not in st.session_state:
    st.session_state.flight_data = []
if "report_data" not in st.session_state:
    st.session_state.report_data = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "pending_user_message" not in st.session_state:
    st.session_state.pending_user_message = None

for message in st.session_state.messages:
    role = message.get("role")

    if role == "tool" and "report_data" in message:
        with st.chat_message("assistant"):
            render_final_report(message["report_data"])
        continue

    if role in ("system", "tool"):
        continue

    if role == "assistant":
        if message.get("hidden"):
            continue
        if message.get("tool_calls"):
            continue
        content = message.get("content") or ""
        if content:
            with st.chat_message("assistant"):
                st.markdown(content)

    elif role == "user":
        if message.get("hidden"):
            continue
        with st.chat_message("user"):
            st.markdown(message.get("content", ""))

else:
    if st.session_state.flight_data and not _is_valid_flight_data(st.session_state.flight_data):
        st.session_state.flight_data = []

if st.session_state.last_error:
    st.error(f"⚠️ {st.session_state.last_error}")
    st.session_state.last_error = None

trigger = st.session_state.pending_user_message
if trigger:
    st.session_state.pending_user_message = None
    last = st.session_state.messages[-1] if st.session_state.messages else {}
    if last.get("role") == "user":
        st.session_state.messages[-1]["content"] += "\n" + trigger
    else:
        st.session_state.messages.append({"role": "user", "content": trigger})
    with st.spinner("Confirming…"):
        _call_llm()
    st.rerun()

# Disable input entirely if report is generated (session over)
if user_input := st.chat_input("Type your message here...", disabled=(st.session_state.report_data is not None)):
    if user_input.strip():
        last = st.session_state.messages[-1] if st.session_state.messages else {}
        if last.get("role") == "user":
            st.session_state.messages[-1]["content"] += "\n" + user_input
        else:
            st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.spinner("Thinking…"):
            _call_llm()
        st.rerun()