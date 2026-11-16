"""Worker local AIS de paper trading (solo ficticio).

Uso:
 python -m automation.worker --demo --once --symbols SPY AAPL
 python -m automation.worker --once --symbols SPY AAPL BTC-USD
 python -m automation.worker --loop --interval-minutes 60 --symbols SPY AAPL

Requiere que el usuario active el motor en la app; el proceso no se ejecuta
en segundo plano cuando se apaga el equipo. Jamás conecta brókeres.
"""
import argparse
from datetime import datetime
import json
import time

from analysis.indicators import add_indicators
from analysis.signal_engine import generate_signal
from app.markets import MARKET_BY_SYMBOL, PAPER_SYMBOLS
from automation.paper import is_paused, process_bar
from data.demo_data import make_demo_data
from data.market_data import get_market_data


def _closed_historical(data):
    """Omitir la vela correspondiente a 'hoy', potencialmente aún abierta.

    Esto no convierte el precio de cierre en precio de ejecución real.
    """
    if data is None or data.empty:
        return data
    latest = data.index[-1]
    tz = latest.tzinfo
    today = datetime.now(tz).date() if tz else datetime.now().date()
    if latest.date() >= today:
        return data.iloc[:-1]
    return data


def cycle(symbols: tuple[str, ...], demo: bool = False) -> list[dict]:
    out = []
    source = "SYNTHETIC_DEMO" if demo else "YAHOO_HISTORICAL"
    if is_paused():
        print("Motor PAUSADO; activa paper trading desde la app (sin dinero real).")
        return [{"status": "PAUSED"}]
    for symbol in symbols:
        try:
            market = MARKET_BY_SYMBOL[symbol]
            if not market.paper_eligible:
                out.append({"symbol": symbol, "status": "ANALYSIS_ONLY"})
                continue
            raw = make_demo_data(symbol) if demo else get_market_data(symbol, period="1y")
            if not demo:
                raw = _closed_historical(raw)
            if raw is None or len(raw) < 50:
                out.append({"symbol": symbol, "status": "NO_DATA"})
                continue
            analyzed = add_indicators(raw)
            report = generate_signal(analyzed, symbol)
            bar = str(analyzed.index[-1])
            if not report.valid:
                out.append({"symbol": symbol, "status": "INVALID_SIGNAL"})
                continue
            close = float(analyzed["Close"].iloc[-1])
            out.append(process_bar(
                source=source, symbol=symbol, bar=bar, close_price=close,
                signal=report.signal,
            ))
        except Exception as exc:
            # Un mercado no debe impedir que se comprueben los demás.
            out.append({"symbol": symbol, "status": "ERROR", "detail": str(exc)[:200]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="AIS paper-only local automation")
    run_mode = parser.add_mutually_exclusive_group(required=True)
    run_mode.add_argument("--once", action="store_true")
    run_mode.add_argument("--loop", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Datos INVENTADOS")
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument(
        "--symbols", nargs="+", default=["SPY", "AAPL", "MSFT", "BTC-USD"],
        help="Símbolos permitidos del catálogo",
    )
    args = parser.parse_args()
    if not 5 <= args.interval_minutes <= 1440:
        parser.error("interval-minutes debe estar entre 5 y 1440")
    if len(args.symbols) > 15:
        parser.error("Máximo 15 símbolos por ciclo, para evitar consultas excesivas")
    if any(s not in MARKET_BY_SYMBOL for s in args.symbols):
        parser.error("Uno o más símbolos no están en el catálogo")
    if not args.demo and any(s not in PAPER_SYMBOLS for s in args.symbols):
        parser.error("Índices, futuros y divisas son solo de análisis")
    print("AIS PAPER WORKER — NO BROKER — NO REAL ORDERS")
    print("Fills hipotéticos al cierre observado; no precios ejecutables.")
    try:
        while True:
            result = cycle(tuple(dict.fromkeys(args.symbols)), demo=args.demo)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.once:
                break
            time.sleep(args.interval_minutes * 60)
    except KeyboardInterrupt:
        print("Automatización local detenida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
