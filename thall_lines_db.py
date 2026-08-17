"""
thall_lines_db.py

SQL-backed flight and booking repository.

This module is the secure middleman between LLM-facing tools and MySQL.

Design rules:
- No raw SQL is exposed to the LLM.
- No dynamic SQL is built from LLM input.
- All queries are hardcoded and parameterized.
- Only explicit repository functions are callable by tools.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from enum import Enum
from typing import Any

from database.db import fetch_all, fetch_one

AIRLINE_NAME = "Thall Lines"


# ---------------------------------------------------------------------------
# Enums kept for backward compatibility
# ---------------------------------------------------------------------------
class TransferStatus(str, Enum):
    DIRECT = "Direct"
    CONNECTING = "Connecting"


class BookingStatus(str, Enum):
    CONFIRMED = "Confirmed"
    PENDING = "Pending"
    CANCELLED = "Cancelled"
    WAITLISTED = "Waitlisted"
    FAILED = "Failed"


TRANSFER_STATUS_LOCALIZED = {
    TransferStatus.DIRECT: {
        "en": "Direct",
        "tr": "Direkt",
    },
    TransferStatus.CONNECTING: {
        "en": "Connecting",
        "tr": "Aktarmalı",
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Flight queries
# ---------------------------------------------------------------------------
def get_flight_by_number(flight_number: str) -> dict | None:
    """
    Get one flight by flight_number.

    LLM-safe:
    - flight_number is passed as a parameter.
    """
    flight_number = (flight_number or "").strip()

    if not flight_number:
        return None

    row = fetch_one(
        """
        SELECT *
        FROM flights
        WHERE flight_number = %s
        """,
        (flight_number,),
    )

    return _flight_row_to_dict(row)


def search_flights(departure: str, arrival: str) -> list[dict]:
    """
    Return all independently sellable flights matching a route.

    Direct flights are ranked before connecting itineraries.

    LLM-safe:
    - departure/arrival are resolved through _resolve_code.
    - SQL uses parameters only.
    """
    origin_code = _resolve_code(departure)
    dest_code = _resolve_code(arrival)

    if not origin_code or not dest_code:
        return []

    rows = fetch_all(
        """
        SELECT *
        FROM flights
        WHERE origin_code = %s
          AND dest_code = %s
          AND is_leg = 0
        ORDER BY
            CASE transfer_status
                WHEN 'Direct' THEN 0
                ELSE 1
            END,
            flight_number
        """,
        (origin_code, dest_code),
    )

    return [_flight_row_to_dict(row) for row in rows]


def find_flight(departure: str, arrival: str) -> dict | None:
    """
    API-compatible replacement for the old mock find_flight().

    Returns the best matching sellable flight, preferring Direct flights.
    """
    flights = search_flights(departure, arrival)

    if not flights:
        return None

    return flights[0]


# ---------------------------------------------------------------------------
# Capacity / overbooking
# ---------------------------------------------------------------------------
def db_check_capacity(
    flight_number: str,
    departure_date: str,
    additional_passengers: int = 0,
) -> dict:
    """
    Check remaining seats for a flight/date.

    Only Confirmed and Pending bookings hold seats.
    Cancelled, Failed, and Waitlisted bookings do not.
    """
    flight_number = (flight_number or "").strip()

    flight = get_flight_by_number(flight_number)

    if not flight:
        return {"error": f"Flight '{flight_number}' not found."}

    row = fetch_one(
        """
        SELECT
            COALESCE(SUM(
                CASE
                    WHEN b.booking_status IN ('Confirmed', 'Pending')
                    THEN b.passenger_count
                    ELSE 0
                END
            ), 0) AS seats_booked
        FROM bookings b
        JOIN flights f ON f.flight_id = b.flight_id
        WHERE f.flight_number = %s
          AND b.departure_date = %s
        """,
        (flight_number, departure_date),
    )

    seats_booked = int(row["seats_booked"] or 0)
    max_capacity = int(flight.get("max_capacity") or 0)
    remaining = max_capacity - seats_booked

    return {
        "flight_number": flight_number,
        "departure_date": departure_date,
        "max_capacity": max_capacity,
        "seats_booked": seats_booked,
        "seats_remaining": max(remaining, 0),
        "can_accommodate": remaining >= additional_passengers,
        "would_overbook_by": max(additional_passengers - remaining, 0),
    }


# ---------------------------------------------------------------------------
# Route catalogue / route details
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Airport queries
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Booking queries
# ---------------------------------------------------------------------------
def db_list_bookings() -> dict:
    """
    Return all bookings.

    Booking status is returned as a string for JSON/LLM compatibility.
    """
    rows = fetch_all(
        """
        SELECT
            b.booking_id,
            outbound_flight.flight_number,
            return_flight.flight_number AS return_flight_number,
            b.passenger_count,
            b.trip_type,
            b.departure_date,
            b.return_date,
            b.total_price_tl,
            b.booking_status,
            b.notes
        FROM bookings b
        JOIN flights outbound_flight
            ON outbound_flight.flight_id = b.flight_id
        LEFT JOIN flights return_flight
            ON return_flight.flight_id = b.return_flight_id
        ORDER BY b.booking_id
        """
    )

    bookings = []

    for row in rows:
        bookings.append(
            {
                "booking_id": row["booking_id"],
                "flight_number": row["flight_number"],
                "return_flight_number": row["return_flight_number"],
                "passenger_count": row["passenger_count"],
                "trip_type": row["trip_type"],
                "departure_date": _date_to_str(row["departure_date"]),
                "return_date": _date_to_str(row["return_date"]),
                "total_price_tl": float(row["total_price_tl"]) if row.get("total_price_tl") is not None else None,
                "booking_status": row["booking_status"],
                "notes": row.get("notes"),
            }
        )

    return {
        "bookings": bookings,
        "total": len(bookings),
    }


def get_booking_details(booking_id: int | str) -> dict:
    """
    Safe LLM-facing booking lookup.

    The LLM may provide booking_id as a string or number.
    We normalize it to int before using it as a SQL parameter.
    """
    try:
        booking_id = int(booking_id)
    except (TypeError, ValueError):
        return {"error": "booking_id must be an integer."}

    row = fetch_one(
        """
        SELECT
            b.booking_id,
            outbound_flight.flight_number,
            return_flight.flight_number AS return_flight_number,
            b.passenger_count,
            b.trip_type,
            b.departure_date,
            b.return_date,
            b.total_price_tl,
            b.booking_status,
            b.notes
        FROM bookings b
        JOIN flights outbound_flight
            ON outbound_flight.flight_id = b.flight_id
        LEFT JOIN flights return_flight
            ON return_flight.flight_id = b.return_flight_id
        WHERE b.booking_id = %s
        """,
        (booking_id,),
    )

    if not row:
        return {"error": f"Booking {booking_id} not found."}

    booking = {
        "booking_id": row["booking_id"],
        "flight_number": row["flight_number"],
        "return_flight_number": row["return_flight_number"],
        "passenger_count": row["passenger_count"],
        "trip_type": row["trip_type"],
        "departure_date": _date_to_str(row["departure_date"]),
        "return_date": _date_to_str(row["return_date"]),
        "total_price_tl": float(row["total_price_tl"]) if row.get("total_price_tl") is not None else None,
        "booking_status": row["booking_status"],
        "notes": row.get("notes"),
    }

    outbound_flight = get_flight_by_number(row["flight_number"])
    return_flight = None

    if row["return_flight_number"]:
        return_flight = get_flight_by_number(row["return_flight_number"])

    return {
        "booking": booking,
        "outbound_flight": outbound_flight,
        "return_flight": return_flight,
    }


# ---------------------------------------------------------------------------
# Ancillary catalogues (seats, luggage, extras)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Self-test helpers
# ---------------------------------------------------------------------------
def self_test_bidirectional_coverage() -> list[str]:
    """
    SQL-backed replacement for the old mock bidirectional coverage test.
    """
    rows = fetch_all(
        """
        SELECT DISTINCT
            f.origin_code,
            f.dest_code
        FROM flights f
        WHERE f.is_leg = 0
          AND NOT EXISTS (
              SELECT 1
              FROM flights r
              WHERE r.origin_code = f.dest_code
                AND r.dest_code = f.origin_code
                AND r.is_leg = 0
          )
        ORDER BY f.origin_code, f.dest_code
        """
    )

    return [
        f"{row['origin_code']}->{row['dest_code']} has no return route "
        f"{row['dest_code']}->{row['origin_code']}"
        for row in rows
    ]
