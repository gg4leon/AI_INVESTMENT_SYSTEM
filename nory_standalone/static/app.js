"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  trend: "Seguimiento de tendencia",
  mean_reversion: "Reversión a la media",
  momentum: "Momentum",
  breakout: "Ruptura de rango",
  cash: "Defensiva · efectivo",
};
const actions = {
  PAUSED: "Detenido",
  WARMUP: "Preparando historial",
  WAIT: "Conservar efectivo",
  HOLD: "Mantener posición",
  BUY: "Entrada candidata",
  SELL: "Salida candidata",
  BUY_PENDING: "Compra pendiente",
  SELL_PENDING: "Venta pendiente",
  ORDER_PENDING: "Orden pendiente",
  BLOCK_COSTS: "Costes elevados",
  BLOCK_RISK: "Bloqueado por riesgo",
  STALE: "Sin precio fresco",
};
const feedNames = { coinbase: "Coinbase Exchange", kraken: "Kraken" };
const feedLabels = {
  CONNECTING: "Conectando",
  WAITING_FOR_QUOTES: "Esperando precios",
  LIVE: "Recibiendo datos",
  RECONNECTING: "Reconectando",
  STOPPED: "Detenido",
};
const orderLabels = {
  PENDING: "Pendiente",
  PARTIAL: "Parcial",
  FILLED: "Completada",
  EXPIRED: "Vencida",
  CANCELED_STOP: "Cancelada al detener",
  CANCELED_SHUTDOWN: "Cancelada al cerrar",
  CANCELED_RESTART: "Cancelada al reiniciar",
  CANCELED_EMERGENCY: "Cancelada por emergencia",
  CANCELED_DRAWDOWN: "Cancelada por drawdown",
  CANCELED_RISK_OR_SIGNAL: "Cancelada por riesgo o señal",
  CANCELED_NO_POSITION: "Sin posición",
};
const names = {
  BTC: "Bitcoin",
  ETH: "Ethereum",
  SOL: "Solana",
  XRP: "XRP",
  ADA: "Cardano",
  DOGE: "Dogecoin",
  AVAX: "Avalanche",
  LINK: "Chainlink",
  LTC: "Litecoin",
  BCH: "Bitcoin Cash",
  DOT: "Polkadot",
};
const fmt = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "USD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 2,
});
const num = (n, d = 2) =>
  n == null || !Number.isFinite(Number(n))
    ? "—"
    : Number(n).toLocaleString("es-MX", {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      });
const money = (n) =>
  n == null || !Number.isFinite(Number(n)) ? "—" : fmt.format(n);
