"""Integracion sin internet; prueba CLI, reportes y separacion demo."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data.demo_data import make_demo_data
from main import analyze_market


class IntegrationTests(unittest.TestCase):
    def test_reports_written_to_temporary_directory(self):
        df = make_demo_data("SPY", 120)
        with tempfile.TemporaryDirectory() as directory:
            with (patch("main.OUTPUT", Path(directory)),
                  patch("main.get_market_data", return_value=df)):
                ok = analyze_market("SPY", "Demo", "all", "2y", False)
            self.assertTrue(ok)
            report = Path(directory, "SPY_report.json")
            summary = Path(directory, "SPY_backtest_summary.json")
            curve = Path(directory, "SPY_backtest_equity.csv")
            self.assertTrue(report.exists())
            self.assertTrue(summary.exists())
            self.assertTrue(curve.exists())
            parsed = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(parsed["mode"], "HISTORICAL_PAPER_ONLY")
            self.assertTrue(parsed["final_equity"] > 0)


if __name__ == "__main__":
    unittest.main()
