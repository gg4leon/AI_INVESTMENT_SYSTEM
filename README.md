# AIS v0.6.1 — Investment Terminal / Markets & Paper Automation

Plataforma educativa de investigación, gráficos, noticias y operaciones **100% simuladas**. **No conecta a brókeres, no ejecuta compras/ventas reales y no requiere depositar dinero.** El logotipo de AIS conserva el diseño original aportado por su creador, vectorizado para su uso en la interfaz.

## Ejecutar en Windows / VS Code

En la carpeta local AI_INVESTMENT_SYSTEM:

```powershell
git status
git pull origin main
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Si ya aparece `(.venv)`, no hace falta activar de nuevo. La aplicación local se abre en `http://127.0.0.1:8501`; también puedes hacer doble clic en `INICIAR_AIS.bat` tras instalar dependencias. Para detener Streamlit, pulsa `Ctrl+C` en la terminal.

**Si `git status` presenta CSV modificados que ya estaban versionados**, guarda una copia fuera de la carpeta antes de restaurarlos; no uses `git reset --hard`. El `.gitignore` ignora nuevas salidas pero no retira por sí solo archivos que Git ya seguía.

## Panel de AIS

- **Resumen:** curva de capital, drawdown, retorno, exposición y señal del motor técnico.
- **Mercado:** velas, medias móviles, RSI, MACD; permite más de 40 activos de distintas clases.
- **Operaciones / Historial:** operaciones simuladas del backtest y sesiones persistentes en SQLite.
- **Universo de mercados:** acciones EE. UU./México/internacionales, ETFs, cripto, forex, materias primas e índices.
- **Automatización:** activar/pausar motor local, procesar una vela ficticia y ver cuentas/libro de eventos.
- **Noticias:** titulares RSS para investigación, incluyendo cultura, marcas y celebridades. *No se tratan como hechos verificados* y **no influyen en operaciones**.

La paleta de diseño usa negro, rojo intenso del logotipo original y blanco.

### Cómo iniciar el operador automático de cartera simulada

1. Abre la aplicación, en la sección **🤖 Automatización · cartera ficticia** pulsa **Activar operador de SIMULACIÓN**. Arranca pausado por defecto.
2. Para probarlo sin Internet, elige un instrumento y activa **Datos sintéticos para prueba**; pulsa **Ejecutar un ciclo ficticio ahora**. La ejecución usa precios completamente inventados y queda etiquetada como tal.
3. Para ejecutar un ciclo usando **datos históricos reales** de Yahoo (no cotizaciones ejecutables), abre **otra terminal PowerShell**:

```powershell
python -m automation.worker --once --symbols SPY AAPL MSFT BTC-USD
```

4. Para que AIS ejecute una revisión ficticia cada 60 minutos **mientras la PC y esa terminal sigan encendidas**:

```powershell
python -m automation.worker --loop --interval-minutes 60 --symbols SPY AAPL MSFT BTC-USD
```

Para probar el bucle sin Internet, añade `--demo`. El motor se detiene con `Ctrl+C` o con **Pausar operador** en la app. El proceso no trabaja cuando Windows está apagado o suspendido. Un mismo símbolo y vela no se procesan dos veces. El máximo es 15 símbolos por ejecución. Ten presente que hay límites de peticiones a la fuente de datos.

### Qué significan los "movimientos"

El motor crea **cuentas ficticias separadas por activo, origen y moneda**. No es correcto sumar dólares y pesos como si fueran la misma divisa. Cada cuenta inicia con 10,000 unidades **inventadas** de la moneda de cotización. Con señal alcista y sin posición, simula una compra de 10% del efectivo; con señal bajista o stop, simula una venta de su posición. Incluye comisión, deslizamiento y control de posición única. Una señal neutra registra `HOLD`. Una misma fecha se registra una vez; evita duplicados incluso tras reiniciar.

**Limitación crucial:** los fills usan el cierre observado de una vela histórica como precio **hipotético**, posiblemente ya no disponible; la app **no reproduce ejecución real ni puede garantizar stops**. La última vela del día actual se descarta si podría estar abierta. No hay órdenes reales, datos minuto a minuto, pujas/ofertas, libro de órdenes, impuestos ni liquidez. Para automatización real futura hacen falta licencias, elegibilidad de cuenta, validación fuera de muestra, reglas de control, un feed de precios apropiado y supervisión legal/técnica.

La base de datos del trabajador está en `data/ais_paper.sqlite3`, distinta del historial de backtests `data/ais_history.sqlite3`. Ambas se ignoran en Git. No existe un broker ni cuentas conectadas.

**Índices, divisas y futuros son solo analíticos**; no se pueden tratar como acciones directamente comprables. Las criptomonedas y acciones están representadas únicamente por cuentas ficticias educativas.

### Actualidad, famosos y rumores

El lector RSS obtiene **titulares de terceros**, no verifica independientemente su veracidad. En la pestaña de investigación puedes consultar noticias de empresas y cultura de marcas. Los titulares que mencionan rumores se marcan como tales. **No se utiliza información privada, chismes, relaciones de famosos o rumores no contrastados para generar operaciones**. No hay indicador de sentimiento validado ni relación causal demostrada entre una noticia y un rendimiento futuro. Los movimientos automáticos se basan únicamente en las reglas técnicas ya documentadas.

## Arquitectura

```text
assets/ais_original.svg           # vectorización fiel del logo aportado por el usuario
streamlit_app.py                  # panel rojo/negro/blanco
app/markets.py                    # catálogo de mercados y divisas
app/news.py                       # RSS público de contexto
app/service.py                    # análisis histórico
app/storage.py                    # SQLite para backtesting
automation/paper.py               # motor de saldos y libro de eventos ficticios
automation/worker.py              # comprobación local repetible (nunca brokers)
analysis/                        # indicadores técnicos
backtesting/engine.py             # backtester histórico
tests/                            # pruebas sin red
```

## Pruebas y limitaciones

```powershell
python -m unittest discover -s tests -v
python main.py --demo --symbols SPY
```

GitHub Actions ejecuta esas pruebas. Que las pruebas pasen indica que el código funciona conforme a sus supuestos, **no que una estrategia sea rentable ni apta para gestionar dinero real**. Falta validación temporal fuera de muestra, comparación ajustada a riesgos y costes, simulación de datos en tiempo de mercado, control de sesgos y verificación humana independiente. Yahoo Finance puede limitar, modificar o interrumpir el acceso y sus datos pueden estar atrasados/incompletos. No extrapolar resultados de datos sintéticos a mercados reales.
