"""
UI/forms/luggage_form.py

Renders per-passenger luggage tier selection for the booking.

- Reads passenger list from ``st.session_state.passenger_details``.
- Cabin bag is always included (pre-selected, no charge).
- Business-class passengers see certain tiers marked as "Included".
- Supports multiple luggage items per passenger via "Add Another Bag".
- On submit → validate → store to ``st.session_state.luggage_selections`` →
  set ``pending_user_message`` → ``st.rerun()``.
"""

from __future__ import annotations

import streamlit as st

from data.luggage_data import get_luggage_options, validate_luggage_selection


# Maximum additional bags a single passenger can add (beyond default cabin)
_MAX_EXTRA_BAGS = 3


def render_luggage_form() -> None:
    """Render the luggage selection form and handle submission."""
    st.markdown("### 🧳 Secure Checkout: Luggage Selection")

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

    # --- fetch luggage tiers for this ticket class --------------------------
    tiers = get_luggage_options(ticket_class)

    # Build label → tier-dict lookup
    tier_labels: list[str] = []
    label_to_tier: dict[str, dict] = {}

    for t in tiers:
        if t.get("included"):
            price_tag = "Included"
        elif t["price_tl"] == 0:
            price_tag = "Free"
        else:
            price_tag = f"+{t['price_tl']:.0f} TL"

        label = f"{t['label']} — {price_tag}"
        tier_labels.append(label)
        label_to_tier[label] = t

    no_add_label = "— No additional bag —"

    st.caption(
        "Every passenger receives a complimentary cabin bag. "
        "Select additional checked luggage below."
    )

    # --- per-passenger luggage selection ------------------------------------
    all_selections: list[dict] = []

    with st.container():
        for idx, p in enumerate(passengers):
            ptype = p.get("type", "Passenger")
            first = p.get("first_name", "")
            last = p.get("last_name", "")
            display_name = f"{first} {last}".strip() or f"Passenger {idx + 1}"

            st.markdown(f"#### {ptype} {idx + 1} — {display_name}")

            # Primary luggage tier
            primary_label = st.selectbox(
                "Luggage tier",
                tier_labels,
                index=0,
                key=f"luggage_primary_{idx}",
            )
            all_selections.append({
                "passenger_idx": idx,
                "chosen_label": primary_label,
                "slot": "primary",
            })

            # Extra bags via counter
            extra_count_key = f"luggage_extra_count_{idx}"
            if extra_count_key not in st.session_state:
                st.session_state[extra_count_key] = 0

            extra_count = st.number_input(
                "Additional bags",
                min_value=0,
                max_value=_MAX_EXTRA_BAGS,
                value=st.session_state[extra_count_key],
                key=f"luggage_extra_input_{idx}",
                help=f"Add up to {_MAX_EXTRA_BAGS} extra bags per passenger.",
            )

            for bag_i in range(int(extra_count)):
                extra_labels = [no_add_label] + tier_labels
                extra_label = st.selectbox(
                    f"Extra bag {bag_i + 1}",
                    extra_labels,
                    index=0,
                    key=f"luggage_extra_{idx}_{bag_i}",
                )
                if extra_label != no_add_label:
                    all_selections.append({
                        "passenger_idx": idx,
                        "chosen_label": extra_label,
                        "slot": f"extra_{bag_i}",
                    })

        # --- running total --------------------------------------------------
        running_total = 0.0
        for sel in all_selections:
            tier = label_to_tier.get(sel["chosen_label"])
            if tier:
                running_total += tier["price_tl"]

        st.markdown(f"**Luggage total: {running_total:,.0f} TL**")
        st.divider()

        submitted = st.button("✅ Confirm Luggage", key="luggage_submit", disabled=st.session_state.get("is_thinking", False))

    if not submitted:
        return

    # --- validate and store -------------------------------------------------
    result = _process_luggage_submission(all_selections, label_to_tier, ticket_class)

    if result["success"]:
        st.session_state.pending_user_message = (
            "[System Note: User successfully submitted the luggage"
            f" form. {result.get('detail', '')} Now call render_secure_form(form_type='extras').]".strip()
        )
        st.session_state.report_data = None
        st.rerun()
    else:
        st.error(result["error"])


def _process_luggage_submission(
    selections: list[dict],
    label_to_tier: dict[str, dict],
    ticket_class: str,
) -> dict:
    """Validate luggage selections and persist to session state."""
    luggage_records: list[dict] = []

    for sel in selections:
        tier = label_to_tier.get(sel["chosen_label"])
        if tier is None:
            continue  # "no add" placeholder — skip

        val = validate_luggage_selection(tier["key"], ticket_class)
        if not val["valid"]:
            return {
                "success": False,
                "error": f"Passenger {sel['passenger_idx'] + 1}: {val['error']}",
            }

        luggage_records.append({
            "passenger_idx": sel["passenger_idx"],
            "tier": tier["key"],
            "label": tier["label"],
            "price_tl": tier["price_tl"],
        })

    st.session_state.luggage_selections = luggage_records
    return {"success": True, "detail": "Luggage selections recorded."}
