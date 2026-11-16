"""AIS dashboard service: tests sin red ni bróker."""
import unittest
from unittest.mock import patch

from app.service import run_analysis, MARKETS
from backtesting.engine import BacktestConfig


class ServiceTests(unittest.TestCase):
    def test_all_supported_demo_symbols(self):
        for symbol in MARKETS:
            with self.subTest(symbol=symbol):
                result = run_analysis(symbol, source="demo")
                self.assertEqual(result["source"], "SYNTHETIC_DEMO")
                self.assertEqual(result["symbol"], symbol)
                self.assertEqual(result["schema_version"], 1)
                self.assertEqual(result["backtest"]["mode"], "HISTORICAL_PAPER_ONLY")
                self.assertGreater(len(result["price_history"]), 0)
                self.assertGreater(len(result["equity_curve"]), 100)

    def test_real_data_failure_cannot_turn_into_demo(self):
        with patch("app.service.get_market_data", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "No se sustituyen"):
                run_analysis("SPY", source="historical")
        with patch("app.service.get_market_data", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                run_analysis("SPY", source="historical")

    def test_invalid_symbol_and_source(self):
        with self.assertRaises(ValueError):
            run_analysis("FAKE", source="demo")
        with self.assertRaises(ValueError):
            run_analysis("SPY", source="invalid")
        with self.assertRaises(ValueError):
            run_analysis("SPY", period="100y")

    def test_config_changes_simulation(self):
        low_cost = run_analysis(
            "SPY", config=BacktestConfig(fee_bps=0, slippage_bps=0)
        )
        costly = run_analysis(
            "SPY", config=BacktestConfig(fee_bps=30, slippage_bps=30)
        )
        self.assertGreaterEqual(
            low_cost["backtest"]["final_equity"],
            costly["backtest"]["final_equity"],
        )


if __name__ == "__main__":
    unittest.main()
