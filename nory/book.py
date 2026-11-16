"""Nory shared-USD, SQLite-backed simulated portfolio.

Important: one common fictitious USD balance across instruments, never
separate capital per symbol. Decisions at confirmed bar close, fills at
NEXT bar's Open only IF that next bar is subsequently observed. Historical
fills are approximations (not orders one could really have obtained).
Nory has no imports of brokers, credentials or execution APIs.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd

from nory.engine import NoryPolicy, Observation, rank_candidates

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "nory_paper.sqlite3"
SOURCES = ("SYNTHETIC_DEMO", "YAHOO_HISTORICAL")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path = DEFAULT_DB):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS nory_control(
      id INTEGER PRIMARY KEY CHECK(id=1),
      paused INTEGER NOT NULL DEFAULT 1,
      demo_step INTEGER NOT NULL DEFAULT 0
    );
    INSERT OR IGNORE INTO nory_control(id,paused,demo_step) VALUES(1,1,0);
    CREATE TABLE IF NOT EXISTS nory_portfolios(
      source TEXT PRIMARY KEY,
      starting_cash REAL NOT NULL,
      cash REAL NOT NULL,
      equity REAL NOT NULL,
      peak_equity REAL NOT NULL,
      halted INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS nory_positions(
      source TEXT NOT NULL,
      symbol TEXT NOT NULL,
      category TEXT NOT NULL,
      quantity REAL NOT NULL,
      entry_price REAL NOT NULL,
      invested_basis REAL NOT NULL,
      mark_price REAL NOT NULL,
      mark_bar TEXT NOT NULL,
      PRIMARY KEY(source,symbol)
    );
    CREATE TABLE IF NOT EXISTS nory_orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      symbol TEXT NOT NULL,
      side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
      decision_bar TEXT NOT NULL,
      weight REAL NOT NULL,
      priority REAL NOT NULL,
      reason TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('PENDING','FILLED','CANCELED','EXPIRED')),
      fill_bar TEXT,
      fill_price REAL,
      quantity REAL,
      fee REAL,
      pnl REAL,
      UNIQUE(source,symbol,side,decision_bar)
    );
    CREATE INDEX IF NOT EXISTS nory_order_status ON nory_orders(source,status);
    CREATE TABLE IF NOT EXISTS nory_scans(
      source TEXT NOT NULL,
      symbol TEXT NOT NULL,
      bar TEXT NOT NULL,
      signal TEXT NOT NULL,
      priority REAL NOT NULL,
      reason TEXT NOT NULL,
      recorded_at TEXT NOT NULL,
      PRIMARY KEY(source,symbol,bar)
    );
    CREATE TABLE IF NOT EXISTS nory_cycles(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      created_at TEXT NOT NULL,
      cash REAL NOT NULL,
      equity REAL NOT NULL,
      exposure_pct REAL NOT NULL,
      open_positions INTEGER NOT NULL,
      halted INTEGER NOT NULL,
      events_json TEXT NOT NULL
    );
    """)
    return con


def is_paused(db_path: str | Path = DEFAULT_DB) -> bool:
    con = connect(db_path)
    try:
        return bool(con.execute("SELECT paused FROM nory_control WHERE id=1").fetchone()[0])
    finally:
        con.close()


def set_paused(paused: bool, db_path: str | Path = DEFAULT_DB):
    con = connect(db_path)
    try:
        with con:
            con.execute("UPDATE nory_control SET paused=? WHERE id=1", (int(bool(paused)),))
    finally:
        con.close()


def next_demo_step(db_path: str | Path = DEFAULT_DB) -> int:
    """Deterministic demo timeline advances once each active scan cycle."""
    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT paused,demo_step FROM nory_control WHERE id=1").fetchone()
        if row["paused"]:
            con.rollback()
            raise ValueError("Nory esta pausado: primero activalo en la interfaz")
        step = int(row["demo_step"])
        if step >= 440:
            con.rollback()
            raise ValueError("Fin del conjunto sintetico de 600 velas")
        con.execute("UPDATE nory_control SET demo_step=demo_step+1 WHERE id=1")
        con.commit()
        return step
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def _position_rows(con, source):
    return {
        row["symbol"]: dict(row)
        for row in con.execute(
            "SELECT * FROM nory_positions WHERE source=?", (source,)
        )
    }


