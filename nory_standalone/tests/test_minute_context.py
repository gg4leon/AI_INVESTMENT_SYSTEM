"""All prices below are FABRICATED regression fixtures, never live market evidence."""

from contextlib import closing
from dataclasses import replace
import math
import sqlite3

import httpx
import pytest

from nory_standalone.nory.config import Config
from nory_standalone.nory.core import ResearchCore
from nory_standalone.nory.engine import Engine
from nory_standalone.nory.history import (
    AnalysisHistory,
    PriceSample,
    PublicHistoryClient,
    parse_candles,
)
from nory_standalone.nory.storage import Store, resolve_database
from .helpers import T, quote


def past_context(provider="coinbase", symbol="BTC-USD", known_at=T):
    return [
        PriceSample(
            provider,
            symbol,
            T - (240 - i) * 60,
            known_at,
            100 + i * 0.025 + 0.25 * math.sin(i * 0.75),
            "PUBLIC_CANDLE",
        )
        for i in range(240)
    ]


def current_price():
    return 100 + 240 * 0.025 + 0.25 * math.sin(240 * 0.75)


def test_default_costs_can_admit_a_longer_horizon_signal_then_change_equity():
    cfg = Config()
    core = ResearchCore(cfg)
    core.analysis.seed(past_context(), T)
    q = quote(mid=current_price())
    core.receive(q, T)
    core.step(T + 0.1, running=True)
    a = core.accounts["coinbase:trend"]
    decision = core.decisions[(a.id, q.symbol)]
    assert decision["action"] == "BUY_PENDING", decision["reason"]
    assert not core.events  # Historical closes and decision quote never fill the order.
    core.receive(quote(1, mid=current_price() + 0.01), T + 1)
    core.step(T + 1.1, running=True)
    assert a.positions and a.cash < 10000 and a.equity < 10000
    fills = [f for f in core.events if f["account"] == a.id]
    assert fills and fills[0]["quote_ts"] > fills[0]["decision_ts"]
    assert fills[0]["fee"] > 0
    assert cfg.fee_bps == {"coinbase": 60.0, "kraken": 40.0}


def test_bootstrap_context_alone_cannot_create_orders_fills_or_live_prices():
    core = ResearchCore(Config())
    core.analysis.seed(past_context(), T)
    assert core.step(T + 0.1, running=True) == []
    assert not core.latest and not core.events
    assert all(
        not a.positions and not a.orders and a.cash == 10000
        for a in core.accounts.values()
    )


def test_eight_second_ticker_pause_preserves_hours_of_context_but_expired_prices_stay_blocked():
    cfg = Config()
    core = ResearchCore(cfg)
    core.analysis.seed(past_context(), T)
    core.receive(quote(mid=current_price()), T)
    core.step(T + 0.1, running=False)
    assert core.step(T + 15, running=True) == []
    assert not core.events
    core.receive(quote(20, mid=current_price()), T + 20)
    core.step(T + 20.1, running=False)
    points = core.analysis.points_for(core.latest[("coinbase", "BTC-USD")])
    assert len(points) >= cfg.min_history
    assert points[-1].exchange_ts - points[0].exchange_ts > 3 * 3600
    assert core.metrics["history_gap_resets"] == 0


def test_unexplained_drop_on_first_live_quote_is_not_hidden_by_bootstrap():
    core = ResearchCore(Config())
    core.analysis.seed(past_context(), T)
    core.receive(quote(mid=current_price() * 0.95), T)
    core.step(T + 0.1, running=True)
    assert core.freeze_until[("coinbase", "BTC-USD")] > T + 100
    assert not core.events
    assert all(not a.orders for a in core.accounts.values())


def test_holdout_context_acquired_later_cannot_change_training_selection():
    from nory_standalone.nory.backtest import validate
    from .helpers import config, scenario

    cfg = config()
    quotes = scenario("bull")
    late = [replace(p, known_at=T + 550) for p in past_context()]
    changed = [replace(p, mid=p.mid * 1.5) for p in late]
    first = validate(quotes, cfg, source="SYNTHETIC_TEST", context=late)
    second = validate(quotes, cfg, source="SYNTHETIC_TEST", context=changed)
    assert first["training"] == second["training"]
    assert first["selected_from_training"] == second["selected_from_training"]


