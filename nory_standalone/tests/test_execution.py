from dataclasses import asdict, replace
from unittest.mock import patch
import pytest

from nory_standalone.nory.core import ResearchCore
from nory_standalone.nory.models import Position
from nory_standalone.nory.strategies import Signal
from .helpers import T, config, quote

SIGNAL = Signal(
    "BUY",
    100,
    "Señal fabricada para aislar las pruebas del libro de ejecución",
    features={"volatility": 0.001},
)


def prepared(**kwargs):
    core = ResearchCore(config(**kwargs))
    a = core.accounts["coinbase:trend"]
    q = quote()
    core.receive(q, T)
    return core, a, q


def fill_next(core, a, q, now):
    core.receive(q, now)
    with patch("nory_standalone.nory.core.evaluate", return_value=SIGNAL):
        core.fill(a, q, now)


def test_pending_order_cannot_fill_known_buffered_or_predecision_market_price():
    core, a, q = prepared()
    assert core.queue(a, q, "BUY", T + 0.5, "Test", SIGNAL)[0]
    assert core.queue(a, q, "BUY", T + 0.5, "Duplicada", SIGNAL)[0] is False
    for candidate in (
        q,
        quote(0.1),
        replace(quote(0.6), received_ts=T + 0.4),
        replace(quote(0.6), exchange_ts=T + 0.4),
    ):
        core.fill(a, candidate, T + 1)
        assert a.cash == 10000
        assert not core.events
    fill_next(core, a, quote(1), T + 1)
    assert a.positions["BTC-USD"].qty > 0
    assert len(core.events) == 1
    assert core.events[0]["quote_ts"] > core.events[0]["decision_ts"]
    assert core.events[0]["received_ts"] > core.events[0]["decision_ts"]


def test_cash_conservation_fees_and_sell_pnl_include_both_sides():
    core, a, q = prepared()
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    fill_next(core, a, quote(1), T + 1)
    buy = core.events[-1]
    assert a.cash + buy["qty"] * buy["price"] + buy["fee"] == pytest.approx(10000)
    assert buy["price"] > buy["ask"]
    core.mark(a)
    assert (
        a.equity < 10000
    )  # Even a constant market loses spread, commissions and slippage.
    core.queue(a, quote(1), "SELL", T + 1, "Salida de prueba")
    fill_next(core, a, quote(2, mid=103), T + 2)
    sell = core.events[-1]
    assert sell["price"] < sell["bid"]
    expected = (
        sell["qty"] * sell["price"]
        - sell["fee"]
        - (buy["qty"] * buy["price"] + buy["fee"])
    )
    assert sell["realized_pnl"] == pytest.approx(expected)
    assert a.cash - 10000 == pytest.approx(expected)
    assert core.closed[0]["pnl"] == pytest.approx(expected)
    assert not a.positions


def test_partial_fills_expiry_and_reservations_do_not_overdraw_cash():
    core, a, q = prepared(top_book_participation=0.01, min_liquidity_usd=50)
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    # Visible book supports only .01 base units in the simulated participation model.
    fill_next(core, a, quote(1, qty=1), T + 1)
    order = a.orders["BTC-USD"]
    assert order.status == "PARTIAL"
    assert order.filled_qty == pytest.approx(0.01)
    assert a.cash >= 10000 * core.cfg.cash_reserve
    remaining = order.remaining
    core.fill(a, quote(1, qty=1), T + 1)
    assert order.remaining == remaining
    assert not core.receive(quote(1, qty=1), T + 1)
    core.step(T + 12, running=True)
    assert "BTC-USD" not in a.orders
    assert any(o["status"] == "EXPIRED" for o in core.order_events.values())
    assert remaining > 0


def test_quote_that_turns_stale_cannot_fill():
    core, a, q = prepared(order_ttl_seconds=30)
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    fill_next(core, a, quote(1), T + 12)
    assert not a.positions and a.cash == 10000


def test_unknown_five_percent_drop_blocks_buy_even_with_mocked_signal():
    core, a, q = prepared()
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    fill_next(core, a, quote(1, mid=95), T + 1)
    assert not a.positions
    assert not a.orders
    assert core.freeze_until[("coinbase", "BTC-USD")] > T + 100
    assert core.metrics["unexplained_shocks"] == 1


def test_stale_other_position_and_unknown_correlations_block_new_entries():
    core, a, q = prepared()
    a.positions["ETH-USD"] = Position("ETH-USD", 1, 100, T, 100, 100, T)
    budget, reason = core.budget(a, q, T, SIGNAL)
    assert budget == 0 and "fresca" in reason
    core.receive(quote(1, symbol="ETH-USD"), T + 1)
    budget, reason = core.budget(a, quote(1), T + 1, SIGNAL)
    assert budget == 0 and "Correlación" in reason


def test_order_rate_and_single_position_slot_include_pending_reservation():
    core, a, q = prepared(max_positions=1, max_orders_per_minute=1)
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    core.receive(quote(1, symbol="ETH-USD"), T + 1)
    ok, reason = core.queue(a, quote(1, symbol="ETH-USD"), "BUY", T + 1, "Test", SIGNAL)
    assert not ok and "minuto" in reason
    core.finish_order(a, "BTC-USD", "EXPIRED")
    assert a.cash == 10000


def test_drawdown_halts_entries_but_does_not_fabricate_liquidation():
    core, a, q = prepared(max_drawdown=0.01)
    a.positions["BTC-USD"] = Position("BTC-USD", 20, 2000, T, 100, 100, T)
    a.cash = 8000
    core.receive(quote(1, mid=90), T + 1)
    core.mark(a)
    assert a.halted and a.positions
    assert not core.queue(a, quote(1, mid=90), "BUY", T + 1, "Test", SIGNAL)[0]
    assert not core.events


def test_stop_cancels_orders_and_preserves_exact_portfolio():
    core, a, q = prepared()
    core.queue(a, q, "BUY", T, "Test", SIGNAL)
    fill_next(core, a, quote(1), T + 1)
    core.queue(a, quote(1), "SELL", T + 1, "Test")
    before = asdict(a.positions["BTC-USD"])
    core.cancel_all()
    core.receive(quote(2, mid=120), T + 2)
    core.step(T + 2, running=False)
    assert not a.orders
    assert a.positions["BTC-USD"].qty == before["qty"]
    assert len(core.events) == 1
