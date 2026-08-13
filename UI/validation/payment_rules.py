"""
validation/payment_rules.py

Shape-level validation for payment card details.

These are lightweight, presentation-layer checks meant to catch obvious
input mistakes before submission — they do not replace real PCI-compliant
payment processing/validation performed by a payment gateway.
"""

import re
from datetime import datetime

# --- Regex patterns -----------------------------------------------------

_CARD_NUMBER_CLEAN_RE = re.compile(r"[\s-]+")
_CARD_NUMBER_DIGITS_RE = re.compile(r"^\d{12,19}$")
_CVC_RE = re.compile(r"^\d{3,4}$")
_EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])\/?([0-9]{2})$")

# Recognized card brand prefixes -> (name, valid lengths)
_CARD_BRAND_RULES = [
    ("Visa", re.compile(r"^4\d{12}(\d{3})?(\d{3})?$")),
    ("Mastercard", re.compile(r"^(5[1-5]\d{14}|2(2[2-9]\d{12}|[3-6]\d{13}|7[01]\d{12}|720\d{12}))$")),
    ("American Express", re.compile(r"^3[47]\d{13}$")),
    ("Discover", re.compile(r"^6(?:011|5\d{2})\d{12}$")),
]


def clean_card_number(raw_number: str) -> str:
    """Strip spaces and dashes from a raw card number string."""
    if not raw_number:
        return ""
    return _CARD_NUMBER_CLEAN_RE.sub("", raw_number.strip())


def _luhn_checksum(number: str) -> bool:
    """Validate a numeric string against the Luhn algorithm."""
    digits = [int(d) for d in number]
    checksum = 0
    parity = len(digits) % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def detect_card_brand(raw_number: str) -> str:
    """
    Best-effort detection of card brand from number prefix/length.
    Returns "Unknown" if no rule matches.
    """
    cleaned = clean_card_number(raw_number)
    for brand, pattern in _CARD_BRAND_RULES:
        if pattern.match(cleaned):
            return brand
    return "Unknown"


def validate_card_number(raw_number: str) -> tuple[bool, str]:
    """
    Validate the shape and checksum of a card number.

    Returns (is_valid, error_message). error_message is "" when valid.
    """
    if not raw_number or not raw_number.strip():
        return False, "Card number is required."

    cleaned = clean_card_number(raw_number)

    if not _CARD_NUMBER_DIGITS_RE.match(cleaned):
        return False, "Card number must be 12-19 digits."

    if not _luhn_checksum(cleaned):
        return False, "Card number is invalid (failed checksum)."

    return True, ""


def validate_cvc(raw_cvc: str, card_brand: str | None = None) -> tuple[bool, str]:
    """
    Validate a CVC/CVV code. American Express uses 4 digits; other
    brands typically use 3.
    """
    if not raw_cvc or not raw_cvc.strip():
        return False, "CVC is required."

    cvc = raw_cvc.strip()

    if not _CVC_RE.match(cvc):
        return False, "CVC must be 3 or 4 digits."

    if card_brand == "American Express" and len(cvc) != 4:
        return False, "American Express cards require a 4-digit CVC."

    if card_brand and card_brand != "American Express" and len(cvc) != 3:
        return False, "CVC must be 3 digits for this card type."

    return True, ""


def validate_expiry(raw_expiry: str) -> tuple[bool, str]:
    """
    Validate an expiry string in MM/YY or MMYY format and ensure the
    card has not already expired.
    """
    if not raw_expiry or not raw_expiry.strip():
        return False, "Expiry date is required."

    expiry = raw_expiry.strip()
    match = _EXPIRY_RE.match(expiry)
    if not match:
        return False, "Expiry must be in MM/YY format."

    month = int(match.group(1))
    year_two_digit = int(match.group(2))
    year = 2000 + year_two_digit

    now = datetime.now()
    # Card is valid through the last day of the expiry month.
    if year < now.year or (year == now.year and month < now.month):
        return False, "Card has expired."

    return True, ""


def validate_cardholder_name(raw_name: str) -> tuple[bool, str]:
    """
    Minimal shape check for the cardholder name field on a payment form.
    Delegates the actual character/format rules to name_rules where the
    two overlap; this only enforces presence and a sane length here.
    """
    if not raw_name or not raw_name.strip():
        return False, "Cardholder name is required."

    if len(raw_name.strip()) < 2:
        return False, "Cardholder name is too short."

    if len(raw_name.strip()) > 100:
        return False, "Cardholder name is too long."

    return True, ""


def validate_payment_details(
    card_number: str,
    cvc: str,
    expiry: str,
    cardholder_name: str,
) -> tuple[bool, list[str]]:
    """
    Run all payment field validations together.

    Returns (all_valid, list_of_error_messages).
    """
    errors: list[str] = []

    name_ok, name_err = validate_cardholder_name(cardholder_name)
    if not name_ok:
        errors.append(name_err)

    number_ok, number_err = validate_card_number(card_number)
    if not number_ok:
        errors.append(number_err)

    brand = detect_card_brand(card_number) if number_ok else None

    cvc_ok, cvc_err = validate_cvc(cvc, brand)
    if not cvc_ok:
        errors.append(cvc_err)

    expiry_ok, expiry_err = validate_expiry(expiry)
    if not expiry_ok:
        errors.append(expiry_err)

    return (len(errors) == 0), errors