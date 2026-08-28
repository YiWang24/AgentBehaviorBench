"""Deterministic local mocks for TradingAgents' non-LLM network dependencies."""

from .patches import apply_patches

__all__ = ["apply_patches"]
