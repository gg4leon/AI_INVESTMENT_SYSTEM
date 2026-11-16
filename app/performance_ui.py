"""AIS Performance Center: organized UI for prospective paper results.

No new trading actions, no additional market data subscriptions.
"""
import io
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nory.performance import (
    summarize_live,summarize_synthetic,diagnosis,
)
from nory.live_paper import LIVE_DB,COINBASE_LIVE_DB


def _csv_download(title, rows, filename, key):
    if not rows:
        return
    st.download_button(
        title,pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
        filename,mime="text/csv",key=key,
    )


def _equity_plot(rows, realtime):
    frame=pd.DataFrame(rows)
    if frame.empty:
        return None
    key="observed_at" if realtime else "tick"
    fig=go.Figure()
    fig.add_trace(go.Scatter(
        x=frame[key],y=frame["equity"],name="Capital de Nory (paper)",
        line=dict(color="#ff0d00",width=2.6),mode="lines",
    ))
    fig.update_layout(
        title="Evolución del capital ficticio · neto de costes registrados",
        height=390,paper_bgcolor="#101010",plot_bgcolor="#101010",
        font=dict(color="#ffffff"),margin=dict(l=18,r=18,t=65,b=24),
        xaxis=dict(showgrid=True,gridcolor="#292929",title="Hora real UTC" if realtime else "Segundo virtual"),
        yaxis=dict(showgrid=True,gridcolor="#292929",title="USD ficticios"),
    )
    return fig


def _render_report(report,label,realtime):
    if not report.get("available"):
        st.info(report.get("reason","Todavía no hay operaciones ni cotizaciones guardadas."))
        return
    stats=report["stats"]
    st.caption(
        f"Fuente de datos: **{label}** · "
        + ("cotizaciones auténticas, ejecuciones SOLO SIMULADAS" if realtime
           else "cotizaciones y ejecuciones COMPLETAMENTE INVENTADAS")
    )
    cols=st.columns(4)
    cols[0].metric("Capital paper",f'$ {stats["equity"]:,.2f}')
    cols[1].metric("Resultado neto",f'{stats["return_pct"]:+.3f}%')
    cols[2].metric("Compras / ventas",f'{stats["simulated_buys"]} / {stats["closed_sells"]}')
    cols[3].metric("Costes registrados",f'$ {stats["total_fees"]:,.2f}')
    info=st.columns(4)
    info[0].metric("Pérdida máxima",f'{stats["max_drawdown_pct"]:.3f}%')
    winrate=stats["win_rate_pct"]
    info[1].metric("Ventas ganadoras",f'{winrate:.1f}%' if winrate is not None else "Sin cierres")
    info[2].metric("Ganancia realizada",f'$ {stats["realized_net_pnl"]:+,.2f}')
    info[3].metric("Cotizaciones / pasos",f'{stats["observations"]:,}')
    if realtime:
        st.info(diagnosis(report))
        st.caption(
            f'Último registro de la cuenta: {report.get("last_cycle_at") or "N/D"} UTC. '
            "Sin movimientos NO implica error. Una compra solo debe ejecutarse si "
            "el beneficio esperado podría superar tarifas, spreads y riesgo."
        )
        st.caption(
            f'Exposición media: {stats["average_exposure_pct"]:.2f}% · '
            f'Máxima observada: {stats["peak_exposure_pct"]:.2f}% · '
            f'{stats["distinct_assets"]} activos con datos válidos'
        )
        if stats["benchmark_btc_gross_pct"] is not None:
            st.metric("Referencia: comprar BTC y mantener (BRUTO)",
                      f'{stats["benchmark_btc_gross_pct"]:+.3f}%')
            st.caption(
                "No es una comparación con el mismo riesgo, exposición ni gastos: "
                "solo referencia del movimiento de BTC durante el registro."
            )
    graph=_equity_plot(report["equity"],realtime)
    if graph:
        st.plotly_chart(graph,use_container_width=True)
    st.markdown("**Por qué Nory decidió esperar, bloquear o entrar**")
    if report["reasons"]:
        count=pd.DataFrame(report["reasons"]).rename(columns={
            "decision":"Decisión","count":"Cantidad"
        })
        st.dataframe(count,hide_index=True,use_container_width=True)
    else:
        st.caption("Aún no hay decisiones guardadas.")

    with st.expander("Detalle de operaciones, activos y descargas",expanded=False):
        if realtime and report.get("markets"):
            st.markdown("**Cobertura real recibida**")
            st.dataframe(pd.DataFrame(report["markets"]),hide_index=True,use_container_width=True)
        if realtime and report.get("assets"):
            st.markdown("**Resultados por activo**")
            st.dataframe(pd.DataFrame(report["assets"]),hide_index=True,use_container_width=True)
        if report["fills"]:
            st.markdown("**Libro de operaciones ficticias**")
            st.dataframe(pd.DataFrame(report["fills"]),hide_index=True,use_container_width=True)
        else:
            st.caption("Sin operaciones completadas: esto también es un resultado válido.")
        if realtime and report.get("decisions"):
            st.markdown("**Últimas decisiones y razones**")
            st.dataframe(pd.DataFrame(report["decisions"]),hide_index=True,use_container_width=True)
        b1,b2,b3=st.columns(3)
        with b1:
            _csv_download("Descargar capital CSV",report["equity"],
                          "ais_equity_"+label.lower()+".csv","dl_eq_"+label)
        with b2:
            _csv_download("Descargar operaciones CSV",report["fills"],
                          "ais_trades_"+label.lower()+".csv","dl_trades_"+label)
        with b3:
            if realtime:
                _csv_download("Descargar decisiones CSV",report["decisions"],
                              "ais_decisions_"+label.lower()+".csv","dl_dec_"+label)
            else:
                _csv_download("Descargar causas CSV",report["reasons"],
                              "ais_signals_synthetic.csv","dl_why_synth")


