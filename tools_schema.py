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

check_capacity_tool = [
    {
        "type": "function",
        "function": {
            "name": "check_capacity",
            "description": "Check if a flight has enough capacity for the requested number of passengers. Must be called before booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": "string"},
                    "departure_date": {"type": "string", "description": "Date of departure (YYYY-MM-DD)"},
                    "additional_passengers": {"type": "integer"}
                },
                "required": ["flight_number", "departure_date", "additional_passengers"]
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

db_tools = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search sellable flights between a departure and arrival city or airport code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure": {
                        "type": "string",
                        "description": "Departure city name or airport code, for example Istanbul or IST."
                    },
                    "arrival": {
                        "type": "string",
                        "description": "Arrival city name or airport code, for example London or LHR."
                    }
                },
                "required": ["departure", "arrival"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_alternative_routes",
            "description": "Find alternative routes when a direct search fails. Returns destinations reachable from the departure airport, and origins that can reach the arrival airport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure": {
                        "type": "string",
                        "description": "Departure city name or airport code, for example Istanbul or IST."
                    },
                    "arrival": {
                        "type": "string",
                        "description": "Arrival city name or airport code, for example London or LHR."
                    }
                },
                "required": ["departure", "arrival"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_route_details",
            "description": "Get full route details (including connecting legs) for a flight between departure and arrival points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure": {"type": "string"},
                    "arrival": {"type": "string"}
                },
                "required": ["departure", "arrival"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_routes",
            "description": "List all sellable routes operated by the airline.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_airports",
            "description": "List all airports serviced by the airline.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_airport_info",
            "description": "Get details for a specific airport by code or city name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "airport_code": {"type": "string"}
                },
                "required": ["airport_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_bookings",
            "description": "List all existing bookings.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking_details",
            "description": "Get details for one booking by booking ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "integer",
                        "description": "The booking ID."
                    }
                },
                "required": ["booking_id"]
            }
        }
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
                        "enum": ["auth", "passenger_details", "seat_selection", "luggage", "extras", "payment"],
                        "description": "Which form to render. Flow is ALWAYS: auth -> passenger_details -> seat_selection -> luggage -> extras -> payment."
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
    + db_tools
    + context_tool
    + check_capacity_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
)

PRE_CART_TOOLS = flight_widget_tool + db_tools + context_tool + check_capacity_tool

POST_CART_TOOLS = (
    flight_widget_tool
    + final_report_tool
    + db_tools
    + context_tool
    + check_capacity_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
)
