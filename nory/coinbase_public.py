"""Coinbase Exchange PUBLIC ticker feed: authentic bid/ask, no private API.

Public market data does not mean guaranteed execution. This client *only*
receives quotes. Never place orders or handle account credentials here.
"""
from datetime import datetime,timezone
import json
import math
from threading import Event,RLock,Thread

from nory.kraken_public import PublicQuote,QuoteStore,_parse_timestamp

COINBASE_WS_URL="wss://ws-feed.exchange.coinbase.com"
COINBASE_PROVIDER="COINBASE_EXCHANGE_PUBLIC_WS"
# Public USD spot products; exchange availability may change. Rejections are
# displayed explicitly rather than substituted with synthetic prices.
PAIRS=(
    "BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD",
    "DOGE-USD","AVAX-USD","LINK-USD","LTC-USD","BCH-USD",
    "XLM-USD","UNI-USD","AAVE-USD","DOT-USD","NEAR-USD",
)


def parse_coinbase_ticker(message,now=None) -> list[PublicQuote]:
    if not isinstance(message,dict) or message.get("type")!="ticker":
        return []
    sym=message.get("product_id")
    if sym not in PAIRS:
        return []
    try:
        bid=float(message["best_bid"])
        ask=float(message["best_ask"])
        bsize=float(message["best_bid_size"])
        asize=float(message["best_ask_size"])
        time_exchange=_parse_timestamp(message["time"])
        if "sequence" in message and (isinstance(message["sequence"],bool)
                                     or int(message["sequence"])<0):
            return []
    except (KeyError,TypeError,ValueError,OverflowError):
        return []
    if not all(math.isfinite(x) for x in (bid,ask,bsize,asize)):
        return []
    if not (0<bid<ask and bsize>0 and asize>0):
        return []
    if (ask-bid)/((ask+bid)*.5)>.03:
        return []
    now=now or datetime.now(timezone.utc)
    lag=(now-time_exchange).total_seconds()
    if not -2<=lag<=15:
        return []
    return [PublicQuote(
        symbol=sym,exchange_symbol=sym,
        bid=bid,ask=ask,bid_qty=bsize,ask_qty=asize,
        exchange_time=time_exchange.isoformat(),
        received_time=now.astimezone(timezone.utc).isoformat(),
        provider=COINBASE_PROVIDER,
    )]


class CoinbasePublicClient:
    """Opt-in 15-product public exchange feed; reconnect with backoff."""

    def __init__(self,symbols=("BTC-USD","ETH-USD","SOL-USD"),store=None,app_factory=None):
        symbols=tuple(dict.fromkeys(symbols))
        if not symbols or len(symbols)>len(PAIRS) or any(s not in PAIRS for s in symbols):
            raise ValueError("Unsupported Coinbase Exchange public USD spot product")
        self.symbols=symbols
        self.store=store or QuoteStore()
        self._factory=app_factory
        self._lock=RLock()
        self._stop=Event()
        self._thread=None
        self._socket=None
        self._state="IDLE"
        self._error=None
        self._reconnects=0
        self._rejected=0

    def status(self):
        with self._lock:
            return {
                "state":self._state,
                "running":self._thread is not None and self._thread.is_alive(),
                "error":self._error,
                "reconnect_attempts":self._reconnects,
                "symbols":list(self.symbols),
                "endpoint":COINBASE_WS_URL,
                **self.store.metrics(),
            }

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop=Event()
            self._state="CONNECTING"
            self._error=None
            self._thread=Thread(target=self._run,name="Nory-Coinbase-Public-WS",daemon=True)
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()
        with self._lock:
            sock=self._socket
        if sock is not None:
            try: sock.close()
            except Exception: pass
        with self._lock:
            thread=self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=4)
        with self._lock:
            self._state="STOPPED"

    def _run(self):
        import websocket
        factory=self._factory or websocket.WebSocketApp
        backoff=1.
        while not self._stop.is_set():
            def on_open(ws):
                ws.send(json.dumps({
                    "type":"subscribe",
                    "product_ids":list(self.symbols),
                    "channels":["ticker","heartbeat"],
                }))
                with self._lock:
                    self._state="SUBSCRIBED_WAITING_FOR_TRADES"
                    self._error=None

            def on_message(ws,raw):
                if not isinstance(raw,str) or len(raw)>256000:
                    return
                try:
                    message=json.loads(raw)
                    if not isinstance(message,dict):
                        return
                    if message.get("type")=="error":
                        with self._lock:
                            self._state="ERROR"
                            self._error=str(message.get("message","Exchange rejected subscription"))[:220]
                        ws.close()
                        return
                    parsed=parse_coinbase_ticker(message)
                    good=0
                    for q in parsed:
                        if self.store.record_quote(q):
                            good+=1
                    if good:
                        with self._lock:
                            self._state="RECEIVING_LIVE_UPDATES"
                except (ValueError,TypeError,AttributeError):
                    return

            def on_error(ws,error):
                with self._lock:
                    self._error=f"{type(error).__name__}: {str(error)[:180]}"
                    self._state="RECONNECTING"

            def on_close(ws,code,message):
                with self._lock:
                    if not self._stop.is_set():
                        self._state="DISCONNECTED"

            try:
                ws=factory(COINBASE_WS_URL,on_open=on_open,on_message=on_message,
                           on_error=on_error,on_close=on_close)
                with self._lock:
                    self._socket=ws
                ws.run_forever(ping_interval=25,ping_timeout=10)
            except Exception as exc:
                with self._lock:
                    self._error=f"{type(exc).__name__}: {str(exc)[:180]}"
                    self._state="RECONNECTING"
            finally:
                with self._lock:
                    self._socket=None
            if self._stop.wait(backoff):
                break
            with self._lock:
                self._reconnects+=1
            backoff=min(30.,backoff*2)
        with self._lock:
            self._state="STOPPED"
