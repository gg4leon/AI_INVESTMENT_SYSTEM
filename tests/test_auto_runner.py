"""MicroAutoRunner tests: singleton behavior, stop, failure, risk circuit.

All tests use disposable local SQLite and invented ticks. No web/broker.
"""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from threading import Lock

from nory.auto_runner import MicroAutoRunner
from nory.micro_lab import dashboard, is_paused, process_second, set_paused


def wait_until(fn, timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if fn():
            return True
        time.sleep(.02)
    return fn()


class AutoRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"autotest.sqlite3"
        self.runners=[]

    def tearDown(self):
        for runner in self.runners:
            runner.stop()
        self.tmp.cleanup()

    def new_runner(self, **kw):
        runner=MicroAutoRunner(db_path=self.db,**kw)
        self.runners.append(runner)
        return runner

    def test_construct_does_not_start_or_unpause(self):
        runner=self.new_runner()
        self.assertFalse(runner.status()["running"])
        self.assertEqual(runner.status()["status"],"IDLE")
        self.assertTrue(is_paused(self.db))
        self.assertEqual(dashboard(self.db)["state"]["tick"],-1)

    def test_start_auto_stop_and_no_duplicate_threads(self):
        runner=self.new_runner()
        self.assertTrue(runner.start(("SPY","AAPL"),interval_seconds=.2)["started"])
        self.assertFalse(runner.start(("SPY","AAPL"),interval_seconds=.2)["started"])
        self.assertTrue(wait_until(lambda:runner.status()["cycles_this_run"]>=2))
        self.assertFalse(is_paused(self.db))
        stopped=runner.stop()
        self.assertFalse(stopped["running"])
        self.assertTrue(is_paused(self.db))
        tick=dashboard(self.db)["state"]["tick"]
        time.sleep(.25)
        self.assertEqual(dashboard(self.db)["state"]["tick"],tick)

    def test_autostops_on_risk_signal(self):
        lock=Lock()
        count=[0]
        def mock_step(**kw):
            with lock:
                count[0]+=1
                return {"status":"PROCESSED" if count[0]<3 else "CIRCUIT_HALTED",
                        "tick":count[0]}
        runner=self.new_runner(processor=mock_step)
        runner.start(("SPY",),interval_seconds=.2)
        self.assertTrue(wait_until(lambda:runner.status()["status"]=="CIRCUIT_HALTED"))
        self.assertTrue(wait_until(lambda:not runner.status()["running"]))
        self.assertEqual(runner.status()["cycles_this_run"],2)
        self.assertEqual(count[0],3)
        self.assertTrue(is_paused(self.db))

    def test_autostops_and_reports_unexpected_exception(self):
        def bad(**kwargs):
            raise RuntimeError("synthetic failure")
        runner=self.new_runner(processor=bad)
        runner.start(("SPY",),interval_seconds=.2)
        self.assertTrue(wait_until(lambda:runner.status()["status"]=="ERROR"))
        self.assertTrue(wait_until(lambda:not runner.status()["running"]))
        self.assertIn("synthetic failure",runner.status()["last_error"])
        self.assertTrue(is_paused(self.db))

    def test_refuses_incompatible_stored_scenario(self):
        set_paused(False,self.db)
        process_second(symbols=("SPY","AAPL"),scenario="mixed",db_path=self.db)
        set_paused(True,self.db)
        runner=self.new_runner()
        with self.assertRaisesRegex(ValueError,"fixed scenario"):
            runner.start(("SPY","AAPL"),scenario="shock")
        with self.assertRaisesRegex(ValueError,"fixed universe"):
            runner.start(("SPY","MSFT"),scenario="mixed")
        self.assertTrue(is_paused(self.db))
        self.assertFalse(runner.status()["running"])

    def test_refuses_halted_portfolio_without_reset(self):
        dashboard(self.db)
        con=sqlite3.connect(self.db)
        con.execute("UPDATE micro_state SET halted=1 WHERE id=1")
        con.commit()
        con.close()
        runner=self.new_runner()
        with self.assertRaisesRegex(ValueError,"Risk circuit"):
            runner.start(("SPY",))
        self.assertTrue(is_paused(self.db))

    def test_bad_symbols_and_interval(self):
        runner=self.new_runner()
        with self.assertRaises(ValueError):
            runner.start(("AAPL",))
        with self.assertRaises(ValueError):
            runner.start(("SPY",),interval_seconds=0)
        with self.assertRaises(ValueError):
            runner.start(("SPY",),scenario="fake")
        self.assertTrue(is_paused(self.db))


if __name__=="__main__":
    unittest.main()
