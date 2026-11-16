import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
import json
import logging
from pathlib import Path
import sys
import threading
import webbrowser

from .nory.config import BASE, load_config


async def probe(cfg, seconds, provider, output):
    from .nory.feeds import PublicFeed

    counts, samples = {}, {}

    def record(q, now):
        counts[q.provider] = counts.get(q.provider, 0) + 1
        samples[q.provider] = q.as_dict()

    providers = cfg.providers if provider == "both" else (provider,)
    feeds = [PublicFeed(p, cfg.symbols, record) for p in providers]
    tasks = [asyncio.create_task(f.run()) for f in feeds]
    try:
        await asyncio.sleep(seconds)
        status = {
            "tested_at_utc": datetime.now(timezone.utc).isoformat(),
            "seconds": seconds,
            "test": "LIVE_PUBLIC_WEBSOCKET_NO_PAPER_ORDERS",
            "counts": counts,
            "samples": samples,
            "providers": [f.status() for f in feeds],
            "passed": all(counts.get(p, 0) > 0 for p in providers),
        }
        text = json.dumps(status, indent=2, ensure_ascii=False, allow_nan=False)
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(text)
        return 0 if status["passed"] else 2
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="NORY 2.0 · datos públicos, paper trading exclusivamente"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "probe", "backtest", "config"),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--db", type=Path, default=BASE / "data" / "nory.sqlite3")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Panel sin conexiones; no genera precios de prueba",
    )
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument(
        "--provider", choices=("coinbase", "kraken", "both"), default="both"
    )
    parser.add_argument("--csv", type=Path)
    parser.add_argument(
        "--context",
        type=Path,
        help="Contexto histórico exportado con sus fechas de adquisición",
    )
    parser.add_argument(
        "--source", choices=("DECLARED_PUBLIC_CSV_UNVERIFIED", "SYNTHETIC_TEST")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 5 <= args.seconds <= 120:
        parser.error("Puerto o duración inválidos (probe: 5–120 s)")
    try:
        cfg = load_config(args.config)
        if args.command == "config":
            text = json.dumps(asdict(cfg), indent=2, ensure_ascii=False)
            if args.output:
                args.output.write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
            return 0
        if args.command == "probe":
            return asyncio.run(probe(cfg, args.seconds, args.provider, args.output))
        if args.command == "backtest":
            from .nory.backtest import read_csv, read_context, validate

            if not args.csv or not args.source:
                parser.error(
                    "backtest requiere --csv y --source para declarar la procedencia"
                )
            result = validate(
                read_csv(args.csv),
                cfg,
                source=args.source,
                context=read_context(args.context) if args.context else (),
            )
            text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
            if args.output:
                args.output.write_text(text + "\n", encoding="utf-8")
                print(f"Validación guardada en {args.output}")
            else:
                print(text)
            return 0
        import uvicorn
        from .server import create_app

        (BASE / "logs").mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            BASE / "logs" / "nory.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logging.basicConfig(
            level=logging.INFO, handlers=[handler, logging.StreamHandler()]
        )
        url = f"http://127.0.0.1:{args.port}"
        print(
            f"NORY 2.0 · PAPER ONLY\nPanel local: {url}\nCtrl+C para cerrar. Inicia detenido; no hay operaciones reales."
        )
        if not args.no_browser:
            timer = threading.Timer(1.5, lambda: webbrowser.open(url))
            timer.daemon = True
            timer.start()
        uvicorn.run(
            create_app(cfg, args.db, network=not args.offline),
            host="127.0.0.1",
            port=args.port,
            workers=1,
            log_level="info",
            access_log=False,
        )
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Nory no pudo continuar: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
