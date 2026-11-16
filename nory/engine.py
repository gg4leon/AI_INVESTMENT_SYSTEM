"""Nory v0.7: explainable multi-asset research and conservative paper-only sizing.

Risk scores and allocations are heuristics, NOT estimates of safety or returns.
No broker integration. No sentiment, celebrity data, rumors or RSS in signals.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math

import pandas as pd

from analysis.indicators import add_indicators
from analysis.signal_engine import generate_signal
from app.markets import MARKET_BY_SYMBOL


@dataclass(frozen=True)
class NoryPolicy:
    starting_cash: float = 10_000.0
    max_total_exposure: float = 0.65
    max_position_weight: float = 0.15
    max_category_weight: float = 0.40
    max_crypto_weight: float = 0.12
    max_positions: int = 8
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    stop_loss_pct: float = 0.08
    drawdown_kill_pct: float = 0.12

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Configuracion de Nory invalida: {key}")
        if self.starting_cash <= 0 or not 1 <= self.max_positions <= 20:
            raise ValueError("Capital inicial y posiciones invalidas")
        fractions = (
            self.max_total_exposure, self.max_position_weight,
            self.max_category_weight, self.max_crypto_weight,
            self.stop_loss_pct, self.drawdown_kill_pct,
        )
        if not all(0 < v < 1 for v in fractions):
            raise ValueError("Limites de riesgo deben estar en (0, 1)")
        if self.max_position_weight > self.max_total_exposure:
            raise ValueError("La posicion maxima no puede exceder exposicion maxima")
        if not 0 <= self.fee_bps <= 200 or not 0 <= self.slippage_bps <= 200:
            raise ValueError("Costos por lado deben estar entre 0 y 200 bps")


@dataclass(frozen=True)
class Observation:
    symbol: str
    bar: str
    open_price: float
    close_price: float
    signal: str
    volatility_20d: float
    category: str
    priority: float
    target_weight: float
    reason: str

    def as_dict(self):
        return asdict(self)


def risk_priority(volatility: float, signal: str) -> tuple[float, float]:
    """No infiere seguridad: variacion de 20 velas y score tecnico heuristico."""
    if not math.isfinite(volatility) or volatility < 0:
        raise ValueError("Volatilidad invalida")
    # Una vola mayor reduce prioridad y dimension, sin llamar 'seguro' al activo.
    v = min(volatility, 1.0)
    score = round(100 / (1 + 35 * v), 2)
    allocation = 0.14 if v < 0.012 else 0.09 if v < 0.03 else 0.045
    if signal != "CANDIDATO_COMPRA":
        allocation = 0.0
    return score, allocation


def observation_from_prices(data: pd.DataFrame, symbol: str) -> Observation:
    """Datos históricos completos hasta t; solo crea una hipótesis para t+1."""
    market = MARKET_BY_SYMBOL.get(symbol)
    if market is None or not market.paper_eligible or market.currency != "USD":
        raise ValueError("Nory v0.7 solo admite activos de papel cotizados en USD")
    if not isinstance(data, pd.DataFrame) or len(data) < 55:
        raise ValueError("Al menos 55 velas historicas requeridas")
    if not data.index.is_unique or not data.index.is_monotonic_increasing:
        raise ValueError("Fechas no ordenadas o duplicadas")
    for col in ("Open", "Close"):
        if col not in data or not pd.to_numeric(data[col], errors="coerce").notna().all():
            raise ValueError(f"{col} ausente o incompleto")
        if (pd.to_numeric(data[col]) <= 0).any():
            raise ValueError(f"{col} debe ser positivo")
    prices = pd.to_numeric(data["Close"])
    v = float(prices.pct_change().dropna().tail(20).std(ddof=1))
    if not math.isfinite(v):
        raise ValueError("Volatilidad no disponible")
    analyzed = add_indicators(data)
    signal = generate_signal(analyzed, symbol)
    if not signal.valid:
        raise ValueError("Senal tecnica insuficiente: " + "; ".join(signal.warnings))
    score, weight = risk_priority(v, signal.signal)
    if market.category == "Criptomonedas":
        weight = min(weight, 0.08)
    last = data.iloc[-1]
    timestamp = pd.Timestamp(data.index[-1])
    bar = timestamp.strftime("%Y-%m-%d")
    obs = Observation(
        symbol=symbol, bar=bar, open_price=float(last["Open"]),
        close_price=float(last["Close"]), signal=signal.signal,
        volatility_20d=round(v, 7), category=market.category,
        priority=score, target_weight=round(weight, 4),
        reason=(
            f"{signal.signal}: {signal.agreement}/3 reglas; "
            f"volatilidad diaria 20 velas={v*100:.2f}%. "
            "La prioridad no implica probabilidad de rentabilidad."
        ),
    )
    return obs


def rank_candidates(observations: list[Observation], policy: NoryPolicy | None = None) -> list[Observation]:
    cfg = policy or NoryPolicy()
    chosen = [
        o for o in observations if o.signal == "CANDIDATO_COMPRA" and
        o.target_weight > 0 and o.category in (
            "ETFs", "Acciones EE. UU.", "Acciones internacionales", "Criptomonedas"
        )
    ]
    # Determinista independientemente de orden de llegada desde hilos.
    return sorted(chosen, key=lambda x: (-x.priority, x.symbol))[:cfg.max_positions]


def source_is_fresh(bar: str, category: str, now: datetime | None = None) -> bool:
    """Prohibir decisiones de datos muy viejos en el trabajador histórico."""
    today = (now or datetime.now(timezone.utc)).date()
    try:
        parsed = datetime.strptime(bar, "%Y-%m-%d").date()
    except ValueError:
        return False
    age = (today - parsed).days
    return 0 <= age <= (3 if category == "Criptomonedas" else 7)
