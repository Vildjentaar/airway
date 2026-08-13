"""
Shared name/text validation rules used across auth, passenger, and payment forms.

This module intentionally has NO Streamlit import — it is pure validation logic
so it can be unit-tested and reused without a UI context.
"""

import re
from dataclasses import dataclass
from typing import Optional

# A "name" here covers: person names, cardholder names, login display names.
# Allows unicode letters (accents, Turkish chars, etc.), spaces, hyphens, and apostrophes.
_NAME_PATTERN = re.compile(r"^[^\W\d_]+([ '\-][^\W\d_]+)*$", re.UNICODE)

# Stricter pattern for fields that must not contain punctuation at all (e.g. usernames-as-names)
_SIMPLE_NAME_PATTERN = re.compile(r"^[^\W\d_]+$", re.UNICODE)

MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 60


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    error_message: Optional[str] = None

    def __bool__(self) -> bool:
        return self.is_valid

    @staticmethod
    def ok() -> "ValidationResult":
        return ValidationResult(True, None)

    @staticmethod
    def fail(message: str) -> "ValidationResult":
        return ValidationResult(False, message)


def normalize_name(raw: str) -> str:
    """Trim and collapse internal whitespace in a name string."""
    if raw is None:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def validate_name(
    raw: str,
    *,
    field_label: str = "Name",
    allow_punctuation: bool = True,
    min_length: int = MIN_NAME_LENGTH,
    max_length: int = MAX_NAME_LENGTH,
) -> ValidationResult:
    """
    Validate a single name field (first name, last name, cardholder name, etc.)

    Args:
        raw: the raw user input.
        field_label: human-readable label used in error messages (e.g. "First name").
        allow_punctuation: if True, allows spaces/hyphens/apostrophes (e.g. "Anne-Marie",
            "O'Brien"); if False, requires a single unbroken word.
        min_length: minimum allowed length after normalization.
        max_length: maximum allowed length after normalization.

    Returns:
        ValidationResult indicating success or the first failing rule.
    """
    value = normalize_name(raw)

    if not value:
        return ValidationResult.fail(f"{field_label} is required.")

    if len(value) < min_length:
        return ValidationResult.fail(
            f"{field_label} must be at least {min_length} characters."
        )

    if len(value) > max_length:
        return ValidationResult.fail(
            f"{field_label} must be at most {max_length} characters."
        )

    pattern = _NAME_PATTERN if allow_punctuation else _SIMPLE_NAME_PATTERN
    if not pattern.match(value):
        return ValidationResult.fail(
            f"{field_label} may only contain letters"
            + (", spaces, hyphens, and apostrophes." if allow_punctuation else ".")
        )

    # Disallow leading/trailing/duplicate punctuation like "--" or "''"
    if allow_punctuation and re.search(r"[ '\-]{2,}", value):
        return ValidationResult.fail(
            f"{field_label} contains invalid repeated punctuation."
        )

    return ValidationResult.ok()


def validate_full_name(
    raw: str,
    *,
    field_label: str = "Full name",
    min_parts: int = 2,
) -> ValidationResult:
    """
    Validate a full name field, ensuring it has at least `min_parts` words
    (e.g. a first and last name), each of which passes validate_name.
    """
    value = normalize_name(raw)

    base_check = validate_name(value, field_label=field_label)
    if not base_check:
        return base_check

    parts = value.split(" ")
    if len(parts) < min_parts:
        return ValidationResult.fail(
            f"{field_label} must include at least {min_parts} words "
            f"(e.g. first and last name)."
        )

    return ValidationResult.ok()


def names_match(a: str, b: str) -> bool:
    """Case-insensitive comparison of two normalized names."""
    return normalize_name(a).casefold() == normalize_name(b).casefold()