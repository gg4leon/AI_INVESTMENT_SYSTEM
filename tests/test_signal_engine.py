"""Pruebas sin red ni dependencia de Yahoo Finance."""
import unittest
import numpy as np
import pandas as pd

from analysis.signal_engine import SignalConfig, generate_signal
from analysis.risk_engine import assess_risk


def frame(n=50, direction="up"):
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    base = np.linspace(100, 120 if direction == "up" else 80, n)
    df = pd.DataFrame({"Close": base, "SMA_10": base - 1,
                       "SMA_30": base - 2, "RSI_14": 55.0,
                       "MACD": 2.0, "MACD_SIGNAL": 1.0,
                       "MACD_HIST": 1.0}, index=index)
    if direction == "down":
        df["SMA_10"] = base - 2
        df["SMA_30"] = base - 1
        df["RSI_14"] = 40.0
        df["MACD"] = -2.0
        df["MACD_SIGNAL"] = -1.0
        df["MACD_HIST"] = -1.0
    return df


class SignalEngineTests(unittest.TestCase):
    def test_bullish(self):
        result = generate_signal(frame(), "SPY")
        self.assertEqual(result.signal, "CANDIDATO_COMPRA")
        self.assertEqual(result.agreement, 3)
        self.assertTrue(result.valid)

    def test_bearish(self):
        self.assertEqual(generate_signal(frame(direction="down"), "SPY").signal,
                         "CANDIDATO_VENTA")

    def test_mixed_wait(self):
        df = frame()
        df.loc[df.index[-1], "MACD_HIST"] = -1.0
        self.assertEqual(generate_signal(df, "SPY").signal, "ESPERAR")

    def test_insufficient_history(self):
        self.assertFalse(generate_signal(frame(20), "SPY").valid)

    def test_nan_latest_cannot_trade(self):
        df = frame()
        df.loc[df.index[-1], "RSI_14"] = np.nan
        self.assertEqual(generate_signal(df, "SPY").signal, "SIN_SENAL")

    def test_unsorted_index(self):
        self.assertFalse(generate_signal(frame().iloc[::-1], "SPY").valid)

    def test_ignores_future_bars(self):
        df = frame()
        at_t = generate_signal(df.iloc[:40], "SPY")
        changed_future = df.copy()
        changed_future.loc[changed_future.index[40]:, "RSI_14"] = 99
        self.assertEqual(at_t, generate_signal(changed_future.iloc[:40], "SPY"))

    def test_config_rejects_invalid_ranges(self):
        with self.assertRaises(ValueError):
            SignalConfig(bullish_rsi_min=90, bullish_rsi_max=60)

    def test_risk_constant_series(self):
        df = pd.DataFrame({"Close": [100.0] * 40})
        risk = assess_risk(df, "SPY")
        self.assertEqual(risk.volatility_20d_pct, 0.0)
        self.assertEqual(risk.max_drawdown_pct, 0.0)

    def test_risk_short_series(self):
        df = pd.DataFrame({"Close": [100.0] * 10})
        self.assertEqual(assess_risk(df, "SPY").risk_level, "SIN_DATOS")


if __name__ == "__main__":
    unittest.main()
