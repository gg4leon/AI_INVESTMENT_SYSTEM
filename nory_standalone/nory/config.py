from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

STRATEGIES = ("trend", "mean_reversion", "momentum", "breakout", "cash")
RULES_VERSION = "2.0.0-fixed-rules"
LABELS = {
    "trend": "Seguimiento de tendencia",
    "mean_reversion": "Reversión a la media",
    "momentum": "Momentum",
    "breakout": "Ruptura de rango",
    "cash": "Defensiva · efectivo",
}
BASE = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    initial_capital: float = 10_000.0
    symbols: tuple[str, ...] = (
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "XRP-USD",
        "ADA-USD",
        "DOGE-USD",
    )
    providers: tuple[str, ...] = ("coinbase", "kraken")
    cadence_seconds: float = 0.5
    sample_seconds: int = 1
    min_history: int = 120
    history_limit: int = 1800
    max_gap_seconds: float = 8.0
    quote_max_age_seconds: float = 8.0
    fee_bps: dict[str, float] = field(
        default_factory=lambda: {"coinbase": 60.0, "kraken": 40.0}
    )
    slippage_bps: float = 5.0
    max_spread_bps: float = 30.0
    min_net_edge_bps: float = 35.0
    profit_net_bps: float = 60.0
    stop_net_bps: float = 250.0
    max_drawdown: float = 0.08
    max_asset_weight: float = 0.12
    max_category_weight: float = 0.40
    cash_reserve: float = 0.50
    risk_per_trade: float = 0.003
    max_positions: int = 4
    max_orders_per_minute: int = 6
    correlation_limit: float = 0.80
    max_correlated_weight: float = 0.20
    min_correlation_samples: int = 30
    top_book_participation: float = 0.10
    min_liquidity_usd: float = 500.0
    min_order_usd: float = 25.0
    order_ttl_seconds: float = 10.0
    cooldown_seconds: float = 60.0
    shock_fraction: float = 0.03
    market_shock_fraction: float = 0.015
    shock_cooldown_seconds: float = 180.0
    max_volatility: float = 0.015
    retention_days: int = 7
    max_recorded_samples: int = 300_000

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name in ("symbols", "providers", "fee_bps"):
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Parámetro no numérico/finito: {name}")
        integers = (
            "sample_seconds",
            "min_history",
            "history_limit",
            "max_positions",
            "max_orders_per_minute",
            "min_correlation_samples",
            "retention_days",
            "max_recorded_samples",
        )
        if any(type(getattr(self, name)) is not int for name in integers):
            raise ValueError("Los contadores deben ser enteros")
        if (
            not 100 <= self.initial_capital <= 1e9
            or not 0.5 <= self.cadence_seconds <= 1
        ):
            raise ValueError("Capital o cadencia inválidos (0.5–1 s)")
        if not (
            1 <= self.sample_seconds <= 60
            and 35 <= self.min_history <= self.history_limit <= 5000
        ):
            raise ValueError("Historial inválido")
        if (
            not 1 <= self.max_positions <= 20
            or not 1 <= self.max_orders_per_minute <= 60
        ):
            raise ValueError("Límites de órdenes inválidos")
        if (
            not self.providers
            or len(set(self.providers)) != len(self.providers)
            or any(p not in ("coinbase", "kraken") for p in self.providers)
        ):
            raise ValueError("Proveedor público no admitido")
        if (
            not 1 <= len(self.symbols) <= 40
            or len(set(self.symbols)) != len(self.symbols)
            or any(not re.fullmatch(r"[A-Z0-9]{2,12}-USD", s) for s in self.symbols)
        ):
            raise ValueError("Usa 1–40 símbolos spot únicos cotizados en USD")
        if "BTC-USD" not in self.symbols:
            raise ValueError(
                "Incluye BTC-USD como referencia de mercado del mismo proveedor"
            )
        if set(self.fee_bps) != {"coinbase", "kraken"} or any(
            isinstance(v, bool)
            or not isinstance(v, (float, int))
            or not math.isfinite(v)
            or not 0 <= v <= 300
            for v in self.fee_bps.values()
        ):
            raise ValueError("Comisiones simuladas inválidas")
        fractions = (
            self.max_drawdown,
            self.max_asset_weight,
            self.max_category_weight,
            self.cash_reserve,
            self.risk_per_trade,
            self.correlation_limit,
            self.max_correlated_weight,
            self.top_book_participation,
            self.shock_fraction,
            self.market_shock_fraction,
            self.max_volatility,
        )
        if not all(0 < f < 1 for f in fractions):
            raise ValueError("Las fracciones de riesgo deben estar entre 0 y 1")
        if (
            not self.max_asset_weight
            <= self.max_category_weight
            <= 1 - self.cash_reserve
        ):
            raise ValueError("Los límites de exposición y reserva son incompatibles")
        if not (
            0 <= self.slippage_bps <= 150
            and 0 < self.max_spread_bps <= 300
            and 0 < self.min_net_edge_bps < 5000
            and 0 < self.profit_net_bps < 5000
            and 0 < self.stop_net_bps < 5000
        ):
            raise ValueError("Costes/objetivos inválidos")
        if not (
            1 <= self.quote_max_age_seconds <= 30
            and 1 <= self.max_gap_seconds <= 120
            and 1 <= self.order_ttl_seconds <= 60
            and 0 <= self.cooldown_seconds <= 3600
            and 1 <= self.shock_cooldown_seconds <= 86400
        ):
            raise ValueError("Tiempos inválidos")
        if not (
            0 < self.min_order_usd <= self.initial_capital
            and 0 <= self.min_liquidity_usd <= 1e9
            and 10 <= self.min_correlation_samples <= self.min_history
            and 1 <= self.retention_days <= 365
            and 1000 <= self.max_recorded_samples <= 5_000_000
        ):
            raise ValueError("Límites de liquidez/retención inválidos")

    def fingerprint(self):
        return hashlib.sha256(
            json.dumps(
                {"rules_version": RULES_VERSION, "parameters": asdict(self)},
                sort_keys=True,
            ).encode()
        ).hexdigest()


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        return Config()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("La configuración debe ser un objeto JSON")
    for key in ("symbols", "providers"):
        if key in raw:
            raw[key] = tuple(raw[key])
    try:
        return Config(**raw)
    except TypeError as exc:
        raise ValueError(f"Campo de configuración inválido: {exc}") from exc
