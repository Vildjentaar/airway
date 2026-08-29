"""
luggage_data.py
---------------
Luggage-tier catalogue and helpers.

Delegates to ``db.db_get_luggage_tiers()`` for the raw
catalogue (sourced from the ``luggage_tiers`` table created by
``02-ancillary.sql``).

This module adds:

  * ``get_luggage_options`` — returns tiers with ``included`` flag set per
    ticket class and an ``effective_price_tl`` that respects inclusions.
  * ``validate_luggage_selection`` — pre-submit guard used by the UI form.
"""

from __future__ import annotations

from db import db_get_luggage_tiers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_luggage_options(ticket_class: str = "Economy") -> list[dict]:
    """Return available luggage tiers for a given ticket class.

    Each entry::

        {
            "key":        "checked_20kg",
            "label":      "Checked Bag (20 kg)",
            "weight_kg":  20,
            "price_tl":   350.0,   # 0.0 when included
            "included":   False,
        }

    Business-class passengers get ``cabin_only``, ``extra_cabin``,
    ``checked_20kg``, and ``musical_instr`` marked as included (free)
    according to the DB's ``included_in_business`` flag.

    Parameters
    ----------
    ticket_class:
        ``"Economy"`` or ``"Business"``.
    """
    return db_get_luggage_tiers(ticket_class)


def validate_luggage_selection(
    tier_key: str,
    ticket_class: str = "Economy",
) -> dict:
    """Check if a luggage tier key is valid.

    Returns
    -------
    dict
        ``{"valid": True}`` on success, or
        ``{"valid": False, "error": "..."}`` on failure.
    """
    tiers = db_get_luggage_tiers(ticket_class)
    valid_keys = {t["key"] for t in tiers}

    if tier_key not in valid_keys:
        return {
            "valid": False,
            "error": f"Unknown luggage tier '{tier_key}'. "
                     f"Valid options: {', '.join(sorted(valid_keys))}.",
        }

    return {"valid": True}