const signed = (n, d = 2) => (n == null ? "—" : (n > 0 ? "+" : "") + num(n, d));
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (ts) =>
  ts
    ? new Date(ts * 1000).toLocaleString("es-MX", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
const price = (n) =>
  n == null ? "—" : "$" + num(n, n < 1 ? 5 : n < 100 ? 3 : 2);
let state = null,
  session = null,
  stream = null,
  view = "dashboard",
  operation = "positions",
  intelligence = "performance",
  selectedSymbol = "BTC-USD",
  connected = false,
  controlBusy = false;
const headings = {
  dashboard: [
    "Tu capital, con perspectiva.",
    "El pulso de tus mercados. Cada decisión, explicada.",
    "Dashboard",
  ],
  markets: [
    "El mercado, sin ruido.",
    "Cotizaciones auténticas, señales trazables y contexto para cada activo.",
    "Mercados",
  ],
  operations: [
    "Cada movimiento, registrado.",
    "Órdenes, costes y resultados. Una historia completa del capital ficticio.",
    "Operaciones",
  ],
  intelligence: [
    "Decisiones con evidencia.",
    "Compara hipótesis. Entiende los límites. Evalúa lo que realmente funciona.",
    "Inteligencia y rendimiento",
  ],
};

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 5500);
}
function showError(message) {
  $("error-banner").textContent = message;
  $("error-banner").classList.toggle("hidden", !message);
}
function navigate(next) {
  if (!headings[next]) return;
  view = next;
  document
    .querySelectorAll(".view")
    .forEach((el) => el.classList.toggle("hidden", el.id !== next + "-view"));
  document.querySelectorAll("[data-view]").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === next);
    el.setAttribute(
      "aria-current",
      el.dataset.view === next ? "page" : "false",
    );
  });
  $("page-title").textContent = headings[next][0];
  $("page-subtitle").textContent = headings[next][1];
  $("breadcrumb").textContent = headings[next][2];
  history.replaceState(null, "", "#" + next);
  renderSection();
}
function tag(action) {
  return `<span class="decision-tag ${["BLOCK_RISK", "STALE", "SELL_PENDING"].includes(action) ? "alert" : ""}">${esc(actions[action] || action)}</span>`;
}
function table(
  headers,
  rows,
  empty = "Aún no hay registros.",
  sub = "Los resultados aparecerán cuando existan observaciones u operaciones registradas.",
) {
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.join("") : `<tr><td colspan="${headers.length}" class="empty-state"><strong>${esc(empty)}</strong>${esc(sub)}</td></tr>`}</tbody></table>`;
}
function asset(symbol) {
  const short = symbol.split("-")[0];
  return `<span class="asset"><span class="asset-icon">${esc(short.slice(0, 1))}</span><span><strong>${esc(short)}<span class="muted"> / USD</span></strong><small>${esc(names[short] || short)}</small></span></span>`;
}
function updateControls() {
  const running = state?.running;
  $("start").disabled =
    !connected || controlBusy || !!running || !!state?.fatal_error;
  $("stop").disabled = !connected || controlBusy || !running;
}
async function command(path, body) {
  controlBusy = true;
  updateControls();
  try {
    const response = await fetch("/api/" + path, {
      method: "POST",
      headers: {
        "X-Nory-Token": session.token,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(result.detail || "No se pudo completar la acción.");
    toast(result.reason || "Acción registrada.");
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    controlBusy = false;
    updateControls();
  }
}
async function refresh() {
  const r = await fetch(
    `/api/status?provider=${encodeURIComponent($("provider").value)}&strategy=${encodeURIComponent($("strategy").value)}`,
  );
  if (!r.ok) throw Error("El motor no respondió.");
  state = await r.json();
  render();
}
function connectStream() {
  if (stream) stream.close();
  const p = $("provider").value,
    s = $("strategy").value;
  localStorage.setItem("nory-provider", p);
  localStorage.setItem("nory-strategy", s);
  connected = false;
  state = null;
  updateControls();
  stream = new EventSource(
    `/api/stream?provider=${encodeURIComponent(p)}&strategy=${encodeURIComponent(s)}`,
  );
  stream.onopen = () => {
    connected = true;
    $("offline-banner").classList.add("hidden");
    $("connection").textContent = "Panel conectado";
    updateControls();
  };
  stream.onerror = () => {
    connected = false;
    $("offline-banner").classList.remove("hidden");
    $("connection").textContent = "Reconectando con el panel";
    updateControls();
  };
  stream.onmessage = (event) => {
    try {
      state = JSON.parse(event.data);
      render();
    } catch (error) {
      showError("No se pudo mostrar la actualización: " + error.message);
    }
  };
}

function render() {
  if (!state) return;
  const a = state.state,
    st = state.stats;
  $("capital").textContent = money(a.equity);
  $("initial-capital").textContent = "Inicial: " + money(a.initial);
  $("net-pnl").textContent = (st.net_pnl > 0 ? "+" : "") + money(st.net_pnl);
  $("net-pnl").classList.toggle("negative", st.net_pnl < 0);
  $("return-pct").textContent =
    signed((st.net_pnl / a.initial) * 100) + " % · neto estimado";
  $("cash").textContent = money(a.cash);
  $("cash-note").textContent =
    num((a.cash / a.equity) * 100, 1) + " % en efectivo";
  $("position-count").textContent = Object.keys(a.positions)
    .length.toString()
    .padStart(2, "0");
  $("position-value").textContent =
    "Liquidación estimada: " + money(a.equity - a.cash);
  $("engine-status").textContent = state.fatal_error
    ? "Error del motor"
    : state.running
      ? "Nory en ejecución"
      : "Nory detenido";
  $("engine-dot").classList.toggle("active", state.running);
  $("active-markets").textContent =
    `${state.markets.filter((m) => m.fresh).length} de ${state.markets.length} mercados frescos`;
  $("control-scope").textContent =
    `Control global · ${state.config.providers.length * 5} carteras independientes`;
  $("diagnosis").textContent = state.diagnosis;
  $("diagnosis-label").textContent = !state.running
    ? "EN ESPERA"
    : a.halted
      ? "BLOQUEO DE RIESGO"
      : "ANÁLISIS CONTINUO";
  $("risk-state").textContent = a.halted
    ? "Bloqueado"
    : state.stale_positions.length
      ? "Posiciones sin precio fresco"
      : "Límites activos";
  $("fee-label").textContent =
    num(state.config.fee_bps[a.provider], 0) + " bps + deslizamiento";
  $("drawdown").textContent = num(a.max_drawdown * 100) + " %";
  const warning = state.fatal_error
    ? state.fatal_error
    : state.stale_positions.length
      ? "Valoración con precios antiguos en: " +
        state.stale_positions.join(", ") +
        ". El resultado actual es una estimación con última cotización conocida."
      : "";
  showError(warning);
  for (const [id, kind] of [
    ["export-quotes", "quotes"],
    ["export-fills", "fills"],
  ])
    $(id).href =
      `/api/export/${kind}?provider=${encodeURIComponent(a.provider)}&strategy=${encodeURIComponent(a.strategy)}`;
  updateControls();
  renderSection();
}
function renderSection() {
  if (!state) return;
  if (view === "dashboard") renderDashboard();
  if (view === "markets") renderMarkets();
  if (view === "operations") renderOperations();
  if (view === "intelligence") renderIntelligence();
}
function renderChart() {
  const rows = state.equity.filter((r) => Number.isFinite(r.equity)),
    initial = state.state.initial;
  if (!rows.length) {
    $("equity-chart").innerHTML =
      '<div class="chart-empty"><svg viewBox="0 0 48 36" fill="none" stroke="currentColor"><path d="M2 29h44M5 5v24M8 24l8-8 8 5 9-12 10 3"/></svg><strong>Tu historial comienza aquí.</strong>La gráfica se construye con las observaciones registradas.</div>';
    $("chart-range").textContent = "Sin observaciones registradas";
    return;
  }
  const w = 800,
    h = 235,
    l = 61,
    r = 17,
    t = 24,
    b = 31,
    all = [initial, ...rows.map((x) => x.equity)],
    low = Math.min(...all),
    high = Math.max(...all),
    pad = Math.max((high - low) * 0.18, initial * 0.0005);
  const min = low - pad,
    max = high + pad;
  const y = (v) => h - b - ((v - min) / (max - min)) * (h - t - b);
  const x = (i) =>
    l + (rows.length === 1 ? 0.5 : i / (rows.length - 1)) * (w - l - r);
  const path = rows
    .map(
      (v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v.equity).toFixed(2)}`,
    )
    .join(" ");
  let grid = "";
  for (let i = 0; i < 5; i++) {
    const val = min + ((max - min) * i) / 4,
      yy = y(val);
    grid += `<line x1="${l}" y1="${yy}" x2="${w - r}" y2="${yy}" stroke="#272727" stroke-dasharray="2 5"/><text x="${l - 10}" y="${yy + 3}" text-anchor="end" fill="#717171" font-size="9">${esc(money(val))}</text>`;
  }
  let ticks = "";
  [0, Math.floor((rows.length - 1) / 2), rows.length - 1]
    .filter((v, i, a) => a.indexOf(v) === i)
    .forEach((i) => {
      ticks += `<text x="${x(i)}" y="${h - 8}" text-anchor="middle" fill="#777" font-size="9">${esc(new Date(rows[i].observed_at * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" }))}</text>`;
    });
  $("equity-chart").innerHTML =
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Capital neto registrado"><defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ff0d00" stop-opacity=".15"/><stop offset="1" stop-color="#ff0d00" stop-opacity="0"/></linearGradient></defs>${grid}<line x1="${l}" x2="${w - r}" y1="${y(initial)}" y2="${y(initial)}" stroke="#777" stroke-dasharray="5 5"/><path d="${path} L${x(rows.length - 1)},${h - b} L${x(0)},${h - b} Z" fill="url(#equity-fill)"/><path d="${path}" fill="none" stroke="#ff0d00" stroke-width="2" vector-effect="non-scaling-stroke"/><circle cx="${x(rows.length - 1)}" cy="${y(rows.at(-1).equity)}" r="3" fill="#fff"/>${ticks}</svg>`;
  $("chart-range").textContent =
    date(rows[0].observed_at) + " — " + date(rows.at(-1).observed_at);
}
function marketTable(markets, compact) {
  return table(
    compact
      ? ["ACTIVO", "PRECIO", "VAR. LOCAL", "DECISIÓN"]
      : [
          "ACTIVO",
          "PRECIO",
          "VAR. LOCAL",
          "SPREAD",
          "PRIORIDAD",
          "RIESGO",
          "DECISIÓN",
        ],
    markets.map(
      (m) =>
        `<tr data-symbol="${esc(m.symbol)}" tabindex="0" aria-label="Ver detalle de ${esc(m.symbol)}"><td>${asset(m.symbol)}</td><td>${price(m.price)}${!m.fresh ? '<small class="muted"> · antiguo</small>' : ""}</td><td class="${m.change_pct < 0 ? "negative" : ""}">${signed(m.change_pct)} %</td>${compact ? "" : `<td>${num(m.spread_bps, 1)} bps</td><td>${num(m.score, 0)} / 100</td><td>${esc(m.risk)}</td>`}<td>${tag(m.action)}</td></tr>`,
    ),
    "Esperando cotizaciones",
    "El proveedor aún no ha enviado precios utilizables.",
  );
}
function renderDashboard() {
  renderChart();
  $("dashboard-markets").innerHTML = marketTable(
    state.markets.slice(0, 5),
    true,
  );
  $("feed-cards").innerHTML = state.config.providers
    .map((p) => {
      const f = state.feeds[p];
      return `<div class="feed-card"><div class="feed-title"><span>${esc(feedNames[p])}</span><span class="feed-state ${f?.state === "LIVE" ? "live" : ""}">${esc(feedLabels[f?.state] || "Sin conexión")}</span></div><div class="feed-stats"><span>${num(f?.valid_quotes ?? 0, 0)} cotizaciones recibidas</span><span>${f?.latency_ms == null ? "Sin latencia medida" : num(f.latency_ms, 0) + " ms"}</span></div>${f?.error ? `<div class="feed-error">${esc(f.error)}</div>` : ""}</div>`;
    })
    .join("");
}
function renderMarkets() {
  const search = $("market-search").value.trim().toLowerCase(),
    risk = $("risk-filter").value;
  const markets = state.markets.filter(
    (m) =>
      (m.symbol.toLowerCase().includes(search) ||
        (names[m.symbol.split("-")[0]] || "").toLowerCase().includes(search)) &&
      (risk === "all" || m.risk === risk),
  );
  $("full-markets").innerHTML = marketTable(markets, false);
  const m = state.markets.find((m) => m.symbol === selectedSymbol);
  if (!m) return;
  $("market-detail").innerHTML =
    `<div class="eyebrow">TRAZABILIDAD DE LA SEÑAL · ${esc(m.symbol)}</div><h2>${esc(names[m.symbol.split("-")[0]] || m.symbol)} ${tag(m.action)}</h2><p class="muted small">${esc(m.reason)}</p><div class="detail-grid"><div class="detail-cell">Antigüedad de la cotización<strong>${num(m.age_seconds, 1)} s</strong></div><div class="detail-cell">Muestras genuinas por intervalo<strong>${num(m.samples, 0)} / ${state.config.min_history}</strong></div><div class="detail-cell">Margen heurístico · no pronóstico<strong>${num(m.headroom_bps, 1)} bps</strong></div><div class="detail-cell">Coste estimado ida/vuelta<strong>${num(m.features.round_trip_cost_bps ?? 2 * (state.config.fee_bps[state.state.provider] + state.config.slippage_bps) + (m.spread_bps ?? 0), 1)} bps</strong></div></div><div class="checks">${Object.entries(
      m.checks,
    )
      .map(
        ([k, v]) =>
          `<span class="check ${v ? "" : "failed"}">${v ? "Cumple" : "No cumple"} · ${esc(k.replaceAll("_", " "))}</span>`,
      )
      .join(
        "",
      )}</div><p class="panel-note">Ventana local: ${num(m.samples * state.config.sample_seconds, 0)} s nominales, con huecos posibles. RSI: ${num(m.features.rsi, 1)} · Momentum: ${num(m.features.momentum_bps, 1)} bps · Volumen de 24 h reportado: ${num(m.quote?.volume_24h, 2)} unidades base. Sin contexto de noticias verificado.</p>`;
}
function renderOperations() {
  const a = state.state;
  let headers, rows, empty, sub;
  const title = {
    positions: "Posiciones abiertas",
    orders: "Órdenes pendientes e historial",
    fills: "Ejecuciones ficticias",
    closed: "Operaciones cerradas",
  };
  $("operations-title").textContent = title[operation];
  if (operation === "positions") {
    headers = [
      "ACTIVO",
      "CANTIDAD",
      "COSTE CON COMISIÓN",
      "VALOR NETO ESTIMADO",
      "P/L ABIERTO",
      "APERTURA",
    ];
    rows = Object.entries(a.positions).map(([s, p]) => {
      const value =
        p.qty *
        p.last_bid *
        (1 - state.config.slippage_bps / 10000) *
        (1 - state.config.fee_bps[a.provider] / 10000);
      return `<tr><td>${asset(s)}</td><td>${num(p.qty, 8)}</td><td>${money(p.basis)}</td><td>${money(value)}</td><td class="${value - p.basis < 0 ? "negative" : ""}">${money(value - p.basis)}</td><td>${date(p.opened_at)}</td></tr>`;
    });
    empty = "El capital puede esperar.";
    sub =
      "No hay posiciones abiertas en esta cartera. Nory solo entra si la señal supera costes y controles de riesgo.";
  } else if (operation === "orders") {
    headers = [
      "FECHA",
      "ACTIVO",
      "LADO",
      "CANTIDAD RESTANTE",
      "ESTADO",
      "EXPLICACIÓN",
    ];
    rows = state.orders.map(
      (o) =>
        `<tr><td>${date(o.created_at)}</td><td>${esc(o.symbol)}</td><td>${o.side === "BUY" ? "Compra" : "Venta"}</td><td>${num(o.remaining, 8)}</td><td><span class="decision-tag">${esc(orderLabels[o.status] || o.status)}</span></td><td class="wrap">${esc(o.reason)}</td></tr>`,
    );
    empty = "Sin órdenes registradas.";
    sub = "Las entradas se reservan antes de esperar una cotización posterior.";
  } else if (operation === "fills") {
    headers = [
      "EJECUCIÓN FICTICIA",
      "ACTIVO",
      "LADO",
      "CANTIDAD",
      "PRECIO",
      "COMISIÓN",
      "P/L REALIZADO",
      "EXPLICACIÓN",
    ];
    rows = state.fills.map(
      (f) =>
        `<tr><td>${date(f.filled_at)}</td><td>${esc(f.symbol)}</td><td>${f.side === "BUY" ? "Compra" : "Venta"}</td><td>${num(f.qty, 8)}</td><td>${price(f.price)}</td><td>${money(f.fee)}</td><td class="${f.realized_pnl < 0 ? "negative" : ""}">${f.side === "SELL" ? money(f.realized_pnl) : "—"}</td><td class="wrap">${esc(f.reason)}</td></tr>`,
    );
    empty = "Aún no hay ejecuciones ficticias.";
    sub = "No se fuerzan operaciones. Una orden puede vencer sin ejecutarse.";
  } else {
    headers = ["CIERRE", "ACTIVO", "APERTURA", "RESULTADO NETO", "RESULTADO"];
    rows = state.round_trips.map(
      (t) =>
        `<tr><td>${date(t.closed_at)}</td><td>${esc(t.symbol)}</td><td>${date(t.opened_at)}</td><td class="${t.pnl < 0 ? "negative" : ""}">${money(t.pnl)}</td><td>${t.pnl > 0 ? "Ganancia" : t.pnl < 0 ? "Pérdida" : "Sin ganancia ni pérdida"}</td></tr>`,
    );
    empty = "Sin operaciones completamente cerradas.";
    sub =
      "Las ventas parciales se agrupan hasta cerrar toda la posición para calcular la tasa de acierto.";
  }
  $("operations-content").innerHTML = table(headers, rows, empty, sub);
}
function statBox(label, value) {
  return `<div class="stat-box"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}
