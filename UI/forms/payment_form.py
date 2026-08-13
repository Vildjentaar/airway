"""
UI/forms/payment_form.py

Renders the secure payment form, validates card shape using the validation
module, then delegates actual charging to the PaymentGateway service.

On successful submission, sets `pending_user_message` and reruns so the LLM
can advance the checkout pipeline.
"""

from __future__ import annotations

import streamlit as st

from ..validation.payment_rules import (
    validate_card_number,
    validate_cardholder_name,
    validate_cvc,
    validate_expiry,
)

from payment import default_payment_gateway


def render_payment_form() -> None:
    """Render the payment form UI and handle submission."""
    st.markdown("### Secure Checkout: Payment")

    with st.form(key="form_payment"):
        cardholder_name = st.text_input("Cardholder Name")
        card_number = st.text_input(
            "Card Number", max_chars=16,
            placeholder="0000 0000 0000 0000",
        )
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

    expiry = f"{exp_mm}/{exp_yy}" if exp_mm and exp_yy else ""
    result = _process_payment_submission(cardholder_name, card_number, expiry, cvc)

    if result["success"]:
        st.session_state.pending_user_message = (
            "[System Note: User successfully submitted the payment form."
            f" {result.get('detail', '')}]".strip()
        )
        st.rerun()
    else:
        st.error(result["error"])


def _process_payment_submission(
    cardholder_name: str,
    card_number: str,
    expiry: str,
    cvc: str,
) -> dict:
    """Validate card shape, then delegate to the PaymentGateway service."""
    # Shape validation using the new validation module
    name_ok, name_msg = validate_cardholder_name(cardholder_name)
    if not name_ok:
        return {"success": False, "error": name_msg}

    card_ok, card_msg = validate_card_number(card_number)
    if not card_ok:
        return {"success": False, "error": card_msg}

    expiry_ok, expiry_msg = validate_expiry(expiry)
    if not expiry_ok:
        return {"success": False, "error": expiry_msg}

    cvc_ok, cvc_msg = validate_cvc(cvc)
    if not cvc_ok:
        return {"success": False, "error": cvc_msg}

    # Delegate to the payment gateway service
    result = default_payment_gateway.charge(
        card_number or "", expiry or "", cvc or "", cardholder_name or "",
    )
    if result["success"]:
        st.session_state.payment_details = {
            "card_last4": (card_number or "")[-4:],
        }
        return {
            "success": True,
            "detail": f"Payment approved ({result['transaction_id']}).",
        }
    return {"success": False, "error": result["error"]}