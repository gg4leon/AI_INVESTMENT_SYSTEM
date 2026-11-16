"""Chronological quote replay, training-only selection and an embargoed holdout."""

from dataclasses import asdict, replace
import csv
import json
import math

from .config import STRATEGIES
from .core import ResearchCore
from .evidence import trade_evidence
from .models import Quote, iso
from .strategies import VERSION


def replay(quotes, cfg, *, trade_start=None):
    if not quotes:
        raise ValueError("Sin cotizaciones para reproducir")
    providers = {q.provider for q in quotes}
    if len(providers) != 1:
        raise ValueError("No se mezclan proveedores en el backtest")
    provider = next(iter(providers))
    cfg = replace(cfg, providers=(provider,))
    core = ResearchCore(cfg)
    fills, closed, exposure = [], [], {s: [] for s in STRATEGIES}
    curves = {s: [] for s in STRATEGIES}
    begin = quotes[0].received_ts if trade_start is None else trade_start
    next_step = (
        math.floor(quotes[0].received_ts / cfg.cadence_seconds) + 1
    ) * cfg.cadence_seconds

    def step(moment):
        changed = core.step(moment, running=moment >= begin)
        new_fills, _, new_closed = core.drain_events()
        fills.extend(new_fills)
        closed.extend(new_closed)
        if changed and moment >= begin:
            for s in STRATEGIES:
                a = core.accounts[f"{provider}:{s}"]
                exposure[s].append(
                    max(0.0, (a.equity - a.cash) / a.equity) if a.equity > 0 else 0
                )
                if not curves[s] or moment - curves[s][-1]["time"] >= 10:
                    curves[s].append({"time": moment, "equity": a.equity})

    previous_time = -math.inf
    for q in quotes:
        if q.received_ts < previous_time:
            raise ValueError("El replay requiere orden cronológico de recepción")
        previous_time = q.received_ts
        if q.received_ts >= next_step:
            step(next_step)
            # Missing intervals are not observations and never filled forward.
            next_step = (
                math.floor(q.received_ts / cfg.cadence_seconds) + 1
            ) * cfg.cadence_seconds
        core.receive(q, q.received_ts)
    step(next_step)
    results = {}
    for s in STRATEGIES:
        a = core.accounts[f"{provider}:{s}"]
        sf = [f for f in fills if f["account"] == a.id]
        sc = [t for t in closed if t["account"] == a.id]
        results[s] = {
            "strategy": s,
            "initial": a.initial,
            "final_equity": a.equity,
            "net_return_pct": (a.equity / a.initial - 1) * 100,
            "max_drawdown_pct": a.max_drawdown * 100,
            "fills": len(sf),
            "closed_trades": len(sc),
            "fees": sum(f["fee"] for f in sf),
            "realized_pnl": sum(f["realized_pnl"] for f in sf),
            "win_rate_pct": sum(t["pnl"] > 0 for t in sc) / len(sc) * 100
            if sc
            else None,
            "average_exposure_pct": sum(exposure[s]) / len(exposure[s]) * 100
            if exposure[s]
            else 0,
            "open_positions": len(a.positions),
            "evidence": trade_evidence([t["pnl"] for t in sc]),
            "curve": curves[s][-300:],
            "trades": sf[-200:],
        }
    return results


