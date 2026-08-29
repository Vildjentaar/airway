"""
extras_data.py
--------------
Extra-services catalogue and helpers.

Delegates to ``thall_lines_db.db_get_extra_services()`` for the raw
catalogue (sourced from the ``extra_services`` table created by
``02-ancillary.sql``).

This module adds:

  * ``get_extras_for_class`` — returns extras with ``included`` flag and
    effective pricing per ticket class.
  * ``validate_extras_selection`` — pre-submit guard used by the UI form.
"""

from __future__ import annotations

from thall_lines_db import db_get_extra_services


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_extras_for_class(ticket_class: str = "Economy") -> list[dict]:
    """Return available extra services for a given ticket class.

    Each entry::

        {
            "key":         "lounge_access",
            "label":       "Lounge Access",
            "price_tl":    400.0,     # 0.0 when included
            "included":    False,
            "description": "Access to the airline lounge before departure.",
        }

    Business-class passengers get certain services (priority boarding,
    lounge, flexi-ticket, champagne) complimentary according to the DB's
    ``included_in_business`` flag.

    Parameters
    ----------
    ticket_class:
        ``"Economy"`` or ``"Business"``.
    """
    return db_get_extra_services(ticket_class)


def validate_extras_selection(
    service_keys: list[str],
    ticket_class: str = "Economy",
) -> dict:
    """Check if a list of extra-service keys are all valid.

    Returns
    -------
    dict
        ``{"valid": True}`` on success, or
        ``{"valid": False, "error": "..."}`` on failure.
    """
    extras = db_get_extra_services(ticket_class)
    valid_keys = {e["key"] for e in extras}

    invalid = [k for k in service_keys if k not in valid_keys]
    if invalid:
        return {
            "valid": False,
            "error": f"Unknown service(s): {', '.join(invalid)}. "
                     f"Valid options: {', '.join(sorted(valid_keys))}.",
        }

    return {"valid": True}
