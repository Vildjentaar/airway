"""
booking_context.py
-------------------
Date/time context the LLM looks up via the `get_context` tool: the
current date/time, pre-computed relative dates ("tomorrow", "next
Monday"), and the allowed booking window. Split out of thall_lines_db.py
because none of this has anything to do with the flight/route data model —
it doesn't change when a route is added, and a route being added doesn't
need this file touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta


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
