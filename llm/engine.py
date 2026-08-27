import json
from typing import Optional

from .config import MODEL_NAME, THINKING_BUDGET, MAX_HISTORY_MESSAGES, CIRCUIT_BREAK_TURN, MAX_TURNS
from .history_sanitizer import truncate_tool_results, sanitize_for_gemini
from .tool_policy import select_active_tools
from .tool_dispatch import dispatch_tool_call


def _prepare_for_api(messages: list) -> list:
    """Replace any message dict that carries ``_raw_response_message`` with
    the raw SDK object itself.

    Gemini thinking models attach a ``thought_signature`` to every functionCall
    part.  That field is encoded inside the raw SDK object and is NOT reproduced
    by ``model_dump()`` / any dict serialisation.  By passing the original SDK
    object back to ``client.chat.completions.create`` (which the OpenAI-compat
    layer accepts) the signature survives the round-trip and the API stops
    returning the 400 'Function call is missing a thought_signature' error.
    """
    out = []
    for msg in messages:
        raw = msg.get("_raw_response_message") if isinstance(msg, dict) else None
        if raw is not None:
            out.append(raw)
        else:
            out.append(msg)
    return out


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
        flattened_history = sanitize_for_gemini(system_msg + trimmed_recent)

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
            # _prepare_for_api replaces any dict that wraps a raw SDK message
            # object (stored under '_raw_response_message') with the object
            # itself, so thought_signatures are preserved on the wire.
            api_messages = _prepare_for_api(flattened_history)

            # Only send thinking_config when a budget is actually set.
            # Models that don't support thinking (e.g. gemini-3.5-flash-lite)
            # return 400 INVALID_ARGUMENT if thinking_config is present at all,
            # even when the budget is 0.
            extra_body = (
                {"thinking_config": {"thinking_budget": THINKING_BUDGET}}
                if THINKING_BUDGET != 0
                else {}
            )

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=api_messages,
                temperature=0.3,
                tools=active_tools if active_tools else None,
                tool_choice=active_tool_choice if active_tools else "none",
                extra_body=extra_body or None,
            )
        except Exception as e:
            last_error = str(e)
            break

        response_message = response.choices[0].message

        if response_message.tool_calls:
            # IMPORTANT: Do NOT use model_dump() here — Gemini thinking models
            # attach a `thought_signature` to each functionCall part.  That
            # field lives in the raw SDK object and is silently dropped by
            # model_dump()'s OpenAI-compat mapping.  If it is missing when the
            # history is replayed the API returns:
            #   400 – "Function call is missing a thought_signature"
            #
            # Solution: store the raw SDK message object directly.  The Gemini
            # Python SDK accepts its own Content/GenerateContentResponse objects
            # back in the `messages` list, so the signature is preserved
            # end-to-end.  We keep a parallel `_raw` key so the sanitizer and
            # debug logger can introspect it without re-serialising.
            msg_dict = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in response_message.tool_calls
                ],
                "content": response_message.content or "",
                # Preserve the raw SDK object so thought_signature survives
                # the round-trip back to the API.
                "_raw_response_message": response_message,
            }
            messages.append(msg_dict)

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
