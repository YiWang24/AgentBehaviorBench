"""The probe `verify` sends an Agent before any Case exists.

Preflight asks whether the Agent answers at all, so the text only has to invite a
reply. It deliberately says nothing an Agent could be graded against: preflight
serves synthesized model replies, and wording carries no signal worth judging.
"""

from __future__ import annotations

DEFAULT_PROBE_TEXT = "Reply with a short confirmation that you received this message."

__all__ = ["DEFAULT_PROBE_TEXT"]
