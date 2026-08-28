"""Wire the deterministic fixtures into the clinical pipeline.

Most of this agent's reference data already ships as Python literals — the
drug-interaction table and the ICD-10 index are module-level dicts — and the
GraphRAG service defaults to its in-memory backend. The only outbound call is
the FHIR patient lookup, which is replaced with a deterministic record.
"""

from __future__ import annotations

from . import records
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


def _patch_fhir() -> None:
    """Replace the one outbound call in the FHIR service.

    `push_to_fhir_server` POSTs a resource with httpx. httpx cannot be blocked
    wholesale — it is the model SDK's transport — so this call is replaced
    directly. The other functions in the module are pure resource builders and
    are left alone.
    """
    from clinical_agent.services import fhir_service

    async def _push(resource: dict, *args: object, **kwargs: object) -> dict:
        records.record("fhir", "push", str(resource.get("resourceType", "resource")))
        return {
            "resourceType": resource.get("resourceType", "Resource"),
            "id": "benchmark-accepted",
            "status": "accepted",
        }

    fhir_service.push_to_fhir_server = _push


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_fhir()
    install_network_guard()
    _installed = True
