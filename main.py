
"""AIS v0.4: analisis tecnico explicable (solo investigacion y simulacion)."""
from pathlib import Path
import json
import pandas as pd

from data.market_data import get_market_data
from analysis.indicators import add_indicators, classify_trend, classify_rsi
from analysis.signal_engine import generate_signal
from analysis.risk_engine import assess_risk

MARKETS = {
    "SPY": "ETF S&P 500",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "Euro / Dolar",
}
OUTPUT = Path("data")


def analyze_market(symbol: str, name: str) -> bool:
    print("\n" + "=" * 64)
    print(f"ACTIVO: {name} ({symbol})")
    print("=" * 64)
    data = get_market_data(symbol)
    if data is None or data.empty:
        print("SIN ANALISIS: No hay datos de mercado.")
        return False
    try:
        if len(data) < 35:
            print(f"SIN ANALISIS: Solo {len(data)} velas; se requieren al menos 35.")
            return False
        analyzed = add_indicators(data)
        report = generate_signal(analyzed, symbol)
        risk = assess_risk(analyzed, symbol)
        latest = analyzed.iloc[-1]
        print(f"Ultima vela: {report.timestamp}")
        print(f"Precio: {latest['Close']:.4f}")
        print(f"SMA10: {latest['SMA_10']:.4f} | SMA30: {latest['SMA_30']:.4f}")
        print(f"RSI14: {latest['RSI_14']:.2f} ({classify_rsi(latest['RSI_14'])})")
        print(f"MACD: {latest['MACD']:.5f} | Signal: {latest['MACD_SIGNAL']:.5f}")
        print(f"Tendencia SMA: {classify_trend(analyzed)}")
        print("\nMOTOR DE SENALES - SOLO SIMULACION")
        print(f"Etiqueta: {report.signal} | Sesgo: {report.bias}")
        print(f"Acuerdo: {report.agreement}/3 | Score heuristico: {report.score}/100")
        for observation in report.observations:
            print(f"  - {observation}")
        for warning in report.warnings:
            print(f"  AVISO: {warning}")
        print("\nRIESGO HISTORICO (DESCRIPTIVO)")
        print(f"Volatilidad diaria 20 velas: {risk.volatility_20d_pct}%")
        print(f"Max drawdown ultimas 60 velas: {risk.max_drawdown_pct}%")
        print(f"Categoria descriptiva: {risk.risk_level}")
        for warning in risk.warnings:
            print(f"  AVISO: {warning}")

        OUTPUT.mkdir(parents=True, exist_ok=True)
        safe_name = symbol.replace("=", "_").replace("/", "_")
        analyzed.to_csv(OUTPUT / f"{safe_name}_analyzed.csv")
        result = report.as_dict()
        result["risk"] = {
            "volatility_20d_pct": risk.volatility_20d_pct,
            "max_drawdown_pct": risk.max_drawdown_pct,
            "risk_level": risk.risk_level,
            "warnings": list(risk.warnings),
        }
        (OUTPUT / f"{safe_name}_report.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Reporte guardado: data/{safe_name}_report.json")
        return report.valid
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        print(f"ERROR CONTROLADO: {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    print("AI INVESTMENT SYSTEM | MARKET INTELLIGENCE v0.4")
    print("MODO INVESTIGACION: NO SE ENVIAN ORDENES")
    ok = sum(analyze_market(symbol, name) for symbol, name in MARKETS.items())
    print(f"\nAnalisis validos: {ok}/{len(MARKETS)}")
    print("Las senales NO son recomendaciones ni probabilidades de rentabilidad.")


if __name__ == "__main__":
    main()
