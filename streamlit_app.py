"""AIS Investment Terminal v0.6 — interfaz local, sin ejecucion financiera real."""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.service import MARKETS, PERIODS, run_analysis
from app.storage import get_run, list_runs, save_run
from backtesting.engine import BacktestConfig


st.set_page_config(
    page_title="AIS · Investment Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
[data-testid="stAppViewContainer"] {background: #08111e;}
[data-testid="stSidebar"] {background: #101b2b; border-right: 1px solid #203047;}
.block-container {padding-top: 1.8rem; max-width: 1500px;}
h1, h2, h3 {letter-spacing: -.035em;}
h1 {font-size: clamp(2rem, 4vw, 3.1rem) !important; font-weight: 780 !important;}
[data-testid="stMetric"] {
    background: linear-gradient(145deg, #132237 0%, #0d1828 100%);
    border: 1px solid #25384b; border-radius: 13px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] {color: #93a9bc;}
[data-testid="stMetricValue"] {font-weight: 700;}
div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {
    background: #45d5b6; color: #071420; border: none; font-weight: 750;
}
.ais-eyebrow {color: #45d5b6; font-size: .75rem; letter-spacing: .18em;
    text-transform: uppercase; font-weight: 700; margin-bottom: .35rem;}
.ais-note {background: #101e30; border-left: 3px solid #45d5b6;
    border-radius: 4px; padding: .8rem 1rem; color: #b8c7d8; font-size: .88rem;}
</style>
    """,
    unsafe_allow_html=True,
)


def _figure(title: str, height: int = 390) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, font=dict(size=17, color="#e7eef7")),
        paper_bgcolor="#0c1625",
        plot_bgcolor="#0c1625",
        font=dict(color="#b9c8d9"),
        margin=dict(l=16, r=16, t=55, b=15),
        height=height,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0),
        xaxis=dict(showgrid=True, gridcolor="#203044", zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="#203044", zeroline=False),
    )
    return fig


def _equity_plot(snapshot: dict) -> go.Figure:
    frame = pd.DataFrame(snapshot["equity_curve"])
    fig = _figure("Curva de capital · simulación histórica", 430)
    if frame.empty:
        return fig
    fig.add_trace(go.Scatter(
        x=frame["timestamp"], y=frame["equity"], name="AIS · capital simulado",
        mode="lines", line=dict(color="#45d5b6", width=2.7),
    ))
    initial = float(snapshot["backtest"]["initial_cash"])
    first_close = float(frame["close"].iloc[0])
    if first_close > 0:
        comparison = frame["close"] / first_close * initial
        fig.add_trace(go.Scatter(
            x=frame["timestamp"], y=comparison, name="Comprar y mantener · bruto",
            mode="lines", line=dict(color="#96a8bd", width=1.9, dash="dash"),
        ))
    entries = frame[frame["action"] == "ENTER_LONG"]
    exits = frame[frame["action"] == "EXIT_LONG"]
    for name, points, color, symbol in (
        ("Entrada simulada", entries, "#6ce6bb", "triangle-up"),
        ("Salida simulada", exits, "#fb9d75", "triangle-down"),
    ):
        if not points.empty:
            fig.add_trace(go.Scatter(
                x=points["timestamp"], y=points["equity"],
                name=name, mode="markers",
                marker=dict(color=color, symbol=symbol, size=10),
            ))
    fig.update_yaxes(title="Unidades ficticias de cotización")
    return fig


def _market_plot(snapshot: dict) -> go.Figure:
    frame = pd.DataFrame(snapshot["price_history"])
    fig = _figure(f'{snapshot["symbol"]} · precio y medias móviles', 470)
    if frame.empty:
        return fig
    fig.add_trace(go.Candlestick(
        x=frame["timestamp"], open=frame["Open"],
        high=frame["High"], low=frame["Low"], close=frame["Close"],
        name="OHLC",
        increasing_line_color="#45d5b6", decreasing_line_color="#f18b8b",
    ))
    for col, name, color in (
        ("SMA_10", "SMA 10", "#e3c66e"),
        ("SMA_30", "SMA 30", "#77a6ee"),
    ):
        if col in frame:
            fig.add_trace(go.Scatter(
                x=frame["timestamp"], y=frame[col], name=name,
                mode="lines", line=dict(color=color, width=1.8),
            ))
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def _rsi_plot(snapshot: dict) -> go.Figure:
    frame = pd.DataFrame(snapshot["price_history"])
    fig = _figure("RSI · 14 periodos", 260)
    if "RSI_14" in frame:
        fig.add_trace(go.Scatter(
            x=frame["timestamp"], y=frame["RSI_14"], name="RSI 14",
            mode="lines", line=dict(color="#d8bafa", width=2),
        ))
        fig.add_hline(y=70, line_dash="dash", line_color="#f18b8b")
        fig.add_hline(y=30, line_dash="dash", line_color="#45d5b6")
        fig.update_yaxes(range=[0, 100])
    return fig


def _macd_plot(snapshot: dict) -> go.Figure:
    frame = pd.DataFrame(snapshot["price_history"])
    fig = _figure("MACD · momentum", 280)
    if "MACD" in frame:
        fig.add_trace(go.Scatter(
            x=frame["timestamp"], y=frame["MACD"], name="MACD",
            line=dict(color="#45d5b6", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=frame["timestamp"], y=frame["MACD_SIGNAL"], name="Señal",
            line=dict(color="#d1a1f1", width=2),
        ))
        fig.add_trace(go.Bar(
            x=frame["timestamp"], y=frame["MACD_HIST"], name="Histograma",
            marker_color="#7b94ac", opacity=.45,
        ))
    return fig


def _number(value: float | None, suffix: str = "", digits: int = 2) -> str:
    return "N/D" if value is None else f"{value:,.{digits}f}{suffix}"


with st.sidebar:
    st.markdown('<div class="ais-eyebrow">AIS / CONTROL CENTER</div>', unsafe_allow_html=True)
    st.subheader("Configurar simulación")
    st.caption("Todos los importes son ficticios. Ninguna opción mueve dinero.")
    with st.form("new_run_form"):
        symbol = st.selectbox(
            "Mercado", options=list(MARKETS),
            format_func=lambda x: f"{x} · {MARKETS[x]}",
        )
        data_label = st.radio(
            "Fuente de datos",
            ["Demo sintética (sin Internet)", "Históricos de Yahoo"],
            help="La demo utiliza precios inventados, siempre identificados.",
        )
        period = st.selectbox("Historial real", PERIODS, index=1)
        st.markdown("**Reglas del backtest**")
        initial_cash = st.number_input(
            "Capital ficticio (unidades)", min_value=100.0,
            max_value=1_000_000.0, value=10_000.0, step=500.0,
        )
        allocation_pct = st.slider("Asignación por entrada", 5, 100, 25, 5)
        stop_pct = st.slider("Pérdida de cierre para salida", 1, 30, 8, 1)
        fee_bps = st.number_input(
            "Comisión por lado (bps)", 0.0, 200.0, 10.0, 1.0,
        )
        slippage_bps = st.number_input(
            "Deslizamiento por lado (bps)", 0.0, 200.0, 5.0, 1.0,
        )
        execute = st.form_submit_button(
            "▶ Ejecutar análisis y simulación", type="primary", use_container_width=True,
        )

    st.divider()
    st.caption("AIS v0.6 · Investigación cuantitativa")
    st.caption("🔒 Sin bróker · Sin órdenes · Base de datos local")

if execute:
    try:
        cfg = BacktestConfig(
            initial_cash=float(initial_cash),
            allocation_fraction=allocation_pct / 100,
            stop_loss_pct=stop_pct / 100,
            fee_bps=float(fee_bps),
            slippage_bps=float(slippage_bps),
        )
        with st.spinner("Procesando velas, señales, comisiones y operaciones simuladas…"):
            snapshot = run_analysis(
                symbol=symbol,
                source="demo" if data_label.startswith("Demo") else "historical",
                period=period, config=cfg,
            )
            new_id = save_run(snapshot)
        st.session_state["ais_selected_run_id"] = new_id
        st.success("Simulación completada y guardada localmente.")
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        st.error(f"No fue posible completar el análisis: {exc}")
    except Exception as exc:
        st.error(
            f"Fallo inesperado ({type(exc).__name__}). "
            "Consulta la terminal de VS Code; no se ejecutó ninguna orden."
        )

st.markdown('<div class="ais-eyebrow">INTELLIGENCE / RESEARCH / BACKTEST</div>',
            unsafe_allow_html=True)
st.title("AIS Investment Terminal")
st.caption(
    "Plataforma local de investigación y simulación de mercados. "
    "No es una cuenta financiera ni una recomendación de inversión."
)

try:
    runs = list_runs(limit=75)
except Exception as exc:
    st.error(f"No se pudo leer el historial local: {type(exc).__name__}")
    st.stop()

if not runs:
    st.info(
        "Todavía no hay simulaciones guardadas. En el panel izquierdo selecciona "
        "'Demo sintética' y pulsa 'Ejecutar análisis y simulación' para crear la primera."
    )
    st.markdown(
        '<div class="ais-note">Primero prueba con datos sintéticos. '
        'Después podrás consultar datos históricos reales, sin conectarte a un bróker.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

current_id = st.session_state.get("ais_selected_run_id", runs[0]["id"])
chosen_index = next((i for i, row in enumerate(runs) if row["id"] == current_id), 0)
selected_id = st.selectbox(
    "Explorar sesión guardada",
    options=[run["id"] for run in runs],
    index=chosen_index,
    format_func=lambda rid: next(
        f'{row["created_at"][:16].replace("T", " ")} UTC · {row["symbol"]} · '
        f'{"DEMO" if row["source"] == "SYNTHETIC_DEMO" else "HISTÓRICO"} · '
        f'{row["total_return_pct"]:+.2f}%'
        for row in runs if row["id"] == rid
    ),
)
st.session_state["ais_selected_run_id"] = selected_id

snapshot = get_run(selected_id)
if snapshot is None:
    st.error("No se encontró la simulación seleccionada.")
    st.stop()

summary = snapshot["backtest"]
signal = snapshot["signal"]
risk = snapshot["risk"]
source = snapshot["source"]
source_label = (
    "DEMO · PRECIOS INVENTADOS" if source == "SYNTHETIC_DEMO"
    else "HISTÓRICO · YAHOO FINANCE"
)
st.markdown(f"**{snapshot['market_name']}** · `{snapshot['symbol']}` · {source_label}")
if source == "SYNTHETIC_DEMO":
    st.warning("Esta sesión utiliza datos sintéticos inventados. No representan cotizaciones.")
else:
    st.info(
        f'Histórico de Yahoo Finance, última vela: {snapshot["last_candle"]}. '
        "Puede estar retrasado o incluir una sesión aún no consolidada."
    )

metric_cols = st.columns(4)
metric_cols[0].metric(
    "Capital final ficticio", _number(summary["final_equity"]),
    f'{summary["total_return_pct"]:+.2f}% histórico',
)
metric_cols[1].metric("Drawdown máximo", _number(summary["max_drawdown_pct"], "%"))
metric_cols[2].metric("Operaciones cerradas", str(summary["closed_trades"]))
metric_cols[3].metric("Exposición al mercado", _number(summary["market_exposure_pct"], "%"))

overview, market_tab, trades_tab, history_tab, about_tab = st.tabs(
    ["📊 Resumen", "📉 Mercado", "🧾 Operaciones", "🗂️ Historial", "🛡️ Metodología"]
)

with overview:
    st.plotly_chart(_equity_plot(snapshot), use_container_width=True)
    st.caption(
        "Comparador bruto comprar/mantener al 100%: NO usa la misma exposición "
        "ni costos que la estrategia AIS."
    )
    left, middle, right = st.columns(3)
    with left:
        st.subheader("Señal experimental")
        st.metric("Etiqueta", signal["signal"].replace("_", " "))
        st.write(f'**Sesgo:** {signal["bias"]}')
        st.write(f'**Acuerdo:** {signal["agreement"]}/3 indicadores')
        st.caption("Este acuerdo no es la probabilidad de acertar.")
    with middle:
        st.subheader("Riesgo y métricas")
        st.metric("Volatilidad anualizada", _number(summary["annualized_volatility_pct"], "%"))
        st.metric("Sharpe · RF=0", _number(summary["sharpe_zero_rf"]))
        st.caption("Cálculos históricos simplificados; no predicen el futuro.")
    with right:
        st.subheader("Lectura del mercado")
        st.metric("Último cierre", _number(snapshot["last_close"], digits=4))
        st.write(f'**Tendencia SMA:** {snapshot["trend"]}')
        st.write(f'**RSI:** {snapshot["rsi_text"]}')
        st.write(f'**Riesgo diario:** {risk["risk_level"]}')
    with st.expander("Ver explicación de la señal y advertencias"):
        for observation in signal["observations"]:
            st.write("• " + observation)
        for warning in signal["warnings"] + risk["warnings"]:
            st.warning(warning)

with market_tab:
    st.plotly_chart(_market_plot(snapshot), use_container_width=True)
    m1, m2 = st.columns(2)
    with m1:
        st.plotly_chart(_rsi_plot(snapshot), use_container_width=True)
    with m2:
        st.plotly_chart(_macd_plot(snapshot), use_container_width=True)
    st.caption(
        "Los indicadores describen el pasado. Las señales no garantizan "
        "una dirección futura del precio."
    )

with trades_tab:
    st.subheader("Libro de operaciones ficticias")
    trades = pd.DataFrame(snapshot["trades"])
    if trades.empty:
        st.info("La estrategia no cerró ninguna posición en esta simulación.")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        st.download_button(
            "Descargar operaciones CSV",
            data=trades.to_csv(index=False).encode("utf-8"),
            file_name=f'AIS_{snapshot["symbol"].replace("=", "_")}_trades.csv',
            mime="text/csv",
        )
    st.caption(
        "Solo aparecen operaciones cerradas. La posición abierta, si existe, "
        "se valora a mercado y no está liquidada."
    )

with history_tab:
    st.subheader("Sesiones guardadas en tu computadora")
    runs_frame = pd.DataFrame(runs)
    runs_frame = runs_frame[[
        "created_at", "symbol", "source", "period", "total_return_pct"
    ]]
    st.dataframe(runs_frame, use_container_width=True, hide_index=True)
    st.download_button(
        "Descargar sesión completa JSON",
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        file_name=f'AIS_{snapshot["symbol"].replace("=", "_")}_simulation.json',
        mime="application/json",
    )
    st.caption(
        "Historial local en data/ais_history.sqlite3. "
        "No se sincroniza con GitHub ni con servicios de nube."
    )

with about_tab:
    st.subheader("Qué hace AIS y qué no hace")
    st.markdown(
        """
- **AIS analiza datos históricos y simula operaciones** con una estrategia
  experimental de posiciones largas y efectivo, sin apalancamiento.
- Decide con datos hasta la vela anterior y simula ejecución en la apertura
  siguiente. Incluye comisión, deslizamiento y un stop aproximado.
- **La interfaz no tiene botones de compra real**, conexiones con bróker,
  cuentas bancarias ni credenciales financieras.
- El capital de la simulación es ficticio, expresado en unidades de la moneda
  de cotización. No son depósitos ni saldos de dinero real.
- Falta validación independiente fuera de muestra, walk-forward, costes
  reales del intermediario y comparación con benchmarks equivalentes.
        """
    )
    st.markdown(
        '<div class="ais-note">AIS v0.6 es una aplicación local de investigación, '
        'no un robot de inversión validado. Ninguna rentabilidad histórica '
        'garantiza resultados futuros.</div>',
        unsafe_allow_html=True,
    )
