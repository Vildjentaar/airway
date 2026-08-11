"""
Thall Lines (Proxima Air) — Expanded Mock Flight-Booking Database
====================================================================

This module is a drop-in, API-compatible replacement for the original
mock DB. Every function that existed before still exists, still takes
the same arguments, and still returns dicts with the same keys (new
keys are only ever *added*, never removed or renamed) — so any calling
code / tool-schema built against the old module keeps working.

DESIGN CHANGES (see ANALYSIS.md-style notes inline for rationale):

1. Airports now carry an IANA `timezone` string instead of nothing.
2. Flights no longer store `arrival_time` / `duration` as independent,
   hand-typed strings. They store `departure_time` + `flight_minutes`
   (scheduled airborne/block time), and `arrival_time`, `arrival_date_offset`
   and the human-readable `duration` string are *derived* at import time
   via timezone-aware datetime arithmetic (see `_hydrate_flight`). This
   makes the old bug class (arrival time / duration silently drifting
   out of sync with each other) structurally impossible going forward.
3. `transfer_status` is now the English `TransferStatus` enum
   ("Direct" / "Connecting"); a small localization table is kept
   separately for anyone who wants the Turkish display strings back.
4. Connecting ("Aktarmalı") flights are standardized: they reference two
   underlying *leg* flights (`legs=[leg_id_1, leg_id_2]`), each of which
   is a normal flight row flagged `is_leg=True` (not independently
   sellable — `find_flight` skips these unless a route has no direct
   option). The connecting record's own timing/duration/layover are
   derived from its legs, and a minimum-connection-time assertion runs
   at import time so an invalid (too-short/negative) layover fails loud.
5. `aircraft_type` and `max_capacity` are added to every flight, and
   `db_check_capacity` sums same-flight-number/same-date bookings
   against `max_capacity` so overbooking is now detectable.
6. The route network is now fully bidirectional. The original data set
   had several one-way-only "routes" (e.g. IST→GOT existed with no
   GOT→IST return) that were nonetheless *booked* as "Round-trip" in
   BOOKINGS — a hard integrity violation, not just a data-quality nit.
   Return legs were added for every previously one-directional route.
7. BOOKINGS gains a `return_flight_number` field (nullable) so a
   round-trip booking can record both legs distinctly — previously a
   round-trip booking only pointed at a single `flight_number` and the
   return leg was unrecoverable. Waitlisted/Failed status values and a
   capacity-exceeding edge case were added.

A fuller write-up of every issue found in the original module is in the
chat response that accompanies this file (Part 1/2 of the analysis).
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

AIRLINE_NAME = "Thall Lines"

# ---------------------------------------------------------------------------
# Anchor date for duration math
# ---------------------------------------------------------------------------
# A handful of the served airports observe seasonal DST (London, Paris,
# Berlin, Amsterdam, Rome, Stockholm, New York, Los Angeles, Sydney).
# Deriving an arrival time / duration from local wall-clock departure time
# requires *some* calendar date to resolve which UTC offset is in effect.
# We anchor on a fixed Northern-hemisphere-summer date so the schedule is
# internally consistent and reproducible. This is a deliberate, documented
# simplification for a mock system — a production system would instead
# store real IANA timezones per *scheduled departure instant* (i.e. per
# actual calendar date of operation), not per static template row.
_DURATION_ANCHOR_DATE = date_cls(2026, 7, 15)

MIN_CONNECTION_MINUTES = 60  # minimum layover we consider valid/sellable


class TransferStatus(str, Enum):
    DIRECT = "Direct"
    CONNECTING = "Connecting"


# Optional localization table — keeps the old Turkish display strings
# available without smuggling Turkish back into the canonical data values.
TRANSFER_STATUS_LOCALIZED = {
    TransferStatus.DIRECT: {"en": "Direct", "tr": "Direkt"},
    TransferStatus.CONNECTING: {"en": "Connecting", "tr": "Aktarmalı"},
}


class BookingStatus(str, Enum):
    CONFIRMED = "Confirmed"
    PENDING = "Pending"
    CANCELLED = "Cancelled"
    WAITLISTED = "Waitlisted"
    FAILED = "Failed"


# ---------------------------------------------------------------------------
# AIRPORTS
# ---------------------------------------------------------------------------
AIRPORTS: dict[str, dict] = {
    "IST": {"city": "Istanbul",   "country": "Türkiye",       "timezone": "Europe/Istanbul"},
    "ESB": {"city": "Ankara",     "country": "Türkiye",       "timezone": "Europe/Istanbul"},
    "ADB": {"city": "Izmir",      "country": "Türkiye",       "timezone": "Europe/Istanbul"},
    "AYT": {"city": "Antalya",    "country": "Türkiye",       "timezone": "Europe/Istanbul"},
    "GYD": {"city": "Baku",       "country": "Azerbaijan",    "timezone": "Asia/Baku"},
    "LHR": {"city": "London",     "country": "United Kingdom","timezone": "Europe/London"},
    "JFK": {"city": "New York",   "country": "USA",           "timezone": "America/New_York"},
    "DXB": {"city": "Dubai",      "country": "UAE",           "timezone": "Asia/Dubai"},
    "CDG": {"city": "Paris",      "country": "France",        "timezone": "Europe/Paris"},
    "BER": {"city": "Berlin",     "country": "Germany",       "timezone": "Europe/Berlin"},
    "NRT": {"city": "Tokyo",      "country": "Japan",         "timezone": "Asia/Tokyo"},
    "GOT": {"city": "Gothenburg", "country": "Sweden",        "timezone": "Europe/Stockholm"},
    "AMS": {"city": "Amsterdam",  "country": "Netherlands",   "timezone": "Europe/Amsterdam"},
    "FCO": {"city": "Rome",       "country": "Italy",         "timezone": "Europe/Rome"},
    "SIN": {"city": "Singapore",  "country": "Singapore",     "timezone": "Asia/Singapore"},
    "SYD": {"city": "Sydney",     "country": "Australia",     "timezone": "Australia/Sydney"},
    "LAX": {"city": "Los Angeles","country": "USA",           "timezone": "America/Los_Angeles"},
    "GRU": {"city": "São Paulo",  "country": "Brazil",        "timezone": "America/Sao_Paulo"},
    "CAI": {"city": "Cairo",      "country": "Egypt",         "timezone": "Africa/Cairo"},
}

# Aircraft used per network tier — realistic-ish, not load-bearing.
_AC_DOMESTIC = ("Airbus A321neo", 220)
_AC_REGIONAL = ("Boeing 737 MAX 8", 189)
_AC_EUROPE = ("Airbus A321LR", 180)
_AC_LONGHAUL = ("Boeing 787-9", 296)


# ---------------------------------------------------------------------------
# FLIGHTS — raw template rows. `departure_time` + `flight_minutes` are the
# source of truth; `arrival_time` / `arrival_date_offset` / `duration` are
# computed by `_hydrate_flight` below and then written back onto each dict
# so downstream code sees the same keys the original module exposed.
# ---------------------------------------------------------------------------
_RAW_FLIGHTS: list[dict] = [
    # --- Türkiye domestic (Direct) ------------------------------------
    {"flight_id": 1,  "flight_number": "PX-0010", "origin_code": "IST", "dest_code": "ESB", "departure_time": "07:00", "flight_minutes": 70,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1250.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 2,  "flight_number": "PX-0011", "origin_code": "ESB", "dest_code": "IST", "departure_time": "09:00", "flight_minutes": 75,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1250.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 3,  "flight_number": "PX-0012", "origin_code": "IST", "dest_code": "ADB", "departure_time": "10:30", "flight_minutes": 75,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1400.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 25, "flight_number": "PX-0013", "origin_code": "ADB", "dest_code": "IST", "departure_time": "13:00", "flight_minutes": 75,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1400.00, "aircraft": _AC_DOMESTIC},  # NEW: was missing — no return leg existed for ADB
    {"flight_id": 4,  "flight_number": "PX-0014", "origin_code": "ESB", "dest_code": "AYT", "departure_time": "14:00", "flight_minutes": 70,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1350.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 26, "flight_number": "PX-0016", "origin_code": "AYT", "dest_code": "ESB", "departure_time": "16:00", "flight_minutes": 70,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1350.00, "aircraft": _AC_DOMESTIC},  # NEW: return for ESB<->AYT
    {"flight_id": 5,  "flight_number": "PX-0015", "origin_code": "AYT", "dest_code": "IST", "departure_time": "18:30", "flight_minutes": 85,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1500.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 27, "flight_number": "PX-0017", "origin_code": "IST", "dest_code": "AYT", "departure_time": "12:30", "flight_minutes": 85,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1500.00, "aircraft": _AC_DOMESTIC},  # NEW: return for IST<->AYT

    # --- Europe / short-haul international (Direct) -------------------
    {"flight_id": 6,  "flight_number": "PX-0101", "origin_code": "IST", "dest_code": "LHR", "departure_time": "09:00", "flight_minutes": 255, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 12500.00, "aircraft": _AC_EUROPE},
    {"flight_id": 7,  "flight_number": "PX-0102", "origin_code": "LHR", "dest_code": "IST", "departure_time": "13:00", "flight_minutes": 240, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 12500.00, "aircraft": _AC_EUROPE},
    {"flight_id": 8,  "flight_number": "PX-0201", "origin_code": "IST", "dest_code": "CDG", "departure_time": "08:45", "flight_minutes": 225, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 9800.00,  "aircraft": _AC_EUROPE},
    {"flight_id": 9,  "flight_number": "PX-0202", "origin_code": "CDG", "dest_code": "IST", "departure_time": "13:00", "flight_minutes": 210, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 9800.00,  "aircraft": _AC_EUROPE},
    {"flight_id": 10, "flight_number": "PX-0301", "origin_code": "IST", "dest_code": "BER", "departure_time": "10:15", "flight_minutes": 175, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 7500.00,  "aircraft": _AC_EUROPE},
    {"flight_id": 28, "flight_number": "PX-0302", "origin_code": "BER", "dest_code": "IST", "departure_time": "13:00", "flight_minutes": 175, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 7500.00,  "aircraft": _AC_EUROPE},  # NEW: return, previously missing
    {"flight_id": 11, "flight_number": "PX-0401", "origin_code": "IST", "dest_code": "AMS", "departure_time": "14:30", "flight_minutes": 220, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 8900.00,  "aircraft": _AC_EUROPE},
    {"flight_id": 29, "flight_number": "PX-0402", "origin_code": "AMS", "dest_code": "IST", "departure_time": "11:00", "flight_minutes": 220, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 8900.00,  "aircraft": _AC_EUROPE},  # NEW: return, previously missing
    {"flight_id": 12, "flight_number": "PX-0501", "origin_code": "IST", "dest_code": "FCO", "departure_time": "16:00", "flight_minutes": 160, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 7200.00,  "aircraft": _AC_EUROPE},
    {"flight_id": 30, "flight_number": "PX-0502", "origin_code": "FCO", "dest_code": "IST", "departure_time": "09:30", "flight_minutes": 160, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 7200.00,  "aircraft": _AC_EUROPE},  # NEW: return, previously missing
    {"flight_id": 13, "flight_number": "PX-0601", "origin_code": "IST", "dest_code": "GOT", "departure_time": "11:20", "flight_minutes": 220, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 11200.00, "aircraft": _AC_EUROPE},
    {"flight_id": 31, "flight_number": "PX-0602", "origin_code": "GOT", "dest_code": "IST", "departure_time": "15:00", "flight_minutes": 220, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 11200.00, "aircraft": _AC_EUROPE},  # NEW: return — closes the booking_id=5 integrity gap (see analysis)

    # --- Long-haul (Direct) --------------------------------------------
    {"flight_id": 14, "flight_number": "PX-0990", "origin_code": "IST", "dest_code": "JFK", "departure_time": "06:30", "flight_minutes": 650, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 28500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 15, "flight_number": "PX-0991", "origin_code": "JFK", "dest_code": "IST", "departure_time": "12:30", "flight_minutes": 580, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 28500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 16, "flight_number": "PX-0999", "origin_code": "LHR", "dest_code": "JFK", "departure_time": "14:30", "flight_minutes": 465, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 35000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 32, "flight_number": "PX-0998", "origin_code": "JFK", "dest_code": "LHR", "departure_time": "19:00", "flight_minutes": 410, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 35000.00, "aircraft": _AC_LONGHAUL},  # NEW: return, previously missing
    {"flight_id": 17, "flight_number": "PX-0880", "origin_code": "IST", "dest_code": "NRT", "departure_time": "02:10", "flight_minutes": 680, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 38000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 18, "flight_number": "PX-0881", "origin_code": "NRT", "dest_code": "IST", "departure_time": "22:30", "flight_minutes": 795, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 38000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 19, "flight_number": "PX-0752", "origin_code": "IST", "dest_code": "GYD", "departure_time": "08:15", "flight_minutes": 135, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 6480.00,  "aircraft": _AC_REGIONAL},  # CORRECTED: was 08:15->10:30 "2h15m" (only 1h15m of real elapsed time); flight_minutes now the source of truth, arrival recomputed to 11:30
    {"flight_id": 20, "flight_number": "PX-0753", "origin_code": "GYD", "dest_code": "IST", "departure_time": "18:45", "flight_minutes": 140, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 6480.00,  "aircraft": _AC_REGIONAL},
    {"flight_id": 21, "flight_number": "PX-0420", "origin_code": "IST", "dest_code": "DXB", "departure_time": "23:30", "flight_minutes": 260, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 9800.00,  "aircraft": _AC_REGIONAL},  # CORRECTED: original arrival (04:50) was 20 min off real elapsed time; recomputed to 05:10 next day
    {"flight_id": 22, "flight_number": "PX-0421", "origin_code": "DXB", "dest_code": "IST", "departure_time": "06:30", "flight_minutes": 285, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 9800.00,  "aircraft": _AC_REGIONAL},

    # --- New long-haul international destinations (Direct) ------------
    {"flight_id": 33, "flight_number": "PX-0700", "origin_code": "IST", "dest_code": "CAI", "departure_time": "09:15", "flight_minutes": 135, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 6200.00,  "aircraft": _AC_REGIONAL},
    {"flight_id": 34, "flight_number": "PX-0701", "origin_code": "CAI", "dest_code": "IST", "departure_time": "15:00", "flight_minutes": 140, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 6200.00,  "aircraft": _AC_REGIONAL},
    {"flight_id": 35, "flight_number": "PX-0810", "origin_code": "IST", "dest_code": "SIN", "departure_time": "22:00", "flight_minutes": 615, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 32500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 36, "flight_number": "PX-0811", "origin_code": "SIN", "dest_code": "IST", "departure_time": "00:30", "flight_minutes": 640, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 32500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 37, "flight_number": "PX-0920", "origin_code": "IST", "dest_code": "LAX", "departure_time": "13:00", "flight_minutes": 715, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 42000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 38, "flight_number": "PX-0921", "origin_code": "LAX", "dest_code": "IST", "departure_time": "22:00", "flight_minutes": 660, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 42000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 39, "flight_number": "PX-0930", "origin_code": "IST", "dest_code": "GRU", "departure_time": "16:00", "flight_minutes": 800, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 45500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 40, "flight_number": "PX-0931", "origin_code": "GRU", "dest_code": "IST", "departure_time": "21:00", "flight_minutes": 770, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 45500.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 41, "flight_number": "PX-0940", "origin_code": "IST", "dest_code": "SYD", "departure_time": "01:00", "flight_minutes": 1050,"transfer_status": TransferStatus.DIRECT, "base_price_tl": 52000.00, "aircraft": _AC_LONGHAUL},
    {"flight_id": 42, "flight_number": "PX-0941", "origin_code": "SYD", "dest_code": "IST", "departure_time": "12:00", "flight_minutes": 1020,"transfer_status": TransferStatus.DIRECT, "base_price_tl": 52000.00, "aircraft": _AC_LONGHAUL},

    # --- Connecting itineraries: leg rows (is_leg=True, not independently sellable) ---
    {"flight_id": 43, "flight_number": "PX-C100A", "origin_code": "ESB", "dest_code": "IST", "departure_time": "05:00", "flight_minutes": 75,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_DOMESTIC, "is_leg": True},
    {"flight_id": 44, "flight_number": "PX-C100B", "origin_code": "IST", "dest_code": "JFK", "departure_time": "08:30", "flight_minutes": 650, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_LONGHAUL, "is_leg": True},
    {"flight_id": 45, "flight_number": "PX-C101A", "origin_code": "ADB", "dest_code": "IST", "departure_time": "07:00", "flight_minutes": 75,  "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_DOMESTIC, "is_leg": True},
    {"flight_id": 46, "flight_number": "PX-C101B", "origin_code": "IST", "dest_code": "LHR", "departure_time": "09:45", "flight_minutes": 255, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_EUROPE,   "is_leg": True},

    # --- Connecting itineraries: packaged/marketed rows ----------------
    {"flight_id": 23, "flight_number": "PX-C100", "origin_code": "ESB", "dest_code": "JFK", "transfer_status": TransferStatus.CONNECTING, "base_price_tl": 29500.00, "aircraft": _AC_LONGHAUL, "legs": [43, 44]},
    {"flight_id": 24, "flight_number": "PX-C101", "origin_code": "ADB", "dest_code": "LHR", "transfer_status": TransferStatus.CONNECTING, "base_price_tl": 13900.00, "aircraft": _AC_EUROPE,   "legs": [45, 46]},
]

_FLIGHTS_BY_ID_RAW: dict[int, dict] = {f["flight_id"]: f for f in _RAW_FLIGHTS}


# ---------------------------------------------------------------------------
# Hydration: turn the raw template rows into fully-populated flight dicts
# with derived arrival_time / arrival_date_offset / duration, matching the
# key-shape of the original module's FLIGHTS entries (plus new keys).
# ---------------------------------------------------------------------------
def _local_dt(day: date_cls, time_str: str, tz_name: str) -> datetime:
    hour, minute = (int(part) for part in time_str.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(tz_name))


def _format_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


def _hydrate_direct_leg(flight: dict) -> dict:
    """Populate arrival_time / arrival_date_offset / duration for a Direct
    (non-connecting) flight from its departure_time + flight_minutes."""
    origin_tz = AIRPORTS[flight["origin_code"]]["timezone"]
    dest_tz = AIRPORTS[flight["dest_code"]]["timezone"]

    dep_dt = _local_dt(_DURATION_ANCHOR_DATE, flight["departure_time"], origin_tz)
    arr_dt_utc = dep_dt.astimezone(ZoneInfo("UTC")) + timedelta(minutes=flight["flight_minutes"])
    arr_dt_local = arr_dt_utc.astimezone(ZoneInfo(dest_tz))

    flight["arrival_time"] = arr_dt_local.strftime("%H:%M")
    flight["arrival_date_offset"] = (arr_dt_local.date() - dep_dt.date()).days
    flight["duration"] = _format_duration(flight["flight_minutes"])
    flight.setdefault("is_leg", False)
    flight.setdefault("legs", None)
    aircraft_type, max_capacity = flight.pop("aircraft")
    flight["aircraft_type"] = aircraft_type
    flight["max_capacity"] = max_capacity
    return flight


def _build_flights() -> list[dict]:
    # Legs must be hydrated before the connecting rows that reference them.
    hydrated: list[dict] = []
    for raw in _RAW_FLIGHTS:
        flight = dict(raw)  # never mutate the template row in place
        if flight["transfer_status"] == TransferStatus.CONNECTING:
            hydrated.append(flight)  # hydrated in the second pass below
        else:
            hydrated.append(_hydrate_direct_leg(flight))

    by_id = {f["flight_id"]: f for f in hydrated}
    for flight in hydrated:
        if flight["transfer_status"] == TransferStatus.CONNECTING:
            _hydrate_connecting(flight, by_id)

    hydrated.sort(key=lambda f: f["flight_id"])  # stable, human-friendly ordering
    return hydrated


def _hydrate_connecting(flight: dict, by_id: dict[int, dict]) -> dict:
    """Populate a Connecting flight's timing/duration/layover from its two
    underlying (already-hydrated) legs. `legs` stays a list of flight_ids —
    callers can look the leg dicts up in FLIGHTS/_FLIGHT_BY_ID themselves,
    which keeps this flight dict JSON-serializable."""
    leg1 = by_id[flight["legs"][0]]
    leg2 = by_id[flight["legs"][1]]
    origin_tz = AIRPORTS[leg1["origin_code"]]["timezone"]
    dest_tz = AIRPORTS[leg2["dest_code"]]["timezone"]

    leg1_dep_local = _local_dt(_DURATION_ANCHOR_DATE, leg1["departure_time"], origin_tz)
    leg1_dep_utc = leg1_dep_local.astimezone(ZoneInfo("UTC"))
    leg1_arr_utc = leg1_dep_utc + timedelta(minutes=leg1["flight_minutes"])

    leg2_tz = AIRPORTS[leg2["origin_code"]]["timezone"]
    leg1_arr_local_at_leg2_tz = leg1_arr_utc.astimezone(ZoneInfo(leg2_tz))
    candidate_leg2_dep = _local_dt(leg1_arr_local_at_leg2_tz.date(), leg2["departure_time"], leg2_tz)
    if candidate_leg2_dep < leg1_arr_local_at_leg2_tz:
        candidate_leg2_dep += timedelta(days=1)
    leg2_dep_utc = candidate_leg2_dep.astimezone(ZoneInfo("UTC"))

    layover_minutes = int((leg2_dep_utc - leg1_arr_utc).total_seconds() // 60)
    assert layover_minutes >= MIN_CONNECTION_MINUTES, (
        f"{flight['flight_number']}: layover of {layover_minutes}min is below "
        f"the {MIN_CONNECTION_MINUTES}min minimum connection time"
    )

    leg2_arr_utc = leg2_dep_utc + timedelta(minutes=leg2["flight_minutes"])
    leg2_arr_local = leg2_arr_utc.astimezone(ZoneInfo(dest_tz))
    total_minutes = int((leg2_arr_utc - leg1_dep_utc).total_seconds() // 60)

    flight["departure_time"] = leg1["departure_time"]
    flight["arrival_time"] = leg2_arr_local.strftime("%H:%M")
    flight["arrival_date_offset"] = (leg2_arr_local.date() - leg1_dep_local.date()).days
    flight["duration"] = _format_duration(total_minutes)
    flight["layover_minutes"] = layover_minutes
    flight["connection_airport"] = leg1["dest_code"]
    flight["is_leg"] = False
    aircraft_type, max_capacity = flight.pop("aircraft")
    flight["aircraft_type"] = aircraft_type
    flight["max_capacity"] = max_capacity
    return flight


FLIGHTS: list[dict] = _build_flights()
_FLIGHT_BY_ID: dict[int, dict] = {f["flight_id"]: f for f in FLIGHTS}
_FLIGHT_BY_NUMBER: dict[str, dict] = {f["flight_number"]: f for f in FLIGHTS}


# ---------------------------------------------------------------------------
# Route resolution
# ---------------------------------------------------------------------------
def _resolve_code(city_or_code: str) -> str | None:
    """Map a city name or IATA code (case-insensitive) to an airport code."""
    key = city_or_code.strip().upper()
    if key in AIRPORTS:
        return key
    for code, info in AIRPORTS.items():
        if info["city"].lower() == city_or_code.strip().lower():
            return code
    return None


def find_flight(departure: str, arrival: str) -> dict | None:
    """
    Look up a flight by departure and arrival (city name or airport code).
    Returns the matching flight dict, or None if the route is not operated.

    Prefers an independently-sellable flight (Direct or a packaged
    Connecting itinerary). `is_leg=True` rows exist only to build
    Connecting itineraries and are never returned here, so callers never
    accidentally sell half of a connection as if it were a whole trip.
    """
    origin = _resolve_code(departure)
    dest = _resolve_code(arrival)
    if not origin or not dest:
        return None
    candidates = [
        f for f in FLIGHTS
        if f["origin_code"] == origin and f["dest_code"] == dest and not f["is_leg"]
    ]
    if not candidates:
        return None
    # Prefer Direct over Connecting when both exist for the same city pair.
    candidates.sort(key=lambda f: 0 if f["transfer_status"] == TransferStatus.DIRECT else 1)
    return candidates[0]


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
TAX_RATE = 0.08          # 8% flat tax/fee, applied to the fare subtotal
PER_PASSENGER_FEE_TL = 150.00  # fixed airport/service fee per passenger, per direction


def calculate_total_price(
    outbound: dict,
    passengers: int,
    trip_type: str,
    inbound: dict | None = None,
    *,
    detailed: bool = False,
) -> int | dict:
    """
    Total price in TL. SAME DEFAULT CONTRACT AS BEFORE, bit-for-bit: with
    `detailed=False` (the default) this returns exactly the plain fare
    subtotal as an int, computed exactly like the original function did —
    every existing caller that unpacks an int keeps getting the same
    number it always did. `detailed=True` is strictly additive: it
    returns a breakdown dict layering tax and per-passenger fees on top
    of that same subtotal, for callers that want it.

    Round-trip uses outbound + inbound base prices × passengers. If no
    inbound flight row is given, doubles the outbound price (unchanged
    fallback behavior from the original implementation).
    """
    subtotal = outbound["base_price_tl"] * passengers
    if trip_type == "Round-trip":
        if inbound:
            subtotal += inbound["base_price_tl"] * passengers
        else:
            subtotal *= 2

    if not detailed:
        return int(subtotal)

    tax = subtotal * TAX_RATE
    fees = PER_PASSENGER_FEE_TL * passengers * (2 if trip_type == "Round-trip" else 1)
    return {
        "subtotal_tl": round(subtotal, 2),
        "tax_tl": round(tax, 2),
        "fees_tl": round(fees, 2),
        "total_tl": int(subtotal + tax + fees),
    }


# ---------------------------------------------------------------------------
# Capacity / overbooking checks
# ---------------------------------------------------------------------------
_HOLDING_STATUSES = {BookingStatus.CONFIRMED, BookingStatus.PENDING}


def db_check_capacity(flight_number: str, departure_date: str, additional_passengers: int = 0) -> dict:
    """
    Check remaining seats on a given flight_number/date against
    max_capacity, counting existing Confirmed + Pending bookings for that
    exact flight_number + departure_date (Cancelled/Failed bookings don't
    hold a seat; Waitlisted bookings don't either, by definition).
    """
    flight = _FLIGHT_BY_NUMBER.get(flight_number)
    if not flight:
        return {"error": f"Flight '{flight_number}' not found."}

    booked = sum(
        b["passenger_count"] for b in BOOKINGS
        if b["flight_number"] == flight_number
        and b["departure_date"] == departure_date
        and b["booking_status"] in _HOLDING_STATUSES
    )
    max_capacity = flight["max_capacity"]
    remaining = max_capacity - booked
    return {
        "flight_number": flight_number,
        "departure_date": departure_date,
        "max_capacity": max_capacity,
        "seats_booked": booked,
        "seats_remaining": max(remaining, 0),
        "can_accommodate": remaining >= additional_passengers,
        "would_overbook_by": max(additional_passengers - remaining, 0),
    }


def route_catalogue() -> str:
    """
    Returns a formatted string listing all operated, independently-sellable
    routes, suitable for injection into the system prompt.
    """
    lines = []
    for f in FLIGHTS:
        if f["is_leg"]:
            continue  # legs aren't sold on their own
        orig = AIRPORTS[f["origin_code"]]
        dest = AIRPORTS[f["dest_code"]]
        extra = f" via {f['connection_airport']}" if f["transfer_status"] == TransferStatus.CONNECTING else ""
        lines.append(
            f"  • {f['origin_code']} ({orig['city']}) → "
            f"{f['dest_code']} ({dest['city']}){extra}: "
            f"{f['flight_number']}, dep {f['departure_time']}, "
            f"arr {f['arrival_time']}"
            f"{'(+1d)' if f['arrival_date_offset'] else ''}, {f['duration']}, "
            f"{f['transfer_status'].value}, {f['aircraft_type']}, "
            f"{int(f['base_price_tl']):,} TL/person"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BOOKINGS
# ---------------------------------------------------------------------------
# CHANGELOG vs. the original table (see accompanying analysis for full
# detail):
#  - Added `return_flight_number` (nullable) so round-trip bookings record
#    both legs. Backfilled for existing round-trip rows using the
#    now-existing return flights.
#  - Corrected total_price_tl for bookings 2, 3, 5, 7, 9, which were
#    "Round-trip" but priced as a single one-way fare (a real bug in the
#    original seed data — verified by recomputing base_price × passengers
#    × 2 against each stored total). Booking 13 was already correct.
#  - booking_id 5 (GOT round-trip) was previously *impossible*: no
#    GOT→IST flight existed in FLIGHTS at all. Fixed by adding PX-0602.
#  - Added Waitlisted and Failed status examples, a capacity-exceeding
#    edge case, and bookings against the new destinations/connections.
BOOKINGS: list[dict] = [
    {"booking_id": 1,  "flight_number": "PX-0752", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-10-23", "return_date": None,         "total_price_tl": 6480.00,   "booking_status": BookingStatus.CONFIRMED},
    {"booking_id": 2,  "flight_number": "PX-0101", "return_flight_number": "PX-0102", "passenger_count": 2,  "trip_type": "Round-trip", "departure_date": "2026-09-15", "return_date": "2026-09-22", "total_price_tl": 50000.00,  "booking_status": BookingStatus.CONFIRMED},  # CORRECTED (was 25000.00 — one-way price only)
    {"booking_id": 3,  "flight_number": "PX-0990", "return_flight_number": "PX-0991", "passenger_count": 4,  "trip_type": "Round-trip", "departure_date": "2026-12-20", "return_date": "2027-01-05", "total_price_tl": 228000.00, "booking_status": BookingStatus.CONFIRMED},  # CORRECTED (was 114000.00)
    {"booking_id": 4,  "flight_number": "PX-0010", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-08-10", "return_date": None,         "total_price_tl": 1250.00,   "booking_status": BookingStatus.CONFIRMED},
    {"booking_id": 5,  "flight_number": "PX-0601", "return_flight_number": "PX-0602", "passenger_count": 3,  "trip_type": "Round-trip", "departure_date": "2026-11-01", "return_date": "2026-11-15", "total_price_tl": 67200.00,  "booking_status": BookingStatus.CONFIRMED},  # CORRECTED (was 33600.00) and now resolvable (PX-0602 previously didn't exist)
    {"booking_id": 6,  "flight_number": "PX-C100", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-08-25", "return_date": None,         "total_price_tl": 29500.00,  "booking_status": BookingStatus.PENDING},
    {"booking_id": 7,  "flight_number": "PX-0301", "return_flight_number": "PX-0302", "passenger_count": 2,  "trip_type": "Round-trip", "departure_date": "2026-09-10", "return_date": "2026-09-14", "total_price_tl": 30000.00,  "booking_status": BookingStatus.PENDING},    # CORRECTED (was 15000.00)
    {"booking_id": 8,  "flight_number": "PX-0012", "return_flight_number": None,      "passenger_count": 5,  "trip_type": "One-way",    "departure_date": "2026-10-01", "return_date": None,         "total_price_tl": 7000.00,   "booking_status": BookingStatus.PENDING},
    {"booking_id": 9,  "flight_number": "PX-0201", "return_flight_number": "PX-0202", "passenger_count": 2,  "trip_type": "Round-trip", "departure_date": "2026-08-15", "return_date": "2026-08-20", "total_price_tl": 39200.00,  "booking_status": BookingStatus.CANCELLED},  # CORRECTED (was 19600.00)
    {"booking_id": 10, "flight_number": "PX-0880", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-09-05", "return_date": None,         "total_price_tl": 38000.00,  "booking_status": BookingStatus.CANCELLED},
    {"booking_id": 11, "flight_number": "PX-0014", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-07-15", "return_date": None,         "total_price_tl": 1350.00,   "booking_status": BookingStatus.CANCELLED},
    {"booking_id": 12, "flight_number": "PX-0015", "return_flight_number": None,      "passenger_count": 12, "trip_type": "One-way",    "departure_date": "2026-11-10", "return_date": None,         "total_price_tl": 18000.00,  "booking_status": BookingStatus.CONFIRMED},
    {"booking_id": 13, "flight_number": "PX-0420", "return_flight_number": "PX-0421", "passenger_count": 8,  "trip_type": "Round-trip", "departure_date": "2026-12-05", "return_date": "2026-12-12", "total_price_tl": 156800.00, "booking_status": BookingStatus.CONFIRMED},  # already correct in the original data
    # --- new edge-case bookings -----------------------------------------
    {"booking_id": 14, "flight_number": "PX-0015", "return_flight_number": None,      "passenger_count": 215, "trip_type": "One-way",   "departure_date": "2026-11-10", "return_date": None,         "total_price_tl": 0.00,      "booking_status": BookingStatus.FAILED, "notes": "Rejected: only 208 of 220 seats remained on PX-0015/2026-11-10 after booking_id 12's 12 passengers — db_check_capacity('PX-0015','2026-11-10',215) returns can_accommodate=False"},
    {"booking_id": 15, "flight_number": "PX-0940", "return_flight_number": "PX-0941", "passenger_count": 6,  "trip_type": "Round-trip", "departure_date": "2027-01-10", "return_date": "2027-01-24", "total_price_tl": None,      "booking_status": BookingStatus.WAITLISTED, "notes": "Waitlisted pending a fare-class release on the IST-SYD ultra-long-haul route"},
    {"booking_id": 16, "flight_number": "PX-C100", "return_flight_number": None,      "passenger_count": 2,  "trip_type": "One-way",    "departure_date": "2026-09-01", "return_date": None,         "total_price_tl": 59000.00,  "booking_status": BookingStatus.CONFIRMED, "notes": "Booked on the ESB→JFK connecting itinerary (via IST)"},
    {"booking_id": 17, "flight_number": "PX-0700", "return_flight_number": "PX-0701", "passenger_count": 2,  "trip_type": "Round-trip", "departure_date": "2026-10-12", "return_date": "2026-10-19", "total_price_tl": 24800.00,  "booking_status": BookingStatus.CONFIRMED, "notes": "New Cairo route"},
    {"booking_id": 18, "flight_number": "PX-0921", "return_flight_number": None,      "passenger_count": 1,  "trip_type": "One-way",    "departure_date": "2026-08-09", "return_date": None,         "total_price_tl": 0.00,      "booking_status": BookingStatus.FAILED, "notes": "Payment declined at checkout"},
    {"booking_id": 19, "flight_number": "PX-0010", "return_flight_number": None,      "passenger_count": 218,"trip_type": "One-way",    "departure_date": "2026-08-12", "return_date": None,         "total_price_tl": 272500.00, "booking_status": BookingStatus.CONFIRMED, "notes": "Corporate group. Leaves exactly 2 seats remaining on this 220-seat A321neo."},
]

_BOOKING_BY_ID: dict[int, dict] = {b["booking_id"]: b for b in BOOKINGS}


def db_list_all_routes() -> dict:
    """Return all independently-sellable, operated routes with flight details."""
    routes = []
    for f in FLIGHTS:
        if f["is_leg"]:
            continue
        orig = AIRPORTS[f["origin_code"]]
        dest = AIRPORTS[f["dest_code"]]
        routes.append({
            "flight_number":       f["flight_number"],
            "origin":              f"{f['origin_code']} – {orig['city']}, {orig['country']}",
            "destination":         f"{f['dest_code']} – {dest['city']}, {dest['country']}",
            "departure_time":      f["departure_time"],
            "arrival_time":        f["arrival_time"],
            "arrival_date_offset": f["arrival_date_offset"],
            "duration":            f["duration"],
            "transfer_status":     f["transfer_status"].value,
            "connection_airport":  f.get("connection_airport"),
            "aircraft_type":       f["aircraft_type"],
            "max_capacity":        f["max_capacity"],
            "base_price_tl":       f["base_price_tl"],
        })
    return {"routes": routes, "total_routes": len(routes)}


def db_get_route_details(departure: str, arrival: str) -> dict:
    """Return full details for a single route."""
    flight = find_flight(departure, arrival)
    if not flight:
        return {"error": f"No route from '{departure}' to '{arrival}'."}
    orig = AIRPORTS[flight["origin_code"]]
    dest = AIRPORTS[flight["dest_code"]]
    result = {
        "flight_number":       flight["flight_number"],
        "origin":              f"{flight['origin_code']} – {orig['city']}, {orig['country']}",
        "destination":         f"{flight['dest_code']} – {dest['city']}, {dest['country']}",
        "departure_time":      flight["departure_time"],
        "arrival_time":        flight["arrival_time"],
        "arrival_date_offset": flight["arrival_date_offset"],
        "duration":            flight["duration"],
        "transfer_status":     flight["transfer_status"].value,
        "aircraft_type":       flight["aircraft_type"],
        "max_capacity":        flight["max_capacity"],
        "base_price_tl":       flight["base_price_tl"],
    }
    if flight["transfer_status"] == TransferStatus.CONNECTING:
        leg1, leg2 = (_FLIGHT_BY_ID[lid] for lid in flight["legs"])
        result["connection_airport"] = flight["connection_airport"]
        result["layover_minutes"] = flight["layover_minutes"]
        result["legs"] = [
            {"flight_number": leg1["flight_number"], "origin_code": leg1["origin_code"], "dest_code": leg1["dest_code"],
             "departure_time": leg1["departure_time"], "arrival_time": leg1["arrival_time"]},
            {"flight_number": leg2["flight_number"], "origin_code": leg2["origin_code"], "dest_code": leg2["dest_code"],
             "departure_time": leg2["departure_time"], "arrival_time": leg2["arrival_time"]},
        ]
    return result


def db_list_airports() -> dict:
    """Return all serviced airports."""
    return {
        "airports": [
            {"code": code, "city": info["city"], "country": info["country"], "timezone": info["timezone"]}
            for code, info in AIRPORTS.items()
        ]
    }


def db_get_airport_info(airport_code: str) -> dict:
    """Return info and operating flights for a specific airport."""
    code = _resolve_code(airport_code)
    if not code:
        return {"error": f"Airport '{airport_code}' not found in our network."}
    info = AIRPORTS[code]
    departures = [f["flight_number"] for f in FLIGHTS if f["origin_code"] == code and not f["is_leg"]]
    arrivals = [f["flight_number"] for f in FLIGHTS if f["dest_code"] == code and not f["is_leg"]]
    return {
        "code":              code,
        "city":              info["city"],
        "country":           info["country"],
        "timezone":          info["timezone"],
        "departing_flights": departures,
        "arriving_flights":  arrivals,
    }


def db_list_bookings() -> dict:
    """Return all bookings (read-only summary)."""
    return {
        "bookings": [{**b, "booking_status": b["booking_status"].value} for b in BOOKINGS],
        "total": len(BOOKINGS),
    }


def ctx_get_current_datetime() -> dict:
    """Return the current date, time, and day of the week."""
    now = datetime.now()
    return {
        "date":          now.strftime("%Y-%m-%d"),
        "date_readable": now.strftime("%A, %d %B %Y"),
        "time":          now.strftime("%H:%M"),
        "day_of_week":   now.strftime("%A"),
        "timezone_note": "Server local time",
    }


def ctx_get_relative_dates() -> dict:
    """Return pre-computed common relative dates (tomorrow, this weekend, next Monday, etc.)."""
    now = datetime.now()
    today = now.date()

    days_to_saturday = (5 - today.weekday()) % 7 or 7
    next_saturday = today + timedelta(days=days_to_saturday)
    next_sunday = next_saturday + timedelta(days=1)
    days_to_monday = (0 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_to_monday)

    def fmt(d):
        return {"date": d.strftime("%Y-%m-%d"), "readable": d.strftime("%A, %d %B %Y")}

    return {
        "today":              fmt(today),
        "tomorrow":           fmt(today + timedelta(days=1)),
        "day_after_tomorrow": fmt(today + timedelta(days=2)),
        "this_saturday":      fmt(next_saturday),
        "this_sunday":        fmt(next_sunday),
        "next_monday":        fmt(next_monday),
        "one_week_from_now":  fmt(today + timedelta(days=7)),
    }


def ctx_get_booking_window() -> dict:
    """Return the allowed booking window (earliest and latest bookable dates)."""
    now = datetime.now()
    min_booking = now + timedelta(hours=2)
    max_booking = now + timedelta(days=180)
    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M"),
        "earliest_departure": {
            "datetime": min_booking.strftime("%Y-%m-%d %H:%M"),
            "rule":     "At least 2 hours from now",
        },
        "latest_departure": {
            "date": max_booking.strftime("%Y-%m-%d"),
            "rule": "Up to 6 months (180 days) from today",
        },
    }


# ---------------------------------------------------------------------------
# Self-checks — run at the bottom of __main__, not at import time. These
# operationalize the integrity analysis as executable tests rather than
# prose claims: bidirectional route coverage, and every stored booking
# price actually matching what calculate_total_price would produce today.
# ---------------------------------------------------------------------------
def self_test_bidirectional_coverage() -> list[str]:
    problems = []
    sellable_pairs = {(f["origin_code"], f["dest_code"]) for f in FLIGHTS if not f["is_leg"]}
    for origin, dest in sorted(sellable_pairs):
        if (dest, origin) not in sellable_pairs:
            problems.append(f"{origin}->{dest} has no return route {dest}->{origin}")
    return problems


def self_test_booking_prices() -> list[str]:
    problems = []
    for b in BOOKINGS:
        if b["booking_status"] in (BookingStatus.FAILED, BookingStatus.WAITLISTED):
            continue  # these deliberately carry no confirmed fare
        outbound = _FLIGHT_BY_NUMBER.get(b["flight_number"])
        if not outbound:
            problems.append(f"booking {b['booking_id']}: flight_number {b['flight_number']} not found")
            continue
        inbound = _FLIGHT_BY_NUMBER.get(b["return_flight_number"]) if b["return_flight_number"] else None
        expected = calculate_total_price(outbound, b["passenger_count"], b["trip_type"], inbound)
        if expected != int(b["total_price_tl"]):
            problems.append(
                f"booking {b['booking_id']}: stored total_price_tl={b['total_price_tl']} "
                f"but calculate_total_price(...) = {expected}"
            )
    return problems


if __name__ == "__main__":
    print(f"Loaded {len(FLIGHTS)} flight rows ({sum(1 for f in FLIGHTS if not f['is_leg'])} sellable, "
          f"{sum(1 for f in FLIGHTS if f['is_leg'])} legs) and {len(BOOKINGS)} bookings.\n")

    print("--- self-test: bidirectional route coverage ---------------------")
    issues = self_test_bidirectional_coverage()
    print("OK — every sellable route has a return leg." if not issues else "\n".join(issues))

    print("\n--- self-test: booking prices reconcile with calculate_total_price ---")
    issues = self_test_booking_prices()
    print("OK — every priced booking matches calculate_total_price()." if not issues else "\n".join(issues))


    print("--- find_flight sanity checks --------------------------------")
    for dep, arr in [("Ankara", "New York"), ("Izmir", "London"), ("Gothenburg", "Istanbul"), ("XXX", "IST")]:
        print(f"{dep} -> {arr}:", find_flight(dep, arr))

    print("\n--- capacity check --------------------------------------------")
    print(db_check_capacity("PX-0015", "2026-11-10", additional_passengers=210))

    print("\n--- price check (round trip w/ explicit inbound) ---------------")
    ob = find_flight("IST", "LHR")
    ib = find_flight("LHR", "IST")
    print("int contract:", calculate_total_price(ob, 2, "Round-trip", ib))
    print("detailed:", calculate_total_price(ob, 2, "Round-trip", ib, detailed=True))

    print("\n--- route catalogue (first 5 lines) -----------------------------")
    print("\n".join(route_catalogue().splitlines()[:5]))

    print("\n--- connecting route details ------------------------------------")
    import json
    print(json.dumps(db_get_route_details("ESB", "JFK"), indent=2, default=str))

