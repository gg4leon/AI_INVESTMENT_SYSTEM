"""Public data only. Heartbeats and snapshots are never invented price updates."""

import asyncio
from dataclasses import asdict, dataclass, field
import json
import logging
import math
import random
import time

from websockets.asyncio.client import connect

from .models import Quote, timestamp

ENDPOINTS = {
    "coinbase": "wss://ws-feed.exchange.coinbase.com",
    "kraken": "wss://ws.kraken.com/v2",
}
log = logging.getLogger(__name__)


def number(value):
    if isinstance(value, bool):
        raise ValueError("Campo numérico booleano inválido")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Campo numérico no finito")
    return parsed


def subscription(provider, symbols):
    if provider == "coinbase":
        return {
            "type": "subscribe",
            "product_ids": list(symbols),
            "channels": ["ticker", "heartbeat"],
        }
    return {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": [s.replace("-", "/") for s in symbols],
            "event_trigger": "bbo",
            "snapshot": False,
        },
    }


def parse_message(provider, message, now, symbols):
    """Validate documented public message shapes; provenance comes from TLS at runtime."""
    if not isinstance(message, dict):
        return []
    if provider == "coinbase":
        if message.get("type") != "ticker":
            return []
        symbol = message.get("product_id")
        if symbol not in symbols:
            return []
        seq = message.get("sequence")
        if type(seq) is not int:
            raise ValueError("Ticker Coinbase sin secuencia entera")
        price = number(message.get("price", message["best_bid"]))
        open_24h = number(message["open_24h"]) if message.get("open_24h") else None
        change = (price / open_24h - 1) * 100 if open_24h and open_24h > 0 else None
        return [
            Quote(
                provider,
                symbol,
                timestamp(message["time"]),
                now,
                number(message["best_bid"]),
                number(message["best_ask"]),
                number(message["best_bid_size"]),
                number(message["best_ask_size"]),
                seq,
                number(message["volume_24h"]) if "volume_24h" in message else None,
                change,
            )
        ]
    if message.get("channel") != "ticker" or message.get("type") != "update":
        return []
    items = message.get("data")
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("Lista ticker Kraken inválida")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Ticker Kraken inválido")
        symbol = str(item.get("symbol", "")).replace("/", "-")
        if symbol not in symbols:
            continue
        result.append(
            Quote(
                provider,
                symbol,
                timestamp(item["timestamp"]),
                now,
                number(item["bid"]),
                number(item["ask"]),
                number(item["bid_qty"]),
                number(item["ask_qty"]),
                volume_24h=number(item["volume"]) if "volume" in item else None,
                change_24h_pct=number(item["change_pct"])
                if "change_pct" in item
                else None,
            )
        )
    return result


@dataclass
class FeedStatus:
    provider: str
    state: str = "CONNECTING"
    messages: int = 0
    valid_quotes: int = 0
    invalid_messages: int = 0
    reconnects: int = 0
    last_message_ts: float | None = None
    last_quote_ts: float | None = None
    latency_ms: float | None = None
    error: str | None = None
    subscriptions: list[str] = field(default_factory=list)
    subscription_errors: dict[str, str] = field(default_factory=dict)


class PublicFeed:
    def __init__(self, provider, symbols, on_quote, *, connector=connect):
        self.provider, self.symbols, self.on_quote = provider, tuple(symbols), on_quote
        self.metrics = FeedStatus(provider)
        self.connector = connector

    def status(self):
        return {**asdict(self.metrics), "endpoint": ENDPOINTS[self.provider]}

    async def run(self):
        delay = 1.0
        try:
            while True:
                self.metrics.state = "CONNECTING"
                connected_at = time.monotonic()
                try:
                    async with self.connector(
                        ENDPOINTS[self.provider],
                        open_timeout=15,
                        close_timeout=3,
                        ping_interval=20,
                        ping_timeout=15,
                        max_size=512_000,
                        max_queue=32,
                        compression=None,
                    ) as socket:
                        await socket.send(
                            json.dumps(subscription(self.provider, self.symbols))
                        )
                        self.metrics.state = "WAITING_FOR_QUOTES"
                        self.metrics.error = None
                        # Receive timeout detects silent connections even if the TCP socket stays open.
                        while True:
                            raw = await asyncio.wait_for(socket.recv(), timeout=35)
                            now = time.time()
                            self.metrics.messages += 1
                            self.metrics.last_message_ts = now
                            try:
                                message = json.loads(raw)
                                if not isinstance(message, dict):
                                    raise ValueError("Mensaje raíz no es un objeto")
                                if message.get("type") == "error":
                                    raise ConnectionError(
                                        str(
                                            message.get(
                                                "message", "Suscripción rechazada"
                                            )
                                        )[:240]
                                    )
                                if message.get("method") == "subscribe":
                                    symbol = str(
                                        message.get("result", {}).get(
                                            "symbol", "general"
                                        )
                                    ).replace("/", "-")
                                    if message.get("success") is False:
                                        self.metrics.subscription_errors[symbol] = str(
                                            message.get("error", "Rechazado")
                                        )[:240]
                                    elif symbol not in self.metrics.subscriptions:
                                        self.metrics.subscriptions.append(symbol)
                                if message.get("type") == "subscriptions":
                                    self.metrics.subscriptions = sorted(
                                        {
                                            s
                                            for c in message.get("channels", [])
                                            for s in c.get("product_ids", [])
                                        }
                                    )
                                for quote in parse_message(
                                    self.provider, message, now, self.symbols
                                ):
                                    if not quote.fresh(now, 15):
                                        self.metrics.invalid_messages += 1
                                        continue
                                    self.metrics.valid_quotes += 1
                                    self.metrics.last_quote_ts = now
                                    self.metrics.latency_ms = (
                                        now - quote.exchange_ts
                                    ) * 1000
                                    self.metrics.state = "LIVE"
                                    self.on_quote(quote, now)
                            except (ValueError, KeyError, TypeError, OverflowError):
                                self.metrics.invalid_messages += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.metrics.state = "RECONNECTING"
                    self.metrics.error = f"{type(exc).__name__}: {str(exc)[:240]}"
                    log.warning("%s: %s", self.provider, self.metrics.error)
                if time.monotonic() - connected_at > 60:
                    delay = 1.0
                self.metrics.reconnects += 1
                await asyncio.sleep(delay + random.uniform(0, delay * 0.15))
                delay = min(30.0, delay * 2)
        finally:
            self.metrics.state = "STOPPED"
