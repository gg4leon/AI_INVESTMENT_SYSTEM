from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
import re


def timestamp(value: str) -> float:
    if not isinstance(value, str):
        raise ValueError("Se requiere una fecha RFC3339")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("Fecha sin zona horaria")
    return moment.timestamp()


def iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(
        timespec="milliseconds"
    )


@dataclass(frozen=True)
class Quote:
    provider: str
    symbol: str
    exchange_ts: float
    received_ts: float
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    sequence: int | None = None
    volume_24h: float | None = None
    change_24h_pct: float | None = None

    def __post_init__(self):
        nums = (
            self.exchange_ts,
            self.received_ts,
            self.bid,
            self.ask,
            self.bid_qty,
            self.ask_qty,
        )
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in nums
        ):
            raise ValueError("Cotización no finita")
        if self.provider not in ("coinbase", "kraken") or not re.fullmatch(
            r"[A-Z0-9]{2,12}-USD", self.symbol
        ):
            raise ValueError("Proveedor o símbolo inválido")
        if not (0 < self.bid < self.ask and self.bid_qty > 0 and self.ask_qty > 0):
            raise ValueError("Libro vacío o cruzado")
        if self.spread_bps > 300 or self.exchange_ts <= 0 or self.received_ts <= 0:
            raise ValueError("Spread o fecha inválidos")
        if self.sequence is not None and (
            type(self.sequence) is not int or self.sequence < 0
        ):
            raise ValueError("Secuencia inválida")
        for value in (self.volume_24h, self.change_24h_pct):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
            ):
                raise ValueError("Volumen/variación inválidos")
        if self.volume_24h is not None and self.volume_24h < 0:
            raise ValueError("Volumen negativo")

    @property
    def mid(self):
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self):
        return (self.ask - self.bid) / self.mid * 10_000

    @property
    def key(self):
        return f"{self.provider}:{self.symbol}:{self.exchange_ts:.6f}:{self.sequence}"

    def fresh(self, now, age):
        return (
            -2 <= now - self.exchange_ts <= age
            and -0.05 <= now - self.received_ts <= age
        )

    def newer_than(self, old):
        return old is None or (
            self.exchange_ts > old.exchange_ts
            and (
                self.sequence is None
                or old.sequence is None
                or self.sequence > old.sequence
            )
        )

    def as_dict(self):
        return asdict(self)


@dataclass
class Position:
    symbol: str
    qty: float
    basis: float
    opened_at: float
    entry_price: float
    last_bid: float
    mark_ts: float
    realized: float = 0.0


@dataclass
class Order:
    id: str
    account: str
    symbol: str
    side: str
    created_at: float
    decision_ts: float
    decision_key: str
    expires_at: float
    qty: float
    remaining: float
    budget: float
    reason: str
    status: str = "PENDING"
    filled_qty: float = 0.0
    last_fill_key: str | None = None


@dataclass
class Account:
    provider: str
    strategy: str
    initial: float
    cash: float
    peak: float
    equity: float
    max_drawdown: float = 0.0
    halted: bool = False
    positions: dict[str, Position] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    cooldowns: dict[str, float] = field(default_factory=dict)
    order_times: list[float] = field(default_factory=list)

    @property
    def id(self):
        return f"{self.provider}:{self.strategy}"

    def as_dict(self):
        return asdict(self)

    @classmethod
    def restore(cls, raw):
        data = dict(raw)
        data["positions"] = {s: Position(**p) for s, p in data["positions"].items()}
        data["orders"] = {s: Order(**o) for s, o in data["orders"].items()}
        return cls(**data)
