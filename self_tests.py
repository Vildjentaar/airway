"""
self_tests.py
-------------
Combined self-test / demo runner for the mock backend. Run directly:

    python self_tests.py

This replaces the old `if __name__ == "__main__":` block that used to
live at the bottom of thall_lines_db.py. It lives on its own now because
it exercises several modules (thall_lines_db, pricing, accounts, payment,
booking_context) — bottom-of-file demo code for a multi-module system
doesn't belong inside any one of those modules.
"""

import json

from thall_lines_db import (
    find_flight, db_check_capacity,
    route_catalogue, db_get_route_details, self_test_bidirectional_coverage,
)
from database.db import fetch_one
from pricing import calculate_total_price, self_test_booking_prices
from accounts import default_auth_provider, validate_tckn
from payment import default_payment_gateway

    flight_stats = fetch_one("SELECT COUNT(*) as total, SUM(CASE WHEN is_leg = 0 THEN 1 ELSE 0 END) as sellable, SUM(is_leg) as legs FROM flights")
    booking_stats = fetch_one("SELECT COUNT(*) as total FROM bookings")
    
    print(f"Loaded {flight_stats['total']} flight rows ({flight_stats['sellable']} sellable, "
          f"{flight_stats['legs']} legs) and {booking_stats['total']} bookings.\n")

    print("--- self-test: bidirectional route coverage ---------------------")
    issues = self_test_bidirectional_coverage()
    print("OK — every sellable route has a return leg." if not issues else "\n".join(issues))

    print("\n--- self-test: booking prices reconcile with calculate_total_price ---")
    issues = self_test_booking_prices()
    print("OK — every priced booking matches calculate_total_price()." if not issues else "\n".join(issues))

    print("\n--- find_flight sanity checks --------------------------------")
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
    print(json.dumps(db_get_route_details("ESB", "JFK"), indent=2, default=str))

    print("\n--- accounts.py: AuthProvider (DIP) sanity checks ---------------")
    print("login (correct pw): ", default_auth_provider.authenticate("ahmet@example.com", "password123"))
    print("login (wrong pw):   ", default_auth_provider.authenticate("ahmet@example.com", "wrong"))
    print("register (new user):", default_auth_provider.register(
        {"email": "test@example.com", "password": "x", "name": "Test", "surname": "User"}
    ))
    print("validate_tckn:      ", validate_tckn("10000000146"))

    print("\n--- payment.py: PaymentGateway (DIP) sanity checks ---------------")
    print("valid card:  ", default_payment_gateway.charge("4539 1488 0343 6467", "12/29", "123", "Ahmet Yilmaz"))
    print("bad luhn:    ", default_payment_gateway.charge("4539 1488 0343 6468", "12/29", "123", "Ahmet Yilmaz"))
    print("expired:     ", default_payment_gateway.charge("4539 1488 0343 6467", "01/20", "123", "Ahmet Yilmaz"))
