# Refactoring Plan: `services/email_service.py`

## Current State

`services/email_service.py` is **400 lines** mixing two concerns:

| Section | Lines | What it does |
|---------|-------|-------------|
| Template builders | 44–263 | `_build_itinerary_html()` — 152 lines of inline HTML string construction; `_build_plain_text()` — 64 lines of plain-text version |
| Provider implementations | 270–326 | `_send_via_smtp()`, `_send_via_sendgrid()` — SMTP/SendGrid dispatch |
| Public API | 333–400 | `send_itinerary_email()` — entry point (validation, build, send, error handling) |

The problem isn't "spaghetti" — the code is well-structured internally. The issue is that **60% of the file is HTML template string** construction, which obscures the actual email-sending logic.

## Proposed Split

```
services/
├── email_service.py      # Public API + provider dispatch (~150 lines)
└── email_templates.py    # HTML + plain-text builders (~220 lines)
```

### What moves to `email_templates.py`:
- `_build_itinerary_html()` (lines 44–196) — the entire HTML email template
- `_build_plain_text()` (lines 199–263) — the plain-text fallback
- The `from thall_lines_db import AIRLINE_NAME` import (only used in templates)
- The `textwrap` import (only used in templates)

### What stays in `email_service.py`:
- Module docstring (configuration docs)
- `_send_via_smtp()` — SMTP provider
- `_send_via_sendgrid()` — SendGrid provider
- `send_itinerary_email()` — public entry point
- Imports: `logging`, `os`, `smtplib`, `email.mime.*`

### The change in `email_service.py`:

```python
# Before:
html_body = _build_itinerary_html(report_data, pnr_label, summary_label)
plain_body = _build_plain_text(report_data, pnr_label, summary_label)

# After:
from .email_templates import build_itinerary_html, build_plain_text
html_body = build_itinerary_html(report_data, pnr_label, summary_label)
plain_body = build_plain_text(report_data, pnr_label, summary_label)
```

## Consumer Impact: Zero

Only **one file** imports from `email_service.py`:

| Consumer | Import |
|----------|--------|
| `llm/tool_dispatch/reporting.py` | `from services.email_service import send_itinerary_email` |

Since `send_itinerary_email` stays in `email_service.py`, **no external imports change**.

## Execution Order

1. Create `services/email_templates.py` with `build_itinerary_html()` and `build_plain_text()` (the `_` prefix removed since they're now the module's public API)
2. Update `services/email_service.py` — remove template functions, add import from `email_templates`
3. Smoke-test the import chain

> [!NOTE]
> This is a clean, low-risk split. The template module has no dependencies on the send logic, and the send logic just calls two template functions. No circular imports possible.
