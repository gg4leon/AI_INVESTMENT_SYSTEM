# AIS v0.9 — Investment Terminal · Nory con Kraken en tiempo real

## Nory v0.9 — DATOS REALES por Kraken, operaciones 100% ficticias

**Ya no dependemos de datos fabricados para toda la investigación:** la nueva
sección **«NORY LIVE LAB v0.9»** recibe cotizaciones de compra y venta reales
(Bid/Ask) del WebSocket público de Kraken. No necesitas crear cuenta, introducir
contraseñas, contratar una suscripción ni entregar llaves API para leer estas
cotizaciones. **Nory nunca envía órdenes, depósitos ni retiros.**

### 1. Actualiza AIS en VS Code (PowerShell)

Antes de actualizar, cierra AIS y cualquier worker en otra terminal. Respáldate
los archivos locales SQLite si te interesa conservar experimentos.

```powershell
git status
git pull origin main
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m streamlit run streamlit_app.py
```

Revisa cambios sin guardar en `git status` antes de descargar. **No hagas
`git reset --hard` ni borres tu carpeta `data`.**

Abre `http://127.0.0.1:8501`. Expande **«● NORY LIVE LAB v0.9»**, selecciona
`BTC-USD` obligatoriamente como referencia más otros símbolos, y pulsa
**«▶ Conectar precios reales · SOLO PAPER»**. El panel muestra el estado de
la conexión, precios reales bid/ask y sus fechas, recepción de mensajes,
spreads, efectivo ficticio, posiciones, órdenes pendientes y operaciones
hipotéticas. **«■ Desconectar y detener»** pausa el motor y cierra la conexión.

Puedes verificar exclusivamente la conexión pública desde otra terminal,
con la app desconectada:

```powershell
python -m nory.kraken_probe --seconds 20 --symbols BTC-USD ETH-USD
```

Si hay conexión WebSocket y actualizaciones reales, imprimirá bid/ask y
`PASS`. Si no, mostrará que faltan cotizaciones o un error. **Las pruebas
unitarias sin Internet no prueban la conexión a Kraken desde tu computadora.**

### 2. Qué mercados son reales ahora

Este módulo gratuito accede al canal público `ticker` de Kraken WebSocket
v2 `wss://ws.kraken.com/v2`: **BTC/USD, ETH/USD, SOL/USD, XRP/USD y
ADA/USD**, si la disponibilidad de esos instrumentos permite suscribirse.
Son **criptomonedas**, **no acciones de empresas**. El catálogo existente de
más de 50 símbolos (SPY, AAPL, NVDA, acciones México, índices, divisas,
materias primas y otros) continúa operativo en el **analizador histórico
Yahoo**, pero no se presenta falsamente como un feed de operaciones
bursátiles de segundo a segundo.

Para **acciones de EE. UU.**, una posible futura opción es **Alpaca Basic**:
datos IEX en tiempo real (no todo el mercado), hasta 30 símbolos de stream,
con claves de API y requisitos de cuenta; no habilitamos ese feed porque
no es completamente abierto sin registro. El plan no permite considerar
sus datos IEX equivalentes a SIP completo de todas las bolsas.

### 3. Diseño de la cartera prospectiva

- **1 solo capital ficticio de 10,000 USD**, separado de las sesiones sintéticas.
- No abre ningún WebSocket automáticamente: requiere pulsar el botón.
- Escucha datos reales con un **único stream** y procesa un lote cada ~1 s
  si hay **nuevas cotizaciones verificables**. Los mensajes pueden llegar
  más o menos rápido; no se inventan ticks ni se garantiza una operación
  cada segundo. Es trabajo **paper**, no alta frecuencia real.
- Usa **solo actualizaciones**, no snapshots iniciales como señales; cada
  símbolo debe tener marca de tiempo posterior a su última observación.
  Rechaza timestamps no cronológicos, bids cruzados, cotizaciones viejas,
  spread excesivo, tamaños nulos y fuentes no reconocidas.
- Las operaciones ficticias usan el **Ask real** para compra y el
  **Bid real** para venta, más **5 bps de deslizamiento supuesto por lado**
  y **80 bps de comisión supuesto por lado**. Esta tarifa conservadora es
  ilustrativa basada en tarifas taker iniciales publicadas por Kraken Pro,
  no un presupuesto personalizado ni una garantía del coste real.
