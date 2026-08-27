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

from system_prompt import get_system_prompt
from thall_lines_db import AIRLINE_NAME
from llm import call_llm, is_valid_flight_data
from UI import (
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
    # Resolve the authenticated user's email address server-side.
    # This is the ONLY place the recipient address is set for the email tool.
    # It is never read from LLM output to prevent hallucinations or injection.
    user_profile = st.session_state.get("user_profile") or {}
    user_email = user_profile.get("email") or st.session_state.get("guest_email")

    result = call_llm(
        client,
        st.session_state.messages,
        st.session_state.flight_data,
        st.session_state.report_data,
        ancillary_data={
            "seat_selections": st.session_state.get("seat_selections", []),
            "luggage_selections": st.session_state.get("luggage_selections", []),
            "extras_selections": st.session_state.get("extras_selections", []),
            "passenger_details": st.session_state.get("passenger_details", []),
        },
        user_email=user_email,
        email_sent=st.session_state.get("email_sent", False),
    )
    st.session_state.messages = result["messages"]
    st.session_state.flight_data = result["flight_data"]
    st.session_state.report_data = result["report_data"]
    st.session_state.email_sent = result.get("email_sent", st.session_state.get("email_sent", False))
    if result["error"]:
        st.session_state.last_error = result["error"]
    return result["success"]


# --------------------------------------------------------------------------
# Session state bootstrap
# --------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": get_system_prompt()},
        {
            "role": "user",
            "content": "Greet and briefly introduce yourself with the airline, and ask the customer their request without exaggeration.",
            "hidden": True,
        },
    ]
    st.session_state.flight_data = []
    st.session_state.report_data = None
    st.session_state.last_error = None
    st.session_state.pending_user_message = None
    st.session_state.needs_init = True

if "flight_data" not in st.session_state:
    st.session_state.flight_data = []
if "report_data" not in st.session_state:
    st.session_state.report_data = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "pending_user_message" not in st.session_state:
    st.session_state.pending_user_message = None
if "email_sent" not in st.session_state:
    st.session_state.email_sent = False

# --------------------------------------------------------------------------
# Sidebar: cart widget + session controls + export
# --------------------------------------------------------------------------

with st.sidebar:
    if (
        st.session_state.get("flight_data")
        and is_valid_flight_data(st.session_state.flight_data)
    ):
        is_checkout_disabled = bool(st.session_state.get("report_data")) or st.session_state.get("is_thinking", False)
        render_flight_card(st.session_state.flight_data, is_checkout_disabled)

    st.markdown("### 🛠️ Session Controls")

    has_convo = any(
        m.get("role") == "user" and not m.get("hidden")
        for m in st.session_state.get("messages", [])
    )

    is_fresh = (
        not has_convo
        and not st.session_state.get("flight_data")
        and not st.session_state.get("report_data")
        and st.session_state.get("last_error") is None
    )
    is_busy = st.session_state.get("needs_init", False) or st.session_state.get("is_thinking", False)
    if st.button("Start Over", use_container_width=True, disabled=(is_fresh or is_busy)):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.divider()
    st.markdown("### 📥 Export")

    # has_convo definition moved up

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

    st.divider()
    st.markdown("### 🐛 Debugging")
    st.image("diagrams/CONVERSATIONAL AI LOGIC.png", caption="Conversational AI Logic")


# --------------------------------------------------------------------------
# Main chat history render
# --------------------------------------------------------------------------

for i, message in enumerate(st.session_state.messages):
    role = message.get("role")
    is_last = (i == len(st.session_state.messages) - 1)

    if role == "tool" and "report_data" in message:
        if message["report_data"] and message["report_data"].get("render_form"):
            if is_last:
                with st.chat_message("assistant"):
                    render_secure_form_ui(message["report_data"]["render_form"])
        else:
            with st.chat_message("assistant"):
                render_final_report(message["report_data"])
        continue

    if role in ("system", "tool"):
        continue

    if role == "assistant":
        if message.get("hidden"):
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
if trigger and not st.session_state.get("needs_init", False):
    st.session_state.pending_user_message = None
    if trigger.startswith("[System Note:"):
        st.session_state.messages.append({"role": "user", "content": trigger, "hidden": True})
    else:
        st.session_state.messages.append({"role": "user", "content": trigger})
    st.session_state.is_thinking = True
    st.rerun()

# Disable input entirely if report is generated (session over) or initializing/thinking
is_chat_disabled = (st.session_state.report_data is not None) or st.session_state.get("needs_init", False) or st.session_state.get("is_thinking", False)
if user_input := st.chat_input("Type your message here...", disabled=is_chat_disabled):
    if user_input.strip():
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.is_thinking = True
        st.rerun()

if not is_chat_disabled:
    st.html(
        """
        <script>
        setTimeout(function() {
            var inputs = window.parent.document.querySelectorAll('textarea[data-testid="stChatInputTextArea"]');
            if (inputs.length > 0) {
                inputs[0].focus();
            }
        }, 50);
        </script>
        """
    )

if st.session_state.get("is_thinking"):
    with st.spinner("Thinking…"):
        _run_llm_turn()
    st.session_state.is_thinking = False
    st.rerun()

if st.session_state.get("needs_init"):
    with st.spinner("Connecting to terminal..."):
        if not _run_llm_turn():
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Welcome to {AIRLINE_NAME}. I'm currently experiencing connection issues. Please try again or click 'Start Over'."
            })
    st.session_state.needs_init = False
    st.rerun()
