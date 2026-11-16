"""Motor persistente de paper trading. NO hay APIs de bróker ni órdenes reales.

Todas las ejecuciones son FILLS HIPOTÉTICOS al cierre OBSERVADO, NO precios
obtenibles en un mercado. Una misma vela se procesa una única vez por cuenta.
El modo de ejecución comienza PAUSADO y requiere activación manual local.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import math
import sqlite3

from app.markets import MARKET_BY_SYMBOL


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "ais_paper.sqlite3"


@dataclass(frozen=True)
class PaperPolicy:
    starting_cash: float = 10_000.0
    allocation_fraction: float = 0.10
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    stop_loss_pct: float = 0.08

    def __post_init__(self):
        values = asdict(self)
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in values.values()):
            raise ValueError("Los parámetros deben ser finitos")
        if self.starting_cash <= 0 or not 0 < self.allocation_fraction <= 1:
            raise ValueError("Capital/asignación inválidos")
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("Stop inválido")
        if not 0 <= self.fee_bps <= 200 or not 0 <= self.slippage_bps <= 200:
            raise ValueError("Comisiones/deslizamiento fuera de rango")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("""
       CREATE TABLE IF NOT EXISTS paper_control (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          paused INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
       )
    """)
    con.execute("INSERT OR IGNORE INTO paper_control (id,paused,updated_at) VALUES (1,1,?)", (_now(),))
    con.execute("""
       CREATE TABLE IF NOT EXISTS paper_accounts (
          source TEXT NOT NULL,
          symbol TEXT NOT NULL,
          currency TEXT NOT NULL,
          cash REAL NOT NULL,
          quantity REAL NOT NULL,
          average_cost REAL NOT NULL,
          invested_basis REAL NOT NULL,
          last_bar TEXT NOT NULL DEFAULT '',
          last_price REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (source, symbol)
       )
    """)
    con.execute("""
       CREATE TABLE IF NOT EXISTS paper_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          symbol TEXT NOT NULL,
          bar TEXT NOT NULL,
          processed_at TEXT NOT NULL,
          signal TEXT NOT NULL,
          action TEXT NOT NULL,
          close_proxy REAL NOT NULL,
          fill_proxy REAL NOT NULL,
          quantity_delta REAL NOT NULL,
          fee REAL NOT NULL,
          realized_pnl REAL NOT NULL,
          cash_after REAL NOT NULL,
          position_after REAL NOT NULL,
          UNIQUE(source, symbol, bar)
       )
    """)
    con.commit()
    return con


def is_paused(db_path: str | Path = DEFAULT_DB) -> bool:
    con = _connect(db_path)
    try:
        return bool(con.execute("SELECT paused FROM paper_control WHERE id=1").fetchone()["paused"])
    finally:
        con.close()


def set_paused(paused: bool, db_path: str | Path = DEFAULT_DB) -> None:
    con = _connect(db_path)
    try:
        with con:
            con.execute("UPDATE paper_control SET paused=?, updated_at=? WHERE id=1",
                        (int(bool(paused)), _now()))
    finally:
        con.close()


def process_bar(
    source: str, symbol: str, bar: str, close_price: float,
    signal: str, db_path: str | Path = DEFAULT_DB,
    policy: PaperPolicy | None = None,
) -> dict:
    """Procesa una única vela cerrada con auditoría, tras activar motor local.

    Fills proxy al mismo cierre OBSERVADO de la vela (aproximación, no ejecución
    posible retroactivamente). Nunca consulta el bróker ni mueve dinero.
    """
    cfg = policy or PaperPolicy()
    if source not in ("SYNTHETIC_DEMO", "YAHOO_HISTORICAL"):
        raise ValueError("Fuente no permitida")
    market = MARKET_BY_SYMBOL.get(symbol)
    if market is None or not market.paper_eligible:
        raise ValueError("Activo solo analítico/no permitido en paper engine")
    if not bar or len(bar) > 80:
        raise ValueError("Bar inválido")
    if signal not in ("CANDIDATO_COMPRA", "CANDIDATO_VENTA", "ESPERAR", "SIN_SENAL"):
        raise ValueError("Señal inválida")
    if not isinstance(close_price, (int, float)) or not math.isfinite(close_price) or close_price <= 0:
        raise ValueError("Precio inválido")
    con = _connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT paused FROM paper_control WHERE id=1").fetchone()["paused"]:
            con.rollback()
            return {"status": "PAUSED", "symbol": symbol, "source": source}
        old = con.execute(
            "SELECT * FROM paper_accounts WHERE source=? AND symbol=?",
            (source, symbol),
        ).fetchone()
        if old is None:
            con.execute(
                "INSERT INTO paper_accounts "
                "(source,symbol,currency,cash,quantity,average_cost,invested_basis,last_bar,last_price,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source, symbol, market.currency, cfg.starting_cash, 0., 0., 0., "", 0., _now()),
            )
            old = con.execute(
                "SELECT * FROM paper_accounts WHERE source=? AND symbol=?",
                (source, symbol),
            ).fetchone()
        if bar <= old["last_bar"]:
            con.rollback()
            return {"status": "DUPLICATE_OR_OLD", "symbol": symbol, "bar": bar}

        cash = float(old["cash"])
        quantity = float(old["quantity"])
        average = float(old["average_cost"])
        basis = float(old["invested_basis"])
        fee_rate = cfg.fee_bps / 10_000
        slip = cfg.slippage_bps / 10_000
        action, fee, changed_qty, pnl = "HOLD", 0., 0., 0.
        fill_proxy = float(close_price)
        # Stop es solo una regla de alerta basada en el cierre, NO stop garantizado.
        stop = quantity > 0 and close_price <= average * (1 - cfg.stop_loss_pct)
        if quantity > 0 and (signal == "CANDIDATO_VENTA" or stop):
            fill_proxy = close_price * (1 - slip)
            gross = quantity * fill_proxy
            fee = gross * fee_rate
            cash += gross - fee
            pnl = gross - fee - basis
            changed_qty = -quantity
            quantity, average, basis = 0., 0., 0.
            action = "SELL_SIM_STOP" if stop else "SELL_SIM"
        elif quantity == 0 and signal == "CANDIDATO_COMPRA":
            budget = cash * cfg.allocation_fraction
            fill_proxy = close_price * (1 + slip)
            qty = budget / (fill_proxy * (1 + fee_rate))
            fee = qty * fill_proxy * fee_rate
            spent = qty * fill_proxy + fee
            cash -= spent
            quantity, changed_qty = qty, qty
            average, basis = fill_proxy, spent
            action = "BUY_SIM"

        con.execute(
            "UPDATE paper_accounts SET cash=?, quantity=?, average_cost=?,"
            "invested_basis=?,last_bar=?,last_price=?,updated_at=? WHERE source=? AND symbol=?",
            (cash, quantity, average, basis, bar, close_price, _now(), source, symbol),
        )
        con.execute(
            "INSERT INTO paper_events (source,symbol,bar,processed_at,signal,action,"
            "close_proxy,fill_proxy,quantity_delta,fee,realized_pnl,cash_after,position_after)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (source, symbol, bar, _now(), signal, action, close_price, fill_proxy,
             changed_qty, fee, pnl, cash, quantity),
        )
        con.commit()
        return {
            "status": "PROCESSED", "source": source, "symbol": symbol, "bar": bar,
            "signal": signal, "action": action, "currency": market.currency,
            "cash": round(cash, 4), "quantity": round(quantity, 8),
            "equity_mark": round(cash + quantity * close_price, 4),
            "realized_pnl": round(pnl, 4),
            "execution_type": "HYPOTHETICAL_CLOSE_PROXY_NOT_LIVE",
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def get_accounts(db_path: str | Path = DEFAULT_DB, source: str | None = None) -> list[dict]:
    con = _connect(db_path)
    try:
        sql = "SELECT * FROM paper_accounts"
        args = ()
        if source is not None:
            sql += " WHERE source=?"
            args = (source,)
        rows = con.execute(sql + " ORDER BY source,symbol", args).fetchall()
        result = []
        for row in rows:
            obj = dict(row)
            obj["equity_mark"] = obj["cash"] + obj["quantity"] * obj["last_price"]
            result.append(obj)
        return result
    finally:
        con.close()


def get_events(db_path: str | Path = DEFAULT_DB, limit: int = 100) -> list[dict]:
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit inválido")
    con = _connect(db_path)
    try:
        return [dict(row) for row in con.execute(
            "SELECT * FROM paper_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
    finally:
        con.close()
