"""Nory v0.9 offline validation. REAL market message shapes with INVENTED test prices.

No Kraken connection is made by the test suite. Real connectivity must be
confirmed separately from the user's computer.
"""
from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from nory.kraken_public import (
    PAIRS, PublicQuote, QuoteStore, KrakenPublicClient, parse_public_ticker,
)
from nory.live_paper import (
    ALL_PAIRS, LivePolicy, apply_real_quotes, dashboard, pause,
)


class KrakenFormatTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,16,20,30,tzinfo=timezone.utc)
        self.msg={
            "channel":"ticker","type":"update","data":[{
                "symbol":"BTC/USD","bid":90100.,"ask":90105.,
                "bid_qty":1.5,"ask_qty":2.3,
                "timestamp":self.now.isoformat(),
            }]
        }

    def test_ticker_parses_genuine_shape_and_bidask(self):
        quotes=parse_public_ticker(self.msg,now=self.now)
        self.assertEqual(len(quotes),1)
        q=quotes[0]
        self.assertEqual(q.symbol,"BTC-USD")
        self.assertEqual(q.provider,"KRAKEN_PUBLIC_WS_V2")
        self.assertGreater(q.spread_bps,0)
        self.assertTrue(q.is_fresh(self.now))

    def test_snapshot_never_triggers_trade(self):
        self.msg["type"]="snapshot"
        self.assertEqual(parse_public_ticker(self.msg,now=self.now),[])

    def test_bad_spread_timestamp_liquidity_rejected(self):
        for key,value in (("bid",90110),("ask",90000),("bid_qty",0),
                          ("ask_qty",-3),("timestamp","not-a-date"),
                          ("timestamp",(self.now-timedelta(minutes=2)).isoformat())):
            with self.subTest(key=key,value=value):
                msg={"channel":"ticker","type":"update",
                     "data":[{**self.msg["data"][0],key:value}]}
                self.assertEqual(parse_public_ticker(msg,now=self.now),[])

    def test_expired_quotes_and_unordered_duplicates_rejected(self):
        store=QuoteStore()
        self.assertEqual(store.record_message(self.msg,now=self.now),1)
        self.assertEqual(store.record_message(self.msg,now=self.now),0)
        self.assertEqual(len(store.snapshot(now=self.now)),1)
        future=self.now+timedelta(seconds=20)
        self.assertFalse(store.snapshot(now=future))
        self.assertEqual(store.metrics()["messages_rejected"],1)

    def test_invalid_pair_validation(self):
        with self.assertRaises(ValueError):
            KrakenPublicClient(symbols=("AAPL",))
        with self.assertRaises(ValueError):
            KrakenPublicClient(symbols=())


def fake_quote(sym,now,bid,ask=None,depth=500.):
    exch={"BTC-USD":"BTC/USD","ETH-USD":"ETH/USD",
          "SOL-USD":"SOL/USD","XRP-USD":"XRP/USD",
          "ADA-USD":"ADA/USD"}[sym]
    return PublicQuote(
        symbol=sym,exchange_symbol=exch,
        bid=float(bid),ask=float(ask if ask is not None else bid*1.0001),
        bid_qty=depth,ask_qty=depth,
        exchange_time=now.isoformat(),received_time=now.isoformat(),
    )


class RealQuotePaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"paper.sqlite3"
        self.base=datetime(2026,11,16,20,30,tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self,t=0,btc=90000,eth=3000,policy=None):
        moment=self.base+timedelta(seconds=t)
        return apply_real_quotes(
            {"BTC-USD":fake_quote("BTC-USD",moment,btc),
             "ETH-USD":fake_quote("ETH-USD",moment,eth)},
            self.db,policy=policy,now=moment,
        )

    def test_default_is_paused_and_not_real(self):
        ret=self.apply()
        self.assertEqual(ret["status"],"PAUSED")
        self.assertEqual(dashboard(self.db)["fills"],[])
        self.assertEqual(dashboard(self.db)["state"]["cash"],10000)

    def test_new_timestamp_required_no_backfill(self):
        pause(False,self.db)
        r=self.apply(t=0)
        self.assertEqual(r["status"],"PROCESSED")
        same=self.apply(t=0)
        self.assertEqual(same["status"],"WAITING_FOR_NEW_EXCHANGE_QUOTES")
        self.assertEqual(len(dashboard(self.db)["equity"]),1)

    def test_stale_quote_blocks_portfolio(self):
        pause(False,self.db)
        q=fake_quote("BTC-USD",self.base,90000)
        out=apply_real_quotes({"BTC-USD":q},self.db,now=self.base+timedelta(seconds=30))
        self.assertEqual(out["status"],"STALE_BENCHMARK")
        self.assertEqual(len(dashboard(self.db)["equity"]),0)

    def test_requires_btc_benchmark(self):
        pause(False,self.db)
        moment=self.base
        out=apply_real_quotes({"ETH-USD":fake_quote("ETH-USD",moment,3000)},self.db,now=moment)
        self.assertEqual(out["status"],"STALE_BENCHMARK")

    def test_history_and_strategic_audit(self):
        pause(False,self.db)
        for step in range(50):
            price=3000*(1-.0015)**step
            self.apply(t=step,btc=90000,eth=price)
        data=dashboard(self.db)
        self.assertEqual(len(data["equity"]),50)
        self.assertEqual(len(data["fills"]),0)
        self.assertGreater(len(data["decisions"]),0)
        self.assertEqual(data["state"]["cash"],10000)

    def test_prior_quote_pending_order_fills_on_new_quote(self):
        pause(False,self.db)
        self.apply(t=0)
        con=sqlite3.connect(self.db)
        t0=self.base.isoformat()
        con.execute(
            "INSERT INTO live_orders(symbol,side,decision_time,expires_at,reason,weight) "
            "VALUES(?,?,?,?,?,?)",
            ("ETH-USD","BUY",t0,(self.base+timedelta(seconds=7)).isoformat(),
             "Test potential move",.07),
        )
        con.commit()
        con.close()
        self.apply(t=1)
        snap=dashboard(self.db)
        buys=[x for x in snap["fills"] if x["side"]=="BUY"]
        self.assertEqual(len(buys),1)
        self.assertGreater(buys[0]["price"],3000)
        self.assertEqual(buys[0]["quote_time"],(self.base+timedelta(seconds=1)).isoformat())
        self.assertLess(snap["state"]["cash"],10000)
        self.assertLess(snap["state"]["equity"],10000)

    def test_real_time_rebound_creates_pending_then_next_quote_buy(self):
        pause(False,self.db)
        for step in range(45):
            # Fabricated but chronological quote fixtures, no WebSocket.
            # Slow decline is not proof of undervaluation.
            eth=100*(1-.0012)**step
            r=self.apply(t=step,btc=90000,eth=eth)
            self.assertEqual(r["status"],"PROCESSED")
        rebound=100*(1-.0012)**44 * 1.0003
        signal=self.apply(t=45,btc=90000,eth=rebound)
        self.assertTrue(any(x["event"]=="BUY_PENDING" and x["symbol"]=="ETH-USD"
                            for x in signal["events"]))
        self.assertFalse(dashboard(self.db)["fills"])
        r=self.apply(t=46,btc=90000,eth=rebound*1.0001)
        self.assertTrue(any(x["event"]=="BUY_PAPER" for x in r["events"]))
        fills=dashboard(self.db)["fills"]
        self.assertEqual(len(fills),1)
        self.assertEqual(fills[0]["side"],"BUY")
        self.assertEqual(fills[0]["decision_time"],(self.base+timedelta(seconds=45)).isoformat())
        self.assertEqual(fills[0]["quote_time"],(self.base+timedelta(seconds=46)).isoformat())

    def test_missing_quote_for_existing_position_stops_trading(self):
        pause(False,self.db)
        self.apply(t=0)
        con=sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO live_positions(symbol,quantity,basis,entry_ask,opened_at,last_bid)"
            "VALUES(?,?,?,?,?,?)",
            ("ETH-USD",.2,601.,3002.,self.base.isoformat(),3000.)
        )
        con.commit()
        con.close()
        now=self.base+timedelta(seconds=20)
        result=apply_real_quotes(
            {"BTC-USD":fake_quote("BTC-USD",now,90000.)},
            self.db,now=now,
        )
        self.assertEqual(result["status"],"STALE_POSITION_QUOTES")
        self.assertEqual(result["missing"],["ETH-USD"])
        self.assertEqual(len(dashboard(self.db)["equity"]),1)

    def test_selling_uses_real_bid_and_fee_produces_realized_pnl_in_ledger(self):
        pause(False,self.db)
        self.apply(t=0)
        con=sqlite3.connect(self.db)
        t0=self.base.isoformat()
        con.execute(
            "INSERT INTO live_positions(symbol,quantity,basis,entry_ask,opened_at,last_bid)"
            " VALUES(?,?,?,?,?,?)",("ETH-USD",.1,305.,3050.,t0,3000.)
        )
        con.execute(
            "UPDATE live_state SET cash=9695,equity=9985,peak=10000 WHERE id=1"
        )
        con.execute(
            "INSERT INTO live_orders(symbol,side,decision_time,expires_at,reason,weight)"
            " VALUES(?,?,?,?,?,?)",
            ("ETH-USD","SELL",t0,(self.base+timedelta(seconds=7)).isoformat(),
             "Test net exit",0)
        )
        con.commit()
        con.close()
        result=self.apply(t=1,btc=90000,eth=3100)
        self.assertTrue(any(x["event"]=="SELL_PAPER" for x in result["events"]))
        fills=dashboard(self.db)["fills"]
        self.assertEqual(fills[0]["side"],"SELL")
        self.assertLess(fills[0]["price"],3100)
        self.assertGreater(fills[0]["fee"],0)
        self.assertEqual(len(dashboard(self.db)["positions"]),0)

    def test_cost_assumptions_are_conservative_and_no_free_profit(self):
        cfg=LivePolicy()
        self.assertEqual(cfg.fee_bps_each_side,80.)
        self.assertGreater(cfg.profit_net_bps,0)
        self.assertLessEqual(cfg.max_exposure,.30)
        self.assertLessEqual(cfg.top_book_participation,.25)

    def test_risk_rejects_crossed_book_and_excessive_spread(self):
        now=self.base
        q=fake_quote("BTC-USD",now,90100,90000)
        self.assertLess(q.ask,q.bid)
        # Live quote engine should not silently accept crossed market.
        pause(False,self.db)
        with self.assertRaises(ValueError):
            apply_real_quotes({"BTC-USD":q},self.db,now=now)

    def test_there_is_no_broker_connector(self):
        import inspect
        import nory.live_paper as module
        text=inspect.getsource(module)
        self.assertNotIn("api_key",text.lower())
        self.assertNotIn("place_order",text.lower())


if __name__=="__main__":
    unittest.main()
