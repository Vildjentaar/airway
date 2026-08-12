"""
ui_components.py
-----------------
Streamlit component rendering and presentation logic.

Nothing in here talks to the LLM. Functions either render widgets directly
to the page, or build export strings (markdown transcript / raw JSON log)
from session data that is handed to them. This keeps the frontend isolated
from the chatbot "brain" — restyle the cart or tweak the transcript format
without touching engine code.

One deliberate exception: the secure checkout forms (auth / passenger
details / payment) validate themselves on submit by calling
`default_auth_provider` / `default_payment_gateway` / `validate_tckn`
directly, rather than routing sensitive field values through the LLM and
chat history (see workflow_extension_plan.md, Phase 2.1 — this is the
"Hybrid" approach). That's still just "render a secure form and react to
its result" — one cohesive job — not "implement auth or payment logic,"
which stays behind the AuthProvider / PaymentGateway interfaces in
accounts.py / payment.py. Swapping either mock for a real implementation
later requires no changes in this file.
"""

import json
from datetime import datetime

import streamlit as st

from accounts import default_auth_provider, validate_tckn
from payment import default_payment_gateway


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
            fn = flight_data.get("flight_number", "")
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


def build_transcript(messages: list, flight_data: list, report_data: dict, is_valid_flight_data) -> str:
    """
    Human-readable markdown transcript of the conversation.

    `is_valid_flight_data` is injected (rather than imported) so this module
    has no dependency on llm_engine — it just needs a predicate function.
    """
    lines = [
        "# Airline Booking Transcript",
        f"_Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
    ]
    for msg in messages or []:
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

    if flight_data and is_valid_flight_data(flight_data):
        lines += [
            "---",
            "## 🛫 Booked Flights",
        ]
        total_price = 0
        for fd in flight_data:
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

    if report_data and not report_data.get("render_form"):
        lines += [
            "",
            "---",
            "## 📊 Session Report",
            f"- **Summary:** {report_data.get('passenger_summary', 'N/A')}",
            f"- **Flow:** {report_data.get('process_smoothness', 'N/A')}",
            f"- **Evaluation:** {report_data.get('overall_evaluation', 'N/A')}",
        ]
        issues = report_data.get("issues_encountered", [])
        if isinstance(issues, list) and issues:
            lines.append("- **Issues:**")
            for iss in issues:
                lines.append(f"  - {iss}")

    return "\n".join(lines)


def build_raw_log(messages: list, flight_data: list, report_data: dict) -> str:
    """Full JSON dump of session state for debugging."""
    payload = {
        "messages": messages,
        "flight_data": flight_data,
        "report_data": report_data,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_secure_form_ui(form_type: str):
    """
    Renders the appropriate secure checkout form and, on submit, validates
    it against the relevant service — rather than unconditionally telling
    the LLM the submission succeeded regardless of what was typed.
    """
    st.markdown(f"### 🔒 Secure Checkout: {form_type.replace('_', ' ').title()}")

    mode = email = password = None
    first_name = last_name = nationality = tckn = None
    cardholder_name = card_number = expiry = cvc = None

    with st.form(key=f"form_{form_type}"):
        if form_type == "auth":
            mode = st.radio("Checkout as:", ["Guest", "Login", "Register"])
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")

        elif form_type == "passenger_details":
            first_name = st.text_input("First Name")
            last_name = st.text_input("Last Name")
            st.date_input("Date of Birth", min_value=datetime(1900, 1, 1), max_value=datetime.today())
            st.radio("Gender", ["Male", "Female", "Other"])
            nationality = st.text_input("Nationality", placeholder="TR")
            tckn = st.text_input("TCKN (if Turkish)", max_chars=11)

        elif form_type == "payment":
            cardholder_name = st.text_input("Cardholder Name")
            card_number = st.text_input("Card Number", max_chars=19, placeholder="0000 0000 0000 0000")
            col1, col2 = st.columns(2)
            with col1:
                expiry = st.text_input("Expiry Date", placeholder="MM/YY")
            with col2:
                cvc = st.text_input("CVC", type="password", max_chars=4)

        submitted = st.form_submit_button("Submit & Continue")

    if not submitted:
        return

    if form_type == "auth":
        result = _process_auth_submission(mode, email, password)
    elif form_type == "passenger_details":
        result = _process_passenger_submission(first_name, last_name, nationality, tckn)
    elif form_type == "payment":
        result = _process_payment_submission(cardholder_name, card_number, expiry, cvc)
    else:
        result = {"success": True, "detail": ""}

    if result["success"]:
        st.session_state.pending_user_message = (
            f"[System Note: User successfully submitted the {form_type} form. {result.get('detail', '')}]".strip()
        )
        st.rerun()
    else:
        st.error(result["error"])


def _process_auth_submission(mode: str, email: str, password: str) -> dict:
    """Calls the AuthProvider abstraction — never talks to USERS directly."""
    if mode == "Guest":
        return {"success": True, "detail": "Continuing as guest."}

    if mode == "Login":
        result = default_auth_provider.authenticate(email or "", password or "")
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {"success": True, "detail": f"Logged in as {result['profile'].get('name', email)}."}
        return {"success": False, "error": result["error"]}

    if mode == "Register":
        result = default_auth_provider.register({"email": email, "password": password})
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {"success": True, "detail": "Account created."}
        return {"success": False, "error": result["error"]}

    return {"success": False, "error": "Please select Guest, Login, or Register."}


def _process_passenger_submission(first_name: str, last_name: str, nationality: str, tckn: str) -> dict:
    """Basic required-field check, plus a real TCKN checksum validation for
    Turkish nationals — the same validate_tckn used elsewhere in the app."""
    if not (first_name or "").strip() or not (last_name or "").strip():
        return {"success": False, "error": "First and last name are required."}

    if (nationality or "").strip().upper() == "TR":
        tckn_result = validate_tckn(tckn or "")
        if not tckn_result["valid"]:
            return {"success": False, "error": tckn_result["error"]}

    return {"success": True, "detail": "Passenger details recorded."}


def _process_payment_submission(cardholder_name: str, card_number: str, expiry: str, cvc: str) -> dict:
    """Calls the PaymentGateway abstraction — never validates card shape
    itself. Swapping default_payment_gateway for a real processor later
    requires no change here."""
    result = default_payment_gateway.charge(card_number or "", expiry or "", cvc or "", cardholder_name or "")
    if result["success"]:
        return {"success": True, "detail": f"Payment approved ({result['transaction_id']})."}
    return {"success": False, "error": result["error"]}
