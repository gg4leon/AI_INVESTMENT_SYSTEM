"""Backtesting reproducible: señales al cierre t-1; ejecuciones a la apertura t.

Solo simula posiciones largas y efectivo. No puede enviar órdenes a un bróker.
"""
from dataclasses import asdict, dataclass
import math
import pandas as pd

from analysis.signal_engine import REQUIRED, SignalConfig, generate_signal


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    allocation_fraction: float = 0.25
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    stop_loss_pct: float = 0.08
    warmup_bars: int = 50

    def __post_init__(self) -> None:
        for name in ("initial_cash", "allocation_fraction", "fee_bps",
                     "slippage_bps", "stop_loss_pct"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} debe ser un numero finito")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash debe ser > 0")
        if not 0 < self.allocation_fraction <= 1:
            raise ValueError("allocation_fraction debe estar en (0, 1]")
        if not 0 <= self.fee_bps < 10_000 or not 0 <= self.slippage_bps < 10_000:
            raise ValueError("fee_bps/slippage_bps deben estar en [0, 10000)")
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct debe estar en (0, 1)")
        if not isinstance(self.warmup_bars, int) or self.warmup_bars < 35:
            raise ValueError("warmup_bars debe ser un entero >= 35")


@dataclass
class BacktestResult:
    symbol: str
    config: BacktestConfig
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    initial_cash: float
    final_equity: float
    total_return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    annualized_volatility_pct: float
    sharpe_zero_rf: float | None
    closed_trades: int
    win_rate_pct: float | None
    exposure_pct: float
    open_position: bool
    start: str
    end: str

    def summary(self) -> dict:
        """JSON serializable: no timestamps/numpy scalars."""
        return {
            "symbol": self.symbol,
            "mode": "HISTORICAL_PAPER_ONLY",
            "config": asdict(self.config),
            "start": self.start, "end": self.end,
            "initial_cash": round(self.initial_cash, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return_pct, 3),
            "benchmark_return_pct_gross": round(self.benchmark_return_pct, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "annualized_volatility_pct": round(self.annualized_volatility_pct, 3),
            "sharpe_zero_rf": (round(self.sharpe_zero_rf, 3)
                               if self.sharpe_zero_rf is not None else None),
            "closed_trades": self.closed_trades,
            "win_rate_pct": (round(self.win_rate_pct, 2)
                             if self.win_rate_pct is not None else None),
            "market_exposure_pct": round(self.exposure_pct, 2),
            "open_position": self.open_position,
            "notes": [
                "La senal se calcula solo con velas anteriores; orden simulada a siguiente apertura.",
                "Comisiones y deslizamiento se aplican por lado.",
                "Stop basado en cierre previo; se ejecuta a apertura siguiente y puede sufrir gaps.",
                "Posicion abierta se valora al ultimo cierre sin restar un costo de salida futuro.",
                "Benchmark comprar/mantener bruto, sin costos, desde fin de calentamiento.",
                "Sin interes sobre efectivo, impuestos, spreads variables, dividendos separados ni margen.",
                "Backtest historico NO indica rentabilidad futura ni permite ejecutar dinero real.",
            ],
        }


def run_backtest(
    analyzed: pd.DataFrame,
    symbol: str,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    if not isinstance(analyzed, pd.DataFrame):
        raise ValueError("Se requiere un DataFrame")
    if len(analyzed) <= cfg.warmup_bars:
        raise ValueError(f"Se requieren mas de {cfg.warmup_bars} velas")
    required = ("Open",) + REQUIRED
    missing = [col for col in required if col not in analyzed.columns]
    if missing:
        raise ValueError("Columnas faltantes: " + ", ".join(missing))
    if not analyzed.index.is_unique or not analyzed.index.is_monotonic_increasing:
        raise ValueError("El indice debe ser unico y cronologico")

    prices = analyzed.loc[:, ["Open", "Close"]].apply(pd.to_numeric, errors="coerce")
    if not prices.notna().all().all():
        raise ValueError("Aperturas/cierres contienen valores nulos")
    if not (prices > 0).all().all():
        raise ValueError("Aperturas/cierres deben ser positivos")
    if not prices.map(math.isfinite).all().all():
        raise ValueError("Aperturas/cierres deben ser finitos")

    signal_cfg = SignalConfig(min_bars=cfg.warmup_bars)
    fee = cfg.fee_bps / 10_000
    slip = cfg.slippage_bps / 10_000
    cash = cfg.initial_cash
    qty = 0.0
    entry_price = 0.0
    entry_spend = 0.0
    entry_time = ""
    entry_decision = ""
    equity_rows = [{
        "timestamp": str(analyzed.index[cfg.warmup_bars - 1]),
        "equity": cash, "cash": cash, "qty": 0.0,
        "close": float(prices["Close"].iloc[cfg.warmup_bars - 1]),
        "action": "WARMUP", "signal": "SIN_SENAL",
    }]
    trades = []

    for i in range(cfg.warmup_bars, len(analyzed)):
        # La decision del dia i solo observa el historial hasta i-1.
        previous = analyzed.iloc[:i]
        report = generate_signal(previous, symbol, signal_cfg)
        open_px = float(prices["Open"].iloc[i])
        close_px = float(prices["Close"].iloc[i])
        now = str(analyzed.index[i])
        decision_time = str(analyzed.index[i - 1])
        action = "HOLD"

        stop_triggered = (qty > 0 and
                          float(prices["Close"].iloc[i - 1]) <=
                          entry_price * (1 - cfg.stop_loss_pct))
        should_sell = qty > 0 and (stop_triggered or report.signal == "CANDIDATO_VENTA")
        if should_sell:
            fill = open_px * (1 - slip)
            gross = qty * fill
            exit_fee = gross * fee
            net_proceeds = gross - exit_fee
            cash += net_proceeds
            pnl = net_proceeds - entry_spend
            trades.append({
                "entry_decision": entry_decision, "entry_time": entry_time,
                "exit_decision": decision_time, "exit_time": now,
                "entry_price": entry_price, "exit_price": fill,
                "quantity": qty, "spent_with_fee": entry_spend,
                "net_proceeds": net_proceeds, "pnl": pnl,
                "return_pct": (net_proceeds / entry_spend - 1) * 100,
                "exit_reason": "STOP_CLOSE_PREV" if stop_triggered else "SIGNAL",
            })
            qty, entry_price, entry_spend = 0.0, 0.0, 0.0
            entry_time, entry_decision = "", ""
            action = "EXIT_LONG"
        elif qty == 0 and report.signal == "CANDIDATO_COMPRA":
            budget = cash * cfg.allocation_fraction
            fill = open_px * (1 + slip)
            # La tarifa de entrada debe pagarse del presupuesto disponible.
            bought_qty = budget / (fill * (1 + fee))
            spent = bought_qty * fill * (1 + fee)
            if bought_qty > 0:
                cash -= spent
                qty, entry_price, entry_spend = bought_qty, fill, spent
                entry_time, entry_decision = now, decision_time
                action = "ENTER_LONG"

        equity_rows.append({
            "timestamp": now,
            "equity": cash + qty * close_px,
            "cash": cash, "qty": qty,
            "close": close_px, "action": action,
            "signal": report.signal,
        })

    equity = pd.DataFrame.from_records(equity_rows).set_index("timestamp")
    ledger = pd.DataFrame.from_records(trades)
    net = equity["equity"].pct_change().dropna()
    high = equity["equity"].cummax()
    dd = float(((equity["equity"] / high) - 1).min() * 100)
    periods_year = 365 if symbol == "BTC-USD" else 252
    stdev = float(net.std(ddof=1)) if len(net) >= 2 else float("nan")
    volatility = stdev * math.sqrt(periods_year) * 100 if math.isfinite(stdev) else 0.0
    sharpe = (float(net.mean()) / stdev * math.sqrt(periods_year)
              if math.isfinite(stdev) and stdev > 0 else None)

    wins = sum(t["pnl"] > 0 for t in trades)
    win_rate = (wins / len(trades) * 100) if trades else None
    final = float(equity["equity"].iloc[-1])
    close_start = float(prices["Close"].iloc[cfg.warmup_bars - 1])
    close_end = float(prices["Close"].iloc[-1])
    return BacktestResult(
        symbol=symbol, config=cfg, equity_curve=equity, trades=ledger,
        initial_cash=cfg.initial_cash, final_equity=final,
        total_return_pct=(final / cfg.initial_cash - 1) * 100,
        benchmark_return_pct=(close_end / close_start - 1) * 100,
        max_drawdown_pct=dd, annualized_volatility_pct=volatility,
        sharpe_zero_rf=sharpe, closed_trades=len(trades),
        win_rate_pct=win_rate,
        exposure_pct=float((equity["qty"] > 0).mean() * 100),
        open_position=qty > 0,
        start=str(analyzed.index[cfg.warmup_bars - 1]),
        end=str(analyzed.index[-1]),
    )
