from trading_agents_benchmark.input_mapping import DEFAULT_TICKER, parse_request


def test_extracts_bare_ticker_and_date() -> None:
    ticker, trade_date, asset_type = parse_request(
        "Should I buy NVDA on 2024-05-10? Give me your full analysis."
    )
    assert ticker == "NVDA"
    assert trade_date == "2024-05-10"
    assert asset_type == "stock"


def test_resolves_company_name_alias() -> None:
    ticker, _trade_date, _asset_type = parse_request("What's your read on Tesla right now?")
    assert ticker == "TSLA"


def test_ignores_common_acronyms() -> None:
    ticker, _trade_date, _asset_type = parse_request(
        "The CEO announced an IPO; what should the SEC and GDP outlook mean for AAPL?"
    )
    assert ticker == "AAPL"


def test_falls_back_to_default_ticker_when_none_found() -> None:
    ticker, _trade_date, _asset_type = parse_request("Give me a general market outlook please.")
    assert ticker == DEFAULT_TICKER


def test_defaults_date_to_today_when_absent() -> None:
    from datetime import datetime, timezone

    _ticker, trade_date, _asset_type = parse_request("Analyze NVDA for me")
    assert trade_date == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_accepts_structured_object_input() -> None:
    ticker, trade_date, _asset_type = parse_request(
        {"prompt": "Analyze MSFT on 2025-01-15"}
    )
    assert ticker == "MSFT"
    assert trade_date == "2025-01-15"


def test_rejects_empty_text() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_request("   ")


def test_rejects_object_without_any_text_value() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_request({"ticker_id": 123, "count": 4})
