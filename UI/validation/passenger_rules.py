"""
ui/validation/passenger_rules.py

Age-bracket validation rules per passenger type.

This module is intentionally free of Streamlit imports so it can be
unit-tested in isolation and reused by both the UI layer
(ui/forms/passenger_form.py) and any backend/report logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# Passenger type definitions
# ---------------------------------------------------------------------------

PASSENGER_TYPES = ["Adult", "Child", "Infant", "Baby"]

# Inclusive (min_age, max_age) bounds in whole years at time of travel.
# max_age of None means "no upper bound".
_AGE_BRACKETS = {
    "Infant": (0, 1),
    "Baby": (0, 1),      # alias used by tools_schema / system_prompt
    "Child": (2, 11),
    "Adult": (12, None),
}


@dataclass(frozen=True)
class PassengerValidationResult:
    is_valid: bool
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculate_age(birth_date: date, as_of: Optional[date] = None) -> int:
    """
    Calculate a person's age in whole years as of a given date
    (defaults to today).
    """
    as_of = as_of or date.today()

    if birth_date > as_of:
        raise ValueError("birth_date cannot be in the future")

    age = as_of.year - birth_date.year
    had_birthday_this_year = (as_of.month, as_of.day) >= (
        birth_date.month,
        birth_date.day,
    )
    if not had_birthday_this_year:
        age -= 1
    return age


def _bracket_label(passenger_type: str) -> str:
    min_age, max_age = _AGE_BRACKETS[passenger_type]
    if max_age is None:
        return f"{min_age}+ years"
    return f"{min_age}-{max_age} years"


# ---------------------------------------------------------------------------
# Public validation API
# ---------------------------------------------------------------------------

def validate_passenger_type(passenger_type: str) -> PassengerValidationResult:
    """Confirm the passenger type is one we recognize."""
    if passenger_type not in PASSENGER_TYPES:
        return PassengerValidationResult(
            is_valid=False,
            error_message=(
                f"Unknown passenger type '{passenger_type}'. "
                f"Expected one of: {', '.join(PASSENGER_TYPES)}."
            ),
        )
    return PassengerValidationResult(is_valid=True)


def validate_age_for_type(
    passenger_type: str,
    birth_date: date,
    as_of: Optional[date] = None,
) -> PassengerValidationResult:
    """
    Validate that a passenger's age (derived from birth_date) fits the
    allowed bracket for the declared passenger_type.
    """
    type_check = validate_passenger_type(passenger_type)
    if not type_check.is_valid:
        return type_check

    try:
        age = calculate_age(birth_date, as_of=as_of)
    except ValueError as exc:
        return PassengerValidationResult(is_valid=False, error_message=str(exc))

    min_age, max_age = _AGE_BRACKETS[passenger_type]

    if age < min_age or (max_age is not None and age > max_age):
        return PassengerValidationResult(
            is_valid=False,
            error_message=(
                f"Age {age} does not match passenger type '{passenger_type}' "
                f"(expected {_bracket_label(passenger_type)})."
            ),
        )

    return PassengerValidationResult(is_valid=True)


def suggest_passenger_type(birth_date: date, as_of: Optional[date] = None) -> str:
    """
    Given a birth date, suggest the passenger type whose bracket it falls
    into. Falls back to 'Adult' for ages beyond all defined brackets.
    """
    age = calculate_age(birth_date, as_of=as_of)
    for passenger_type, (min_age, max_age) in _AGE_BRACKETS.items():
        if age >= min_age and (max_age is None or age <= max_age):
            return passenger_type
    return "Adult"


def validate_passenger_count(
    passenger_type: str,
    count: int,
    *,
    max_infants_per_adult: int = 1,
    adult_count: Optional[int] = None,
) -> PassengerValidationResult:
    """
    Validate group-level counts, e.g. ensuring infants don't exceed the
    number of accompanying adults (a common airline constraint).
    """
    if count < 0:
        return PassengerValidationResult(
            is_valid=False,
            error_message="Passenger count cannot be negative.",
        )

    if passenger_type == "Infant" and adult_count is not None:
        max_allowed = adult_count * max_infants_per_adult
        if count > max_allowed:
            return PassengerValidationResult(
                is_valid=False,
                error_message=(
                    f"Too many infants ({count}) for the number of adults "
                    f"({adult_count}). Max {max_infants_per_adult} infant(s) "
                    f"per adult."
                ),
            )

    return PassengerValidationResult(is_valid=True)