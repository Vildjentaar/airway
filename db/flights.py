"""
db.flights

Flight search, lookup, and itinerary-building queries.
"""

from __future__ import annotations

from database.db import fetch_all, fetch_one

from db._helpers import _flight_row_to_dict, _resolve_code


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


def db_find_alternative_routes(departure: str, arrival: str) -> dict:
    """
    Find alternative routes when a direct search fails.
    Returns destinations reachable from the departure airport,
    and origins that can reach the arrival airport.
    """
    origin_code = _resolve_code(departure)
    dest_code = _resolve_code(arrival)

    alternatives = {
        "reachable_from_departure": [],
        "reachable_to_arrival": []
    }

    if origin_code:
        rows_from = fetch_all(
            """
            SELECT DISTINCT a.code, a.city, a.country
            FROM flights f
            JOIN airports a ON f.dest_code = a.code
            WHERE f.origin_code = %s AND f.is_leg = 0
            ORDER BY a.city
            """,
            (origin_code,)
        )
        alternatives["reachable_from_departure"] = [
            f"{row['code']} - {row['city']}, {row['country']}" for row in rows_from
        ]

    if dest_code:
        rows_to = fetch_all(
            """
            SELECT DISTINCT a.code, a.city, a.country
            FROM flights f
            JOIN airports a ON f.origin_code = a.code
            WHERE f.dest_code = %s AND f.is_leg = 0
            ORDER BY a.city
            """,
            (dest_code,)
        )
        alternatives["reachable_to_arrival"] = [
            f"{row['code']} - {row['city']}, {row['country']}" for row in rows_to
        ]

    return alternatives


def _search_flights_by_codes(origin_code: str, dest_code: str) -> list[dict]:
    """
    Internal: search flights when both airport codes are already resolved.

    Skips the redundant ``_resolve_code()`` calls that ``search_flights()``
    does, saving 2 DB round-trips per invocation.
    """
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


# Maximum intermediate hubs to evaluate in one-stop connection search.
# Prevents pathological fan-out on dense networks.
_MAX_HUBS = 3


