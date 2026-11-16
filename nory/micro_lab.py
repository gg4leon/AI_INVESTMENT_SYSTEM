"""Nory MicroLab v0.8: one shared fictitious USD account, seconds simulator.

This module NEVER contacts a broker or gets live market prices. A synthetic tick
is *not* a bid, offer, forecast, trading signal, verified news event, or fill.
A short-cycle statistical heuristic is stress-tested WITH all trading costs.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean, stdev

from app.markets import MARKET_BY_SYMBOL
from nory.micro_feed import SCENARIOS, SyntheticTick, synthesize_tick

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "nory_micro.sqlite3"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "BTC-USD", "ETH-USD")


@dataclass(frozen=True)
class MicroPolicy:
    initial_cash: float = 10_000.0
    max_total_exposure: float = 0.55
    max_asset_weight: float = 0.12
    max_sector_exposure: float = 0.30
    max_crypto_exposure: float = 0.12
    max_positions: int = 6
    fee_bps: float = 5.0
    spread_bps: float = 4.0
    slippage_bps: float = 2.0
    profit_target_net_bps: float = 18.0
    stop_loss_net_bps: float = 65.0
    drawdown_circuit_pct: float = 0.07
    z_buy_threshold: float = -1.35
    shock_return_threshold: float = -0.008
    systemic_drop_threshold: float = -0.005
    volatility_limit: float = 0.007
    min_history: int = 45
    min_hold_ticks: int = 3
    max_hold_ticks: int = 240
    cooldown_ticks: int = 8
    max_trades_per_60_ticks: int = 24

    def __post_init__(self):
        for field, v in asdict(self).items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"Invalid MicroPolicy {field}")
        if self.initial_cash <= 0 or not 1 <= self.max_positions <= 20:
            raise ValueError("Invalid initial_cash/max_positions")
        if not (0 < self.max_asset_weight <= self.max_total_exposure <= 1):
            raise ValueError("Invalid exposure constraints")
        if not all(0 < x <= 1 for x in (self.max_sector_exposure, self.max_crypto_exposure)):
            raise ValueError("Invalid category limits")
        if not all(0 <= x <= 200 for x in (self.fee_bps, self.spread_bps, self.slippage_bps)):
            raise ValueError("Invalid cost assumptions")
        if not (0 < self.profit_target_net_bps < 2000 and 0 < self.stop_loss_net_bps < 5000):
            raise ValueError("Invalid exit targets")
        if not (0 < self.drawdown_circuit_pct < 1 and -4 < self.z_buy_threshold < 0):
            raise ValueError("Invalid circuit/z-score")
        if not (-0.5 < self.shock_return_threshold < 0 and
                -0.5 < self.systemic_drop_threshold < 0 and
                0 < self.volatility_limit < 1):
            raise ValueError("Invalid volatility thresholds")
        if not 20 <= self.min_history <= 120 or not 1 <= self.min_hold_ticks < self.max_hold_ticks:
            raise ValueError("Invalid history/holding periods")
        if not 0 <= self.cooldown_ticks <= 120 or not 1 <= self.max_trades_per_60_ticks <= 120:
            raise ValueError("Invalid frequency guards")
        # A strategy seeking less than the cost of a round trip makes no sense.
        if self.profit_target_net_bps <= 0:
            raise ValueError("Net target must be positive")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_universe(symbols):
    if not symbols or len(symbols) > 20 or len(set(symbols)) != len(symbols):
        raise ValueError("Choose 1-20 distinct symbols")
    if "SPY" not in symbols:
        raise ValueError("Include SPY as an artificial broad market risk reference")
    for sym in symbols:
        m = MARKET_BY_SYMBOL.get(sym)
        if m is None or m.currency != "USD" or not m.paper_eligible:
            raise ValueError("MicroLab only supports fictitious USD-quoted tradable symbols")
    return tuple(sorted(symbols))


def _conn(db_path):
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS micro_state(
      id INTEGER PRIMARY KEY CHECK(id=1),
      paused INTEGER NOT NULL DEFAULT 1,
      halted INTEGER NOT NULL DEFAULT 0,
      tick INTEGER NOT NULL DEFAULT -1,
      universe_json TEXT,
      scenario TEXT,
      policy_json TEXT,
      cash REAL,
      equity REAL,
      peak REAL,
      updated_at TEXT
    );
    INSERT OR IGNORE INTO micro_state(id,paused,halted,tick) VALUES(1,1,0,-1);
    CREATE TABLE IF NOT EXISTS micro_ticks(
      tick INTEGER NOT NULL, symbol TEXT NOT NULL,
      virtual_time TEXT NOT NULL,
      mid REAL NOT NULL, event TEXT NOT NULL,
      PRIMARY KEY(tick,symbol)
    );
    CREATE INDEX IF NOT EXISTS micro_tick_symbol ON micro_ticks(symbol,tick DESC);
    CREATE TABLE IF NOT EXISTS micro_positions(
      symbol TEXT PRIMARY KEY, category TEXT NOT NULL,
      qty REAL NOT NULL, basis REAL NOT NULL,
      entry_fill REAL NOT NULL, entry_tick INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS micro_trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tick INTEGER NOT NULL, symbol TEXT NOT NULL,
      side TEXT NOT NULL, qty REAL NOT NULL,
      mid REAL NOT NULL, fill REAL NOT NULL, fee REAL NOT NULL,
      realized_pnl REAL NOT NULL, reason TEXT NOT NULL,
      cash_after REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS micro_pending(
      symbol TEXT PRIMARY KEY, side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
      decision_tick INTEGER NOT NULL, target_weight REAL NOT NULL,
      priority REAL NOT NULL, reason TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS micro_decisions(
      tick INTEGER NOT NULL, symbol TEXT NOT NULL,
      decision TEXT NOT NULL, score REAL,
      reason TEXT NOT NULL,
      PRIMARY KEY(tick,symbol)
    );
    CREATE TABLE IF NOT EXISTS micro_equity(
      tick INTEGER PRIMARY KEY, virtual_time TEXT NOT NULL,
      cash REAL NOT NULL, equity REAL NOT NULL, exposure_pct REAL NOT NULL,
      drawdown_pct REAL NOT NULL, positions INTEGER NOT NULL,
      halted INTEGER NOT NULL
    );
    """)
    return con


