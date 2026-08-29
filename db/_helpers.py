"""
db._helpers

Internal helpers shared by the query modules. Not part of the public API —
import from ``db`` (the package root) instead of this module directly.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from database.db import fetch_all, fetch_one

from db.models import TransferStatus


def _time_to_str(value: Any) -> str | None:
    """
    MySQL TIME columns often come back as timedelta objects.
    Convert them to 'HH:MM' strings for API compatibility.
    """
    if value is None:
        return None

    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours:02d}:{minutes:02d}"

    if isinstance(value, time):
        return value.strftime("%H:%M")

    return str(value)


def _date_to_str(value: Any) -> str | None:
    """
    MySQL DATE columns come back as date objects.
    Convert them to ISO date strings.
    """
    if value is None:
        return None

    if isinstance(value, date):
        return value.isoformat()

    return str(value)


def _flight_row_to_dict(row: dict | None) -> dict | None:
    """
    Convert a MySQL flights row into the dictionary shape used by the old
    mock FLIGHTS entries.
    """
    if not row:
        return None

    row = dict(row)

    transfer_status = TransferStatus(row["transfer_status"])

    flight = {
        "flight_id": row["flight_id"],
        "flight_number": row["flight_number"],
        "origin_code": row["origin_code"],
        "dest_code": row["dest_code"],
        "departure_time": _time_to_str(row.get("departure_time")),
        "arrival_time": _time_to_str(row.get("arrival_time")),
        "arrival_date_offset": row.get("arrival_date_offset") or 0,
        "duration": row.get("duration_text") or row.get("duration"),
        "transfer_status": transfer_status,
        "base_price_tl": float(row["base_price_tl"]) if row.get("base_price_tl") is not None else 0.0,
        "aircraft_type": row.get("aircraft_model") or row.get("aircraft_type"),
        "max_capacity": row.get("max_capacity"),
        "is_leg": bool(row.get("is_leg")),
    }

    if transfer_status == TransferStatus.DIRECT:
        flight["flight_minutes"] = row.get("flight_minutes")
        flight["legs"] = None
    else:
        # Connecting itinerary.
        # The old mock structure exposed legs as a list of flight_ids.
        flight["flight_minutes"] = None
        flight["layover_minutes"] = row.get("layover_minutes")
        flight["connection_airport"] = row.get("connection_airport")

        leg_rows = fetch_all(
            """
            SELECT leg_flight_id
            FROM flight_legs
            WHERE parent_flight_id = %s
            ORDER BY leg_order
            """,
            (flight["flight_id"],),
        )

        flight["legs"] = [leg_row["leg_flight_id"] for leg_row in leg_rows]

    return flight


def _resolve_code(city_or_code: str) -> str | None:
    """
    Resolve an airport code or city name to an airport code.

    This is safe because:
    - The input is only used as a query parameter.
    - The returned value is a DB-stored airport code.
    """
    candidate = (city_or_code or "").strip()

    if not candidate:
        return None

    row = fetch_one(
        """
        SELECT code
        FROM airports
        WHERE code = %s
           OR LOWER(city) = LOWER(%s)
        LIMIT 1
        """,
        (candidate.upper(), candidate),
    )

    return row["code"] if row else None
