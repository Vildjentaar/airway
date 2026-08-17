"""
Form Dispatcher Module
Routes to the appropriate form rendering logic based on the requested form type.
"""

from .auth_form import render_auth_form
from .passenger_form import render_passenger_form
from .seat_form import render_seat_form
from .luggage_form import render_luggage_form
from .extras_form import render_extras_form
from .payment_form import render_payment_form


def render_secure_form_ui(form_type: str):
    """
    Dispatch to the correct form component based on the requested form_type.

    Supported form_type values:
    - 'auth': Authentication form (Login/Register/Guest)
    - 'passenger_details' or 'passenger': Passenger details form
    - 'seat_selection' or 'seat': Per-passenger seat type selection
    - 'luggage': Per-passenger luggage tier selection
    - 'extras' or 'extra_services': Add-on services (per-booking)
    - 'payment': Payment and billing form
    """
    if form_type == "auth":
        return render_auth_form()
    elif form_type in ("passenger_details", "passenger"):
        return render_passenger_form()
    elif form_type in ("seat_selection", "seat"):
        return render_seat_form()
    elif form_type == "luggage":
        return render_luggage_form()
    elif form_type in ("extras", "extra_services"):
        return render_extras_form()
    elif form_type == "payment":
        return render_payment_form()
    else:
        raise ValueError(
            f"Unsupported form_type: '{form_type}'. "
            "Expected one of: 'auth', 'passenger_details', 'seat_selection', 'luggage', 'extras', 'payment'."
        )


__all__ = [
    "render_secure_form_ui",
    "render_auth_form",
    "render_passenger_form",
    "render_seat_form",
    "render_luggage_form",
    "render_extras_form",
    "render_payment_form",
]