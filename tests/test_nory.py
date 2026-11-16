"""Nory v0.7 tests: next-open timing, shared cash, concurrency and guards.

All tests use deterministic fabricated prices. Nothing touches Yahoo or brokers.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.markets import MARKET_BY_SYMBOL
from nory.book import (
    apply_cycle, get_dashboard, is_paused, next_demo_step, set_paused,
)
from nory.engine import (
    NoryPolicy, Observation, rank_candidates, risk_priority, source_is_fresh,
)
from nory.worker import run_once, scan_markets, validate_symbols


def frame(values):
    dates = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Open": [v[0] for v in values],
                         "Close": [v[1] for v in values]}, index=dates)


def sample(symbol, prices, signal="CANDIDATO_COMPRA", priority=70., weight=.14):
    data = frame(prices)
    category = MARKET_BY_SYMBOL[symbol].category
    obs = Observation(
        symbol=symbol, bar=data.index[-1].strftime("%Y-%m-%d"),
        open_price=float(data["Open"].iloc[-1]),
        close_price=float(data["Close"].iloc[-1]),
        signal=signal, volatility_20d=.009, category=category,
        priority=priority, target_weight=weight, reason="Fabricated test",
    )
    return obs, data


class NoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "nory.sqlite3"
        self.source = "SYNTHETIC_DEMO"

    def tearDown(self):
        self.temp.cleanup()

    def _cycle(self, batch, policy=None):
        return apply_cycle(
            batch, source=self.source, db_path=self.db, policy=policy,
        )

    def test_default_off_and_no_real_orders(self):
        self.assertTrue(is_paused(self.db))
        batch = {"SPY":sample("SPY",[(100,100),(100,100)])}
        r = self._cycle(batch)
        self.assertEqual(r["status"],"PAUSED")
        self.assertEqual(get_dashboard(self.db)["orders"],[])

    def test_signal_staged_then_executed_at_next_open(self):
        set_paused(False,self.db)
        first = self._cycle({
            "SPY":sample("SPY",[(100,100),(100,100)])
        })
        self.assertTrue(any(e["event"]=="BUY_PENDING" for e in first["events"]))
        self.assertEqual(first["cash"],10_000)
        self.assertEqual(get_dashboard(self.db)["positions"],[])
        later = self._cycle({
            "SPY":sample("SPY",[(100,100),(100,100),(110,111)],signal="ESPERAR")
        })
        self.assertEqual(later["open_positions"],1)
        fill = next(e for e in later["events"] if e["event"]=="BUY_SIM")
        self.assertGreater(fill["fill"],110)
        self.assertEqual(fill["execution"],"NEXT_OBSERVED_BAR_OPEN_HYPOTHETICAL")
        orders = get_dashboard(self.db)["orders"]
        self.assertEqual(orders[0]["fill_bar"],"2025-01-03")
        self.assertEqual(orders[0]["status"],"FILLED")
        self.assertLess(later["cash"],10000)

    def test_duplicate_scans_not_double_spend(self):
        set_paused(False,self.db)
        batch = {"SPY":sample("SPY",[(100,100),(100,100)])}
        self._cycle(batch)
        other = self._cycle(batch)
        self.assertEqual(len(get_dashboard(self.db)["orders"]),1)
        self.assertFalse(any(e["event"]=="BUY_SIM" for e in other["events"]))
        newer = {"SPY":sample("SPY",[(100,100),(100,100),(101,102)],"ESPERAR")}
        self._cycle(newer)
        after = get_dashboard(self.db)["portfolio"]["cash"]
        self._cycle(newer)
        self.assertEqual(get_dashboard(self.db)["portfolio"]["cash"],after)

    def test_multiple_markets_share_a_single_cash_balance(self):
        set_paused(False,self.db)
        batch0 = {
            "SPY":sample("SPY",[(100,100),(100,100)],priority=80),
            "AAPL":sample("AAPL",[(50,50),(50,50)],priority=60),
            "BTC-USD":sample("BTC-USD",[(100,100),(100,100)],priority=50,weight=.08),
        }
        first=self._cycle(batch0)
        self.assertEqual(first["cash"],10000)
        self.assertEqual(first["open_positions"],0)
        batch1 = {
            "SPY":sample("SPY",[(100,100),(100,100),(101,101)],"ESPERAR"),
            "AAPL":sample("AAPL",[(50,50),(50,50),(52,52)],"ESPERAR"),
            "BTC-USD":sample("BTC-USD",[(100,100),(100,100),(105,105)],"ESPERAR"),
        }
        second=self._cycle(batch1)
        self.assertEqual(second["open_positions"],3)
        self.assertEqual(len(get_dashboard(self.db)["positions"]),3)
        self.assertGreater(second["cash"],0)
        self.assertLessEqual(second["exposure_pct"],65.1)
        self.assertAlmostEqual(
            get_dashboard(self.db)["portfolio"]["cash"], second["cash"],places=2
        )
        self.assertEqual({p["source"] for p in get_dashboard(self.db)["positions"]},
                         {"SYNTHETIC_DEMO"})

    def test_size_uses_open_not_future_close_of_current_bar(self):
        set_paused(False,self.db)
        original = {"SPY":sample("SPY",[(100,100),(100,100)]),
                    "AAPL":sample("AAPL",[(100,100),(100,100)],priority=60.)}
        self._cycle(original)
        late={
            "SPY":sample("SPY",[(100,100),(100,100),(100,1000)],"ESPERAR"),
            "AAPL":sample("AAPL",[(100,100),(100,100),(100,100)],"ESPERAR"),
        }
        self._cycle(late)
        positions={x["symbol"]:x for x in get_dashboard(self.db)["positions"]}
        self.assertAlmostEqual(
            positions["AAPL"]["invested_basis"],1400,delta=1
        )  # No usar precio de cierre 1000 de SPY para dimensionar AAPL

    def test_next_bar_gap_expires_unfilled_order(self):
        set_paused(False,self.db)
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})
        future={"SPY":sample("SPY",[(100,100),(100,100),(90,90),(80,80)],
                             signal="ESPERAR")}
        r=self._cycle(future)
        self.assertEqual(r["open_positions"],0)
        self.assertTrue(any(e["event"]=="EXPIRED" for e in r["events"]))
        self.assertEqual(get_dashboard(self.db)["orders"][0]["status"],"EXPIRED")

    def test_next_open_sell_and_profit_in_shared_cash(self):
        set_paused(False,self.db)
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100),(100,105)],
                                 signal="CANDIDATO_VENTA")})
        self.assertEqual(get_dashboard(self.db)["orders"][0]["side"],"SELL")
        result=self._cycle({"SPY":sample(
            "SPY",[(100,100),(100,100),(100,105),(120,120)],
            signal="ESPERAR"
        )})
        self.assertEqual(result["open_positions"],0)
        sell=next(x for x in result["events"] if x["event"]=="SELL_SIM")
        self.assertGreater(sell["pnl"],0)
        self.assertGreater(result["cash"],10_000)

    def test_drawdown_kill_blocks_new_entries(self):
        set_paused(False,self.db)
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100),(100,100)],
                                 signal="ESPERAR")})
        # 14% invested: if asset declines to $1, the overall portfolio falls >12%.
        r=self._cycle({"SPY":sample(
            "SPY",[(100,100),(100,100),(100,100),(1,1)],
            signal="CANDIDATO_COMPRA"
        )})
        self.assertEqual(r["status"],"HALTED")
        self.assertTrue(get_dashboard(self.db)["portfolio"]["halted"])
        self.assertFalse(any(o["side"]=="BUY" and o["status"]=="PENDING"
                             for o in get_dashboard(self.db)["orders"]))

    def test_invalid_instruments_and_currency(self):
        for sym in ("EURUSD=X","GC=F","WALMEX.MX","^GSPC"):
            with self.subTest(sym=sym), self.assertRaises(ValueError):
                validate_symbols(["SPY",sym])
        with self.assertRaises(ValueError):
            validate_symbols(["BAD"])
        with self.assertRaises(ValueError):
            validate_symbols([])

    def test_priority_and_risk_sizing_heuristics(self):
        safer_score,safer_weight=risk_priority(.008,"CANDIDATO_COMPRA")
        volatile_score,volatile_weight=risk_priority(.07,"CANDIDATO_COMPRA")
        self.assertGreater(safer_score,volatile_score)
        self.assertGreater(safer_weight,volatile_weight)
        self.assertEqual(risk_priority(.02,"ESPERAR")[1],0)
        obs1,_=sample("AAPL",[(50,50),(50,50)],priority=42)
        obs2,_=sample("SPY",[(50,50),(50,50)],priority=91)
        self.assertEqual([o.symbol for o in rank_candidates([obs1,obs2])],
                         ["SPY","AAPL"])

    def test_demo_worker_progresses_one_bar_per_scan(self):
        set_paused(False,self.db)
        one=run_once(["SPY","AAPL"],demo=True,db_path=self.db,max_workers=2)
        two=run_once(["SPY","AAPL"],demo=True,db_path=self.db,max_workers=2)
        self.assertEqual(one["status"],"PROCESSED")
        self.assertEqual(two["status"],"PROCESSED")
        self.assertEqual(one["demo_step"],0)
        self.assertEqual(two["demo_step"],1)
        self.assertEqual(get_dashboard(self.db)["demo_step"],2)
        self.assertEqual(len(get_dashboard(self.db)["cycles"]),2)

    def test_scanner_results_sorted_even_with_parallel_workers(self):
        def loader(symbol,demo,step):
            return sample(symbol,[(100,100),(100,100)])
        batch,warnings=scan_markets(
            ["MSFT","AAPL","SPY"],demo=True,max_workers=3,loader=loader
        )
        self.assertEqual(list(batch),["AAPL","MSFT","SPY"])
        self.assertEqual(warnings,[])

    def test_synthetic_and_historical_accounts_separate(self):
        set_paused(False,self.db)
        self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})
        other=apply_cycle(
            {"SPY":sample("SPY",[(100,100),(100,100)])},
            "YAHOO_HISTORICAL",db_path=self.db
        )
        self.assertEqual(other["cash"],10000)
        self.assertEqual(get_dashboard(self.db)["portfolio"]["cash"],10000)
        self.assertEqual(get_dashboard(self.db,"YAHOO_HISTORICAL")["portfolio"]["cash"],10000)

    def test_stale_data_prevention(self):
        from datetime import timedelta
        now = datetime(2026,11,16,tzinfo=timezone.utc)
        self.assertTrue(source_is_fresh("2026-11-14","ETFs",now))
        self.assertFalse(source_is_fresh("2026-10-20","ETFs",now))
        self.assertFalse(source_is_fresh("2026-11-20","ETFs",now))
        self.assertFalse(source_is_fresh("2026-11-11","Criptomonedas",now))

    def test_control_and_json_are_serializable(self):
        set_paused(False,self.db)
        r=self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})
        json.dumps(r,allow_nan=False)
        json.dumps(get_dashboard(self.db),allow_nan=False)
        set_paused(True,self.db)
        self.assertEqual(self._cycle({"SPY":sample("SPY",[(100,100),(100,100)])})["status"],"PAUSED")


if __name__ == "__main__":
    unittest.main()
