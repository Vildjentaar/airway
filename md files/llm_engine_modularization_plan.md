# llm_engine.py — Modularization Plan

## 1. Why split it

`llm_engine.py` (29 KB) currently mixes five distinct responsibilities in one file:

1. **Message-history sanitization** for Gemini's turn-sequencing rules (merging, truncation, orphan removal, flattening tool turns into user turns).
2. **Flight validation & pricing** (`_build_verified_flight`) — booking-domain business logic.
3. **Tool-call dispatch** (`_dispatch_tool_call`) — a 200+ line if/elif chain routing ~12 different tool names.
4. **Tool-selection policy** (`_select_active_tools`) — which tools are legal given cart/report state.
5. **The orchestration loop** (`call_llm`) — talks to the API, drives turns, applies the circuit-breaker, assembles the return value.

These layers change for different reasons and at different rates (new tool → dispatch changes; new booking rule → validation changes; API quirk → sanitization changes), so they belong in separate modules. Right now a change to, say, duplicate-itinerary detection requires reading through Gemini-specific message-flattening code to get there.

## 2. Target module layout

```
llm/
├── __init__.py              # re-exports call_llm for backward-compatible imports
├── config.py                 # MODEL_NAME, MAX_HISTORY_MESSAGES, MAX_TOOL_RESULT_CHARS, FLIGHT_REQUIRED, CIRCUIT_BREAK_TURN
├── history_sanitizer.py      # _truncate_tool_results, _sanitize_for_gemini, _extract_code, message flattening
├── tool_policy.py            # _select_active_tools
├── flight_validation.py      # is_valid_flight_data, _build_verified_flight
├── tool_dispatch/
│   ├── __init__.py           # dispatch registry + dispatch_tool_call(...) facade
│   ├── cart.py                # generate_flight_widget, remove_flight_from_cart handlers
│   ├── capacity.py            # check_capacity handler
│   ├── reporting.py           # generate_final_report handler
│   ├── lookups.py             # search_flights/find_flight/... passthrough handlers to tool_dispatcher
│   ├── context.py             # get_context handler
│   └── forms.py               # validate_tckn, render_secure_form handlers
└── engine.py                  # call_llm orchestration loop only
```

Existing top-level `app.py` continues to `from llm import call_llm` — no caller changes required (see Section 5).

## 3. Module responsibilities & contents

### 3.1 `llm/config.py`
Pure constants, no logic:
- `MODEL_NAME`, `MAX_HISTORY_MESSAGES`, `MAX_TOOL_RESULT_CHARS`, `FLIGHT_REQUIRED`, `CIRCUIT_BREAK_TURN` (currently a magic `3` inline in `call_llm` — promote to a named constant).

### 3.2 `llm/history_sanitizer.py`
- `truncate_tool_results(messages) -> list`
- `sanitize_for_gemini(messages) -> list`
- `extract_code(value) -> str`
- `flatten_history(recent_messages) -> list` — **new extraction**: currently the tool-id-to-name mapping + tool→user flattening logic lives inline inside `call_llm`'s loop (~35 lines). Pull it out as its own function so `call_llm` becomes a caller, not an implementer.
- Depends on: nothing else in this project (pure message-list transforms). Fully unit-testable with plain dict fixtures — no API client or DB needed.

### 3.3 `llm/tool_policy.py`
- `select_active_tools(messages, flight_data, report_data, email_sent: bool) -> (tools, tool_choice)`
- Imports `PRE_CART_TOOLS`, `POST_CART_TOOLS`, `POST_REPORT_TOOLS` from `tools_schema.py` (unchanged; `POST_REPORT_TOOLS` is the new minimal bundle containing only `send_itinerary_email_tool`).
- Encodes the post-report execution lock: once `report_data` exists and `email_sent` is `False`, return `(POST_REPORT_TOOLS, "required")` so the model has exactly one legal move. Once `email_sent` is `True`, return `([], "none")`.

