"""
db.bookings

Booking listing/detail queries, plus capacity (overbooking) checks.
"""

from __future__ import annotations

from database.db import fetch_all, fetch_one

from db._helpers import _date_to_str
from db.flights import get_flight_by_number


def db_list_bookings() -> dict:
    """
    Return all bookings.

    Booking status is returned as a string for JSON/LLM compatibility.
    """
    rows = fetch_all(
        """
        SELECT
            b.booking_id,
            b.passenger_count,
            b.trip_type,
            b.total_price_tl,
            b.booking_status,
            b.notes
        FROM bookings b
        ORDER BY b.booking_id
        """
    )

    segments_rows = fetch_all(
        """
        SELECT
            s.booking_id,
            s.segment_order,
            f.flight_number,
            s.departure_date
        FROM booking_segments s
        JOIN flights f ON f.flight_id = s.flight_id
        ORDER BY s.booking_id, s.segment_order
        """
    )

    segments_by_booking = {}
    for sr in segments_rows:
        bid = sr["booking_id"]
        if bid not in segments_by_booking:
            segments_by_booking[bid] = []
        segments_by_booking[bid].append({
            "flight_number": sr["flight_number"],
            "departure_date": _date_to_str(sr["departure_date"])
        })

    bookings = []
    for row in rows:
        bid = row["booking_id"]
        bookings.append(
            {
                "booking_id": bid,
                "passenger_count": row["passenger_count"],
                "trip_type": row["trip_type"],
                "segments": segments_by_booking.get(bid, []),
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
            b.passenger_count,
            b.trip_type,
            b.total_price_tl,
            b.booking_status,
            b.notes
        FROM bookings b
        WHERE b.booking_id = %s
        """,
        (booking_id,),
    )

    if not row:
        return {"error": f"Booking {booking_id} not found."}

    segments_rows = fetch_all(
        """
        SELECT
            s.segment_order,
            f.flight_number,
            s.departure_date
        FROM booking_segments s
        JOIN flights f ON f.flight_id = s.flight_id
        WHERE s.booking_id = %s
        ORDER BY s.segment_order
        """,
        (booking_id,)
    )

    segments = []
    flights_info = []
    for sr in segments_rows:
        segments.append({
            "flight_number": sr["flight_number"],
            "departure_date": _date_to_str(sr["departure_date"])
        })
        flights_info.append(get_flight_by_number(sr["flight_number"]))

    booking = {
        "booking_id": row["booking_id"],
        "passenger_count": row["passenger_count"],
        "trip_type": row["trip_type"],
        "segments": segments,
        "total_price_tl": float(row["total_price_tl"]) if row.get("total_price_tl") is not None else None,
        "booking_status": row["booking_status"],
        "notes": row.get("notes"),
    }

    return {
        "booking": booking,
        "segments_flights": flights_info,
    }


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
