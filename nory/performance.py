"""AIS v1.0 Performance Center — explainable, fee-aware PAPER metrics.

Does not forecast returns. Never combines synthetic and real accounts.
BTC benchmark is hypothetical 100% buy/hold, NOT risk/exposure matched.
All queries are local SQLite and work offline.
"""
from collections import Counter,defaultdict
from dataclasses import dataclass,asdict
from pathlib import Path
import math
import sqlite3

from nory.live_paper import LIVE_DB,COINBASE_LIVE_DB
from nory.micro_lab import DEFAULT_DB as SYNTHETIC_DB


@dataclass(frozen=True)
class PerformanceStats:
    source: str
    cash: float
    equity: float
    return_pct: float
    starting_capital: float
    closed_sells: int
    simulated_buys: int
    wins: int
    losses: int
    win_rate_pct: float | None
    realized_net_pnl: float
    estimated_open_pnl: float
    total_fees: float
    max_drawdown_pct: float
    average_exposure_pct: float
    peak_exposure_pct: float
    observations: int
    distinct_assets: int
    benchmark_btc_gross_pct: float | None
    benchmark_note: str

    def as_dict(self):
        return asdict(self)


def _read_rows(con, query,params=()):
    return [dict(x) for x in con.execute(query,params)]


def summarize_live(db_path=LIVE_DB, source="KRAKEN"):
    if source not in ("KRAKEN","COINBASE"):
        raise ValueError("Unknown paper data source")
    path=Path(db_path)
    if not path.exists():
        return {"available":False,"source":source,"reason":"No prospective quotes recorded yet"}
    con=sqlite3.connect(path,timeout=10)
    con.row_factory=sqlite3.Row
    try:
        state=con.execute("SELECT * FROM live_state WHERE id=1").fetchone()
        if state is None:
            return {"available":False,"source":source,"reason":"Empty paper account"}
        fills=_read_rows(con,"SELECT * FROM live_fills ORDER BY id DESC")
        decisions=_read_rows(con,"SELECT decision,reason,symbol,quote_time FROM live_decisions ORDER BY id DESC LIMIT 2000")
        equity=_read_rows(con,"SELECT * FROM live_equity ORDER BY id ASC")
        positions=_read_rows(con,"SELECT * FROM live_positions ORDER BY symbol")
        per_asset=_read_rows(con,"SELECT symbol,COUNT(*) AS quote_count,MIN(exchange_time) AS first,MAX(exchange_time) AS last,AVG((ask-bid)*20000/(ask+bid)) AS spread_bps FROM live_quotes GROUP BY symbol ORDER BY quote_count DESC")
        n_obs=sum(int(p["quote_count"]) for p in per_asset)
        closed=[f for f in fills if f["side"]=="SELL"]
        buys=[f for f in fills if f["side"]=="BUY"]
        realized=sum(float(f["realized_pnl"]) for f in closed)
        fees=sum(float(f["fee"]) for f in fills)
        win=sum(float(f["realized_pnl"])>0 for f in closed)
        loss=sum(float(f["realized_pnl"])<0 for f in closed)
        initial=float(state["initial_cash"])
        total=float(state["equity"])-initial
        returns=total/initial*100 if initial>0 else 0.
        observed_dd=max((float(x["drawdown_pct"]) for x in equity),default=0.)
        average_exp=sum(float(x["exposure_pct"]) for x in equity)/len(equity) if equity else 0.
        peak_exp=max((float(x["exposure_pct"]) for x in equity),default=0.)
        btc=con.execute(
            "SELECT MIN(id) AS oldest,MAX(id) AS newest FROM live_quotes WHERE symbol='BTC-USD'"
        ).fetchone()
        btc_return=None
        if btc["oldest"] is not None and btc["newest"]!=btc["oldest"]:
            a=con.execute("SELECT (bid+ask)/2 FROM live_quotes WHERE id=?",(btc["oldest"],)).fetchone()[0]
            b=con.execute("SELECT (bid+ask)/2 FROM live_quotes WHERE id=?",(btc["newest"],)).fetchone()[0]
            btc_return=(b/a-1)*100 if a>0 else None
        perf=PerformanceStats(
            source=source,cash=float(state["cash"]),equity=float(state["equity"]),
            return_pct=returns,starting_capital=initial,
            closed_sells=len(closed),simulated_buys=len(buys),
            wins=win,losses=loss,win_rate_pct=(win/len(closed)*100 if closed else None),
            realized_net_pnl=realized,estimated_open_pnl=total-realized,
            total_fees=fees,max_drawdown_pct=observed_dd,
            average_exposure_pct=average_exp,peak_exposure_pct=peak_exp,
            observations=n_obs,distinct_assets=len(per_asset),
            benchmark_btc_gross_pct=btc_return,
            benchmark_note="BTC hypothetical 100% gross hold over recorded quote window; costs/exposure NOT matched.",
        )
        decision_counts=Counter(r["decision"] for r in decisions)
        grouped=defaultdict(lambda:{"buys":0,"sells":0,"net_realized_pnl":0.,"fees":0.})
        for f in fills:
            row=grouped[f["symbol"]]
            row["buys" if f["side"]=="BUY" else "sells"]+=1
            row["net_realized_pnl"]+=float(f["realized_pnl"])
            row["fees"]+=float(f["fee"])
        assets=[{"symbol":sym,**vals} for sym,vals in sorted(grouped.items())]
        return {
            "available":True,"source":source,"stats":perf.as_dict(),
            "equity":equity,"fills":fills[:500],"decisions":decisions[:350],
            "reasons":[{"decision":key,"count":n} for key,n in decision_counts.most_common()],
            "assets":assets,"markets":per_asset,"positions":positions,
            "account_paused":bool(state["paused"]),
            "account_halted":bool(state["halted"]),
            "last_cycle_at":state["last_cycle_at"],
        }
    finally:
        con.close()


