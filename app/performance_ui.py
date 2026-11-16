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
from nory.validation import validate_out_of_sample,ValidationConfig
from data.market_data import get_market_data


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

    st.divider()
    with st.expander("🧪 Laboratorio histórico: entrenamiento y prueba fuera de muestra",
                     expanded=False):
        st.write(
            "AIS selecciona la estrategia usando únicamente el 70 % inicial "
            "del historial. Después evalúa los resultados en el 30 % reservado, "
            "sin haberlo usado para escoger la estrategia."
        )
        st.caption(
            "Las señales se calculan con datos hasta el cierre anterior y "
            "las operaciones se simulan en la siguiente apertura, con costes."
        )
        c1,c2=st.columns(2)
        with c1:
            valid_symbol=st.selectbox(
                "Mercado histórico Yahoo",
                ["SPY","QQQ","AAPL","MSFT","NVDA","BTC-USD","ETH-USD"],
                key="wf_symbol",
            )
        with c2:
            fee=st.number_input(
                "Comisión supuesta por lado (bps)",
                min_value=0.,max_value=200.,value=60.,step=5.,
                key="wf_fee",
            )
        if st.button("Validar sin mirar los resultados futuros",
                     type="primary",key="wf_run"):
            try:
                with st.spinner("Descargando históricos y separando entrenamiento/prueba..."):
                    frame=get_market_data(valid_symbol,period="5y",interval="1d")
                    if frame is None or len(frame)<150:
                        raise ValueError("No hay suficientes velas reales válidas")
                    res=validate_out_of_sample(
                        frame,ValidationConfig(fee_bps_each_side=float(fee))
                    )
                    res["symbol"]=valid_symbol
                    st.session_state["wf_last_result"]=res
                st.success("Validación histórica completada. Las ejecuciones siguen siendo ficticias.")
            except (ValueError,OSError,RuntimeError,KeyError) as exc:
                st.error(f"No se pudo validar: {exc}")
        res=st.session_state.get("wf_last_result")
        if res:
            st.markdown(
                f'**Última validación: {res["symbol"]}** · '
                f'Estrategia elegida SOLO con entrenamiento: '
                f'**{res["chosen_from_train_only"]}**'
            )
            d=res["dates"]
            st.caption(
                f'Entrenamiento: {d["train_start"][:10]} a {d["train_end"][:10]} · '
                f'Prueba reservada: {d["holdout_start"][:10]} a {d["holdout_end"][:10]}'
            )
            train=pd.DataFrame(res["all_training_summaries"])
            train.columns=["Estrategia","Retorno entrenamiento (%)",
                           "Drawdown máximo entrenamiento (%)","Ventas entrenamiento"]
            st.write("**Selección: primeros datos, sin tocar la prueba**")
            st.dataframe(train,hide_index=True,use_container_width=True)
            tests=pd.DataFrame([{
                "Estrategia":name,
                "Resultado reservado (%)":round(val["return_pct"],3),
                "Drawdown reservado (%)":round(val["max_drawdown_pct"],3),
                "Entradas ficticias":val["buys"],
                "Costes ficticios USD":round(val["recorded_fees"],2),
            } for name,val in res["holdout_results"].items()])
            st.write("**Periodo realmente reservado: comparación de estrategias**")
            st.dataframe(tests,hide_index=True,use_container_width=True)
            winner=res["chosen_holdout"]
            cols=st.columns(3)
            cols[0].metric("Rendimiento reservado, estrategia elegida",
                           f'{winner["return_pct"]:+.3f}%')
            cols[1].metric("Drawdown reservado",
                           f'{winner["max_drawdown_pct"]:.3f}%')
            cols[2].metric("Referencia BTC/acción 100 % invertida",
                           f'{res["benchmark_100pct_buy_hold_net_pct"]:+.3f}%')
            chart=go.Figure()
            for key,val in res["holdout_results"].items():
                curve=pd.DataFrame(val["curve"])
                chart.add_trace(go.Scatter(
                    x=curve["date"],y=curve["equity"],
                    name=key,mode="lines",
                    line=dict(color="#ff0d00" if key==res["chosen_from_train_only"]
                              else "#ffffff" if key=="CASH" else "#777777",
                              width=3 if key==res["chosen_from_train_only"] else 1.5),
                ))
            chart.update_layout(
                height=350,paper_bgcolor="#101010",plot_bgcolor="#101010",
                font=dict(color="#ffffff"),
                title="Curvas ficticias del periodo fuera de muestra",
                xaxis=dict(showgrid=True,gridcolor="#292929"),
                yaxis=dict(showgrid=True,gridcolor="#292929"),
            )
            st.plotly_chart(chart,use_container_width=True)
            _csv_download(
                "Exportar trades de estrategia elegida",
                winner["trades"],"ais_wf_chosen_trades.csv","wf_trades",
            )
            st.warning(
                "Una prueba histórica no demuestra rentabilidad futura. "
                "Yahoo puede ajustar precios; las operaciones al próximo "
                "precio de apertura son aproximadas. El benchmark invierte "
                "100 % y la estrategia hasta 30 %: sus riesgos NO son iguales. "
                "Una sola partición 70/30 es una evaluación preliminar."
            )

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
