"""Fail loudly when a non-LLM service is reached over the network.

The model provider is the only permitted real dependency, and it travels over
``httpx`` (openai SDK -> langchain-openai). Every other client TradingAgents
can reach for — ``requests`` for Alpha Vantage / FRED / Polymarket, and
``curl_cffi`` for yfinance — is blocked here so a gap in mock coverage raises
instead of quietly returning live data or an empty fallback.
"""

from __future__ import annotations


class BenchmarkNetworkBlocked(RuntimeError):
    """Raised when mocked coverage is missing and real egress was attempted."""


def _target(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    """Best-effort URL for the error message.

    These patches replace an unbound method, so a call through an instance
    arrives as ``(session, method, url)`` while a direct call arrives as
    ``(method, url)``. Pick the first argument that looks like a URL instead of
    guessing a position.
    """
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
    except ModuleNotFoundError:  # pragma: no cover - requests is a hard dependency
        pass
    else:
        requests.Session.request = _blocked("requests")  # type: ignore[method-assign]

    try:
        import curl_cffi.requests as curl_requests
    except ModuleNotFoundError:  # pragma: no cover - optional yfinance backend
        pass
    else:
        if hasattr(curl_requests, "Session"):
            curl_requests.Session.request = _blocked("curl_cffi")  # type: ignore[method-assign]

    # The StockTwits and Reddit fetchers use urllib directly, which neither of
    # the clients above covers.
    import urllib.request

    urllib.request.urlopen = _blocked("urllib")  # type: ignore[assignment]