def _pending_rows(con, source):
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM nory_orders WHERE source=? AND status='PENDING' "
            "ORDER BY CASE side WHEN 'SELL' THEN 0 ELSE 1 END, "
            "priority DESC,symbol ASC,id ASC", (source,)
        )
    ]


def _next_open(frame: pd.DataFrame, decision_bar: str, observed_bar: str):
    """Only fill if next bar after decision is EXACTLY the latest observed bar."""
    dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in frame.index]
    if not dates or dates[-1] != observed_bar:
        return None
    older = [i for i, day in enumerate(dates) if day == decision_bar]
    if len(older) != 1 or older[0] + 1 != len(dates) - 1:
        return None
    opening = float(frame["Open"].iloc[-1])
    return opening if math.isfinite(opening) and opening > 0 else None


def _equity(cash, positions):
    invested = sum(p["quantity"] * p["mark_price"] for p in positions.values())
    return cash + invested, invested


def _weight_for_category(positions, category):
    return sum(
        p["quantity"] * p["mark_price"]
        for p in positions.values() if p["category"] == category
    )


def _validate_batch(observations: dict[str, tuple[Observation, pd.DataFrame]]):
    if not isinstance(observations, dict) or not observations:
        raise ValueError("Se requiere una lista de activos revisados")
    if len(observations) > 20:
        raise ValueError("Maximo de 20 activos por lote")
    for symbol, (obs, frame) in observations.items():
        if obs.symbol != symbol or not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("Lote mal formado")
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("Fechas no cronologicas")
        bar = pd.Timestamp(frame.index[-1]).strftime("%Y-%m-%d")
        if bar != obs.bar:
            raise ValueError("Fecha de observacion no coincide con ultimo dato")
        for col in ("Open", "Close"):
            if col not in frame or not math.isfinite(float(frame[col].iloc[-1])):
                raise ValueError(f"Ultimo {col} invalido")
        if abs(float(frame["Close"].iloc[-1]) - obs.close_price) > max(1e-6, obs.close_price * 1e-8):
            raise ValueError("Cotizacion de observacion no corresponde a fuente")
        if obs.signal not in ("CANDIDATO_COMPRA", "CANDIDATO_VENTA", "ESPERAR", "SIN_SENAL"):
            raise ValueError("Senal invalida")


