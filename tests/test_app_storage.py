"""SQLite local, persistencia y no inyección SQL."""
import tempfile
import unittest
from pathlib import Path

from app.service import run_analysis
from app.storage import get_run, list_runs, save_run


class StorageTests(unittest.TestCase):
    def test_store_and_retrieve_backtest(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "private.sqlite3"
            snapshot = run_analysis("SPY", source="demo")
            run_id = save_run(snapshot, db_path)
            self.assertTrue(db_path.is_file())
            runs = list_runs(db_path=db_path)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["id"], run_id)
            record = get_run(run_id, db_path)
            self.assertEqual(record["backtest"]["mode"], "HISTORICAL_PAPER_ONLY")
            self.assertEqual(record["source"], "SYNTHETIC_DEMO")
            self.assertEqual(record["price_history"], snapshot["price_history"])
            self.assertIsNone(get_run("unknown", db_path))

    def test_multiple_runs_and_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.sqlite3"
            snapshot = run_analysis("BTC-USD")
            ids = [save_run(snapshot, path) for _ in range(3)]
            self.assertEqual(len(list_runs(db_path=path)), 3)
            self.assertEqual(len(list_runs(limit=2, db_path=path)), 2)
            self.assertEqual(len(set(ids)), 3)
            with self.assertRaises(ValueError):
                list_runs(limit=0, db_path=path)

    def test_invalid_document_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                save_run({"wrong": True}, Path(folder) / "x.sqlite3")


if __name__ == "__main__":
    unittest.main()
