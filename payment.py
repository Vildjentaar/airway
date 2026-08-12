"""
payment.py
----------
Card validation and (mock) payment processing.

DEPENDENCY INVERSION:
The checkout form (ui_components.py) validates a card by calling
`default_payment_gateway.charge(...)` — an abstract `PaymentGateway`, not
a hardcoded mock function. Swapping in a real processor later (Stripe,
iyzico, a 3D-Secure redirect flow) means writing one new class and
repointing the single `default_payment_gateway` assignment at the bottom
of this file. No caller changes.

Still a mock: `MockPaymentGateway` only checks card-number shape (Luhn),
expiry, and CVC format. It never contacts a real payment network and
never should for fabricated card numbers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, card_number: str, expiry: str, cvc: str, cardholder_name: str) -> dict:
        """Return {"success": True, "transaction_id": "..."} or {"success": False, "error": "..."}."""


class MockPaymentGateway(PaymentGateway):
    """Mock validation only — Luhn check, expiry, and CVC format. Always
    'approves' once the shape is valid; never talks to a real network."""

    def charge(self, card_number: str, expiry: str, cvc: str, cardholder_name: str) -> dict:
        digits = (card_number or "").replace(" ", "").replace("-", "")

        if not cardholder_name or not cardholder_name.strip():
            return {"success": False, "error": "Cardholder name is required."}
        if len(digits) != 16 or not digits.isdigit():
            return {"success": False, "error": "Card number must be 16 digits."}
        if not self._luhn_valid(digits):
            return {"success": False, "error": "Card number failed validation (Luhn check)."}
        if not self._expiry_valid(expiry):
            return {"success": False, "error": "Expiry date must be a valid, non-expired MM/YY date."}
        if not (cvc or "").isdigit() or len(cvc) != 3:
            return {"success": False, "error": "CVC must be 3 digits."}

        return {"success": True, "transaction_id": "TXN-MOCK-" + digits[-4:]}

    @staticmethod
    def _luhn_valid(digits: str) -> bool:
        total = 0
        for i, ch in enumerate(reversed(digits)):
            d = int(ch)
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0

    @staticmethod
    def _expiry_valid(expiry: str) -> bool:
        try:
            month_str, year_str = (expiry or "").strip().split("/")
            month = int(month_str)
            year = 2000 + int(year_str)
            if not (1 <= month <= 12):
                return False
            now = datetime.now()
            if (year, month) < (now.year, now.month):
                return False
            return True
        except (ValueError, AttributeError):
            return False


# The one line every caller depends on. Repoint this at a real gateway
# implementation when one exists.
default_payment_gateway: PaymentGateway = MockPaymentGateway()
