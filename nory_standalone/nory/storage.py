"""Single transactional writer, WAL readers and bounded observation retention."""

from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from .config import STRATEGIES, RULES_VERSION
from .models import Account, Quote


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS latest (provider TEXT, symbol TEXT, data TEXT NOT NULL, PRIMARY KEY(provider,symbol));
CREATE TABLE IF NOT EXISTS samples (
 provider TEXT, symbol TEXT, bucket INTEGER, exchange_ts REAL NOT NULL, received_ts REAL NOT NULL,
 data TEXT NOT NULL, PRIMARY KEY(provider,symbol,bucket));
CREATE INDEX IF NOT EXISTS sample_time ON samples(provider,received_ts);
CREATE TABLE IF NOT EXISTS fills (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
 filled_at REAL NOT NULL, fee REAL NOT NULL, realized_pnl REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS fill_account ON fills(account,filled_at DESC);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS order_account ON orders(account,created_at DESC);
CREATE TABLE IF NOT EXISTS round_trips (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, symbol TEXT NOT NULL, closed_at REAL NOT NULL, pnl REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS round_account ON round_trips(account,closed_at DESC);
CREATE TABLE IF NOT EXISTS decisions (
 account TEXT, symbol TEXT, quote_ts REAL, observed_at REAL NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(account,symbol,quote_ts));
CREATE INDEX IF NOT EXISTS decision_time ON decisions(observed_at);
CREATE TABLE IF NOT EXISTS current_decisions (account TEXT, symbol TEXT, data TEXT NOT NULL, PRIMARY KEY(account,symbol));
CREATE TABLE IF NOT EXISTS equity (
 account TEXT, bucket INTEGER, observed_at REAL NOT NULL, equity REAL NOT NULL, cash REAL NOT NULL,
 exposure REAL NOT NULL, drawdown REAL NOT NULL, PRIMARY KEY(account,bucket));
CREATE TABLE IF NOT EXISTS totals (
 account TEXT PRIMARY KEY, fees REAL NOT NULL DEFAULT 0, fills INTEGER NOT NULL DEFAULT 0,
 buys INTEGER NOT NULL DEFAULT 0, sells INTEGER NOT NULL DEFAULT 0, realized REAL NOT NULL DEFAULT 0,
 wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0,
 gross_profits REAL NOT NULL DEFAULT 0, gross_losses REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS asset_totals (
 account TEXT, symbol TEXT, fees REAL NOT NULL DEFAULT 0, realized REAL NOT NULL DEFAULT 0,
 fills INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account,symbol));
CREATE TABLE IF NOT EXISTS benchmark (
 provider TEXT PRIMARY KEY, first_quote TEXT NOT NULL, last_quote TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, data TEXT NOT NULL);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, path, cfg):
        self.path, self.cfg = Path(path), cfg
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.writer.row_factory = sqlite3.Row
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("PRAGMA synchronous=FULL")
        self.writer.execute("PRAGMA busy_timeout=10000")
        self.writer.executescript(SCHEMA)
        existing = self.writer.execute(
            "SELECT value FROM meta WHERE key='config_fingerprint'"
        ).fetchone()
        if existing and existing[0] != cfg.fingerprint():
            self.writer.close()
            raise ValueError(
                "La configuración difiere de esta cartera. Usa otra ruta --db para un experimento nuevo; conserva el historial."
            )
        with self.writer:
            self.writer.execute(
                "INSERT OR IGNORE INTO meta VALUES('rules_version',?)", (RULES_VERSION,)
            )
            self.writer.execute(
                "INSERT OR IGNORE INTO meta VALUES('config_fingerprint',?)",
                (cfg.fingerprint(),),
            )
            self.writer.execute(
                "INSERT OR IGNORE INTO meta VALUES('config',?)", (encode(asdict(cfg)),)
            )
            for p in cfg.providers:
                for s in STRATEGIES:
                    key = f"{p}:{s}"
                    account = Account(
                        p,
                        s,
                        cfg.initial_capital,
                        cfg.initial_capital,
                        cfg.initial_capital,
                        cfg.initial_capital,
                    )
                    self.writer.execute(
                        "INSERT OR IGNORE INTO accounts VALUES(?,?)",
                        (key, encode(account.as_dict())),
                    )
                    self.writer.execute(
                        "INSERT OR IGNORE INTO totals(account) VALUES(?)", (key,)
                    )
        self.last_maintenance = 0.0

    def close(self):
        self.writer.close()

    def reader(self):
        con = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        return con

    def restore(self):
        accounts = {
            r["id"]: Account.restore(json.loads(r["state"]))
            for r in self.writer.execute("SELECT * FROM accounts")
        }
        latest = [
            Quote(**json.loads(r[0]))
            for r in self.writer.execute("SELECT data FROM latest")
        ]
        freeze = self.writer.execute(
            "SELECT value FROM meta WHERE key='freeze'"
        ).fetchone()
        return accounts, latest, json.loads(freeze[0]) if freeze else []

    def checkpoint(self, payload):
        now = payload["now"]
        db = self.writer
        try:
            db.execute("BEGIN IMMEDIATE")
            for key, state in payload["accounts"].items():
                db.execute(
                    "UPDATE accounts SET state=? WHERE id=?", (encode(state), key)
                )
            for q in payload["quotes"]:
                raw = encode(q)
                db.execute(
                    "INSERT INTO latest VALUES(?,?,?) ON CONFLICT(provider,symbol) DO UPDATE SET data=excluded.data",
                    (q["provider"], q["symbol"], raw),
                )
                db.execute(
                    "INSERT INTO samples VALUES(?,?,?,?,?,?) ON CONFLICT(provider,symbol,bucket) DO UPDATE SET "
                    "exchange_ts=excluded.exchange_ts,received_ts=excluded.received_ts,data=excluded.data",
                    (
                        q["provider"],
                        q["symbol"],
                        int(q["exchange_ts"] // self.cfg.sample_seconds),
                        q["exchange_ts"],
                        q["received_ts"],
                        raw,
                    ),
                )
                if q["symbol"] == "BTC-USD":
                    db.execute(
                        "INSERT INTO benchmark VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET last_quote=excluded.last_quote",
                        (q["provider"], raw, raw),
                    )
            for fill in payload["fills"]:
                changed = db.execute(
                    "INSERT OR IGNORE INTO fills VALUES(?,?,?,?,?,?,?,?)",
                    (
                        fill["id"],
                        fill["account"],
                        fill["symbol"],
                        fill["side"],
                        fill["filled_at"],
                        fill["fee"],
                        fill["realized_pnl"],
                        encode(fill),
                    ),
                ).rowcount
                if changed:
                    db.execute(
                        "UPDATE totals SET fees=fees+?,fills=fills+1,buys=buys+?,sells=sells+?,realized=realized+? WHERE account=?",
                        (
                            fill["fee"],
                            int(fill["side"] == "BUY"),
                            int(fill["side"] == "SELL"),
                            fill["realized_pnl"],
                            fill["account"],
                        ),
                    )
                    db.execute(
                        "INSERT INTO asset_totals VALUES(?,?,?,?,1) ON CONFLICT(account,symbol) DO UPDATE SET "
                        "fees=fees+excluded.fees,realized=realized+excluded.realized,fills=fills+1",
                        (
                            fill["account"],
                            fill["symbol"],
                            fill["fee"],
                            fill["realized_pnl"],
                        ),
                    )
            for order in payload["orders"]:
                db.execute(
                    "INSERT INTO orders VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                    (
                        order["id"],
                        order["account"],
                        order["created_at"],
                        order["status"],
                        encode(order),
                    ),
                )
            for trade in payload["closed"]:
                if db.execute(
                    "INSERT OR IGNORE INTO round_trips VALUES(?,?,?,?,?,?)",
                    (
                        trade["id"],
                        trade["account"],
                        trade["symbol"],
                        trade["closed_at"],
                        trade["pnl"],
                        encode(trade),
                    ),
                ).rowcount:
                    pnl = trade["pnl"]
                    db.execute(
                        "UPDATE totals SET closed=closed+1,wins=wins+?,losses=losses+?,gross_profits=gross_profits+?,gross_losses=gross_losses+? WHERE account=?",
                        (
                            int(pnl > 0),
                            int(pnl < 0),
                            max(pnl, 0),
                            min(pnl, 0),
                            trade["account"],
                        ),
                    )
            for decision in payload["decisions"]:
                raw = encode(decision)
                old = db.execute(
                    "SELECT data FROM current_decisions WHERE account=? AND symbol=?",
                    (decision["account"], decision["symbol"]),
                ).fetchone()
                old_data = json.loads(old[0]) if old else None
                if (
                    old_data is None
                    or old_data["action"] != decision["action"]
                    or int(old_data["observed_at"] // 60)
                    != int(decision["observed_at"] // 60)
                ):
                    db.execute(
                        "INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?)",
                        (
                            decision["account"],
                            decision["symbol"],
                            decision["quote_ts"],
                            decision["observed_at"],
                            raw,
                        ),
                    )
                db.execute(
                    "INSERT INTO current_decisions VALUES(?,?,?) ON CONFLICT(account,symbol) DO UPDATE SET data=excluded.data",
                    (decision["account"], decision["symbol"], raw),
                )
            if payload["quotes"]:
                for key, state in payload["accounts"].items():
                    if not any(
                        q["provider"] == state["provider"] for q in payload["quotes"]
                    ):
                        continue
                    eq = state["equity"]
                    exposure = max(0, eq - state["cash"]) / eq if eq > 0 else 0
                    db.execute(
                        "INSERT INTO equity VALUES(?,?,?,?,?,?,?) ON CONFLICT(account,bucket) DO UPDATE SET "
                        "observed_at=excluded.observed_at,equity=excluded.equity,cash=excluded.cash,exposure=excluded.exposure,drawdown=excluded.drawdown",
                        (
                            key,
                            int(now // 10),
                            now,
                            eq,
                            state["cash"],
                            exposure,
                            state["max_drawdown"],
                        ),
                    )
            db.execute(
                "INSERT INTO meta VALUES('freeze',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (encode(payload["freeze"]),),
            )
            if now - self.last_maintenance >= 300:
                cutoff = now - self.cfg.retention_days * 86400
                db.execute("DELETE FROM samples WHERE received_ts < ?", (cutoff,))
                # Hard cap bounds disk use even with an unusually active universe.
                db.execute(
                    "DELETE FROM samples WHERE rowid IN (SELECT rowid FROM samples ORDER BY received_ts DESC LIMIT -1 OFFSET ?)",
                    (self.cfg.max_recorded_samples,),
                )
                db.execute(
                    "DELETE FROM decisions WHERE observed_at < ?", (now - 86400,)
                )
                db.execute(
                    "DELETE FROM decisions WHERE rowid IN (SELECT rowid FROM decisions ORDER BY observed_at DESC LIMIT -1 OFFSET 100000)"
                )
                db.execute(
                    "DELETE FROM equity WHERE observed_at < ?", (now - 30 * 86400,)
                )
                self.last_maintenance = now
            db.commit()
        except Exception:
            db.rollback()
            raise

    def report(self, account_id):
        with closing(self.reader()) as db:
            db.execute("BEGIN")  # Consistent balances and totals in one WAL snapshot.
            row = db.execute(
                "SELECT state FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Cartera desconocida")
            state = json.loads(row[0])
            stats = dict(
                db.execute(
                    "SELECT * FROM totals WHERE account=?", (account_id,)
                ).fetchone()
            )

            def documents(table, order, limit):
                return [
                    json.loads(r[0])
                    for r in db.execute(
                        f"SELECT data FROM {table} WHERE account=? ORDER BY {order} DESC LIMIT ?",
                        (account_id, limit),
                    )
                ]

            closed = stats["closed"]
            stats.update(
                {
                    "net_pnl": state["equity"] - state["initial"],
                    "unrealized_pnl": state["equity"]
                    - state["initial"]
                    - stats["realized"],
                    "win_rate_pct": stats["wins"] / closed * 100 if closed else None,
                    "average_win": stats["gross_profits"] / stats["wins"]
                    if stats["wins"]
                    else None,
                    "average_loss": stats["gross_losses"] / stats["losses"]
                    if stats["losses"]
                    else None,
                }
            )
            benchmark = db.execute(
                "SELECT * FROM benchmark WHERE provider=?", (state["provider"],)
            ).fetchone()
            baseline = None
            if benchmark:
                first, last = (
                    json.loads(benchmark["first_quote"]),
                    json.loads(benchmark["last_quote"]),
                )
                fee, slip = (
                    self.cfg.fee_bps[state["provider"]] / 10000,
                    self.cfg.slippage_bps / 10000,
                )
                qty = state["initial"] / (first["ask"] * (1 + slip) * (1 + fee))
                final = qty * last["bid"] * (1 - slip) * (1 - fee)
                baseline = {
                    "return_pct": (final / state["initial"] - 1) * 100,
                    "final_equity": final,
                    "first_ts": first["exchange_ts"],
                    "last_ts": last["exchange_ts"],
                    "note": "BTC: 100 % invertido desde la primera muestra registrada, costes en ambos lados. Exposición y periodo pueden diferir de Nory; no está ajustado al riesgo.",
                }
            return {
                "state": state,
                "stats": stats,
                "benchmark": baseline,
                "fills": documents("fills", "filled_at", 200),
                "orders": documents("orders", "created_at", 200),
                "round_trips": documents("round_trips", "closed_at", 200),
                "decisions": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT data FROM current_decisions WHERE account=?",
                        (account_id,),
                    )
                ],
                "assets": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM asset_totals WHERE account=?", (account_id,)
                    )
                ],
                "equity": list(
                    reversed(
                        [
                            dict(r)
                            for r in db.execute(
                                "SELECT * FROM equity WHERE account=? ORDER BY bucket DESC LIMIT 600",
                                (account_id,),
                            )
                        ]
                    )
                ),
                "comparison": [
                    {
                        "id": r["id"],
                        "state": json.loads(r["state"]),
                        "stats": dict(
                            db.execute(
                                "SELECT * FROM totals WHERE account=?", (r["id"],)
                            ).fetchone()
                        ),
                    }
                    for r in db.execute(
                        "SELECT * FROM accounts WHERE id LIKE ?",
                        (state["provider"] + ":%",),
                    )
                ],
                "research": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT data FROM research ORDER BY id DESC LIMIT 5"
                    )
                ],
            }

    def recorded(self, provider, limit=100_000):
        with closing(self.reader()) as db:
            return list(
                reversed(
                    [
                        Quote(**json.loads(r[0]))
                        for r in db.execute(
                            "SELECT data FROM samples WHERE provider=? ORDER BY received_ts DESC LIMIT ?",
                            (provider, limit),
                        )
                    ]
                )
            )

    def save_research(self, report, now):
        # Separate writer connection: research may finish concurrently with a live checkpoint.
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute(
                "INSERT INTO research(created_at,data) VALUES(?,?)",
                (now, encode(report)),
            )
            db.execute(
                "DELETE FROM research WHERE id NOT IN (SELECT id FROM research ORDER BY id DESC LIMIT 20)"
            )
