"""
accounts.py
-----------
User accounts, identity validation (TCKN), and authentication. Split out
of thall_lines_db.py because "who is this customer and can they log in"
is a different responsibility than "what flights exist" — they change for
different reasons and shouldn't force edits to the same file.

DEPENDENCY INVERSION:
Callers (ui_components.py today; llm_engine.py or a future FastAPI route
tomorrow) depend on the abstract `AuthProvider` interface below, never on
the concrete mock store. `default_auth_provider` is the one line every
caller actually imports. When this graduates to a real backend, write a
new class (e.g. `DatabaseAuthProvider`) and repoint that single line —
nothing that calls `default_auth_provider.authenticate(...)` has to change.

Still a mock: passwords are compared in plaintext against an in-memory
list. That's fine for a prototype with fabricated data — it must never
happen against real credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# ---------------------------------------------------------------------------
# Mock user store
# ---------------------------------------------------------------------------
USERS: list[dict] = [
    {
        "user_id": 1,
        "email": "ahmet@example.com",
        "password": "password123",  # mock only — never store plaintext for real
        "name": "Ahmet",
        "surname": "Yılmaz",
        "birthdate": "1990-05-14",
        "sex": "M",
        "nationality": "TR",
        "tckn": "10000000146",
        "mobile": "+905551234567",
    }
]


def validate_tckn(tckn: str) -> dict:
    """Validate a Turkish Citizen Identity Number using the official checksum algorithm."""
    if len(tckn) != 11 or not tckn.isdigit() or tckn[0] == '0':
        return {"valid": False, "error": "TCKN must be 11 digits and cannot start with 0."}

    digits = [int(d) for d in tckn]
    sum_odds = sum(digits[0:9:2])
    sum_evens = sum(digits[1:8:2])

    digit_10 = (sum_odds * 7 - sum_evens) % 10
    digit_11 = sum(digits[:10]) % 10

    if digits[9] != digit_10 or digits[10] != digit_11:
        return {"valid": False, "error": "TCKN checksum failed. Please enter a valid TCKN."}

    return {"valid": True, "message": "TCKN is valid."}


# ---------------------------------------------------------------------------
# Auth abstraction
# ---------------------------------------------------------------------------
class AuthProvider(ABC):
    """Abstract identity provider. A concrete implementation decides *how*
    credentials are checked and *where* accounts live — callers never know
    or need to know which one they're talking to."""

    @abstractmethod
    def authenticate(self, email: str, password: str) -> dict:
        """Return {"success": True, "profile": {...}} or {"success": False, "error": "..."}."""

    @abstractmethod
    def register(self, profile: dict) -> dict:
        """Create a new account. Return {"success": True, "profile": {...}} or an error dict."""


class MockAuthProvider(AuthProvider):
    """In-memory implementation backed by USERS. Good enough for a
    prototype; swappable for a real provider (a database, an OAuth
    service) later without touching any caller."""

    def __init__(self, users: list[dict] | None = None):
        self._users = users if users is not None else USERS

    def authenticate(self, email: str, password: str) -> dict:
        email_norm = (email or "").strip().lower()
        for user in self._users:
            if user["email"].lower() == email_norm:
                if user["password"] == password:
                    profile = {k: v for k, v in user.items() if k != "password"}
                    return {"success": True, "profile": profile}
                return {"success": False, "error": "Incorrect password."}
        return {"success": False, "error": "No account found with that email."}

    def register(self, profile: dict) -> dict:
        email_norm = (profile.get("email") or "").strip().lower()
        if not email_norm:
            return {"success": False, "error": "Email is required."}
        if any(u["email"].lower() == email_norm for u in self._users):
            return {"success": False, "error": "An account with that email already exists."}

        new_user = {
            "user_id": max((u["user_id"] for u in self._users), default=0) + 1,
            "email": profile.get("email", ""),
            "password": profile.get("password", ""),
            "name": profile.get("name", ""),
            "surname": profile.get("surname", ""),
            "birthdate": profile.get("birthdate", ""),
            "sex": profile.get("sex", ""),
            "nationality": profile.get("nationality", ""),
            "tckn": profile.get("tckn", ""),
            "mobile": profile.get("mobile", ""),
        }
        self._users.append(new_user)
        clean = {k: v for k, v in new_user.items() if k != "password"}
        return {"success": True, "profile": clean}


# The one line every caller depends on. Repoint this at a different
# AuthProvider implementation when a real backend exists.
default_auth_provider: AuthProvider = MockAuthProvider()
