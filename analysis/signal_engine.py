"""AIS v0.4: motor de señales determinista, explicable y sin ejecución de órdenes.

Las etiquetas CANDIDATO_COMPRA/VENTA describen condiciones técnicas,
NO constituyen recomendaciones ni instrucciones de operar.
"""
from dataclasses import dataclass
from typing import Tuple
import math
import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    min_bars: int = 35
    bullish_rsi_min: float = 45.0
    bullish_rsi_max: float = 68.0
    bearish_rsi_min: float = 32.0
    bearish_rsi_max: float = 55.0
    minimum_agreement: int = 3

    def __post_init__(self):
        if self.min_bars < 30:
            raise ValueError("min_bars debe ser >= 30")
        if not (0 <= self.bullish_rsi_min < self.bullish_rsi_max <= 100):
            raise ValueError("Rango RSI alcista invalido")
        if not (0 <= self.bearish_rsi_min < self.bearish_rsi_max <= 100):
            raise ValueError("Rango RSI bajista invalido")
        if not 1 <= self.minimum_agreement <= 3:
            raise ValueError("minimum_agreement debe estar entre 1 y 3")


@dataclass(frozen=True)
class SignalReport:
    symbol: str
    timestamp: str
    signal: str
    bias: str
    agreement: int
    score: int
    observations: Tuple[str, ...]
    warnings: Tuple[str, ...]
    valid: bool

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "timestamp": self.timestamp,
            "signal": self.signal, "bias": self.bias,
            "agreement": self.agreement, "score": self.score,
            "observations": list(self.observations),
            "warnings": list(self.warnings), "valid": self.valid,
        }


REQUIRED = ("Close", "SMA_10", "SMA_30", "RSI_14",
            "MACD", "MACD_SIGNAL", "MACD_HIST")


def _invalid(symbol: str, reason: str, timestamp: str = "") -> SignalReport:
    return SignalReport(
        symbol=symbol, timestamp=timestamp, signal="SIN_SENAL",
        bias="INDETERMINADO", agreement=0, score=0,
        observations=(), warnings=(reason,), valid=False,
    )


def generate_signal(
    data: pd.DataFrame,
    symbol: str,
    config: SignalConfig | None = None,
) -> SignalReport:
    """Evalúa únicamente indicadores disponibles hasta la última vela.

    No mira velas futuras. El score mide acuerdo entre reglas,
    NO probabilidad de éxito, precisión ni rentabilidad.
    """
    cfg = config or SignalConfig()
    if not isinstance(data, pd.DataFrame) or data.empty:
        return _invalid(symbol, "Sin datos historicos")
    if not data.index.is_unique or not data.index.is_monotonic_increasing:
        return _invalid(symbol, "Indice temporal duplicado o desordenado")
    if len(data) < cfg.min_bars:
        return _invalid(symbol, f"Insuficiente historial: {len(data)}/{cfg.min_bars} velas")

    missing = [name for name in REQUIRED if name not in data.columns]
    if missing:
        return _invalid(symbol, "Faltan indicadores: " + ", ".join(missing))

    last = data.iloc[-1]
    timestamp = str(data.index[-1])
    try:
        values = {name: float(last[name]) for name in REQUIRED}
    except (TypeError, ValueError):
        return _invalid(symbol, "Indicadores no numericos", timestamp)
    if not all(math.isfinite(v) for v in values.values()):
        return _invalid(symbol, "Indicadores no finitos o incompletos", timestamp)
    if values["Close"] <= 0 or not 0 <= values["RSI_14"] <= 100:
        return _invalid(symbol, "Precio o RSI fuera de rango", timestamp)

    sma_up = values["SMA_10"] > values["SMA_30"]
    sma_down = values["SMA_10"] < values["SMA_30"]
    macd_up = values["MACD"] > values["MACD_SIGNAL"] and values["MACD_HIST"] > 0
    macd_down = values["MACD"] < values["MACD_SIGNAL"] and values["MACD_HIST"] < 0
    rsi_up = cfg.bullish_rsi_min <= values["RSI_14"] <= cfg.bullish_rsi_max
    rsi_down = cfg.bearish_rsi_min <= values["RSI_14"] <= cfg.bearish_rsi_max

    up = sum((sma_up, macd_up, rsi_up))
    down = sum((sma_down, macd_down, rsi_down))
    observations = (
        f"SMA10 {'>' if sma_up else '<' if sma_down else '='} SMA30",
        f"MACD {'sobre' if macd_up else 'bajo' if macd_down else 'igual/inconsistente con'} senal",
        f"RSI14={values['RSI_14']:.1f}",
    )
    warnings = ["Score heuristico: no es probabilidad de ganar"]
    if up >= cfg.minimum_agreement and up > down:
        signal, bias, agreement = "CANDIDATO_COMPRA", "ALCISTA", up
    elif down >= cfg.minimum_agreement and down > up:
        signal, bias, agreement = "CANDIDATO_VENTA", "BAJISTA", down
    else:
        signal, bias, agreement = "ESPERAR", "MIXTO", max(up, down)
        warnings.append("Indicadores sin acuerdo suficiente")
    if symbol.endswith("=X"):
        warnings.append("Forex: volumen de Yahoo puede no ser representativo")
    score = round(agreement / 3 * 100)
    return SignalReport(
        symbol=symbol, timestamp=timestamp, signal=signal,
        bias=bias, agreement=agreement, score=score,
        observations=observations, warnings=tuple(warnings), valid=True,
    )
