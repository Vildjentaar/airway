"""
db

SQL-backed flight and booking repository, split by concern.

This package replaces the old ``the db/ package`` monolith. Consumers
import directly from here, e.g.:

    from db import AIRLINE_NAME, find_flight, BookingStatus

Design rules (unchanged from the db/ package):
- No raw SQL is exposed to the LLM.
- No dynamic SQL is built from LLM input.
- All queries are hardcoded and parameterized.
- Only explicit repository functions are callable by tools.
"""

from db.models import (
    AIRLINE_NAME,
    TRANSFER_STATUS_LOCALIZED,
    BookingStatus,
    TransferStatus,
)
from db.flights import (
    db_find_alternative_routes,
    db_search_itinerary,
    find_flight,
    get_flight_by_number,
    search_flights,
)
from db.airports import (
    db_get_airport_info,
    db_list_airports,
)
from db.bookings import (
    db_check_capacity,
    db_list_bookings,
    get_booking_details,
)
from db.routes import (
    db_get_route_details,
    db_list_all_routes,
    route_catalogue,
)
from db.ancillary import (
    db_get_extra_services,
    db_get_luggage_tiers,
    db_get_seat_types,
)

__all__ = [
    "AIRLINE_NAME",
    "TRANSFER_STATUS_LOCALIZED",
    "BookingStatus",
    "TransferStatus",
    "db_find_alternative_routes",
    "db_search_itinerary",
    "find_flight",
    "get_flight_by_number",
    "search_flights",
    "db_get_airport_info",
    "db_list_airports",
    "db_check_capacity",
    "db_list_bookings",
    "get_booking_details",
    "db_get_route_details",
    "db_list_all_routes",
    "route_catalogue",
    "db_get_extra_services",
    "db_get_luggage_tiers",
    "db_get_seat_types",
]
