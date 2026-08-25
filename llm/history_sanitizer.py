"""
llm/history_sanitizer.py
------------------------
Pure message-list transforms for Gemini API compliance.

Every function in this module operates on plain ``list[dict]`` message
histories and returns a new list — no API client, no database, no
side-effects.  This makes the module trivially unit-testable with
synthetic message fixtures.

Responsibilities
~~~~~~~~~~~~~~~~
* **truncate_tool_results** — cap oversized tool responses so they don't
  blow up the context window.
* **sanitize_for_gemini** — enforce Gemini's strict turn-sequencing
  rules (merge consecutive same-role messages, drop orphaned
  tool-call assistants, inject a placeholder when the first non-system
  message isn't a user turn).
* **extract_code** — pull an IATA code out of freeform strings like
  ``"Ankara (ESB)"``.
* **flatten_history** — convert an assistant ↔ tool turn sequence into
  the user-role-only format Gemini expects, while preserving which tool
  produced each result.
"""

import re as _re

from .config import MAX_TOOL_RESULT_CHARS


# --------------------------------------------------------------------------- #
# Tool-result truncation
# --------------------------------------------------------------------------- #

def truncate_tool_results(messages: list) -> list:
    """
    Return a copy of *messages* where any tool-role message whose content
    exceeds ``MAX_TOOL_RESULT_CHARS`` is replaced with a short preview plus
    an "[omitted]" suffix.
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


# --------------------------------------------------------------------------- #
# IATA code extraction
# --------------------------------------------------------------------------- #

def extract_code(value: str) -> str:
    """Extract an IATA code or city name from strings like ``'Ankara (ESB)'``.

    If the value contains a three-letter code in parentheses, return it
    upper-cased.  Otherwise return the trimmed input as-is.
    """
    m = _re.search(r'\(([A-Za-z]{3})\)', value)
    if m:
        return m.group(1).upper()
    return value.strip()


# --------------------------------------------------------------------------- #
# Gemini turn-sequence sanitization
# --------------------------------------------------------------------------- #

def sanitize_for_gemini(messages: list) -> list:
    """
    Clean up the message list so it conforms to Gemini's strict
    turn-sequence rules:

    1. Merge consecutive messages with the same role
       (user+user → single user).
    2. If an assistant message has ``tool_calls`` but its corresponding
       tool responses were lost (e.g. due to truncation), drop that
       orphaned assistant message.
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


# --------------------------------------------------------------------------- #
# History flattening (tool turns → user turns)
# --------------------------------------------------------------------------- #

def flatten_history(recent_messages: list) -> list:
    """Convert a standard assistant ↔ tool message sequence into the
    user-role-only format Gemini expects.

    This function was previously inlined inside ``call_llm``'s loop
    (~35 lines at lines 625-665 of the original ``llm_engine.py``).

    The transformation:

    * **Tool responses** (``role: "tool"``) are rewritten as ``role: "user"``
      messages, prefixed with ``[You previously invoked: <tool_name>]`` and
      wrapped in ``<tool_result>`` XML tags so the model knows which call
      produced each result.
    * **Assistant tool-call messages** (``role: "assistant"`` with
      ``tool_calls``) are dropped from the flattened output because the
      ``[You previously invoked: …]`` prefix already provides the same
      context.  Any free-text the model emitted alongside the call is
      preserved as a plain assistant message.
    * All other messages pass through unchanged.

    Parameters
    ----------
    recent_messages : list[dict]
        The message history *after* tool-result truncation
        (``truncate_tool_results``).  The list should **not** include the
        system message — that is prepended by the caller after flattening.

    Returns
    -------
    list[dict]
        A new message list ready for ``sanitize_for_gemini``.
    """
    # Build tool_call_id → function name mapping so we can label each
    # tool result with the name of the function that produced it.
    tool_id_to_name: dict[str, str] = {}
    for msg in recent_messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls", []):
                name = (
                    tc.get("function", {}).get("name")
                    if isinstance(tc, dict)
                    else getattr(tc.function, "name", "tool")
                )
                tid = (
                    tc.get("id")
                    if isinstance(tc, dict)
                    else getattr(tc, "id", "")
                )
                if tid and name:
                    tool_id_to_name[tid] = name

    flattened: list[dict] = []
    for msg in recent_messages:
        if msg.get("role") == "tool":
            # Convert tool responses to user messages.  Prefix each
            # result with the tool name so the model knows which call
            # produced this result.  Context is embedded on the *user*
            # role so there is no assistant-side pattern for the model
            # to mimic when writing its own text reply.
            tid = msg.get("tool_call_id", "")
            name = tool_id_to_name.get(tid, "unknown_tool")
            flattened.append({
                "role": "user",
                "content": (
                    f"[You previously invoked: {name}]\n"
                    f"<tool_result tool_name=\"{name}\">\n"
                    f"{msg.get('content', '')}\n"
                    f"</tool_result>"
                ),
            })
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Drop the assistant tool-call turn from flattened history.
            # The "[You previously invoked: …]" prefix on each tool_result
            # provides the same context without creating an assistant-side
            # stub that the model could reproduce verbatim in its text reply.
            # Keep any free-text the model may have emitted alongside the call.
            inline_text = (msg.get("content") or "").strip()
            if inline_text:
                flattened.append({"role": "assistant", "content": inline_text})
        else:
            flattened.append(dict(msg))

    return flattened
