"""
seat_data.py
------------
Seat-map catalogue and validation helpers.

Delegates to ``thall_lines_db.db_get_seat_types()`` for the raw catalogue
(sourced from the ``seat_types`` table created by ``02-ancillary.sql``).
This module adds:

  * ``get_available_seats``  — per-flight/class seat list with occupancy
  * ``validate_seat_selection`` — pre-submit guard used by the UI form
  * ``SEAT_TYPES``             — convenience re-export of the DB catalogue
"""

from __future__ import annotations

from thall_lines_db import db_get_seat_types


# ---------------------------------------------------------------------------
# Catalogue (read-once, DB-backed)
# ---------------------------------------------------------------------------
def _load_seat_types() -> dict[str, dict]:
    """Fetch seat-type catalogue from MySQL and index by key."""
    rows = db_get_seat_types()
    return {row["key"]: row for row in rows}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_seat_type_catalogue() -> list[dict]:
    """Return the full seat-type catalogue as a list of dicts.

    Each entry: ``{"key", "label", "price_tl", "description"}``.
    """
    return db_get_seat_types()


def get_available_seats(
    flight_number: str,
    ticket_class: str,
) -> list[dict]:
    """Return bookable seat options for a given flight and ticket class.

    Each entry::

        {
            "key":         "extra_legroom",
            "label":       "Extra Legroom",
            "price_tl":    250.0,
            "description": "Seats in rows 12-14 with extra pitch.",
        }

    Business-class passengers receive ``front_row`` at no extra charge
    (price_tl set to 0).

    Parameters
    ----------
    flight_number:
        The flight this seat map applies to (reserved for future per-flight
        maps; currently returns the global catalogue).
    ticket_class:
        ``"Economy"`` or ``"Business"`` — determines complimentary upgrades.
    """
    catalogue = db_get_seat_types()
    is_business = (ticket_class or "").strip().lower() == "business"

    # Business perks: front_row and extra_legroom are complimentary
    business_free_keys = {"front_row", "extra_legroom"}

    seats: list[dict] = []
    for seat in catalogue:
        price = seat["price_tl"]
        if is_business and seat["key"] in business_free_keys:
            price = 0.0

        seats.append({
            "key":         seat["key"],
            "label":       seat["label"],
            "price_tl":    price,
            "description": seat.get("description", ""),
        })

    return seats


def validate_seat_selection(
    seat_key: str,
    ticket_class: str = "Economy",
) -> dict:
    """Check if a seat selection key is valid.

    Returns
    -------
    dict
        ``{"valid": True}`` on success, or
        ``{"valid": False, "error": "..."}`` on failure.
    """
    catalogue = _load_seat_types()

    if seat_key not in catalogue:
        return {
            "valid": False,
            "error": f"Unknown seat type '{seat_key}'. "
                     f"Valid options: {', '.join(catalogue.keys())}.",
        }

    return {"valid": True}