def summarize_synthetic(db_path=SYNTHETIC_DB):
    path=Path(db_path)
    if not path.exists():
        return {"available":False,"source":"SYNTHETIC","reason":"No synthetic cycles"}
    con=sqlite3.connect(path,timeout=10)
    con.row_factory=sqlite3.Row
    try:
        state=con.execute("SELECT * FROM micro_state WHERE id=1").fetchone()
        if state is None or state["equity"] is None:
            return {"available":False,"source":"SYNTHETIC","reason":"No synthetic cycles"}
        trades=_read_rows(con,"SELECT * FROM micro_trades ORDER BY id DESC")
        eq=_read_rows(con,"SELECT * FROM micro_equity ORDER BY tick ASC")
        reasons=_read_rows(con,"SELECT decision,COUNT(*) AS count FROM micro_decisions GROUP BY decision ORDER BY count DESC")
        wins=sum(t["realized_pnl"]>0 for t in trades if t["side"]=="SELL")
        sells=sum(t["side"]=="SELL" for t in trades)
        return {
            "available":True,"source":"SYNTHETIC",
            "stats":{
                "equity":float(state["equity"]),
                "cash":float(state["cash"]),
                "starting_capital":10_000.,
                "return_pct":(float(state["equity"])/10000-1)*100,
                "simulated_buys":sum(t["side"]=="BUY" for t in trades),
                "closed_sells":sells,
                "win_rate_pct":wins/sells*100 if sells else None,
                "total_fees":sum(float(t["fee"]) for t in trades),
                "realized_net_pnl":sum(float(t["realized_pnl"]) for t in trades),
                "max_drawdown_pct":max((float(t["drawdown_pct"]) for t in eq),default=0.),
                "observations":int(state["tick"])+1,
            },
            "equity":eq,"fills":trades[:500],
            "reasons":reasons,"scenario":state["scenario"],
        }
    finally:
        con.close()


def diagnosis(report):
    """User-facing reason of no trades based on actual observed decision funnel."""
    if not report.get("available"):
        return "No hay datos registrados todavía. Conecta un proveedor público y observa las cotizaciones."
    stats=report["stats"]
    counts={r["decision"]:r["count"] for r in report.get("reasons",[])}
    if stats["observations"]<45:
        return "Calentamiento: Nory necesita al menos 45 actualizaciones válidas por activo antes de evaluar entradas."
    if stats["simulated_buys"]>0:
        return "Ya hay compras simuladas registradas; revisa sus resultados netos y las ventas pendientes."
    if counts.get("BLOCK_COSTS",0)>0:
        return "Principal obstáculo: ganancias potenciales demasiado pequeñas tras comisiones, spread y deslizamiento. No se deben fabricar operaciones."
    if counts.get("WAIT_FALLING",0)>0 or counts.get("BLOCK_UNKNOWN_DROP",0)>0:
        return "Precios bajando o con caídas anormales: Nory evita comprar sin recuperación técnica o explicación verificada."
    if counts.get("WAIT",0)>0:
        return "Hay cotizaciones, pero ninguna oportunidad supera los requisitos de la estrategia. Es normal que el capital quede en efectivo."
    if counts.get("BLOCK_SPREAD",0)>0:
        return "Los spreads observados son amplios en relación con el margen objetivo."
    return "Revisa el diagnóstico completo de señales, spreads y calidad de las cotizaciones."
