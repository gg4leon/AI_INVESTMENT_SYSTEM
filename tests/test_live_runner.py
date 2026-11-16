"""Nory public-only live runner lifecycle, all network mocked."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

from nory.kraken_public import QuoteStore
from nory.live_paper import dashboard
from nory.live_runner import LivePaperRunner


class FakeClient:
    def __init__(self,symbols):
        self.symbols=symbols
        self.store=QuoteStore()
        self.started=False
        self.stopped=False

    def start(self):
        self.started=True
        return True

    def stop(self):
        self.stopped=True

    def status(self):
        return {"state":"TEST_FAKE","error":None}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"paper.sqlite3"
        self.runners=[]

    def tearDown(self):
        for runner in self.runners:
            runner.stop()
        self.tmp.cleanup()

    def make(self):
        runner=LivePaperRunner(db_path=self.db,client_factory=FakeClient,
                               interval_seconds=.5)
        self.runners.append(runner)
        return runner

    def test_no_network_or_worker_until_explicit_start(self):
        runner=self.make()
        self.assertFalse(runner.status()["running"])
        self.assertEqual(runner.status()["status"],"IDLE")
        self.assertTrue(dashboard(self.db)["state"]["paused"])

    def test_start_stop_and_no_double_worker(self):
        runner=self.make()
        self.assertTrue(runner.start(("BTC-USD","ETH-USD")))
        self.assertFalse(runner.start(("BTC-USD","ETH-USD")))
        self.assertTrue(runner.status()["running"])
        self.assertTrue(runner._client.started)
        stop=runner.stop()
        self.assertFalse(stop["running"])
        self.assertTrue(dashboard(self.db)["state"]["paused"])
        self.assertTrue(runner._client.stopped)

    def test_reject_non_crypto_or_no_btc(self):
        runner=self.make()
        with self.assertRaises(ValueError):
            runner.start(("AAPL",))
        with self.assertRaises(ValueError):
            runner.start(("ETH-USD",))
        with self.assertRaises(ValueError):
            runner.start(())
        self.assertFalse(runner.status()["running"])

    def test_risk_halt_refuses_reconnect(self):
        runner=self.make()
        import sqlite3
        dashboard(self.db)
        con=sqlite3.connect(self.db)
        con.execute("UPDATE live_state SET halted=1 WHERE id=1")
        con.commit()
        con.close()
        with self.assertRaises(ValueError):
            runner.start(("BTC-USD",))
        self.assertFalse(runner.status()["running"])


if __name__=="__main__":
    unittest.main()
