"""
tools_schema.py
----------------
Pure configuration module. Holds every JSON tool/function schema the LLM
(Gemini, via the OpenAI-compatible endpoint) can call.

No Streamlit, no session state, no business logic lives here — just
declarative schema definitions. This makes it trivial to see, edit, or add
new bot capabilities without scrolling past UI or engine code.
"""

from db import AIRLINE_NAME

flight_widget_tool = [
    {
        "type": "function",
        "function": {
            "name": "generate_flight_widget",
            "description": (
                "Trigger this function ONLY when the user has confirmed their trip details "
                "and you are ready to add the flight to the cart. You only need to provide "
                "the flight_number and departure_date for each segment — the backend will "
                "automatically look up departure/arrival times, duration, route, and transfer "
                "status from the database. Do NOT pass times or durations yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_type": {
                        "type": "string",
                        "enum": ["One-way", "Round-trip", "Multi-city"],
                        "description": "Whether the flight is one-way, round-trip, or multi-city."
                    },
                    "segments": {
                        "type": "array",
                        "description": "An array of flight segments in chronological order. Only flight_number and departure_date are required — all other fields are populated by the backend.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "flight_number": {
                                    "type": "string",
                                    "description": "Flight number from the flight database (e.g., TL-0401). Must be a real flight number returned by search_flights."
                                },
                                "departure_date": {
                                    "type": "string",
                                    "description": "The departure date agreed upon (format MUST be YYYY-MM-DD)."
                                }
                            },
                            "required": ["flight_number", "departure_date"]
                        }
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
                    "trip_type", "segments",
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

search_itinerary_tool = [
    {
        "type": "function",
        "function": {
            "name": "search_itinerary",
            "description": (
                "Search for complete connected itineraries between two cities, "
                "automatically routing via hub airports when no direct flight exists. "
                "Use this when the user wants to travel between two cities that may "
                "require a connection — it returns all viable multi-leg options in a "
                "single call. This is much more reliable than calling search_flights "
                "multiple times and manually stitching legs together."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "Origin city name or airport code (e.g., Ankara or ESB)."
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination city name or airport code (e.g., Amsterdam or AMS)."
                    }
                },
                "required": ["origin", "destination"]
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
            "description": "Render a secure UI form during the checkout flow to collect sensitive info. Use this INSTEAD of asking for auth, passenger details, or credit cards in the chat. CRITICAL: Call only ONE form per turn. DO NOT batch multiple calls. Wait for the user's submission before calling the next one.",
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

send_itinerary_email_tool = [
    {
        "type": "function",
        "function": {
            "name": "send_itinerary_email",
            "description": (
                "Call this tool IMMEDIATELY after `generate_final_report` succeeds to dispatch "
                "the booking confirmation email to the passenger. "
                "The system will retrieve the destination email address automatically from the "
                "authenticated session — do NOT ask the user for their email address. "
                "Supply the PNR code and a brief passenger name summary for the email subject line."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pnr_code": {
                        "type": "string",
                        "description": (
                            "The Passenger Name Record / booking reference code to embed in the "
                            "email subject line (e.g. 'PNR-20240825-0001'). "
                            "Derive it from the booked flight numbers and today's date."
                        )
                    },
                    "passenger_name_summary": {
                        "type": "string",
                        "description": (
                            "A short, display-safe summary of who the ticket is for "
                            "(e.g. '2 passengers — A. Smith, B. Jones'). "
                            "Used only for audit logging; not inserted into the email body."
                        )
                    }
                },
                "required": ["pnr_code", "passenger_name_summary"]
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
    + search_itinerary_tool
    + context_tool
    + check_capacity_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
    + send_itinerary_email_tool
)

PRE_CART_TOOLS = flight_widget_tool + db_tools + search_itinerary_tool + context_tool + check_capacity_tool

POST_CART_TOOLS = (
    flight_widget_tool
    + final_report_tool
    + db_tools
    + search_itinerary_tool
    + context_tool
    + check_capacity_tool
    + remove_flight_tool
    + render_secure_form_tool
    + validate_tckn_tool
    + send_itinerary_email_tool
)
