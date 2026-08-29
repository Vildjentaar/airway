"""
db.models

Shared enums and constants used across the db package.
"""

from __future__ import annotations

from enum import Enum

AIRLINE_NAME = "Thall Lines"


class TransferStatus(str, Enum):
    DIRECT = "Direct"
    CONNECTING = "Connecting"


class BookingStatus(str, Enum):
    CONFIRMED = "Confirmed"
    PENDING = "Pending"
    CANCELLED = "Cancelled"
    WAITLISTED = "Waitlisted"
    FAILED = "Failed"


TRANSFER_STATUS_LOCALIZED = {
    TransferStatus.DIRECT: {
        "en": "Direct",
        "tr": "Direkt",
    },
    TransferStatus.CONNECTING: {
        "en": "Connecting",
        "tr": "Aktarmalı",
    },
}
