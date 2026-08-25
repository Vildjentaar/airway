"""
llm package
-----------
Re-exports the public API so callers can do:

    from llm import call_llm

Backward-compatible shim — `app.py` only needs to change its import
path from `llm_engine` to `llm`.
"""

# During migration, individual modules are landed one at a time.
# The final step will wire `call_llm` through from engine.py;
# until then this file stays minimal so the package is importable.

__all__: list[str] = []
