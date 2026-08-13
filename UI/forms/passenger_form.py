"""
UI/forms/passenger_form.py

Renders the passenger-details form for ALL passengers in the booking
(Adult / Child / Baby) in a single batch, and processes submission with
age-bracket and TCKN validation.

Pre-fills the first adult from the authenticated user's profile when available.
On successful submission, sets `pending_user_message` and reruns so the LLM
can advance the checkout pipeline.

Delegates character-level validation to UI/validation/name_rules.py and
age-bracket checks to UI/validation/passenger_rules.py.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from ..constants import GENDERS, NATIONALITIES
from ..validation.name_rules import validate_name
from ..validation.passenger_rules import validate_age_for_type

from accounts import validate_tckn


def render_passenger_form() -> None:
    """
    Render the passenger-details form for every passenger in the booking.
    Reads Adult/Child/Baby counts from ``flight_data[0]`` and pre-fills
    the first adult from ``user_profile`` if available.
    """
    st.markdown("### Secure Checkout: Passenger Details")

    # --- defaults from authenticated profile --------------------------------
    profile = st.session_state.get("user_profile", {})
    default_fn = profile.get("name") or ""
    default_ln = profile.get("surname") or ""

    default_dob = datetime.today()
    if profile.get("birthdate"):
        try:
            bd = profile["birthdate"]
            if isinstance(bd, str):
                default_dob = datetime.strptime(bd, "%Y-%m-%d").date()
            else:
                default_dob = bd
        except Exception:
            pass

    sex = profile.get("sex")
    default_gender_idx = 0
    if sex == "M":
        default_gender_idx = 0
    elif sex == "F":
        default_gender_idx = 1
    elif sex == "O":
        default_gender_idx = 2

    nat = profile.get("nationality")
    default_nat_idx = NATIONALITIES.index(nat) if nat in NATIONALITIES else 0

    default_tckn = profile.get("tckn") or ""

    # --- passenger counts from the first flight in the cart ------------------
    flight = (
        st.session_state.flight_data[0]
        if st.session_state.get("flight_data")
        else {}
    )
    adults = flight.get("adult_count", 1)
    children = flight.get("child_count", 0)
    babies = flight.get("baby_count", 0)

    # --- render fields for every passenger -----------------------------------
    passenger_data_list: list[dict] = []

    with st.container():
        for p_type, count in [("Adult", adults), ("Child", children), ("Baby", babies)]:
            for i in range(count):
                st.markdown(f"#### {p_type} {i + 1}")
                is_first = p_type == "Adult" and i == 0

                fn_val = default_fn if is_first else ""
                ln_val = default_ln if is_first else ""
                dob_val = default_dob if is_first else datetime.today()
                gen_idx = default_gender_idx if is_first else 0
                nat_idx = default_nat_idx if is_first else 0
                tckn_val = default_tckn if is_first else ""

                fn = st.text_input(
                    "First Name", max_chars=32, value=fn_val,
                    key=f"{p_type}_{i}_fn",
                )
                ln = st.text_input(
                    "Last Name", max_chars=32, value=ln_val,
                    key=f"{p_type}_{i}_ln",
                )
                dob = st.date_input(
                    "Date of Birth", value=dob_val,
                    min_value=datetime(1926, 1, 1),
                    max_value=datetime.today(),
                    key=f"{p_type}_{i}_dob",
                )
                gender = st.radio(
                    "Gender", GENDERS, index=gen_idx,
                    key=f"{p_type}_{i}_gen",
                )
                nationality = st.selectbox(
                    "Nationality", NATIONALITIES, index=nat_idx,
                    key=f"{p_type}_{i}_nat",
                )

                tckn = ""
                if nationality == "TR":
                    tckn = st.text_input(
                        "TCKN", max_chars=11, value=tckn_val,
                        key=f"{p_type}_{i}_tckn",
                    )

                passenger_data_list.append({
                    "type": p_type,
                    "first_name": fn,
                    "last_name": ln,
                    "dob": dob,
                    "gender": gender,
                    "nationality": nationality,
                    "tckn": tckn,
                })

        submitted = st.button("Submit & Continue", key="passenger_submit")

    if not submitted:
        return

    result = _process_passenger_submission(passenger_data_list)

    if result["success"]:
        st.session_state.pending_user_message = (
            "[System Note: User successfully submitted the passenger_details"
            f" form. {result.get('detail', '')}]".strip()
        )
        st.rerun()
    else:
        st.error(result["error"])


def _process_passenger_submission(passengers: list) -> dict:
    """Validate all passengers and persist to ``st.session_state.passenger_details``."""
    today = datetime.today().date()

    for idx, p in enumerate(passengers):
        fn = p["first_name"].strip()
        ln = p["last_name"].strip()
        ptype = p["type"]
        label = f"{ptype} {idx + 1}"

        # Name validation via shared module
        fn_result = validate_name(fn, field_label=f"{label} first name")
        if not fn_result:
            return {"success": False, "error": fn_result.error_message}

        ln_result = validate_name(ln, field_label=f"{label} last name")
        if not ln_result:
            return {"success": False, "error": ln_result.error_message}

        # TCKN validation for Turkish nationals
        if p["nationality"].strip().upper() == "TR":
            tckn_result = validate_tckn(p["tckn"] or "")
            if not tckn_result["valid"]:
                return {"success": False, "error": f"{label}: {tckn_result['error']}"}

        # Age bracket validation — map "Baby" to "Infant" for the rules module
        bracket_type = "Infant" if ptype == "Baby" else ptype
        age_result = validate_age_for_type(bracket_type, p["dob"], as_of=today)
        if not age_result.is_valid:
            return {"success": False, "error": f"{label}: {age_result.error_message}"}

    st.session_state.passenger_details = passengers
    return {"success": True, "detail": "Passenger details recorded."}