### 3.4 `llm/flight_validation.py`
- `is_valid_flight_data(data) -> bool`
- `build_verified_flight(tool_args, flight_data) -> dict`
- Depends on `thall_lines_db.find_flight`, `thall_lines_db.get_flight_by_number`, `pricing.calculate_total_price`. This is the module most likely to grow (new fare rules, new passenger types) — isolating it means those changes never touch dispatch or sanitization code.

### 3.5 `llm/tool_dispatch/`
Replace the single 200-line `_dispatch_tool_call` if/elif chain with a **registry pattern**:

- Each handler file exposes function(s) with a uniform signature. Because the email handler needs the securely-injected recipient address and must report back whether the send succeeded, the shared signature grows two fields:
  ```python
  def handle(tool_call, tool_args, messages, flight_data, report_data, ancillary_data, user_email=None) -> (report_data, skip_followup, email_sent)
  ```
  Handlers that have no opinion on `email_sent` simply pass through whatever value they received (see `engine.py` threading notes in 3.6).
- `tool_dispatch/__init__.py` builds a `HANDLERS: dict[str, Callable]` mapping tool name → handler, e.g.:
  ```python
  HANDLERS = {
      "generate_flight_widget": cart.handle_generate_flight_widget,
      "remove_flight_from_cart": cart.handle_remove_flight,
      "check_capacity": capacity.handle_check_capacity,
      "generate_final_report": reporting.handle_generate_final_report,
      "send_itinerary_email": reporting.handle_send_itinerary_email,
      "get_context": context.handle_get_context,
      "validate_tckn": forms.handle_validate_tckn,
      "render_secure_form": forms.handle_render_secure_form,
      **{name: lookups.handle_passthrough for name in lookups.PASSTHROUGH_NAMES},
  }

  def dispatch_tool_call(tool_call, function_name, tool_args, messages, flight_data, report_data, ancillary_data=None, user_email=None):
      handler = HANDLERS.get(function_name, unknown.handle_unknown)
      return handler(tool_call, tool_args, messages, flight_data, report_data, ancillary_data, user_email)
  ```
- Benefit: adding a new tool becomes "add a handler function + one registry line" instead of editing a growing elif chain. Each handler file is independently testable and stays under ~50 lines.
- `lookups.py` keeps the existing passthrough-to-`tool_dispatcher.dispatch_tool` behavior for the 9 read-only DB tools (`search_flights`, `find_flight`, `get_route_details`, etc.) as one shared handler, since they're structurally identical.
- The `render_secure_form` "only once per turn" guard currently lives in `call_llm`'s loop (the `forms_called_this_turn` counter) — **keep this in `engine.py`**, not in `forms.py`, since it's cross-call-turn bookkeeping specific to the orchestration loop, not a property of the form tool itself.
- **`reporting.py` grows a second handler**, `handle_send_itinerary_email`:
  - Reads `user_email` from the injected parameter, never from `tool_args`, so the LLM cannot hallucinate or override the recipient.
  - Wraps the call to `email_service.send_itinerary_email(...)` in `try/except`; on success appends an `EMAIL_SENT` tool message and returns `email_sent=True`; on any exception appends a sanitized `EMAIL_FAILED: status=SERVICE_UNAVAILABLE` tool message and returns `email_sent=False`, so a downstream API/network failure degrades to a conversational fallback instead of crashing the engine.
  - `handle_generate_final_report` (existing handler) gets its confirmation-message copy updated to explicitly instruct the model to call `send_itinerary_email` next, matching the new forced-tool-choice policy in `tool_policy.py`.
- Depends on new `email_service.py` (backend send implementation) and the new `send_itinerary_email_tool` schema entry in `tools_schema.py` — both are out-of-scope existing/sibling files, imported as-is.

