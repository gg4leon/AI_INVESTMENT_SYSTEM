from contextlib import asynccontextmanager, closing
from dataclasses import asdict
import asyncio
import csv
import io
import json
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .nory.backtest import validate
from .nory.config import BASE, LABELS, Config
from .nory.engine import Engine
from .nory.launcher import APP_ID, instance_id
from . import __version__


class ResearchRequest(BaseModel):
    provider: str = "coinbase"


def create_app(cfg=None, db_path=None, *, network=True):
    cfg = cfg or Config()
    token = secrets.token_urlsafe(32)
    engine = Engine(cfg, db_path or BASE / "data" / "nory.sqlite3", network=network)
    research_tasks = set()
    research_state = {"running": False, "error": None}

    @asynccontextmanager
    async def lifespan(app):
        await engine.open()
        try:
            yield
        finally:
            if research_tasks:
                await asyncio.gather(*research_tasks, return_exceptions=True)
            await engine.close()

    app = FastAPI(
        title="NORY 2.0 · Paper Research",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.engine = engine
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def local_controls(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Origen externo rechazado"}, status_code=403
                )
            if not secrets.compare_digest(
                request.headers.get("x-nory-token", ""), token
            ):
                return JSONResponse(
                    {"detail": "Sesión local inválida; recarga el panel"},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/")
    async def index():
        return FileResponse(BASE / "static" / "index.html")

    @app.get("/api/session")
    async def session():
        return {"token": token, "config": asdict(cfg), "strategies": LABELS}

    @app.get("/api/health")
    async def health():
        return {
            "app": APP_ID,
            "version": __version__,
            "mode": "PAPER_ONLY",
            "instance_id": instance_id(cfg, engine.db_path),
        }

    @app.get("/api/status")
    async def status(provider: str = "coinbase", strategy: str = "trend"):
        return {
            **await engine.snapshot(provider, strategy),
            "research_state": research_state,
        }

    @app.get("/api/stream")
    async def stream(
        request: Request, provider: str = "coinbase", strategy: str = "trend"
    ):
        if f"{provider}:{strategy}" not in engine.core.accounts:
            raise HTTPException(400, "Cartera desconocida")

        async def events():
            while not await request.is_disconnected():
                result = {
                    **await engine.snapshot(provider, strategy),
                    "research_state": research_state,
                }
                yield (
                    "data: "
                    + json.dumps(
                        result,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    + "\n\n"
                )
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/start")
    async def start():
        return await engine.start()

    @app.post("/api/stop")
    async def stop():
        return await engine.stop()

    @app.post("/api/emergency")
    async def emergency():
        return await engine.stop(emergency=True)

    async def run_research(provider):
        try:
            quotes = await asyncio.to_thread(engine.store.recorded, provider, 30_000)
            context = await asyncio.to_thread(
                engine.store.context,
                provider=provider,
                start=quotes[0].received_ts
                - cfg.analysis_lookback * cfg.analysis_interval_seconds
                if quotes
                else 0,
                end=quotes[-1].received_ts if quotes else time.time(),
            )
            result = await asyncio.to_thread(validate, quotes, cfg, context=context)
            await asyncio.to_thread(engine.store.save_research, result, time.time())
        except Exception as exc:
            research_state["error"] = str(exc)[:400]
        finally:
            research_state["running"] = False

    @app.post("/api/research")
    async def research(body: ResearchRequest):
        if body.provider not in cfg.providers:
            raise ValueError("Proveedor inválido")
        if research_state["running"]:
            raise HTTPException(409, "Ya hay una evaluación en curso")
        research_state.update(running=True, error=None)
        task = asyncio.create_task(
            run_research(body.provider), name="nory-offline-validation"
        )
        research_tasks.add(task)
        task.add_done_callback(research_tasks.discard)
        return {
            "started": True,
            "reason": "Evaluación del historial registrado iniciada; no cambia las estrategias activas.",
        }

    @app.get("/api/export/{kind}")
    async def export(kind: str, provider: str = "coinbase", strategy: str = "trend"):
        if kind == "context" and provider in cfg.providers:
            points = await asyncio.to_thread(
                engine.store.context,
                provider=provider,
                end=time.time(),
                limit=cfg.max_recorded_samples,
            )
            return JSONResponse(
                {
                    "mode": "RECORDED_PUBLIC_CONTEXT",
                    "points": [p.as_dict() for p in points],
                },
                headers={
                    "Content-Disposition": f'attachment; filename="nory_{provider}_context.json"'
                },
            )
        if (
            kind not in ("quotes", "fills", "round_trips")
            or f"{provider}:{strategy}" not in engine.core.accounts
        ):
            raise ValueError("Exportación desconocida")

        def rows():
            with closing(engine.store.reader()) as db:
                if kind == "quotes":
                    cursor = db.execute(
                        "SELECT data FROM samples WHERE provider=? ORDER BY received_ts",
                        (provider,),
                    )
                    columns = [
                        "provider",
                        "symbol",
                        "exchange_ts",
                        "received_ts",
                        "bid",
                        "ask",
                        "bid_qty",
                        "ask_qty",
                        "sequence",
                        "volume_24h",
                        "change_24h_pct",
                    ]
                else:
                    ordering = "filled_at" if kind == "fills" else "closed_at"
                    cursor = db.execute(
                        f"SELECT data FROM {kind} WHERE account=? ORDER BY {ordering}",
                        (f"{provider}:{strategy}",),
                    )
                    columns = (
                        [
                            "id",
                            "account",
                            "order_id",
                            "symbol",
                            "side",
                            "decision_ts",
                            "decision_quote_ts",
                            "quote_ts",
                            "received_ts",
                            "filled_at",
                            "qty",
                            "price",
                            "bid",
                            "ask",
                            "fee",
                            "realized_pnl",
                            "cash_after",
                            "reason",
                        ]
                        if kind == "fills"
                        else [
                            "id",
                            "account",
                            "symbol",
                            "opened_at",
                            "closed_at",
                            "pnl",
                        ]
                    )
                buffer = io.StringIO()
                writer = csv.DictWriter(
                    buffer, fieldnames=["mode", *columns], extrasaction="ignore"
                )
                writer.writeheader()
                yield buffer.getvalue()
                for row in cursor:
                    buffer.seek(0)
                    buffer.truncate(0)
                    writer.writerow(
                        {
                            "mode": "PUBLIC_WS_SAMPLED"
                            if kind == "quotes"
                            else "PAPER_ONLY",
                            **json.loads(row[0]),
                        }
                    )
                    yield buffer.getvalue()

        return StreamingResponse(
            rows(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="nory_{provider}_{strategy}_{kind}.csv"'
            },
        )

    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    return app
