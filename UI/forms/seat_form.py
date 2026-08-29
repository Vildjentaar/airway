"""
UI/forms/seat_form.py

Renders per-passenger seat-type selection for the booking.

- Reads passenger list from ``st.session_state.passenger_details``.
- Offers a "No Preference (Random)" option at no charge.
- Business-class passengers receive complimentary upgrades on select types.
- On submit → validate → store to ``st.session_state.seat_selections`` →
  set ``pending_user_message`` → ``st.rerun()``.
- A dedicated "Skip" button allows the user to bypass seat selection entirely.
"""

from __future__ import annotations

import streamlit as st

from data.seat_data import get_available_seats, validate_seat_selection


def render_seat_form() -> None:
    """Render the seat selection form and handle submission."""
    st.markdown("### ✈️ Secure Checkout: Seat Selection")

    # --- resolve passenger list and ticket class ----------------------------
    passengers = st.session_state.get("passenger_details", [])
    flight = (
        st.session_state.flight_data[0]
        if st.session_state.get("flight_data")
        else {}
    )
    ticket_class = flight.get("ticket_class", "Economy")

    if not passengers:
        st.warning("No passenger details found. Please complete the previous step.")
        return

    # --- fetch available seat types for this flight/class -------------------
    available_seats = get_available_seats(
        flight_number=flight.get("flight_number", ""),
        ticket_class=ticket_class,
    )

    # Build label → seat-dict lookup and a labels list (with "No Preference")
    no_pref_label = "🎲 No Preference (Random Assignment) — Free"
    seat_labels = [no_pref_label]
    label_to_seat: dict[str, dict] = {}

    for s in available_seats:
        price_tag = "Included" if s["price_tl"] == 0 else f"+{s['price_tl']:.0f} TL"
        label = f"{s['label']} — {price_tag}"
        seat_labels.append(label)
        label_to_seat[label] = s

    # --- render per-passenger seat selectors --------------------------------
    st.caption(
        "Select a seat type for each passenger, or choose *No Preference* "
        "for a free random assignment."
    )

    selections: list[dict] = []

    with st.container():
        for idx, p in enumerate(passengers):
            ptype = p.get("type", "Passenger")
            first = p.get("first_name", "")
            last = p.get("last_name", "")
            display_name = f"{first} {last}".strip() or f"Passenger {idx + 1}"

            st.markdown(f"#### {ptype} {idx + 1} — {display_name}")

            chosen_label = st.selectbox(
                "Seat type",
                seat_labels,
                index=0,
                key=f"seat_sel_{idx}",
                label_visibility="collapsed",
            )

            selections.append({
                "passenger_idx": idx,
                "chosen_label": chosen_label,
            })

        # --- running total --------------------------------------------------
        running_total = 0.0
        for sel in selections:
            seat = label_to_seat.get(sel["chosen_label"])
            if seat:
                running_total += seat["price_tl"]

        st.markdown(f"**Seat total: {running_total:,.0f} TL**")
        st.divider()

        # --- action buttons -------------------------------------------------
        col_submit, col_skip = st.columns(2)
        with col_submit:
            submitted = st.button("✅ Confirm Seats", key="seat_submit", disabled=st.session_state.get("is_thinking", False))
        with col_skip:
            skipped = st.button("⏭️ Skip Seat Selection", key="seat_skip", disabled=st.session_state.get("is_thinking", False))

    # --- handle skip --------------------------------------------------------
    if skipped:
        st.session_state.seat_selections = []
        st.session_state.pending_user_message = (
            "[System Note: User skipped seat selection (random assignment). Now call render_secure_form(form_type='luggage').]"
        )
        st.session_state.report_data = None
        st.rerun()
        return

    if not submitted:
        return

    # --- validate and store -------------------------------------------------
    result = _process_seat_submission(selections, label_to_seat, ticket_class)

    if result["success"]:
        st.session_state.pending_user_message = (
            "[System Note: User successfully submitted the seat_selection"
            f" form. {result.get('detail', '')} Now call render_secure_form(form_type='luggage').]".strip()
        )
        st.session_state.report_data = None
        st.rerun()
    else:
        st.error(result["error"])


def _process_seat_submission(
    selections: list[dict],
    label_to_seat: dict[str, dict],
    ticket_class: str,
) -> dict:
    """Validate seat selections and persist to session state."""
    seat_records: list[dict] = []

    for sel in selections:
        seat = label_to_seat.get(sel["chosen_label"])

        if seat is None:
            # "No Preference" — record as random, price 0
            seat_records.append({
                "passenger_idx": sel["passenger_idx"],
                "seat_id": "random",
                "type": "no_preference",
                "price_tl": 0,
            })
            continue

        # Validate the key against the data layer
        val = validate_seat_selection(seat["key"], ticket_class)
        if not val["valid"]:
            return {
                "success": False,
                "error": f"Passenger {sel['passenger_idx'] + 1}: {val['error']}",
            }

        seat_records.append({
            "passenger_idx": sel["passenger_idx"],
            "seat_id": seat["key"],
            "type": seat["label"],
            "price_tl": seat["price_tl"],
        })

    st.session_state.seat_selections = seat_records
    return {"success": True, "detail": "Seat selections recorded."}
