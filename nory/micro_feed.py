"""Deterministic *synthetic* seconds, NOT market ticks or quotes.

This source never contacts Yahoo, an exchange, a broker, RSS, or a news source.
Every event and price is FABRICATED for strategy testing.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math

import numpy as np

from app.markets import MARKET_BY_SYMBOL

SCENARIOS = ("mixed", "calm", "selloff", "shock")
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SyntheticTick:
    sequence: int
    virtual_time: str
    prices: dict[str, float]
    events: dict[str, str]
    scenario: str


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def initial_price(symbol: str) -> float:
    # Scale is arbitrary. These are NEVER current or actual quotations.
    if symbol.endswith("-USD"):
        return 10_000.0 + (_seed(symbol) % 20_000)
    return 70.0 + (_seed(symbol) % 260)


def synthesize_tick(
    sequence: int,
    symbols: tuple[str, ...],
    previous_prices: dict[str, float],
    scenario: str = "mixed",
) -> SyntheticTick:
    if sequence < 0 or scenario not in SCENARIOS:
        raise ValueError("Invalid simulated timeline or scenario")
    if not 1 <= len(symbols) <= 20 or len(set(symbols)) != len(symbols):
        raise ValueError("Provide 1-20 distinct symbols")
    rng_common = np.random.default_rng(_seed(f"AIS-COMMON:{scenario}:{sequence}"))
    common = float(rng_common.standard_normal())
    prices: dict[str, float] = {}
    events: dict[str, str] = {}
    for symbol in sorted(symbols):
        market = MARKET_BY_SYMBOL.get(symbol)
        if market is None or market.currency != "USD" or not market.paper_eligible:
            raise ValueError(f"Unsupported synthetic paper instrument: {symbol}")
        previous = previous_prices.get(symbol, initial_price(symbol))
        if not math.isfinite(previous) or previous <= 0:
            raise ValueError("Previous simulated price must be positive")
        seed = _seed(f"AIS-INDIVIDUAL:{scenario}:{sequence}:{symbol}")
        individual = float(np.random.default_rng(seed).standard_normal())
        anchor = initial_price(symbol)
        # Price mean-reversion and shared cross-market component (both artificial).
        mean_revert = -0.08 * math.log(previous / anchor)
        market_component = 0.0008 * common
        idiosyncratic = 0.0017 * individual
        drift = 0.00005
        if scenario == "calm":
            market_component *= 0.30
            idiosyncratic *= 0.45
        if scenario == "selloff":
            drift -= 0.0009
        if market.category == "Criptomonedas":
            idiosyncratic *= 1.7
            market_component *= 1.5
        surprise = 0.0
        event = "NO_CONFIRMED_NEWS_CONTEXT"
        if scenario in ("mixed", "shock") and sequence == 95 and symbol == "NVDA":
            surprise = -0.065
            event = "FABRICATED_SINGLE_STOCK_SHOCK_UNKNOWN_CAUSE"
        if scenario == "shock" and sequence == 170:
            surprise -= 0.022
            event = "FABRICATED_SYSTEMIC_SHOCK_UNKNOWN_CAUSE"
        if scenario in ("mixed", "shock") and symbol == "NVDA" and 96 <= sequence <= 102:
            event = "FABRICATED_UNEXPLAINED_POST_SHOCK_WINDOW"
        log_return = max(-0.20, min(0.20, mean_revert + market_component + idiosyncratic + drift + surprise))
        price = previous * math.exp(log_return)
        prices[symbol] = round(price, 8)
        events[symbol] = event
    return SyntheticTick(
        sequence=sequence,
        virtual_time=(BASE_TIME + timedelta(seconds=sequence)).isoformat(),
        prices=prices,
        events=events,
        scenario=scenario,
    )
