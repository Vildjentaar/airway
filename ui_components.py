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
import re
from datetime import datetime

import streamlit as st

from accounts import default_auth_provider, validate_tckn
from payment import default_payment_gateway
from ui_constants import AUTH_MODES, GENDERS, NATIONALITIES


def render_flight_card(flight_cart: list, is_disabled: bool = False):
    """Renders the flight summary card. Called from the persistent widget section."""
    with st.container(border=True):
        st.markdown("### Your Flight Cart")

        total_price = 0
        for i, flight_data in enumerate(flight_cart):
            trip_type = flight_data.get("trip_type", "")
            return_date = flight_data.get("return_date", "")

            if i > 0:
                st.divider()

            st.markdown(
                f"**{flight_data.get('departure_point', '')} ➔ {flight_data.get('arrival_point', '')}**"
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
            details = flight_data.get("pricing_details")
            total_price += price
            st.caption(f"{fn} · {pax} passenger{'s' if pax != 1 else ''} · {price:,} TL")
            if details:
                st.caption(f"↳ Subtotal: {details['subtotal_tl']:,.2f} TL | Tax: {details['tax_tl']:,.2f} TL | Fees: {details['fees_tl']:,.2f} TL")

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
                disabled=is_disabled,
            )


def render_final_report(report_data: dict):
    booked_flights = report_data.get("booked_flights", [])
    if booked_flights:
        st.markdown("### 🎟️ Final E-Ticket Details")
        for flight in booked_flights:
            with st.container(border=True):
                st.markdown(f"**✈️ Flight {flight.get('flight_number', '')}**")
                col1, col2 = st.columns(2)
                with col1:
                    st.text(f"Depart: {flight.get('departure_point', '')} at {flight.get('departure_time', '')}")
                    st.text(f"Date: {flight.get('departure_date', '')}")
                with col2:
                    st.text(f"Arrive: {flight.get('arrival_point', '')} at {flight.get('arrival_time', '')}")
                    st.text(f"Class: {flight.get('ticket_class', 'Economy')}")
                
                pax = st.session_state.get("passenger_details", {})
                pay = st.session_state.get("payment_details", {})
                
                if pax:
                    st.divider()
                    st.caption("Passenger Information (Protected)")
                    
                    fn = pax.get("first_name", "")
                    ln = pax.get("last_name", "")
                    censored_name = f"{fn[:1]}*** {ln[:1]}***" if fn and ln else "N/A"
                    
                    tckn = pax.get("tckn", "")
                    censored_tckn = f"*******{tckn[-4:]}" if len(tckn) == 11 else "N/A"
                    
                    card_last4 = pay.get("card_last4", "****")
                    
                    st.text(f"Name: {censored_name}")
                    st.text(f"ID / TCKN: {censored_tckn}")
                    st.text(f"Payment: **** **** **** {card_last4}")

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
        f"_Exported: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}_",
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
                continue
            elif content:
                lines.append(f"**Assistant:** {content}")

        elif role == "tool":
            continue

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
    st.markdown(f"### Secure Checkout: {form_type.replace('_', ' ').title()}")

    mode = email = password = None
    first_name = last_name = nationality = tckn = None
    cardholder_name = card_number = exp_mm = exp_yy = cvc = None
    submitted = False

    if form_type == "passenger_details":
        profile = st.session_state.get("user_profile", {})
        default_fn = profile.get("name") or ""
        default_ln = profile.get("surname") or ""
        
        default_dob = datetime.today()
        if profile.get("birthdate"):
            try:
                if isinstance(profile["birthdate"], str):
                    default_dob = datetime.strptime(profile["birthdate"], "%Y-%m-%d").date()
                else:
                    default_dob = profile["birthdate"]
            except Exception:
                pass
                
        sex = profile.get("sex")
        default_gender_idx = 0
        if sex == "M": default_gender_idx = 0
        elif sex == "F": default_gender_idx = 1
        elif sex == "O": default_gender_idx = 2
        
        nat = profile.get("nationality")
        default_nat_idx = NATIONALITIES.index(nat) if nat in NATIONALITIES else 0
        
        default_tckn = profile.get("tckn") or ""

        with st.container():
            first_name = st.text_input("First Name", max_chars=32, value=default_fn)
            last_name = st.text_input("Last Name", max_chars=32, value=default_ln)
            st.date_input("Date of Birth", value=default_dob, min_value=datetime(1926, 1, 1), max_value=datetime.today())
            st.radio("Gender", GENDERS, index=default_gender_idx)
            nationality = st.selectbox("Nationality", NATIONALITIES, key="nationality_select", index=default_nat_idx)
            if nationality == "TR":
                tckn = st.text_input("TCKN", max_chars=11, value=default_tckn)
            submitted = st.button("Submit & Continue", key="passenger_submit")
    else:
        if form_type == "auth":
            mode = st.radio("Checkout as:", AUTH_MODES, key="auth_mode")

        with st.form(key=f"form_{form_type}"):
            if form_type == "auth":
                email = st.text_input("Email", placeholder="you@example.com")
                if mode in ("Login", "Register"):
                    password = st.text_input("Password", type="password")
                if mode == "Register":
                    first_name = st.text_input("First Name", max_chars=32)
                    last_name = st.text_input("Last Name", max_chars=32)

            elif form_type == "payment":
                cardholder_name = st.text_input("Cardholder Name")
                card_number = st.text_input("Card Number", max_chars=16, placeholder="0000 0000 0000 0000")
                col1, col2, col3 = st.columns([1, 1, 2])
                with col1:
                    exp_mm = st.text_input("Month", placeholder="MM", max_chars=2)
                with col2:
                    exp_yy = st.text_input("Year", placeholder="YY", max_chars=2)
                with col3:
                    cvc = st.text_input("CVC", type="password", max_chars=3)

            submitted = st.form_submit_button("Submit & Continue")

    if not submitted:
        return

    if form_type == "auth":
        name = f"{first_name or ''} {last_name or ''}".strip() if mode == "Register" else None
        result = _process_auth_submission(mode, email, password, name)
    elif form_type == "passenger_details":
        result = _process_passenger_submission(first_name, last_name, nationality, tckn)
    elif form_type == "payment":
        expiry = f"{exp_mm}/{exp_yy}" if exp_mm and exp_yy else ""
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


