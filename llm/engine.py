import json
from typing import Optional

from .config import MODEL_NAME, MAX_HISTORY_MESSAGES, CIRCUIT_BREAK_TURN, MAX_TURNS
from .history_sanitizer import truncate_tool_results, sanitize_for_gemini, flatten_history
from .tool_policy import select_active_tools
from .tool_dispatch import dispatch_tool_call


def call_llm(
    client,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
    email_sent: bool = False,
):
    """
    Sends the current message history to the model, handles any tool calls
    it requests, and returns the updated state.
    """
    messages = [dict(m) for m in messages]
    flight_data = [dict(f) for f in flight_data] if flight_data else []
    last_error = None

    for turn in range(MAX_TURNS):
        active_tools, active_tool_choice = select_active_tools(
            messages, flight_data, report_data, email_sent
        )

        system_msg = [messages[0]]
        recent = messages[1:][-MAX_HISTORY_MESSAGES:]
        
        trimmed_recent = truncate_tool_results(recent)
        flattened_messages = flatten_history(trimmed_recent)
        flattened_history = sanitize_for_gemini(system_msg + flattened_messages)

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

                report_data, call_skip, call_email_sent = dispatch_tool_call(
                    tool_call, function_name, tool_args, messages, flight_data, report_data,
                    ancillary_data=ancillary_data,
                    user_email=user_email,
                )
                skip_followup = skip_followup or call_skip
                email_sent = email_sent or call_email_sent

            if skip_followup:
                break
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
                messages.append({
                    "role": "assistant",
                    "content": "I'm sorry, I ran into a formatting issue. Could you please repeat your last request?",
                })
            else:
                last_error = None
                if not stripped:
                    bot_reply = "I'm sorry, There was a connection glitch and I couldn't process that. Could you please repeat?"
                messages.append({"role": "assistant", "content": bot_reply})
            break
    else:
        messages.append({
            "role": "assistant", 
            "content": "I apologize, but I'm having trouble processing that request right now. Could you please rephrase it?"
        })
        last_error = "LLM exhausted max tool turns."

    return {
        "messages": messages,
        "flight_data": flight_data,
        "report_data": report_data,
        "email_sent": email_sent,
        "success": last_error is None,
        "error": last_error,
    }
