"""Fail loudly when a non-LLM service is reached over the network.

The model SDK travels over ``httpx``, which is left alone. Every other client
the research stack can reach for — ``requests`` and ``aiohttp`` for search and
scraping APIs, ``urllib`` for direct fetches — raises instead of returning
live data or an empty fallback.
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


def _blocked_async(client: str):
    async def _raise(*args: object, **kwargs: object):
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
    except ModuleNotFoundError:  # pragma: no cover - requests is a hard dependency
        pass
    else:
        requests.Session.request = _blocked("requests")  # type: ignore[method-assign]

    try:
        import aiohttp
    except ModuleNotFoundError:  # pragma: no cover - optional
        pass
    else:
        aiohttp.ClientSession._request = _blocked_async("aiohttp")  # type: ignore[method-assign]

    import urllib.request

    urllib.request.urlopen = _blocked("urllib")  # type: ignore[assignment]
