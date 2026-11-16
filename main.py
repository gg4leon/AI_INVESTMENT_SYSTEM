"""AI Investment System 0.5: analisis y paper backtesting; NUNCA envia ordenes."""
import argparse
import json
from pathlib import Path

from analysis.indicators import add_indicators, classify_rsi, classify_trend
from analysis.risk_engine import assess_risk
from analysis.signal_engine import generate_signal
from backtesting.engine import BacktestConfig, run_backtest
from data.demo_data import make_demo_data
from data.market_data import get_market_data

MARKETS = {
    "SPY": "ETF S&P 500",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "Euro / Dolar",
}
OUTPUT = Path("data")


def analyze_market(
    symbol: str,
    name: str,
    mode: str = "all",
    period: str = "2y",
    demo: bool = False,
) -> bool:
    """Descarga/hace demo, analiza y guarda resultados sin afectar dinero real."""
    print("\n" + "=" * 65)
    print(f"{name} ({symbol}) | {'DEMO SINTETICA' if demo else 'HISTORICO YAHOO'}")
    print("=" * 65)
    raw = make_demo_data(symbol) if demo else get_market_data(symbol, period=period)
    if raw is None or raw.empty:
        print("Sin datos. No se genera reporte ni se asume un precio.")
        return False

    try:
        analyzed = add_indicators(raw)
        if len(analyzed) < 35:
            print("No hay suficientes velas para evaluar indicadores.")
            return False
        report = generate_signal(analyzed, symbol)
        risk = assess_risk(analyzed, symbol)
        latest = analyzed.iloc[-1]
        safe = symbol.replace("=", "_").replace("/", "_")
        OUTPUT.mkdir(parents=True, exist_ok=True)

        if mode in ("analyze", "all"):
            print(f"Ultima vela: {report.timestamp}")
            print(f"Close: {latest['Close']:.4f}")
            print(f"SMA10: {latest['SMA_10']:.4f} | SMA30: {latest['SMA_30']:.4f}")
            print(f"RSI14: {latest['RSI_14']:.2f} ({classify_rsi(latest['RSI_14'])})")
            print(f"MACD: {latest['MACD']:.5f} | Signal: {latest['MACD_SIGNAL']:.5f}")
            print(f"Tendencia SMA: {classify_trend(analyzed)}")
            print(f"Senal experimental: {report.signal} | {report.bias}")
            print(f"Acuerdo de reglas: {report.agreement}/3 (NO es probabilidad)")
            for obs in report.observations:
                print(f"  - {obs}")
            for warning in report.warnings:
                print(f"  AVISO: {warning}")
            print(f"Riesgo historico: {risk.risk_level}")
            print(f"Volatilidad diaria 20 velas: {risk.volatility_20d_pct}%")
            print(f"Drawdown maximo ultimas 60 velas: {risk.max_drawdown_pct}%")
            analyzed.to_csv(OUTPUT / f"{safe}_analyzed.csv")
            result = report.as_dict()
            result["data_source"] = "SYNTHETIC_DEMO" if demo else "YAHOO_HISTORICAL"
            result["risk"] = {
                "volatility_20d_pct": risk.volatility_20d_pct,
                "max_drawdown_pct": risk.max_drawdown_pct,
                "risk_level": risk.risk_level,
                "warnings": list(risk.warnings),
            }
            (OUTPUT / f"{safe}_report.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Analisis guardado: data/{safe}_report.json")

        if mode in ("backtest", "all"):
            if len(analyzed) <= 50:
                print("Backtest omitido: hacen falta mas de 50 velas.")
                return False
            result = run_backtest(analyzed, symbol, BacktestConfig())
            summary = result.summary()
            summary["data_source"] = "SYNTHETIC_DEMO" if demo else "YAHOO_HISTORICAL"
            print("\nBACKTEST HISTORICO — SOLO SIMULACION")
            print(f"Capital ficticio inicial: {result.initial_cash:.2f} USD-equivalente")
            print(f"Equity final: {result.final_equity:.2f} | Retorno: {result.total_return_pct:.2f}%")
            print(f"Comprar/mantener (bruto): {result.benchmark_return_pct:.2f}%")
            print(f"Max drawdown: {result.max_drawdown_pct:.2f}%")
            print(f"Volatilidad anualizada: {result.annualized_volatility_pct:.2f}%")
            print(f"Sharpe (tasa libre riesgo=0): {result.sharpe_zero_rf}")
            print(f"Operaciones cerradas: {result.closed_trades}")
            print(f"Tasa de acierto (solo cerradas): {result.win_rate_pct}")
            print(f"Exposicion: {result.exposure_pct:.1f}% | Abierta: {result.open_position}")
            result.equity_curve.to_csv(OUTPUT / f"{safe}_backtest_equity.csv")
            result.trades.to_csv(OUTPUT / f"{safe}_backtest_trades.csv", index=False)
            (OUTPUT / f"{safe}_backtest_summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Backtest guardado: data/{safe}_backtest_summary.json")
        return report.valid
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        print(f"Error controlado para {symbol}: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AIS v0.5: analisis y backtesting educativo; no opera dinero real."
    )
    parser.add_argument("--mode", choices=("all", "analyze", "backtest"),
                        default="all", help="Modo de ejecucion")
    parser.add_argument("--period", default="2y", help="Historial Yahoo, ej. 2y/5y")
    parser.add_argument("--symbols", nargs="+", choices=tuple(MARKETS),
                        help="Selecciona uno o varios activos")
    parser.add_argument("--demo", action="store_true",
                        help="Datos sinteticos, funciona sin Internet (NO reales)")
    args = parser.parse_args()

    print("AIS MARKET INTELLIGENCE v0.5 — INVESTIGACION / PAPER ONLY")
    print("NO se conectan brokers, NO se envian ordenes ni se usa capital real.")
    if args.demo:
        print("*** DATOS INVENTADOS PARA PRUEBAS; NO SON COTIZACIONES ***")
    symbols = args.symbols or list(MARKETS)
    successful = sum(analyze_market(
        symbol, MARKETS[symbol], args.mode, args.period, args.demo
    ) for symbol in symbols)
    print(f"\nProcesados correctamente: {successful}/{len(symbols)}")
    print("Advertencia: rendimiento pasado no garantiza resultados futuros.")
    return 0 if successful == len(symbols) else 1


if __name__ == "__main__":
    raise SystemExit(main())
