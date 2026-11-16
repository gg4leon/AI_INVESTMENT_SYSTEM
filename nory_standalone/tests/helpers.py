from dataclasses import replace
import math

from nory_standalone.nory.config import Config
from nory_standalone.nory.models import Quote

T = 1_790_000_000.0


def config(**kwargs):
    changes = {
        "min_history": 35,
        "analysis_interval_seconds": kwargs.get("sample_seconds", 1),
        "analysis_lookback": 120,
    }
    return replace(Config(), **{**changes, **kwargs})


def quote(t=0, mid=100.0, symbol="BTC-USD", provider="coinbase", qty=10000, **kwargs):
    return Quote(
        provider,
        symbol,
        T + t,
        T + t,
        mid * 0.9999,
        mid * 1.0001,
        qty,
        qty,
        sequence=int(t * 100) + 1001 if provider == "coinbase" else None,
        volume_24h=1_000_000,
        **kwargs,
    )


def scenario(kind="sideways", seconds=700):
    """FABRICATED unit-test quotes; never passed off as a connectivity test."""
    out = []
    for i in range(seconds):
        drift = 0.0006 * i if kind == "bull" else -0.0006 * i if kind == "bear" else 0.0
        mid = 100 * math.exp(drift + 0.008 * math.sin(i * 0.18))
        out.append(quote(i, mid))
    return out
