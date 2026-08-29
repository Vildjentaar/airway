# Refactoring Plan: `thall_lines_db.py` → `db/` Package

## Current State

`thall_lines_db.py` is a **1059-line monolith** containing 6 distinct concerns:

| Section | Lines | Functions |
|---------|-------|-----------|
| Enums + shared helpers | 1–169 | `TransferStatus`, `BookingStatus`, `_time_to_str`, `_date_to_str`, `_flight_row_to_dict`, `_resolve_code` |
| Flight queries | 170–482 | `get_flight_by_number`, `search_flights`, `find_flight`, `db_find_alternative_routes`, `db_search_itinerary`, `_search_flights_by_codes` |
| Capacity checks | 483–536 | `db_check_capacity` |
| Route catalogue | 537–707 | `route_catalogue`, `db_list_all_routes`, `db_get_route_details` |
| Airport queries | 708–785 | `db_list_airports`, `db_get_airport_info` |
| Booking queries | 786–920 | `db_list_bookings`, `get_booking_details` |
| Ancillary catalogues | 921–1027 | `db_get_seat_types`, `db_get_luggage_tiers`, `db_get_extra_services` |
| Self-test helpers | 1028–1059 | `self_test_bidirectional_coverage` |

## Proposed Split

Rename the existing `database/` to keep `db.py` (connection layer) where it is, and create a new top-level package `db/` that replaces `thall_lines_db.py`:

> [!IMPORTANT]
> We can't use `database/` because it already exists with `db.py` (the MySQL connection helper). The new package will be called `db/` and will re-export everything via `__init__.py` so **zero external imports need to change** — consumers just switch `from thall_lines_db import X` → `from db import X` (or we keep a shim).

### Module breakdown:

```
db/
├── __init__.py          # Re-exports everything (backward compat shim)
├── models.py            # Enums: TransferStatus, BookingStatus, AIRLINE_NAME
├── _helpers.py          # _time_to_str, _date_to_str, _flight_row_to_dict, _resolve_code
├── flights.py           # Flight queries (search, find, itinerary, alternatives)
├── airports.py          # Airport queries (list, get_info)
├── bookings.py          # Booking queries (list, get_details) + capacity check
├── routes.py            # Route catalogue and route details
├── ancillary.py         # Seat types, luggage tiers, extra services
└── _self_tests.py       # self_test_bidirectional_coverage (dev-only)
```

### Backward Compatibility Strategy

**Option A — Shim file (zero-change for consumers):**
Keep `thall_lines_db.py` as a thin re-export file:
```python
"""Backward-compatible shim — real implementation is in db/ package."""
from db import *  # noqa: F401,F403
```
Every existing `from thall_lines_db import X` keeps working with no changes.

**Option B — Update all imports:**
Delete `thall_lines_db.py` and update all 10 consumer files to `from db import ...`.

> [!TIP]
> **Recommendation: Option A** — it's safer, takes 2 lines, and lets us split the logic without touching any other file. We can deprecate the shim later.

## Consumer Impact (Option A = zero changes needed)

| Consumer | Imports |
|----------|---------|
| `app.py` | `AIRLINE_NAME` |
| `system_prompt.py` | `AIRLINE_NAME` |
| `llm/schemas.py` | `AIRLINE_NAME` |
| `llm/flight_validation.py` | `find_flight`, `get_flight_by_number`, `AIRLINE_NAME` |
| `llm/tool_dispatch/dispatcher.py` | `import thall_lines_db` (module-level, 12 function refs) |
| `pricing.py` | `db_list_bookings`, `get_flight_by_number`, `BookingStatus` |
| `data/seat_data.py` | `db_get_seat_types` |
| `data/luggage_data.py` | `db_get_luggage_tiers` |
| `data/extras_data.py` | `db_get_extra_services` |
| `services/email_service.py` | `AIRLINE_NAME` |
| `scripts/self_tests.py` | `find_flight`, `db_check_capacity`, `route_catalogue`, `db_get_route_details`, `self_test_bidirectional_coverage` |

With **Option A**, none of these need changing.

## Execution Order

1. Create `db/` package directory
2. Create `db/models.py` — extract enums + `AIRLINE_NAME`
3. Create `db/_helpers.py` — extract internal helpers
4. Create `db/flights.py` — extract flight queries
5. Create `db/airports.py` — extract airport queries
6. Create `db/bookings.py` — extract booking + capacity queries
7. Create `db/routes.py` — extract route catalogue/details
8. Create `db/ancillary.py` — extract ancillary catalogues
9. Create `db/_self_tests.py` — extract self-test helper
10. Create `db/__init__.py` — re-export all public symbols
11. Replace `thall_lines_db.py` with backward-compat shim (Option A)
12. Smoke-test all imports

> [!NOTE]
> The internal `database/db.py` (connection helper with `fetch_one`, `fetch_all`) stays exactly where it is. The new `db/` package imports from `database.db` just like `thall_lines_db.py` does today.