def is_paused(db_path=DEFAULT_DB):
    con = _conn(db_path)
    try:
        return bool(con.execute("SELECT paused FROM micro_state WHERE id=1").fetchone()["paused"])
    finally:
        con.close()


def set_paused(paused: bool, db_path=DEFAULT_DB):
    con = _conn(db_path)
    try:
        with con:
            con.execute("UPDATE micro_state SET paused=?,updated_at=? WHERE id=1",
                        (int(bool(paused)), _now()))
    finally:
        con.close()


def _costs(policy, mid, side):
    # Spread is a whole bid/ask spread in basis points, not a fee per side.
    half = policy.spread_bps / 20_000
    slip = policy.slippage_bps / 10_000
    return mid * (1 + half) * (1 + slip) if side == "BUY" else mid * (1 - half) * (1 - slip)


def _liquidation_value(policy, mid, qty):
    return qty * _costs(policy, mid, "SELL") * (1 - policy.fee_bps / 10_000)


def _positions(con):
    return {r["symbol"]: dict(r) for r in con.execute("SELECT * FROM micro_positions")}


def _prior_quotes(con, symbol, limit):
    rows = con.execute(
        "SELECT mid FROM micro_ticks WHERE symbol=? ORDER BY tick DESC LIMIT ?",
        (symbol, limit),
    ).fetchall()
    return [float(r["mid"]) for r in reversed(rows)]


