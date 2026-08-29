"""
db.airports

Airport listing and per-airport info queries.
"""

from __future__ import annotations

from database.db import fetch_all, fetch_one

from db._helpers import _resolve_code


def db_list_airports() -> dict:
    """
    Return all serviced airports.
    """
    rows = fetch_all(
        """
        SELECT
            code,
            city,
            country,
            timezone
        FROM airports
        ORDER BY code
        """
    )

    return {
        "airports": rows,
    }


def db_get_airport_info(airport_code: str) -> dict:
    """
    Return airport information plus departing/arriving sellable flights.
    """
    code = _resolve_code(airport_code)

    if not code:
        return {"error": f"Airport '{airport_code}' not found in our network."}

    info = fetch_one(
        """
        SELECT
            code,
            city,
            country,
            timezone
        FROM airports
        WHERE code = %s
        """,
        (code,),
    )

    departures = fetch_all(
        """
        SELECT flight_number
        FROM flights
        WHERE origin_code = %s
          AND is_leg = 0
        ORDER BY flight_number
        """,
        (code,),
    )

    arrivals = fetch_all(
        """
        SELECT flight_number
        FROM flights
        WHERE dest_code = %s
          AND is_leg = 0
        ORDER BY flight_number
        """,
        (code,),
    )

    return {
        "code": info["code"],
        "city": info["city"],
        "country": info["country"],
        "timezone": info["timezone"],
        "departing_flights": [row["flight_number"] for row in departures],
        "arriving_flights": [row["flight_number"] for row in arrivals],
    }
