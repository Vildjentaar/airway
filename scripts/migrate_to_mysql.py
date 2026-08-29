#!/usr/bin/env python3
"""
Migrate mock data from:

- db.AIRPORTS
- db.FLIGHTS
- db.BOOKINGS
- accounts.USERS
- pricing constants

into MySQL.
"""

from __future__ import annotations

import hashlib
import os
from dotenv import load_dotenv
load_dotenv()

import re
import secrets
import sys
from pathlib import Path

# Make project root importable if this script is run from ./scripts
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import mysql.connector

from scripts.mock_data import AIRPORTS, FLIGHTS, BOOKINGS, USERS
import pricing


RESET = os.getenv("MIGRATION_RESET", "0") == "1"


def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "thall_app"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "thall_lines"),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=False,
    )


def clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def parse_duration_to_minutes(duration_text: str | None) -> int | None:
    """
    Convert '2h 05m' -> 125
    """
    if not duration_text:
        return None

    match = re.match(r"^(?P<hours>\d+)h\s*(?P<minutes>\d{1,2})m$", duration_text.strip())
    if not match:
        return None

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    return hours * 60 + minutes


def hash_password(password: str) -> str:
    """
    Simple PBKDF2 password hash for prototype use.

    For production, prefer bcrypt/argon2 via a dedicated library.
    """
    password = password or ""
    salt = secrets.token_hex(16)
    iterations = 600_000

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
        dklen=32,
    )

    return f"pbkdf2_sha256${iterations}${salt}${derived_key.hex()}"


def reset_tables(cursor) -> None:
    print("Resetting tables...")

    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

    tables = [
        "booking_passenger_counts",
        "booking_price_breakdowns",
        "booking_segments",
        "bookings",
        "flight_legs",
        "flights",
        "aircraft_models",
        "users",
        "pricing_config",
        "ticket_class_multipliers",
        "passenger_type_multipliers",
        "airports",
    ]

    for table in tables:
        cursor.execute(f"TRUNCATE TABLE {table}")

    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


def migrate_airports(cursor) -> None:
    print("Migrating airports...")

    sql = """
        INSERT INTO airports (
            code,
            city,
            country,
            timezone
        )
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            city = VALUES(city),
            country = VALUES(country),
            timezone = VALUES(timezone)
    """

    for code, info in AIRPORTS.items():
        cursor.execute(
            sql,
            (
                clean(code),
                clean(info["city"]),
                clean(info["country"]),
                clean(info["timezone"]),
            ),
        )


def migrate_aircraft_models(cursor) -> None:
    print("Migrating aircraft models...")

    aircraft_models: dict[str, int] = {}

    for flight in FLIGHTS:
        model = clean(flight.get("aircraft_type"))
        capacity = flight.get("max_capacity")

        if model and capacity is not None:
            aircraft_models[model] = int(capacity)

    sql = """
        INSERT INTO aircraft_models (
            model_name,
            default_capacity
        )
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            default_capacity = VALUES(default_capacity)
    """

    for model_name, capacity in aircraft_models.items():
        cursor.execute(sql, (model_name, capacity))


def migrate_flights(cursor) -> None:
    print("Migrating flights...")

    sql = """
        INSERT INTO flights (
            flight_id,
            flight_number,
            origin_code,
            dest_code,
            departure_time,
            arrival_time,
            arrival_date_offset,
            flight_minutes,
            total_minutes,
            duration_text,
            layover_minutes,
            connection_airport,
            transfer_status,
            base_price_tl,
            aircraft_model,
            max_capacity,
            is_leg
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            flight_number = VALUES(flight_number),
            origin_code = VALUES(origin_code),
            dest_code = VALUES(dest_code),
            departure_time = VALUES(departure_time),
            arrival_time = VALUES(arrival_time),
            arrival_date_offset = VALUES(arrival_date_offset),
            flight_minutes = VALUES(flight_minutes),
            total_minutes = VALUES(total_minutes),
            duration_text = VALUES(duration_text),
            layover_minutes = VALUES(layover_minutes),
            connection_airport = VALUES(connection_airport),
            transfer_status = VALUES(transfer_status),
            base_price_tl = VALUES(base_price_tl),
            aircraft_model = VALUES(aircraft_model),
            max_capacity = VALUES(max_capacity),
            is_leg = VALUES(is_leg)
    """

    for flight in FLIGHTS:
        transfer_status = flight["transfer_status"]
        if hasattr(transfer_status, "value"):
            transfer_status = transfer_status.value

        flight_minutes = flight.get("flight_minutes")
        duration_text = clean(flight.get("duration"))

        if transfer_status == "Direct":
            total_minutes = flight_minutes
        else:
            total_minutes = parse_duration_to_minutes(duration_text)

        cursor.execute(
            sql,
            (
                int(flight["flight_id"]),
                clean(flight["flight_number"]),
                clean(flight["origin_code"]),
                clean(flight["dest_code"]),
                clean(flight.get("departure_time")),
                clean(flight.get("arrival_time")),
                int(flight.get("arrival_date_offset", 0) or 0),
                int(flight_minutes) if flight_minutes is not None else None,
                int(total_minutes) if total_minutes is not None else None,
                duration_text,
                int(flight["layover_minutes"]) if flight.get("layover_minutes") is not None else None,
                clean(flight.get("connection_airport")),
                transfer_status,
                float(flight["base_price_tl"]),
                clean(flight.get("aircraft_type")),
                int(flight["max_capacity"]) if flight.get("max_capacity") is not None else None,
                1 if flight.get("is_leg") else 0,
            ),
        )


