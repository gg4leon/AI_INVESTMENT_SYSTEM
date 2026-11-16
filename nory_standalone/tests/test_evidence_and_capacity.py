import math

from nory_standalone.nory.core import ResearchCore
from nory_standalone.nory.evidence import trade_evidence
from nory_standalone.nory.storage import Store
from .helpers import T, config, quote
from .test_execution import SIGNAL, fill_next, prepared


def test_no_statistical_advantage_is_invented_from_no_or_few_closes():
    for values in ([], [1, 2, 3]):
        evidence = trade_evidence(values)
        assert evidence["status"] == "INSUFFICIENT_SAMPLE"
        assert evidence["bootstrap_95_mean_usd"] is None
        assert not evidence["positive_interval"]


def test_descriptive_interval_is_reproducible_and_all_losses_remain_negative():
    values = [-i / 10 for i in range(1, 41)]
    evidence = trade_evidence(values)
    assert evidence == trade_evidence(values)
    assert evidence["mean_net_pnl_usd"] < 0
    assert evidence["bootstrap_95_mean_usd"][1] < 0
    assert not evidence["positive_interval"]


def test_partial_entry_does_not_prevent_emergency_stop_exit():
    core, a, q = prepared(top_book_participation=0.01, min_liquidity_usd=50)
    core.queue(a, q, "BUY", T, "Entrada parcial", SIGNAL)
    fill_next(core, a, quote(1, qty=1), T + 1)
    assert a.orders["BTC-USD"].side == "BUY"
    core.dirty.clear()
    core.receive(quote(2, mid=96), T + 2)
    core.step(T + 2.1, running=True)
    assert a.orders["BTC-USD"].side == "SELL"
    assert (
        len(core.events) == 1
    )  # Risk exit is pending, never filled at decision price.


def test_multiple_assets_and_bounded_memory_under_hours_of_fabricated_events():
    cfg = config(
        history_limit=180,
        sample_seconds=8,
        max_gap_seconds=16,
        fee_bps={"coinbase": 1.0, "kraken": 1.0},
        min_net_edge_bps=1,
        slippage_bps=0,
        min_liquidity_usd=10,
    )
    core = ResearchCore(cfg)
    maximum_positions = 0
    for step in range(1500):
        for i, symbol in enumerate(cfg.symbols):
            mid = 100 * math.exp(
                0.0005 * step + 0.012 * math.sin(step * (0.07 + i * 0.013))
            )
            core.receive(quote(step * 8, mid=mid, symbol=symbol), T + step * 8)
        core.step(T + step * 8 + 0.2, running=True)
        for account in core.accounts.values():
            assert account.cash >= -1e-8
            assert len(account.positions) <= cfg.max_positions
            maximum_positions = max(maximum_positions, len(account.positions))
            assert all(order.remaining >= 0 for order in account.orders.values())
        core.drain_events()
    assert maximum_positions >= 2
    assert all(len(series) <= cfg.history_limit for series in core.history.values())
    assert len(core.latest) <= len(cfg.symbols) * len(cfg.providers)


def test_sample_retention_cannot_erase_lifetime_trade_totals_and_paths_with_hash_work(
    tmp_path,
):
    cfg = config(max_recorded_samples=1000)
    core = ResearchCore(cfg)
    folder = tmp_path / "cartera # 1 con espacios"
    store = Store(folder / "nory.db", cfg)
    from .test_persistence_and_api import persist

    records = [quote(i) for i in range(1010)]
    persist(store, core, records, T + 1010)
    assert len(store.recorded("coinbase")) == 1000
    assert store.report("coinbase:trend")["state"]["initial"] == 10000
    store.close()


def test_configured_initial_capital_is_used_by_every_strategy_provider(tmp_path):
    cfg = config(initial_capital=23000)
    store = Store(tmp_path / "capital.db", cfg)
    accounts, _, _ = store.restore()
    assert len(accounts) == 10
    assert all(a.initial == a.cash == 23000 for a in accounts.values())
    store.close()
