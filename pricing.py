"""
pricing.py
----------
Fare calculation — split out of the db/ package because "how much does
this cost" is a different responsibility than "what flights exist," even
though today they're both backed by the same mock data. Pricing rules
change on a completely different cadence and for completely different
reasons (a new fare class, a promo code, a seasonal surcharge) than the
flight schedule does, so they get their own file.

OPEN/CLOSED DESIGN:
calculate_total_price() used to grow a new keyword argument every time a
pricing dimension was added (ticket_class, then passengers_breakdown, ...).
That's a function you have to keep editing forever. Instead, each pricing
dimension is expressed as an independent "modifier" function in
PRICING_MODIFIERS below. Adding a new dimension later (a promo code, a
loyalty discount, a seasonal surcharge) means adding one function to that
list — calculate_total_price's body and signature never need to change
again.
"""

from __future__ import annotations

from typing import Callable

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
TAX_RATE = 0.08                 # 8% flat tax/fee, applied to the fare subtotal
PER_PASSENGER_FEE_TL = 150.00   # fixed airport/service fee per passenger, per direction

TICKET_CLASS_MULTIPLIER = {
    "Economy":  1.0,
    "Business": 2.5,
}

PASSENGER_TYPE_MULTIPLIER = {
    "Adult":  1.0,    # 12+
    "Child":  0.70,   # 2–12 (30% discount)
    "Baby":   0.10,   # 0–2  (90% discount, lap seat)
}


class FareContext:
    """Everything a pricing modifier might need to compute its adjustment
    for one (flight leg, ticket class, passenger type) combination."""

    def __init__(self, base_price_tl: float, ticket_class: str, passenger_type: str):
        self.base_price_tl = base_price_tl
        self.ticket_class = ticket_class
        self.passenger_type = passenger_type


def _ticket_class_modifier(ctx: FareContext) -> float:
    return TICKET_CLASS_MULTIPLIER.get(ctx.ticket_class, 1.0)


def _passenger_type_modifier(ctx: FareContext) -> float:
    return PASSENGER_TYPE_MULTIPLIER.get(ctx.passenger_type, 1.0)


# Ordered list of modifiers applied multiplicatively to the base fare.
# --- To add a new pricing dimension later, write one function shaped like
# the two above and append it here. Do not edit calculate_total_price. ---
PRICING_MODIFIERS: list[Callable[[FareContext], float]] = [
    _ticket_class_modifier,
    _passenger_type_modifier,
]


def _unit_fare(base_price_tl: float, ticket_class: str, passenger_type: str) -> float:
    ctx = FareContext(base_price_tl, ticket_class, passenger_type)
    multiplier = 1.0
    for modifier in PRICING_MODIFIERS:
        multiplier *= modifier(ctx)
    return base_price_tl * multiplier


def calculate_total_price(
    segments: list[dict],
    passengers: int,
    trip_type: str,
    *,
    detailed: bool = False,
    ticket_class: str = "Economy",
    passengers_breakdown: dict | None = None,
) -> int | dict:
    """
    Total price in TL. Round-trip uses outbound + inbound base prices.

    passengers_breakdown: {"Adult": n, "Child": n, "Baby": n}
    """
    if passengers_breakdown is None:
        passengers_breakdown = {"Adult": passengers, "Child": 0, "Baby": 0}

    def _leg_total(flight: dict) -> float:
        base = flight["base_price_tl"]
        return sum(
            _unit_fare(base, ticket_class, ptype) * count
            for ptype, count in passengers_breakdown.items()
        )

    subtotal = sum(_leg_total(leg) for leg in segments)

    if trip_type == "Round-trip" and len(segments) == 1:
        subtotal *= 2

    total_pax = sum(passengers_breakdown.values())

    if not detailed:
        return int(subtotal)

    tax = subtotal * TAX_RATE
    fees = PER_PASSENGER_FEE_TL * total_pax * (2 if trip_type == "Round-trip" else 1)
    return {
        "subtotal_tl": round(subtotal, 2),
        "tax_tl": round(tax, 2),
        "fees_tl": round(fees, 2),
        "total_tl": int(subtotal + tax + fees),
    }


# ---------------------------------------------------------------------------
# Ancillary pricing (seats, luggage, extras)
#
# These costs are *additive*, not multiplicative on the base fare, so they
# bypass PRICING_MODIFIERS and are computed independently.  The grand total
# at report time is: fare_total + ancillary_total.
# ---------------------------------------------------------------------------
def calculate_ancillary_total(
    seat_selections: list[dict] | None = None,
    luggage_selections: list[dict] | None = None,
    extras_selections: list[dict] | None = None,
) -> dict:
    """Compute add-on totals and return an itemized breakdown.

    Parameters
    ----------
    seat_selections:
        List of ``{"passenger_idx": int, "key": str, "price_tl": float, ...}``.
    luggage_selections:
        List of ``{"passenger_idx": int, "key": str, "price_tl": float, ...}``.
    extras_selections:
        List of ``{"service": str, "price_tl": float, ...}``.

    Returns
    -------
    dict
        ``seat_total_tl``, ``luggage_total_tl``, ``extras_total_tl``,
        and ``ancillary_total_tl`` (the sum of the three).
    """
    seat_total = sum(s.get("price_tl", 0) for s in (seat_selections or []))
    luggage_total = sum(l.get("price_tl", 0) for l in (luggage_selections or []))
    extras_total = sum(e.get("price_tl", 0) for e in (extras_selections or []))

    return {
        "seat_total_tl": round(seat_total, 2),
        "luggage_total_tl": round(luggage_total, 2),
        "extras_total_tl": round(extras_total, 2),
        "ancillary_total_tl": round(seat_total + luggage_total + extras_total, 2),
    }


# ---------------------------------------------------------------------------
# Self-check — verifies every stored booking's price still matches what
# calculate_total_price() produces today. Lives here (not in
# the db/ package) because it's a pricing self-test, not a flight-data
# self-test; it imports the flight/booking data it needs rather than the
# other way around, so there's no import cycle.
# ---------------------------------------------------------------------------
def self_test_booking_prices() -> list[str]:
    from db import db_list_bookings, get_flight_by_number, BookingStatus

    problems = []

    bookings = db_list_bookings()["bookings"]

    for b in bookings:
        if b["booking_status"] in (
            BookingStatus.FAILED.value,
            BookingStatus.WAITLISTED.value,
        ):
            continue

        outbound = get_flight_by_number(b["flight_number"])

        if not outbound:
            problems.append(
                f"booking {b['booking_id']}: flight_number {b['flight_number']} not found"
            )
            continue

        inbound = None
        segments = [outbound]

        if b["return_flight_number"]:
            inbound = get_flight_by_number(b["return_flight_number"])
            if inbound:
                segments.append(inbound)

        expected = calculate_total_price(
            segments,
            b["passenger_count"],
            b["trip_type"],
        )

        stored_total = b.get("total_price_tl")

        if stored_total is None:
            problems.append(
                f"booking {b['booking_id']}: total_price_tl is missing"
            )
            continue

        if expected != int(stored_total):
            problems.append(
                f"booking {b['booking_id']}: stored total_price_tl={stored_total} "
                f"but calculate_total_price(...) = {expected}"
            )

    return problems
