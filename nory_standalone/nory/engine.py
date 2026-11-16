import asyncio
from dataclasses import asdict
import logging
from pathlib import Path
import time

from .core import ResearchCore
from .config import RULES_VERSION
from .feeds import PublicFeed
from .history import PublicHistoryClient
from .storage import Store, resolve_database

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
    def __init__(
        self,
        cfg,
        db_path,
        *,
        network=True,
        feed_factory=PublicFeed,
        history_factory=PublicHistoryClient,
    ):
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
        self.migration = None
        self.history_factory = history_factory
        self.history_client = None
        self.history_queue = asyncio.Queue(
            maxsize=len(cfg.symbols) * len(cfg.providers)
        )
        self.history_pending = set()
        self.history_attempts = {}
        self.history_status = {}

    async def open(self):
        self.db_path, self.migration = await asyncio.to_thread(
            resolve_database, self.db_path, self.cfg
        )
        self.process_lock = ProcessLock(str(self.db_path) + ".lock")
        self.process_lock.acquire()
        try:
            self.store = Store(self.db_path, self.cfg)
            accounts, latest, freeze = self.store.restore()
            self.core = ResearchCore(self.cfg, accounts)
            self.core.latest = {(q.provider, q.symbol): q for q in latest}
            self.core.freeze_until = {(p, s): until for p, s, until in freeze}
            now = time.time()
            cached = await asyncio.to_thread(
                self.store.context,
                start=now
                - self.cfg.analysis_interval_seconds * self.cfg.analysis_lookback,
                end=now,
            )
            self.core.analysis.seed(cached, now, record=False)
            self.core.cancel_all("CANCELED_RESTART")
            await self._checkpoint([], time.time())
            if self.network:
                self.history_client = self.history_factory(self.cfg)
                self.tasks.append(
                    asyncio.create_task(self._history_loop(), name="nory-history")
                )
                for provider in self.cfg.providers:
                    for symbol in self.cfg.symbols:
                        self._request_history(provider, symbol, now)
                    feed = self.feed_factory(provider, self.cfg.symbols, self.receive)
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
        if self.history_client:
            await self.history_client.close()
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
            "context": [p.as_dict() for p in self.core.analysis.events],
            "decisions": decisions,
            "freeze": [
                [p, s, until]
                for (p, s), until in self.core.freeze_until.items()
                if until > now
            ],
        }
        self.core.analysis.events.clear()
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
                    if changed or self.core.order_events or self.core.analysis.events:
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

    def receive(self, quote, now):
        accepted = self.core.receive(quote, now)
        if accepted:
            self._request_history(quote.provider, quote.symbol, now)
        return accepted

    def _request_history(self, provider, symbol, now):
        key = provider, symbol
        if not self.network or self.cfg.analysis_interval_seconds not in (60, 300):
            return
        if not self.core.analysis.needs_backfill(provider, symbol, now):
            previous = self.history_status.get(key)
            self.history_status[key] = {
                **(previous or {}),
                "state": "READY" if previous else "CACHED",
                "error": None,
            }
            return
        if key in self.history_pending or now - self.history_attempts.get(key, 0) < 90:
            return
        self.history_pending.add(key)
        self.history_status[key] = {"state": "LOADING", "error": None}
        self.history_queue.put_nowait(key)

    async def _history_loop(self):
        while True:
            provider, symbol = key = await self.history_queue.get()
            self.history_attempts[key] = time.time()
            try:
                samples = await self.history_client.fetch(provider, symbol)
                if not samples:
                    raise ValueError(
                        "El proveedor no devolvió velas públicas cerradas."
                    )
                async with self.guard:
                    self.core.analysis.seed(samples, time.time())
                    await self._checkpoint([], time.time())
                self.history_status[key] = {
                    "state": "PARTIAL"
                    if self.core.analysis.needs_backfill(provider, symbol, time.time())
                    else "READY",
                    "error": "El contexto todavía tiene huecos o es insuficiente."
                    if self.core.analysis.needs_backfill(provider, symbol, time.time())
                    else None,
                    "candles": len(samples),
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.pending_checkpoint is not None:
                    self.running = False
                    self.fatal_error = f"Error al persistir el contexto: {exc}"
                    log.exception("Motor detenido por error de persistencia")
                    return
                self.history_status[key] = {"state": "ERROR", "error": str(exc)[:240]}
                log.warning(
                    "Historial público %s %s: %s", provider, symbol, str(exc)[:240]
                )
            finally:
                self.history_pending.discard(key)
                self.history_queue.task_done()

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
            history = (
                self.core.analysis.points_for(q)
                if q
                else self.core.analysis.closed_for(provider, symbol, now)
            )
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
                    "change_label": "Ventana de análisis observada",
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
                    "analysis_span_seconds": q.exchange_ts - history[0].exchange_ts
                    if q and history
                    else 0,
                    "history_status": self.history_status.get(
                        (provider, symbol), {"state": "OBSERVING", "error": None}
                    ),
                    "position": pos,
                }
            )
        fresh_count = sum(m["fresh"] for m in markets)
        activity = {
            "evaluations": self.core.activity[(account_id, "EVALUATED")],
            "ready_evaluations": self.core.activity[(account_id, "READY_EVALUATED")],
            "cost_rejections": self.core.activity[(account_id, "COST_FILTER")],
            "risk_rejections": self.core.activity[(account_id, "BLOCK_RISK")],
            "fills": report["stats"]["fills"],
            "positions": len(report["state"]["positions"]),
            "pending": len(report["state"]["orders"]),
            "scope": "Evaluaciones de esta cartera desde que se abrió el proceso; fills de todo su historial.",
        }
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
        elif activity["pending"]:
            diagnosis = f"Hay {activity['pending']} órdenes pendientes. Nory espera cotizaciones posteriores para simular su ejecución."
        elif activity["positions"]:
            diagnosis = f"Nory vigila {activity['positions']} posiciones y ha registrado {activity['fills']} ejecuciones ficticias. El capital neto incluye su valor y costes estimados de salida."
        else:
            ready = [
                m
                for m in markets
                if m["fresh"]
                and m["samples"] >= self.cfg.min_history
                and m["action"] != "WARMUP"
            ]
            if not ready:
                errors = [
                    m["history_status"]["error"]
                    for m in markets
                    if m["history_status"].get("error")
                ]
                diagnosis = f"Preparando contexto de minutos y horas para {fresh_count} mercados frescos. El capital sigue en efectivo hasta tener historial suficiente."
                if errors:
                    diagnosis += " Historial público: " + errors[0]
            else:
                best = max(ready, key=lambda m: m["headroom_bps"])
                threshold = best["features"].get(
                    "entry_threshold_bps",
                    2 * (self.cfg.fee_bps[provider] + self.cfg.slippage_bps)
                    + (best["spread_bps"] or 0)
                    + self.cfg.min_net_edge_bps,
                )
                if best["headroom_bps"] < threshold:
                    diagnosis = (
                        f"Sin compras: el margen técnico de {best['symbol']} es {best['headroom_bps'] / 100:.2f} %; "
                        f"se exige {threshold / 100:.2f} % por costes y margen adicional. "
                        f"{activity['evaluations']} evaluaciones realizadas; el capital permanece en efectivo."
                    )
                else:
                    diagnosis = "Sin compras: " + best["reason"]
        stale_positions = [
            s
            for s in report["state"]["positions"]
            if not any(m["symbol"] == s and m["fresh"] for m in markets)
        ]
        report.update(
            {
                "markets": markets,
                "diagnosis": diagnosis,
                "activity": activity,
                "migration": self.migration,
                "history": {
                    f"{p}:{s}": status for (p, s), status in self.history_status.items()
                },
                "stale_positions": stale_positions,
                "timestamp": now,
                "mode": "PAPER_ONLY",
                "rules_version": RULES_VERSION,
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
