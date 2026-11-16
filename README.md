# AIS v0.8 — Investment Terminal con Nory MicroLab

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
