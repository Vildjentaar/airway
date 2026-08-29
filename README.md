# ✈️ Airway — AI-Powered Airline Booking Assistant

An end-to-end conversational AI flight booking system built with **Streamlit**, **Gemini**, and **MySQL**. The assistant handles the complete booking lifecycle — from route search and cart management through a multi-step secure checkout with passenger details, seat selection, luggage, extras, payment, and email confirmation.

> **Note:** This was a demo project built to learn and integrate multiple technologies (LLM tool-calling, prompt engineering, Streamlit UI, MySQL, Docker, SMTP). It is not production-ready.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Streamlit |
| **LLM** | Google Gemini 3.5 Flash Lite (via OpenAI-compatible API) |
| **Database** | MySQL 8.4 (Dockerized) |
| **Email** | SMTP (itinerary confirmation) |
| **Infrastructure** | Docker Compose, Dev Containers |
| **Language** | Python 3.11 |

---

## Architecture

The application follows a layered architecture with strict separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│  Streamlit UI (app.py)                                  │
│  Session state, chat render loop, sidebar controls      │
├─────────────────────────────────────────────────────────┤
│  LLM Engine (llm/)                                      │
│  Gemini API calls, history sanitization, tool dispatch  │
├──────────────┬──────────────────────────────────────────┤
│  Tool Layer  │  Services & Data                         │
│  tool_dispatch/  │  services/accounts.py                │
│  schemas.py      │  services/email_service.py           │
│  tool_policy.py  │  data/seat_data.py, luggage, extras  │
├──────────────┴──────────────────────────────────────────┤
│  Database Layer (database/db.py → MySQL)                │
│  the db/ package — parameterized queries only         │
└─────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- The LLM engine is **deliberately independent of Streamlit** — it takes plain Python data in and returns plain data out, making it portable to any web framework.
- The LLM **never sees raw SQL** — all database access goes through parameterized repository functions.
- Sensitive user data (email, payment) is **never passed to the LLM** — it's injected server-side.
- Tool availability is **state-driven** — the model only sees tools relevant to the current booking phase.

### Flow Diagrams

<details>
<summary>Application Lifecycle</summary>

![Application Lifecycle](diagrams/APPLICATION%20LIFECYCLE.png)
</details>

<details>
<summary>Conversational AI Logic</summary>

![Conversational AI Logic](diagrams/CONVERSATIONAL%20AI%20LOGIC.png)
</details>

---

## Features

- **Natural language flight search** — supports city names, airport codes, and relative dates ("next Monday")
- **Shopping cart model** — add multiple flights before checkout (one-way, round-trip, multi-city)
- **Connecting itinerary search** — finds one-stop routes through hub airports with layover calculation
- **Multi-step secure checkout** — auth → passenger details → seat selection → luggage → extras → payment
- **Automated email confirmation** — sends an HTML itinerary email with fare breakdown
- **Bilingual support** — mirrors the user's language (English / Turkish)
- **Session export** — download conversation transcript (Markdown) or full debug log (JSON)
- **Prompt injection resistance** — strict domain boundaries, immutable system instructions

---

## Project Structure

```
airway/
├── app.py                  # Streamlit entrypoint & session controller
├── system_prompt.py        # LLM system prompt with behavioral rules
├── booking_context.py      # Date/time context helpers for tool calls
├── pricing.py              # Fare calculation (class multipliers, taxes, fees)
├── payment.py              # Payment gateway stubs
├── the db/ package       # SQL-backed flight & booking repository
│
├── llm/                    # LLM orchestration package
│   ├── engine.py           # Gemini API call loop & tool-call handling
│   ├── config.py           # Model name, token limits, loop constants
│   ├── schemas.py          # Tool/function definitions (JSON schemas)
│   ├── tool_policy.py      # State-driven tool availability rules
│   ├── history_sanitizer.py # Message cleanup for Gemini's turn-sequence rules
│   ├── flight_validation.py # Cart data validation
│   └── tool_dispatch/      # One handler per tool category
│       ├── dispatcher.py   # Allowlisted tool router
│       ├── cart.py          # generate_flight_widget, remove_flight
│       ├── lookups.py      # DB search/query passthrough
│       ├── capacity.py     # Seat availability checks
│       ├── reporting.py    # Final report & email dispatch
│       ├── forms.py        # Secure form rendering & TCKN validation
│       ├── context.py      # Date/time context tool
│       └── unknown.py      # Fallback for unrecognized tools
│
├── UI/                     # Streamlit UI components
│   ├── forms/              # Checkout form renderers (auth, passenger, seat, etc.)
│   ├── validation/         # Input validation rules (name, passenger, payment)
│   ├── flight_cart.py      # Sidebar cart widget
│   ├── final_report.py     # E-ticket summary renderer
│   └── export.py           # Transcript & debug log builders
│
├── services/               # Business logic services
│   ├── accounts.py         # Auth provider & TCKN validation
│   └── email_service.py    # SMTP email with HTML template
│
├── data/                   # Static ancillary configuration
│   ├── seat_data.py        # Available seats by class
│   ├── luggage_data.py     # Luggage options & pricing
│   └── extras_data.py      # Add-on services (meals, insurance, etc.)
│
├── database/
│   └── db.py               # MySQL connection pool & query helpers
│
├── mysql/init/             # Docker entrypoint SQL scripts
│   ├── 01-schema.sql       # Tables: airports, flights, flight_legs, bookings
│   └── 02-ancillary.sql    # Seed data for ancillary services
│
├── scripts/                # Dev utilities & data migrations
│   ├── mock_data.py        # Original in-memory DB (archived, pre-MySQL)
│   ├── migrate_to_mysql.py # One-time migration from mock_data → MySQL
│   ├── migrate_aiven.py    # Cloud MySQL migration helper
│   ├── run_sql.py          # Ad-hoc SQL runner
│   └── self_tests.py       # Sanity checks for routes, pricing, auth
│
├── diagrams/               # Architecture flowcharts
├── docker-compose.yml      # MySQL 8.4 + Adminer
├── .devcontainer/          # GitHub Codespaces / VS Code Dev Container
└── requirements.txt
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- A [Google AI Studio](https://aistudio.google.com/) API key (Gemini)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/<your-username>/airway.git
   cd airway
   ```

2. **Create a `.env` file** in the project root:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   MYSQL_ROOT_PASSWORD=rootpass
   MYSQL_DATABASE=thall_lines
   MYSQL_USER=thall_app
   MYSQL_PASSWORD=yourpassword
   MYSQL_HOST=127.0.0.1
   MYSQL_PORT=3306
   ```

3. **Start the database**
   ```bash
   docker compose up -d
   ```
   This spins up MySQL 8.4 and auto-runs the schema + seed scripts from `mysql/init/`.

4. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run the app**
   ```bash
   streamlit run app.py
   ```
   Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## What I Learned

This project was a hands-on exploration of:

- **LLM tool-calling patterns** — structuring function schemas, managing multi-turn tool loops, and handling edge cases (malformed JSON, hallucinated tool calls, circuit-breaking infinite loops)
- **Prompt engineering** — building a detailed system prompt with behavioral guardrails, anti-hallucination rules, and domain boundaries
- **Conversational state management** — maintaining a shopping cart, checkout pipeline, and form rendering sequence through Streamlit's session state
- **Security considerations** — preventing the LLM from seeing sensitive data, parameterized SQL only, server-side email injection
- **Streamlit as a rapid prototyping tool** — and its limitations for complex interactive flows

---

## License

This project is for portfolio/demonstration purposes.
