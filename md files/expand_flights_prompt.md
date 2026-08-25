You are an expert Python developer and data engineer. Your task is to expand an existing mock flight dataset for an airline booking system. 

Currently, the dataset has only 1 or 2 flights per route. I want to expand it so that customers can choose from multiple departure times in a day, with frequencies varying based on the route type.

### Requirements:
1. **Multiple Departure Times:** Generate multiple flights per day for each operated route.
2. **Variable Route Frequencies:**
   - **Domestic routes** (e.g., IST ↔ ESB, IST ↔ ADB, IST ↔ AYT): High frequency (4–6 flights per day).
   - **European / Regional routes** (e.g., IST ↔ LHR, IST ↔ CDG, IST ↔ DXB): Medium frequency (2–4 flights per day).
   - **Long-Haul routes** (e.g., IST ↔ JFK, IST ↔ NRT, IST ↔ SYD): Low frequency (1–2 flights per day).
3. **Bidirectional Integrity:** For every flight added from Origin A to Destination B, ensure there is an appropriate return flight from B to A.
4. **Data Schema Consistency:** Maintain the exact dictionary schema provided below. 
5. **Unique Identifiers:** Ensure `flight_id` and `flight_number` (e.g., 'PX-XXXX') are unique across the entire dataset. Increment `flight_id` continuously.
6. **Connecting Flights:** If you add a connecting flight (`TransferStatus.CONNECTING`), you must also generate its two underlying leg flights (`is_leg=True`) and reference their `flight_id`s in the connecting flight's `legs` list.

### Current Schema & Example Data:
Below is a sample of the current `_RAW_FLIGHTS` list from my `scripts/mock_data.py` file. Please use this as the template and return a complete, expanded Python list.

```python
from enum import Enum

class TransferStatus(str, Enum):
    DIRECT = "Direct"
    CONNECTING = "Connecting"

_AC_DOMESTIC = ("Airbus A321neo", 220)
_AC_REGIONAL = ("Boeing 737 MAX 8", 189)
_AC_EUROPE = ("Airbus A321LR", 180)
_AC_LONGHAUL = ("Boeing 787-9", 296)

_RAW_FLIGHTS = [
    # --- Example Direct Flight (Domestic) ---
    {"flight_id": 1, "flight_number": "PX-0010", "origin_code": "IST", "dest_code": "ESB", "departure_time": "07:00", "flight_minutes": 70, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1250.00, "aircraft": _AC_DOMESTIC},
    {"flight_id": 2, "flight_number": "PX-0011", "origin_code": "ESB", "dest_code": "IST", "departure_time": "09:00", "flight_minutes": 75, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 1250.00, "aircraft": _AC_DOMESTIC},
    
    # --- Example Leg Flights (Not independently sellable, is_leg=True) ---
    {"flight_id": 43, "flight_number": "PX-C100A", "origin_code": "ESB", "dest_code": "IST", "departure_time": "05:00", "flight_minutes": 75, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_DOMESTIC, "is_leg": True},
    {"flight_id": 44, "flight_number": "PX-C100B", "origin_code": "IST", "dest_code": "JFK", "departure_time": "08:30", "flight_minutes": 650, "transfer_status": TransferStatus.DIRECT, "base_price_tl": 0.0, "aircraft": _AC_LONGHAUL, "is_leg": True},
    
    # --- Example Connecting Flight (Marketed itinerary) ---
    {"flight_id": 23, "flight_number": "PX-C100", "origin_code": "ESB", "dest_code": "JFK", "transfer_status": TransferStatus.CONNECTING, "base_price_tl": 29500.00, "aircraft": _AC_LONGHAUL, "legs": [43, 44]},
]
```

### Expected Output:
Please output ONLY the fully expanded `_RAW_FLIGHTS = [...]` Python code block, ready to be copy-pasted into `scripts/mock_data.py`. Do not include explanations, just the code.
