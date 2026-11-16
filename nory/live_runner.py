"""Opt-in bridge: PUBLIC Kraken WebSocket -> real-quote paper engine only.

The WebSocket supplies data; the portfolio contains fictitious USD only.
One local worker per Streamlit server process, never a broker account.
"""
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
import time

from nory.kraken_public import KrakenPublicClient, QuoteStore, REVERSE_PAIRS
from nory.live_paper import LIVE_DB, LivePolicy, apply_real_quotes, dashboard, pause


class LivePaperRunner:
    def __init__(self,db_path: str | Path=LIVE_DB, *,client_factory=KrakenPublicClient,
                 processor=apply_real_quotes, interval_seconds=1.,
                 allowed_symbols=None,market_provider="KRAKEN_PUBLIC_WS_V2",
                 policy:LivePolicy|None=None):
        if not .5<=interval_seconds<=10:
            raise ValueError("Invalid live interval")
        self._db_path=Path(db_path)
        self._client_factory=client_factory
        self._processor=processor
        self._lock=RLock()
        self._stop=Event()
        self._thread=None
        self._client=None
        self._symbols=()
        self._status="IDLE"
        self._error=None
        self._cycles=0
        self._last_processed=None
        self._interval=interval_seconds
        self._allowed_symbols=tuple(allowed_symbols or REVERSE_PAIRS)
        self._provider=market_provider
        self._policy=policy

    def status(self):
        with self._lock:
            running=self._thread is not None and self._thread.is_alive()
            feed=self._client.status() if self._client is not None else None
            return {
                "running":running,"status":self._status,
                "error":self._error,"cycles":self._cycles,
                "symbols":list(self._symbols),"feed":feed,
                "last_result":self._last_processed,
                "mode":"PUBLIC_REAL_QUOTES_PAPER_ONLY",
                "interval_seconds":self._interval,
                "provider":self._provider,
                "assumed_fee_bps_each_side":(self._policy.fee_bps_each_side
                                            if self._policy else LivePolicy().fee_bps_each_side),
            }

    def start(self,symbols=("BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD")):
        symbols=tuple(dict.fromkeys(symbols))
        if not symbols or "BTC-USD" not in symbols or any(s not in self._allowed_symbols for s in symbols):
            raise ValueError("Only supported Kraken USD pairs with BTC benchmark")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            state=dashboard(self._db_path)["state"]
            if state["halted"]:
                raise ValueError("Risk circuit halted the account; review before a new session")
            self._symbols=symbols
            self._stop=Event()
            self._client=self._client_factory(symbols=symbols)
            self._status="CONNECTING"
            self._error=None
            self._cycles=0
            self._last_processed=None
            try:
                pause(False,self._db_path)
                self._client.start()
                self._thread=Thread(target=self._loop,daemon=True,
                                    name="Nory-Live-Market-Paper")
                self._thread.start()
            except Exception:
                pause(True,self._db_path)
                if self._client is not None:
                    self._client.stop()
                self._status="ERROR"
                raise
            return True

    def _loop(self):
        last_data=time.monotonic()
        try:
            while not self._stop.is_set():
                client=self._client
                if client is None:
                    break
                feed_state=client.status().get("state")
                quotes=client.store.snapshot(self._symbols,max_age_seconds=10)
                if "BTC-USD" in quotes:
                    result=self._processor(quotes,db_path=self._db_path,
                                           policy=self._policy,market_provider=self._provider)
                    if result["status"]=="PROCESSED":
                        last_data=time.monotonic()
                        with self._lock:
                            self._cycles+=1
                            self._status="PAPER_PROCESSING_REAL_QUOTES"
                            self._last_processed=result
                    elif result["status"]=="HALTED":
                        with self._lock:
                            self._status="CIRCUIT_HALTED"
                            self._last_processed=result
                        break
                    elif result["status"]=="STALE_POSITION_QUOTES":
                        with self._lock:
                            self._status="STOPPED_STALE_POSITION"
                            self._error=("Missing fresh quotes for an open paper position: "
                                         + ", ".join(result.get("missing",[])))
                            self._last_processed=result
                        break
                    elif result["status"]=="PAUSED":
                        with self._lock:
                            self._status="PAUSED"
                        break
                if time.monotonic()-last_data>90:
                    with self._lock:
                        self._status="NO_FRESH_QUOTES_TIMEOUT"
                        self._error=("No usable fresh exchange quote update for 90 seconds. "
                                     "Paper trading stopped safely; no synthetic fallback.")
                    break
                self._stop.wait(self._interval)
        except Exception as exc:
            with self._lock:
                self._status="ERROR"
                self._error=f"{type(exc).__name__}: {str(exc)[:240]}"
        finally:
            # Fail closed. No data updates are mistaken for a live order.
            try:
                pause(True,self._db_path)
            finally:
                if self._client is not None:
                    self._client.stop()
            with self._lock:
                if self._status in ("CONNECTING","PAPER_PROCESSING_REAL_QUOTES"):
                    self._status="STOPPED"

    def stop(self,timeout=5.0):
        self._stop.set()
        pause(True,self._db_path)
        with self._lock:
            client=self._client
            thread=self._thread
        if client is not None:
            client.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._status="STOPPING"
            elif self._status not in ("ERROR","CIRCUIT_HALTED"):
                self._status="STOPPED"
        return self.status()
