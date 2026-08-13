"""
accounts.py
-----------
User accounts, identity validation (TCKN), and authentication via MySQL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import hashlib
import secrets

from database.db import fetch_one, get_connection

def hash_password(password: str) -> str:
    """Simple PBKDF2 password hash."""
    password = password or ""
    salt = secrets.token_hex(16)
    iterations = 600_000

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
        dklen=32,
    )

    return f"pbkdf2_sha256${iterations}${salt}${derived_key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    if not hashed or not password:
        return False
    parts = hashed.split('$')
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
        
    iterations = int(parts[1])
    salt = bytes.fromhex(parts[2])
    stored_key = parts[3]
    
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    return derived_key.hex() == stored_key


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


class DatabaseAuthProvider(AuthProvider):
    """Production implementation backed by MySQL."""

    def authenticate(self, email: str, password: str) -> dict:
        email_norm = (email or "").strip().lower()
        if not email_norm:
             return {"success": False, "error": "Email is required."}
             
        row = fetch_one("SELECT * FROM users WHERE LOWER(email) = %s", (email_norm,))
        if not row:
            return {"success": False, "error": "No account found with that email."}
            
        if not verify_password(password, row["password_hash"]):
             return {"success": False, "error": "Incorrect password."}
             
        profile = {k: v for k, v in row.items() if k != "password_hash"}
        return {"success": True, "profile": profile}

    def register(self, profile: dict) -> dict:
        email_norm = (profile.get("email") or "").strip().lower()
        if not email_norm:
            return {"success": False, "error": "Email is required."}
            
        existing = fetch_one("SELECT user_id FROM users WHERE LOWER(email) = %s", (email_norm,))
        if existing:
            return {"success": False, "error": "An account with that email already exists."}
            
        hashed_pw = hash_password(profile.get("password", ""))
        
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Use sex[0].upper() safely if it exists
            sex = profile.get("sex", "")
            if sex and len(sex) > 0:
                sex = sex[0].upper()
            else:
                sex = None
                
            cursor.execute(
                """
                INSERT INTO users (email, password_hash, name, surname, birthdate, sex, nationality, tckn, mobile)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    email_norm,
                    hashed_pw,
                    profile.get("name", ""),
                    profile.get("surname", ""),
                    profile.get("birthdate", None) or None,
                    sex,
                    profile.get("nationality", ""),
                    profile.get("tckn", ""),
                    profile.get("mobile", "")
                )
            )
            new_id = cursor.lastrowid
            conn.commit()
            
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (new_id,))
            new_user = cursor.fetchone()
            clean = {k: v for k, v in new_user.items() if k != "password_hash"}
            return {"success": True, "profile": clean}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": f"Registration failed: {e}"}
        finally:
            conn.close()


# The one line every caller depends on. Repointed to the MySQL implementation!
default_auth_provider: AuthProvider = DatabaseAuthProvider()
