DIAGRAM 1 — APPLICATION LIFECYCLE
==================================
Paste the block below into mermaid.live:

flowchart TD
    START(["🔄 Streamlit Page Load / Rerun"]) --> CONFIG["st.set_page_config\nSet title, icon, layout"]
    CONFIG --> SIDEBAR["Render Sidebar\n(Cart, Controls, Exports)"]
    SIDEBAR --> INIT{"Session State\nInitialized?"}
    INIT -- No --> SETUP["Initialize session_state:\n• messages (system + welcome)\n• flight_data (empty list)\n• report_data (None)\n• last_error (None)\n• pending_user_message (None)"]
    SETUP --> RENDER
    INIT -- Yes --> RENDER
    RENDER["Render Chat History Loop\n(iterate st.session_state.messages)"] --> CART_CHECK{"Valid flight_data\nexists & no report?"}
    CART_CHECK -- Yes --> SIDEBAR_CART["Show 🛒 Cart in Sidebar\nwith Checkout button"]
    CART_CHECK -- No --> ERR_CHECK
    SIDEBAR_CART --> ERR_CHECK
    ERR_CHECK{"last_error\nis set?"} -- Yes --> SHOW_ERR["Display ⚠️ error banner\nClear last_error"]
    ERR_CHECK -- No --> PENDING
    SHOW_ERR --> PENDING
    PENDING{"pending_user_message\nis set?"} -- Yes --> INJECT["Append pending msg\nto messages list\n(merge if last is user)"]
    INJECT --> CALL_LLM_P["_call_llm()\nwith spinner 'Confirming…'"]
    CALL_LLM_P --> RERUN(["st.rerun()"])
    PENDING -- No --> CHAT_INPUT{"User types in\nchat_input?"}
    CHAT_INPUT -- Yes --> APPEND_MSG["Append user message\n(merge if last is user)"]
    APPEND_MSG --> CALL_LLM_U["_call_llm()\nwith spinner 'Thinking…'"]
    CALL_LLM_U --> RERUN
    CHAT_INPUT -- No --> IDLE(["⏳ Idle — Waiting for input"])
    style START fill:#1a1a2e,stroke:#e94560,color:#fff
    style RERUN fill:#1a1a2e,stroke:#e94560,color:#fff
    style IDLE fill:#0f3460,stroke:#16213e,color:#fff
    style SETUP fill:#533483,stroke:#2b2d42,color:#fff


DIAGRAM 2 — CHAT HISTORY RENDERING
====================================
Paste the block below into mermaid.live:

flowchart TD
    LOOP(["For each message\nin session_state.messages"]) --> ROLE{"message.role?"}
    ROLE -- "system" --> SKIP1(["Skip — never rendered"])
    ROLE -- "tool" --> TOOL_CHECK{"Has 'report_data'\nkey?"}
    TOOL_CHECK -- Yes --> RENDER_REPORT["🎯 Render Final Report\n(render_final_report)"]
    TOOL_CHECK -- No --> SKIP2(["Skip — tool results\nare internal"])
    ROLE -- "assistant" --> HIDDEN{"message.hidden\n== True?"}
    HIDDEN -- Yes --> SKIP3(["Skip — structural\nplaceholder"])
    HIDDEN -- No --> TOOL_CALLS{"Has tool_calls?"}
    TOOL_CALLS -- Yes --> SKIP4(["Skip — tool invocation\nnot shown to user"])
    TOOL_CALLS -- No --> HAS_CONTENT{"Has text content?"}
    HAS_CONTENT -- Yes --> RENDER_BOT["💬 Render assistant\nchat bubble"]
    HAS_CONTENT -- No --> SKIP5(["Skip — empty"])
    ROLE -- "user" --> RENDER_USER["👤 Render user\nchat bubble"]
    style LOOP fill:#1a1a2e,stroke:#e94560,color:#fff
    style RENDER_BOT fill:#0f3460,stroke:#16213e,color:#fff
    style RENDER_USER fill:#533483,stroke:#2b2d42,color:#fff
    style RENDER_REPORT fill:#e94560,stroke:#1a1a2e,color:#fff


DIAGRAM 3 — CORE LLM INTERACTION
==================================
Paste the block below into mermaid.live:

flowchart TD
    ENTRY(["_call_llm()"]) --> PREP["Prepare messages:\n1. Extract system msg\n2. Slice last 100 msgs\n3. _truncate_tool_results()\n4. _sanitize_for_gemini()"]
    PREP --> TOOL_SELECT{"Current State?"}
    TOOL_SELECT -- "report_data exists\nOR hidden startup msg" --> NO_TOOLS["tools = None\ntool_choice = 'none'"]
    TOOL_SELECT -- "flight_data has items" --> ALL_TOOLS["tools = widget + report\n+ db_query + context\n+ check_avail + remove\ntool_choice = 'auto'"]
    TOOL_SELECT -- "cart is empty" --> PARTIAL_TOOLS["tools = widget\n+ db_query + context\n+ check_avail\ntool_choice = 'auto'"]
    NO_TOOLS --> API_CALL
    ALL_TOOLS --> API_CALL
    PARTIAL_TOOLS --> API_CALL
    API_CALL["🌐 Gemini API Call\nmodel: gemini-3.5-flash-lite\ntemp: 0.4"] --> API_OK{"API\nSuccess?"}
    API_OK -- No --> API_FAIL["Set last_error\nReturn False"]
    API_OK -- Yes --> RESPONSE{"Response has\ntool_calls?"}
    RESPONSE -- Yes --> TOOL_BRANCH["Append raw assistant msg\n(with thought_signature)\nto history"]
    TOOL_BRANCH --> DISPATCH(["Dispatch Each Tool Call\n(see Tool Dispatch diagram)"])
    DISPATCH --> FOLLOWUP{"skip_followup\nflag set?"}
    FOLLOWUP -- No --> FOLLOWUP_CALL["🌐 Follow-up API Call\ntools = None\ntemp: 0.3"]
    FOLLOWUP -- Yes --> DONE_TRUE
    FOLLOWUP_CALL --> FU_OK{"Follow-up\nSuccess?"}
    FU_OK -- Yes --> FU_TEXT{"Has text\ncontent?"}
    FU_TEXT -- Yes --> APPEND_FU["Append assistant\nresponse to history"]
    FU_TEXT -- No --> APPEND_HIDDEN["Append hidden\nplaceholder msg"]
    FU_OK -- No --> FU_FAIL["Set last_error\nAppend fallback\nerror message"]
    APPEND_FU --> DONE_TRUE(["Return True ✅"])
    APPEND_HIDDEN --> DONE_TRUE
    FU_FAIL --> DONE_TRUE
    RESPONSE -- No --> TEXT_CHECK{"Response looks like\nraw JSON tool call?"}
    TEXT_CHECK -- Yes --> WARN["Set last_error:\n'wrong format, retry'"]
    TEXT_CHECK -- No --> APPEND_BOT["Append assistant\ntext to history"]
    WARN --> DONE_TRUE
    APPEND_BOT --> DONE_TRUE
    style ENTRY fill:#1a1a2e,stroke:#e94560,color:#fff
    style API_CALL fill:#0f3460,stroke:#16213e,color:#fff
    style FOLLOWUP_CALL fill:#0f3460,stroke:#16213e,color:#fff
    style DONE_TRUE fill:#533483,stroke:#2b2d42,color:#fff
    style API_FAIL fill:#e94560,stroke:#1a1a2e,color:#fff


DIAGRAM 4 — TOOL DISPATCH
===========================
Paste the block below into mermaid.live:

flowchart TD
    ENTRY(["For each tool_call\nin response"]) --> PARSE{"Parse JSON\narguments?"}
    PARSE -- "Malformed JSON" --> JSON_ERR["Append tool error msg\nSet last_error\nContinue to next tool"]
    PARSE -- OK --> WHICH{"function_name?"}
    WHICH -- "generate_flight_widget" --> WIDGET_VAL["Validate pax (1-9)\nValidate date format\nCheck for duplicates"]
    WIDGET_VAL --> MISSING{"Missing required\nfields or invalid?"}
    MISSING -- Yes --> MISSING_ERR["Append error"]
    MISSING -- No --> FIND["find_flight(dep, arr)\n(Check return if round-trip)"]
    FIND --> FOUND{"Route\nfound?"}
    FOUND -- No --> NO_ROUTE["Append error"]
    FOUND -- Yes --> PRICE["calculate_total_price()"]
    PRICE --> BUILD["Build verified flight dict"]
    BUILD --> CART["Append to\nflight_data cart"]
    CART --> WIDGET_MSG["Append tool success\nSet skip_followup = True"]
    WHICH -- "generate_final_report" --> CART_CHECK{"flight_data\nhas items?"}
    CART_CHECK -- No --> REPORT_ERR["Append error:\n'No flights in cart'"]
    CART_CHECK -- Yes --> REPORT["Set report_data = dict\nAppend tool msg\nSet skip_followup = True"]
    WHICH -- "check_availability" --> AVAIL["db_check_capacity()\nAppend JSON result"]
    WHICH -- "remove_flight_from_cart" --> REMOVE["Remove from flight_data\nAppend success/fail msg"]
    WHICH -- "query_database" --> DB_OP{"operation?"}
    DB_OP -- "list_all_routes" --> DB1["db_list_all_routes()"]
    DB_OP -- "get_route_details" --> DB2["db_get_route_details()"]
    DB_OP -- "list_airports" --> DB3["db_list_airports()"]
    DB_OP -- "get_airport_info" --> DB4["db_get_airport_info()"]
    DB_OP -- "list_bookings" --> DB5["db_list_bookings()"]
    DB_OP -- "unknown" --> DB_ERR["Return error"]
    DB1 --> DB_RESULT["Append JSON result\nas tool message"]
    DB2 --> DB_RESULT
    DB3 --> DB_RESULT
    DB4 --> DB_RESULT
    DB5 --> DB_RESULT
    WHICH -- "get_context" --> CTX_TYPE{"info_type?"}
    CTX_TYPE -- "current_datetime" --> CTX1["ctx_get_current_datetime()"]
    CTX_TYPE -- "relative_dates" --> CTX2["ctx_get_relative_dates()"]
    CTX_TYPE -- "booking_window" --> CTX3["ctx_get_booking_window()"]
    CTX_TYPE -- "unknown" --> CTX_ERR["Return error"]
    CTX1 --> CTX_RESULT["Append JSON result\nas tool message"]
    CTX2 --> CTX_RESULT
    CTX3 --> CTX_RESULT
    WHICH -- "unknown function" --> UNK_ERR["Append error:\n'Unknown function'"]
    style ENTRY fill:#1a1a2e,stroke:#e94560,color:#fff
    style CART fill:#533483,stroke:#2b2d42,color:#fff
    style REPORT fill:#e94560,stroke:#1a1a2e,color:#fff
    style DB_RESULT fill:#0f3460,stroke:#16213e,color:#fff
    style CTX_RESULT fill:#0f3460,stroke:#16213e,color:#fff


DIAGRAM 5 — MESSAGE SANITIZATION PIPELINE
===========================================
Paste the block below into mermaid.live:

flowchart TD
    INPUT(["Raw message list\n(system + last 100)"]) --> TRUNC["_truncate_tool_results()\nCap tool content at 800 chars"]
    TRUNC --> PASS1["Pass 1: Merge consecutive\nsame-role messages\n(user+user → single user)\n(assistant+assistant → merge)"]
    PASS1 --> PASS2["Pass 2: Remove orphaned\nassistant tool_calls whose\ntool responses were lost\ndue to history truncation"]
    PASS2 --> PASS3["Pass 3: Ensure first message\nafter system is role='user'\n(Inject hidden [System Note]\nplaceholder if needed)"]
    PASS3 --> OUTPUT(["Clean message list\nready for Gemini API"])
    style INPUT fill:#1a1a2e,stroke:#e94560,color:#fff
    style OUTPUT fill:#533483,stroke:#2b2d42,color:#fff
    style PASS1 fill:#0f3460,stroke:#16213e,color:#fff
    style PASS2 fill:#0f3460,stroke:#16213e,color:#fff
    style PASS3 fill:#0f3460,stroke:#16213e,color:#fff


DIAGRAM 6 — SIDEBAR LAYOUT
============================
Paste the block below into mermaid.live:

flowchart TD
    SIDEBAR(["📐 Sidebar"]) --> CART_EXISTS{"flight_data valid\n& no report?"}
    CART_EXISTS -- Yes --> RENDER_CART["🛒 Render Flight Cart\n(all legs + total price)\n+ Checkout & Finalize btn"]
    CART_EXISTS -- No --> CONTROLS
    RENDER_CART --> CONTROLS["🛠️ Session Controls\n🔄 Start Over button"]
    CONTROLS --> EXPORT["📥 Export Section"]
    EXPORT --> DL_TRANSCRIPT["📄 Download Transcript\n(markdown)"]
    EXPORT --> DL_JSON["🔍 Download Raw Log\n(JSON debug dump)"]
    CONTROLS -- "Start Over clicked" --> WIPE["Delete all\nsession_state keys"] --> RERUN(["st.rerun()"])
    RENDER_CART -- "Checkout clicked" --> PENDING["Set pending_user_message:\n'I am completely done\nadding flights...'"]
    style SIDEBAR fill:#1a1a2e,stroke:#e94560,color:#fff
    style RENDER_CART fill:#e94560,stroke:#1a1a2e,color:#fff
    style RERUN fill:#533483,stroke:#2b2d42,color:#fff