def _process_auth_submission(mode: str, email: str, password: str, name: str = None) -> dict:
    """Calls the AuthProvider abstraction — never talks to USERS directly."""
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return {"success": False, "error": "Please enter a valid email address."}

    if mode == "Guest":
        return {"success": True, "detail": "Continuing as guest."}

    if mode == "Login":
        result = default_auth_provider.authenticate(email or "", password or "")
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {"success": True, "detail": f"Logged in as {result['profile'].get('name', email)}."}
        return {"success": False, "error": result["error"]}

    if mode == "Register":
        if name:
            if len(name.replace(" ", "")) < 2:
                return {"success": False, "error": "Name must be at least 2 characters."}
            if not re.match(r"^[a-zA-ZçÇğĞıIİiöÖşŞüÜ\s\-']+$", name):
                return {"success": False, "error": "Name can only contain letters, spaces, hyphens, and apostrophes."}
            
        result = default_auth_provider.register({"email": email, "password": password, "name": name})
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {"success": True, "detail": "Account created."}
        return {"success": False, "error": result["error"]}

    return {"success": False, "error": "Please select Guest, Login, or Register."}


def _process_passenger_submission(first_name: str, last_name: str, nationality: str, tckn: str) -> dict:
    """Basic required-field check, plus a real TCKN checksum validation for
    Turkish nationals — the same validate_tckn used elsewhere in the app."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn or not ln:
        return {"success": False, "error": "First and last name are required."}
    if len(fn) < 2 or len(ln) < 2:
        return {"success": False, "error": "First and last name must be at least 2 characters each."}
        
    name_regex = r"^[a-zA-ZçÇğĞıIİiöÖşŞüÜ\s\-']+$"
    if not re.match(name_regex, fn):
        return {"success": False, "error": "First name can only contain letters."}
    if not re.match(name_regex, ln):
        return {"success": False, "error": "Last name can only contain letters."}

    if (nationality or "").strip().upper() == "TR":
        tckn_result = validate_tckn(tckn or "")
        if not tckn_result["valid"]:
            return {"success": False, "error": tckn_result["error"]}

    st.session_state.passenger_details = {
        "first_name": fn,
        "last_name": ln,
        "tckn": tckn or ""
    }

    return {"success": True, "detail": "Passenger details recorded."}


def _process_payment_submission(cardholder_name: str, card_number: str, expiry: str, cvc: str) -> dict:
    """Calls the PaymentGateway abstraction — never validates card shape
    itself. Swapping default_payment_gateway for a real processor later
    requires no change here."""
    
    if not re.match(r"^[a-zA-ZçÇğĞıIİiöÖşŞüÜ\s\-']+$", cardholder_name or ""):
        return {"success": False, "error": "Cardholder name can only contain letters."}
    if not re.match(r"^[\d\s]+$", card_number or ""):
        return {"success": False, "error": "Card number can only contain numbers."}
    if not re.match(r"^\d{3,4}$", cvc or ""):
        return {"success": False, "error": "CVC must be 3 or 4 digits."}
        
    result = default_payment_gateway.charge(card_number or "", expiry or "", cvc or "", cardholder_name or "")
    if result["success"]:
        st.session_state.payment_details = {
            "card_last4": (card_number or "")[-4:]
        }
        return {"success": True, "detail": f"Payment approved ({result['transaction_id']})."}
    return {"success": False, "error": result["error"]}
