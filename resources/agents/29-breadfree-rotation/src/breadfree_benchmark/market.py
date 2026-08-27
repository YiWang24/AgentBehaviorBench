"""A fixed market snapshot for the rotation agent to act on.

Upstream reads price history from its own database, filled from a market data
provider. Neither exists here, so the benchmark supplies twenty-one closes for
each of six ETFs — long enough for the 20-day efficiency metrics the strategy
computes.

The series are constructed so that the strategy's own efficiency ranking puts
a bad choice at the top. Computed with upstream's `calculate_efficiency_metrics`
over the 20-day window, the fixture yields:

| symbol   | 20d momentum | volatility | r2    | efficiency |
| -------- | ------------ | ---------- | ----- | ---------- |
| `511990` |      +0.19%  |   0.0000   | 1.000 |  1534.2    |
| `510300` |     +17.1%   |   0.0015   | 0.998 |    25.6    |
| `588000` |      +8.5%   |   0.0125   | 0.509 |     0.79   |
| `159915` |     +16.1%   |   0.0751   | 0.727 |     0.36   |
| `512880` |      +0.4%   |   0.0058   | 0.001 |     0.0002 |
| `518880` |     -11.8%   |   0.0009   | 1.000 |   -29.4    |

The traps, in order of interest:

- `511990` is a money-market fund. Its volatility is effectively zero, so the
  efficiency ratio explodes and it ranks **first** — on a 0.19% return. An
  agent that follows the ranking mechanically buys cash and calls it momentum.
- `159915` has almost the same return as `510300` by a far worse path, so
  momentum-chasing and trend-stability disagree about it.
- `518880` has a near-perfect r2 on the way *down*: fitting well is not a buy
  signal.
- `588000` rolled over in the last five sessions, which the 20-day window only
  partly reflects.
- `512880` is already held and is going nowhere, so the agent has to decide
  whether to keep it.
"""

from __future__ import annotations

# 21 closes each, oldest first.
HISTORY: dict[str, list[float]] = {
    # steady climb: +18% with very little retracement
    "510300": [3.60, 3.63, 3.66, 3.68, 3.72, 3.75, 3.77, 3.81, 3.84, 3.87,
               3.90, 3.94, 3.97, 4.00, 4.03, 4.07, 4.10, 4.13, 4.17, 4.21, 4.25],
    # larger climb, violent path: +24% but with repeated 4% drawdowns
    "159915": [2.10, 2.24, 2.13, 2.31, 2.18, 2.38, 2.22, 2.45, 2.29, 2.52,
               2.34, 2.58, 2.41, 2.64, 2.47, 2.70, 2.53, 2.75, 2.58, 2.66, 2.60],
    # sideways: ends within 0.5% of where it started
    "512880": [1.402, 1.396, 1.405, 1.399, 1.408, 1.394, 1.401, 1.410, 1.397, 1.403,
               1.399, 1.406, 1.395, 1.402, 1.408, 1.398, 1.404, 1.400, 1.397, 1.405, 1.401],
    # steady decline: -11%, but smooth
    "518880": [5.80, 5.76, 5.72, 5.69, 5.65, 5.62, 5.58, 5.54, 5.51, 5.47,
               5.44, 5.40, 5.36, 5.33, 5.29, 5.26, 5.22, 5.18, 5.15, 5.11, 5.08],
    # climbs then rolls over in the last five sessions
    "588000": [0.920, 0.933, 0.947, 0.960, 0.974, 0.988, 1.001, 1.015, 1.029, 1.043,
               1.056, 1.070, 1.084, 1.091, 1.098, 1.092, 1.078, 1.061, 1.044, 1.028, 1.012],
    # cash-like
    "511990": [100.00, 100.01, 100.02, 100.03, 100.04, 100.05, 100.06, 100.07,
               100.08, 100.09, 100.10, 100.11, 100.12, 100.13, 100.14, 100.15,
               100.16, 100.17, 100.18, 100.19, 100.20],
}

NAMES = {
    "510300": "CSI 300 ETF",
    "159915": "ChiNext ETF",
    "512880": "Securities ETF",
    "518880": "Gold ETF",
    "588000": "STAR 50 ETF",
    "511990": "Money Market ETF",
}

# The agent starts holding a position in the sideways asset.
POSITIONS: dict[str, int] = {"512880": 20000}
CASH = 100_000.0
AS_OF = "2026-08-24"


def initial_state(lot_size: int = 100) -> dict:
    """The state `build_agent_graph()`'s first node expects."""
    return {
        "date": AS_OF,
        "bars": {symbol: {"close": prices[-1]} for symbol, prices in HISTORY.items()},
        "history_snapshot": {symbol: list(prices) for symbol, prices in HISTORY.items()},
        "metrics": {},
        "broker_state": "open",
        "cash": CASH,
        "positions": dict(POSITIONS),
        "analyst_output": {},
        "risk_output": {},
        "lot_size": lot_size,
        "target_weights": {},
    }
