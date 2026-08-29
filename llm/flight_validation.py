"""
llm/flight_validation.py
-------------------------
Booking-domain business logic for validating and pricing flights before
they are added to the cart.

This module is the most likely to grow over time (new fare rules, new
passenger types, ancillary pricing gates) — isolating it here means
those changes never touch the dispatch or sanitization code.

Dependencies
~~~~~~~~~~~~
* ``db`` — route / flight-number lookups.
* ``pricing`` — total-price calculation.
* ``llm.config.FLIGHT_REQUIRED`` — list of required segment keys.
* ``llm.history_sanitizer.extract_code`` — IATA code extraction.
"""

from datetime import datetime

from booking_context import _get_now
from db import find_flight, get_flight_by_number, AIRLINE_NAME
from pricing import calculate_total_price

from .config import FLIGHT_REQUIRED
from .history_sanitizer import extract_code


# --------------------------------------------------------------------------- #
# Cart-level validation
# --------------------------------------------------------------------------- #

def is_valid_flight_data(data) -> bool:
    """Return ``True`` only when all required fields are non-empty and
    price > 0 for every flight in the cart.
    """
    if not data or not isinstance(data, list):
        return False
    for flight in data:
        segments = flight.get("segments", [])
        if not segments:
            return False
        for segment in segments:
            all_filled = all(str(segment.get(f, "")).strip() for f in FLIGHT_REQUIRED)
            if not all_filled:
                return False
        price_ok = bool(flight.get("price_tl", 0))
        if not price_ok:
            return False
    return True


# --------------------------------------------------------------------------- #
# Single-flight verification & pricing
# --------------------------------------------------------------------------- #