def risk_assessment(symbol, current, previous, market_return, event, policy, correlated):
    """Screen a *relative price discount*, not an estimate of intrinsic value."""
    if len(previous) < policy.min_history:
        return ("WARMUP", 0.0, f"Waiting for {policy.min_history} preceding artificial ticks")
    window = previous[-policy.min_history:]
    level = mean(window)
    sigma_level = stdev(window)
    z = (current - level) / max(1e-9, sigma_level)
    prev_ret = current / previous[-1] - 1
    returns = [window[i] / window[i-1] - 1 for i in range(1, len(window))]
    volatility = stdev(returns)
    if event != "NO_CONFIRMED_NEWS_CONTEXT":
        return ("BLOCK_UNKNOWN_EVENT", z, f"Unexplained fabricated event: {event}; no verified cause")
    if prev_ret <= policy.shock_return_threshold:
        return ("BLOCK_SHOCK", z, f"Sudden price drop {prev_ret*100:.3f}% may have an unknown cause")
    if market_return <= policy.systemic_drop_threshold:
        return ("BLOCK_MARKET_STRESS", z, f"Artificial benchmark drop {market_return*100:.3f}%")
    if volatility > policy.volatility_limit:
        return ("BLOCK_VOLATILITY", z, f"Recent synthetic tick volatility {volatility*100:.3f}%")
    if correlated:
        return ("BLOCK_CORRELATION", z, "Similar exposure already in portfolio")
    if z >= policy.z_buy_threshold:
        return ("WAIT", z, f"Not sufficiently below trailing reference (z={z:.2f})")
    if prev_ret <= 0:
        return ("WAIT_FALLING", z, "Still falling: wait for evidence of rebound")
    return ("BUY_CANDIDATE", z, f"Below rolling mean (z={z:.2f}) and a positive synthetic tick; cause NOT verified")


def _category_used(positions, mid, category):
    return sum(p["qty"] * mid[p["symbol"]] for p in positions.values()
               if p["category"] == category)


def _corr(a, b):
    if len(a) < 35 or len(b) < 35:
        return 0.0
    ra = [a[i]/a[i-1]-1 for i in range(1,len(a))]
    rb = [b[i]/b[i-1]-1 for i in range(1,len(b))]
    ma, mb = mean(ra), mean(rb)
    covariance = sum((x-ma)*(y-mb) for x,y in zip(ra,rb))
    aa = sum((x-ma)**2 for x in ra)
    bb = sum((y-mb)**2 for y in rb)
    return covariance / math.sqrt(aa*bb) if aa>1e-15 and bb>1e-15 else 0.0


