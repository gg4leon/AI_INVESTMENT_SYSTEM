"""Descriptive evidence, never a production strategy promotion rule."""

import math
import random
from statistics import mean


def trade_evidence(pnls, *, resamples=1000):
    """Circular moving-block bootstrap of completed-position net USD P/L.

    Retains short sequences of dependent trades. It does not remove selection
    bias, nonstationarity, size differences, survivorship or simulation error.
    """
    values = list(pnls)
    count = len(values)
    result = {
        "completed_positions": count,
        "mean_net_pnl_usd": mean(values) if values else None,
        "bootstrap_95_mean_usd": None,
        "positive_interval": False,
        "status": "INSUFFICIENT_SAMPLE",
        "method": "circular-moving-block-bootstrap",
        "note": "Describe cierres simulados y su incertidumbre; no prueba rentabilidad ni elimina sesgos de selección.",
    }
    if count < 20:
        return result
    block = max(2, int(math.sqrt(count)))
    rng = random.Random(2026)
    means = []
    for _ in range(resamples):
        sample = []
        while len(sample) < count:
            start = rng.randrange(count)
            sample.extend(values[(start + i) % count] for i in range(block))
        means.append(mean(sample[:count]))
    means.sort()
    lower, upper = means[int(resamples * 0.025)], means[int(resamples * 0.975)]
    result.update(
        bootstrap_95_mean_usd=[lower, upper],
        positive_interval=lower > 0,
        block_length=block,
        resamples=resamples,
        status="DESCRIPTIVE_ONLY",
    )
    return result