def validate(quotes, cfg, *, source="RECORDED_PUBLIC_WS", train_fraction=0.70):
    if source not in (
        "RECORDED_PUBLIC_WS",
        "DECLARED_PUBLIC_CSV_UNVERIFIED",
        "SYNTHETIC_TEST",
    ):
        raise ValueError("La procedencia debe declararse expresamente")
    if not 0.55 <= train_fraction <= 0.85:
        raise ValueError("Separación train/test inválida")
    quotes = list(quotes)
    if not quotes or len({q.provider for q in quotes}) != 1:
        raise ValueError("Se necesita un único proveedor")
    if any(a.received_ts > b.received_ts for a, b in zip(quotes, quotes[1:])):
        raise ValueError("Datos desordenados; no se reordenan silenciosamente")
    moments = sorted({int(q.received_ts // cfg.sample_seconds) for q in quotes})
    if len(moments) < cfg.min_history * 3:
        raise ValueError(
            f"Historial insuficiente: se requieren al menos {cfg.min_history * 3} intervalos observados; hay {len(moments)}."
        )
    split_index = int(len(moments) * train_fraction)
    split_ts = moments[split_index] * cfg.sample_seconds
    training_quotes = [q for q in quotes if q.received_ts < split_ts]
    embargo = cfg.order_ttl_seconds + cfg.quote_max_age_seconds
    test_start = split_ts + embargo
    if quotes[-1].received_ts - test_start < cfg.min_history * cfg.sample_seconds / 2:
        raise ValueError("El periodo de prueba después del embargo es demasiado corto")
    training = replay(training_quotes, cfg)
    # Cash wins exact ties. Selection reads ONLY training results.
    selected = max(
        STRATEGIES,
        key=lambda s: (
            training[s]["net_return_pct"],
            -training[s]["max_drawdown_pct"],
            s == "cash",
        ),
    )
    holdout = replay(quotes, cfg, trade_start=test_start)
    btc = [q for q in quotes if q.symbol == "BTC-USD" and q.received_ts >= test_start]
    benchmark = None
    if len(btc) >= 2:
        fee = cfg.fee_bps[btc[0].provider] / 10000
        slip = cfg.slippage_bps / 10000
        qty = cfg.initial_capital / (btc[0].ask * (1 + slip) * (1 + fee))
        final = qty * btc[-1].bid * (1 - slip) * (1 - fee)
        benchmark = (final / cfg.initial_capital - 1) * 100
    report = {
        "source": source,
        "provider": quotes[0].provider,
        "strategy_version": VERSION,
        "train_start": iso(quotes[0].received_ts),
        "train_end": iso(training_quotes[-1].received_ts),
        "test_start": iso(test_start),
        "test_end": iso(quotes[-1].received_ts),
        "embargo_seconds": embargo,
        "observed_intervals": len(moments),
        "quotes": len(quotes),
        "selected_from_training": selected,
        "training": {
            s: {k: v for k, v in r.items() if k not in ("curve", "trades")}
            for s, r in training.items()
        },
        "holdout": holdout,
        "benchmark_100pct_net_return_pct": benchmark,
        "config": asdict(cfg),
        "limitations": [
            "Un solo split temporal no demuestra ventaja estadística; requiere más periodos y evaluación prospectiva.",
            "Quotes de nivel 1 muestreadas; sin cola real, profundidad completa ni garantía de ejecución.",
            "La cartera de prueba comienza en efectivo; usa historial pasado para calentar indicadores sin heredar posiciones.",
            "Benchmark BTC al 100 %: exposición y riesgo diferentes. No hay promoción automática a producción.",
        ],
    }
    json.dumps(report, allow_nan=False)
    return report


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(handle)
        quotes = []
        for row in rows:
            quotes.append(
                Quote(
                    provider=row["provider"],
                    symbol=row["symbol"],
                    exchange_ts=float(row["exchange_ts"]),
                    received_ts=float(row["received_ts"]),
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    bid_qty=float(row["bid_qty"]),
                    ask_qty=float(row["ask_qty"]),
                    sequence=int(row["sequence"]) if row.get("sequence") else None,
                    volume_24h=float(row["volume_24h"])
                    if row.get("volume_24h")
                    else None,
                    change_24h_pct=float(row["change_24h_pct"])
                    if row.get("change_24h_pct")
                    else None,
                )
            )
            if len(quotes) > 300_000:
                raise ValueError(
                    "CSV demasiado grande: máximo 300000 filas por experimento"
                )
        return quotes
