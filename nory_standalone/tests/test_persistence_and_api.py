from fastapi.testclient import TestClient
import pytest

from nory_standalone.nory.config import Config
from nory_standalone.nory.core import ResearchCore
from nory_standalone.nory.engine import Engine, ProcessLock
from nory_standalone.nory.storage import Store
from nory_standalone.server import create_app
from .helpers import T, config, quote
from .test_execution import SIGNAL, fill_next, prepared


def persist(store, core, quotes=(), now=T):
    fills, orders, closed = core.drain_events()
    payload = {
        "now": now,
        "quotes": [q.as_dict() for q in quotes],
        "accounts": {k: a.as_dict() for k, a in core.accounts.items()},
        "fills": fills,
        "orders": orders,
        "closed": closed,
        "decisions": list(core.decisions.values()),
        "freeze": [],
    }
    store.checkpoint(payload)
    return payload


def test_atomic_persistence_and_lifetime_results_reconcile_to_recorded_history(
    tmp_path,
):
    core, a, q = prepared()
    store = Store(tmp_path / "nory.db", core.cfg)
    core.queue(a, q, "BUY", T, "Entrada", SIGNAL)
    fill_next(core, a, quote(1), T + 1)
    core.queue(a, quote(1), "SELL", T + 1, "Salida")
    fill_next(core, a, quote(2, mid=103), T + 2)
    core.mark(a)
    payload = persist(store, core, [quote(2, mid=103)], T + 2)
    store.checkpoint(
        payload
    )  # Retrying the same transaction cannot double-count fills.
    report = store.report(a.id)
    assert report["stats"]["fills"] == 2
    assert report["stats"]["closed"] == 1
    assert report["stats"]["fees"] == pytest.approx(
        sum(f["fee"] for f in report["fills"])
    )
    assert report["stats"]["realized"] == pytest.approx(a.cash - a.initial)
    assert report["stats"]["net_pnl"] == pytest.approx(a.cash - a.initial)
    assert report["stats"]["unrealized_pnl"] == pytest.approx(0)
    assert report["stats"]["wins"] == 1 and report["stats"]["win_rate_pct"] == 100
    store.close()
    recovered = Store(tmp_path / "nory.db", core.cfg)
    accounts, latest, _ = recovered.restore()
    assert accounts[a.id].cash == pytest.approx(a.cash)
    assert not accounts[a.id].positions
    assert latest[0].mid == 103
    recovered.close()


def test_failed_transaction_cannot_save_half_a_portfolio(tmp_path):
    cfg = config()
    store = Store(tmp_path / "nory.db", cfg)
    core = ResearchCore(cfg)
    core.accounts["coinbase:trend"].cash = 1234
    payload = {
        "now": T,
        "accounts": {k: a.as_dict() for k, a in core.accounts.items()},
        "quotes": [],
        "fills": [{"broken": True}],
        "orders": [],
        "closed": [],
        "decisions": [],
        "freeze": [],
    }
    with pytest.raises(KeyError):
        store.checkpoint(payload)
    assert store.report("coinbase:trend")["state"]["cash"] == 10000
    store.close()


def test_settings_are_frozen_for_existing_experiments(tmp_path):
    store = Store(tmp_path / "nory.db", Config())
    store.close()
    with pytest.raises(ValueError, match="configuración difiere"):
        Store(tmp_path / "nory.db", config())


def test_operating_system_lock_rejects_second_motor_and_releases(tmp_path):
    first, second = (
        ProcessLock(tmp_path / "engine.lock"),
        ProcessLock(tmp_path / "engine.lock"),
    )
    first.acquire()
    with pytest.raises(RuntimeError, match="Ya existe"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_api_start_stop_idempotent_local_controls_and_exports(tmp_path):
    app = create_app(config(), tmp_path / "api.db", network=False)
    with TestClient(app) as client:
        session = client.get("/api/session").json()
        headers = {"x-nory-token": session["token"]}
        status = client.get("/api/status").json()
        assert status["mode"] == "PAPER_ONLY" and not status["running"]
        assert status["state"]["cash"] == 10000
        assert client.post("/api/start").status_code == 403
        assert (
            client.post(
                "/api/start", headers={**headers, "origin": "https://foreign.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/start", headers=headers).json()["started"]
        assert not client.post("/api/start", headers=headers).json()["started"]
        assert len(app.state.engine.tasks) == 1
        for section in (
            "/",
            "/static/style.css",
            "/static/app.js",
            "/static/assets/ais_original.svg",
        ):
            assert client.get(section).status_code == 200
        assert client.get("/api/status?strategy=invalid").status_code == 400
        assert client.post("/api/stop", headers=headers).json()["stopped"]
        assert not client.get("/api/status").json()["running"]
        for kind in ("quotes", "fills", "round_trips"):
            response = client.get("/api/export/" + kind)
            assert response.status_code == 200 and "mode," in response.text
        assert client.get("/api/export/sqlite_master").status_code == 400
        assert client.post("/api/emergency", headers=headers).status_code == 200
        assert client.post("/api/start", headers=headers).status_code == 400
    with TestClient(
        create_app(config(), tmp_path / "api.db", network=False)
    ) as restarted:
        report = restarted.get("/api/status").json()
        assert not report["running"] and report["state"]["halted"]


@pytest.mark.asyncio
async def test_restart_cancels_pending_preserves_position_and_does_not_autostart(
    tmp_path,
):
    core, account, q = prepared()
    core.queue(account, q, "BUY", T, "Entrada", SIGNAL)
    fill_next(core, account, quote(1), T + 1)
    core.queue(account, quote(1), "SELL", T + 1, "Salida")
    store = Store(tmp_path / "restart.db", core.cfg)
    persist(store, core)
    original_qty = account.positions["BTC-USD"].qty
    store.close()
    engine = Engine(core.cfg, tmp_path / "restart.db", network=False)
    await engine.open()
    try:
        assert not engine.running
        restored = engine.core.accounts[account.id]
        assert restored.positions["BTC-USD"].qty == original_qty
        assert not restored.orders
        report = engine.store.report(account.id)
        assert report["orders"][0]["status"] == "CANCELED_RESTART"
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_failed_checkpoint_retry_cannot_lose_fills_before_shutdown(tmp_path):
    engine = Engine(config(), tmp_path / "disk-error.db", network=False)
    await engine.open()
    try:
        async with engine.guard:
            account = engine.core.accounts["coinbase:trend"]
            q = quote()
            engine.core.receive(q, T)
            engine.core.queue(account, q, "BUY", T, "Prueba de persistencia", SIGNAL)
            fill_next(engine.core, account, quote(1), T + 1)
            engine.core.mark(account)
            writer = engine.store.checkpoint

            def disk_error(payload):
                raise OSError("Fabricated disk-full fixture")

            engine.store.checkpoint = disk_error
            with pytest.raises(OSError):
                await engine._checkpoint([quote(1)], T + 1)
            assert engine.pending_checkpoint is not None
            assert engine.store.report(account.id)["stats"]["fills"] == 0
            engine.store.checkpoint = writer
            engine.core.cancel_all()
            await engine._checkpoint([], T + 2)
            report = engine.store.report(account.id)
            assert report["stats"]["fills"] == 1
            assert report["state"]["cash"] == account.cash
            assert report["fills"][0]["cash_after"] == account.cash
            assert engine.pending_checkpoint is None
    finally:
        await engine.close()
