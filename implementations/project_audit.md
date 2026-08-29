# Airway — Project Audit & Cleanup Plan

## 1. Directory Structure Assessment

### Current Layout (annotated)

```
airway/
├── .devcontainer/          ✅ Fine
├── .vscode/                ✅ Fine
├── .env                    ✅ Gitignored
├── .gitignore              ⚠️  Incomplete (see below)
├── airway-key.pem          ✅ Gitignored
├── docker-compose.yml      ✅ Fine
├── requirements.txt        ✅ Fine
│
├── app.py                  ✅ Streamlit entrypoint — belongs at root
├── system_prompt.py        ✅ Used by app.py — root is acceptable
├── booking_context.py      ✅ Small utility — root is acceptable
│
├── llm_engine.py           🔴 DEAD CODE — superseded by llm/ package
├── tool_dispatcher.py      ⚠️  Still imported by llm/ submodules — needs relocation
├── tools_schema.py         ⚠️  Only imported by llm_engine.py (dead) & llm/tool_policy.py
├── the db/ package       ⚠️  899-line data+query monolith — addressed in §2
│
├── accounts.py             ⚠️  Root-level business logic (auth/TCKN)
├── email_service.py        ⚠️  Root-level service (357 lines)
├── pricing.py              ✅ Standalone pricing module — root is fine
├── payment.py              ✅ Small payment stubs — root is fine
├── run_sql.py              ⚠️  Dev utility — belongs in scripts/
├── self_tests.py           ⚠️  Dev utility — belongs in scripts/ or tests/
│
├── seat_data.py            ⚠️  Static data — should be grouped
├── luggage_data.py         ⚠️  Static data — should be grouped
├── extras_data.py          ⚠️  Static data — should be grouped
│
├── database/               ✅ Clean — just db.py connection helper
├── mysql/init/             ✅ Clean — SQL schema files for Docker
├── diagrams/               ✅ Architecture diagrams
├── debug/                  ✅ Gitignored runtime output
├── scripts/                ⚠️  Contains mock_data.py + migration scripts (good concept, see notes)
├── md files/               🔴 BAD — space in folder name, internal planning docs
│
├── UI/                     ✅ Well-structured sub-package
│   ├── forms/              ✅ Each form in its own file
│   ├── validation/         ✅ Validation rules separated
│   ├── export.py           ✅
│   ├── flight_cart.py      ✅
│   ├── final_report.py     ✅
│   └── constants.py        ✅
│
├── llm/                    ✅ Well-structured sub-package
│   ├── engine.py           ✅ Modularized engine
│   ├── config.py           ✅
│   ├── history_sanitizer.py ✅
│   ├── flight_validation.py ✅
│   ├── tool_policy.py      ✅
│   └── tool_dispatch/      ✅ Each tool handler separated
│
└── __pycache__/            ⚠️  Should be gitignored (already is)
```

---

## 2. Issues & Fix Plan (Priority Order)

### 🔴 Critical — Remove Before Pushing to GitHub

| # | Issue | Fix | Status |
|---|-------|-----|--------|
| 1 | **`llm_engine.py` (782 lines) is dead code** | **Deleted** | ✅ |
| 2 | **`md files/` folder** — space in name, internal planning docs | **Deleted** | ✅ |
| 3 | **`.gitignore` is too minimal** | **Expanded** with categories (secrets, Python, IDE, debug, Docker) | ✅ |

### 🟡 Recommended — Cleaner Organization

| # | Issue | Fix | Status |
|---|-------|-----|--------|
| 4 | **3 static data files scattered at root** | Moved to `data/` | ✅ |
| 5 | **`run_sql.py` and `self_tests.py` at root** | Moved to `scripts/` | ✅ |
| 6 | **`tool_dispatcher.py` at root** | Moved to `llm/tool_dispatch/dispatcher.py` | ✅ |
| 7 | **`tools_schema.py` at root** | Moved to `llm/schemas.py` | ✅ |
| 8 | **`accounts.py` and `email_service.py` at root** | Moved to `services/` | ✅ |
| 9 | **No `README.md`** | **Created** with tech stack, architecture, features, structure, setup | ✅ |

### 🟢 Nice-to-Have

| # | Issue | Fix | Status |
|---|-------|-----|--------|
| 10 | **No `Dockerfile`** for the Streamlit app itself | Deferred — nice-to-have | ⏭️ |
| 11 | **`scripts/mock_data.py`** — old in-memory DB | Added ⚠️ ARCHIVED note to docstring | ✅ |

---

## 3. Proposed Clean Directory Structure

