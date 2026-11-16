
from data.market_data import get_market_data
from analysis.indicators import (
    add_indicators,
    classify_trend,
    classify_rsi
)

print("=" * 55)
print("          AI INVESTMENT SYSTEM")
print("          MARKET INTELLIGENCE v0.3")
print("=" * 55)

markets = {
    "SPY": "ETF S&P 500",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "Euro / Dólar"
}

for symbol, name in markets.items():

    print("\n" + "=" * 55)
    print(f"ACTIVO: {name} ({symbol})")
    print("=" * 55)

    data = get_market_data(symbol)

    if data is None:
        print("No fue posible analizar este activo.")
        continue

    try:
        analyzed = add_indicators(data)

        latest = analyzed.iloc[-1]

        trend = classify_trend(analyzed)
        rsi_status = classify_rsi(latest["RSI_14"])

        print("\nINDICADORES")

        print(f"Precio: {latest['Close']:.4f}")
        print(f"SMA 10: {latest['SMA_10']:.4f}")
        print(f"SMA 30: {latest['SMA_30']:.4f}")

        print(f"RSI 14: {latest['RSI_14']:.2f}")
        print(f"MACD: {latest['MACD']:.5f}")
        print(f"MACD Signal: {latest['MACD_SIGNAL']:.5f}")

        print("\nINTERPRETACION")

        print(f"Tendencia: {trend}")
        print(f"RSI: {rsi_status}")

        if latest["MACD_HIST"] > 0:
            print("Momentum MACD: POSITIVO")
        else:
            print("Momentum MACD: NEGATIVO")

        filename = (
            f"data/{symbol.replace('=', '_')}_analyzed.csv"
        )

        analyzed.to_csv(filename)

        print(f"\nDatos guardados: {filename}")

    except Exception as error:
        print(f"Error analizando el activo: {error}")

print("\n" + "=" * 55)
print("ANALISIS COMPLETADO")
print("AIS MARKET INTELLIGENCE v0.3")
print("=" * 55)

print("\nNOTA: Los indicadores no garantizan resultados.")
print("Este programa no realiza operaciones reales.")