def migrate_flight_legs(cursor) -> None:
    print("Migrating flight legs...")

    sql = """
        INSERT INTO flight_legs (
            parent_flight_id,
            leg_flight_id,
            leg_order
        )
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            leg_flight_id = VALUES(leg_flight_id)
    """

    for flight in FLIGHTS:
        legs = flight.get("legs")

        if not legs:
            continue

        parent_flight_id = int(flight["flight_id"])

        for order, leg_flight_id in enumerate(legs, start=1):
            cursor.execute(
                sql,
                (
                    parent_flight_id,
                    int(leg_flight_id),
                    order,
                ),
            )


def migrate_users(cursor) -> None:
    print("Migrating users...")

    sql = """
        INSERT INTO users (
            user_id,
            email,
            password_hash,
            name,
            surname,
            birthdate,
            sex,
            nationality,
            tckn,
            mobile
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            email = VALUES(email),
            password_hash = VALUES(password_hash),
            name = VALUES(name),
            surname = VALUES(surname),
            birthdate = VALUES(birthdate),
            sex = VALUES(sex),
            nationality = VALUES(nationality),
            tckn = VALUES(tckn),
            mobile = VALUES(mobile)
    """

    for user in USERS:
        sex = clean(user.get("sex"))
        if sex and len(sex) > 1:
            sex = sex[0].upper()

        cursor.execute(
            sql,
            (
                int(user["user_id"]),
                clean(user["email"]),
                hash_password(user.get("password", "")),
                clean(user.get("name")) or "",
                clean(user.get("surname")) or "",
                clean(user.get("birthdate")),
                sex,
                clean(user.get("nationality")),
                clean(user.get("tckn")),
                clean(user.get("mobile")),
            ),
        )


def migrate_bookings(cursor) -> None:
    print("Migrating bookings...")

    flight_id_by_number = {
        clean(flight["flight_number"]): int(flight["flight_id"])
        for flight in FLIGHTS
    }

    booking_sql = """
        INSERT INTO bookings (
            booking_id,
            user_id,
            passenger_count,
            trip_type,
            ticket_class,
            total_price_tl,
            booking_status,
            notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            user_id = VALUES(user_id),
            passenger_count = VALUES(passenger_count),
            trip_type = VALUES(trip_type),
            ticket_class = VALUES(ticket_class),
            total_price_tl = VALUES(total_price_tl),
            booking_status = VALUES(booking_status),
            notes = VALUES(notes)
    """

    segment_sql = """
        INSERT INTO booking_segments (
            booking_id,
            segment_order,
            flight_id,
            departure_date
        )
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            flight_id = VALUES(flight_id),
            departure_date = VALUES(departure_date)
    """

    passenger_count_sql = """
        INSERT INTO booking_passenger_counts (
            booking_id,
            passenger_type,
            quantity
        )
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            quantity = VALUES(quantity)
    """

    for booking in BOOKINGS:
        booking_status = booking["booking_status"]
        if hasattr(booking_status, "value"):
            booking_status = booking_status.value

        total_price_tl = booking.get("total_price_tl")
        if total_price_tl is not None:
            total_price_tl = float(total_price_tl)

        cursor.execute(
            booking_sql,
            (
                int(booking["booking_id"]),
                None,  # user_id is not present in current mock bookings
                int(booking["passenger_count"]),
                clean(booking["trip_type"]),
                "Economy",  # current mock bookings do not store ticket class
                total_price_tl,
                booking_status,
                clean(booking.get("notes")),
            ),
        )

        for i, segment in enumerate(booking.get("segments", []), start=1):
            flight_number = clean(segment["flight_number"])
            flight_id = flight_id_by_number.get(flight_number)
            if flight_id is None:
                raise ValueError(f"Booking {booking['booking_id']} references unknown flight {flight_number}")
            
            cursor.execute(
                segment_sql,
                (
                    int(booking["booking_id"]),
                    i,
                    flight_id,
                    clean(segment["departure_date"]),
                )
            )

        # Current mock data only has total passenger_count.
        # Treat all existing passengers as Adult.
        cursor.execute(
            passenger_count_sql,
            (
                int(booking["booking_id"]),
                "Adult",
                int(booking["passenger_count"]),
            ),
        )


def migrate_pricing(cursor) -> None:
    print("Migrating pricing configuration...")

    config_sql = """
        INSERT INTO pricing_config (
            config_key,
            numeric_value,
            text_value
        )
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            numeric_value = VALUES(numeric_value),
            text_value = VALUES(text_value)
    """

    cursor.execute(
        config_sql,
        ("TAX_RATE", float(pricing.TAX_RATE), None),
    )

    cursor.execute(
        config_sql,
        ("PER_PASSENGER_FEE_TL", float(pricing.PER_PASSENGER_FEE_TL), None),
    )

    ticket_class_sql = """
        INSERT INTO ticket_class_multipliers (
            class_name,
            multiplier
        )
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            multiplier = VALUES(multiplier)
    """

    for class_name, multiplier in pricing.TICKET_CLASS_MULTIPLIER.items():
        cursor.execute(
            ticket_class_sql,
            (
                clean(class_name),
                float(multiplier),
            ),
        )

    passenger_type_sql = """
        INSERT INTO passenger_type_multipliers (
            passenger_type,
            multiplier
        )
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            multiplier = VALUES(multiplier)
    """

    for passenger_type, multiplier in pricing.PASSENGER_TYPE_MULTIPLIER.items():
        cursor.execute(
            passenger_type_sql,
            (
                clean(passenger_type),
                float(multiplier),
            ),
        )


def main() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if RESET:
            reset_tables(cursor)

        migrate_airports(cursor)
        migrate_aircraft_models(cursor)
        migrate_flights(cursor)
        migrate_flight_legs(cursor)
        migrate_users(cursor)
        migrate_bookings(cursor)
        migrate_pricing(cursor)

        conn.commit()
        print("Migration completed successfully.")

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
