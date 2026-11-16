import asyncio
from collections import Counter
from dataclasses import asdict
import logging
from pathlib import Path
import time

from .core import ResearchCore
from .feeds import PublicFeed
from .storage import Store

log = logging.getLogger(__name__)


class ProcessLock:
    """OS releases the lock after a crash. Works on Windows and POSIX."""

    def __init__(self, path):
        self.path, self.handle = Path(path), None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            import os

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError(
                "Ya existe un motor que utiliza esta base de Nory."
            ) from exc

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class Engine:
    def __init__(self, cfg, db_path, *, network=True, feed_factory=PublicFeed):
        self.cfg, self.db_path, self.network, self.feed_factory = (
            cfg,
            Path(db_path),
            network,
            feed_factory,
        )
        self.process_lock = ProcessLock(str(self.db_path) + ".lock")
        self.guard = asyncio.Lock()
        self.running = False
        self.fatal_error = None
        self.started_at = None
        self.store = None
        self.core = None
        self.tasks, self.feeds = [], {}
        self.cycles = 0
        self.last_decisions = {}
        self.pending_checkpoint = None
        self.shutdown = asyncio.Event()

    async def open(self):
        self.process_lock.acquire()
        try:
            self.store = Store(self.db_path, self.cfg)
            accounts, latest, freeze = self.store.restore()
            self.core = ResearchCore(self.cfg, accounts)
            self.core.latest = {(q.provider, q.symbol): q for q in latest}
            self.core.freeze_until = {(p, s): until for p, s, until in freeze}
            self.core.cancel_all("CANCELED_RESTART")
            await self._checkpoint([], time.time())
            if self.network:
                for provider in self.cfg.providers:
                    feed = self.feed_factory(
                        provider, self.cfg.symbols, self.core.receive
                    )
                    self.feeds[provider] = feed
                    self.tasks.append(
                        asyncio.create_task(feed.run(), name=f"nory-data-{provider}")
                    )
            self.tasks.append(
                asyncio.create_task(self._loop(), name="nory-coordinator")
            )
        except Exception:
            if self.store:
                self.store.close()
            self.process_lock.release()
            raise

    async def close(self):
        self.shutdown.set()
        for task in self.tasks:
            if task.get_name() != "nory-coordinator":
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        async with self.guard:
            self.running = False
            if self.core and self.store:
                self.core.cancel_all("CANCELED_SHUTDOWN")
                try:
                    await self._checkpoint([], time.time())
                finally:
                    self.store.close()
                    self.process_lock.release()

    async def _checkpoint(self, quotes, now):
        if self.pending_checkpoint is not None:
            await asyncio.to_thread(self.store.checkpoint, self.pending_checkpoint)
            self.pending_checkpoint = None
        fills, orders, closed = self.core.drain_events()
        decisions = [
            d
            for key, d in self.core.decisions.items()
            if self.last_decisions.get(key) != d["quote_ts"]
        ]
        payload = {
            "now": now,
            "quotes": [q.as_dict() for q in quotes],
            "accounts": {k: a.as_dict() for k, a in self.core.accounts.items()},
            "fills": fills,
            "orders": orders,
            "closed": closed,
            "decisions": decisions,
            "freeze": [
                [p, s, until]
                for (p, s), until in self.core.freeze_until.items()
                if until > now
            ],
        }
        try:
            await asyncio.to_thread(self.store.checkpoint, payload)
        except Exception:
            # Retain the complete batch so shutdown/retry cannot save changed
            # cash without its corresponding fills, quotes and order history.
            self.pending_checkpoint = payload
            raise
        self.last_decisions.update(
            {key: d["quote_ts"] for key, d in self.core.decisions.items()}
        )

    async def _loop(self):
        try:
            while not self.shutdown.is_set():
                before = time.monotonic()
                async with self.guard:
                    now = time.time()
                    changed = self.core.step(now, running=self.running)
                    self.cycles += 1
                    if changed or self.core.order_events:
                        await self._checkpoint(changed, now)
                await asyncio.sleep(
                    max(0.01, self.cfg.cadence_seconds - (time.monotonic() - before))
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.running = False
            self.fatal_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.exception("Motor detenido por error; se requiere reiniciar el servicio")

    async def start(self):
        async with self.guard:
            if self.fatal_error:
                raise ValueError(
                    "Error persistente del motor: reinicia el servicio después de revisar el registro."
                )
            if all(a.halted for a in self.core.accounts.values()):
                raise ValueError(
                    "Las carteras están bloqueadas. Usa una base nueva después de investigar el riesgo."
                )
            if self.running:
                return {"started": False, "reason": "Nory ya está en ejecución."}
            self.running, self.started_at = True, time.time()
            return {
                "started": True,
                "reason": "Nory iniciado. Esperando cotizaciones nuevas y condiciones válidas.",
            }

    async def stop(self, *, emergency=False):
        async with self.guard:
            self.running = False
            self.core.cancel_all("CANCELED_EMERGENCY" if emergency else "CANCELED_STOP")
            if emergency:
                for account in self.core.accounts.values():
                    account.halted = True
            await self._checkpoint([], time.time())
            return {
                "stopped": True,
                "reason": "Órdenes pendientes canceladas. Las posiciones ficticias permanecen abiertas.",
            }

    async def snapshot(self, provider, strategy):
        account_id = f"{provider}:{strategy}"
        if account_id not in self.core.accounts:
            raise ValueError("Cartera no disponible")
        report = await asyncio.to_thread(self.store.report, account_id)
        now = time.time()
        decisions = {d["symbol"]: d for d in report["decisions"]}
        markets = []
        for symbol in self.cfg.symbols:
            q = self.core.latest.get((provider, symbol))
            decision = decisions.get(symbol)
            fresh = q is not None and q.fresh(now, self.cfg.quote_max_age_seconds)
            pos = report["state"]["positions"].get(symbol)
            history = self.core.history_for(provider, symbol)
            change = (q.mid / history[0].mid - 1) * 100 if q and history else None
            action = decision["action"] if decision else "WARMUP"
            reason = (
                decision["reason"]
                if decision
                else "Esperando muestras auténticas suficientes."
            )
            if not fresh:
                action, reason = (
                    "STALE",
                    "Cotización vencida o no recibida; no puede generar nuevas operaciones.",
                )
            elif not self.running:
                action, reason = (
                    "PAUSED",
                    "Nory detenido. " + reason.removeprefix("Nory detenido. "),
                )
            markets.append(
                {
                    "symbol": symbol,
                    "quote": q.as_dict() if q else None,
                    "fresh": fresh,
                    "price": q.mid if q else None,
                    "spread_bps": q.spread_bps if q else None,
                    "age_seconds": max(now - q.exchange_ts, now - q.received_ts)
                    if q
                    else None,
                    "change_pct": change,
                    "change_label": "Ventana local observada",
                    "risk": "Alto"
                    if not fresh or action == "BLOCK_RISK"
                    else "Moderado",
                    "action": action,
                    "reason": reason,
                    "score": decision["score"] if decision else 0,
                    "checks": decision["checks"] if decision else {},
                    "features": decision["features"] if decision else {},
                    "headroom_bps": decision.get("headroom_bps", 0) if decision else 0,
                    "samples": len(history),
                    "position": pos,
                }
            )
        fresh_count = sum(m["fresh"] for m in markets)
        counts = Counter(m["action"] for m in markets)
        if self.fatal_error:
            diagnosis = "Motor detenido por error: " + self.fatal_error
        elif not self.running:
            diagnosis = f"Nory está detenido. {fresh_count} de {len(markets)} mercados tienen cotizaciones frescas. Pulsa Iniciar Nory para activar la investigación paper."
        elif report["state"]["halted"]:
            diagnosis = "Cartera bloqueada por riesgo. Las entradas están suspendidas; se vigilan salidas con cotizaciones frescas."
        elif not fresh_count:
            diagnosis = "Sin cotizaciones frescas. Revisa la conexión de los proveedores; no se sustituyen los precios."
        elif strategy == "cash":
            diagnosis = "La estrategia defensiva conserva efectivo por diseño y sirve como referencia de exposición cero."
        else:
            main_reason = counts.most_common(1)[0][0]
            diagnosis = f"Nory analiza {fresh_count} mercados frescos. Estado más frecuente: {main_reason}. "
            diagnosis += next(
                (m["reason"] for m in markets if m["action"] == main_reason), ""
            )
        stale_positions = [
            s
            for s in report["state"]["positions"]
            if not any(m["symbol"] == s and m["fresh"] for m in markets)
        ]
        report.update(
            {
                "markets": markets,
                "diagnosis": diagnosis,
                "stale_positions": stale_positions,
                "timestamp": now,
                "mode": "PAPER_ONLY",
                "running": self.running,
                "started_at": self.started_at,
                "fatal_error": self.fatal_error,
                "feeds": {p: f.status() for p, f in self.feeds.items()},
                "metrics": {
                    **dict(self.core.metrics),
                    "coordinator_cycles": self.cycles,
                },
                "config": asdict(self.cfg),
                "prices": [
                    {"time": q.exchange_ts, "price": q.mid}
                    for q in self.core.history_for(provider, "BTC-USD")[-300:]
                ],
            }
        )
        return report
