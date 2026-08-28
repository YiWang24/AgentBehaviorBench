"""Deterministic flight and hotel inventory.

Upstream queries Google Flights and Google Hotels through SerpAPI. The
benchmark has no SerpAPI key and no egress, so the inventory is generated from
the query itself: the same route on the same dates always returns the same
options, and different routes return visibly different ones.

The shapes match what the upstream tools return — ``best_flights`` entries and
hotel ``properties`` entries — because the model is shown the raw structure and
the system prompt asks it to quote prices, logos, and booking links from it.
"""

from __future__ import annotations

import hashlib

_AIRLINES = [
    ("Benchmark Atlantic", "BA"),
    ("Fixture Airways", "FX"),
    ("Offline Air", "OA"),
]

_HOTEL_NAMES = [
    "The Benchmark Grand",
    "Fixture Park Hotel",
    "Offline Suites",
    "Placeholder Inn",
    "Deterministic Lodge",
]


def _seed(*parts: object) -> int:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def _price(seed: int, low: int, high: int) -> int:
    return low + (seed % max(1, high - low))


def best_flights(
    departure: str | None,
    arrival: str | None,
    outbound_date: str | None,
    return_date: str | None,
    adults: int = 1,
) -> list[dict[str, object]]:
    departure = (departure or "???").upper()
    arrival = (arrival or "???").upper()
    flights = []
    for index, (airline, code) in enumerate(_AIRLINES):
        seed = _seed(departure, arrival, outbound_date, code)
        duration = 180 + (seed % 420)
        price = _price(seed, 210, 1400) * max(1, int(adults or 1))
        flights.append(
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": f"{departure} Airport",
                            "id": departure,
                            "time": f"{outbound_date} {6 + index * 4:02d}:15",
                        },
                        "arrival_airport": {
                            "name": f"{arrival} Airport",
                            "id": arrival,
                            "time": f"{outbound_date} {(6 + index * 4 + duration // 60) % 24:02d}:{duration % 60:02d}",
                        },
                        "duration": duration,
                        "airplane": "Benchmark 000",
                        "airline": airline,
                        "airline_logo": f"https://benchmark.invalid/airlines/{code}.png",
                        "travel_class": "Economy",
                        "flight_number": f"{code} {1000 + (seed % 8999)}",
                    }
                ],
                "total_duration": duration,
                "price": price,
                "type": "Round trip" if return_date else "One way",
                "airline_logo": f"https://benchmark.invalid/airlines/{code}.png",
                "booking_token": f"benchmark-{seed:08x}",
            }
        )
    return sorted(flights, key=lambda f: f["price"])


def properties(
    location: str,
    check_in_date: str | None,
    check_out_date: str | None,
    hotel_class: str | None = None,
    adults: int = 1,
) -> list[dict[str, object]]:
    hotels = []
    for index, name in enumerate(_HOTEL_NAMES):
        seed = _seed(location, check_in_date, name)
        rate = _price(seed, 90, 700)
        nights = 6
        stars = 3 + (seed % 3)
        if hotel_class:
            wanted = {c.strip() for c in str(hotel_class).split(",") if c.strip().isdigit()}
            if wanted and str(stars) not in wanted:
                continue
        hotels.append(
            {
                "name": name,
                "description": (
                    f"A benchmark fixture hotel in {location}. No such property "
                    "exists; the record is generated for testing."
                ),
                "link": f"https://benchmark.invalid/hotels/{seed:08x}",
                "gps_coordinates": {"latitude": 0.0, "longitude": 0.0},
                "check_in_time": "3:00 PM",
                "check_out_time": "11:00 AM",
                "rate_per_night": {"lowest": f"${rate}", "extracted_lowest": rate},
                "total_rate": {
                    "lowest": f"${rate * nights}",
                    "extracted_lowest": rate * nights,
                },
                "overall_rating": round(3.5 + (seed % 15) / 10, 1),
                "reviews": 100 + (seed % 4000),
                "hotel_class": f"{stars}-star hotel",
                "extracted_hotel_class": stars,
                "amenities": ["Free Wi-Fi", "Air conditioning", "Restaurant"],
                "images": [{"thumbnail": f"https://benchmark.invalid/hotels/{seed:08x}.jpg"}],
            }
        )
    return hotels[:5]
