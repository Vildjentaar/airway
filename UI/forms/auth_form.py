"""
UI/forms/auth_form.py

Renders the authentication step of the booking flow (Guest / Login / Register)
and processes the submitted form data against the AuthProvider service.

On successful submission, sets `pending_user_message` and reruns so the LLM
can advance the checkout pipeline.
"""

from __future__ import annotations

import re
from typing import Optional

import streamlit as st

from ..constants import AUTH_MODES
from ..validation.name_rules import validate_name

from accounts import default_auth_provider

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def render_auth_form() -> None:
    """Render the authentication form and process submission."""
    st.markdown("### Secure Checkout: Auth")

    mode = st.radio("Checkout as:", AUTH_MODES, key="auth_mode")

    with st.form(key="form_auth"):
        email = st.text_input("Email", placeholder="you@example.com")
        password: Optional[str] = None
        first_name: Optional[str] = None
        last_name: Optional[str] = None

        if mode in ("Login", "Register"):
            password = st.text_input("Password", type="password")
        if mode == "Register":
            first_name = st.text_input("First Name", max_chars=32)
            last_name = st.text_input("Last Name", max_chars=32)

        submitted = st.form_submit_button("Submit & Continue", disabled=st.session_state.get("is_thinking", False))

    if not submitted:
        return

    name = f"{first_name or ''} {last_name or ''}".strip() if mode == "Register" else None
    result = _process_auth_submission(mode, email, password, name)

    if result["success"]:
        st.session_state.pending_user_message = (
            f"[System Note: User successfully submitted the auth form. {result.get('detail', '')}]".strip()
        )
        st.session_state.report_data = None
        st.rerun()
    else:
        st.error(result["error"])


def _process_auth_submission(
    mode: str,
    email: Optional[str],
    password: Optional[str],
    name: Optional[str] = None,
) -> dict:
    """Validate auth data and delegate to the AuthProvider service."""
    if not email or not EMAIL_REGEX.match(email):
        return {"success": False, "error": "Please enter a valid email address."}

    if mode == "Guest":
        # Persist the guest email so the backend email service can use it
        # without requiring a full user_profile object.
        st.session_state.guest_email = email
        return {"success": True, "detail": "Continuing as guest."}

    if mode == "Login":
        result = default_auth_provider.authenticate(email or "", password or "")
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {
                "success": True,
                "detail": f"Logged in as {result['profile'].get('name', email)}.",
            }
        return {"success": False, "error": result["error"]}

    if mode == "Register":
        if name:
            name_result = validate_name(name)
            if not name_result:
                return {"success": False, "error": name_result.error_message}

        result = default_auth_provider.register(
            {"email": email, "password": password, "name": name}
        )
        if result["success"]:
            st.session_state.user_profile = result["profile"]
            return {"success": True, "detail": "Account created."}
        return {"success": False, "error": result["error"]}

    return {"success": False, "error": "Please select Guest, Login, or Register."}