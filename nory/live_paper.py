"""Prospective Kraken-quote paper ledger; real quotes, FICTITIOUS transactions.

Do not conflate observations with executions. Exchange bid/ask quantities
reflect only top-of-book and may be cancelled before hypothetical fills.
This implementation cannot submit orders or withdraw/deposit money.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean, stdev

from nory.kraken_public import PublicQuote, _parse_timestamp

LIVE_DB=Path(__file__).resolve().parents[1]/"data"/"nory_live_paper.sqlite3"
ALL_PAIRS=("BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD")


@dataclass(frozen=True)
class LivePolicy:
    initial_cash: float = 10_000.0
    max_exposure: float = .30
    max_asset_weight: float = .085
    max_positions: int = 4
    fee_bps_each_side: float = 80.0
    slippage_bps_each_side: float = 5.0
    max_spread_bps: float = 30.0
    profit_net_bps: float = 45.0
    stop_net_bps: float = 300.0
    portfolio_drawdown_kill: float = .06
    shock_return_threshold: float = -.006
    market_shock_threshold: float = -.008
    high_volatility_threshold: float = .010
    z_threshold: float = -1.25
    min_history: int = 45
    min_holding_seconds: int = 12
    order_expiration_seconds: int = 8
    cooldown_seconds: int = 30
    max_orders_per_60_seconds: int = 12
    max_quote_age_seconds: int = 10
    top_book_participation: float = .10

    def __post_init__(self):
        for name,val in asdict(self).items():
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val):
                raise ValueError("Invalid live policy: "+name)
        if self.initial_cash<=0 or not 1<=self.max_positions<=5 or not 20<=self.min_history<=150:
            raise ValueError("Invalid capital, positions or history")
        if not 0<self.max_asset_weight<=self.max_exposure<=.6:
            raise ValueError("Invalid allocation constraints")
        if not 0<self.portfolio_drawdown_kill<.5 or not 0<self.top_book_participation<=.25:
            raise ValueError("Invalid risk constraints")
        if not 0<=self.fee_bps_each_side<=300 or not 0<=self.slippage_bps_each_side<=100:
            raise ValueError("Invalid simulated costs")
        if not 0<self.max_spread_bps<=150 or not 0<self.profit_net_bps<3000 or not 0<self.stop_net_bps<5000:
            raise ValueError("Invalid spread/targets")
        if not 5<=self.min_holding_seconds<=3600 or not 1<=self.order_expiration_seconds<=30:
            raise ValueError("Invalid timing")
        if not 0<=self.cooldown_seconds<=3600 or not 1<=self.max_orders_per_60_seconds<=120:
            raise ValueError("Invalid order rate")


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(path):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(p,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS live_state (
      id INTEGER PRIMARY KEY CHECK(id=1),paused INTEGER NOT NULL DEFAULT 1,
      halted INTEGER NOT NULL DEFAULT 0,
      initial_cash REAL NOT NULL DEFAULT 10000,
      cash REAL NOT NULL DEFAULT 10000,
      equity REAL NOT NULL DEFAULT 10000,
      peak REAL NOT NULL DEFAULT 10000,
      last_cycle_at TEXT, last_status TEXT NOT NULL DEFAULT 'IDLE'
    );
    INSERT OR IGNORE INTO live_state(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS live_quotes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL,exchange_time TEXT NOT NULL,
      received_time TEXT NOT NULL,bid REAL NOT NULL,ask REAL NOT NULL,
      bid_qty REAL NOT NULL,ask_qty REAL NOT NULL,
      UNIQUE(symbol,exchange_time)
    );
    CREATE INDEX IF NOT EXISTS idx_live_quotes ON live_quotes(symbol,id DESC);
    CREATE TABLE IF NOT EXISTS live_positions(
      symbol TEXT PRIMARY KEY,quantity REAL NOT NULL,basis REAL NOT NULL,
      entry_ask REAL NOT NULL,opened_at TEXT NOT NULL,
      last_bid REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_orders(
      symbol TEXT PRIMARY KEY,side TEXT NOT NULL,decision_time TEXT NOT NULL,
      expires_at TEXT NOT NULL,reason TEXT NOT NULL, weight REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_fills(
      id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,side TEXT NOT NULL,
      decision_time TEXT NOT NULL,quote_time TEXT NOT NULL,qty REAL NOT NULL,
      price REAL NOT NULL,fee REAL NOT NULL,
      realized_pnl REAL NOT NULL,reason TEXT NOT NULL,
      cash_after REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_decisions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL,quote_time TEXT NOT NULL,
      decision TEXT NOT NULL,reason TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_equity(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      observed_at TEXT NOT NULL,cash REAL NOT NULL,
      equity REAL NOT NULL,drawdown_pct REAL NOT NULL,
      exposure_pct REAL NOT NULL,positions INTEGER NOT NULL
    );
    """)
    return db


