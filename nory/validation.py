"""Nory v1.0: fee-aware rolling historical validation with untouched holdout.

The selection is based ONLY on earlier training candles. Every order's decision
uses information available at previous close, fill at next open. The benchmark
is single-asset 100% invested and NOT risk-matched to the 30%-exposed strategy.
No financial orders are submitted. Yahoo history can contain adjustments.
"""
from dataclasses import asdict,dataclass
import math
import pandas as pd

STRATEGIES=("TREND","MEAN_REVERSION","CASH")


@dataclass(frozen=True)
class ValidationConfig:
    capital: float = 10000.
    train_fraction: float = .70
    allocation: float = .30
    fee_bps_each_side: float = 60.
    slippage_bps_each_side: float = 5.

    def __post_init__(self):
        if not all(math.isfinite(x) for x in asdict(self).values()):
            raise ValueError("Parameters must be finite")
        if not self.capital>0 or not .55<=self.train_fraction<=.85:
            raise ValueError("Bad initial capital/train split")
        if not 0<self.allocation<=1:
            raise ValueError("Bad allocation")
        if not 0<=self.fee_bps_each_side<=300 or not 0<=self.slippage_bps_each_side<=150:
            raise ValueError("Bad costs")


def _clean(data):
    if not isinstance(data,pd.DataFrame) or len(data)<150:
        raise ValueError("Need at least 150 real historical daily candles")
    if not all(c in data.columns for c in ("Open","Close")):
        raise ValueError("Open/Close columns are required")
    clean=data[["Open","Close"]].copy()
    clean=clean.apply(pd.to_numeric,errors="coerce").dropna()
    if len(clean)<150 or clean.isna().any().any() or (clean<=0).any().any():
        raise ValueError("Bad daily prices")
    if not clean.index.is_unique or not clean.index.is_monotonic_increasing:
        raise ValueError("Duplicate/out-of-order dates")
    clean["sma10"]=clean["Close"].rolling(10).mean()
    clean["sma30"]=clean["Close"].rolling(30).mean()
    clean["sigma30"]=clean["Close"].rolling(30).std()
    clean["z30"]=(clean["Close"]-clean["sma30"])/clean["sigma30"].clip(lower=1e-9)
    return clean


def _signal(frame, index, strategy, in_position):
    """Decision as of previous day close; index denotes next open to fill."""
    if strategy=="CASH":
        return "WAIT"
    old=frame.iloc[index-1]
    older=frame.iloc[index-2]
    if strategy=="TREND":
        if in_position:
            return "EXIT" if old.sma10<old.sma30 or old.Close<old.sma30 else "HOLD"
        return "BUY" if old.sma10>old.sma30 and old.Close>old.sma30 else "WAIT"
    if in_position:
        return "EXIT" if old.z30>=0 or old.Close<old.sma30*.95 else "HOLD"
    return "BUY" if old.z30< -1.2 and old.Close>older.Close else "WAIT"


