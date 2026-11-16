"""Datos 100% SINTETICOS, reproducibles; nunca tratarlos como datos del mercado."""
import hashlib
import numpy as np
import pandas as pd


def make_demo_data(symbol: str, bars: int = 600) -> pd.DataFrame:
    """Genera OHLCV de prueba sin descarga, con semilla estable."""
    if bars < 60:
        raise ValueError("bars debe ser >= 60")
    seeds = {"SPY": 17, "BTC-USD": 23, "EURUSD=X": 47}
    seed = seeds.get(symbol)
    if seed is None:
        seed = int.from_bytes(hashlib.sha256(symbol.encode("utf-8")).digest()[:4], "big")
    rng = np.random.default_rng(seed)
    # Ciclos de tendencia para ejercitar entradas y salidas.
    t = np.arange(bars)
    drift = 0.00015 + 0.002 * np.sin(t / 36)
    shocks = rng.normal(0, 0.006, bars)
    close = 100 * np.exp(np.cumsum(drift + shocks))
    open_px = np.concatenate(([100.0], close[:-1])) * (1 + rng.normal(0, 0.0015, bars))
    high = np.maximum(close, open_px) * (1 + rng.uniform(0, 0.004, bars))
    low = np.minimum(close, open_px) * (1 - rng.uniform(0, 0.004, bars))
    volume = rng.integers(100_000, 300_000, bars)
    return pd.DataFrame(
        {"Open": open_px, "High": high, "Low": low,
         "Close": close, "Volume": volume},
        index=pd.date_range("2024-01-01", periods=bars, freq="D"),
    )
