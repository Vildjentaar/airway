"""
llm package
-----------
Re-exports the public API so callers can do:

    from llm import call_llm

Backward-compatible shim — `app.py` only needs to change its import
path from `llm_engine` to `llm`.
"""

from .engine import call_llm
from .flight_validation import is_valid_flight_data

__all__ = ["call_llm", "is_valid_flight_data"]