```
airway/
├── .gitignore              (expanded)
├── README.md               (NEW)
├── docker-compose.yml
├── requirements.txt
│
├── app.py                  (Streamlit entrypoint)
├── system_prompt.py
├── booking_context.py
├── pricing.py
├── payment.py
│
├── services/               (NEW — business logic services)
│   ├── accounts.py
│   └── email_service.py
│
├── data/                   (NEW — static ancillary configs)
│   ├── seat_data.py
│   ├── luggage_data.py
│   └── extras_data.py
│
├── database/
│   └── db.py
│
├── llm/                    (already well-organized)
│   ├── engine.py
│   ├── config.py
│   ├── schemas.py          (moved from root tools_schema.py)
│   ├── history_sanitizer.py
│   ├── flight_validation.py
│   ├── tool_policy.py
│   └── tool_dispatch/
│       ├── dispatcher.py   (moved from root tool_dispatcher.py)
│       ├── ...
│
├── UI/                     (already well-organized)
│   ├── forms/
│   ├── validation/
│   └── ...
│
├── mysql/init/
├── diagrams/
├── scripts/
│   ├── mock_data.py        (archived original in-memory DB)
│   ├── migrate_to_mysql.py
│   ├── migrate_aiven.py
│   ├── run_sql.py          (moved from root)
│   └── self_tests.py       (moved from root)
│
└── docs/                   (optional — only if you want to showcase architecture)
    └── workflow_diagrams.md
```

---

## 4. Long `.py` Files — Refactoring Candidates

> [!NOTE]
> Only files **≥ 200 lines** are listed. Files that are mostly static data (like `mock_data.py`) are noted but not refactoring targets — data is data. The focus is on files with **logic** that could benefit from being broken up.

| # | File | Lines | Type | Refactoring Notes |
|---|------|-------|------|-------------------|
| ~~1~~ | ~~`llm_engine.py`~~ | ~~683~~ | ~~Dead code~~ | ~~**Delete it** — superseded by `llm/` package~~ |
| 2 | `the db/ package` | 899 | Active logic | **Top priority.** This is a monolith: enums + helpers + 12+ query functions + booking queries all in one file. Could be split into `db/models.py`, `db/flights.py`, `db/bookings.py`, `db/airports.py` |
| 3 | `tools_schema.py` | 434 | Active (schema defs) | Mostly declarative JSON schema dicts — long but **not spaghetti**. Low priority. Moving it into `llm/` is enough cleanup |
| 4 | `email_service.py` | 357 | Active logic | Moderate — contains HTML template strings + send logic. Could extract the HTML template into a separate file or use a template engine, but for a demo project this is acceptable |
| 5 | `scripts/migrate_to_mysql.py` | 455 | Migration script | One-time script — **leave as-is** |
| 6 | `app.py` | 227 | Active (entrypoint) | Slightly long but well-commented — **fine for a Streamlit app** |
| 7 | `system_prompt.py` | 210 | Active (prompt text) | Almost entirely a big prompt string — **not spaghetti**, leave as-is |
| 8 | `llm/history_sanitizer.py` | 209 | Active logic | Well-structured, good comments — **fine** |
| 9 | `scripts/mock_data.py` | 979 | Archived data | Static data + hydration logic — **not a refactoring target** (mostly dict definitions) |

### Recommended Shortlist to Refactor

Pick from this list in priority order:

| Priority | File | Why |
|----------|------|-----|
| **1** | [the db/ package](file:///c:/Users/THALL1/Desktop/airway/the db/ package) (899 lines) | Monolith with 6 distinct concerns (enums, helpers, flight queries, airport queries, booking queries, capacity checks). A portfolio reviewer would notice this immediately. |
| **2** | [email_service.py](file:///c:/Users/THALL1/Desktop/airway/email_service.py) (357 lines) | Mixing HTML template construction with email sending logic. Separating the template would improve readability. |
| **3** | [tools_schema.py](file:///c:/Users/THALL1/Desktop/airway/tools_schema.py) (434 lines) | Not really "spaghetti" (it's declarative schema defs), but it's long. Moving it to `llm/schemas.py` is sufficient cleanup. |

---

## 5. Recommended Order of Operations

1. ✂️ **Delete dead code** (`llm_engine.py`, `md files/`)
2. 📁 **Reorganize files** into `services/`, `data/`, move utilities to `scripts/`
3. 📝 **Update imports** across the codebase to match new locations
4. 📋 **Expand `.gitignore`**
5. 📖 **Create `README.md`**
6. 🔧 **Refactor `the db/ package`** (optional, highest-impact)
7. 🔧 **Refactor `email_service.py`** (optional, moderate-impact)

> [!IMPORTANT]
> Steps 1–5 are pure file moves and cleanup — **zero risk of breaking functionality**. Steps 6–7 involve actual code changes and would need testing afterward.
