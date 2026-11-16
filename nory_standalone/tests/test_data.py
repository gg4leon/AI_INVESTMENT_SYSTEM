from dataclasses import replace
import pytest

from nory_standalone.nory.config import Config
from nory_standalone.nory.core import ResearchCore
from nory_standalone.nory.feeds import parse_message, subscription
from nory_standalone.nory.models import iso
from nory_standalone.nory.strategies import aligned_correlation, evaluate
from .helpers import T, config, quote


def test_official_message_shapes_are_only_offline_format_tests():
    coinbase = {
        "type": "ticker",
        "sequence": 100,
        "product_id": "BTC-USD",
        "time": iso(T),
        "price": "100",
        "open_24h": "99",
        "volume_24h": "3000",
        "best_bid": "99.99",
        "best_ask": "100.01",
        "best_bid_size": "5",
        "best_ask_size": "6",
    }
    kraken = {
        "channel": "ticker",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "timestamp": iso(T),
                "bid": 99.99,
                "ask": 100.01,
                "bid_qty": 5,
                "ask_qty": 6,
                "volume": 3000,
                "change_pct": 1.01,
            }
        ],
    }
    cq = parse_message("coinbase", coinbase, T, ("BTC-USD",))[0]
    kq = parse_message("kraken", kraken, T, ("BTC-USD",))[0]
    assert cq.bid == kq.bid == 99.99
    assert cq.provider != kq.provider
    assert cq.volume_24h == 3000
    assert parse_message("coinbase", {"type": "heartbeat"}, T, ("BTC-USD",)) == []
    assert (
        parse_message("kraken", {**kraken, "type": "snapshot"}, T, ("BTC-USD",)) == []
    )
    assert (
        parse_message(
            "coinbase", {**coinbase, "product_id": "UNLISTED-USD"}, T, ("BTC-USD",)
        )
        == []
    )
    with pytest.raises(ValueError):
        parse_message("coinbase", {**coinbase, "best_ask": "90"}, T, ("BTC-USD",))
    with pytest.raises(ValueError):
        parse_message("coinbase", {**coinbase, "best_ask_size": True}, T, ("BTC-USD",))
    assert subscription("kraken", ("BTC-USD",))["params"]["event_trigger"] == "bbo"


@pytest.mark.parametrize(
    "field,value",
    [
        ("bid", float("nan")),
        ("ask", float("inf")),
        ("ask", 90),
        ("bid_qty", 0),
        ("exchange_ts", 0),
        ("sequence", True),
        ("volume_24h", -1),
    ],
)
def test_invalid_quote_rejected(field, value):
    with pytest.raises(ValueError):
        replace(quote(), **{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"max_positions": 0},
        {"cash_reserve": 0.99},
        {"cadence_seconds": 0.1},
        {"max_orders_per_minute": 1.5},
        {"slippage_bps": -1},
        {"symbols": ("ETH-USD",)},
        {"providers": ("bad",)},
        {"initial_capital": float("nan")},
    ],
)
def test_bad_configuration_is_not_silently_used(changes):
    with pytest.raises((ValueError, TypeError)):
        Config(**changes)


def test_duplicates_old_and_expired_quotes_never_create_observations():
    core = ResearchCore(config())
    assert core.receive(quote(), T)
    assert not core.receive(quote(), T)
    assert not core.receive(quote(-1), T)
    assert not core.receive(quote(1), T + 20)
    core.step(T + 0.5, running=True)
    core.step(T + 1, running=True)
    assert len(core.history_for("coinbase", "BTC-USD")) == 1
    assert not core.events
    assert core.metrics["cycles_with_new_quotes"] == 1


def test_same_asset_different_providers_never_share_history_or_cash():
    core = ResearchCore(config())
    core.receive(quote(), T)
    core.receive(quote(mid=200, provider="kraken"), T)
    core.step(T + 0.5, running=True)
    assert core.history_for("coinbase", "BTC-USD")[0].mid == 100
    assert core.history_for("kraken", "BTC-USD")[0].mid == 200
    core.accounts["coinbase:trend"].cash = 8000
    assert core.accounts["kraken:trend"].cash == 10000
    assert core.accounts["coinbase:cash"].cash == 10000


def test_interval_sampling_no_artificial_ticks_and_gap_restarts_warmup():
    core = ResearchCore(config())
    for t in (0, 0.1, 0.2, 0.3, 1, 2, 20):
        core.receive(quote(t), T + t)
        core.step(T + t + 0.01, running=False)
    assert len(core.history_for("coinbase", "BTC-USD")) == 1
    assert core.metrics["history_gap_resets"] == 1


def test_correlation_matches_return_intervals_and_unknown_is_not_zero_risk():
    a = [quote(i, 100 + i * 0.1 + (i % 3) * 0.07) for i in range(80)]
    b = [quote(i, (100 + i * 0.1 + (i % 3) * 0.07) * 2, "ETH-USD") for i in range(80)]
    assert aligned_correlation(a, b, 1) == pytest.approx(1)
    offset = [replace(q, exchange_ts=q.exchange_ts + 200) for q in b]
    assert aligned_correlation(a, offset, 1) is None


def test_flat_prices_and_expensive_point_two_percent_move_do_not_force_trades():
    cfg = config()
    prices = [quote(i, 100 + 0.2 * i / 34) for i in range(35)]
    for strategy in ("trend", "mean_reversion", "momentum", "breakout", "cash"):
        signal = evaluate(strategy, prices, cfg, "coinbase")
        assert signal.action != "BUY"
        assert "not" not in signal.reason  # Spanish explanations remain user-facing.
    flat = [quote(i) for i in range(35)]
    assert evaluate("trend", flat, cfg, "coinbase").features["rsi"] == 50
