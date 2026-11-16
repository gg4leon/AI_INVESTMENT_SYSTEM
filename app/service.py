"""Orquestador independiente de Streamlit: solo datos, señales y paper backtesting.

Never substitutes synthetic data after a real market-data failure.
"""
from dataclasses import asdict
import json
import math

from analysis.indicators import add_indicators, classify_rsi, classify_trend
from analysis.risk_engine import assess_risk
from analysis.signal_engine import generate_signal
from backtesting.engine import BacktestConfig, run_backtest
from data.demo_data import make_demo_data
from data.market_data import get_market_data


MARKETS = {
    "SPY": "ETF S&P 500",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "Euro / Dólar",
}
PERIODS = ("1y", "2y", "5y")


def run_analysis(
    symbol: str,
    source: str = "demo",
    period: str = "2y",
    config: BacktestConfig | None = None,
) -> dict:
    """Ejecuta una simulación y devuelve un documento JSON-safe.

    `source=historical` usa Yahoo exclusivamente. No usa bróker, depósitos ni
    información privada. `source=demo` siempre etiqueta datos inventados.
    """
    if symbol not in MARKETS:
        raise ValueError(f"Símbolo no permitido: {symbol}")
    if source not in ("demo", "historical"):
        raise ValueError("source debe ser demo o historical")
    if period not in PERIODS:
        raise ValueError("Periodo inválido")
    cfg = config or BacktestConfig()

    if source == "demo":
        raw = make_demo_data(symbol)
    else:
        raw = get_market_data(symbol, period=period)
        if raw is None or raw.empty:
            raise RuntimeError(
                f"No se obtuvieron datos históricos de Yahoo para {symbol}. "
                "No se sustituyen por datos sintéticos."
            )

    if raw is None or raw.empty:
        raise ValueError("Fuente de datos vacía")

    analyzed = add_indicators(raw)
    if len(analyzed) <= cfg.warmup_bars:
        raise ValueError(
            f"Se necesitan más de {cfg.warmup_bars} velas para simular."
        )
    if raw.index.has_duplicates or not raw.index.is_monotonic_increasing:
        raise ValueError("Fechas duplicadas o desordenadas")

    signal = generate_signal(analyzed, symbol)
    risk = assess_risk(analyzed, symbol)
    result = run_backtest(analyzed, symbol, cfg)
    price = float(analyzed["Close"].iloc[-1])
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Último cierre inválido")

    cols = [
        name for name in (
            "Open", "High", "Low", "Close", "SMA_10", "SMA_30",
            "RSI_14", "MACD", "MACD_SIGNAL", "MACD_HIST"
        ) if name in analyzed.columns
    ]
    candle_frame = analyzed[cols].tail(250).copy()
    candle_frame.insert(
        0, "timestamp", [str(value) for value in candle_frame.index]
    )

    equity_frame = result.equity_curve.reset_index()

    snapshot = {
        "schema_version": 1,
        "app_version": "0.6",
        "symbol": symbol,
        "market_name": MARKETS[symbol],
        "source": "SYNTHETIC_DEMO" if source == "demo" else "YAHOO_HISTORICAL",
        "period": period if source == "historical" else "synthetic_600_bars",
        "last_candle": str(analyzed.index[-1]),
        "last_close": price,
        "trend": classify_trend(analyzed),
        "rsi_text": classify_rsi(analyzed["RSI_14"].iloc[-1]),
        "signal": signal.as_dict(),
        "risk": asdict(risk),
        "backtest": result.summary(),
        "price_history": json.loads(
            candle_frame.to_json(orient="records")
        ),
        "equity_curve": json.loads(
            equity_frame.to_json(orient="records")
        ),
        "trades": json.loads(
            result.trades.to_json(orient="records")
        ),
    }
    # Defensively ensure no NaN/Infinity breaks SQLite JSON or UI.
    json.dumps(snapshot, allow_nan=False)
    return snapshot
