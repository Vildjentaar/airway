"""
flight_cart.py
---------------
Renders the persistent flight cart summary card and handles the
"Checkout & Finalize" button's session-state side effect.

Pure presentation module: reads from data handed to it by the caller,
writes only to st.session_state.pending_user_message on user action.
No LLM calls, no validation logic, no imports from accounts.py / payment.py.
"""

import streamlit as st


def render_flight_card(flight_cart: list, is_disabled: bool = False):
    """Renders the flight summary card. Called from the persistent widget section."""
    with st.container(border=True):
        st.markdown("### Your Flight Cart")

        total_price = 0
        for i, flight_data in enumerate(flight_cart):
            trip_type = flight_data.get("trip_type", "")
            segments = flight_data.get("segments", [])

            if i > 0:
                st.divider()

            if not segments:
                continue

            first_seg = segments[0]
            last_seg = segments[-1]

            st.markdown(
                f"**{first_seg.get('departure_point', '')} ➔ {last_seg.get('arrival_point', '')}**"
            )

            caption = f"Departure: {first_seg.get('departure_date', '')}"
            if trip_type == "Round-trip" and len(segments) > 1:
                caption += f" | Return: {last_seg.get('departure_date', '')}"
            st.caption(caption)

            for idx, segment in enumerate(segments):
                if idx > 0:
                    st.divider()
                    st.markdown(f"**{segment.get('departure_point', '')} ➔ {segment.get('arrival_point', '')}**")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        label="Departure" if idx == 0 else "Departure (Leg " + str(idx + 1) + ")",
                        value=segment.get("departure_time", "08:15"),
                        delta=segment.get("transfer_status", "Direct"),
                    )
                    st.text(segment.get("departure_point", ""))
                with col2:
                    st.metric(label="Duration", value=segment.get("flight_duration", ""), delta_color="off")
                with col3:
                    st.metric(
                        label="Arrival",
                        value=segment.get("arrival_time", ""),
                        delta=segment.get("transfer_status", "Direct"),
                    )
                    st.text(segment.get("arrival_point", ""))

            pax = flight_data.get("passenger_count", 1)
            fn_list = " & ".join(s.get("flight_number", "") for s in segments)
            price = flight_data.get("price_tl", 0)
            details = flight_data.get("pricing_details")
            total_price += price
            st.caption(f"{fn_list} · {pax} passenger{'s' if pax != 1 else ''} · {price:,} TL")
            if details:
                st.caption(
                    f"↳ Subtotal: {details['subtotal_tl']:,.2f} TL | "
                    f"Tax: {details['tax_tl']:,.2f} TL | "
                    f"Fees: {details['fees_tl']:,.2f} TL"
                )

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


def _on_confirm_booking():
    """Runs before the next script rerun when the user clicks Checkout & Finalize."""
    st.session_state.pending_user_message = (
        "I'm completely done adding flights. Please check out and finalize my itinerary."
    )