function panel(title, content, kicker = "INTELIGENCIA Y RENDIMIENTO") {
  return `<article class="panel"><div class="panel-heading"><div><div class="eyebrow">${esc(kicker)}</div><h2>${esc(title)}</h2></div></div>${content}</article>`;
}
function renderIntelligence() {
  const st = state.stats,
    a = state.state,
    cfg = state.config;
  let html = "";
  if (intelligence === "performance") {
    html =
      `<div class="stats-grid">${statBox("Ganancias realizadas · posiciones cerradas", money(st.gross_profits))}${statBox("Pérdidas realizadas · posiciones cerradas", money(st.gross_losses))}${statBox("P/L realizado · incluye ventas parciales", money(st.realized))}${statBox("P/L no realizado · neto estimado", money(st.unrealized_pnl))}${statBox("Comisiones de ejecuciones registradas", money(st.fees))}${statBox("Operaciones completamente cerradas", num(st.closed, 0))}${statBox("Operaciones ganadoras", st.win_rate_pct == null ? "Sin cierres" : num(st.win_rate_pct, 1) + " %")}${statBox("Ganancia media por operación ganadora", money(st.average_win))}${statBox("Pérdida media por operación perdedora", money(st.average_loss))}${statBox("Drawdown máximo observado", num(a.max_drawdown * 100) + " %")}${statBox("Ejecuciones · compras / ventas", `${st.fills} · ${st.buys} / ${st.sells}`)}${statBox("Exposición actual neta", num(((a.equity - a.cash) / a.equity) * 100, 1) + " %")}</div>` +
      panel(
        "Una referencia, con sus diferencias.",
        `<div class="section-text"><h3>BTC · comprar y mantener</h3><p>${state.benchmark ? `${signed(state.benchmark.return_pct)} % neto estimado. ${esc(state.benchmark.note)}` : "Aún no hay una referencia registrada del proveedor."}</p><p>La tasa de acierto usa posiciones completamente cerradas. Las comisiones acumuladas incluyen los llenados registrados; el capital neto también descuenta costes estimados de salida en posiciones abiertas.</p></div>`,
      ) +
      `<div class="detail-panel panel"><h2>Resultado por activo</h2>${table(
        ["ACTIVO", "P/L REALIZADO", "COMISIONES", "LLENADOS"],
        state.assets.map(
          (x) =>
            `<tr><td>${esc(x.symbol)}</td><td>${money(x.realized)}</td><td>${money(x.fees)}</td><td>${x.fills}</td></tr>`,
        ),
        "Sin resultados por activo",
      )}</div>`;
  } else if (intelligence === "strategies") {
    html = panel(
      "Cinco hipótesis. Carteras independientes.",
      `<div class="section-text"><p>Se evalúan simultáneamente con el mismo proveedor, cada una con ${money(cfg.initial_capital)} de capital ficticio. Las carteras no se suman y ninguna se selecciona con información futura. Las reglas activas permanecen fijas.</p></div>${table(
        [
          "ESTRATEGIA",
          "CAPITAL NETO",
          "RETORNO",
          "CIERRES",
          "COMISIONES",
          "DRAWDOWN",
        ],
        state.comparison.map(
          (x) =>
            `<tr><td>${esc(labels[x.state.strategy])}</td><td>${money(x.state.equity)}</td><td>${signed((x.state.equity / x.state.initial - 1) * 100)} %</td><td>${x.stats.closed}</td><td>${money(x.stats.fees)}</td><td>${num(x.state.max_drawdown * 100)} %</td></tr>`,
        ),
      )}<div class="section-text"><p><strong>Tendencia:</strong> alineación de medias y momentum. <strong>Reversión:</strong> desviación y rebote confirmado. <strong>Momentum:</strong> persistencia del movimiento. <strong>Ruptura:</strong> superación del máximo anterior. <strong>Defensiva:</strong> efectivo.</p><p>El margen de una señal es una heurística de amplitud observada, no una estimación validada del beneficio esperado. Los scores miden reglas cumplidas; no son probabilidades.</p></div>`,
    );
  } else if (intelligence === "risk") {
    const params = [
      ["Capital inicial por cartera", money(cfg.initial_capital)],
      [
        "Comisión por lado · supuesto",
        num(cfg.fee_bps[a.provider], 0) + " bps",
      ],
      ["Deslizamiento por lado · supuesto", num(cfg.slippage_bps, 0) + " bps"],
      ["Reserva de efectivo", num(cfg.cash_reserve * 100, 0) + " %"],
      ["Máximo por activo", num(cfg.max_asset_weight * 100, 0) + " %"],
      ["Máximo categoría cripto", num(cfg.max_category_weight * 100, 0) + " %"],
      ["Máximo de posiciones", cfg.max_positions],
      ["Riesgo objetivo por entrada", num(cfg.risk_per_trade * 100, 2) + " %"],
      ["Objetivo de beneficio neto", num(cfg.profit_net_bps, 0) + " bps"],
      [
        "Stop neto · sin garantía de ejecución",
        num(cfg.stop_net_bps, 0) + " bps",
      ],
      ["Límite de drawdown", num(cfg.max_drawdown * 100, 0) + " %"],
      ["Nuevas órdenes por minuto", cfg.max_orders_per_minute],
      [
        "Participación en mejor nivel",
        num(cfg.top_book_participation * 100, 0) + " %",
      ],
      ["Caducidad de cotizaciones", num(cfg.quote_max_age_seconds, 1) + " s"],
      ["Cadencia de evaluación", num(cfg.cadence_seconds, 1) + " s"],
      ["Límite absoluto de correlación", num(cfg.correlation_limit, 2)],
      [
        "Máximo en grupo correlacionado",
        num(cfg.max_correlated_weight * 100, 0) + " %",
      ],
    ];
    html =
      panel(
        "Límites antes que actividad.",
        `<div class="section-text"><p>Las salidas se evalúan con beneficio neto y datos frescos. Los stops son decisiones simuladas: una desconexión, falta de liquidez o salto de precio puede impedir ejecutarlos al nivel previsto.</p></div>${table(
          ["PARÁMETRO", "VALOR"],
          params.map(
            ([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`,
          ),
        )}<div class="section-text"><p>Los parámetros se fijan al crear la cartera. Para un experimento diferente, edita una copia de la configuración e inicia una base nueva según el README. Se conserva el historial de cada experimento.</p></div>`,
      ) +
      `<div class="danger-zone"><h3>Interruptor de emergencia</h3><p>Bloquea todas las carteras y cancela órdenes pendientes. Las posiciones ficticias se conservan. El bloqueo permanece después de reiniciar.</p><button id="open-emergency" class="primary">Bloquear Nory</button></div>`;
  } else if (intelligence === "research") {
    const r = state.research.find((x) => x.provider === a.provider);
    html = panel(
      "Evaluar antes de creer.",
      `<div class="section-text"><p>Reproduce el historial de cotizaciones registrado por ${esc(feedNames[a.provider])}. El 70 % inicial sirve para comparar estrategias. El 30 % posterior se evalúa con capital nuevo, después de un embargo que supera la vigencia de las órdenes. La prueba no cambia las estrategias activas.</p><p>Se requieren al menos ${cfg.min_history * 3} intervalos observados; un historial breve no permite demostrar una ventaja estadística.</p></div><div class="research-action"><button id="run-research" class="primary" ${state.research_state.running ? "disabled" : ""}>${state.research_state.running ? "Evaluando historial…" : "Evaluar historial registrado"}</button><span>Datos públicos registrados · órdenes ficticias</span></div>${state.research_state.error ? `<div class="section-text negative">${esc(state.research_state.error)}</div>` : ""}${
        r
          ? `<div class="section-text"><span class="validation-label">${esc(r.source)}</span><p>Elegida solo con entrenamiento: <strong>${esc(labels[r.selected_from_training])}</strong><br>Prueba: ${esc(r.test_start)} → ${esc(r.test_end)}<br>Embargo: ${r.embargo_seconds} s. ${r.observed_intervals} intervalos observados.</p></div>${table(
              [
                "ESTRATEGIA",
                "RETORNO TRAIN",
                "RETORNO TEST",
                "CIERRES TEST",
                "DRAWDOWN TEST",
                "EVIDENCIA · P/L MEDIO",
              ],
              Object.entries(r.holdout).map(
                ([s, t]) =>
                  `<tr><td>${esc(labels[s])}${s === r.selected_from_training ? " · elegida" : ""}</td><td>${signed(r.training[s].net_return_pct)} %</td><td>${signed(t.net_return_pct)} %</td><td>${t.closed_trades}</td><td>${num(t.max_drawdown_pct)} %</td><td>${t.evidence?.bootstrap_95_mean_usd ? `${money(t.evidence.bootstrap_95_mean_usd[0])} a ${money(t.evidence.bootstrap_95_mean_usd[1])} · IC descriptivo 95 %` : "Muestra insuficiente"}</td></tr>`,
              ),
            )}<div class="section-text">${r.limitations.map((x) => `<p>${esc(x)}</p>`).join("")}</div>`
          : '<div class="empty-state"><strong>Aún no hay evaluación de este proveedor.</strong>Deja que el historial crezca y ejecuta la validación.</div>'
      }`,
    );
  } else {
    html = panel(
      "Calidad de datos y trazabilidad.",
      `<div class="section-text"><p>${esc(state.diagnosis)}</p><p>Los ciclos indican revisiones del motor. Las cotizaciones aceptadas son mensajes nuevos del mercado; las muestras agrupan como máximo un precio observado por intervalo y activo. No se rellenan huecos ni se generan precios sintéticos.</p></div>${table(
        ["MÉTRICA", "VALOR"],
        Object.entries(state.metrics).map(
          ([k, v]) =>
            `<tr><td>${esc({ accepted_quotes: "Cotizaciones genuinas aceptadas", duplicates_or_out_of_order: "Duplicados o desordenados descartados", stale_rejected: "Cotizaciones vencidas descartadas", coalesced_updates: "Actualizaciones agrupadas entre evaluaciones", coordinator_cycles: "Ciclos del coordinador", cycles_with_new_quotes: "Ciclos con cotizaciones nuevas", simulated_fills: "Llenados ficticios", history_gap_resets: "Historiales reiniciados por huecos", unexplained_shocks: "Caídas anormales detectadas" }[k] || k)}</td><td>${num(v, 0)}</td></tr>`,
        ),
      )}<pre class="raw-log">${esc(JSON.stringify(state.feeds, null, 2))}</pre>`,
    );
  }
  $("intelligence-content").innerHTML = html;
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view],[data-open]");
  if (nav) navigate(nav.dataset.view || nav.dataset.open);
  const row = event.target.closest("[data-symbol]");
  if (row) {
    selectedSymbol = row.dataset.symbol;
    navigate("markets");
  }
  const ot = event.target.closest("[data-operation]");
  if (ot) {
    operation = ot.dataset.operation;
    document.querySelectorAll("[data-operation]").forEach((b) => {
      b.classList.toggle("active", b === ot);
      b.setAttribute("aria-selected", String(b === ot));
    });
    renderOperations();
  }
  const it = event.target.closest("[data-intelligence]");
  if (it) {
    intelligence = it.dataset.intelligence;
    document.querySelectorAll("[data-intelligence]").forEach((b) => {
      b.classList.toggle("active", b === it);
      b.setAttribute("aria-selected", String(b === it));
    });
    renderIntelligence();
  }
  if (event.target.closest("#run-research"))
    command("research", { provider: $("provider").value });
  if (event.target.closest("#open-emergency"))
    $("emergency-dialog").showModal();
});
document.addEventListener("keydown", (event) => {
  const row = event.target.closest("[data-symbol]");
  if (row && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    selectedSymbol = row.dataset.symbol;
    navigate("markets");
  }
});
$("start").addEventListener("click", () => command("start"));
$("stop").addEventListener("click", () => command("stop"));
$("provider").addEventListener("change", connectStream);
$("strategy").addEventListener("change", connectStream);
$("market-search").addEventListener("input", () => state && renderMarkets());
$("risk-filter").addEventListener("change", () => state && renderMarkets());
$("market-type").addEventListener("change", () => state && renderMarkets());
$("cancel-emergency").addEventListener("click", () =>
  $("emergency-dialog").close(),
);
$("confirm-emergency").addEventListener("click", () => {
  $("emergency-dialog").close();
  command("emergency");
});
async function boot() {
  try {
    const response = await fetch("/api/session");
    if (!response.ok) throw Error("No se pudo abrir la sesión local.");
    session = await response.json();
    $("strategy").innerHTML = Object.entries(session.strategies)
      .map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`)
      .join("");
    $("provider").innerHTML = session.config.providers
      .map((p) => `<option value="${esc(p)}">${esc(feedNames[p])}</option>`)
      .join("");
    const p = localStorage.getItem("nory-provider"),
      s = localStorage.getItem("nory-strategy");
    if (session.config.providers.includes(p)) $("provider").value = p;
    if (session.strategies[s]) $("strategy").value = s;
    navigate(location.hash.slice(1) || "dashboard");
    connectStream();
  } catch (error) {
    showError(error.message);
    updateControls();
  }
}
setInterval(
  () =>
    ($("clock").textContent = new Date().toLocaleTimeString("es-MX", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })),
  1000,
);
updateControls();
boot();
