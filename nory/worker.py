"""Nory multi-market scanner and local scheduler.

Parallelism is limited to four network-bound readers. Decisions remain
sequential and atomic in SQLite. No broker and no real orders.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import time

from app.markets import MARKET_BY_SYMBOL, MARKETS
from data.demo_data import make_demo_data
from data.market_data import get_market_data
from nory.book import DEFAULT_DB, apply_cycle, is_paused, next_demo_step
from nory.engine import (
    NoryPolicy, observation_from_prices, source_is_fresh,
)


DEFAULT_SYMBOLS = ("SPY","QQQ","AAPL","MSFT","NVDA","AMZN","BTC-USD","ETH-USD")


def validate_symbols(symbols):
    cleaned = tuple(dict.fromkeys(symbols))
    if not cleaned or len(cleaned) > 20:
        raise ValueError("Nory acepta entre 1 y 20 símbolos por ciclo")
    invalid = [
        sym for sym in cleaned
        if sym not in MARKET_BY_SYMBOL
        or not MARKET_BY_SYMBOL[sym].paper_eligible
        or MARKET_BY_SYMBOL[sym].currency != "USD"
    ]
    if invalid:
        raise ValueError("Nory solo admite acciones, ETF y criptomonedas cotizados en USD: "
                         + ", ".join(invalid))
    return cleaned


def _load_one(symbol: str, demo: bool, demo_step: int):
    if demo:
        # Progresses exactly one deterministic bar each time the user runs a cycle.
        data = make_demo_data(symbol, bars=600).iloc[:140 + demo_step].copy()
    else:
        data = get_market_data(symbol, period="1y")
        if data is None or data.empty:
            raise ValueError("Sin datos Yahoo; no se sustituyen por datos inventados")
        last = data.index[-1]
        current_day = datetime.now(last.tzinfo or timezone.utc).date()
        if last.date() >= current_day:
            data = data.iloc[:-1]  # conservative: never use possibly open candle
        if data.empty:
            raise ValueError("Sin velas históricas cerradas")
    obs = observation_from_prices(data, symbol)
    if not demo and not source_is_fresh(obs.bar, obs.category):
        raise ValueError("Última vela demasiado antigua; señal omitida")
    return obs, data


def scan_markets(
    symbols, demo=False, demo_step=0, max_workers=4,
    loader=None,
) -> tuple[dict, list[dict]]:
    """Concurrent data retrieval; deterministic results; no writes or positions."""
    symbols = validate_symbols(symbols)
    if not 1 <= max_workers <= 4:
        raise ValueError("Maximo de cuatro descargas paralelas")
    if demo and not 0 <= demo_step <= 439:
        raise ValueError("Paso de demo fuera de rango")
    load = loader or _load_one
    data_by_symbol, warnings = {}, []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as pool:
        futures = {
            pool.submit(load, symbol, demo, demo_step): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                obs, frame = future.result()
                data_by_symbol[symbol] = (obs, frame)
            except Exception as exc:
                warnings.append({
                    "symbol":symbol,"status":"SKIPPED",
                    "reason":f"{type(exc).__name__}: {str(exc)[:170]}",
                })
    return {sym:data_by_symbol[sym] for sym in sorted(data_by_symbol)}, sorted(
        warnings, key=lambda x:x["symbol"]
    )


def run_once(
    symbols=DEFAULT_SYMBOLS, demo: bool = False,
    db_path=DEFAULT_DB, policy: NoryPolicy | None = None,
    max_workers: int = 4,
) -> dict:
    symbols = validate_symbols(symbols)
    if is_paused(db_path):
        return {
            "status":"PAUSED","note":"Nory debe ser activado manualmente en el dashboard",
            "warnings":[],"events":[],
        }
    step = next_demo_step(db_path) if demo else 0
    batch, warnings = scan_markets(
        symbols, demo=demo, demo_step=step, max_workers=max_workers,
    )
    source = "SYNTHETIC_DEMO" if demo else "YAHOO_HISTORICAL"
    if not batch:
        return {"status":"NO_VALID_DATA","source":source,"warnings":warnings,"events":[]}
    result = apply_cycle(batch, source=source, db_path=db_path, policy=policy)
    result["scanned"] = list(batch)
    result["warnings"] = warnings
    result["demo_step"] = step if demo else None
    result["parallel_workers"] = min(max_workers, len(symbols))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nory 0.7 multiasset portfolio worker. ONLY PAPER TRADING."
    )
    run = parser.add_mutually_exclusive_group(required=True)
    run.add_argument("--once", action="store_true")
    run.add_argument("--loop", action="store_true")
    parser.add_argument("--demo", action="store_true",
                        help="PRECIOS INVENTADOS, sin mercado real")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS),
                        help="1–20 símbolos del catálogo, solo USD")
    parser.add_argument("--interval-minutes",type=int,default=60)
    parser.add_argument("--workers",type=int,default=4)
    args = parser.parse_args()
    try:
        validate_symbols(args.symbols)
    except ValueError as exc:
        parser.error(str(exc))
    if not 15 <= args.interval_minutes <= 1440:
        parser.error("interval-minutes entre 15 y 1440")
    if not 1 <= args.workers <= 4:
        parser.error("workers entre 1 y 4")
    print("NORY v0.7 — MULTI-MARKET PAPER PORTFOLIO — NO REAL ORDERS")
    print("Solo velas diarias confirmadas; no es trading de alta frecuencia.")
    try:
        while True:
            print(json.dumps(
                run_once(args.symbols, demo=args.demo, max_workers=args.workers),
                ensure_ascii=False, indent=2, allow_nan=False,
            ))
            if args.once:
                break
            time.sleep(args.interval_minutes * 60)
    except KeyboardInterrupt:
        print("Nory detenido por el usuario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
