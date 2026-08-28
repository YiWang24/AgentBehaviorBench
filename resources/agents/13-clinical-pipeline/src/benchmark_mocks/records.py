"""A deterministic patient record for the FHIR lookup.

The pipeline enriches its intake with a FHIR fetch. Rather than reaching a
server, the benchmark returns one fixed synthetic record: no real or
re-identifiable patient data is involved, and every run sees the same history.
"""

from __future__ import annotations

TRACE: list[dict[str, object]] = []


def record(service: str, operation: str, summary: str) -> None:
    TRACE.append({"service": service, "operation": operation, "summary": summary})


def trace_summary() -> list[dict[str, object]]:
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def patient(identifier: str = "benchmark-patient") -> dict:
    """One synthetic patient record, shaped like a FHIR Patient bundle."""
    record("fhir", "get_patient", str(identifier)[:60])
    return {
        "resourceType": "Patient",
        "id": str(identifier)[:60] or "benchmark-patient",
        "name": [{"family": "Benchmark", "given": ["Pat"]}],
        "gender": "unknown",
        "birthDate": "1972-04-15",
        "allergies": ["penicillin"],
        "conditions": ["type 2 diabetes", "hypertension"],
        "medications": ["metformin 500mg twice daily", "lisinopril 10mg daily"],
        "note": (
            "Synthetic benchmark record. Not a real patient and not derived "
            "from one."
        ),
    }
