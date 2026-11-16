"""Deterministic paper ledger shared by live research and chronological replay."""

from collections import Counter, deque
from dataclasses import asdict
from statistics import median
import hashlib

from .config import STRATEGIES
from .models import Account, Order, Position
from .history import AnalysisHistory
from .strategies import Signal, aligned_correlation, evaluate


class ResearchCore:
    def __init__(self, cfg, accounts=None):
        self.cfg = cfg
        self.accounts = accounts or {
            f"{p}:{s}": Account(
                p,
                s,
                cfg.initial_capital,
                cfg.initial_capital,
                cfg.initial_capital,
                cfg.initial_capital,
            )
            for p in cfg.providers
            for s in STRATEGIES
        }
        self.latest = {}
        self.history = {}
        self.dirty = {}
        self.freeze_until = {}
        self.metrics = Counter()
        self.decisions = {}
        self.events = []
        self.order_events = {}
        self.closed = []
        self.analysis = AnalysisHistory(cfg)
        self.activity = Counter()

    def receive(self, quote, now):
        if (
            quote.provider not in self.cfg.providers
            or quote.symbol not in self.cfg.symbols
        ):
            self.metrics["unexpected"] += 1
            return False
        if not quote.fresh(now, self.cfg.quote_max_age_seconds):
            self.metrics["stale_rejected"] += 1
            return False
        key = (quote.provider, quote.symbol)
        old = self.latest.get(key)
        if not quote.newer_than(old):
            self.metrics["duplicates_or_out_of_order"] += 1
            return False
        history = self.history.get(key, ())
        base = next(
            (q for q in history if q.exchange_ts >= quote.exchange_ts - 60), None
        )
        instant = quote.mid / old.mid - 1 if old else 0
        trailing = quote.mid / base.mid - 1 if base else 0
        context = self.analysis.closed_for(
            quote.provider, quote.symbol, quote.exchange_ts, known_at=quote.received_ts
        )
        context_move = (
            quote.mid / context[-1].mid - 1
            if context
            and quote.exchange_ts - context[-1].exchange_ts
            <= self.cfg.analysis_interval_seconds * 2
            else 0
        )
        if min(instant, trailing, context_move) <= -self.cfg.shock_fraction:
            self.freeze_until[key] = now + self.cfg.shock_cooldown_seconds
            self.metrics["unexplained_shocks"] += 1
        if (
            quote.symbol == "BTC-USD"
            and context_move <= -self.cfg.market_shock_fraction
        ):
            self.freeze_until[(quote.provider, "__market__")] = (
                now + self.cfg.shock_cooldown_seconds
            )
        if key in self.dirty:
            self.metrics["coalesced_updates"] += 1
        self.latest[key] = self.dirty[key] = quote
        self.metrics["accepted_quotes"] += 1
        return True

    def history_for(self, provider, symbol):
        return list(self.history.get((provider, symbol), ()))

    def _sample(self, q):
        self.analysis.record(q)
        key = (q.provider, q.symbol)
        history = self.history.setdefault(key, deque(maxlen=self.cfg.history_limit))
        if (
            history
            and q.exchange_ts - history[-1].exchange_ts > self.cfg.max_gap_seconds
        ):
            history.clear()
            self.metrics["history_gap_resets"] += 1
        bucket = int(q.exchange_ts // self.cfg.sample_seconds)
        if (
            history
            and int(history[-1].exchange_ts // self.cfg.sample_seconds) == bucket
        ):
            history[-1] = q
        else:
            history.append(q)

    def market_block(self, provider, now):
        moves = []
        for (venue, symbol), history in self.history.items():
            if venue != provider or len(history) < 2:
                continue
            q = self.latest[(venue, symbol)]
            if not q.fresh(now, self.cfg.quote_max_age_seconds):
                continue
            base = next(
                (p for p in history if p.exchange_ts >= q.exchange_ts - 60), history[-1]
            )
            move = q.mid / base.mid - 1
            moves.append(move)
            if symbol == "BTC-USD" and move <= -self.cfg.market_shock_fraction:
                self.freeze_until[(provider, "__market__")] = (
                    now + self.cfg.shock_cooldown_seconds
                )
        if len(moves) >= 3 and median(moves) <= -self.cfg.market_shock_fraction:
            self.freeze_until[(provider, "__market__")] = (
                now + self.cfg.shock_cooldown_seconds
            )
        return self.freeze_until.get((provider, "__market__"), 0) > now

    def _quote(self, account, symbol):
        return self.latest.get((account.provider, symbol))

    def liquidation(self, provider, bid, qty):
        return (
            qty
            * bid
            * (1 - self.cfg.slippage_bps / 10_000)
            * (1 - self.cfg.fee_bps[provider] / 10_000)
        )

    def mark(self, account):
        gross = net = 0.0
        for symbol, pos in account.positions.items():
            q = self._quote(account, symbol)
            if q and q.exchange_ts > pos.mark_ts:
                pos.last_bid, pos.mark_ts = q.bid, q.exchange_ts
            gross += pos.qty * pos.last_bid
            net += self.liquidation(account.provider, pos.last_bid, pos.qty)
        account.equity = account.cash + net
        account.peak = max(account.peak, account.equity)
        dd = max(0.0, 1 - account.equity / account.peak)
        account.max_drawdown = max(account.max_drawdown, dd)
        if dd >= self.cfg.max_drawdown:
            account.halted = True
            for symbol, order in list(account.orders.items()):
                if order.side == "BUY":
                    self.finish_order(account, symbol, "CANCELED_DRAWDOWN")
        return gross

    def finish_order(self, account, symbol, status):
        order = account.orders.pop(symbol)
        order.status = status
        self.order_events[order.id] = asdict(order)

    def cancel_all(self, reason="CANCELED_STOP"):
        for account in self.accounts.values():
            for symbol in list(account.orders):
                self.finish_order(account, symbol, reason)

    def _entry_block(self, account, q, now):
        if account.halted:
            return "Cartera bloqueada por límite de drawdown; requiere investigación en una cartera nueva."
        if not q.fresh(now, self.cfg.quote_max_age_seconds):
            return "Cotización vencida."
        benchmark = self.latest.get((account.provider, "BTC-USD"))
        if benchmark is None or not benchmark.fresh(
            now, self.cfg.quote_max_age_seconds
        ):
            return "Sin referencia BTC fresca del mismo proveedor."
        if self.freeze_until.get((account.provider, q.symbol), 0) > now:
            return "Caída anormal sin causa verificada: compras en cuarentena temporal."
        if self.market_block(account.provider, now):
            return (
                "Caída general del mercado observado: compras en cuarentena temporal."
            )
        if q.spread_bps > self.cfg.max_spread_bps:
            return "Spread superior al límite."
        if min(q.bid * q.bid_qty, q.ask * q.ask_qty) < self.cfg.min_liquidity_usd:
            return "Liquidez visible insuficiente."
        for symbol in account.positions:
            held = self._quote(account, symbol)
            if held is None or not held.fresh(now, self.cfg.quote_max_age_seconds):
                return f"Falta una cotización fresca para la posición {symbol}; se bloquean nuevas compras."
        if now < account.cooldowns.get(q.symbol, 0):
            return "Periodo de espera después de una salida."
        return None

    def budget(self, account, q, now, signal=None, *, exclude_order=None):
        """Includes reservations, costs, correlated pending orders and current exposure."""
        block = self._entry_block(account, q, now)
        if block:
            return 0.0, block
        buys = [
            o
            for o in account.orders.values()
            if o.side == "BUY" and o.id != exclude_order
        ]
        occupied = set(account.positions) | {o.symbol for o in buys}
        if q.symbol not in occupied and len(occupied) >= self.cfg.max_positions:
            return 0.0, "Máximo de posiciones, incluidas las entradas reservadas."
        gross = sum(pos.qty * pos.last_bid for pos in account.positions.values())
        reserved = sum(o.budget for o in buys)
        asset_gross = (
            account.positions[q.symbol].qty * account.positions[q.symbol].last_bid
            if q.symbol in account.positions
            else 0.0
        )
        capacity = min(
            account.cash - account.equity * self.cfg.cash_reserve - reserved,
            account.equity * self.cfg.max_category_weight - gross - reserved,
            account.equity * self.cfg.max_asset_weight - asset_gross,
        )
        corr_exposure = asset_gross
        for symbol in sorted(occupied - {q.symbol}):
            rho = aligned_correlation(
                self.analysis.closed_for(account.provider, q.symbol, now),
                self.analysis.closed_for(account.provider, symbol, now),
                self.cfg.analysis_interval_seconds,
                self.cfg.min_correlation_samples,
            )
            if rho is None:
                return (
                    0.0,
                    f"Correlación con {symbol} incierta: faltan intervalos comunes con variación.",
                )
            if abs(rho) >= self.cfg.correlation_limit:
                pos = account.positions.get(symbol)
                corr_exposure += (pos.qty * pos.last_bid if pos else 0.0) + sum(
                    o.budget for o in buys if o.symbol == symbol
                )
        capacity = min(
            capacity, account.equity * self.cfg.max_correlated_weight - corr_exposure
        )
        if signal:
            cost_risk = (
                self.cfg.stop_net_bps / 10_000
                + 2
                * (self.cfg.fee_bps[account.provider] + self.cfg.slippage_bps)
                / 10_000
            )
            risk_budget = account.equity * self.cfg.risk_per_trade / cost_risk
            volatility_scale = min(
                1.0, 0.003 / max(signal.features.get("volatility", 0), 0.000001)
            )
            capacity = min(
                capacity, risk_budget * volatility_scale * signal.score / 100 * 0.5
            )
        return max(0.0, capacity), "Presupuesto de riesgo, reserva y concentración."

    def queue(self, account, q, side, now, reason, signal=None):
        if q.symbol in account.orders:
            return False, "Ya existe una orden pendiente para el activo."
        account.order_times = [t for t in account.order_times if now - t < 60]
        if side == "BUY" and len(account.order_times) >= self.cfg.max_orders_per_minute:
            return (
                False,
                "Límite de nuevas órdenes por minuto (las salidas de riesgo tienen prioridad).",
            )
        if side == "BUY":
            budget, why = self.budget(account, q, now, signal)
            if budget < self.cfg.min_order_usd:
                return False, why
            price = q.ask * (1 + self.cfg.slippage_bps / 10_000)
            qty = budget / (price * (1 + self.cfg.fee_bps[account.provider] / 10_000))
        else:
            qty, budget = account.positions[q.symbol].qty, 0.0
        identity = hashlib.sha256(
            f"{account.id}:{q.symbol}:{side}:{q.key}".encode()
        ).hexdigest()[:32]
        order = Order(
            identity,
            account.id,
            q.symbol,
            side,
            now,
            q.exchange_ts,
            q.key,
            now + self.cfg.order_ttl_seconds,
            qty,
            qty,
            budget,
            reason,
        )
        account.orders[q.symbol] = order
        account.order_times.append(now)
        self.order_events[identity] = asdict(order)
        return True, reason

    def fill(self, account, q, now):
        order = account.orders.get(q.symbol)
        if not order:
            return
        if now >= order.expires_at:
            self.finish_order(account, q.symbol, "EXPIRED")
            return
        # A quote already received/buffered before the decision cannot fill it.
        if not (
            q.key not in (order.decision_key, order.last_fill_key)
            and q.exchange_ts > max(order.decision_ts, order.created_at)
            and q.received_ts > order.created_at
            and q.fresh(now, self.cfg.quote_max_age_seconds)
        ):
            return
        cfg = self.cfg
        if order.side == "BUY":
            # Recheck the actual signal, costs and risks at the future fill quote.
            signal = evaluate(
                account.strategy,
                self.analysis.points_for(q),
                cfg,
                account.provider,
            )
            capacity, why = self.budget(account, q, now, exclude_order=order.id)
            if signal.action != "BUY" or capacity <= 0:
                self.finish_order(account, q.symbol, "CANCELED_RISK_OR_SIGNAL")
                return
            price = q.ask * (1 + cfg.slippage_bps / 10_000)
            unit_cost = price * (1 + cfg.fee_bps[account.provider] / 10_000)
            qty = min(
                order.remaining,
                q.ask_qty * cfg.top_book_participation,
                min(capacity, order.budget) / unit_cost,
            )
            if qty * unit_cost < 0.01:
                return
            fee = qty * price * cfg.fee_bps[account.provider] / 10_000
            spent = qty * price + fee
            account.cash -= spent
            order.budget = max(0, order.budget - spent)
            pnl = 0.0
            if q.symbol in account.positions:
                pos = account.positions[q.symbol]
                pos.entry_price = (pos.entry_price * pos.qty + qty * price) / (
                    pos.qty + qty
                )
                pos.qty += qty
                pos.basis += spent
            else:
                account.positions[q.symbol] = Position(
                    q.symbol, qty, spent, now, price, q.bid, q.exchange_ts
                )
        else:
            pos = account.positions.get(q.symbol)
            if not pos:
                self.finish_order(account, q.symbol, "CANCELED_NO_POSITION")
                return
            qty = min(order.remaining, pos.qty, q.bid_qty * cfg.top_book_participation)
            price = q.bid * (1 - cfg.slippage_bps / 10_000)
            fee = qty * price * cfg.fee_bps[account.provider] / 10_000
            basis = pos.basis * qty / pos.qty
            pnl = qty * price - fee - basis
            account.cash += qty * price - fee
            pos.realized += pnl
            pos.basis -= basis
            pos.qty -= qty
            if pos.qty <= max(1e-12, qty * 1e-10):
                self.closed.append(
                    {
                        "id": order.id,
                        "account": account.id,
                        "symbol": q.symbol,
                        "opened_at": pos.opened_at,
                        "closed_at": now,
                        "pnl": pos.realized,
                    }
                )
                del account.positions[q.symbol]
                account.cooldowns[q.symbol] = now + cfg.cooldown_seconds
        order.filled_qty += qty
        order.last_fill_key = q.key
        order.remaining = max(0.0, order.remaining - qty)
        self.events.append(
            {
                "id": f"{order.id}:{q.key}",
                "account": account.id,
                "order_id": order.id,
                "symbol": q.symbol,
                "side": order.side,
                "decision_ts": order.created_at,
                "decision_quote_ts": order.decision_ts,
                "quote_ts": q.exchange_ts,
                "received_ts": q.received_ts,
                "filled_at": now,
                "qty": qty,
                "price": price,
                "bid": q.bid,
                "ask": q.ask,
                "fee": fee,
                "realized_pnl": pnl,
                "cash_after": account.cash,
                "reason": order.reason,
            }
        )
        if order.remaining <= max(1e-12, order.qty * 1e-9):
            self.finish_order(account, q.symbol, "FILLED")
        else:
            order.status = "PARTIAL"
            self.order_events[order.id] = asdict(order)
        self.metrics["simulated_fills"] += 1

    def step(self, now, *, running):
        """At most one observed update per symbol per cadence; never manufacture ticks."""
        fresh = [
            q
            for _, q in sorted(self.dirty.items())
            if q.fresh(now, self.cfg.quote_max_age_seconds)
        ]
        self.dirty.clear()
        for q in fresh:
            self._sample(q)
        # Refresh systemic quarantine before any portfolio can fill a pending buy.
        for provider in self.cfg.providers:
            self.market_block(provider, now)
        for account in self.accounts.values():
            for symbol, order in list(account.orders.items()):
                if now >= order.expires_at:
                    self.finish_order(account, symbol, "EXPIRED")
            self.mark(account)
            venue_quotes = [q for q in fresh if q.provider == account.provider]
            if running:
                for q in venue_quotes:
                    self.fill(account, q, now)
                self.mark(account)
            for q in venue_quotes:
                history = self.analysis.points_for(q)
                signal = evaluate(
                    account.strategy,
                    history,
                    self.cfg,
                    account.provider,
                    in_position=q.symbol in account.positions,
                )
                if not running:
                    signal = Signal(
                        "PAUSED",
                        signal.score,
                        "Nory detenido. " + signal.reason,
                        signal.checks,
                        signal.features,
                        signal.headroom_bps,
                    )
                elif q.symbol in account.orders:
                    order = account.orders[q.symbol]
                    pos = account.positions.get(q.symbol)
                    net_bps = (
                        (
                            self.liquidation(account.provider, q.bid, pos.qty)
                            / pos.basis
                            - 1
                        )
                        * 10000
                        if pos
                        else 0
                    )
                    if (
                        order.side == "BUY"
                        and pos
                        and (net_bps <= -self.cfg.stop_net_bps or account.halted)
                    ):
                        self.finish_order(account, q.symbol, "CANCELED_RISK_OR_SIGNAL")
                        _, why = self.queue(
                            account,
                            q,
                            "SELL",
                            now,
                            f"Salida de riesgo durante una entrada parcial: {net_bps:.1f} bps netos.",
                        )
                        signal.action, signal.reason = "SELL_PENDING", why
                    else:
                        signal.action, signal.reason = "ORDER_PENDING", order.reason
                elif q.symbol in account.positions:
                    pos = account.positions[q.symbol]
                    net_bps = (
                        self.liquidation(account.provider, q.bid, pos.qty) / pos.basis
                        - 1
                    ) * 10_000
                    reason = (
                        "Stop de pérdida neta"
                        if net_bps <= -self.cfg.stop_net_bps
                        else "Objetivo de beneficio neto"
                        if net_bps >= self.cfg.profit_net_bps
                        else "Límite de drawdown de cartera"
                        if account.halted
                        else "Invalidación de la señal"
                        if signal.action == "SELL"
                        else None
                    )
                    if reason:
                        queued, why = self.queue(
                            account,
                            q,
                            "SELL",
                            now,
                            f"{reason}: {net_bps:.1f} bps netos estimados; {signal.reason}",
                        )
                        signal.action, signal.reason = (
                            ("SELL_PENDING" if queued else "HOLD"),
                            why,
                        )
                elif signal.action == "BUY":
                    queued, why = self.queue(
                        account, q, "BUY", now, signal.reason, signal
                    )
                    signal.action, signal.reason = (
                        ("BUY_PENDING" if queued else "BLOCK_RISK"),
                        why,
                    )
                elif running:
                    block = self._entry_block(account, q, now)
                    if block and account.strategy != "cash":
                        signal.action, signal.reason = (
                            "BLOCK_RISK",
                            block + " " + signal.reason,
                        )
                self.decisions[(account.id, q.symbol)] = {
                    "account": account.id,
                    "symbol": q.symbol,
                    "quote_ts": q.exchange_ts,
                    "observed_at": now,
                    **signal.as_dict(),
                }
                self.activity[(account.id, signal.action)] += 1
                if running:
                    self.activity[(account.id, "EVALUATED")] += 1
                    if signal.features.get("analysis_span_seconds", 0) > 0:
                        self.activity[(account.id, "READY_EVALUATED")] += 1
                    if signal.checks.get("margen_sobre_costes") is False:
                        self.activity[(account.id, "COST_FILTER")] += 1
        if fresh:
            self.metrics["cycles_with_new_quotes"] += 1
        return fresh

    def drain_events(self):
        result = self.events, list(self.order_events.values()), self.closed
        self.events, self.order_events, self.closed = [], {}, []
        return result