- Una compra se decide tras observar un precio y se deja pendiente hasta
  una **cotización posterior**. Se limita al **10% del tamaño visible del
  mejor nivel Ask** de esa cotización. Las ventas pueden ser parciales,
  limitadas a la profundidad Bid visible; el llenado **NO se garantiza**.
- Exposición máxima **30%**, asignación hasta **8.5% por activo**,
  máximo **4 posiciones**, objetivo de ganancia **45 bps netos**
  después de costes, stop indicativo **300 bps de pérdida neta**,
  bloqueo de pérdidas de cartera **6%**. Los stops NO garantizan venta
  al precio esperado. Una operación de menos de 2% bruto puede perder
  dinero con costes elevados.
- Exige al menos **45 cotizaciones previas por instrumento**, rebote
  tras relativa debilidad, filtro de caída anormal, rango/volatilidad,
  spread y estrés general del benchmark BTC. Si el movimiento bajista
  pudiera deberse a un evento desconocido, **NO inventa su causa**:
  puede bloquear compras hasta que se recupere el contexto técnico.
- Máximo **12 operaciones ficticias por minuto** y tiempo de espera
  entre movimientos del mismo activo. Menos operaciones y mayores
  costes reales pueden eliminar ganancias que aparecen en MicroLab.
- Al perder conexión, quedarse sin datos válidos o alcanzar un
  límite de riesgo, el motor detiene/pone en pausa la simulación.
  No hay conexión con cuenta de dinero real y **no intenta liquidar
  ni cerrar activos reales**.
- Historial persistente exclusivo en `data/nory_live_paper.sqlite3`.
  Guarda precios recibidos, decisiones, operaciones hipotéticas, equity,
  costes y explicaciones. Está excluido de GitHub por `.gitignore`.

### 4. Lo que todavía NO hemos demostrado

- Que la estrategia sea rentable con datos reales: es posible que
  **Nory casi nunca compre** porque los spreads, tarifas y filtros
  impiden operaciones cuya rentabilidad esperada no supera los costes.
- Que un precio se pueda ejecutar: una cotización observada puede
  cambiar o desaparecer antes de una orden. No son fills reales.
- Que el origen de una caída esté verificado: Kraken ofrece datos
  de mercado, **no la explicación causal de un movimiento**. Las
  noticias RSS existentes son información de contexto; no activan
  automáticamente decisiones ni convierten rumores en hechos.
- Datos de acciones por segundo de todas las bolsas, profundidad completa
  de libro, licencias de distribución, latencia propia de un bróker,
  exactitud de precios llenados, slippage histórico comprobado ni
  robustez de resultados fuera de muestra.

Este sistema ofrece investigación **prospectiva** con cotizaciones
auténticas, pero no garantiza que una estrategia resulte viable. Nory
puede perder dinero FICTICIO y esa pérdida es información útil para
mejorarlo. Para cualquier inversión real futura se requerirían
elegibilidad legal, intermediario autorizado, validaciones y controles
adicionales; AIS v0.9 deliberadamente no integra tales acciones.

Fuentes de referencia técnica:
- https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker
- https://www.kraken.com/pro/fees
- https://docs.alpaca.markets/us/docs/about-market-data-api

Nuevos módulos:
`nory/kraken_public.py`, `nory/live_paper.py`,
`nory/live_runner.py`, `nory/kraken_probe.py` y pruebas offline.

---


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

---

## Nory v0.7 — multiactivo, capital ficticio UNIFICADO

**Nory** es el motor de investigación y `paper trading` multiactivo experimental.
Conserva el logo original de AIS y los colores negro, rojo intenso y blanco.

### Qué incluye realmente

- Escáner concurrente de **hasta 20 activos por ciclo, máximo 4 descargas
  paralelas** (principalmente limitado por Yahoo Finance y por las conexiones,
  no por capacidad de trading de alta frecuencia). Los datos diarios pueden
  estar retrasados.
- Única **cartera común de 10,000 USD FICTICIOS** compartida por las posiciones
  de esa fuente de datos. Las carteras de demo y Yahoo se mantienen separadas
  para que las series inventadas no se mezclen con precios históricos.
