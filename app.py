"""
app.py
------
The Streamlit adapter / controller. Owns `st.session_state` and the main
render loop, but delegates all real work:
    - LLM calls + tool dispatch -> llm_engine.call_llm()
    - Widget rendering + exports -> ui_components.*
    - Tool schemas -> tools_schema.py (consumed indirectly via llm_engine)

When this prototype graduates to a real website, this file (and
ui_components.py) get thrown away; llm_engine.py can be wrapped directly in
a FastAPI/Flask route for the new frontend to call.
"""

import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from system_prompt import SYSTEM_PROMPT
from thall_lines_db import AIRLINE_NAME
from llm_engine import call_llm, is_valid_flight_data
from ui_components import (
    render_flight_card,
    render_final_report,
    render_secure_form_ui,
    build_transcript,
    build_raw_log,
)

load_dotenv()

st.set_page_config(page_title="Airline Chatbot", page_icon="✈️", layout="centered")
st.title("Airline Ticket Assistant")

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.getenv("GEMINI_API_KEY"),
)


def _run_llm_turn():
    """Calls the engine with current session state and writes the result back."""
    result = call_llm(
        client,
        st.session_state.messages,
        st.session_state.flight_data,
        st.session_state.report_data,
    )
    st.session_state.messages = result["messages"]
    st.session_state.flight_data = result["flight_data"]
    st.session_state.report_data = result["report_data"]
    if result["error"]:
        st.session_state.last_error = result["error"]
    return result["success"]


# --------------------------------------------------------------------------
# Session state bootstrap
# --------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "In English, greet and briefly introduce yourself with the airline, and ask the customer their request without exaggeration.",
            "hidden": True,
        },
    ]
    st.session_state.flight_data = []
    st.session_state.report_data = None
    st.session_state.last_error = None
    st.session_state.pending_user_message = None

    with st.spinner("Connecting to terminal..."):
        if not _run_llm_turn():
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

# --------------------------------------------------------------------------
# Sidebar: cart widget + session controls + export
# --------------------------------------------------------------------------

with st.sidebar:
    if (
        st.session_state.get("flight_data")
        and is_valid_flight_data(st.session_state.flight_data)
        and not st.session_state.get("report_data")
    ):
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
        data=build_transcript(
            st.session_state.get("messages", []),
            st.session_state.get("flight_data"),
            st.session_state.get("report_data"),
            is_valid_flight_data,
        ),
        file_name="airway_transcript.md",
        mime="text/markdown",
        use_container_width=True,
        disabled=not has_convo,
        help="Human-readable markdown log of the conversation.",
    )

    st.download_button(
        label="🔍 Download Raw Log (JSON)",
        data=build_raw_log(
            st.session_state.get("messages", []),
            st.session_state.get("flight_data"),
            st.session_state.get("report_data"),
        ),
        file_name="airway_debug_log.json",
        mime="application/json",
        use_container_width=True,
        disabled=not has_convo,
        help="Full session state including tool calls and tool results.",
    )


# --------------------------------------------------------------------------
# Main chat history render
# --------------------------------------------------------------------------

for i, message in enumerate(st.session_state.messages):
    role = message.get("role")
    is_last = (i == len(st.session_state.messages) - 1)

    if role == "tool" and "report_data" in message:
        with st.chat_message("assistant"):
            if message["report_data"] and message["report_data"].get("render_form"):
                if is_last:
                    render_secure_form_ui(message["report_data"]["render_form"])
                else:
                    st.markdown(f"*(Secure {message['report_data']['render_form']} form submitted)*")
            else:
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

if st.session_state.flight_data and not is_valid_flight_data(st.session_state.flight_data):
    st.session_state.flight_data = []

if st.session_state.last_error:
    st.error(f"⚠️ {st.session_state.last_error}")
    st.session_state.last_error = None

# --------------------------------------------------------------------------
# Input handling
# --------------------------------------------------------------------------

trigger = st.session_state.pending_user_message
if trigger:
    st.session_state.pending_user_message = None
    last = st.session_state.messages[-1] if st.session_state.messages else {}
    if last.get("role") == "user":
        st.session_state.messages[-1]["content"] += "\n" + trigger
    else:
        st.session_state.messages.append({"role": "user", "content": trigger})
    with st.spinner("Confirming…"):
        _run_llm_turn()
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
            _run_llm_turn()
        st.rerun()