def build_verified_flight(tool_args: dict, flight_data: list) -> dict:
    """Validate a ``generate_flight_widget`` call and, if valid, price it
    and return the flight record ready to add to the cart.

    Deliberately kept separate from the tool-dispatch layer: this function
    only knows about booking rules (passenger counts, dates, route
    existence, pricing, duplicates) and returns plain data.  It has no idea
    a ``tool_call`` or a ``messages`` list exists.  That split means the
    validation/pricing logic here can be tested or reused (e.g. from a
    future non-chat booking form) without dragging tool-call plumbing
    along with it, and adding a new validation rule never requires
    touching the tool-call bookkeeping in the dispatch layer.

    Returns ``{"error": "..."}`` or ``{"flight": {...}}``.
    """
    segments = tool_args.get("segments", [])
    if not segments:
        return {"error": "No flight segments provided."}

    trip_type = tool_args.get("trip_type", "One-way")
    adult_count = int(tool_args.get("adult_count", 0))
    child_count = int(tool_args.get("child_count", 0))
    baby_count = int(tool_args.get("baby_count", 0))
    ticket_class = tool_args.get("ticket_class", "Economy")

    # Fallback if old passenger_count is used by the model
    passenger_count = int(tool_args.get("passenger_count", 0))
    if passenger_count > 0 and adult_count == 0 and child_count == 0 and baby_count == 0:
        adult_count = passenger_count

    if adult_count < 0 or child_count < 0 or baby_count < 0:
        return {"error": "Passenger counts cannot be negative."}

    passengers = adult_count + child_count + baby_count
    passengers_breakdown = {"Adult": adult_count, "Child": child_count, "Baby": baby_count}

    if passengers <= 0 or passengers > 9:
        return {"error": "Invalid passenger count. Cannot book more than 9 passengers per transaction."}

    verified_segments = []
    prev_dep_date = None

    # Per-call cache: avoids hitting the DB twice for the same flight
    # number (e.g. round-trip using the same flight, or retries).
    _flight_cache: dict[str, dict | None] = {}

    for seg_idx, seg in enumerate(segments):
        dep_date_str = seg.get("departure_date", "")

        try:
            dep_date_parsed = datetime.strptime(dep_date_str, "%Y-%m-%d")
            current_time = _get_now()
            if dep_date_parsed.date() < current_time.date():
                return {"error": f"Departure date {dep_date_str} cannot be in the past."}
        except ValueError:
            return {"error": f"Invalid departure_date format: {dep_date_str}. Must be YYYY-MM-DD."}

        # Cross-segment chronological ordering: each segment must depart
        # on or after the previous segment's departure date.
        if prev_dep_date is not None and dep_date_parsed.date() < prev_dep_date:
            return {"error": (
                f"Segment {seg_idx + 1} departs on {dep_date_str}, which is before "
                f"the previous segment's departure date ({prev_dep_date.isoformat()}). "
                f"Segments must be in chronological order."
            )}
        prev_dep_date = dep_date_parsed.date()

        flight_number_provided = seg.get("flight_number")
        if not flight_number_provided:
            return {"error": (
                f"Segment {seg_idx + 1}: flight_number is required. "
                f"Use search_flights or search_itinerary to find valid flight numbers first."
            )}

        # Look up the flight entirely from the database — the LLM only
        # provides the flight_number; all route/time data comes from the DB.
        if flight_number_provided not in _flight_cache:
            _flight_cache[flight_number_provided] = get_flight_by_number(flight_number_provided)
        found = _flight_cache[flight_number_provided]
        if not found:
            return {"error": (
                f"Flight number '{flight_number_provided}' not found in the database. "
                f"Use search_flights or search_itinerary to find valid flight numbers."
            )}

        # If the LLM also provided departure_point/arrival_point (legacy
        # payloads or extra context), validate them against the DB record.
        dep_provided = seg.get("departure_point", "")
        arr_provided = seg.get("arrival_point", "")
        if dep_provided:
            dep_code = extract_code(dep_provided)
            if dep_code and dep_code != found["origin_code"]:
                return {"error": (
                    f"Flight {flight_number_provided} departs from {found['origin_code']}, "
                    f"not {dep_code}. Check the flight number."
                )}
        if arr_provided:
            arr_code = extract_code(arr_provided)
            if arr_code and arr_code != found["dest_code"]:
                return {"error": (
                    f"Flight {flight_number_provided} arrives at {found['dest_code']}, "
                    f"not {arr_code}. Check the flight number."
                )}

        # Also validate the exact time if the flight is today
        if dep_date_parsed.date() == current_time.date():
            # e.g. "09:00" -> parsed into hours and minutes
            dep_hour, dep_minute = map(int, found["departure_time"].split(":"))
            if current_time.hour > dep_hour or (current_time.hour == dep_hour and current_time.minute > dep_minute):
                return {"error": (
                    f"Flight {flight_number_provided} departs at {found['departure_time']}, "
                    f"which has already passed today. Please select a future flight."
                )}

        verified_segments.append({
            "departure_point": found["origin_code"],
            "arrival_point": found["dest_code"],
            "departure_date": dep_date_str,
            "departure_time": found["departure_time"],
            "arrival_time": found["arrival_time"],
            "flight_duration": found["duration"],
            "transfer_status": found["transfer_status"].value if hasattr(found["transfer_status"], "value") else found["transfer_status"],
            "airline_name": AIRLINE_NAME,
            "flight_number": found["flight_number"],
            "base_price_tl": found["base_price_tl"]
        })

    pricing_details = calculate_total_price(
        verified_segments, passengers, trip_type,
        detailed=True, ticket_class=ticket_class, passengers_breakdown=passengers_breakdown
    )

    verified = {
        "trip_type": trip_type,
        "passenger_count": passengers,
        "adult_count": adult_count,
        "child_count": child_count,
        "baby_count": baby_count,
        "ticket_class": ticket_class,
        "price_tl": pricing_details["total_tl"],
        "pricing_details": pricing_details,
        "segments": verified_segments,
    }

    # Compare ALL segments for duplicate detection, not just the first.
    # Two bookings sharing only the outbound but differing on return are
    # distinct, and vice versa.
    new_seg_keys = tuple(
        (s["flight_number"], s["departure_date"]) for s in verified_segments
    )
    is_duplicate = any(
        f.get("segments")
        and tuple(
            (s["flight_number"], s["departure_date"]) for s in f["segments"]
        ) == new_seg_keys
        for f in flight_data
    )
    if is_duplicate:
        return {"error": f"This itinerary is already in the cart."}

    return {"flight": verified}