### 3.6 `llm/engine.py`
- `call_llm(client, messages, flight_data, report_data, ancillary_data=None, user_email=None, email_sent=False)` — the orchestration loop only.
- After extraction, this function's job shrinks to: copy inputs → loop up to `max_turns` (now **6**, raised from 5 to accommodate the mandatory trailing `send_itinerary_email` call) → call `tool_policy.select_active_tools(..., email_sent)` → call `history_sanitizer.flatten_history` / `sanitize_for_gemini` → call the API → on tool_calls, loop calling `tool_dispatch.dispatch_tool_call(..., user_email=user_email)`, threading the returned `email_sent` value forward each iteration → on text reply, validate/append/break → assemble return dict including `email_sent` so `app.py` can persist it to session state.
- `user_email` is accepted only as a pass-through parameter here — `engine.py` never reads or logs it, it only forwards it to the dispatch layer, keeping the "backend injects the recipient" guarantee intact at every layer.
- No business logic (pricing, validation) or message-format logic should remain inline here — if a line isn't about *sequencing the turn*, it belongs in another module.

### 3.7 `llm/__init__.py`
```python
from .engine import call_llm
__all__ = ["call_llm"]
```
Keeps `from llm_engine import call_llm` → `from llm import call_llm` a one-line change in `app.py`.

## 4. Migration steps (suggested order)