def process_second(
    symbols=DEFAULT_SYMBOLS, scenario="mixed", db_path=DEFAULT_DB,
    policy: MicroPolicy | None=None,
):
    cfg = policy or MicroPolicy()
    symbols = _validate_universe(tuple(symbols))
    if scenario not in SCENARIOS:
        raise ValueError("Unrecognized synthetic scenario")
    con = _conn(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM micro_state WHERE id=1").fetchone()
        if row["paused"]:
            con.rollback()
            return {"status":"PAUSED", "tick":row["tick"],"events":[]}
        if row["halted"]:
            con.rollback()
            return {"status":"CIRCUIT_HALTED","tick":row["tick"],"events":[]}
        if row["universe_json"] is not None:
            if json.loads(row["universe_json"]) != list(symbols) or row["scenario"] != scenario:
                raise ValueError("This demo account already has a fixed universe/scenario; use same selection")
            if json.loads(row["policy_json"]) != asdict(cfg):
                raise ValueError("Risk policy is locked for an existing session")
        seq = row["tick"] + 1
        cash = cfg.initial_cash if row["cash"] is None else float(row["cash"])
        peak = cfg.initial_cash if row["peak"] is None else float(row["peak"])
        positions = _positions(con)
        prior = {sym:_prior_quotes(con,sym,max(cfg.min_history,60)) for sym in symbols}
        prev_prices={sym:vals[-1] for sym,vals in prior.items() if vals}
        tick = synthesize_tick(seq,symbols,prev_prices,scenario)
        mids = tick.prices
        benchmark_prev = prior.get("SPY",[])
        market_return=(mids["SPY"]/benchmark_prev[-1]-1) if benchmark_prev else 0.
        events=[]
        outcomes={}
        # Liquidation-value equity avoids treating fee/spread as free profit.
        def snapshot():
            liquid=sum(
                _liquidation_value(cfg,mids[sym],pos["qty"])
                for sym,pos in positions.items()
            )
            return cash + liquid,liquid
        before_equity, _ = snapshot()
        # Resolve decisions from PRIOR synthetic seconds at the NEXT mid.
        # The current price was not known at decision time.
        pending=[dict(x) for x in con.execute(
            "SELECT * FROM micro_pending ORDER BY "
            "CASE side WHEN 'SELL' THEN 0 ELSE 1 END,priority DESC,symbol"
        )]
        outcomes={}
        recent_count=con.execute(
            "SELECT COUNT(*) FROM micro_trades WHERE tick>=?",(seq-59,)
        ).fetchone()[0]
        for order in pending:
            sym=order["symbol"]
            if order["decision_tick"]>=seq:
                continue
            pos=positions.get(sym)
            if order["side"]=="SELL" and pos:
                bid=_costs(cfg,mids[sym],"SELL")
                fee=pos["qty"]*bid*cfg.fee_bps/10000
                proceeds=pos["qty"]*bid-fee
                pnl=proceeds-pos["basis"]
                cash+=proceeds
                con.execute(
                    "INSERT INTO micro_trades(tick,symbol,side,qty,mid,fill,fee,realized_pnl,reason,cash_after)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (seq,sym,"SELL",pos["qty"],mids[sym],bid,fee,pnl,order["reason"],cash),
                )
                con.execute("DELETE FROM micro_positions WHERE symbol=?",(sym,))
                events.append({"symbol":sym,"event":"SELL_SIM","reason":order["reason"],
                               "net_pnl":round(pnl,4),"decision_tick":order["decision_tick"],
                               "fill_tick":seq})
                outcomes[sym]="EXIT_FILLED"
                del positions[sym]
                recent_count+=1
            elif order["side"]=="BUY" and not pos:
                reason=None
                if tick.events[sym]!="NO_CONFIRMED_NEWS_CONTEXT":
                    reason="UNKNOWN_EVENT_AT_FILL"
                elif market_return<=cfg.systemic_drop_threshold:
                    reason="MARKET_STRESS_AT_FILL"
                elif prior[sym] and mids[sym]/prior[sym][-1]-1<=cfg.shock_return_threshold:
                    reason="PRICE_SHOCK_AT_FILL"
                elif recent_count>=cfg.max_trades_per_60_ticks:
                    reason="TRADE_RATE_LIMIT"
                elif len(positions)>=cfg.max_positions:
                    reason="MAX_POSITIONS"
                if reason is None:
                    eq, exposed=snapshot()
                    cat=MARKET_BY_SYMBOL[sym].category
                    used=_category_used(positions,mids,cat)
                    budget=min(
                        cfg.max_asset_weight*eq,order["target_weight"]*eq,
                        max(0.,cfg.max_total_exposure*eq-exposed),
                        max(0.,cfg.max_sector_exposure*eq-used),cash
                    )
                    if cat=="Criptomonedas":
                        budget=min(budget,max(0.,cfg.max_crypto_exposure*eq-used))
                    if budget<50:
                        reason="INSUFFICIENT_RISK_BUDGET"
                if reason is None:
                    ask=_costs(cfg,mids[sym],"BUY")
                    qty=budget/(ask*(1+cfg.fee_bps/10000))
                    fee=qty*ask*cfg.fee_bps/10000
                    spent=qty*ask+fee
                    cash-=spent
                    positions[sym]=dict(
                        symbol=sym,category=cat,qty=qty,basis=spent,
                        entry_fill=ask,entry_tick=seq
                    )
                    con.execute(
                        "INSERT INTO micro_positions(symbol,category,qty,basis,entry_fill,entry_tick)"
                        " VALUES(?,?,?,?,?,?)",
                        (sym,cat,qty,spent,ask,seq)
                    )
                    con.execute(
                        "INSERT INTO micro_trades(tick,symbol,side,qty,mid,fill,fee,realized_pnl,reason,cash_after)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (seq,sym,"BUY",qty,mids[sym],ask,fee,0.,order["reason"],cash)
                    )
                    events.append({"symbol":sym,"event":"BUY_SIM","notional":round(spent,2),
                                   "decision_tick":order["decision_tick"],"fill_tick":seq})
                    outcomes[sym]="ENTRY_FILLED"
                    recent_count+=1
                else:
                    events.append({"symbol":sym,"event":"BUY_CANCELED","reason":reason})
            con.execute("DELETE FROM micro_pending WHERE symbol=?",(sym,))
        # Decide exits now but fill only on the next synthetic second.
        for sym in sorted(positions):
            pos=positions[sym]
            net=_liquidation_value(cfg,mids[sym],pos["qty"])
            pct=(net/pos["basis"]-1)*10000
            held=seq-pos["entry_tick"]
            reason=None
            if pct>=cfg.profit_target_net_bps and held>=cfg.min_hold_ticks:
                reason="NET_PROFIT_TARGET"
            elif pct<=-cfg.stop_loss_net_bps:
                reason="NET_STOP_LOSS"
            elif held>=cfg.max_hold_ticks:
                reason="MAX_HOLD_TIME"
            elif tick.events[sym]!="NO_CONFIRMED_NEWS_CONTEXT":
                reason="UNEXPLAINED_RISK_EXIT"
            if reason and sym not in outcomes:
                con.execute(
                    "INSERT OR IGNORE INTO micro_pending"
                    "(symbol,side,decision_tick,target_weight,priority,reason)"
                    "VALUES(?,?,?,?,?,?)",
                    (sym,"SELL",seq,0.,100.,reason)
                )
                events.append({"symbol":sym,"event":"SELL_PENDING",
                               "decision_tick":seq,"reason":reason})
        # All remaining candidate analysis uses only old quotes + THIS synthetic mid.
        candidates=[]
        trades_recent=con.execute(
            "SELECT COUNT(*) AS count FROM micro_trades WHERE tick>=?",
            (seq-59,),
        ).fetchone()["count"]
        for sym in symbols:
            current=mids[sym]
            category=MARKET_BY_SYMBOL[sym].category
            # A high past correlation with an existing position inhibits duplicative risk.
            correlated=False
            if sym not in positions and len(prior[sym])>=35:
                for owned in positions:
                    if owned!=sym and len(prior.get(owned,[]))>=35:
                        if _corr(prior[sym][-40:],prior[owned][-40:])>.92:
                            correlated=True
                            break
            code,z,detail=risk_assessment(
                sym,current,prior[sym],market_return,tick.events[sym],cfg,correlated
            )
            if sym in outcomes:
                code="EXIT_"+outcomes[sym][0]
            elif sym in positions:
                code="HOLD_POSITION"
            elif trades_recent>=cfg.max_trades_per_60_ticks:
                code="BLOCK_TRADE_LIMIT"
            else:
                latest_sell=con.execute(
                    "SELECT MAX(tick) as tick FROM micro_trades WHERE symbol=? AND side='SELL'",
                    (sym,),
                ).fetchone()["tick"]
                if latest_sell is not None and seq-latest_sell < cfg.cooldown_ticks:
                    code="BLOCK_COOLDOWN"
            # Require estimated cost-aware upside headroom to beat net objective.
            if code=="BUY_CANDIDATE":
                past_mean=mean(prior[sym][-cfg.min_history:])
                estimated_net=(past_mean/current-1)*10_000 - (
                    2*cfg.fee_bps+cfg.spread_bps+2*cfg.slippage_bps
                )
                if estimated_net < cfg.profit_target_net_bps*1.6:
                    code="BLOCK_COSTS"
                    detail=f"Estimated regression headroom {estimated_net:.1f} bps insufficient vs costs/target"
            if code=="BUY_CANDIDATE":
                returns=[
                    prior[sym][i]/prior[sym][i-1]-1
                    for i in range(max(1,len(prior[sym])-30),len(prior[sym]))
                ]
                volatility=stdev(returns) if len(returns)>1 else .01
                weight=.12 if volatility<.0016 else .075 if volatility<.0035 else .035
                if category=="Criptomonedas":
                    weight=min(weight,.055)
                candidates.append((volatility,z,sym,weight,detail))
            con.execute(
                "INSERT INTO micro_decisions(tick,symbol,decision,score,reason) VALUES(?,?,?,?,?)",
                (seq,sym,code,round(z,5),detail),
            )
        # Rank deterministic: lowest past volatility first, then deepest pullback.
        candidates.sort(key=lambda x:(x[0],x[1],x[2]))
        for volatility,z,sym,weight,detail in candidates:
            if sym in positions or len(positions)>=cfg.max_positions:
                continue
            equity_now,exposed=snapshot()
            category=MARKET_BY_SYMBOL[sym].category
            sector_used=_category_used(positions,mids,category)
            reserved=max(0.,cfg.max_total_exposure*equity_now-exposed)
            category_room=max(0.,cfg.max_sector_exposure*equity_now-sector_used)
            budget=min(
                cfg.max_asset_weight*equity_now, weight*equity_now,
                reserved, category_room, cash
            )
            if category=="Criptomonedas":
                budget=min(
                    budget,
                    max(0.,cfg.max_crypto_exposure*equity_now-sector_used),
                )
            if budget < 50:
                continue
            ask=_costs(cfg,mids[sym],"BUY")
            fee_ratio=cfg.fee_bps/10_000
            qty=budget/(ask*(1+fee_ratio))
            fee=qty*ask*fee_ratio
            spent=qty*ask+fee
            cash-=spent
            positions[sym]=dict(
                symbol=sym,category=category,qty=qty,basis=spent,
                entry_fill=ask,entry_tick=seq,
            )
            con.execute(
                "INSERT INTO micro_positions(symbol,category,qty,basis,entry_fill,entry_tick)"
                " VALUES(?,?,?,?,?,?)",
                (sym,category,qty,spent,ask,seq),
            )
            con.execute(
                "INSERT INTO micro_trades(tick,symbol,side,qty,mid,fill,fee,realized_pnl,reason,cash_after)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (seq,sym,"BUY",qty,mids[sym],ask,fee,0.,"MEAN_REVERSION_CANDIDATE",cash),
            )
            events.append({
                "symbol":sym,"event":"BUY_SIM",
                "notional":round(spent,2),
                "reason":"RELATIVE_PULLBACK_AFTER_BOUNCE_NOT_INTRINSIC_VALUE",
            })
        for sym in symbols:
            con.execute(
                "INSERT INTO micro_ticks(tick,symbol,virtual_time,mid,event)"
                " VALUES(?,?,?,?,?)",
                (seq,sym,tick.virtual_time,mids[sym],tick.events[sym]),
            )
        eq, invested=snapshot()
        peak=max(peak,eq)
        dd=(peak-eq)/peak if peak>0 else 0.
        halted=dd>=cfg.drawdown_circuit_pct
        con.execute(
            "UPDATE micro_state SET paused=CASE WHEN ? THEN 1 ELSE paused END,"
            "halted=?,tick=?,universe_json=?,scenario=?,policy_json=?,cash=?,equity=?,peak=?,updated_at=? WHERE id=1",
            (int(halted),int(halted),seq,json.dumps(list(symbols)),scenario,
             json.dumps(asdict(cfg),sort_keys=True),cash,eq,peak,_now()),
        )
        con.execute(
            "INSERT INTO micro_equity(tick,virtual_time,cash,equity,exposure_pct,"
            "drawdown_pct,positions,halted) VALUES(?,?,?,?,?,?,?,?)",
            (seq,tick.virtual_time,cash,eq,(invested/eq*100 if eq else 0),
             dd*100,len(positions),int(halted)),
        )
        con.commit()
        return dict(
            status="CIRCUIT_HALTED" if halted else "PROCESSED",
            source="SYNTHETIC_SECOND_FEED_ONLY",
            tick=seq, virtual_time=tick.virtual_time,
            cash=round(cash,2),equity=round(eq,2),
            exposure_pct=round((invested/eq*100 if eq else 0),2),
            drawdown_pct=round(dd*100,3),
            open_positions=len(positions),
            trades=events, scenario=scenario,
            caveat="ONE SYNTHETIC SECOND, NOT A MARKET DATA TICK OR A REAL TRADE",
        )
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def dashboard(db_path=DEFAULT_DB, history_limit=360):
    if not 1<=history_limit<=2000:
        raise ValueError("history_limit outside supported range")
    con=_conn(db_path)
    try:
        state=dict(con.execute("SELECT * FROM micro_state WHERE id=1").fetchone())
        positions=[dict(x) for x in con.execute("SELECT * FROM micro_positions ORDER BY symbol")]
        trades=[dict(x) for x in con.execute(
            "SELECT * FROM micro_trades ORDER BY id DESC LIMIT 60"
        )]
        decisions=[dict(x) for x in con.execute(
            "SELECT * FROM micro_decisions ORDER BY tick DESC,symbol LIMIT 60"
        )]
        equity=[dict(x) for x in con.execute(
            "SELECT * FROM micro_equity ORDER BY tick DESC LIMIT ?",(history_limit,)
        )][::-1]
        return {
            "source":"SYNTHETIC_SECOND_FEED_ONLY",
            "state":state,"positions":positions,"trades":trades,
            "decisions":decisions,"equity":equity,
            "notes":"No tick-level real feed. Only synthetic per-second scenarios, not investment predictions.",
        }
    finally:
        con.close()