def test_short_quote_capture_without_minute_context_is_not_a_valid_backtest():
    from nory_standalone.nory.backtest import validate
    from .helpers import scenario

    with pytest.raises(ValueError, match="Contexto histórico insuficiente"):
        validate(scenario("bull"), Config(), source="SYNTHETIC_TEST")


def test_recent_context_with_large_holes_requests_backfill_instead_of_waiting_forever():
    history = AnalysisHistory(Config())
    full = past_context()
    sparse = [p for i, p in enumerate(full) if i % 2 == 0 or i == len(full) - 1]
    history.seed(sparse, T)
    assert len(sparse) >= 119
    assert history.needs_backfill("coinbase", "BTC-USD", T)


def test_future_or_later_acquired_context_is_unavailable_to_prior_quote():
    history = AnalysisHistory(Config())
    history.seed(past_context(known_at=T + 10), T + 10)
    assert len(history.points_for(quote(1))) == 1
    assert len(history.points_for(quote(11))) > 120
    with pytest.raises(ValueError, match="futuro"):
        AnalysisHistory(Config()).seed(past_context(known_at=T + 10), T)


def test_parse_authentic_candle_formats_discards_unfinished_and_invalid_rows():
    start = math.floor(T / 60) * 60
    cb = [[start, 99, 102, 100, 101, 5], [start - 60, 98, 101, 99, 100, 6]]
    out = parse_candles("coinbase", "BTC-USD", cb, start + 30)
    assert len(out) == 1 and out[0].mid == 100 and out[0].exchange_ts == start
    kr = {
        "error": [],
        "result": {
            "XXBTZUSD": [[start - 60, "99", "101", "98", "100", "99.5", "6", 12]],
            "last": start,
        },
    }
    assert parse_candles("kraken", "BTC-USD", kr, start + 30)[0].mid == 100
    with pytest.raises(ValueError):
        parse_candles(
            "coinbase", "BTC-USD", [[start - 60, 110, 100, 99, 100, 5]], start + 30
        )
    with pytest.raises(ValueError):
        parse_candles("kraken", "BTC-USD", {"error": ["EAPI:Rate limit exceeded"]}, T)


@pytest.mark.asyncio
async def test_public_history_client_only_uses_public_price_endpoints():
    seen = []

    def response(request):
        seen.append(str(request.url))
        start = math.floor(T / 60) * 60 - 60
        return httpx.Response(200, json=[[start, 99, 102, 100, 101, 5]])

    client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    source = PublicHistoryClient(Config(), client=client)
    try:
        points = await source.fetch("coinbase", "BTC-USD")
        assert points and "/products/BTC-USD/candles?granularity=60" in seen[0]
    finally:
        await source.close()


def test_rules_upgrade_keeps_old_ledger_bytes_and_routes_to_a_new_experiment(tmp_path):
    old = tmp_path / "nory.sqlite3"
    with closing(sqlite3.connect(old)) as db, db:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta VALUES('rules_version','2.0.0-fixed-rules')")
        db.execute("CREATE TABLE user_history(note TEXT)")
        db.execute("INSERT INTO user_history VALUES('preserve this')")
    before = old.read_bytes()
    routed, notice = resolve_database(old, Config())
    assert routed != old and notice and old.read_bytes() == before
    assert resolve_database(old, Config())[0] == routed
    store = Store(routed, Config())
    store.close()
    assert old.read_bytes() == before


@pytest.mark.asyncio
async def test_restart_reuses_saved_context_without_inventing_quotes(tmp_path):
    cfg = Config()
    engine = Engine(cfg, tmp_path / "nory.sqlite3", network=False)
    await engine.open()
    try:
        import time

        now = time.time()
        points = [
            replace(p, exchange_ts=p.exchange_ts + (now - T), known_at=now)
            for p in past_context()
        ]
        async with engine.guard:
            engine.core.analysis.seed(points, now)
            await engine._checkpoint([], now)
    finally:
        await engine.close()
    again = Engine(cfg, tmp_path / "nory.sqlite3", network=False)
    await again.open()
    try:
        assert len(again.core.analysis.closed[("coinbase", "BTC-USD")]) >= 120
        assert not again.core.latest and not again.running
    finally:
        await again.close()
