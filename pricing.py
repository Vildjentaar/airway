"""
pricing.py
----------
Fare calculation — split out of thall_lines_db.py because "how much does
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
    outbound: dict,
    passengers: int,
    trip_type: str,
    inbound: dict | None = None,
    *,
    detailed: bool = False,
    ticket_class: str = "Economy",
    passengers_breakdown: dict | None = None,
) -> int | dict:
    """
    Total price in TL. Round-trip uses outbound + inbound base prices.

    passengers_breakdown: {"Adult": n, "Child": n, "Baby": n}

    Public signature is unchanged from the original module on purpose —
    every existing caller (llm_engine.py, self-tests) keeps working. What
    changed is internal: the actual per-passenger fare math now runs
    through PRICING_MODIFIERS instead of being hardcoded inline, so this
    function's body doesn't need to change again when a new pricing
    dimension shows up.
    """
    if passengers_breakdown is None:
        passengers_breakdown = {"Adult": passengers, "Child": 0, "Baby": 0}

    def _leg_total(flight: dict) -> float:
        base = flight["base_price_tl"]
        return sum(
            _unit_fare(base, ticket_class, ptype) * count
            for ptype, count in passengers_breakdown.items()
        )

    subtotal = _leg_total(outbound)

    if trip_type == "Round-trip":
        if inbound:
            subtotal += _leg_total(inbound)
        else:
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
# Self-check — verifies every stored booking's price still matches what
# calculate_total_price() produces today. Lives here (not in
# thall_lines_db.py) because it's a pricing self-test, not a flight-data
# self-test; it imports the flight/booking data it needs rather than the
# other way around, so there's no import cycle.
# ---------------------------------------------------------------------------
def self_test_booking_prices() -> list[str]:
    from thall_lines_db import db_list_bookings, get_flight_by_number, BookingStatus

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

        if b["return_flight_number"]:
            inbound = get_flight_by_number(b["return_flight_number"])

        expected = calculate_total_price(
            outbound,
            b["passenger_count"],
            b["trip_type"],
            inbound,
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
