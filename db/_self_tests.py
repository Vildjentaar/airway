"""
db._self_tests

Dev-only diagnostic helpers. Not part of the stable public API — imported
directly by scripts/self_tests.py.
"""

from __future__ import annotations

from database.db import fetch_all


def self_test_bidirectional_coverage() -> list[str]:
    """
    SQL-backed replacement for the old mock bidirectional coverage test.
    """
    rows = fetch_all(
        """
        SELECT DISTINCT
            f.origin_code,
            f.dest_code
        FROM flights f
        WHERE f.is_leg = 0
          AND NOT EXISTS (
              SELECT 1
              FROM flights r
              WHERE r.origin_code = f.dest_code
                AND r.dest_code = f.origin_code
                AND r.is_leg = 0
          )
        ORDER BY f.origin_code, f.dest_code
        """
    )

    return [
        f"{row['origin_code']}->{row['dest_code']} has no return route "
        f"{row['dest_code']}->{row['origin_code']}"
        for row in rows
    ]
