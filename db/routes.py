"""
db.routes

Human-readable route catalogue and structured route-detail queries.
"""

from __future__ import annotations

from database.db import fetch_all, fetch_one

from db._helpers import _time_to_str
from db.flights import find_flight
from db.models import TransferStatus


def route_catalogue() -> str:
    """
    Human-readable route catalogue.

    This is useful for system prompts or UI diagnostics.
    """
    rows = fetch_all(
        """
        SELECT
            f.*,
            o.city AS origin_city,
            d.city AS dest_city
        FROM flights f
        JOIN airports o ON o.code = f.origin_code
        JOIN airports d ON d.code = f.dest_code
        WHERE f.is_leg = 0
        ORDER BY f.flight_number
        """
    )

    lines = []

    for row in rows:
        connection = row.get("connection_airport")

        extra = f" via {connection}" if connection else ""
        plus_one_day = " (+1d)" if row.get("arrival_date_offset") else ""
        base_price = int(row.get("base_price_tl") or 0)

        lines.append(
            f"  • {row['origin_code']} ({row['origin_city']}) → "
            f"{row['dest_code']} ({row['dest_city']}){extra}: "
            f"{row['flight_number']}, dep {_time_to_str(row.get('departure_time'))}, "
            f"arr {_time_to_str(row.get('arrival_time'))}{plus_one_day}, "
            f"{row.get('duration_text')}, "
            f"{row['transfer_status']}, "
            f"{row.get('aircraft_model')}, "
            f"{base_price:,} TL/person"
        )

    return "\n".join(lines)


def db_list_all_routes() -> dict:
    """
    Return all independently sellable routes with flight details.
    """
    rows = fetch_all(
        """
        SELECT
            f.*,
            o.city AS origin_city,
            o.country AS origin_country,
            d.city AS dest_city,
            d.country AS dest_country
        FROM flights f
        JOIN airports o ON o.code = f.origin_code
        JOIN airports d ON d.code = f.dest_code
        WHERE f.is_leg = 0
        ORDER BY f.flight_number
        """
    )

    routes = []

    for row in rows:
        routes.append(
            {
                "flight_number": row["flight_number"],
                "origin": f"{row['origin_code']} – {row['origin_city']}, {row['origin_country']}",
                "destination": f"{row['dest_code']} – {row['dest_city']}, {row['dest_country']}",
                "departure_time": _time_to_str(row.get("departure_time")),
                "arrival_time": _time_to_str(row.get("arrival_time")),
                "arrival_date_offset": row.get("arrival_date_offset") or 0,
                "duration": row.get("duration_text"),
                "transfer_status": row["transfer_status"],
                "connection_airport": row.get("connection_airport"),
                "aircraft_type": row.get("aircraft_model"),
                "max_capacity": row.get("max_capacity"),
                "base_price_tl": float(row["base_price_tl"]) if row.get("base_price_tl") is not None else 0.0,
            }
        )

    return {
        "routes": routes,
        "total_routes": len(routes),
    }


def db_get_route_details(departure: str, arrival: str) -> dict:
    """
    Return full details for one route.

    For connecting itineraries, includes the underlying leg details.
    """
    flight = find_flight(departure, arrival)

    if not flight:
        return {"error": f"No route from '{departure}' to '{arrival}'."}

    origin_info = fetch_one(
        """
        SELECT city, country
        FROM airports
        WHERE code = %s
        """,
        (flight["origin_code"],),
    )

    dest_info = fetch_one(
        """
        SELECT city, country
        FROM airports
        WHERE code = %s
        """,
        (flight["dest_code"],),
    )

    result = {
        "flight_number": flight["flight_number"],
        "origin": f"{flight['origin_code']} – {origin_info['city']}, {origin_info['country']}",
        "destination": f"{flight['dest_code']} – {dest_info['city']}, {dest_info['country']}",
        "departure_time": flight["departure_time"],
        "arrival_time": flight["arrival_time"],
        "arrival_date_offset": flight["arrival_date_offset"],
        "duration": flight["duration"],
        "transfer_status": flight["transfer_status"].value,
        "aircraft_type": flight["aircraft_type"],
        "max_capacity": flight["max_capacity"],
        "base_price_tl": flight["base_price_tl"],
    }

    if flight["transfer_status"] == TransferStatus.CONNECTING:
        legs = []

        for leg_id in flight.get("legs", []):
            leg_row = fetch_one(
                """
                SELECT
                    flight_number,
                    origin_code,
                    dest_code,
                    departure_time,
                    arrival_time
                FROM flights
                WHERE flight_id = %s
                """,
                (leg_id,),
            )

            if leg_row:
                legs.append(
                    {
                        "flight_number": leg_row["flight_number"],
                        "origin_code": leg_row["origin_code"],
                        "dest_code": leg_row["dest_code"],
                        "departure_time": _time_to_str(leg_row["departure_time"]),
                        "arrival_time": _time_to_str(leg_row["arrival_time"]),
                    }
                )

        result["connection_airport"] = flight.get("connection_airport")
        result["layover_minutes"] = flight.get("layover_minutes")
        result["legs"] = legs

    return result
