"""
tools_schema.py
----------------
Pure configuration module. Holds every JSON tool/function schema the LLM
(Gemini, via the OpenAI-compatible endpoint) can call.

No Streamlit, no session state, no business logic lives here — just
declarative schema definitions. This makes it trivial to see, edit, or add
new bot capabilities without scrolling past UI or engine code.
"""

from thall_lines_db import AIRLINE_NAME

flight_widget_tool = [
    {
        "type": "function",
        "function": {
            "name": "generate_flight_widget",
            "description": "Trigger this function ONLY when the user has confirmed their trip details and you are ready to generate the final visual summary card for the flight.",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure_point": {
                        "type": "string",
                        "description": "The city or airport code the user is flying from (e.g., Istanbul, IST)."
                    },
                    "arrival_point": {
                        "type": "string",
                        "description": "The city or airport code the user is flying to (e.g., Baku, GYD)."
                    },
                    "trip_type": {
                        "type": "string",
                        "enum": ["One-way", "Round-trip", "Multi-city"],
                        "description": "Whether the flight is one-way, round-trip, or multi-city."
                    },
                    "departure_date": {
                        "type": "string",
                        "description": "The departure date agreed upon (format MUST be YYYY-MM-DD)."
                    },
                    "return_date": {
                        "type": "string",
                        "description": "The return date, if applicable. Leave blank if One-way or Multi-city."
                    },
                    "departure_time": {
                        "type": "string",
                        "description": "Generate a realistic mock departure time (e.g., 08:15)."
                    },
                    "arrival_time": {
                        "type": "string",
                        "description": "Generate a realistic mock arrival time based on the distance (e.g., 10:30)."
                    },
                    "flight_duration": {
                        "type": "string",
                        "description": "Generate a realistic mock flight duration (e.g., 2h 15m)."
                    },
                    "transfer_status": {
                        "type": "string",
                        "enum": ["Direct", "Connecting"],
                        "description": "Transfer status from the flight database."
                    },
                    "airline_name": {
                        "type": "string",
                        "description": f"The airline name (always {AIRLINE_NAME})."
                    },
                    "flight_number": {
                        "type": "string",
                        "description": "Flight number from the flight database (e.g., PX-0752)."
                    },
                    "price_tl": {
                        "type": "integer",
                        "description": "Total trip price in TL from the database."
                    },
                    "ticket_class": {
                        "type": "string",
                        "enum": ["Economy", "Business"],
                        "description": "Ticket class selected by the user."
                    },
                    "adult_count": {
                        "type": "integer",
                        "description": "Number of adult passengers (age 12+)."
                    },
                    "child_count": {
                        "type": "integer",
                        "description": "Number of child passengers (age 2-12)."
                    },
                    "baby_count": {
                        "type": "integer",
                        "description": "Number of baby passengers (age 0-2)."
                    }
                },
                "required": [
                    "departure_point", "arrival_point", "trip_type", "departure_date",
                    "departure_time", "arrival_time", "flight_duration",
                    "transfer_status", "airline_name", "flight_number", "price_tl",
                    "ticket_class", "adult_count", "child_count", "baby_count"
                ]
            }
        }
    }
]

final_report_tool = [
    {
        "type": "function",
        "function": {
            "name": "generate_final_report",
            "description": "Trigger this ONLY after the user confirms their flight details, OR to forcefully terminate the session if the user is repeatedly spamming, trolling, or refusing to progress. This generates the final analytical report and ends the chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "passenger_summary": {
                        "type": "string",
                        "description": "A short summary of the passenger's travel data."
                    },
                    "process_smoothness": {
                        "type": "string",
                        "enum": ["Smooth", "Minor Issues", "Problematic"],
                        "description": "Rate how easily the transaction was completed."
                    },
                    "issues_encountered": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List any missing info, skipped steps, or off-topic questions the user attempted. If none, return an empty array."
                    },
                    "overall_evaluation": {
                        "type": "string",
                        "description": "A brief, final evaluation of the AI's performance and user experience."
                    }
                },
                "required": ["passenger_summary", "process_smoothness", "issues_encountered", "overall_evaluation"]
            }
        }
    }
]

