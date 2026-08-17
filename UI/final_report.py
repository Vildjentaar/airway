"""
final_report.py
----------------
Renders the final e-ticket summary and the session analytics report
shown once a booking has been finalized.

Pure presentation module: reads from data handed to it by the caller
plus st.session_state (for passenger/payment details), writes nothing.
No LLM calls, no validation logic.
"""

import json

import streamlit as st


def render_final_report(report_data: dict):
    booked_flights = report_data.get("booked_flights", [])
    if booked_flights:
        st.markdown("### Final E-Ticket Details")
        for flight in booked_flights:
            with st.container(border=True):
                st.markdown(f"** Flight {flight.get('flight_number', '')}**")
                col1, col2 = st.columns(2)
                with col1:
                    st.text(f"Depart: {flight.get('departure_point', '')} at {flight.get('departure_time', '')}")
                    st.text(f"Date: {flight.get('departure_date', '')}")
                with col2:
                    st.text(f"Arrive: {flight.get('arrival_point', '')} at {flight.get('arrival_time', '')}")
                    st.text(f"Class: {flight.get('ticket_class', 'Economy')}")

                if flight.get("trip_type") == "Round-trip" and flight.get("return_flight_number"):
                    st.divider()
                    st.markdown(f"** Return Flight {flight.get('return_flight_number', '')}**")
                    r_col1, r_col2 = st.columns(2)
                    with r_col1:
                        st.text(f"Depart: {flight.get('arrival_point', '')} at {flight.get('return_departure_time', '')}")
                        st.text(f"Date: {flight.get('return_date', '')}")
                    with r_col2:
                        st.text(f"Arrive: {flight.get('departure_point', '')} at {flight.get('return_arrival_time', '')}")
                        st.text(f"Class: {flight.get('ticket_class', 'Economy')}")

                pax_data = st.session_state.get("passenger_details", [])
                if isinstance(pax_data, dict):
                    pax_data = [pax_data]
                pay = st.session_state.get("payment_details", {})

                if pax_data:
                    st.divider()
                    st.caption("Passenger Information")

                    for p in pax_data:
                        fn = p.get("first_name", "")
                        ln = p.get("last_name", "")
                        censored_name = f"{fn[:1]}*** {ln[:1]}***" if fn and ln else "N/A"

                        tckn = p.get("tckn", "")
                        censored_tckn = f"*******{tckn[-4:]}" if len(tckn) == 11 else "N/A"
                        ptype = p.get("type", "Adult")

                        st.text(f"[{ptype}] Name: {censored_name} | ID / TCKN: {censored_tckn}")

                    card_last4 = pay.get("card_last4", "****")
                    st.text(f"Payment: **** **** **** {card_last4}")

        if report_data.get("seat_selections"):
            st.markdown("#### 💺 Seat Selections")
            for s in report_data["seat_selections"]:
                st.markdown(f"- Passenger {s['passenger_idx']+1}: Seat **{s['seat_id']}** ({s['type']}) — {s['price_tl']} TL")

        if report_data.get("luggage_selections"):
            st.markdown("#### 🧳 Luggage")
            for l in report_data["luggage_selections"]:
                st.markdown(f"- Passenger {l['passenger_idx']+1}: {l['tier']} — {l['price_tl']} TL")

        if report_data.get("extras_selections"):
            st.markdown("#### ✨ Extra Services")
            for e in report_data["extras_selections"]:
                st.markdown(f"- {e['service']} — {e['price_tl']} TL")

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
