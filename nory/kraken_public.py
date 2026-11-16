"""Kraken public WebSocket v2 — REAL order-book top quotes, NO trading.

A feed update is not a fill and is not guaranteed obtainable. This module
never uses credentials, account endpoints or order endpoints.
"""
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from threading import Event, RLock, Thread
import time

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"
PAIRS = {
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "SOL/USD": "SOL-USD",
    "XRP/USD": "XRP-USD",
    "ADA/USD": "ADA-USD",
}
REVERSE_PAIRS = {v:k for k,v in PAIRS.items()}
MAX_SUBSCRIPTIONS = len(PAIRS)


def _utc():
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("Missing exchange timestamp")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Exchange timestamp needs timezone")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class PublicQuote:
    symbol: str
    exchange_symbol: str
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    exchange_time: str
    received_time: str
    provider: str = "KRAKEN_PUBLIC_WS_V2"

    @property
    def mid(self) -> float:
        return (self.bid+self.ask)/2

    @property
    def spread_bps(self) -> float:
        return (self.ask-self.bid)/self.mid*10000

    def as_dict(self):
        return {**asdict(self),"mid":self.mid,"spread_bps":self.spread_bps}

    def is_fresh(self, now=None, max_age_seconds=10) -> bool:
        now=now or _utc()
        if now.tzinfo is None:
            raise ValueError("Current clock must be timezone-aware")
        exchange=_parse_timestamp(self.exchange_time)
        received=_parse_timestamp(self.received_time)
        age_exchange=(now-exchange).total_seconds()
        age_received=(now-received).total_seconds()
        return (0<=age_exchange<=max_age_seconds
                and 0<=age_received<=max_age_seconds)


def parse_public_ticker(message: dict, now=None) -> list[PublicQuote]:
    """Validate authentic message SHAPE, never verify authenticity offline.

    Only Kraken WebSocket ticker updates, not initial snapshots, are accepted
    for the trading research engine (snapshots may be displayed separately).
    """
    if not isinstance(message, dict) or message.get("channel")!="ticker":
        return []
    if message.get("type")!="update":
        return []
    data=message.get("data")
    if not isinstance(data,list) or len(data)>60:
        raise ValueError("Invalid ticker data array")
    now=(now or _utc()).astimezone(timezone.utc)
    result=[]
    for item in data:
        if not isinstance(item,dict):
            continue
        kraken_symbol=item.get("symbol")
        if kraken_symbol not in PAIRS:
            continue
        try:
            bid=float(item["bid"])
            ask=float(item["ask"])
            bid_qty=float(item["bid_qty"])
            ask_qty=float(item["ask_qty"])
            moment=_parse_timestamp(item["timestamp"])
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
        if not all(math.isfinite(x) for x in (bid,ask,bid_qty,ask_qty)):
            continue
        if bid<=0 or ask<=bid or bid_qty<=0 or ask_qty<=0:
            continue
        # No potentially impossible book states or crossed prices.
        if (ask-bid)/((bid+ask)/2)>0.03:
            continue
        lag=(now-moment).total_seconds()
        if not -2<=lag<=15:
            continue
        result.append(PublicQuote(
            symbol=PAIRS[kraken_symbol],exchange_symbol=kraken_symbol,
            bid=bid,ask=ask,bid_qty=bid_qty,ask_qty=ask_qty,
            exchange_time=moment.isoformat(),received_time=now.isoformat(),
        ))
    return result


