"""Image providers for the standalone model interceptor service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class InterceptorImageProvider(Protocol):
    def resolve_image(self) -> str:
        ...


@dataclass(frozen=True, slots=True)
class StaticInterceptorImageProvider:
    image: str

    def resolve_image(self) -> str:
        if not self.image.strip():
            raise ValueError("Model interceptor image cannot be empty")
        return self.image.strip()
