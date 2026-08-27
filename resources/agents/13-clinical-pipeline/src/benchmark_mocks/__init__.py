"""Deterministic stand-ins for the clinical pipeline's non-model dependencies.

The model provider is the only permitted real dependency. The FHIR lookup is
served from a synthetic record and anything else reaching the network raises.
"""

from __future__ import annotations

from .install import install, installed
from .records import patient, reset_trace, trace_summary

__all__ = ["install", "installed", "patient", "reset_trace", "trace_summary"]