def db_search_itinerary(origin: str, destination: str) -> dict:
    """
    Search for complete itineraries between two cities, including connected
    routes through hub airports.

    Returns direct flights (if any) plus all one-stop connecting options
    that route through a common intermediate airport. Each option includes
    full flight details for every leg so the LLM never needs to guess.

    Performance notes
    ~~~~~~~~~~~~~~~~~
    * ``_resolve_code`` results are memoized for the duration of this call
      to avoid redundant airport-code lookups.
    * Leg queries use ``_search_flights_by_codes`` (already-resolved codes)
      and results are cached per hub to avoid re-fetching the same leg
      twice for different combinations.
    * Hub count is capped at ``_MAX_HUBS`` to prevent O(N×M) explosion on
      dense networks.
    """
    # ── Per-call memoization cache for _resolve_code ────────────────────
    _code_cache: dict[str, str | None] = {}

    def _resolve_cached(city_or_code: str) -> str | None:
        key = (city_or_code or "").strip().lower()
        if key not in _code_cache:
            _code_cache[key] = _resolve_code(city_or_code)
        return _code_cache[key]

    origin_code = _resolve_cached(origin)
    dest_code = _resolve_cached(destination)

    if not origin_code:
        return {"error": f"Origin airport '{origin}' not found in our network."}
    if not dest_code:
        return {"error": f"Destination airport '{destination}' not found in our network."}
    if origin_code == dest_code:
        return {"error": "Origin and destination cannot be the same."}

    # 1) Direct flights — use pre-resolved codes to skip 2 _resolve_code
    #    calls inside search_flights.
    direct_flights = _search_flights_by_codes(origin_code, dest_code)

    # 2) One-stop connections: find intermediate airports reachable from
    #    origin that also have onward service to destination.
    #    LIMIT _MAX_HUBS prevents runaway fan-out.
    connection_rows = fetch_all(
        """
        SELECT DISTINCT f1.dest_code AS hub_code
        FROM flights f1
        JOIN flights f2 ON f2.origin_code = f1.dest_code
        WHERE f1.origin_code = %s
          AND f2.dest_code = %s
          AND f1.is_leg = 0
          AND f2.is_leg = 0
          AND f1.dest_code != %s
          AND f1.dest_code != %s
        LIMIT %s
        """,
        (origin_code, dest_code, origin_code, dest_code, _MAX_HUBS),
    )

    # ── Per-hub leg cache ───────────────────────────────────────────────
    # Avoids re-querying the same (origin→hub) or (hub→dest) route if
    # multiple hubs share a common first or second leg.
    _leg_cache: dict[tuple[str, str], list[dict]] = {}

    def _cached_search(from_code: str, to_code: str) -> list[dict]:
        pair = (from_code, to_code)
        if pair not in _leg_cache:
            _leg_cache[pair] = _search_flights_by_codes(from_code, to_code)
        return _leg_cache[pair]

    connecting_options = []
    for conn_row in connection_rows:
        hub = conn_row["hub_code"]

        # All first-leg flights to the hub (cached)
        first_legs = _cached_search(origin_code, hub)
        # All second-leg flights from the hub (cached)
        second_legs = _cached_search(hub, dest_code)

        for leg1 in first_legs:
            for leg2 in second_legs:
                # Calculate layover in minutes
                # Parse arrival of leg1 and departure of leg2
                try:
                    arr_parts = leg1["arrival_time"].split(":")
                    dep_parts = leg2["departure_time"].split(":")
                    arr_minutes = int(arr_parts[0]) * 60 + int(arr_parts[1])
                    dep_minutes = int(dep_parts[0]) * 60 + int(dep_parts[1])

                    # Account for arrival date offset on leg1
                    arr_day_offset = leg1.get("arrival_date_offset", 0) or 0
                    layover = (dep_minutes - arr_minutes) + (0 - arr_day_offset) * 1440

                    # If layover is negative, the connection departs the next day
                    if layover < 0:
                        layover += 1440  # add 24h
                        next_day_departure = True
                    else:
                        next_day_departure = layover == 0 or False

                    # Minimum connection time: 60 minutes
                    if layover < 60:
                        # Skip connections with less than 1 hour layover
                        # (unless next-day, which always has enough time)
                        if not next_day_departure:
                            continue
                except (ValueError, AttributeError):
                    layover = None
                    next_day_departure = False

                connecting_options.append({
                    "connection_airport": hub,
                    "layover_minutes": layover,
                    "next_day_departure": next_day_departure,
                    "legs": [
                        {
                            "flight_number": leg1["flight_number"],
                            "origin_code": leg1["origin_code"],
                            "dest_code": leg1["dest_code"],
                            "departure_time": leg1["departure_time"],
                            "arrival_time": leg1["arrival_time"],
                            "arrival_date_offset": leg1.get("arrival_date_offset", 0),
                            "duration": leg1["duration"],
                            "base_price_tl": leg1["base_price_tl"],
                            "aircraft_type": leg1.get("aircraft_type"),
                        },
                        {
                            "flight_number": leg2["flight_number"],
                            "origin_code": leg2["origin_code"],
                            "dest_code": leg2["dest_code"],
                            "departure_time": leg2["departure_time"],
                            "arrival_time": leg2["arrival_time"],
                            "arrival_date_offset": leg2.get("arrival_date_offset", 0),
                            "duration": leg2["duration"],
                            "base_price_tl": leg2["base_price_tl"],
                            "aircraft_type": leg2.get("aircraft_type"),
                        },
                    ],
                    "combined_base_price_tl": leg1["base_price_tl"] + leg2["base_price_tl"],
                })

    # Sort connecting options by combined price, then by shortest layover
    connecting_options.sort(
        key=lambda x: (x["combined_base_price_tl"], x.get("layover_minutes") or 9999)
    )

    return {
        "origin": origin_code,
        "destination": dest_code,
        "direct_flights": direct_flights,
        "connecting_options": connecting_options,
        "total_options": len(direct_flights) + len(connecting_options),
    }