def pause(paused=True,db_path=LIVE_DB):
    db=_connect(db_path)
    try:
        with db:
            db.execute("UPDATE live_state SET paused=? WHERE id=1",(int(bool(paused)),))
    finally:
        db.close()


def _positions(db):
    return {r["symbol"]:dict(r) for r in db.execute("SELECT * FROM live_positions")}


def _equity(cash,positions,quotes,policy):
    exposure=0.
    for symbol,pos in positions.items():
        quote=quotes.get(symbol)
        bid=quote.bid if quote is not None else pos["last_bid"]
        exposure+=pos["quantity"]*bid*(1-policy.slippage_bps_each_side/10000)*(1-policy.fee_bps_each_side/10000)
    return cash+exposure,exposure


def _history(db,symbol,limit=65):
    rows=db.execute(
        "SELECT (bid+ask)/2 AS mid FROM live_quotes WHERE symbol=? "
        "ORDER BY id DESC LIMIT ?",(symbol,limit)
    ).fetchall()
    return [float(r["mid"]) for r in reversed(rows)]


def _next_quote(db,symbol,when):
    row=db.execute("SELECT exchange_time FROM live_quotes WHERE symbol=? "
                   "ORDER BY id DESC LIMIT 1",(symbol,)).fetchone()
    return row is None or _parse_timestamp(when)>_parse_timestamp(row["exchange_time"])


def _log_decision(db,symbol,quote,code,reason):
    db.execute(
        "INSERT INTO live_decisions(symbol,quote_time,decision,reason) VALUES(?,?,?,?)",
        (symbol,quote.exchange_time,code,reason[:360])
    )


def _trade(db,symbol,side,order,quote,qty,fill,fee,pnl,cash):
    db.execute(
        "INSERT INTO live_fills(symbol,side,decision_time,quote_time,qty,price,fee,realized_pnl,reason,cash_after)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (symbol,side,order["decision_time"],quote.exchange_time,qty,fill,fee,pnl,order["reason"],cash),
    )


def _risk_decision(quote,history,btc_prev_return,policy):
    if len(history)<policy.min_history:
        return "WARMUP",f"Need {policy.min_history} separate genuine WS quotes"
    last=history[-1]
    change=quote.mid/last-1
    if change<=policy.shock_return_threshold:
        return "BLOCK_UNKNOWN_DROP",f"Unexplained sudden move {change*100:.3f}% (not confirmed by news)"
    if btc_prev_return<=policy.market_shock_threshold:
        return "BLOCK_MARKET_DROP",f"BTC market benchmark moved {btc_prev_return*100:.3f}%"
    if quote.spread_bps>policy.max_spread_bps:
        return "BLOCK_SPREAD",f"Quote spread {quote.spread_bps:.2f} bps"
    returns=[history[i]/history[i-1]-1 for i in range(1,len(history))]
    vol=stdev(returns[-30:]) if len(returns)>2 else 0
    if vol>policy.high_volatility_threshold:
        return "BLOCK_VOLATILITY",f"Recent genuine quote volatility {vol*100:.3f}%"
    avg=mean(history[-policy.min_history:])
    sigma=stdev(history[-policy.min_history:])
    z=(quote.mid-avg)/max(sigma,1e-10)
    if z>=policy.z_threshold:
        return "WAIT",f"Price not relatively depressed: z={z:.2f}"
    if change<=0:
        return "WAIT_FALLING",f"Possible falling knife: latest move {change*100:.3f}%"
    cost_bps=2*(policy.fee_bps_each_side+policy.slippage_bps_each_side)+quote.spread_bps
    headroom=(avg/quote.mid-1)*10000-cost_bps
    if headroom<policy.profit_net_bps*1.5:
        return "BLOCK_COSTS",f"Mean reversion headroom {headroom:.1f} bps after fees/spread"
    return "BUY_CANDIDATE",f"Experimental rebound, z={z:.2f}, modeled net headroom={headroom:.1f} bps"