- Priorización reproducible por **volatilidad diaria reciente** y señal
  técnica (SMA/RSI/MACD). Una volatilidad menor suele recibir más
  presupuesto ficticio; esto **NO convierte a un activo en seguro ni
  predice que ganará más**. El sistema no ha demostrado un rendimiento
  superior a una estrategia pasiva.
- Límites predeterminados: exposición total hasta **65 %**, una posición
  hasta **15 %**, una categoría hasta **40 %**, criptomonedas sumadas hasta
  **12 %**, máximo **8 posiciones**. Otros activos pueden recibir menos.
- Órdenes **PENDING** decididas al cierre de la última vela confirmada.
  La compra/venta simulada se contabiliza **a la apertura de la vela
  siguiente** únicamente cuando aparece esa vela en el histórico.
  Si se pierden velas, la orden caduca: no se inventan operaciones.
- Comisiones ficticias de 10 puntos básicos y deslizamiento de 5 por
  operación. Las salidas por señal bajista o stop también se programan
  para una vela posterior.
- Interruptor de riesgo si la caída de cartera simulada desde su máximo
  alcanza el **12 %**. Bloquea nuevas compras; no garantiza
  liquidación ni protección contra pérdidas adicionales.
- Registro SQLite auditable de observaciones, prioridades, órdenes,
  fills hipotéticos, posiciones y curva de capital.
- Seguridad: **pausado inicialmente**. Ni la app ni el worker importan
  ni invocan APIs de bróker. No hay depósito de dinero.

### Cómo probarlo

1. Abre AIS en el navegador y despliega
   **«🔺 NORY v0.7 · Cartera multiactivo autónoma (ficticia)»**.
2. Elige **DEMO sintética**, selecciona 3 a 8 activos y pulsa
   **Activar Nory · SOLO SIMULACIÓN**.
3. Pulsa **Revisar mercados y simular ciclo**. Verás observaciones y,
   si existen señales alcistas, órdenes pendientes. Vuelve a pulsar para
   avanzar **una vela sintética**; así podrán simularse las órdenes
   anteriores a la siguiente apertura.
4. Para revisar **datos históricos** de Yahoo selecciona el otro origen,
   que conserva otra cartera ficticia separada y exige Internet. No se
   sustituyen datos reales ausentes por precios inventados.
5. Para automatizar ciclos, manteniendo tu ThinkPad encendida, en una
   **segunda terminal PowerShell**:

```powershell
python -m nory.worker --demo --loop --interval-minutes 60 --symbols SPY QQQ AAPL MSFT NVDA BTC-USD ETH-USD
```

Sin `--demo`, consulta históricos Yahoo:

```powershell
python -m nory.worker --loop --interval-minutes 60 --symbols SPY QQQ AAPL MSFT NVDA BTC-USD ETH-USD
```

Se interrumpe con `Ctrl+C` o el botón **Pausar Nory** en el navegador.
Si el equipo se suspende, el worker no ejecuta ciclos. Los ciclos
se calculan con datos diarios, NO son transacciones ultrarrápidas.

### Qué NO significa

- Las “acciones simultáneas” son **observaciones de varios mercados
  procesadas en paralelo**, con órdenes contables ficticias compartiendo
  capital. El motor no puede garantizar disponibilidad, liquidez, spreads,
  llenado inmediato o precio.
- Un histórico descargado **después** del movimiento no permite haber
  operado realmente en la apertura pasada: Nory sólo está evaluando un
  escenario retrospectivo. Para paper trading prospectivo verificado
  faltan sellos de recepción, precios en tiempo de mercado y un reloj
  de ejecución controlado.
- Nory v0.7 no permite usar instrumentos en MXN dentro de la misma
  cartera USD sin conversión verificable de divisas: hasta tenerla,
  divisas, índices, futuros y acciones mexicanas quedan en la pestaña
  de investigación general de AIS.
- Las noticias RSS se muestran como contexto pero **NO se convierten
  en órdenes ni se usa información privada de famosos, relaciones
  personales o rumores no verificados para negociar**. Esas funciones
  requieren evaluación estadística, controles de procedencia y
  supervisión antes de considerar su integración.
