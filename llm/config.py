"""
llm/config.py
-------------
Pure constants shared across the llm package.

No logic, no imports from the rest of the project.
Changing a value here propagates automatically to every module
that references it (history_sanitizer, engine, flight_validation, …).
"""

# ── Gemini model identifier ──────────────────────────────────────────
MODEL_NAME = "gemini-3.5-flash-lite"

# ── History / context-window knobs ───────────────────────────────────
MAX_HISTORY_MESSAGES = 100
MAX_TOOL_RESULT_CHARS = 800

# ── Flight-data validation ───────────────────────────────────────────
# Every segment dict in the cart must contain all of these keys with
# non-empty string values.
FLIGHT_REQUIRED = [
    "departure_point", "arrival_point", "departure_date",
    "departure_time", "arrival_time", "flight_duration", "flight_number",
]

# ── Orchestration-loop limits ────────────────────────────────────────
# Maximum number of tool-call turns the engine will run before forcing
# the model to emit a text reply.
CIRCUIT_BREAK_TURN = 3

# Maximum total loop iterations (tool-call + follow-up turns).
# Raised from 5 to 6 to accommodate the mandatory trailing
# send_itinerary_email call after generate_final_report.
MAX_TURNS = 6
