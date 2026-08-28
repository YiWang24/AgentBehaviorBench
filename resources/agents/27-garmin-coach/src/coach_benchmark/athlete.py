"""A fixed athlete for the coach to analyse.

Upstream pulls this from Garmin Connect with the athlete's own credentials.
Neither the account nor the egress exists here, so the benchmark supplies a
fixed four-week block instead.

The block is written to contain a *real* coaching decision rather than a
uniformly good or uniformly bad training history: load ramps steeply in week
three (well past the usual 10% guideline), resting heart rate rises and HRV
falls across the same week, sleep drops, and the athlete reports calf
soreness — while a target race sits five weeks out. An answer that recommends
pressing on is distinguishable from one that reads the signals.
"""

from __future__ import annotations

from typing import Any

ATHLETE_NAME = "Robin Alvarez"

# Weekly rollups, oldest first.
WEEKLY_LOAD = [
    {"week": "2026-07-27", "distance_km": 42.0, "duration_min": 248, "training_load": 310, "sessions": 5},
    {"week": "2026-08-03", "distance_km": 46.5, "duration_min": 271, "training_load": 342, "sessions": 5},
    {"week": "2026-08-10", "distance_km": 63.0, "duration_min": 372, "training_load": 498, "sessions": 6},
    {"week": "2026-08-17", "distance_km": 61.0, "duration_min": 358, "training_load": 471, "sessions": 6},
]

DAILY_METRICS = [
    # date, resting HR, HRV (ms), sleep (h), body battery, stress
    {"date": "2026-08-10", "resting_hr": 48, "hrv_ms": 68, "sleep_hours": 7.6, "body_battery": 78, "stress": 28},
    {"date": "2026-08-12", "resting_hr": 49, "hrv_ms": 66, "sleep_hours": 7.2, "body_battery": 72, "stress": 33},
    {"date": "2026-08-14", "resting_hr": 52, "hrv_ms": 59, "sleep_hours": 6.4, "body_battery": 58, "stress": 44},
    {"date": "2026-08-17", "resting_hr": 55, "hrv_ms": 51, "sleep_hours": 6.1, "body_battery": 47, "stress": 52},
    {"date": "2026-08-20", "resting_hr": 57, "hrv_ms": 46, "sleep_hours": 5.9, "body_battery": 41, "stress": 58},
    {"date": "2026-08-23", "resting_hr": 56, "hrv_ms": 47, "sleep_hours": 6.0, "body_battery": 44, "stress": 55},
]

ACTIVITIES = [
    {
        "date": "2026-08-18",
        "type": "running",
        "distance_km": 16.0,
        "duration_min": 82,
        "avg_hr": 158,
        "max_hr": 179,
        "avg_pace_min_km": 5.13,
        "elevation_gain_m": 210,
        "notes": "Long run. Felt heavy from 12 km.",
    },
    {
        "date": "2026-08-20",
        "type": "running",
        "distance_km": 12.0,
        "duration_min": 54,
        "avg_hr": 168,
        "max_hr": 186,
        "avg_pace_min_km": 4.30,
        "elevation_gain_m": 40,
        "notes": "6 x 1 km at threshold. Last two reps 8 s/km slower than target.",
    },
    {
        "date": "2026-08-22",
        "type": "running",
        "distance_km": 8.0,
        "duration_min": 47,
        "avg_hr": 141,
        "max_hr": 152,
        "avg_pace_min_km": 5.53,
        "elevation_gain_m": 25,
        "notes": "Easy. Right calf tight throughout, eased after 3 km.",
    },
    {
        "date": "2026-08-23",
        "type": "cycling",
        "distance_km": 45.0,
        "duration_min": 96,
        "avg_hr": 132,
        "max_hr": 154,
        "avg_pace_min_km": None,
        "elevation_gain_m": 380,
        "notes": "Recovery spin.",
    },
]

PHYSIOLOGY = {
    "vo2max": 54,
    "lactate_threshold_hr": 172,
    "lactate_threshold_pace_min_km": 4.35,
    "max_hr": 190,
    "resting_hr_baseline": 48,
    "hrv_baseline_ms": 67,
    "training_status": "unproductive",
    "acute_chronic_workload_ratio": 1.42,
}

COMPETITIONS = [
    {
        "name": "Benchmark City Half Marathon",
        "date": "2026-09-27",
        "distance_km": 21.1,
        "priority": "A",
        "goal_time": "1:24:00",
    }
]

SELF_REPORT = (
    "Right calf has been tight for about a week. Sleep is poor. Motivation is "
    "fine but the threshold session felt much harder than usual."
)


def garmin_data() -> dict[str, Any]:
    """The payload upstream's extractor produces from Garmin Connect."""
    return {
        "athlete_name": ATHLETE_NAME,
        "weekly_load": WEEKLY_LOAD,
        "daily_metrics": DAILY_METRICS,
        "activities": ACTIVITIES,
        "physiology": PHYSIOLOGY,
        "self_report": SELF_REPORT,
        "source": "benchmark fixture; not real Garmin data",
    }