1. ✅ **DONE** — Create `llm/` package skeleton → [`llm/__init__.py`](file:///c:/Users/THALL1/Desktop/airway/llm/__init__.py)
2. ✅ **DONE** — Move constants to `config.py` → [`llm/config.py`](file:///c:/Users/THALL1/Desktop/airway/llm/config.py)
   - Extracted: `MODEL_NAME`, `MAX_HISTORY_MESSAGES`, `MAX_TOOL_RESULT_CHARS`, `FLIGHT_REQUIRED`, `CIRCUIT_BREAK_TURN` (promoted from magic `3`), `MAX_TURNS` (promoted from magic `6`).
3. ✅ **DONE** — Move `history_sanitizer.py` → [`llm/history_sanitizer.py`](file:///c:/Users/THALL1/Desktop/airway/llm/history_sanitizer.py)
   - Extracted: `truncate_tool_results`, `sanitize_for_gemini`, `extract_code` (all renamed without leading `_`), plus the **new** `flatten_history` (pulled from ~35 inline lines inside `call_llm`'s loop).
   - All functions are pure message-list transforms with no project imports except `config.MAX_TOOL_RESULT_CHARS`.
4. ✅ **DONE** — Move `flight_validation.py` → [`llm/flight_validation.py`](file:///c:/Users/THALL1/Desktop/airway/llm/flight_validation.py)
   - Extracted: `is_valid_flight_data` (unchanged), `build_verified_flight` (renamed from `_build_verified_flight` — leading underscore dropped for the public module API).
   - Internal `_extract_code` call replaced with `history_sanitizer.extract_code`; `FLIGHT_REQUIRED` now imported from `llm.config`.
   - External dependencies: `thall_lines_db.find_flight`, `thall_lines_db.get_flight_by_number`, `thall_lines_db.AIRLINE_NAME`, `pricing.calculate_total_price`.
5. ✅ **DONE** — Move `tool_policy.py` → [`llm/tool_policy.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_policy.py)
   - Extracted: `select_active_tools` (renamed from `_select_active_tools` — leading underscore dropped for the public module API).
   - Co-located `POST_REPORT_TOOLS` constant (was a module-level assignment in `llm_engine.py` aliasing `send_itinerary_email_tool`), since it is only consumed by this function.
   - Imports `PRE_CART_TOOLS`, `POST_CART_TOOLS`, `send_itinerary_email_tool` from `tools_schema`.
   - No config imports needed — the function is stateless and purely data-driven.
6. ✅ **DONE** — Build `tool_dispatch/` registry → [`llm/tool_dispatch/`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/)
   - [`__init__.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/__init__.py) — `HANDLERS` registry mapping tool name → callable, plus `dispatch_tool_call(...)` public façade.
   - [`cart.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/cart.py) — `handle_generate_flight_widget` (delegates to `flight_validation.build_verified_flight`), `handle_remove_flight`.
   - [`capacity.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/capacity.py) — `handle_check_capacity` (delegates to `tool_dispatcher.dispatch_tool`, reformats into Available/Unavailable status).
   - [`reporting.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/reporting.py) — `handle_generate_final_report` (freezes cart → report, injects ancillaries), `handle_send_itinerary_email` (server-controlled recipient, belt-and-suspenders error handling).
   - [`lookups.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/lookups.py) — `handle_passthrough` shared handler for 9 read-only DB tools (`search_flights`, `find_flight`, `get_route_details`, `list_all_routes`, `route_catalogue`, `list_airports`, `get_airport_info`, `list_bookings`, `get_booking_details`); `PASSTHROUGH_NAMES` constant used by the registry.
   - [`context.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/context.py) — `handle_get_context` (routes `info_type` to `booking_context` functions).
   - [`forms.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/forms.py) — `handle_validate_tckn`, `handle_render_secure_form` (sets `skip_followup=True`). Note: the per-turn "only once" guard stays in `engine.py`.
   - [`unknown.py`](file:///c:/Users/THALL1/Desktop/airway/llm/tool_dispatch/unknown.py) — `handle_unknown` fallback for unrecognised tool names.
   - All handlers share the uniform signature `(tool_call, tool_args, messages, flight_data, report_data, ancillary_data, user_email) → (report_data, skip_followup, email_sent)`.
   - Passthrough handlers receive an extra `_function_name` keyword argument injected by `dispatch_tool_call` so the single shared handler knows which DB tool to delegate to.
7. Slim `engine.py` down to the loop, wiring in the now-extracted modules.
8. Update `app.py` import from `llm_engine` to `llm`.
9. Delete the old `llm_engine.py` only after a full manual regression pass (happy-path booking, tool-error path, form-submission path, circuit-breaker path).

### Sanity check — Steps 1 & 2

Run the following from the project root to verify that the new package is importable and all constants match the values currently used by `llm_engine.py`:

```powershell
cd c:\Users\THALL1\Desktop\airway
python -c "
from llm.config import (
    MODEL_NAME, MAX_HISTORY_MESSAGES, MAX_TOOL_RESULT_CHARS,
    FLIGHT_REQUIRED, CIRCUIT_BREAK_TURN, MAX_TURNS,
)
import llm_engine as old

# 1. Constants match the originals
assert MODEL_NAME == old.MODEL_NAME,           f'MODEL_NAME mismatch: {MODEL_NAME!r} vs {old.MODEL_NAME!r}'
assert MAX_HISTORY_MESSAGES == old.MAX_HISTORY_MESSAGES
assert MAX_TOOL_RESULT_CHARS == old.MAX_TOOL_RESULT_CHARS
assert FLIGHT_REQUIRED == old.FLIGHT_REQUIRED
# CIRCUIT_BREAK_TURN and MAX_TURNS were inline magic numbers — just verify types
assert isinstance(CIRCUIT_BREAK_TURN, int) and CIRCUIT_BREAK_TURN == 3
assert isinstance(MAX_TURNS, int) and MAX_TURNS == 6

# 2. The package itself is importable
import llm
assert hasattr(llm, '__all__')

print('✅ All sanity checks passed.')
"
```

**Expected output:** `✅ All sanity checks passed.`
If any assertion fails, the error message will name the mismatched constant.

### Sanity check — Step 3

Run the following from the project root to verify that `history_sanitizer.py` is importable, exposes the expected public API, and produces identical output to the original inline implementations in `llm_engine.py`:

```powershell
cd c:\Users\THALL1\Desktop\airway
python -c "
from llm.history_sanitizer import (
    truncate_tool_results, sanitize_for_gemini, extract_code, flatten_history,
)
import llm_engine as old

# 1. Functions exist and are callable
assert callable(truncate_tool_results)
assert callable(sanitize_for_gemini)
assert callable(extract_code)
assert callable(flatten_history)

# 2. extract_code matches the original _extract_code
test_cases = ['Ankara (ESB)', 'istanbul (ist)', 'London', '  JFK  ']
for tc in test_cases:
    assert extract_code(tc) == old._extract_code(tc), f'extract_code mismatch on {tc!r}'

# 3. truncate_tool_results matches the original _truncate_tool_results
short_msg  = [{'role': 'tool', 'content': 'OK', 'tool_call_id': 'x1'}]
long_msg   = [{'role': 'tool', 'content': 'A' * 2000, 'tool_call_id': 'x2'}]
mixed_msgs = [{'role': 'user', 'content': 'hi'}, *long_msg, *short_msg]

assert truncate_tool_results(short_msg) == old._truncate_tool_results(short_msg)
assert truncate_tool_results(long_msg)  == old._truncate_tool_results(long_msg)
assert truncate_tool_results(mixed_msgs) == old._truncate_tool_results(mixed_msgs)

# 4. sanitize_for_gemini matches the original _sanitize_for_gemini
test_histories = [
    [],
    [{'role': 'user', 'content': 'a'}],
    [
        {'role': 'user', 'content': 'a'},
        {'role': 'user', 'content': 'b'},
        {'role': 'assistant', 'content': 'c'},
        {'role': 'assistant', 'content': 'd'},
    ],
    # Orphaned tool-call assistant (no matching tool responses)
    [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'tc1', 'function': {'name': 'f'}}]},
        {'role': 'user', 'content': 'next'},
    ],
]
for hist in test_histories:
    assert sanitize_for_gemini(hist) == old._sanitize_for_gemini(hist), (
        f'sanitize_for_gemini mismatch on {hist!r}'
    )

# 5. flatten_history smoke test — ensure it returns a list and
#    converts tool messages to user role
sample_recent = [
    {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'tc99', 'function': {'name': 'search_flights'}}
    ]},
    {'role': 'tool', 'tool_call_id': 'tc99', 'content': '{\"result\": \"found\"}'},
    {'role': 'user', 'content': 'thanks'},
]
flat = flatten_history(sample_recent)
assert isinstance(flat, list)
assert all(m.get('role') != 'tool' for m in flat), 'tool messages should be converted'
assert any('search_flights' in m.get('content', '') for m in flat), (
    'tool name should appear in flattened output'
)

print('✅ Step 3 sanity checks passed.')
"
```

**Expected output:** `✅ Step 3 sanity checks passed.`
If any assertion fails, the error message will identify the mismatched function and input.

### Sanity check — Step 4

Run the following from the project root to verify that `flight_validation.py` is importable, exposes the expected public API, and produces identical output to the original functions in `llm_engine.py`:

```powershell
cd c:\Users\THALL1\Desktop\airway
python -c "
from llm.flight_validation import is_valid_flight_data, build_verified_flight
import llm_engine as old

# 1. Functions exist and are callable
assert callable(is_valid_flight_data)
assert callable(build_verified_flight)

# 2. is_valid_flight_data matches the original — pure-data tests (no DB)
empty_cases = [None, [], '', 0, [{}]]
for case in empty_cases:
    assert is_valid_flight_data(case) == old.is_valid_flight_data(case), (
        f'is_valid_flight_data mismatch on {case!r}'
    )

# Valid cart entry (synthetic — all required fields present + price > 0)
valid_cart = [{
    'segments': [{
        'departure_point': 'IST', 'arrival_point': 'LHR',
        'departure_date': '2026-12-01', 'departure_time': '08:00',
        'arrival_time': '11:30', 'flight_duration': '3h 30m',
        'flight_number': 'PX-0001',
    }],
    'price_tl': 4500,
}]
assert is_valid_flight_data(valid_cart) == old.is_valid_flight_data(valid_cart)

# Missing field
bad_cart = [{'segments': [{'departure_point': 'IST'}], 'price_tl': 100}]
assert is_valid_flight_data(bad_cart) == old.is_valid_flight_data(bad_cart)

# Zero price
zero_price = [{
    'segments': [{
        'departure_point': 'IST', 'arrival_point': 'LHR',
        'departure_date': '2026-12-01', 'departure_time': '08:00',
        'arrival_time': '11:30', 'flight_duration': '3h 30m',
        'flight_number': 'PX-0001',
    }],
    'price_tl': 0,
}]
assert is_valid_flight_data(zero_price) == old.is_valid_flight_data(zero_price)

# 3. build_verified_flight error paths (no DB needed)
# 3a. No segments
res_new = build_verified_flight({}, [])
res_old = old._build_verified_flight({}, [])
assert res_new == res_old, f'No-segments mismatch: {res_new!r} vs {res_old!r}'

# 3b. Negative passenger count
bad_pax = {'segments': [{'departure_point': 'IST', 'arrival_point': 'LHR', 'departure_date': '2026-12-01'}], 'adult_count': -1}
res_new = build_verified_flight(bad_pax, [])
res_old = old._build_verified_flight(bad_pax, [])
assert res_new == res_old, f'Negative-pax mismatch: {res_new!r} vs {res_old!r}'

# 3c. Zero passengers
zero_pax = {'segments': [{'departure_point': 'IST', 'arrival_point': 'LHR', 'departure_date': '2026-12-01'}], 'adult_count': 0}
res_new = build_verified_flight(zero_pax, [])
res_old = old._build_verified_flight(zero_pax, [])
assert res_new == res_old, f'Zero-pax mismatch: {res_new!r} vs {res_old!r}'

# 3d. Too many passengers
over_pax = {'segments': [{'departure_point': 'IST', 'arrival_point': 'LHR', 'departure_date': '2026-12-01'}], 'adult_count': 10}
res_new = build_verified_flight(over_pax, [])
res_old = old._build_verified_flight(over_pax, [])
assert res_new == res_old, f'Over-pax mismatch: {res_new!r} vs {res_old!r}'

# 3e. Bad date format
bad_date = {'segments': [{'departure_point': 'IST', 'arrival_point': 'LHR', 'departure_date': '01-12-2026'}], 'adult_count': 1}
res_new = build_verified_flight(bad_date, [])
res_old = old._build_verified_flight(bad_date, [])
assert res_new == res_old, f'Bad-date mismatch: {res_new!r} vs {res_old!r}'

# 3f. Past date
bad_past = {'segments': [{'departure_point': 'IST', 'arrival_point': 'LHR', 'departure_date': '2020-01-01'}], 'adult_count': 1}
res_new = build_verified_flight(bad_past, [])
res_old = old._build_verified_flight(bad_past, [])
assert res_new == res_old, f'Past-date mismatch: {res_new!r} vs {res_old!r}'

# 4. build_verified_flight happy path (requires live DB for route lookup)
# Uses a known route IST→LHR with a future date.
happy_args = {
    'segments': [{
        'departure_point': 'Istanbul (IST)',
        'arrival_point': 'London (LHR)',
        'departure_date': '2026-12-15',
    }],
    'trip_type': 'One-way',
    'adult_count': 2,
    'child_count': 0,
    'baby_count': 0,
    'ticket_class': 'Economy',
}
res_new = build_verified_flight(happy_args, [])
res_old = old._build_verified_flight(happy_args, [])
assert res_new == res_old, f'Happy-path mismatch:\n  NEW: {res_new!r}\n  OLD: {res_old!r}'

# 5. Duplicate detection
if 'flight' in res_new:
    existing_cart = [res_new['flight']]
    dup_new = build_verified_flight(happy_args, existing_cart)
    dup_old = old._build_verified_flight(happy_args, list(existing_cart))
    assert dup_new == dup_old, f'Duplicate mismatch: {dup_new!r} vs {dup_old!r}'

print('✅ Step 4 sanity checks passed.')
"
```

**Expected output:** `✅ Step 4 sanity checks passed.`
If any assertion fails, the error message will identify the mismatched function and input.

### Sanity check — Step 5

Run the following from the project root to verify that `tool_policy.py` is importable, exposes the expected public API, and produces identical output to the original `_select_active_tools` in `llm_engine.py` across all four tool-phase transitions:

```powershell
cd c:\Users\THALL1\Desktop\airway
python sanity_check_5.py
```

The sanity check script is located at [`sanity_check_5.py`](file:///c:/Users/THALL1/Desktop/airway/sanity_check_5.py).

**Expected output:** `✅ Step 5 sanity checks passed.`
If any assertion fails, the error message will identify the mismatched phase and input.

### Sanity check — Step 6

Run the following from the project root to verify that the new `llm.tool_dispatch.dispatch_tool_call` registry produces byte-identical tool-response messages and return values compared to the legacy `llm_engine._dispatch_tool_call` for every tool-name branch:

```powershell
cd c:\Users\THALL1\Desktop\airway
python sanity_check_6.py
```

The sanity check script is located at [`sanity_check_6.py`](file:///c:/Users/THALL1/Desktop/airway/sanity_check_6.py).

It covers the following cases (each compared old vs new):

| Test | Tool name(s) | Notes |
|------|-------------|-------|
| `remove_flight_from_cart` | `remove_flight_from_cart` | Flight found + not-found paths |
| `check_capacity` | `check_capacity` | Mocked `tool_dispatcher.dispatch_tool` |
| All 9 lookups | `search_flights`, `find_flight`, `get_route_details`, `list_all_routes`, `route_catalogue`, `list_airports`, `get_airport_info`, `list_bookings`, `get_booking_details` | Shared passthrough handler, mocked DB |
| `get_context` | `get_context` | All 3 `info_type` values + unknown type |
| `validate_tckn` | `validate_tckn` | Valid + invalid TCKN inputs |
| `render_secure_form` | `render_secure_form` | `report_data=None` + existing dict |
| `generate_final_report` | `generate_final_report` | Empty cart (error) + with cart + ancillaries |
| `send_itinerary_email` (success) | `send_itinerary_email` | Mocked email success |
| `send_itinerary_email` (failure) | `send_itinerary_email` | Mocked email failure → `EMAIL_FAILED` message |
| `unknown_tool` | `totally_made_up_tool` | Fallback error handler |
| `generate_flight_widget` (errors) | `generate_flight_widget` | No segments, negative pax |
| `generate_flight_widget` (happy) | `generate_flight_widget` | IST→LHR booking (requires live DB) |

**Expected output:** `✅ Step 6 sanity checks passed.`
If any assertion fails, the error message will name the mismatched tool and include both the old and new outputs.

## 5. Compatibility notes

- Public entry point signature grows from `call_llm(client, messages, flight_data, report_data, ancillary_data)` to `call_llm(client, messages, flight_data, report_data, ancillary_data=None, user_email=None, email_sent=False)`. This is a pre-existing change to `llm_engine.py` (not introduced by this refactor), so `app.py` already needs to pass `user_email`/`email_sent` and persist the returned `email_sent` regardless of whether modularization happens — the import path is still the only *extra* change this plan requires (`from llm_engine import call_llm` → `from llm import call_llm`).
- `tools_schema.py` gains `send_itinerary_email_tool` and the `POST_REPORT_TOOLS` bundle; `tool_policy.py` and `tool_dispatch/reporting.py` import both as-is.
- `email_service.py` (new backend module, `send_itinerary_email`) is a sibling dependency, imported only from `tool_dispatch/reporting.py` — no other module should import it directly, to keep the email-sending side effect isolated to one handler.
- `tool_dispatcher.py` (the existing separate file for DB-lookup tools) is untouched; `llm/tool_dispatch/lookups.py` continues to delegate to it exactly as `_dispatch_tool_call` does today.
- No behavior changes beyond the email feature itself are in scope for this pass — this is otherwise a structural refactor only. Any further bug fixes noticed during migration should be logged separately (e.g. in `llm_engine_fixes.md`) rather than silently folded in.

## 6. Out of scope

- Rewriting the Gemini sanitization logic itself.
- Changing the tool schema definitions in `tools_schema.py`.
- Introducing async/await or changing the `client.chat.completions.create` call shape.
