import asyncio
from dataclasses import replace
import json
import pytest

from nory_standalone.nory.backtest import replay, validate
from nory_standalone.nory.feeds import PublicFeed
from nory_standalone.nory.models import iso
from .helpers import config, scenario


@pytest.mark.parametrize("kind", ["bull", "bear", "sideways"])
def test_all_regimes_replay_costs_limits_and_strict_future_fills(kind):
    cfg = config(fee_bps={"coinbase": 10.0, "kraken": 40.0}, min_net_edge_bps=5)
    result = replay(scenario(kind), cfg)
    assert result["cash"]["final_equity"] == 10000
    for report in result.values():
        assert report["final_equity"] > 0
        assert report["average_exposure_pct"] <= (1 - cfg.cash_reserve) * 100
        for fill in report["trades"]:
            assert fill["quote_ts"] > fill["decision_ts"]
            assert fill["received_ts"] > fill["decision_ts"]
            assert fill["fee"] > 0 and fill["cash_after"] >= 0
    if kind == "bull":
        assert (
            result["trend"]["fills"] > 0
        )  # Real strategy conditions, not a mocked signal.


def test_holdout_future_cannot_change_training_selection():
    cfg = config()
    original = scenario("bull")
    first = validate(original, cfg, source="SYNTHETIC_TEST")
    # Only alter the last 30%; the training report must remain bit-for-bit identical.
    changed = [
        replace(
            q,
            bid=q.bid * (0.7 if i >= 490 else 1),
            ask=q.ask * (0.7 if i >= 490 else 1),
        )
        for i, q in enumerate(original)
    ]
    second = validate(changed, cfg, source="SYNTHETIC_TEST")
    assert first["training"] == second["training"]
    assert first["selected_from_training"] == second["selected_from_training"]
    assert first["source"] == "SYNTHETIC_TEST"
    assert first["test_start"] > first["train_end"]


def test_short_history_and_mixed_provider_fail_explicitly():
    with pytest.raises(ValueError, match="insuficiente"):
        validate(scenario(seconds=80), config())
    quotes = scenario()
    quotes[-1] = replace(quotes[-1], provider="kraken", sequence=None)
    with pytest.raises(ValueError, match="único proveedor"):
        validate(quotes, config())


@pytest.mark.asyncio
async def test_connection_interrupt_reconnects_with_backoff_and_cancel_is_clean(
    monkeypatch,
):
    received = asyncio.Event()
    calls = []
    sent = []
    real_sleep = asyncio.sleep

    async def fast_backoff(delay):
        assert 1 <= delay <= 35
        await real_sleep(0.001)

    monkeypatch.setattr("nory_standalone.nory.feeds.asyncio.sleep", fast_backoff)

    class Socket:
        used = False

        async def send(self, raw):
            sent.append(json.loads(raw))

        async def recv(self):
            if self.used:
                await asyncio.Future()
            self.used = True
            import time

            return json.dumps(
                {
                    "type": "ticker",
                    "product_id": "BTC-USD",
                    "sequence": 100,
                    "time": iso(time.time()),
                    "best_bid": "99.99",
                    "best_ask": "100.01",
                    "best_bid_size": "100",
                    "best_ask_size": "100",
                    "volume_24h": "1000",
                }
            )

    class Connection:
        async def __aenter__(self):
            if len(calls) == 1:
                raise OSError("Intentional offline fixture: disconnected")
            return Socket()

        async def __aexit__(self, *args):
            return False

    def connector(*args, **kwargs):
        calls.append(args[0])
        return Connection()

    feed = PublicFeed(
        "coinbase", ("BTC-USD",), lambda q, now: received.set(), connector=connector
    )
    task = asyncio.create_task(feed.run())
    await asyncio.wait_for(received.wait(), timeout=2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(calls) == 2
    assert sent[0]["channels"] == ["ticker", "heartbeat"]
    assert feed.metrics.reconnects == 1 and feed.metrics.state == "STOPPED"
