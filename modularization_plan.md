# Architecture Modularization Plan for Airway Chatbot

Currently, `app.py` is over 1,000 lines long, mixing UI rendering, API communication, raw JSON tool schemas, and chat history sanitization. To make the project maintainable, scalable, and easy to test, we need to separate these concerns. 

I propose splitting `app.py` into the following **4 distinct modules**:

---

### 1. `tools_schema.py` (The Definitions)
**Responsibility:** Pure configuration and schema definitions.
**What moves here:**
- `flight_widget_tool`
- `final_report_tool`
- `check_availability_tool`
- `remove_flight_tool`
- `db_query_tool`
- `context_tool`

**Why:** These JSON schemas take up hundreds of lines. Moving them into a dedicated file makes it incredibly easy to see, edit, or add new capabilities to the bot without scrolling past UI code.

---

### 2. `ui_components.py` (The Visuals)
**Responsibility:** Streamlit component rendering and UI logic.
**What moves here:**
- `render_flight_card(flight_cart)`
- `render_final_report(report_data)`
- `_build_transcript()`
- `_build_raw_log()`

**Why:** If you want to change the color of a button or the layout of the shopping cart, you shouldn't have to touch the core logic of the chatbot. This isolates the frontend from the backend.

---

### 3. `llm_engine.py` (The Brains / API Backend)
**Responsibility:** Handling all communication with the Gemini API and data formatting, **completely independent of Streamlit**.
**What moves here:**
- `_call_llm()` (rewritten to take arguments and return data, rather than mutating `st.session_state` directly)
- `_sanitize_for_gemini(messages)`
- `_truncate_tool_results(messages)`
- `_extract_code(value)`
- The tool-dispatch block.

**Why:** By decoupling this engine from `st.session_state`, it becomes a portable, pure-Python backend. When you migrate to a real website later, this exact file can be wrapped in a FastAPI or Flask route, and your React/Vue frontend can simply communicate with it via JSON over HTTP.

---

### 4. `app.py` (The Controller / Temporary Frontend)
**Responsibility:** The main execution loop and session state management for the Streamlit prototype.
**What remains here:**
- `st.set_page_config(...)`
- Initializing `st.session_state` variables.
- The main `for message in st.session_state.messages:` render loop.
- Handling `st.chat_input` and passing data to `llm_engine.py`.

**Why:** `app.py` acts strictly as the Streamlit adapter. When you build your real website, you will simply throw this file and `ui_components.py` away, replacing them with your web frontend.

---

### Recommended Action Plan
If you agree with this structure, we can execute the refactor one file at a time to ensure nothing breaks:
1. Extract `tools_schema.py` first (easiest and safest).
2. Extract `ui_components.py`.
3. Extract `llm_engine.py` and finalize the slim `app.py`.

---

### Future: Database Migration & Prompt Optimization
You are absolutely correct. Injecting the entire `route_catalogue()` into the `SYSTEM_PROMPT` is a hack for the prototype. In a production environment with thousands of routes, this would destroy your context window, increase latency, and cost a fortune in API tokens.

When moving to a real website, the architecture should evolve as follows:

1. **Clean the System Prompt:** Remove the hardcoded route list from `SYSTEM_PROMPT`. The bot should be instructed to *always* use its `query_database` tool when asked about destinations or flights.
2. **Strictly Typed Tool Calls (No Raw SQL):** The LLM should *never* generate raw SQL (this is a massive security risk for SQL injection or hallucinated tables). It should continue using the semantic tools we've defined (e.g., `{"operation": "get_route_details", "departure": "IST", "arrival": "LHR"}`).
3. **ORM / Backend Integration:** In your new backend (e.g., FastAPI), the Python functions triggered by those tool calls (like `db_get_route_details`) will be rewritten to execute safe, parameterized SQL queries (via SQLAlchemy, psycopg2, etc.) against your real Postgres/MySQL database.
4. **Data Isolation:** `thall_lines_db.py` will simply become `database_connector.py`, housing the ORM models and connection strings, fully isolating the database layer from the LLM engine.

---

### Future: Model Agnosticism & Avoiding Vendor Lock-in
Currently, `_sanitize_for_gemini` and the API payload are tightly coupled to Gemini's specific quirks (like its strict turn-sequence rules and tool-call schema requirements). To easily swap to OpenAI, Claude, or a local Llama 3 instance in the future, you should implement the **Adapter Pattern**:

1. **Standard Internal Format:** Your `llm_engine.py` should use a universal, standardized message format internally. 
2. **Provider Adapters:** Instead of calling `client.chat.completions.create` directly in the core logic, route the call through a provider class (e.g., `GeminiAdapter`, `LocalLlamaAdapter`). 
   - `GeminiAdapter` will run `_sanitize_for_gemini()` before sending the request.
   - `LocalLlamaAdapter` might format the tools differently or wrap them in a specific XML system prompt.
3. **Consider LiteLLM:** Rather than building these adapters yourself, look into an open-source proxy library like **LiteLLM**. It acts as a universal translator, allowing you to use the standard OpenAI SDK syntax while easily swapping out the `model=` parameter to route to Anthropic, local Ollama, or Gemini with zero code changes.
