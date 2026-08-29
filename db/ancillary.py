"""
db.ancillary

Ancillary product catalogues: seat types, luggage tiers, extra services.
"""

from __future__ import annotations

from database.db import fetch_all


def db_get_seat_types() -> list[dict]:
    """
    Return all bookable seat categories with their price deltas.

    The UI renders these as radio/select options during seat selection.
    """
    rows = fetch_all(
        """
        SELECT
            seat_type_key,
            label,
            price_tl,
            description
        FROM seat_types
        ORDER BY display_order
        """
    )

    return [
        {
            "key":         row["seat_type_key"],
            "label":       row["label"],
            "price_tl":    float(row["price_tl"]),
            "description": row.get("description") or "",
        }
        for row in rows
    ]


def db_get_luggage_tiers(ticket_class: str = "Economy") -> list[dict]:
    """
    Return luggage tiers with an ``included`` flag based on ticket class.

    Business passengers get ``checked_20kg`` marked as included (free).
    Economy passengers only get ``cabin_only`` included.
    """
    is_business = ticket_class.strip().lower() == "business"

    rows = fetch_all(
        """
        SELECT
            tier_key,
            label,
            weight_kg,
            price_tl,
            included_in_economy,
            included_in_business
        FROM luggage_tiers
        ORDER BY display_order
        """
    )

    result = []
    for row in rows:
        included = bool(
            row["included_in_business"] if is_business
            else row["included_in_economy"]
        )
        result.append({
            "key":       row["tier_key"],
            "label":     row["label"],
            "weight_kg": row["weight_kg"],
            "price_tl":  0.0 if included else float(row["price_tl"]),
            "included":  included,
        })
    return result


def db_get_extra_services(ticket_class: str = "Economy") -> list[dict]:
    """
    Return extra services with an ``included`` flag based on ticket class.

    Business passengers get certain services (priority boarding, lounge)
    complimentary.
    """
    is_business = ticket_class.strip().lower() == "business"

    rows = fetch_all(
        """
        SELECT
            service_key,
            label,
            price_tl,
            included_in_business,
            description
        FROM extra_services
        ORDER BY display_order
        """
    )

    result = []
    for row in rows:
        included = bool(row["included_in_business"]) if is_business else False
        result.append({
            "key":         row["service_key"],
            "label":       row["label"],
            "price_tl":    0.0 if included else float(row["price_tl"]),
            "included":    included,
            "description": row.get("description") or "",
        })
    return result
