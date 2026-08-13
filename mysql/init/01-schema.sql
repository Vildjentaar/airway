CREATE DATABASE IF NOT EXISTS thall_lines
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE thall_lines;

SET FOREIGN_KEY_CHECKS = 0;

DROP VIEW IF EXISTS v_sellable_routes;

DROP TABLE IF EXISTS booking_passenger_counts;
DROP TABLE IF EXISTS booking_price_breakdowns;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS flight_legs;
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS aircraft_models;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS pricing_config;
DROP TABLE IF EXISTS ticket_class_multipliers;
DROP TABLE IF EXISTS passenger_type_multipliers;
DROP TABLE IF EXISTS airports;

SET FOREIGN_KEY_CHECKS = 1;

-- ------------------------------------------------------------
-- Airports
-- ------------------------------------------------------------
CREATE TABLE airports (
    code CHAR(3) NOT NULL,
    city VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    timezone VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (code)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Aircraft models
-- ------------------------------------------------------------
CREATE TABLE aircraft_models (
    model_name VARCHAR(100) NOT NULL,
    default_capacity INT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (model_name)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Flights
--
-- Direct flights:
--   flight_minutes is the source of truth.
--
-- Connecting itineraries:
--   total_minutes is derived from the legs.
--   legs are stored in flight_legs.
-- ------------------------------------------------------------
CREATE TABLE flights (
    flight_id INT UNSIGNED NOT NULL,
    flight_number VARCHAR(20) NOT NULL,

    origin_code CHAR(3) NOT NULL,
    dest_code CHAR(3) NOT NULL,

    departure_time TIME NULL,
    arrival_time TIME NULL,
    arrival_date_offset SMALLINT NOT NULL DEFAULT 0,

    flight_minutes SMALLINT UNSIGNED NULL
        COMMENT 'Used for direct flights/legs.',
    total_minutes SMALLINT UNSIGNED NULL
        COMMENT 'Total itinerary duration. Useful for connecting flights.',

    duration_text VARCHAR(20) NULL,
    layover_minutes SMALLINT UNSIGNED NULL,
    connection_airport CHAR(3) NULL,

    transfer_status ENUM('Direct', 'Connecting') NOT NULL,
    base_price_tl DECIMAL(12, 2) NOT NULL DEFAULT 0,

    aircraft_model VARCHAR(100) NULL,
    max_capacity INT UNSIGNED NULL,

    is_leg TINYINT(1) NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (flight_id),
    UNIQUE KEY uq_flights_flight_number (flight_number),
    KEY idx_flights_route (origin_code, dest_code),
    KEY idx_flights_transfer_status (transfer_status),

    CONSTRAINT fk_flights_origin
        FOREIGN KEY (origin_code)
        REFERENCES airports (code),

    CONSTRAINT fk_flights_destination
        FOREIGN KEY (dest_code)
        REFERENCES airports (code),

    CONSTRAINT fk_flights_aircraft_model
        FOREIGN KEY (aircraft_model)
        REFERENCES aircraft_models (model_name),

    CONSTRAINT chk_flights_direct_requires_minutes
        CHECK (
            transfer_status <> 'Direct'
            OR flight_minutes IS NOT NULL
        ),

    CONSTRAINT chk_flights_connecting_requires_total_minutes
        CHECK (
            transfer_status <> 'Connecting'
            OR total_minutes IS NOT NULL
        )
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Flight legs for connecting itineraries
-- ------------------------------------------------------------
CREATE TABLE flight_legs (
    parent_flight_id INT UNSIGNED NOT NULL,
    leg_flight_id INT UNSIGNED NOT NULL,
    leg_order TINYINT UNSIGNED NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (parent_flight_id, leg_order),
    UNIQUE KEY uq_flight_legs_parent_leg (parent_flight_id, leg_flight_id),
    KEY idx_flight_legs_leg (leg_flight_id),

    CONSTRAINT fk_flight_legs_parent
        FOREIGN KEY (parent_flight_id)
        REFERENCES flights (flight_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_flight_legs_leg
        FOREIGN KEY (leg_flight_id)
        REFERENCES flights (flight_id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_flight_legs_order
        CHECK (leg_order IN (1, 2))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Users / accounts
--
-- Important:
-- Do not store plaintext passwords in a real system.
-- Store password_hash instead.
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,

    name VARCHAR(100) NOT NULL DEFAULT '',
    surname VARCHAR(100) NOT NULL DEFAULT '',
    birthdate DATE NULL,
    sex CHAR(1) NULL,
    nationality VARCHAR(10) NULL,
    tckn CHAR(11) NULL,
    mobile VARCHAR(30) NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id),
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_tckn (tckn)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Bookings
-- ------------------------------------------------------------
CREATE TABLE bookings (
    booking_id INT UNSIGNED NOT NULL,
    user_id INT UNSIGNED NULL,

    flight_id INT UNSIGNED NOT NULL,
    return_flight_id INT UNSIGNED NULL,

    passenger_count SMALLINT UNSIGNED NOT NULL,
    trip_type ENUM('One-way', 'Round-trip') NOT NULL,

    departure_date DATE NOT NULL,
    return_date DATE NULL,

    ticket_class VARCHAR(20) NOT NULL DEFAULT 'Economy',

    total_price_tl DECIMAL(14, 2) NULL
        COMMENT 'Current mock data stores subtotal-like total. For real usage, store breakdown separately.',

    booking_status ENUM(
        'Confirmed',
        'Pending',
        'Cancelled',
        'Waitlisted',
        'Failed'
    ) NOT NULL,

    notes TEXT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (booking_id),

    KEY idx_bookings_flight_date (flight_id, departure_date),
    KEY idx_bookings_status (booking_status),

    CONSTRAINT fk_bookings_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_bookings_flight
        FOREIGN KEY (flight_id)
        REFERENCES flights (flight_id),

    CONSTRAINT fk_bookings_return_flight
        FOREIGN KEY (return_flight_id)
        REFERENCES flights (flight_id),

    CONSTRAINT chk_bookings_passenger_count
        CHECK (passenger_count > 0),

    CONSTRAINT chk_bookings_roundtrip_requires_return_flight
        CHECK (
            trip_type <> 'Round-trip'
            OR return_flight_id IS NOT NULL
        ),

    CONSTRAINT chk_bookings_oneway_has_no_return_flight
        CHECK (
            trip_type <> 'One-way'
            OR return_flight_id IS NULL
        ),

    CONSTRAINT chk_bookings_roundtrip_requires_return_date
        CHECK (
            trip_type <> 'Round-trip'
            OR return_date IS NOT NULL
        ),

    CONSTRAINT chk_bookings_ticket_class
        CHECK (ticket_class IN ('Economy', 'Business'))
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Passenger breakdown per booking
--
-- Your current mock bookings only store total passenger_count.
-- This table allows Adult/Child/Baby breakdown in the future.
-- ------------------------------------------------------------
CREATE TABLE booking_passenger_counts (
    booking_id INT UNSIGNED NOT NULL,
    passenger_type VARCHAR(20) NOT NULL,
    quantity SMALLINT UNSIGNED NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (booking_id, passenger_type),

    CONSTRAINT fk_booking_passenger_counts_booking
        FOREIGN KEY (booking_id)
        REFERENCES bookings (booking_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_booking_passenger_type
        CHECK (passenger_type IN ('Adult', 'Child', 'Baby')),

    CONSTRAINT chk_booking_passenger_quantity
        CHECK (quantity > 0)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Optional price breakdown
-- ------------------------------------------------------------
CREATE TABLE booking_price_breakdowns (
    booking_id INT UNSIGNED NOT NULL,
    subtotal_tl DECIMAL(14, 2) NOT NULL,
    tax_tl DECIMAL(14, 2) NOT NULL,
    fees_tl DECIMAL(14, 2) NOT NULL,
    total_tl DECIMAL(14, 2) NOT NULL,

    calculated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (booking_id),

    CONSTRAINT fk_booking_price_breakdowns_booking
        FOREIGN KEY (booking_id)
        REFERENCES bookings (booking_id)
        ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Pricing configuration
-- ------------------------------------------------------------
CREATE TABLE pricing_config (
    config_key VARCHAR(100) NOT NULL,
    numeric_value DECIMAL(18, 6) NULL,
    text_value VARCHAR(255) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (config_key)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

CREATE TABLE ticket_class_multipliers (
    class_name VARCHAR(50) NOT NULL,
    multiplier DECIMAL(8, 4) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (class_name)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

CREATE TABLE passenger_type_multipliers (
    passenger_type VARCHAR(20) NOT NULL,
    multiplier DECIMAL(8, 4) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (passenger_type)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Convenient view for sellable routes
-- ------------------------------------------------------------
CREATE VIEW v_sellable_routes AS
SELECT
    f.flight_id,
    f.flight_number,
    f.origin_code,
    o.city AS origin_city,
    o.country AS origin_country,
    f.dest_code,
    d.city AS destination_city,
    d.country AS destination_country,
    f.departure_time,
    f.arrival_time,
    f.arrival_date_offset,
    f.flight_minutes,
    f.total_minutes,
    f.duration_text,
    f.transfer_status,
    f.connection_airport,
    f.layover_minutes,
    f.base_price_tl,
    f.aircraft_model,
    f.max_capacity
FROM flights f
JOIN airports o ON o.code = f.origin_code
JOIN airports d ON d.code = f.dest_code
WHERE f.is_leg = 0;
