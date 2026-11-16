"""Nory MicroLab offline tests. No online feeds and no actual investments."""
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nory.micro_feed import (
    SCENARIOS, SyntheticTick, initial_price, synthesize_tick,
)
from nory.micro_lab import (
    DEFAULT_SYMBOLS, MicroPolicy, _costs, _liquidation_value,
    dashboard, is_paused, process_second, risk_assessment, set_paused,
)
from nory.micro_worker import run_steps


class MicroLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "micro.sqlite3"
        self.symbols = ("SPY", "QQQ", "AAPL", "NVDA", "BTC-USD")

    def tearDown(self):
        self.temp.cleanup()

    def cycle(self, scenario="mixed", policy=None):
        return process_second(
            symbols=self.symbols,scenario=scenario,db_path=self.db,policy=policy
        )

    def test_default_paused_and_no_money_or_real_orders(self):
        self.assertTrue(is_paused(self.db))
        value=self.cycle()
        self.assertEqual(value["status"],"PAUSED")
        snap=dashboard(self.db)
        self.assertEqual(snap["state"]["tick"],-1)
        self.assertEqual(snap["trades"],[])
        self.assertEqual(snap["positions"],[])

    def test_synthetic_second_reproducible_and_labeled(self):
        p=synthesize_tick(10, self.symbols, {}, "mixed")
        q=synthesize_tick(10, tuple(reversed(self.symbols)), {}, "mixed")
        self.assertEqual(p.prices,q.prices)
        self.assertEqual(p.virtual_time,q.virtual_time)
        self.assertEqual(p.events,q.events)
        self.assertIn("2026-01-01",p.virtual_time)
        self.assertNotEqual(initial_price("AAPL"),initial_price("NVDA"))

    def test_scenario_unexplained_company_drop(self):
        x=synthesize_tick(95, self.symbols,{},"shock")
        self.assertIn("UNKNOWN_CAUSE",x.events["NVDA"])
        self.assertEqual(x.events["AAPL"],"NO_CONFIRMED_NEWS_CONTEXT")

    def test_risk_filter_unknown_event_never_auto_buys(self):
        cfg=MicroPolicy()
        prices=[100+0.01*k for k in range(50)]
        result=risk_assessment(
            "NVDA",92.,prices,0.,"FABRICATED_SINGLE_STOCK_SHOCK_UNKNOWN_CAUSE",
            cfg,False,
        )
        self.assertEqual(result[0],"BLOCK_UNKNOWN_EVENT")

    def test_market_stress_and_falling_knife_blocked(self):
        cfg=MicroPolicy()
        old=[100+math.sin(i/5) for i in range(50)]
        shock=risk_assessment("SPY",98,old,0.,"NO_CONFIRMED_NEWS_CONTEXT",cfg,False)
        self.assertIn(shock[0],("BLOCK_SHOCK","WAIT_FALLING","BLOCK_VOLATILITY"))
        context=risk_assessment(
            "AAPL",99.,old,-0.01,"NO_CONFIRMED_NEWS_CONTEXT",cfg,False
        )
        self.assertEqual(context[0],"BLOCK_MARKET_STRESS")

    def test_bps_costs_require_real_net_gain(self):
        cfg=MicroPolicy()
        buy=_costs(cfg,100.,"BUY")
        sell=_costs(cfg,100.,"SELL")
        out=_liquidation_value(cfg,100.,1)
        self.assertGreater(buy,100.)
        self.assertLess(sell,100.)
        self.assertLess(out,buy)
        self.assertGreater(cfg.profit_target_net_bps,0)

    def test_demo_quick_cycles_persist_and_have_shared_cash(self):
        set_paused(False,self.db)
        last=run_steps(self.symbols,steps=80,interval_seconds=0,db_path=self.db)
        self.assertEqual(last["tick"],79)
        snap=dashboard(self.db)
        self.assertEqual(snap["state"]["tick"],79)
        self.assertEqual(len(snap["equity"]),80)
        self.assertEqual(snap["source"],"SYNTHETIC_SECOND_FEED_ONLY")
        self.assertGreater(snap["state"]["equity"],0)
        self.assertLessEqual(len(snap["positions"]),MicroPolicy().max_positions)
        self.assertGreaterEqual(snap["state"]["cash"],-0.0001)
        self.assertEqual(snap["state"]["universe_json"],json.dumps(sorted(self.symbols)))
        json.dumps(snap,allow_nan=False)

    def test_universe_and_scenario_frozen(self):
        set_paused(False,self.db)
        self.cycle()
        with self.assertRaisesRegex(ValueError,"fixed universe"):
            process_second(
                symbols=("SPY","QQQ"),scenario="mixed",db_path=self.db
            )
        with self.assertRaisesRegex(ValueError,"fixed universe"):
            self.cycle("shock")
        self.assertEqual(dashboard(self.db)["state"]["tick"],0)

    def test_pending_fills_never_on_decision_tick(self):
        set_paused(False,self.db)
        run_steps(self.symbols,steps=190,interval_seconds=0,db_path=self.db)
        snap=dashboard(self.db)
        self.assertTrue(all(tr["reason"] for tr in snap["trades"]))
        con=sqlite3.connect(self.db)
        orders=con.execute(
            "SELECT tick,symbol,side FROM micro_trades ORDER BY id"
        ).fetchall()
        for tick,symbol,side in orders:
            self.assertGreater(tick,0)
            if side=="BUY":
                pred=con.execute(
                    "SELECT tick FROM micro_decisions WHERE symbol=? AND "
                    "decision='BUY_CANDIDATE' AND tick<? ORDER BY tick DESC LIMIT 1",
                    (symbol,tick),
                ).fetchone()
                self.assertIsNotNone(pred)
                self.assertLess(pred[0],tick)
        con.close()

    def test_limit_exposure_even_across_symbols(self):
        set_paused(False,self.db)
        run_steps(self.symbols,steps=140,interval_seconds=0,db_path=self.db)
        snap=dashboard(self.db,history_limit=500)
        self.assertTrue(all(
            row["exposure_pct"]<=61 for row in snap["equity"]
        ))
        self.assertTrue(all(x["qty"]>0 for x in snap["positions"]))

    def test_large_unexplained_shock_never_silent(self):
        set_paused(False,self.db)
        run_steps(self.symbols,scenario="shock",steps=100,
                  interval_seconds=0,db_path=self.db)
        con=sqlite3.connect(self.db)
        row=con.execute(
            "SELECT decision,reason FROM micro_decisions WHERE tick=95 AND symbol='NVDA'"
        ).fetchone()
        con.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0],"BLOCK_UNKNOWN_EVENT")
        self.assertIn("FABRICATED",row[1])

    def test_pausing_stops_cycles_without_mutation(self):
        set_paused(False,self.db)
        self.cycle()
        set_paused(True,self.db)
        result=run_steps(self.symbols,steps=10,db_path=self.db)
        self.assertEqual(result["status"],"PAUSED")
        self.assertEqual(dashboard(self.db)["state"]["tick"],0)

    def test_small_risk_budget_and_invalid_configuration(self):
        with self.assertRaises(ValueError):
            MicroPolicy(initial_cash=-1)
        with self.assertRaises(ValueError):
            MicroPolicy(max_total_exposure=.05,max_asset_weight=.12)
        with self.assertRaises(ValueError):
            MicroPolicy(fee_bps=-3)
        with self.assertRaises(ValueError):
            MicroPolicy(z_buy_threshold=0)
        with self.assertRaises(ValueError):
            process_second(symbols=("AAPL",),db_path=self.db)
        with self.assertRaises(ValueError):
            process_second(symbols=("SPY",),scenario="fake",db_path=self.db)

    def test_scenarios_never_require_web(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                val=synthesize_tick(30,("SPY","MSFT"),{},scenario)
                self.assertEqual(len(val.prices),2)
                self.assertGreater(min(val.prices.values()),0)


if __name__=="__main__":
    unittest.main()
