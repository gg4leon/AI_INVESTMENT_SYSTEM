"""Past public closes for context. These records can NEVER fill a paper order."""

import asyncio
from collections import deque
from dataclasses import asdict, dataclass
import math
import time

import httpx


@dataclass(frozen=True)
class PriceSample:
    provider: str
    symbol: str
    exchange_ts: float  # End of the completed interval, not its opening timestamp.
    known_at: float  # Local time when this application acquired that close.
    mid: float
    source: str

    def __post_init__(self):
        if self.provider not in ("coinbase", "kraken") or not self.symbol.endswith(
            "-USD"
        ):
            raise ValueError("Contexto de mercado inválido")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
            for v in (self.exchange_ts, self.known_at, self.mid)
        ):
            raise ValueError("Precio o fecha de contexto inválidos")
        if self.known_at < self.exchange_ts:
            raise ValueError("Una vela no puede conocerse antes de cerrar")
        if self.source not in ("PUBLIC_CANDLE", "WS_SAMPLED_MID"):
            raise ValueError("Procedencia de contexto desconocida")

    def as_dict(self):
        return asdict(self)


class AnalysisHistory:
    def __init__(self, cfg):
        self.cfg = cfg
        self.closed = {}
        self.current = {}
        self.events = []

    def seed(self, samples, now, *, record=True):
        touched = {}
        for sample in samples:
            if (
                sample.provider not in self.cfg.providers
                or sample.symbol not in self.cfg.symbols
                or sample.known_at > now
                or sample.exchange_ts > now
            ):
                raise ValueError("Contexto futuro o de otro universo")
            key = sample.provider, sample.symbol
            points = touched.setdefault(
                key, {p.exchange_ts: p for p in self.closed.get(key, ())}
            )
            old = points.get(sample.exchange_ts)
            if old is None or (
                sample.source == "PUBLIC_CANDLE" and old.source != "PUBLIC_CANDLE"
            ):
                points[sample.exchange_ts] = sample
                if record:
                    self.events.append(sample)
        for key, points in touched.items():
            ordered = sorted(points.values(), key=lambda p: p.exchange_ts)
            self.closed[key] = deque(
                ordered[-self.cfg.analysis_history_limit :],
                maxlen=self.cfg.analysis_history_limit,
            )

    def record(self, q):
        key = q.provider, q.symbol
        previous = self.current.get(key)
        interval = self.cfg.analysis_interval_seconds
        bucket = int(q.exchange_ts // interval)
        if previous and bucket > int(previous.exchange_ts // interval):
            ended_at = (int(previous.exchange_ts // interval) + 1) * interval
            if ended_at <= q.received_ts:
                self.seed(
                    [
                        PriceSample(
                            q.provider,
                            q.symbol,
                            ended_at,
                            q.received_ts,
                            previous.mid,
                            "WS_SAMPLED_MID",
                        )
                    ],
                    q.received_ts,
                )
        self.current[key] = q

    def closed_for(self, provider, symbol, now, *, known_at=None):
        window = self.cfg.analysis_lookback * self.cfg.analysis_interval_seconds
        return [
            p
            for p in self.closed.get((provider, symbol), ())
            if now - window <= p.exchange_ts <= now
            and p.known_at <= (now if known_at is None else known_at)
        ]

    def points_for(self, q):
        return [
            *self.closed_for(
                q.provider, q.symbol, q.exchange_ts, known_at=q.received_ts
            ),
            q,
        ]

    def needs_backfill(self, provider, symbol, now):
        points = self.closed_for(provider, symbol, now)
        if not points:
            return True
        expected = max(
            1,
            min(
                self.cfg.analysis_lookback,
                math.ceil(
                    (now - points[0].exchange_ts) / self.cfg.analysis_interval_seconds
                ),
            ),
        )
        return (
            len(points) < self.cfg.min_history - 1
            or len(points) / expected < 0.8
            or now - points[-1].exchange_ts > self.cfg.analysis_interval_seconds * 2
        )


def parse_candles(provider, symbol, payload, now, interval=60):
    if interval not in (60, 300):
        raise ValueError("El bootstrap público admite velas de 1 o 5 minutos")
    if provider == "coinbase":
        rows = payload
    else:
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(
                "Kraken rechazó el historial público: "
                + str(payload.get("error") if isinstance(payload, dict) else payload)[
                    :180
                ]
            )
        result = payload.get("result", {})
        series = [v for k, v in result.items() if k != "last"]
        if len(series) != 1:
            raise ValueError("Respuesta OHLC Kraken ambigua")
        rows = series[0]
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Historial de velas inválido")
    samples = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < (6 if provider == "coinbase" else 8):
            raise ValueError("Formato OHLC inválido")
        if any(isinstance(v, bool) for v in row):
            raise ValueError("Valor OHLC booleano inválido")
        started = float(row[0])
        if provider == "coinbase":
            low, high, opened, close, volume = map(float, row[1:6])
        else:
            opened, high, low, close = map(float, row[1:5])
            volume = float(row[6])
        if (
            not all(
                math.isfinite(v) for v in (started, low, high, opened, close, volume)
            )
            or started <= 0
            or min(low, opened, close) <= 0
            or volume < 0
            or low > min(opened, close)
            or high < max(opened, close)
            or started % interval != 0
        ):
            raise ValueError("Datos OHLC inconsistentes")
        ended = started + interval
        if ended > now:  # Never use the current, unfinished REST candle.
            continue
        point = PriceSample(provider, symbol, ended, now, close, "PUBLIC_CANDLE")
        if ended in samples and samples[ended].mid != close:
            raise ValueError("Velas duplicadas con cierres distintos")
        samples[ended] = point
    return sorted(samples.values(), key=lambda p: p.exchange_ts)


class PublicHistoryClient:
    def __init__(self, cfg, *, client=None):
        self.cfg = cfg
        self.client = client or httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(max_connections=2),
            headers={"User-Agent": "Nory-Paper-Research/2.1"},
        )
        self.last_request = {}

    async def close(self):
        await self.client.aclose()

    async def fetch(self, provider, symbol):
        if self.cfg.analysis_interval_seconds not in (60, 300):
            raise ValueError("La configuración experimental no utiliza bootstrap REST")
        spacing = 1.1 if provider == "kraken" else 0.25
        await asyncio.sleep(
            max(0, self.last_request.get(provider, 0) + spacing - time.monotonic())
        )
        self.last_request[provider] = time.monotonic()
        if provider == "coinbase":
            url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
            params = {"granularity": self.cfg.analysis_interval_seconds}
        else:
            url = "https://api.kraken.com/0/public/OHLC"
            params = {
                "pair": symbol.replace("-", ""),
                "interval": self.cfg.analysis_interval_seconds // 60,
            }
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        samples = parse_candles(
            provider,
            symbol,
            response.json(),
            time.time(),
            self.cfg.analysis_interval_seconds,
        )
        return samples[-self.cfg.analysis_history_limit :]
