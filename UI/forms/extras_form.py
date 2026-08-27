"""
UI/forms/extras_form.py

Renders the extra-services selection form (per-booking, not per-passenger).

- Presents a checkbox list of available add-on services with prices.
- Business-class passengers see complimentary items pre-checked and labelled
  as "Included".
- A "Skip" button lets the user proceed without selecting any extras.
- On submit → validate → store to ``st.session_state.extras_selections`` →
  set ``pending_user_message`` → ``st.rerun()``.
"""

from __future__ import annotations

import streamlit as st

from extras_data import get_extras_for_class, validate_extras_selection


def render_extras_form() -> None:
    """Render the extras selection form and handle submission."""
    st.markdown("### ✨ Secure Checkout: Extra Services")

    # --- resolve ticket class -----------------------------------------------
    flight = (
        st.session_state.flight_data[0]
        if st.session_state.get("flight_data")
        else {}
    )
    ticket_class = flight.get("ticket_class", "Economy")

    # --- fetch extras catalogue for this class ------------------------------
    extras = get_extras_for_class(ticket_class)

    if not extras:
        st.info("No extra services available for this booking.")
        _skip_extras()
        return

    st.caption(
        "Enhance your journey with optional add-on services. "
        "Business-class inclusions are pre-selected at no extra charge."
    )

    # --- render checkbox grid -----------------------------------------------
    checked_states: list[tuple[dict, bool]] = []

    with st.container():
        for ext in extras:
            is_included = ext.get("included", False)

            if is_included:
                price_tag = "✅ Included"
            elif ext["price_tl"] == 0:
                price_tag = "Free"
            else:
                price_tag = f"+{ext['price_tl']:.0f} TL"

            label = f"{ext['label']} — {price_tag}"
            desc = ext.get("description", "")

            checked = st.checkbox(
                label,
                value=is_included,          # pre-check included items
                key=f"extra_cb_{ext['key']}",
                help=desc if desc else None,
            )

            checked_states.append((ext, checked))

        # --- running total --------------------------------------------------
        running_total = sum(
            ext["price_tl"] for ext, checked in checked_states if checked
        )
        st.markdown(f"**Extras total: {running_total:,.0f} TL**")
        st.divider()

        # --- action buttons -------------------------------------------------
        col_submit, col_skip = st.columns(2)
        with col_submit:
            submitted = st.button("✅ Confirm Extras", key="extras_submit", disabled=st.session_state.get("is_thinking", False))
        with col_skip:
            skipped = st.button("⏭️ Skip Extra Services", key="extras_skip", disabled=st.session_state.get("is_thinking", False))

    # --- handle skip --------------------------------------------------------
    if skipped:
        _skip_extras()
        return

    if not submitted:
        return

    # --- validate and store -------------------------------------------------
    selected = [ext for ext, checked in checked_states if checked]
    result = _process_extras_submission(selected, ticket_class)

    if result["success"]:
        st.session_state.pending_user_message = (
            "[System Note: User successfully submitted the extras"
            f" form. {result.get('detail', '')} Now call render_secure_form(form_type='payment').]".strip()
        )
        st.session_state.report_data = None
        st.rerun()
    else:
        st.error(result["error"])


def _skip_extras() -> None:
    """Record an empty extras selection and advance the pipeline."""
    st.session_state.extras_selections = []
    st.session_state.pending_user_message = (
        "[System Note: User skipped extra services selection. Now call render_secure_form(form_type='payment').]"
    )
    st.session_state.report_data = None
    st.rerun()


def _process_extras_submission(
    selected_extras: list[dict],
    ticket_class: str,
) -> dict:
    """Validate extra-service selections and persist to session state."""
    if not selected_extras:
        # Nothing selected — still valid, just empty
        st.session_state.extras_selections = []
        return {"success": True, "detail": "No extras selected."}

    service_keys = [e["key"] for e in selected_extras]
    val = validate_extras_selection(service_keys, ticket_class)
    if not val["valid"]:
        return {"success": False, "error": val["error"]}

    extras_records = [
        {
            "service": ext["key"],
            "label": ext["label"],
            "price_tl": ext["price_tl"],
        }
        for ext in selected_extras
    ]

    st.session_state.extras_selections = extras_records
    return {"success": True, "detail": "Extra services recorded."}