def apply_cycle(
    observations: dict[str, tuple[Observation, pd.DataFrame]],
    source: str,
    db_path: str | Path = DEFAULT_DB,
    policy: NoryPolicy | None = None,
) -> dict:
    """Single atomic portfolio cycle, deterministically ordered, no external IO."""
    cfg = policy or NoryPolicy()
    if source not in SOURCES:
        raise ValueError("Fuente prohibida")
    _validate_batch(observations)
    con = connect(db_path)
    events = []
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT paused FROM nory_control WHERE id=1").fetchone()["paused"]:
            con.rollback()
            return {"status": "PAUSED", "source": source, "events": []}

        portfolio = con.execute(
            "SELECT * FROM nory_portfolios WHERE source=?", (source,)
        ).fetchone()
        if portfolio is None:
            con.execute(
                "INSERT INTO nory_portfolios "
                "(source,starting_cash,cash,equity,peak_equity,halted,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (source,cfg.starting_cash,cfg.starting_cash,cfg.starting_cash,
                 cfg.starting_cash,0,utc_now()),
            )
            portfolio = con.execute(
                "SELECT * FROM nory_portfolios WHERE source=?", (source,)
            ).fetchone()
        cash = float(portfolio["cash"])
        peak = float(portfolio["peak_equity"])
        halted = bool(portfolio["halted"])
        positions = _position_rows(con, source)

        # Mark only with observed completed closes; never fabricate missing prices.
        for sym in sorted(observations):
            obs, _ = observations[sym]
            if sym in positions and obs.bar >= positions[sym]["mark_bar"]:
                positions[sym]["mark_price"] = obs.close_price
                positions[sym]["mark_bar"] = obs.bar

        # Process previously pending orders against NEXT bar OPEN, never same bar.
        for order in _pending_rows(con, source):
            symbol = order["symbol"]
            entry = observations.get(symbol)
            if entry is None:
                continue  # no new data: keep pending, no imaginary execution
            obs, frame = entry
            if obs.bar <= order["decision_bar"]:
                continue
            opening = _next_open(frame, order["decision_bar"], obs.bar)
            if opening is None:
                con.execute("UPDATE nory_orders SET status='EXPIRED' WHERE id=?",
                            (order["id"],))
                events.append({"symbol":symbol, "event":"EXPIRED", "reason":"Vela siguiente no observada a tiempo"})
                continue

            qty, fill, fee, pnl, action = 0., 0., 0., 0., "CANCELED"
            if order["side"] == "SELL":
                pos = positions.get(symbol)
                if pos and pos["quantity"] > 0:
                    qty = float(pos["quantity"])
                    fill = opening * (1 - cfg.slippage_bps / 10000)
                    gross = qty * fill
                    fee = gross * cfg.fee_bps / 10000
                    pnl = gross - fee - pos["invested_basis"]
                    cash += gross - fee
                    del positions[symbol]
                    con.execute(
                        "DELETE FROM nory_positions WHERE source=? AND symbol=?",
                        (source, symbol),
                    )
                    action = "FILLED"
            else:
                if not halted and symbol not in positions and len(positions) < cfg.max_positions:
                    equity, invested = _equity(cash, positions)
                    cat = obs.category
                    cat_used = _weight_for_category(positions, cat)
                    target = min(order["weight"], cfg.max_position_weight)
                    cap = min(
                        target * equity,
                        max(0., cfg.max_total_exposure * equity - invested),
                        max(0., cfg.max_category_weight * equity - cat_used),
                        max(0., cash),
                    )
                    if cat == "Criptomonedas":
                        cap = min(cap, max(
                            0., cfg.max_crypto_weight * equity - _weight_for_category(positions,cat)
                        ))
                    if cap >= 1:
                        fill = opening * (1 + cfg.slippage_bps / 10000)
                        qty = cap / (fill * (1 + cfg.fee_bps / 10000))
                        fee = qty * fill * cfg.fee_bps / 10000
                        spent = qty * fill + fee
                        cash -= spent
                        positions[symbol] = {
                            "source": source, "symbol": symbol, "category": cat,
                            "quantity": qty, "entry_price": fill,
                            "invested_basis": spent, "mark_price": obs.close_price,
                            "mark_bar": obs.bar,
                        }
                        action = "FILLED"
            con.execute(
                "UPDATE nory_orders SET status=?,fill_bar=?,fill_price=?,quantity=?,fee=?,pnl=? WHERE id=?",
                (action, obs.bar, fill or None, qty, fee, pnl, order["id"]),
            )
            events.append({
                "symbol": symbol, "event": ("BUY_SIM" if order["side"] == "BUY" else "SELL_SIM")
                if action == "FILLED" else "CANCELED",
                "quantity": round(qty, 8), "fill": round(fill, 6),
                "fee": round(fee, 4), "pnl": round(pnl, 4),
                "execution": "NEXT_OBSERVED_BAR_OPEN_HYPOTHETICAL",
            })
            if action == "FILLED" and order["side"] == "BUY":
                pos = positions[symbol]
                con.execute(
                    "INSERT OR REPLACE INTO nory_positions "
                    "(source,symbol,category,quantity,entry_price,invested_basis,mark_price,mark_bar) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (source,symbol,pos["category"],pos["quantity"],
                     pos["entry_price"],pos["invested_basis"],pos["mark_price"],pos["mark_bar"]),
                )

        # Update all current observations in the position ledger.
        for symbol, pos in positions.items():
            con.execute(
                "UPDATE nory_positions SET mark_price=?,mark_bar=? "
                "WHERE source=? AND symbol=?",
                (pos["mark_price"],pos["mark_bar"],source,symbol),
            )
        equity, invested = _equity(cash, positions)
        peak = max(peak, equity)
        if equity <= peak * (1 - cfg.drawdown_kill_pct):
            halted = True
            con.execute(
                "UPDATE nory_orders SET status='CANCELED' "
                "WHERE source=? AND side='BUY' AND status='PENDING'", (source,)
            )
            events.append({"event":"KILL_SWITCH", "reason":"Caida cartera supera limite; nuevas compras bloqueadas"})
        # New scans; staging sells first and buys sorted by risk score.
        new_scans = []
        for sym in sorted(observations):
            obs, _ = observations[sym]
            cursor = con.execute(
                "INSERT OR IGNORE INTO nory_scans "
                "(source,symbol,bar,signal,priority,reason,recorded_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (source,sym,obs.bar,obs.signal,obs.priority,obs.reason,utc_now()),
            )
            if cursor.rowcount:
                new_scans.append(obs)

        pending_symbols = {
            row["symbol"] for row in _pending_rows(con,source)
        }
        for obs in new_scans:
            pos = positions.get(obs.symbol)
            if pos and obs.symbol not in pending_symbols:
                exit_condition = (
                    obs.signal == "CANDIDATO_VENTA" or
                    obs.close_price <= pos["entry_price"] * (1 - cfg.stop_loss_pct)
                )
                if exit_condition:
                    con.execute(
                        "INSERT OR IGNORE INTO nory_orders "
                        "(source,symbol,side,decision_bar,weight,priority,reason,status) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (source,obs.symbol,"SELL",obs.bar,0.,obs.priority,
                         "Senal de salida o stop evaluado al cierre","PENDING"),
                    )
                    pending_symbols.add(obs.symbol)
                    events.append({"symbol":obs.symbol,"event":"SELL_PENDING", "bar":obs.bar})

        if not halted:
            for obs in rank_candidates(new_scans,cfg):
                if obs.symbol in positions or obs.symbol in pending_symbols:
                    continue
                if len(positions) + len([x for x in pending_symbols if x not in positions]) >= cfg.max_positions:
                    break
                con.execute(
                    "INSERT OR IGNORE INTO nory_orders "
                    "(source,symbol,side,decision_bar,weight,priority,reason,status) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (source,obs.symbol,"BUY",obs.bar,obs.target_weight,obs.priority,
                     obs.reason,"PENDING"),
                )
                pending_symbols.add(obs.symbol)
                events.append({"symbol":obs.symbol,"event":"BUY_PENDING",
                               "target_weight_pct":round(obs.target_weight*100,1),
                               "bar":obs.bar,"priority":obs.priority})

        con.execute(
            "UPDATE nory_portfolios SET cash=?,equity=?,peak_equity=?,halted=?,updated_at=? WHERE source=?",
            (cash,equity,peak,int(halted),utc_now(),source),
        )
        exposure = (invested/equity*100) if equity>0 else 0.
        con.execute(
            "INSERT INTO nory_cycles (source,created_at,cash,equity,exposure_pct,"
            "open_positions,halted,events_json) VALUES(?,?,?,?,?,?,?,?)",
            (source,utc_now(),cash,equity,exposure,len(positions),int(halted),
             json.dumps(events,ensure_ascii=False,allow_nan=False)),
        )
        con.commit()
        return {
            "status": "HALTED" if halted else "PROCESSED",
            "source": source, "cash": round(cash,2), "equity": round(equity,2),
            "exposure_pct": round(exposure,2), "open_positions":len(positions),
            "events":events,
            "note":"Capital USD exclusivamente simulado; fills a apertura posterior, no ejecucion real",
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_dashboard(db_path: str | Path = DEFAULT_DB, source: str = "SYNTHETIC_DEMO") -> dict:
    if source not in SOURCES:
        raise ValueError("Fuente invalida")
    con = connect(db_path)
    try:
        control = con.execute("SELECT * FROM nory_control WHERE id=1").fetchone()
        portfolio = con.execute("SELECT * FROM nory_portfolios WHERE source=?",(source,)).fetchone()
        positions = [dict(row) for row in con.execute(
            "SELECT * FROM nory_positions WHERE source=? ORDER BY symbol",(source,)
        )]
        orders = [dict(row) for row in con.execute(
            "SELECT * FROM nory_orders WHERE source=? ORDER BY id DESC LIMIT 100",(source,)
        )]
        scans = [dict(row) for row in con.execute(
            "SELECT * FROM nory_scans WHERE source=? ORDER BY recorded_at DESC,symbol LIMIT 50",(source,)
        )]
        cycles = [dict(row) for row in con.execute(
            "SELECT id,created_at,cash,equity,exposure_pct,open_positions,halted "
            "FROM nory_cycles WHERE source=? ORDER BY id DESC LIMIT 120",(source,)
        )]
        result = {
            "paused":bool(control["paused"]), "demo_step":control["demo_step"],
            "portfolio":dict(portfolio) if portfolio else None,
            "positions":positions,"orders":orders,"scans":scans,"cycles":cycles,
        }
        return result
    finally:
        con.close()
