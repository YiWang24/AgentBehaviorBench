"""Fail loudly when a non-LLM service is reached over the network.

The Anthropic SDK travels over ``httpx``, so ``httpx`` cannot be blocked
wholesale. The research tool also fetches pages with ``httpx.get``, which the
corpus replaces directly; what remains here is a guard on the other clients so
a gap in coverage raises instead of reaching a live service.
"""

from __future__ import annotations


class BenchmarkNetworkBlocked(RuntimeError):
    """Raised when mock coverage is missing and real egress was attempted."""


def _target(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    url = kwargs.get("url")
    if isinstance(url, str):
        return url
    for value in args:
        if isinstance(value, str) and "://" in value:
            return value
    return "<unknown>"


def _blocked(client: str):
    def _raise(*args: object, **kwargs: object):
        raise BenchmarkNetworkBlocked(
            f"{client} egress to {_target(args, kwargs)!r} is blocked in the "
            "benchmark runtime. Add deterministic coverage to benchmark_mocks "
            "instead of calling a live service."
        )

    return _raise


def install() -> None:
    """Patch non-LLM HTTP clients to raise. Safe to call more than once."""
    try:
        import requests
    except ModuleNotFoundError:  # pragma: no cover - optional
        pass
    else:
        requests.Session.request = _blocked("requests")  # type: ignore[method-assign]

    import urllib.request

    urllib.request.urlopen = _blocked("urllib")  # type: ignore[assignment]