def render_performance():
    st.subheader("Centro de rendimiento · Nory")
    st.write(
        "Mide si la estrategia es viable: capital, costes, drawdown, "
        "operaciones y razones por las que decide no comprar."
    )
    st.warning(
        "Los balances son ficticios. Kraken y Coinbase utilizan exchanges distintos, "
        "sesiones y comisiones supuestas diferentes. Compararlos directamente "
        "NO demuestra cuál es mejor."
    )
    source=st.radio(
        "Selecciona el estudio",[
            "Coinbase · cotizaciones reales",
            "Kraken · cotizaciones reales",
            "MicroLab · datos sintéticos",
        ],horizontal=True,key="performance_source",
    )
    if source.startswith("Coinbase"):
        report=summarize_live(COINBASE_LIVE_DB,source="COINBASE")
        _render_report(report,"COINBASE",True)
    elif source.startswith("Kraken"):
        report=summarize_live(LIVE_DB,source="KRAKEN")
        _render_report(report,"KRAKEN",True)
    else:
        report=summarize_synthetic()
        _render_report(report,"SINTETICO",False)

    with st.expander("Cómo interpretar Nory sin engañarnos"):
        st.markdown(
            "- **Rentabilidad neta:** cambio del valor de la cartera paper, incluyendo "
            "valoraciones de cierre y gastos simulados. No es dinero ganado.\n"
            "- **Tasa de acierto:** porcentaje de eventos de venta con PnL positivo. "
            "Una venta parcial cuenta como un evento, no como una operación completa.\n"
            "- **Drawdown:** caída del capital desde un máximo anterior registrado.\n"
            "- **Comisiones:** tarifa simulada por cada ejecución paper, "
            "no necesariamente la tarifa aplicable a tu cuenta futura.\n"
            "- **Sin operaciones:** a menudo es una respuesta correcta ante "
            "un margen esperado insuficiente. Más señales no garantizan beneficio.\n"
            "- **Datos en vivo:** el proveedor transmite cotizaciones de mercado, "
            "pero una ejecución futura, sus condiciones y liquidez NO están garantizadas.\n"
            "- **Pruebas fuera de muestra:** todavía hay que reunir suficientes "
            "sesiones prospectivas y compararlas con una referencia del mismo riesgo."
        )