check_availability_tool = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if a flight has enough capacity for the requested number of passengers. Must be called before booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": "string"},
                    "date": {"type": "string", "description": "Date of departure (YYYY-MM-DD)"},
                    "passengers": {"type": "integer"}
                },
                "required": ["flight_number", "date", "passengers"]
            }
        }
    }
]

remove_flight_tool = [
    {
        "type": "function",
        "function": {
            "name": "remove_flight_from_cart",
            "description": "Remove a specific flight from the user's cart if they change their mind or make a mistake.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": "string", "description": "The flight number to remove."}
                },
                "required": ["flight_number"]
            }
        }
    }
]

db_query_tool = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Query the flight database to look up route information, airport details, "
                "schedules, or booking status. Use this to answer user questions. "
                "This is READ-ONLY — you cannot insert, update, or delete any data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "list_all_routes",
                            "get_route_details",
                            "list_airports",
                            "get_airport_info",
                            "list_bookings",
                        ],
                        "description": (
                            "The specific read-only operation to run. "
                            "list_all_routes: all operated routes. "
                            "get_route_details: one specific route (requires departure + arrival). "
                            "list_airports: all serviced airports. "
                            "get_airport_info: details for one airport (requires airport_code). "
                            "list_bookings: existing booking records."
                        ),
                    },
                    "departure": {
                        "type": "string",
                        "description": "Departure city or IATA code. Required for get_route_details.",
                    },
                    "arrival": {
                        "type": "string",
                        "description": "Arrival city or IATA code. Required for get_route_details.",
                    },
                    "airport_code": {
                        "type": "string",
                        "description": "IATA code or city name. Required for get_airport_info.",
                    },
                },
                "required": ["operation"],
            },
        },
    }
]

context_tool = [
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": (
                "Retrieve live contextual information such as the current date/time, "
                "pre-computed relative dates (today, tomorrow, this weekend, etc.), "
                "or the allowed booking window. Call this BEFORE asking the user to "
                "confirm a date whenever they use relative language like 'today', "
                "'tomorrow', 'next Monday', or 'this weekend'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": [
                            "current_datetime",
                            "relative_dates",
                            "booking_window",
                        ],
                        "description": (
                            "current_datetime: today's date, current time, day of week. "
                            "relative_dates: pre-computed dates for tomorrow, this weekend, next Monday, etc. "
                            "booking_window: earliest and latest allowed departure dates."
                        ),
                    },
                },
                "required": ["info_type"],
            },
        },
    }
]

render_secure_form_tool = [
    {
        "type": "function",
        "function": {
            "name": "render_secure_form",
            "description": "Render a secure UI form during the checkout flow to collect sensitive info. Use this INSTEAD of asking for auth, passenger details, or credit cards in the chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "form_type": {
                        "type": "string",
                        "enum": ["auth", "passenger_details", "payment"],
                        "description": "Which form to render. Flow is ALWAYS: auth -> passenger_details -> payment."
                    }
                },
                "required": ["form_type"]
            }
        }
    }
]

validate_tckn_tool = [
    {
        "type": "function",
        "function": {
            "name": "validate_tckn",
            "description": "Validate a Turkish Citizen Identity Number (TCKN) using the official checksum algorithm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tckn": {
                        "type": "string",
                        "description": "The 11-digit TCKN to validate."
                    }
                },
                "required": ["tckn"]
            }
        }
    }
]

# Convenience bundles, mirroring how app.py assembles the active tool list
# depending on chatbot state.
ALL_TOOLS = (
    flight_widget_tool
    + final_report_tool
    + db_query_tool
    + context_tool
    + check_availability_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
)

PRE_CART_TOOLS = flight_widget_tool + db_query_tool + context_tool + check_availability_tool

POST_CART_TOOLS = (
    flight_widget_tool
    + final_report_tool
    + db_query_tool
    + context_tool
    + check_availability_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
)
