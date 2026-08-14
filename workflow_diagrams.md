DIAGRAM 1 — APPLICATION LIFECYCLE
==================================
Paste the block below into mermaid.live:

flowchart TD
    START["User opens the application or starts a new interaction"] --> INIT{"Is this a new session?"}
    
    INIT -- Yes --> SETUP["The system sets 'needs_init' and clears session state"]
    SETUP --> LOCK_INIT["The screen instantly updates to a locked state while connecting"]
    LOCK_INIT --> RESTART["The screen unlocks and shows the clean state with greeting"]
    
    INIT -- No --> SIDEBAR["The system renders the sidebar layout"]
    
    SIDEBAR --> CART_CHECK{"Are there any flights currently in the cart?"}
    CART_CHECK -- Yes --> SIDEBAR_CART["The sidebar displays the flight cart along with a checkout button"]
    CART_CHECK -- No --> CHAT_HISTORY
    SIDEBAR_CART --> CHAT_HISTORY
    
    CHAT_HISTORY["The main window displays the entire conversation history"] --> ERR_CHECK{"Did any previous errors occur?"}
    
    ERR_CHECK -- Yes --> SHOW_ERR["The system displays a warning message to the user"]
    ERR_CHECK -- No --> INPUT_CHECK
    SHOW_ERR --> INPUT_CHECK
    
    INPUT_CHECK{"Did the user perform an action or type a message?"}
    INPUT_CHECK -- Yes --> LOCK_UI["The system flags 'is_thinking' to instantly lock the UI"]
    LOCK_UI --> PROCESS_ACTION["The application sends the user input to the AI engine for processing"]
    PROCESS_ACTION --> ROUTE_ACTION{"Does the action require data or interface updates?"}
    ROUTE_ACTION -- "Data Tool" --> DISPATCHER["The AI requests data and the dispatcher fetches it securely from the MySQL database"]
    ROUTE_ACTION -- "Interface Tool" --> UI_STATE["The AI updates the interface or cart state directly"]
    DISPATCHER --> REFRESH
    UI_STATE --> REFRESH
    REFRESH["The screen unlocks and updates to reflect the new state"]
    
    INPUT_CHECK -- No --> IDLE["The system waits for the user to provide input"]
    
    style START fill:#1a1a2e,stroke:#e94560,color:#fff
    style RESTART fill:#1a1a2e,stroke:#e94560,color:#fff
    style REFRESH fill:#1a1a2e,stroke:#e94560,color:#fff
    style IDLE fill:#0f3460,stroke:#16213e,color:#fff
    style SETUP fill:#533483,stroke:#2b2d42,color:#fff
    style LOCK_INIT fill:#e94560,stroke:#1a1a2e,color:#fff
    style LOCK_UI fill:#e94560,stroke:#1a1a2e,color:#fff


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


DIAGRAM 7 — CONVERSATIONAL AI LOGIC
====================================
Paste the block below into mermaid.live:

flowchart TD
    GREET["The AI greets the user and asks how it can help"] --> INTENT{"How should the user input be classified?"}
    
    INTENT -- "Off-Topic" --> PIVOT["The AI pivots the conversation smoothly back to booking a flight"] --> INTENT
    INTENT -- "Relative Dates" --> CTX["The AI checks the calendar to determine the exact travel dates"] --> BOOKING_SEQ
    INTENT -- "Unserviced Route" --> ALT["The AI queries the MySQL database to see that the route is unavailable and offers the closest alternative"]
    ALT -- "User Accepts" --> BOOKING_SEQ
    INTENT -- "Valid Booking Request" --> BOOKING_SEQ
    
    BOOKING_SEQ{"Are any required booking fields missing?"}
    BOOKING_SEQ -- "Fields Missing" --> INFER{"Can the missing fields be inferred from the conversation context?"}
    INFER -- Yes --> PREFILL["The AI pre-fills the missing fields using context"] --> BOOKING_SEQ
    INFER -- No --> ASK["The AI asks the user one specific question to fill the missing field"] --> WAIT_REPLY["The system waits for the user to reply"] --> BOOKING_SEQ
    
    BOOKING_SEQ -- "Invalid Data" --> CALLOUT["The AI informs the user about the invalid data and asks for correct information"] --> WAIT_REPLY
    
    BOOKING_SEQ -- "All Fields Collected" --> AVAIL["The AI queries the MySQL database to check if there are enough available seats"]
    AVAIL --> RECAP["The AI presents a numbered recap of the trip including layovers and asks for confirmation"]
    RECAP --> CONFIRM{"Does the user confirm the trip details?"}
    
    CONFIRM -- No --> EDIT["The AI asks the user what they want to change"] --> WAIT_REPLY
    CONFIRM -- Yes --> WIDGET["The AI triggers a state update to add the flight to the shopping cart"]
    
    WIDGET --> PROMPT_CART["The AI asks if the user wants to add another flight or proceed to checkout"]
    PROMPT_CART --> NEXT_STEP{"What does the user choose to do?"}
    
    NEXT_STEP -- "Add another flight" --> BOOKING_SEQ
    NEXT_STEP -- "Check out" --> AUTH_FORM["The AI triggers the interface to render a secure authentication form"]
    
    AUTH_FORM --> AUTH_CHECK{"The authentication provider securely checks the credentials against the MySQL database"}
    AUTH_CHECK -- "Invalid" --> AUTH_FORM
    AUTH_CHECK -- "Valid" --> PAX_FORM["The AI triggers the interface to render a secure form for passenger details"]

    PAX_FORM --> PAX_CHECK{"The system validates the passenger details and identity checksums"}
    PAX_CHECK -- "Invalid" --> PAX_FORM
    PAX_CHECK -- "Valid" --> PAY_FORM["The AI triggers the interface to render a secure payment form"]

    PAY_FORM --> PAY_CHECK{"The payment gateway validates the credit card information"}
    PAY_CHECK -- "Invalid" --> PAY_FORM
    PAY_CHECK -- "Valid" --> FINAL_REPORT["The AI generates a final report detailing the fare, taxes, and fees"]
    
    style GREET fill:#1a1a2e,stroke:#e94560,color:#fff
    style FINAL_REPORT fill:#e94560,stroke:#1a1a2e,color:#fff
    style BOOKING_SEQ fill:#533483,stroke:#2b2d42,color:#fff
    style WIDGET fill:#0f3460,stroke:#16213e,color:#fff
    style AUTH_FORM fill:#0f3460,stroke:#16213e,color:#fff
    style PAX_FORM fill:#0f3460,stroke:#16213e,color:#fff
    style PAY_FORM fill:#0f3460,stroke:#16213e,color:#fff
