"""
Form Dispatcher Module
Routes to the appropriate form rendering logic based on the requested form type.
"""

from .auth_form import render_auth_form
from .passenger_form import render_passenger_form
from .payment_form import render_payment_form


def render_secure_form_ui(form_type: str):
    """
    Dispatch to the correct form component based on the requested form_type.

    Supported form_type values:
    - 'auth': Authentication form (Login/Register/Guest)
    - 'passenger_details' or 'passenger': Passenger details form
    - 'payment': Payment and billing form
    """
    if form_type == "auth":
        return render_auth_form()
    elif form_type in ("passenger_details", "passenger"):
        return render_passenger_form()
    elif form_type == "payment":
        return render_payment_form()
    else:
        raise ValueError(
            f"Unsupported form_type: '{form_type}'. "
            "Expected one of: 'auth', 'passenger_details', 'payment'."
        )


__all__ = [
    "render_secure_form_ui",
    "render_auth_form",
    "render_passenger_form",
    "render_payment_form",
]