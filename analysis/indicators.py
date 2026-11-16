
import pandas as pd
import numpy as np


def add_indicators(data):
    """
    Calcula indicadores técnicos sobre datos históricos.
    No genera órdenes de compra ni venta.
    """

    if data is None or data.empty:
        raise ValueError("No hay datos para analizar.")

    df = data.copy()

    if "Close" not in df.columns:
        raise ValueError("Falta la columna Close.")

    close = pd.to_numeric(df["Close"], errors="coerce")

    # 1. Medias móviles
    df["SMA_10"] = close.rolling(10).mean()
    df["SMA_30"] = close.rolling(30).mean()

    # 2. RSI de 14 periodos
    delta = close.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(
        alpha=1/14,
        min_periods=14,
        adjust=False
    ).mean()

    avg_loss = losses.ewm(
        alpha=1/14,
        min_periods=14,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["RSI_14"] = 100 - (100 / (1 + rs))

    # Evitar valores indefinidos
    df.loc[
        (avg_loss == 0) & (avg_gain > 0),
        "RSI_14"
    ] = 100

    df.loc[
        (avg_gain == 0) & (avg_loss > 0),
        "RSI_14"
    ] = 0

    df.loc[
        (avg_gain == 0) & (avg_loss == 0),
        "RSI_14"
    ] = 50

    # 3. MACD
    ema_12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema_26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    df["MACD"] = ema_12 - ema_26

    df["MACD_SIGNAL"] = df["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["MACD_HIST"] = (
        df["MACD"] - df["MACD_SIGNAL"]
    )

    # 4. Volumen promedio
    if "Volume" in df.columns:
        df["VOLUME_SMA_20"] = (
            df["Volume"].rolling(20).mean()
        )

    return df


def classify_trend(data):
    """
    Clasificación básica de tendencia.
    """

    latest = data.iloc[-1]

    if pd.isna(latest["SMA_10"]) or pd.isna(latest["SMA_30"]):
        return "DATOS INSUFICIENTES"

    if latest["SMA_10"] > latest["SMA_30"]:
        return "ALCISTA"

    if latest["SMA_10"] < latest["SMA_30"]:
        return "BAJISTA"

    return "LATERAL"


def classify_rsi(value):

    if pd.isna(value):
        return "SIN DATOS"

    if value >= 70:
        return "POSIBLE SOBRECOMPRA"

    if value <= 30:
        return "POSIBLE SOBREVENTA"

    return "ZONA NEUTRAL"