def apply_real_quotes(
    quotes: dict[str,PublicQuote],
    db_path=LIVE_DB,
    policy:LivePolicy|None=None,
    now:datetime|None=None,
):
    cfg=policy or LivePolicy()
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Local clock must be timezone-aware")
    if not quotes:
        return {"status":"NO_FRESH_QUOTES","events":[]}
    if not isinstance(quotes,dict) or len(quotes)>len(ALL_PAIRS):
        raise ValueError("Invalid quote batch")
    valid={}
    for symbol,q in quotes.items():
        if symbol not in ALL_PAIRS or not isinstance(q,PublicQuote) or q.symbol!=symbol:
            raise ValueError("Only Kraken public USD spot quote objects allowed")
        if q.provider!="KRAKEN_PUBLIC_WS_V2":
            raise ValueError("Unverified quote provider")
        if (not all(math.isfinite(v) for v in (q.bid,q.ask,q.bid_qty,q.ask_qty))
            or q.bid<=0 or q.ask<=q.bid or q.bid_qty<=0 or q.ask_qty<=0
            or q.spread_bps>300):
            raise ValueError("Invalid or crossed quote book")
        if q.is_fresh(now=now,max_age_seconds=cfg.max_quote_age_seconds):
            valid[symbol]=q
    if "BTC-USD" not in valid:
        return {"status":"STALE_BENCHMARK","events":[]}
    db=_connect(db_path)
    events=[]
    try:
        db.execute("BEGIN IMMEDIATE")
        state=db.execute("SELECT * FROM live_state WHERE id=1").fetchone()
        if state["paused"] or state["halted"]:
            db.rollback()
            return {"status":"HALTED" if state["halted"] else "PAUSED","events":[]}
        cash=float(state["cash"])
        positions=_positions(db)
        missing_held=sorted(sym for sym in positions if sym not in valid)
        if missing_held:
            db.rollback()
            return {
                "status":"STALE_POSITION_QUOTES",
                "missing":missing_held,
                "events":[],
                "warning":"Position marks are stale. Paper trading must be paused; no fills are permitted.",
            }
        fresh={s:q for s,q in valid.items() if _next_quote(db,s,q.exchange_time)}
        if not fresh:
            db.rollback()
            return {"status":"WAITING_FOR_NEW_EXCHANGE_QUOTES","events":[]}
        btc_history=_history(db,"BTC-USD",2)
        btc_move=(fresh["BTC-USD"].mid/btc_history[-1]-1
                  if "BTC-USD" in fresh and btc_history else 0.)
        # Quote at end of this current update is not treated as a trade fill
        # until at least one later unique exchange timestamp arrives.
        previous={s:_history(db,s,cfg.min_history+3) for s in fresh}
        pending=[dict(x) for x in db.execute(
            "SELECT * FROM live_orders ORDER BY "
            "CASE side WHEN 'SELL' THEN 0 ELSE 1 END,symbol")]
        for order in pending:
            sym=order["symbol"]
            if sym not in fresh:
                continue
            q=fresh[sym]
            quote_t=_parse_timestamp(q.exchange_time)
            decision_t=_parse_timestamp(order["decision_time"])
            if quote_t<=decision_t:
                continue
            if now>_parse_timestamp(order["expires_at"]):
                db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
                events.append({"symbol":sym,"event":"EXPIRED","reason":"Quote arrived after TTL"})
                continue
            if q.spread_bps>cfg.max_spread_bps:
                events.append({"symbol":sym,"event":"WAIT_SPREAD"})
                continue
            pos=positions.get(sym)
            side=order["side"]
            if side=="SELL" and pos:
                qty=min(pos["quantity"],q.bid_qty*cfg.top_book_participation)
                if qty>0:
                    fill=q.bid*(1-cfg.slippage_bps_each_side/10000)
                    gross=qty*fill
                    fee=gross*cfg.fee_bps_each_side/10000
                    allocated_basis=pos["basis"]*qty/pos["quantity"]
                    pnl=gross-fee-allocated_basis
                    cash+=gross-fee
                    _trade(db,sym,side,order,q,qty,fill,fee,pnl,cash)
                    remain=pos["quantity"]-qty
                    if remain<=1e-12:
                        positions.pop(sym)
                        db.execute("DELETE FROM live_positions WHERE symbol=?",(sym,))
                        db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
                    else:
                        pos["quantity"]=remain
                        pos["basis"]-=allocated_basis
                        pos["last_bid"]=q.bid
                        db.execute("UPDATE live_positions SET quantity=?,basis=?,last_bid=? WHERE symbol=?",
                                   (remain,pos["basis"],q.bid,sym))
                    events.append({"symbol":sym,"event":"SELL_PAPER",
                                   "partial":remain>1e-12,"pnl":round(pnl,3)})
            elif side=="BUY" and not pos:
                if btc_move<=cfg.market_shock_threshold:
                    events.append({"symbol":sym,"event":"BUY_VETO","reason":"Market stress on fill"})
                    db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
                    continue
                last_prices=previous.get(sym,[])
                jump=q.mid/last_prices[-1]-1 if last_prices else 0.
                if jump<=cfg.shock_return_threshold:
                    events.append({"symbol":sym,"event":"BUY_VETO","reason":"Unknown sudden drop at fill"})
                    db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
                    continue
                eq,exposure=_equity(cash,positions,valid,cfg)
                budget=min(cash,cfg.max_asset_weight*eq,order["weight"]*eq,
                           max(0.,cfg.max_exposure*eq-exposure))
                fill=q.ask*(1+cfg.slippage_bps_each_side/10000)
                budget=min(budget,q.ask_qty*cfg.top_book_participation*fill)
                if budget>=30 and len(positions)<cfg.max_positions:
                    qty=budget/(fill*(1+cfg.fee_bps_each_side/10000))
                    gross=qty*fill
                    fee=gross*cfg.fee_bps_each_side/10000
                    spent=gross+fee
                    cash-=spent
                    positions[sym]=dict(symbol=sym,quantity=qty,basis=spent,
                                        entry_ask=fill,opened_at=q.exchange_time,last_bid=q.bid)
                    db.execute(
                        "INSERT INTO live_positions(symbol,quantity,basis,entry_ask,opened_at,last_bid)"
                        " VALUES(?,?,?,?,?,?)",
                        (sym,qty,spent,fill,q.exchange_time,q.bid)
                    )
                    _trade(db,sym,side,order,q,qty,fill,fee,0.,cash)
                    events.append({"symbol":sym,"event":"BUY_PAPER","notional":round(spent,2)})
                else:
                    events.append({"symbol":sym,"event":"BUY_VETO","reason":"Not enough risk budget/depth"})
                db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
            else:
                db.execute("DELETE FROM live_orders WHERE symbol=?",(sym,))
        for sym,pos in positions.items():
            if sym in valid:
                pos["last_bid"]=valid[sym].bid
                db.execute("UPDATE live_positions SET last_bid=? WHERE symbol=?",
                           (pos["last_bid"],sym))
        eq,exposure=_equity(cash,positions,valid,cfg)
        peak=max(eq,float(state["peak"]))
        dd=(peak-eq)/peak
        halt=dd>=cfg.portfolio_drawdown_kill
        if halt:
            db.execute("DELETE FROM live_orders WHERE side='BUY'")
            events.append({"event":"CIRCUIT_BREAKER","reason":"Portfolio paper drawdown limit"})

        order_count=db.execute(
            "SELECT COUNT(*) FROM live_fills WHERE quote_time >= ?",
            ((now-timedelta(seconds=60)).isoformat(),)
        ).fetchone()[0]
        for sym,q in sorted(fresh.items()):
            history=previous.get(sym,[])
            code,reason=_risk_decision(q,history,btc_move,cfg)
            active_order=db.execute("SELECT side FROM live_orders WHERE symbol=?",(sym,)).fetchone()
            if sym in positions:
                pos=positions[sym]
                liquid=pos["quantity"]*q.bid*(1-cfg.slippage_bps_each_side/10000)*(1-cfg.fee_bps_each_side/10000)
                pnl_bps=(liquid/pos["basis"]-1)*10000
                held=(now-_parse_timestamp(pos["opened_at"])).total_seconds()
                if (pnl_bps>=cfg.profit_net_bps and held>=cfg.min_holding_seconds):
                    exit_reason=f"Net PnL after costs={pnl_bps:.1f}bps (target)"
                elif pnl_bps<=-cfg.stop_net_bps:
                    exit_reason=f"Net loss after costs={pnl_bps:.1f}bps (stop)"
                else:
                    exit_reason=None
                if exit_reason and not active_order:
                    db.execute("INSERT INTO live_orders(symbol,side,decision_time,expires_at,reason,weight)"
                               " VALUES(?,?,?,?,?,?)",
                               (sym,"SELL",q.exchange_time,(now+timedelta(seconds=cfg.order_expiration_seconds)).isoformat(),
                                exit_reason,0.))
                    code="SELL_PENDING"
                    events.append({"symbol":sym,"event":"SELL_PENDING"})
                elif active_order:
                    code="ORDER_PENDING"
                else:
                    code="HOLD_POSITION"
            elif active_order:
                code="ORDER_PENDING"
            elif not halt and code=="BUY_CANDIDATE":
                last=db.execute("SELECT quote_time FROM live_fills WHERE symbol=? AND side='SELL'"
                                " ORDER BY id DESC LIMIT 1",(sym,)).fetchone()
                cooled=last and (now-_parse_timestamp(last["quote_time"])).total_seconds()<cfg.cooldown_seconds
                if cooled:
                    code="BLOCK_COOLDOWN"
                elif order_count>=cfg.max_orders_per_60_seconds:
                    code="BLOCK_ORDER_RATE"
                elif len(positions)>=cfg.max_positions:
                    code="BLOCK_MAX_POSITIONS"
                else:
                    db.execute("INSERT INTO live_orders(symbol,side,decision_time,expires_at,reason,weight)"
                               " VALUES(?,?,?,?,?,?)",
                               (sym,"BUY",q.exchange_time,(now+timedelta(seconds=cfg.order_expiration_seconds)).isoformat(),
                                reason,cfg.max_asset_weight))
                    code="BUY_PENDING"
                    events.append({"symbol":sym,"event":"BUY_PENDING"})
            elif halt:
                code="BLOCK_PORTFOLIO_DRAWDOWN"
            _log_decision(db,sym,q,code,reason)
            db.execute(
                "INSERT INTO live_quotes(symbol,exchange_time,received_time,bid,ask,bid_qty,ask_qty)"
                " VALUES(?,?,?,?,?,?,?)",
                (sym,q.exchange_time,q.received_time,q.bid,q.ask,q.bid_qty,q.ask_qty)
            )
        eq,exposure=_equity(cash,positions,valid,cfg)
        peak=max(peak,eq)
        dd=(peak-eq)/peak
        db.execute("UPDATE live_state SET cash=?,equity=?,peak=?,paused=?,halted=?,"
                   "last_cycle_at=?,last_status=? WHERE id=1",
                   (cash,eq,peak,int(halt),int(halt),now.isoformat(),
                    "HALTED" if halt else "PROCESSING"))
        db.execute("INSERT INTO live_equity(observed_at,cash,equity,drawdown_pct,"
                   "exposure_pct,positions) VALUES(?,?,?,?,?,?)",
                   (now.isoformat(),cash,eq,dd*100,exposure/eq*100 if eq>0 else 0.,len(positions)))
        db.commit()
        return {"status":"HALTED" if halt else "PROCESSED",
                "source":"KRAKEN_REAL_BID_ASK_PAPER_ONLY",
                "quotes_processed":sorted(fresh),"events":events,
                "cash":round(cash,2),"equity":round(eq,2),"exposure_pct":round(exposure/eq*100,2),
                "warning":"Bid/ask real, FILLS FICTICIOS, profundidad y ejecución no garantizadas"}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dashboard(db_path=LIVE_DB, limit=240):
    if not 1<=limit<=1000:
        raise ValueError("Invalid limit")
    db=_connect(db_path)
    try:
        state=dict(db.execute("SELECT * FROM live_state WHERE id=1").fetchone())
        def get_rows(sql,args=()):
            return [dict(x) for x in db.execute(sql,args)]
        return {
            "source":"KRAKEN_REAL_BID_ASK_PAPER_ONLY",
            "state":state,
            "positions":get_rows("SELECT * FROM live_positions ORDER BY symbol"),
            "pending":get_rows("SELECT * FROM live_orders ORDER BY symbol"),
            "fills":get_rows("SELECT * FROM live_fills ORDER BY id DESC LIMIT ?",(limit,)),
            "decisions":get_rows("SELECT * FROM live_decisions ORDER BY id DESC LIMIT ?",(limit,)),
            "equity":list(reversed(get_rows("SELECT * FROM live_equity ORDER BY id DESC LIMIT ?",(limit,)))),
        }
    finally:
        db.close()