def _simulate(frame,start,end,strategy,cfg):
    if strategy not in STRATEGIES or not 30<=start<end<=len(frame):
        raise ValueError("Invalid historical experiment boundaries")
    cash=float(cfg.capital)
    qty=0.
    basis=0.
    realized=0.
    trades=[]
    curve=[]
    peak=cfg.capital
    dd=0.
    for i in range(start,end):
        open_price=float(frame["Open"].iloc[i])
        close=float(frame["Close"].iloc[i])
        signal=_signal(frame,i,strategy,qty>0)
        timestamp=str(frame.index[i])
        action="HOLD"
        if qty>0 and signal=="EXIT":
            fill=open_price*(1-cfg.slippage_bps_each_side/10000)
            fee=qty*fill*cfg.fee_bps_each_side/10000
            proceeds=qty*fill-fee
            cash+=proceeds
            realized+=proceeds-basis
            trades.append({
                "date":timestamp,"side":"SELL","price":fill,
                "quantity":qty,"fee":fee,"realized_pnl":proceeds-basis,
                "signal_used_from":"PRIOR_CLOSED_DAY"
            })
            qty=0.
            basis=0.
            action="SELL_SIM"
        elif qty==0 and signal=="BUY":
            spend=cash*cfg.allocation
            fill=open_price*(1+cfg.slippage_bps_each_side/10000)
            qty=spend/(fill*(1+cfg.fee_bps_each_side/10000))
            fee=qty*fill*cfg.fee_bps_each_side/10000
            basis=qty*fill+fee
            cash-=basis
            trades.append({
                "date":timestamp,"side":"BUY","price":fill,
                "quantity":qty,"fee":fee,"realized_pnl":0.,
                "signal_used_from":"PRIOR_CLOSED_DAY"
            })
            action="BUY_SIM"
        equity=cash+qty*close*(1-cfg.slippage_bps_each_side/10000)*(1-cfg.fee_bps_each_side/10000)
        peak=max(peak,equity)
        dd=max(dd,(peak-equity)/peak*100)
        curve.append({"date":timestamp,"equity":equity,"action":action})
    last=curve[-1]["equity"]
    fees=sum(x["fee"] for x in trades)
    return {
        "strategy":strategy,
        "final_equity":last,
        "return_pct":(last/cfg.capital-1)*100,
        "max_drawdown_pct":dd,
        "buys":sum(x["side"]=="BUY" for x in trades),
        "sells":sum(x["side"]=="SELL" for x in trades),
        "realized_net_pnl":realized,
        "recorded_fees":fees,
        "curve":curve,
        "trades":trades,
    }


def validate_out_of_sample(data,config:ValidationConfig|None=None):
    cfg=config or ValidationConfig()
    frame=_clean(data)
    split=int(len(frame)*cfg.train_fraction)
    if split<60 or len(frame)-split<30:
        raise ValueError("Holdout too short")
    train={s:_simulate(frame,30,split,s,cfg) for s in STRATEGIES}
    # A cash strategy is a legitimate winner if all active choices fail.
    candidate=max(STRATEGIES,key=lambda s:(train[s]["final_equity"],-STRATEGIES.index(s)))
    holdout={s:_simulate(frame,split,len(frame),s,cfg) for s in STRATEGIES}
    benchmark_first=float(frame["Open"].iloc[split])
    benchmark_last=float(frame["Close"].iloc[-1])
    # Fully invested baseline with both entry and exit costs, distinct exposure.
    buy=benchmark_first*(1+cfg.slippage_bps_each_side/10000)
    shares=cfg.capital/(buy*(1+cfg.fee_bps_each_side/10000))
    gross=shares*benchmark_last*(1-cfg.slippage_bps_each_side/10000)
    net_benchmark=gross*(1-cfg.fee_bps_each_side/10000)
    result={
        "source":"HISTORICAL_YAHOO_OOS_NOT_REALTIME",
        "symbol":None,
        "dates":{
            "train_start":str(frame.index[30]),
            "train_end":str(frame.index[split-1]),
            "holdout_start":str(frame.index[split]),
            "holdout_end":str(frame.index[-1]),
        },
        "train_size":split-30,"holdout_size":len(frame)-split,
        "chosen_from_train_only":candidate,
        "all_training_summaries":[{
            "strategy":s,
            "return_pct":train[s]["return_pct"],
            "max_drawdown_pct":train[s]["max_drawdown_pct"],
            "closed_sells":train[s]["sells"],
        } for s in STRATEGIES],
        "holdout_results":holdout,
        "chosen_holdout":holdout[candidate],
        "benchmark_100pct_buy_hold_net_pct":(net_benchmark/cfg.capital-1)*100,
        "limitations":(
            "Daily historical candles, next open after prior close signal; "
            "adjusted Yahoo quotes, hypothetical fills, constant assumed costs, "
            "one holdout split; benchmark 100% exposure vs 30% strategy."
        ),
        "parameters":asdict(cfg),
    }
    return result
