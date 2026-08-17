-- 02-ancillary.sql
-- -----------------
-- Ancillary product catalogues: seat types, luggage tiers, extra services.
--
-- These tables are pure configuration / catalogue data, read at checkout
-- time by the UI forms. They follow the same pattern as
-- ticket_class_multipliers and passenger_type_multipliers in 01-schema.sql.

USE thall_lines;

DROP TABLE IF EXISTS seat_types;
DROP TABLE IF EXISTS luggage_tiers;
DROP TABLE IF EXISTS extra_services;

-- ------------------------------------------------------------
-- Seat types
--
-- Each row is a bookable seat category with a price delta.
-- "standard" is always 0 TL (included in base fare).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seat_types (
    seat_type_key   VARCHAR(30)    NOT NULL,
    label           VARCHAR(100)   NOT NULL,
    price_tl        DECIMAL(10, 2) NOT NULL DEFAULT 0,
    description     VARCHAR(255)   NULL,
    display_order   SMALLINT       NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (seat_type_key)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

INSERT INTO seat_types (seat_type_key, label, price_tl, description, display_order) VALUES
    ('no_selection',   'No Selection',       0.00,  'Skip seat selection.',                      1),
    ('standard',       'Standard',           0.00,  'Randomly assigned seat at check-in.',       2),
    ('window',         'Window Preferred', 100.00,  'Guaranteed window seat.',                   3),
    ('aisle',          'Aisle Preferred',  100.00,  'Guaranteed aisle seat.',                    4),
    ('extra_legroom',  'Extra Legroom',    250.00,  'Seats in rows 12-14 with extra pitch.',     5),
    ('emergency_exit', 'Emergency Exit',   300.00,  'Exit-row seat — additional legroom.',       6),
    ('front_row',      'Front Row',        450.00,  'First row seats for quick disembarkation.', 7);


-- ------------------------------------------------------------
-- Luggage tiers
--
-- included_in_economy / included_in_business indicate which
-- tiers come free with each ticket class.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS luggage_tiers (
    tier_key              VARCHAR(30)    NOT NULL,
    label                 VARCHAR(100)   NOT NULL,
    weight_kg             SMALLINT       NOT NULL DEFAULT 0,
    price_tl              DECIMAL(10, 2) NOT NULL DEFAULT 0,
    included_in_economy   TINYINT(1)     NOT NULL DEFAULT 0,
    included_in_business  TINYINT(1)     NOT NULL DEFAULT 0,
    display_order         SMALLINT       NOT NULL DEFAULT 0,
    updated_at            TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (tier_key)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

INSERT INTO luggage_tiers (tier_key, label, weight_kg, price_tl, included_in_economy, included_in_business, display_order) VALUES
    ('cabin_only',     'Cabin Bag Only',                                         8,   0.00, 1, 1, 1),
    ('extra_cabin',    'Extra Cabin Bag (8 kg)',                                 8, 250.00, 0, 1, 2),
    ('checked_20kg',   'Checked Bag (20 kg)',                                   20, 350.00, 0, 1, 3),
    ('checked_30kg',   'Checked Bag (30 kg)',                                   30, 550.00, 0, 0, 4),
    ('extra_weighted', 'Extra Weighted Luggage (230 kg max, 300 Tl for +5 kg)',230, 600.00, 0, 0, 5),
    ('oversize',       'Oversize / Sports Gear',                                 0, 800.00, 0, 0, 6),
    ('pet_cabin',      'Pet in Cabin',                                           8, 450.00, 0, 0, 7),
    ('musical_instr',  'Musical Instrument',                                     0, 300.00, 0, 1, 8);


-- ------------------------------------------------------------
-- Extra services
--
-- Per-booking add-ons.  Some are complimentary for Business.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS extra_services (
    service_key           VARCHAR(30)    NOT NULL,
    label                 VARCHAR(100)   NOT NULL,
    price_tl              DECIMAL(10, 2) NOT NULL DEFAULT 0,
    included_in_business  TINYINT(1)     NOT NULL DEFAULT 0,
    description           VARCHAR(255)   NULL,
    display_order         SMALLINT       NOT NULL DEFAULT 0,
    updated_at            TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (service_key)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;

INSERT INTO extra_services (service_key, label, price_tl, included_in_business, description, display_order) VALUES
    ('priority_boarding',   'Priority Boarding',                150.00, 1, 'Board before general passengers.',                      1),
    ('lounge_access',       'Lounge Access',                    400.00, 1, 'Access to the airline lounge before departure.',        2),
    ('meal_upgrade',        'Premium Meal',                     200.00, 0, 'Upgrade to a chef-curated in-flight meal.',             3),
    ('airborne_sandwich',   'Airborne Sandwich',                 80.00, 0, 'A delicious sandwich served during the flight.',        4),
    ('travel_insurance',    'Travel Insurance',                 120.00, 0, 'Coverage for cancellations, delays, and lost baggage.', 5),
    ('fast_track_security', 'Fast Track Security',              180.00, 0, 'Skip the regular security queue.',                      6),
    ('flexi_ticket',        'Flexi-Ticket (Free Rescheduling)', 500.00, 1, 'Change your flight dates without penalty fees.',        7),
    ('champagne_arrival',   'Champagne on Arrival',             350.00, 1, 'Start your journey with a glass of champagne.',         8);