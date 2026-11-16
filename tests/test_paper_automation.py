"""Pruebas sin dinero ni datos de mercado externos para el motor ficticio."""
import tempfile
import unittest
from pathlib import Path

from automation.paper import (
    PaperPolicy, get_accounts, get_events, is_paused, process_bar, set_paused
)
from app.markets import CATALOG, MARKET_BY_SYMBOL, PAPER_SYMBOLS


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "paper.sqlite3"
        self.kw = dict(db_path=self.db, source="SYNTHETIC_DEMO", symbol="SPY")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_paused(self):
        self.assertTrue(is_paused(self.db))
        result = process_bar(bar="2026-01-01", close_price=100, signal="CANDIDATO_COMPRA", **self.kw)
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(len(get_accounts(self.db)), 0)

    def test_buy_sell_balance_and_ledger(self):
        set_paused(False, self.db)
        first = process_bar(
            bar="2026-01-01", close_price=100, signal="CANDIDATO_COMPRA", **self.kw
        )
        self.assertEqual(first["action"], "BUY_SIM")
        self.assertAlmostEqual(first["cash"], 9000, places=5)
        self.assertGreater(first["quantity"], 0)
        second = process_bar(
            bar="2026-01-02", close_price=110, signal="CANDIDATO_VENTA", **self.kw
        )
        self.assertEqual(second["action"], "SELL_SIM")
        self.assertEqual(second["quantity"], 0)
        self.assertGreater(second["realized_pnl"], 0)
        self.assertGreater(second["cash"], 10000)
        events = get_events(self.db)
        self.assertEqual(len(events), 2)

    def test_duplicate_or_old_bar_does_not_double_buy(self):
        set_paused(False, self.db)
        one = process_bar(
            bar="2026-01-01", close_price=100, signal="CANDIDATO_COMPRA", **self.kw
        )
        dup = process_bar(
            bar="2026-01-01", close_price=200, signal="CANDIDATO_COMPRA", **self.kw
        )
        older = process_bar(
            bar="2025-12-30", close_price=90, signal="CANDIDATO_VENTA", **self.kw
        )
        self.assertEqual(dup["status"], "DUPLICATE_OR_OLD")
        self.assertEqual(older["status"], "DUPLICATE_OR_OLD")
        self.assertEqual(len(get_events(self.db)), 1)
        self.assertEqual(get_accounts(self.db)[0]["cash"], one["cash"])

    def test_paused_again_prevents_new_processing(self):
        set_paused(False, self.db)
        process_bar(bar="2026-01-01", close_price=100, signal="ESPERAR", **self.kw)
        set_paused(True, self.db)
        other = process_bar(bar="2026-01-02", close_price=101, signal="CANDIDATO_COMPRA", **self.kw)
        self.assertEqual(other["status"], "PAUSED")
        self.assertEqual(len(get_events(self.db)), 1)

    def test_stop_loss_is_fictitious(self):
        set_paused(False, self.db)
        process_bar(bar="2026-01-01", close_price=100, signal="CANDIDATO_COMPRA", **self.kw)
        result = process_bar(bar="2026-01-02", close_price=80, signal="ESPERAR", **self.kw)
        self.assertEqual(result["action"], "SELL_SIM_STOP")
        self.assertLess(result["realized_pnl"], 0)
        self.assertEqual(result["execution_type"], "HYPOTHETICAL_CLOSE_PROXY_NOT_LIVE")

    def test_forex_indexes_and_futures_not_eligible(self):
        set_paused(False, self.db)
        for symbol in ("EURUSD=X", "^GSPC", "GC=F"):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                process_bar(
                    source="SYNTHETIC_DEMO", symbol=symbol,
                    bar="2026-01-01", close_price=10,
                    signal="CANDIDATO_COMPRA", db_path=self.db,
                )
        self.assertEqual(len(get_events(self.db)), 0)

    def test_invalid_prices_and_signals(self):
        set_paused(False, self.db)
        for price in (float("nan"), float("inf"), -1, 0):
            with self.assertRaises(ValueError):
                process_bar(bar="2026-01-01", close_price=price, signal="ESPERAR", **self.kw)
        with self.assertRaises(ValueError):
            process_bar(bar="2026-01-01", close_price=99, signal="BUY", **self.kw)

    def test_quote_currencies_not_conflated(self):
        set_paused(False, self.db)
        process_bar(bar="2026-01-01", close_price=100, signal="CANDIDATO_COMPRA", **self.kw)
        process_bar(source="SYNTHETIC_DEMO", symbol="WALMEX.MX",
                    bar="2026-01-01", close_price=50,
                    signal="CANDIDATO_COMPRA", db_path=self.db)
        currencies = {row["symbol"]: row["currency"] for row in get_accounts(self.db)}
        self.assertEqual(currencies["SPY"], "USD")
        self.assertEqual(currencies["WALMEX.MX"], "MXN")

    def test_catalog_has_many_markets(self):
        self.assertGreaterEqual(len(CATALOG), 40)
        self.assertTrue(MARKET_BY_SYMBOL["AAPL"].paper_eligible)
        self.assertNotIn("^DJI", PAPER_SYMBOLS)

    def test_bad_policy(self):
        with self.assertRaises(ValueError):
            PaperPolicy(allocation_fraction=1.2)
        with self.assertRaises(ValueError):
            PaperPolicy(fee_bps=-1)


if __name__ == "__main__":
    unittest.main()
