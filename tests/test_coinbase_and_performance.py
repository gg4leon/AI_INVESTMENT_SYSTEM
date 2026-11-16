"""AIS 1.0: Coinbase public ticker, provider isolation, performance metrics.

Offline only; fixtures are invented data with real message format.
"""
from datetime import datetime,timedelta,timezone
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nory.coinbase_public import (
    COINBASE_PROVIDER,CoinbasePublicClient,PAIRS,parse_coinbase_ticker
)
from nory.kraken_public import PublicQuote,QuoteStore
from nory.live_paper import LivePolicy,pause,apply_real_quotes,dashboard
from nory.live_runner import LivePaperRunner
from nory.performance import summarize_live,summarize_synthetic,diagnosis


class CoinbaseTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,16,19,0,tzinfo=timezone.utc)
        self.msg={
            "type":"ticker","sequence":1001,"product_id":"BTC-USD",
            "time":self.now.isoformat().replace("+00:00","Z"),
            "price":"92000.5","best_bid":"92000","best_ask":"92001",
            "best_bid_size":"3.5","best_ask_size":"5.5",
        }

    def test_official_public_ticker_shape(self):
        a=parse_coinbase_ticker(self.msg,now=self.now)
        self.assertEqual(len(a),1)
        self.assertEqual(a[0].provider,COINBASE_PROVIDER)
        self.assertEqual(a[0].bid,92000)
        self.assertEqual(a[0].ask,92001)
        self.assertTrue(a[0].is_fresh(now=self.now))

    def test_invalid_message_never_passes(self):
        self.assertEqual(parse_coinbase_ticker({**self.msg,"type":"subscriptions"},now=self.now),[])
        self.assertEqual(parse_coinbase_ticker({**self.msg,"product_id":"FAKE"},now=self.now),[])
        cases=[
            ("best_ask","90000"),("best_bid","not a price"),
            ("best_ask_size",0),("best_bid_size",-1),
            ("time",(self.now-timedelta(seconds=30)).isoformat()),
        ]
        for key,val in cases:
            with self.subTest(key=key):
                self.assertEqual(parse_coinbase_ticker({**self.msg,key:val},now=self.now),[])

    def test_duplicate_quotes_discarded(self):
        q=parse_coinbase_ticker(self.msg,now=self.now)[0]
        s=QuoteStore()
        self.assertTrue(s.record_quote(q))
        self.assertFalse(s.record_quote(q))
        self.assertEqual(len(s.snapshot(("BTC-USD",),now=self.now)),1)
        self.assertEqual(s.metrics()["messages_rejected"],1)

    def test_broader_crypto_universe_and_no_equities(self):
        self.assertGreaterEqual(len(PAIRS),12)
        self.assertIn("DOGE-USD",PAIRS)
        self.assertNotIn("AAPL",PAIRS)
        with self.assertRaises(ValueError):
            CoinbasePublicClient(symbols=("AAPL",))


def q(symbol,time,bid,ask=None,provider=COINBASE_PROVIDER):
    return PublicQuote(
        symbol=symbol,exchange_symbol=symbol,
        bid=bid,ask=ask or bid*1.0001,
        bid_qty=50_000,ask_qty=50_000,
        exchange_time=time.isoformat(),received_time=time.isoformat(),
        provider=provider,
    )


class CoinbaseLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"coinbase_paper.sqlite3"
        self.now=datetime(2026,11,16,19,0,tzinfo=timezone.utc)
        self.policy=LivePolicy(
            fee_bps_each_side=60,max_positions=8,max_exposure=.40,
            max_asset_weight=.065,max_orders_per_60_seconds=24,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def push(self,step,extra=True):
        moment=self.now+timedelta(seconds=step)
        data={"BTC-USD":q("BTC-USD",moment,90000)}
        if extra:
            data["DOGE-USD"]=q("DOGE-USD",moment,.2)
        return apply_real_quotes(
            data,db_path=self.db,policy=self.policy,
            now=moment,market_provider=COINBASE_PROVIDER,
        )

    def test_real_exchange_account_paused_until_opt_in(self):
        self.assertEqual(self.push(0)["status"],"PAUSED")
        self.assertEqual(dashboard(self.db)["state"]["cash"],10000)
        self.assertFalse(summarize_live(self.db,source="COINBASE")["available"] is False)

    def test_paper_persistence_and_distinct_exchange(self):
        pause(False,self.db)
        for t in range(4):
            self.assertEqual(self.push(t)["status"],"PROCESSED")
        result=summarize_live(self.db,source="COINBASE")
        self.assertTrue(result["available"])
        self.assertEqual(result["stats"]["observations"],8)
        self.assertEqual(result["stats"]["distinct_assets"],2)
        self.assertEqual(result["stats"]["simulated_buys"],0)
        self.assertEqual(result["stats"]["total_fees"],0)
        self.assertGreater(result["stats"]["benchmark_btc_gross_pct"]-0.,-0.001)
        self.assertIn("Calentamiento",diagnosis(result))
        self.assertEqual(dashboard(self.db)["state"]["provider"],COINBASE_PROVIDER)

    def test_no_mix_with_kraken_quotes_even_same_pair(self):
        pause(False,self.db)
        self.push(0)
        moment=self.now+timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,"Unverified quote provider"):
            apply_real_quotes(
                {"BTC-USD":q("BTC-USD",moment,90001,provider="KRAKEN_PUBLIC_WS_V2")},
                db_path=self.db,policy=self.policy,
                now=moment,market_provider=COINBASE_PROVIDER,
            )
        with self.assertRaisesRegex(ValueError,"Cannot mix"):
            apply_real_quotes(
                {"BTC-USD":q("BTC-USD",moment,90001,provider="KRAKEN_PUBLIC_WS_V2")},
                db_path=self.db,policy=self.policy,now=moment,
                market_provider="KRAKEN_PUBLIC_WS_V2",
            )

    def test_coinbase_pending_entry_and_fee_metrics(self):
        pause(False,self.db)
        self.push(0)
        con=sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO live_orders(symbol,side,decision_time,expires_at,reason,weight)"
            " VALUES(?,?,?,?,?,?)",
            ("DOGE-USD","BUY",self.now.isoformat(),
             (self.now+timedelta(seconds=7)).isoformat(),"Fixture entry",.06)
        )
        con.commit()
        con.close()
        r=self.push(1)
        self.assertEqual(r["status"],"PROCESSED")
        report=summarize_live(self.db,source="COINBASE")
        self.assertEqual(report["stats"]["simulated_buys"],1)
        self.assertGreater(report["stats"]["total_fees"],0)
        self.assertLess(report["stats"]["equity"],10000)
        self.assertEqual(len(report["positions"]),1)

    def test_new_ledger_provider_isolated(self):
        second=Path(self.tmp.name)/"kraken.sqlite3"
        pause(False,second)
        moment=self.now
        kraken=q("BTC-USD",moment,90000,provider="KRAKEN_PUBLIC_WS_V2")
        result=apply_real_quotes(
            {"BTC-USD":kraken},db_path=second,now=moment,
        )
        self.assertEqual(result["status"],"PROCESSED")
        self.assertEqual(dashboard(second)["state"]["provider"],"KRAKEN_PUBLIC_WS_V2")
        self.assertEqual(dashboard(self.db)["state"]["cash"],10000)

    def test_performance_missing_files_works(self):
        missing=Path(self.tmp.name)/"none.sqlite3"
        self.assertFalse(summarize_live(missing,source="COINBASE")["available"])
        self.assertFalse(summarize_synthetic(missing)["available"])
        with self.assertRaises(ValueError):
            summarize_live(missing,source="UNKNOWN")


if __name__=="__main__":
    unittest.main()
