"""
llm/tool_dispatch/forms.py
----------------------------
Handlers for identity-validation and secure-form rendering:
  - validate_tckn       (Turkish Citizen ID checksum)
  - render_secure_form  (signal the UI to mount a form component)

Note
~~~~
The ``render_secure_form`` "only once per turn" guard is *not* in this
module — it lives in ``engine.py`` as cross-call-turn bookkeeping
specific to the orchestration loop, not a property of the form tool
itself.
"""

from __future__ import annotations

import json
from typing import Optional

from services.accounts import validate_tckn


def handle_validate_tckn(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Validate a Turkish Citizen Identity Number.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False
    skip_followup = False

    tckn_str = tool_args.get("tckn", "")
    result = validate_tckn(tckn_str)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(result, ensure_ascii=False),
    })

    return report_data, skip_followup, email_sent


def handle_render_secure_form(
    tool_call,
    tool_args: dict,
    messages: list,
    flight_data: list,
    report_data,
    ancillary_data: Optional[dict] = None,
    user_email: Optional[str] = None,
):
    """Signal the UI to mount a secure form component.

    Returns ``(report_data, skip_followup, email_sent)``.
    """
    email_sent = False

    form_type = tool_args.get("form_type", "auth")
    if report_data is None:
        # We use report_data as a generic dict to signal the UI
        report_data = {}
    report_data["render_form"] = form_type

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": f"Form '{form_type}' rendered. Waiting for user submission...",
        "report_data": report_data
    })
    skip_followup = True

    return report_data, skip_followup, email_sent