- El capital ficticio, el porcentaje sugerido y las prioridades NO
  son recomendaciones de inversión. Más diversificación NO garantiza
  beneficio, y más operaciones pueden aumentar costes y pérdidas.

Archivos: `nory/engine.py`, `nory/book.py`, `nory/worker.py` y
`data/nory_paper.sqlite3` (la base local está ignorada por Git).
Las decisiones y límites se comprueban con
`python -m unittest discover -s tests -v`.

Este módulo no es una estrategia validada: faltan pruebas fuera de muestra,
benchmark comparable, pruebas prospectivas, monitorización de errores
y controles de seguridad antes de siquiera evaluar una integración real.

---


## Nory v0.8.1 — AUTO desde la aplicación (sin terminal adicional)

Ahora puedes activar la simulación continua directamente con **▶ Iniciar automático (1 s)**,
en **⚡ NORY MICRO LAB**. Ya **no necesitas presionar «1 segundo» ni «30 segundos»**.

1. Cierra primero cualquier trabajador `python -m nory.micro_worker` que esté ejecutándose
   sobre la misma base de datos. No uses el trabajador de terminal y AUTO al mismo tiempo.
2. Arranca la app normal desde VS Code con `python -m streamlit run streamlit_app.py`.
3. Abre MicroLab y selecciona los activos y el escenario **antes de empezar**.
4. Pulsa **▶ Iniciar automático (1 s)**. El botón habilita explícitamente la simulación
   y crea **un único hilo local**; las métricas se refrescan aproximadamente cada 2 segundos.
5. Pulsa **■ Detener automático** para pararlo de forma segura. También puedes
   usar **Pausar simulador**, que detiene AUTO y pausa la base de datos.

El trabajo continúa aunque cierres la pestaña del navegador, **solo mientras
el proceso local de Streamlit siga encendido**. Cerrar VS Code/terminal, finalizar
Python o suspender/apagar Windows detiene el trabajo. Después de reiniciar
Streamlit, AUTO **no se reinicia solo**: requiere otra pulsación explícita.

La velocidad de un ciclo por segundo es una **cadencia aproximada de software**;
puede haber retrasos si el cálculo tarda, si Windows está ocupado o si SQLite espera
un bloqueo. La velocidad **no implica acceso a un mercado real**: las cotizaciones
y los segundos son fabricados.

Seguridad: no se inicia al cargar la aplicación, solo al pulsar el botón.
AUTO detecta errores y límites de pérdidas, detiene el hilo y vuelve a PAUSADO.
Evita iniciar dos bucles desde el mismo proceso de Streamlit. **No es un
sistema multiusuario o de múltiples procesos; no lo alojes públicamente ni lo
ejecutes al mismo tiempo con otros workers**. El historial queda en
`data/nory_micro.sqlite3`.

**No confundas «sin pérdidas en una simulación» con rentabilidad demostrada.**
Los precios se inventan con ciertas dinámicas de reversión, que pueden favorecer
a una estrategia que busque rebotes. Validar con datos de mercado realmente
cronológicos, spreads, comisiones y pruebas fuera de muestra es una etapa pendiente.

Archivo nuevo: `nory/auto_runner.py`, con pruebas offline
en `tests/test_auto_runner.py`.

---
## Nory v0.8 — MicroLab de operaciones pequeñas (~1 segundo)

**IMPORTANTE:** es una simulación local con PRECIOS INVENTADOS; no usa velas por
segundo de una bolsa, datos de última hora, un bróker ni ejecuciones reales.
Se ha añadido como módulo experimental al resto de AIS y Nory v0.7. El logo
original del usuario y la paleta **rojo intenso, negro y blanco** se conservan.

### Qué aporta al proyecto

- Un ciclo por **segundo virtual** con datos OHLC artificiales, que puede
  ejecutarse aproximadamente cada **1 segundo de reloj** en tu ThinkPad.
  Los tiempos de cálculo y Windows pueden introducir retrasos.
- Un solo capital de **10,000 USD totalmente ficticios** compartido entre
  distintos activos cotizados en USD. Hasta 20 instrumentos de la lista
  permitida, **6 posiciones a la vez** y un límite de **55 % de exposición**.
