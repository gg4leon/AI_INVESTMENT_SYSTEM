"""AIS v0.4: observación de riesgo histórico, sin dimensionamiento ni órdenes."""
from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class RiskReport:
    volatility_20d_pct: float | None
    max_drawdown_pct: float | None
    risk_level: str
    warnings: tuple[str, ...]


def assess_risk(data: pd.DataFrame, symbol: str) -> RiskReport:
    """Volatilidad diaria no anualizada y drawdown de cierre en 60 velas.

    Referencias descriptivas, NO límites operativos ni asesoría.
    """
    if not isinstance(data, pd.DataFrame) or "Close" not in data or len(data) < 21:
        return RiskReport(None, None, "SIN_DATOS", ("Se requieren 21 cierres",))
    close = pd.to_numeric(data["Close"], errors="coerce").tail(60)
    if close.isna().any() or not (close > 0).all():
        return RiskReport(None, None, "SIN_DATOS", ("Cierres invalidos",))
    returns = close.pct_change().dropna().tail(20)
    if len(returns) < 20:
        return RiskReport(None, None, "SIN_DATOS", ("Falta historial",))
    vol = float(returns.std(ddof=1) * 100)
    drawdown = float(((close / close.cummax()) - 1).min() * 100)
    if not math.isfinite(vol) or not math.isfinite(drawdown):
        return RiskReport(None, None, "SIN_DATOS", ("Medidas no finitas",))
    # Etiquetas descriptivas para variación diaria; no comparan riesgo entre activos.
    label = "ELEVADA" if vol >= 3 else "MODERADA" if vol >= 1 else "BAJA"
    warnings = ["Volatilidad historica no predice movimientos futuros"]
    if symbol == "BTC-USD":
        warnings.append("Cripto cotiza 24/7; no comparar sus velas con horario bursatil")
    if symbol.endswith("=X"):
        warnings.append("Forex: datos Yahoo pueden ser indicativos")
    return RiskReport(round(vol, 3), round(drawdown, 3), label, tuple(warnings))
