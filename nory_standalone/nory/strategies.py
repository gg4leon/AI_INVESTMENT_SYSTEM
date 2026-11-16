"""Versioned, fixed research hypotheses. Scores are NOT probabilities."""

from dataclasses import asdict, dataclass, field
from statistics import mean, pstdev
import math

from .config import LABELS, RULES_VERSION

VERSION = RULES_VERSION


@dataclass
class Signal:
    action: str
    score: float
    reason: str
    checks: dict[str, bool] = field(default_factory=dict)
    features: dict[str, float] = field(default_factory=dict)
    headroom_bps: float = 0.0
    uncertainty: str = "Alta: hipótesis técnica sin ventaja validada"

    def as_dict(self):
        return asdict(self)


def indicators(quotes):
    prices = [q.mid for q in quotes]
    recent = prices[-120:]
    returns = [b / a - 1 for a, b in zip(recent, recent[1:])]
    deltas = [b - a for a, b in zip(prices[-15:], prices[-14:])]
    gain = mean([max(d, 0) for d in deltas])
    loss = mean([max(-d, 0) for d in deltas])
    rsi = 100 - 100 / (1 + gain / loss) if loss else 100.0 if gain else 50.0
    avg, sigma = mean(recent), pstdev(recent)
    return {
        "sma_short": mean(prices[-15:]),
        "sma_medium": mean(prices[-60:]),
        "mean": avg,
        "volatility": pstdev(returns) if len(returns) > 1 else 0.0,
        "momentum_bps": (prices[-1] / prices[-30] - 1) * 10_000,
        "medium_bps": (prices[-1] / prices[-min(len(prices), 120)] - 1) * 10_000,
        "rsi": rsi,
        "z_score": (prices[-1] - avg) / sigma if sigma else 0.0,
        "range_bps": (max(recent) / min(recent) - 1) * 10_000,
        "last_return": prices[-1] / prices[-2] - 1,
        "prior_high": max(prices[-61:-1]),
        "prior_low": min(prices[-61:-1]),
    }


def evaluate(strategy, quotes, cfg, provider, *, in_position=False):
    if strategy == "cash":
        return Signal(
            "WAIT",
            0,
            "La estrategia defensiva conserva el 100 % en efectivo.",
            uncertainty="Sin exposición al mercado",
        )
    if len(quotes) < cfg.min_history:
        return Signal(
            "WARMUP",
            0,
            f"Preparando historial: {len(quotes)}/{cfg.min_history} muestras auténticas en intervalos distintos.",
        )
    q = quotes[-1]
    f = indicators(quotes)
    cost = 2 * (cfg.fee_bps[provider] + cfg.slippage_bps) + q.spread_bps
    common = {
        "spread_aceptable": q.spread_bps <= cfg.max_spread_bps,
        "liquidez_visible": min(q.bid * q.bid_qty, q.ask * q.ask_qty)
        >= cfg.min_liquidity_usd,
        "volatilidad_aceptable": f["volatility"] <= cfg.max_volatility,
        "volumen_reportado": q.volume_24h is not None and q.volume_24h > 0,
    }
    if in_position:
        exit_condition = (
            f["sma_short"] < f["sma_medium"]
            if strategy in ("trend", "momentum", "breakout")
            else f["z_score"] >= 0
        )
        return Signal(
            "SELL" if exit_condition else "HOLD",
            50,
            "Salida por invalidación de la hipótesis técnica."
            if exit_condition
            else "La hipótesis sigue vigente; se vigilan objetivo neto y stop.",
            common,
            f,
        )
    if strategy == "mean_reversion":
        checks = {
            "desviacion_bajo_media": f["z_score"] < -1.25,
            "rebote_observado": f["last_return"] > 0,
            "rsi_recuperacion": 25 < f["rsi"] < 60,
            "sin_tendencia_bajista_fuerte": f["medium_bps"] > -300,
        }
        headroom = max(0, (f["mean"] / q.mid - 1) * 10_000)
    elif strategy == "trend":
        checks = {
            "media_corta_sobre_media": f["sma_short"] > f["sma_medium"],
            "precio_sobre_media": q.mid > f["sma_medium"],
            "momentum_positivo": f["momentum_bps"] > 0,
            "rsi_no_extremo": 45 <= f["rsi"] <= 78,
        }
        headroom = max(0, min(f["medium_bps"], f["range_bps"] * 0.5))
    elif strategy == "momentum":
        checks = {
            "momentum_persistente": f["momentum_bps"] > 25,
            "tendencia_media_positiva": f["medium_bps"] > 0,
            "ultimo_movimiento_positivo": f["last_return"] > 0,
            "rsi_no_extremo": 50 < f["rsi"] < 85,
        }
        headroom = max(0, min(f["momentum_bps"] * 1.5, f["range_bps"] * 0.75))
    elif strategy == "breakout":
        checks = {
            "ruptura_maximo_previo": q.mid > f["prior_high"],
            "momentum_positivo": f["momentum_bps"] > 0,
            "rango_previo_suficiente": f["range_bps"] > cost,
            "rsi_no_extremo": f["rsi"] < 85,
        }
        headroom = max(0, f["range_bps"] * 0.5)
    else:
        raise ValueError("Estrategia desconocida")
    checks = {
        **checks,
        **common,
        "margen_sobre_costes": headroom > cost + cfg.min_net_edge_bps,
    }
    score = round(sum(checks.values()) / len(checks) * 100, 1)
    failed = [k for k, passed in checks.items() if not passed]
    action = (
        "BUY"
        if not failed
        else "BLOCK_COSTS"
        if failed == ["margen_sobre_costes"]
        else "WAIT"
    )
    reason = (
        f"{LABELS[strategy]}: {sum(checks.values())}/{len(checks)} condiciones. "
        f"Margen heurístico {headroom:.1f} bps; coste ida/vuelta {cost:.1f} bps. "
        + (
            "No cumplen: " + ", ".join(failed)
            if failed
            else "Entrada candidata, sujeta a límites de cartera."
        )
    )
    return Signal(
        action, score, reason, checks, {**f, "round_trip_cost_bps": cost}, headroom
    )


def aligned_correlation(a, b, sample_seconds, minimum=30):
    """Match return intervals by BOTH endpoints. Never zip unrelated exchange times."""

    def returns(series):
        out = {}
        for old, new in zip(series, series[1:]):
            left, right = (
                int(old.exchange_ts // sample_seconds),
                int(new.exchange_ts // sample_seconds),
            )
            if right - left == 1:
                out[(left, right)] = new.mid / old.mid - 1
        return out

    ra, rb = returns(a), returns(b)
    common = sorted(ra.keys() & rb.keys())[-120:]
    if len(common) < minimum:
        return None
    xa, xb = [ra[k] for k in common], [rb[k] for k in common]
    ma, mb = mean(xa), mean(xb)
    aa, bb = sum((x - ma) ** 2 for x in xa), sum((x - mb) ** 2 for x in xb)
    if aa <= 1e-24 or bb <= 1e-24:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(xa, xb)) / math.sqrt(aa * bb)