- Estrategia **experimental de reversión a la media**: trata de detectar
  precios relativamente por debajo de su promedio reciente, exige un
  rebote y calcula si la diferencia prevista podría superar los gastos.
  **Eso NO identifica valor fundamental ni asegura que el precio subirá.**
- Objetivo de salida **neto de costes** de 18 puntos básicos (0.18 %) y
  pérdida de salida de 65 puntos básicos (0.65 %). Se incluyen **5 bps de
  comisión por lado, 4 bps de spread total y 2 bps de deslizamiento por lado**.
  Son SUPUESTOS artificiales, no cotizaciones ni tarifas de una bolsa.
- El motor crea una orden **PENDIENTE** al observar una oportunidad y
  no la contabiliza hasta el **siguiente segundo virtual**. Si aparece
  una caída anómala o choque de mercado, una compra pendiente puede cancelarse.
  Incluso una venta solicitada al alcanzar un beneficio puede perder dinero
  antes de su llenado en el siguiente tick.
- Detectores técnicos de caída anormal, volatilidad excesiva,
  concentración y movimientos simultáneos del índice de referencia
  sintético (SPY). Se niega a inferir la **causa real** de una caída
  solo a partir del precio: la etiqueta es «causa no verificada».
- Bloqueo de nuevas operaciones cuando el drawdown ficticio alcanza el
  7 %, límites de posiciones y frecuencia, periodo de espera entre
  operaciones, auditoría de señales y gastos.
- Pruebas de los escenarios: `mixed`, `calm`, `selloff` y `shock`.
  Son simulaciones deterministas para probar riesgo, **no resultados
  que puedan trasladarse a mercados reales**.

### Cómo iniciarlo

Con el proyecto actualizado:

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

En el panel **⚡ NORY MICRO LAB v0.8**, selecciona escenario y símbolos.
Deja SPY como referencia de mercado. Pulsa **Activar simulador**,
después **Simular 1 segundo** o **Simular 30 segundos**. La segunda
opción calcula **30 segundos virtuales sin esperar 30 segundos reales**.

Para una simulación que avance aproximadamente un paso por segundo de
reloj, en otra terminal, mientras Nory MicroLab esté activado:

```powershell
python -m nory.micro_worker --demo --steps 300 --interval-seconds 1 --scenario mixed --symbols SPY QQQ AAPL MSFT NVDA BTC-USD ETH-USD
```

El proceso se detiene al terminar 300 pasos, al pulsar `Ctrl+C`, al
pausarlo en la app o al activar el bloqueo de pérdidas. Para ejecución
continua en tu propia PC sustituye `--steps 300` por `--loop`.
La laptop tiene que estar encendida, sin suspensión, y la terminal abierta.

Si quieres comparar escenarios o cambiar universo/política debes crear
una sesión nueva **después de respaldar** el historial: el motor
intencionadamente fija estos parámetros en la base local
`data/nory_micro.sqlite3` para que no mezcle experimentos. No borres
la base sin respaldo ni mientras el worker esté corriendo.

### Lo que todavía NO puede hacer

Un feed de **datos diarios** como el de Yahoo de AIS v0.7 NO es
adecuado para tomar decisiones cada segundo. Ni los RSS ni rumores
son un sustituto de cotizaciones de bid/ask, liquidez, noticias
verificadas y marca temporal. Para hacer paper trading prospectivo
con datos reales de segundos haría falta un proveedor autorizado y
latencia medible, control de horarios de bolsas, acumulación de
órdenes, tasas y spreads dinámicos, detección independiente de
eventos, validación fuera de muestra y controles mucho más severos.
Sin ellos, una ganancia en MicroLab **no acredita una oportunidad
real ni capacidad de enriquecimiento rápido**.

No hay cuenta bancaria, credenciales de inversión, operador de bolsa,
dinero real ni API de órdenes. Los chismes y relaciones de celebridades
siguen como información de contexto en la interfaz, sin afectar decisiones.

Nuevos archivos:
`nory/micro_feed.py`, `nory/micro_lab.py`,
`nory/micro_worker.py`, `tests/test_micro_lab.py`.
