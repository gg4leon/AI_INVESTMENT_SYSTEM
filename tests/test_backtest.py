"""Pruebas de ejecucion al siguiente open, costos, riesgo y sin ventas cortas."""
import unittest
import numpy as np
import pandas as pd

from backtesting.engine import BacktestConfig, run_backtest
from data.demo_data import make_demo_data
from analysis.indicators import add_indicators


def synthetic(bars=90, exit_at=None):
    dates = pd.date_range("2025-01-01", periods=bars, freq="D")
    df = pd.DataFrame({
        "Open": 100.0, "Close": 100.0,
        "SMA_10": 102.0, "SMA_30": 100.0,
        "RSI_14": 55.0, "MACD": 2.0,
        "MACD_SIGNAL": 1.0, "MACD_HIST": 1.0,
    }, index=dates)
    if exit_at is not None:
        where = df.index[exit_at:]
        df.loc[where, "SMA_10"] = 98.0
        df.loc[where, "RSI_14"] = 40.0
        df.loc[where, "MACD"] = -2.0
        df.loc[where, "MACD_SIGNAL"] = -1.0
        df.loc[where, "MACD_HIST"] = -1.0
    return df


class BacktesterTests(unittest.TestCase):
    def setUp(self):
        self.cfg = BacktestConfig(warmup_bars=40, stop_loss_pct=0.08)

    def test_buy_is_at_next_open_not_signal_close(self):
        df = synthetic()
        df.iloc[40, df.columns.get_loc("Open")] = 110.0
        res = run_backtest(df, "SPY", self.cfg)
        row = res.equity_curve.iloc[1]
        self.assertEqual(row["action"], "ENTER_LONG")
        self.assertGreater(row["qty"], 0)
        self.assertLess(row["cash"], 10000)

    def test_exit_uses_next_open_after_sell_signal(self):
        df = synthetic(exit_at=55)
        result = run_backtest(df, "SPY", self.cfg)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades.iloc[0]["exit_decision"], str(df.index[55]))
        self.assertEqual(result.trades.iloc[0]["exit_time"], str(df.index[56]))
        self.assertFalse(result.open_position)

    def test_fees_slippage_reduce_returns(self):
        df = synthetic(exit_at=55)
        costly = run_backtest(df, "SPY", self.cfg)
        free = run_backtest(df, "SPY", BacktestConfig(
            warmup_bars=40, fee_bps=0, slippage_bps=0))
        self.assertLess(costly.final_equity, free.final_equity)
        self.assertAlmostEqual(free.final_equity, 10000.0, places=6)

    def test_no_future_indicator_peeking(self):
        df = synthetic()
        # La primera decision es en t=39. Cambio indicador en t=40
        # sin modificar ningun dato anterior: la orden de t=40 no cambia.
        original = run_backtest(df, "SPY", self.cfg)
        altered = df.copy()
        altered.iloc[40, altered.columns.get_loc("RSI_14")] = 99.0
        updated = run_backtest(altered, "SPY", self.cfg)
        self.assertEqual(original.equity_curve.iloc[1]["action"],
                         updated.equity_curve.iloc[1]["action"])
        self.assertEqual(original.equity_curve.iloc[1]["qty"],
                         updated.equity_curve.iloc[1]["qty"])

    def test_down_signal_does_not_sell_short(self):
        df = synthetic()
        df["SMA_10"], df["SMA_30"] = 98.0, 100.0
        df["RSI_14"] = 40.0
        df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = -2.0, -1.0, -1.0
        res = run_backtest(df, "SPY", self.cfg)
        self.assertEqual(res.closed_trades, 0)
        self.assertFalse(res.open_position)
        self.assertAlmostEqual(res.final_equity, self.cfg.initial_cash)

    def test_spend_limited_to_allocated_cash(self):
        res = run_backtest(synthetic(), "SPY", self.cfg)
        after_entry = res.equity_curve.iloc[1]
        self.assertAlmostEqual(after_entry["cash"], 7500.0, places=6)

    def test_invalid_and_missing_prices_rejected(self):
        df = synthetic()
        df.loc[df.index[42], "Open"] = np.nan
        with self.assertRaises(ValueError):
            run_backtest(df, "SPY", self.cfg)
        df = synthetic().drop(columns=["Open"])
        with self.assertRaises(ValueError):
            run_backtest(df, "SPY", self.cfg)

    def test_unsorted_index_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest(synthetic().iloc[::-1], "SPY", self.cfg)

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(initial_cash=-1)
        with self.assertRaises(ValueError):
            BacktestConfig(allocation_fraction=1.5)
        with self.assertRaises(ValueError):
            BacktestConfig(fee_bps=-0.1)

    def test_summary_serializable_and_numeric(self):
        import json
        result = run_backtest(synthetic(exit_at=55), "SPY", self.cfg)
        json.dumps(result.summary(), allow_nan=False)
        self.assertLess(result.max_drawdown_pct, 0)
        self.assertGreater(result.exposure_pct, 0)

    def test_demo_data_end_to_end_offline(self):
        bars = make_demo_data("BTC-USD", 120)
        analyzed = add_indicators(bars)
        result = run_backtest(analyzed, "BTC-USD", self.cfg)
        self.assertEqual(len(result.equity_curve), 81)
        self.assertGreater(result.final_equity, 0)


if __name__ == "__main__":
    unittest.main()
