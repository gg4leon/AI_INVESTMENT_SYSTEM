
import yfinance as yf
import pandas as pd


def get_market_data(symbol, period="6mo", interval="1d"):
    """
    Obtiene datos históricos de un activo financiero.
    No ejecuta operaciones.
    """

    print(f"\nConsultando mercado: {symbol}")

    try:
        ticker = yf.Ticker(symbol)

        data = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=True
        )

        if data.empty:
            print("No se encontraron datos.")
            return None

        data = data.dropna(subset=["Close"])

        print(f"Datos recibidos: {len(data)} registros")
        print(f"Último precio: {data['Close'].iloc[-1]:.4f}")

        return data

    except Exception as error:
        print(f"Error consultando {symbol}: {error}")
        return None


if __name__ == "__main__":

    markets = [
        "SPY",       # ETF del S&P 500
        "BTC-USD",   # Bitcoin
        "EURUSD=X"   # Euro / dólar
    ]

    for market in markets:
        data = get_market_data(market)

        if data is not None:
            print(data.tail(3))