class QuoteStore:
    """Thread-safe last-known quotes. Staleness is enforced on reads."""

    def __init__(self):
        self._lock=RLock()
        self._latest:dict[str,PublicQuote]={}
        self._received=0
        self._rejected=0

    def record_message(self,message,now=None):
        try:
            parsed=parse_public_ticker(message,now=now)
        except (TypeError,ValueError):
            with self._lock:
                self._rejected+=1
            return 0
        count=0
        with self._lock:
            for quote in parsed:
                previous=self._latest.get(quote.symbol)
                if previous and _parse_timestamp(quote.exchange_time)<=_parse_timestamp(previous.exchange_time):
                    self._rejected+=1
                    continue
                self._latest[quote.symbol]=quote
                self._received+=1
                count+=1
        return count

    def snapshot(self,symbols=None,max_age_seconds=10,now=None):
        now=now or _utc()
        if not 1<=max_age_seconds<=30:
            raise ValueError("max_age_seconds out of range")
        with self._lock:
            subset=symbols or tuple(self._latest)
            return {
                symbol:self._latest[symbol]
                for symbol in subset if symbol in self._latest
                and self._latest[symbol].is_fresh(now,max_age_seconds)
            }

    def metrics(self):
        with self._lock:
            return {
                "messages_valid":self._received,
                "messages_rejected":self._rejected,
                "symbols_seen":sorted(self._latest),
            }


class KrakenPublicClient:
    """Opt-in public WebSocket reader, no account. Reconnects with backoff."""

    def __init__(self,symbols=("BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD"),
                 store=None, app_factory=None):
        symbols=tuple(dict.fromkeys(symbols))
        if not symbols or len(symbols)>MAX_SUBSCRIPTIONS or any(s not in REVERSE_PAIRS for s in symbols):
            raise ValueError("Unsupported Kraken spot symbols")
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

    def status(self):
        with self._lock:
            return {
                "state":self._state,
                "running":self._thread is not None and self._thread.is_alive(),
                "error":self._error,
                "reconnect_attempts":self._reconnects,
                "symbols":list(self.symbols),
                "endpoint":KRAKEN_WS_URL,
                **self.store.metrics(),
            }

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop=Event()
            self._state="CONNECTING"
            self._error=None
            self._thread=Thread(target=self._run,daemon=True,name="Nory-Kraken-Public-WS")
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()
        with self._lock:
            ws=self._socket
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        with self._lock:
            thread=self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=4)
        with self._lock:
            self._state="STOPPED"

    def _run(self):
        # Imported lazily: no socket is opened just by importing the module.
        import websocket
        factory=self._factory or websocket.WebSocketApp
        backoff=1.
        while not self._stop.is_set():
            def on_open(ws):
                req={"method":"subscribe","params":{
                    "channel":"ticker",
                    "symbol":[REVERSE_PAIRS[x] for x in self.symbols],
                    "event_trigger":"bbo","snapshot":True,
                }}
                ws.send(json.dumps(req))
                with self._lock:
                    self._state="SUBSCRIBED_WAITING_FOR_UPDATES"
                    self._error=None

            def on_message(ws,raw):
                if not isinstance(raw,str) or len(raw)>256_000:
                    return
                try:
                    msg=json.loads(raw)
                    if (msg.get("method")=="subscribe" and
                        msg.get("success") is False):
                        with self._lock:
                            self._error=str(msg.get("error","subscription rejected"))[:180]
                            self._state="ERROR"
                        ws.close()
                        return
                    count=self.store.record_message(msg)
                    if count:
                        with self._lock:
                            self._state="RECEIVING_LIVE_UPDATES"
                except (ValueError,TypeError,AttributeError):
                    return

            def on_error(ws,error):
                with self._lock:
                    self._error=f"{type(error).__name__}: {str(error)[:160]}"
                    self._state="RECONNECTING"

            def on_close(ws,close_code,close_msg):
                with self._lock:
                    if not self._stop.is_set():
                        self._state="DISCONNECTED"

            try:
                ws=factory(KRAKEN_WS_URL,on_open=on_open,on_message=on_message,
                           on_error=on_error,on_close=on_close)
                with self._lock:
                    self._socket=ws
                ws.run_forever(ping_interval=25,ping_timeout=10)
            except Exception as exc:
                with self._lock:
                    self._error=f"{type(exc).__name__}: {str(exc)[:160]}"
                    self._state="RECONNECTING"
            finally:
                with self._lock:
                    self._socket=None
            if self._stop.wait(backoff):
                break
            with self._lock:
                self._reconnects+=1
            backoff=min(backoff*2,30)
        with self._lock:
            self._state="STOPPED"
