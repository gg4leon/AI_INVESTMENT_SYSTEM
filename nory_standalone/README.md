# NORY 2.0 — Autonomous Investment Intelligence

Aplicación local independiente de AIS: datos públicos de Coinbase Exchange y
Kraken, cinco estrategias explicables y ejecución **exclusivamente simulada**.
El logo es una copia byte por byte de `../assets/ais_original.svg`.
No usa claves de inversión, cuentas de bróker, depósitos ni retiros.

## Instalar y abrir en Windows / VS Code

Necesitas **Python 3.11 o superior de python.org**, Git e Internet para los
WebSockets. En el instalador de Python activa el lanzador `py`. No se necesita
Node, Docker, Streamlit ni una cuenta de exchange.

1. En VS Code, abre la carpeta del repositorio y una terminal PowerShell.
2. Obtén la rama sin descartar cambios personales:

```powershell
git status
git fetch origin
git switch feature/nory-2-standalone
```

Si ya descargaste el PR o estás en esta rama, omite esos comandos. Si aún no
tienes el repositorio:

```powershell
git clone --branch feature/nory-2-standalone https://github.com/gg4leon/AI_INVESTMENT_SYSTEM.git
cd AI_INVESTMENT_SYSTEM
code .
```

3. En la terminal de VS Code, desde la raíz del repositorio:

```powershell
cd nory_standalone
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

4. Abre **http://127.0.0.1:8765** si el navegador no se abre automáticamente.
   Pulsa **Iniciar Nory** una vez. **Detener Nory** cancela órdenes pendientes y
   detiene las decisiones automáticas; conserva las posiciones ficticias.
5. Para siguientes sesiones, haz doble clic en **`INICIAR_NORY.bat`**. El archivo
   también crea el entorno e instala las dependencias si no existen. Mantén la
   ventana abierta mientras investigas. `Ctrl+C` cierra el servicio.

No es necesario activar PowerShell ni cambiar su política de ejecución.
El intérprete de VS Code se puede seleccionar con **Python: Select Interpreter**
→ `nory_standalone\.venv\Scripts\python.exe`.

En Linux/macOS, desde la raíz:

```bash
python3 -m venv nory_standalone/.venv
nory_standalone/.venv/bin/python -m pip install -r nory_standalone/requirements.txt
nory_standalone/.venv/bin/python -m nory_standalone --no-browser
```

## Uso

- **Dashboard:** capital ficticio, P/L neto, efectivo, posiciones, curva real del
  libro, diagnóstico y calidad de los dos proveedores.
- **Mercados:** activos, precio, variación de la ventana local, spread, score,
  riesgo y decisión. Filtra por activo, mercado y riesgo; selecciona una fila
  para ver condiciones cumplidas/fallidas, RSI, momentum, volumen y antigüedad.
- **Operaciones:** posiciones, historial de órdenes, llenados hipotéticos y
  posiciones completamente cerradas. Exportaciones CSV con todos los llenados.
- **Inteligencia y rendimiento:** métricas, comparación de estrategias,
  parámetros fijados al crear la cartera, evaluación histórica y diagnósticos.

Los selectores de proveedor/estrategia cambian la **cartera mostrada**. Iniciar y
detener son controles globales del motor. Cada combinación tiene **una sola
cartera**, inicialmente de 10,000 USD ficticios: 2 proveedores × 5 estrategias =
10 experimentos independientes. No sumes sus capitales ni sus beneficios.

Los datos se conectan al abrir el servicio, incluso detenido, para observar el
mercado y preparar indicadores. Iniciar habilita decisiones; no obliga a comprar.
El motor es un servicio asíncrono separado de las vistas y sigue activo al
cambiar de pestaña o cerrar el navegador. **Cerrar el proceso Python sí lo
detiene.** Tras un reinicio siempre queda detenido y vuelve a calentar el
historial; recupera posiciones y cancela órdenes pendientes anteriores.

## Datos auténticos y límites

Coinbase usa `wss://ws-feed.exchange.coinbase.com`, canales públicos `ticker` y
`heartbeat`; Kraken usa `wss://ws.kraken.com/v2`, `ticker` con disparador `bbo`.
TLS y la conexión al proveedor aportan procedencia. Los parsers validan formato,
no convierten datos inventados de pruebas en precios reales.

El universo inicial es BTC, ETH, SOL, XRP, ADA y DOGE, cotizados en USD. Puedes
configurar hasta **40 símbolos por proveedor como límite local de recursos**,
no como promesa del límite o disponibilidad del exchange. Se envía una sola
suscripción por conexión; las confirmaciones/rechazos reales se muestran en
Diagnóstico. Un producto retirado o no disponible no tiene un sustituto sintético.
Incluye BTC-USD para la referencia de mercado de cada proveedor. La ampliación
se hace en configuración y en una base nueva, preservando el experimento previo.

Se agrupan mensajes entre evaluaciones de 0.5–1 segundo y se conserva una muestra
auténtica por intervalo/activo. **No se inventan velas ni se rellenan huecos.**
Más ciclos no significan más precios. Se rechazan mensajes duplicados,
desordenados, libros cruzados/no finitos y fechas vencidas o demasiado futuras.
Los heartbeats no actualizan precios. Los huecos grandes reinician el historial.
Una secuencia de ticker Coinbase no es una secuencia contigua de libro completo;
no se presume haber reconstruido nivel 2 ni profundidad oculta.

Los exchanges nunca se mezclan en una estrategia. La correlación se calcula
solo con retornos cuyos dos extremos temporales coinciden en el mismo proveedor;
si faltan intervalos comunes o variación, es desconocida y se restringe la entrada.
El volumen suministrado es de **24 horas en unidades base**; no es volumen por
segundo ni una medida inventada de presión compradora.

Las opciones de acciones y sus permisos están en [PROVIDERS.md](docs/PROVIDERS.md).
No se conecta ningún proveedor de acciones sin credenciales y permisos compatibles.

## Reglas y ejecución

Cinco hipótesis fijas: tendencia, reversión, momentum, ruptura de rango y efectivo.
Se evalúan medias de 15/60 muestras, momentum de 30/120, RSI simple de 14 cambios,
volatilidad, rango, bid/ask, tamaño visible y volumen reportado. Los horizontes son
intervalos observados de la configuración, **no medias diarias**. El score cuenta
reglas cumplidas: no es probabilidad ni una predicción validada.

Las entradas necesitan un margen heurístico superior a comisiones en ambos lados,
spread observado, deslizamiento y un margen adicional. Ese margen es amplitud
técnica observada, no una estimación estadística de rendimiento esperado. No hay
noticias, causas fundamentales inventadas ni selección improvisada de reglas.
Una caída súbita o estrés general del mercado bloquea compras temporalmente.

1. Registrar una orden pendiente, reservando presupuesto y capacidad de cartera.
2. Esperar un **nuevo** precio con fecha del exchange y recepción posteriores a
   la hora local de decisión. Un mensaje ya recibido o en buffer no puede llenarla.
3. Revalidar señal, costes, riesgo y liquidez al comprar. Comprar al ask más
   slippage y vender al bid menos slippage; descontar comisión en cada llenado.
4. Limitar cada llenado a una participación del tamaño visible. Conservar el
   resto como parcial hasta completarse, cancelarse o vencer. Nunca reutilizar
   la misma cotización para llenar dos veces la misma orden.
5. Valorar posiciones al bid, descontando salida estimada. Evaluar stop, objetivo
   neto e invalidación; registrar salida pendiente para una cotización posterior.

La repetición de participación en nuevas cotizaciones es un **supuesto** de
simulación: no demuestra reposición real de liquidez. Sin cola, libro completo,
prioridad ni ejecución real, estos llenados no reproducen fielmente un exchange.
Stops y objetivos no garantizan precio de salida; una caída o desconexión puede
superar la pérdida prevista. No hay ventas en corto ni apalancamiento.

El tamaño usa riesgo por operación, volatilidad, acuerdo de reglas y un descuento
por incertidumbre; también aplica reserva, activo, categoría cripto, número de
posiciones, correlación y reservas de otras órdenes. La reinversión usa el efectivo
y el capital neto actualizado. Las salidas de riesgo tienen prioridad sobre el
límite de nuevas entradas por minuto. Un drawdown bloquea entradas y conserva la
vigilancia de salidas; el interruptor de emergencia detiene todo y persiste el bloqueo.

## Configuración reproducible

`config.example.json` contiene los parámetros completos. **60 bps Coinbase y
40 bps Kraken por lado son supuestos conservadores de investigación**, no una
tarifa garantizada para una cuenta ni una consulta de tu nivel de comisiones.
`1 bp = 0.01 %`. Revisa tarifas del proveedor antes de diseñar otro experimento.

Para cambiar capital, universo, cadencia o costes en Windows:

```powershell
Copy-Item config.example.json config.local.json
code config.local.json
.\.venv\Scripts\python.exe run.py --config config.local.json --db data\experimento_02.sqlite3
```

Detén el servicio antes de cambiar configuración. La huella de configuración del
libro impide reinterpretar una cartera antigua con reglas/costes nuevos. Una base
nueva crea un experimento nuevo; no migra ni borra el anterior. No hay aprendizaje
online ni promoción automática. El historial fuera de muestra y las carteras
prospectivas permiten investigar una mejora antes de versionarla.

## Backtesting y exportación

En **Inteligencia → Validación histórica → Evaluar historial registrado**, se
reproduce un máximo de 30,000 muestras recientes del proveedor seleccionado.
Requiere al menos 360 intervalos con la configuración inicial. La elección de
estrategia usa únicamente el primer 70 %; el test comienza después de un embargo
de vigencia de orden + antigüedad máxima de cotización. El libro de prueba empieza
en efectivo con indicadores calentados exclusivamente con datos anteriores.

El replay utiliza el **mismo motor, reglas de riesgo y contabilidad** que el modo
prospectivo. No usa el precio de decisión para llenar órdenes ni usa el resultado
del test para cambiar la selección. La comparación con BTC incluye entrada/salida
y costes, al 100 % de exposición; no equivale al riesgo o exposición de Nory.

Con 20 o más posiciones cerradas, el informe calcula un intervalo descriptivo
del P/L neto medio mediante bootstrap por bloques. Con menos cierres muestra
«muestra insuficiente». El intervalo no elimina sesgos de selección, cambios de
régimen, tamaños distintos ni errores del simulador; no promueve estrategias.

Desde un CSV exportado de Mercados, también puedes usar:

```powershell
.\.venv\Scripts\python.exe run.py backtest --csv .\nory_coinbase_trend_quotes.csv --source DECLARED_PUBLIC_CSV_UNVERIFIED --output validacion.json
```

Un CSV externo tiene procedencia declarada y **no verificada**, incluso si parece
un mensaje público. Los datos de pruebas deben etiquetarse `SYNTHETIC_TEST`.
No hay precios sintéticos en el servicio normal. Un split, pocas operaciones o
unos minutos en vivo no prueban ventaja; hacen falta periodos extensos, regímenes
distintos, incertidumbre estadística y experimentos prospectivos sin reajustes.

## Pruebas y conexión pública

Desde la raíz del repositorio (en Windows usa la ruta del intérprete indicada):

```powershell
.\nory_standalone\.venv\Scripts\python.exe -m pip install -r nory_standalone\requirements-dev.txt
.\nory_standalone\.venv\Scripts\python.exe -m pytest nory_standalone\tests -q
.\nory_standalone\.venv\Scripts\python.exe -m ruff check nory_standalone
.\nory_standalone\.venv\Scripts\python.exe -m nory_standalone probe --seconds 25 --output nory_standalone\data\probe.json
```

`probe` abre ambos WebSockets públicos sin iniciar paper trading y devuelve
contadores, muestras recibidas, latencia y errores. Sale con código 2 si algún
proveedor no envía precios válidos. No reemplaza un fallo de red con fixtures.

Las pruebas unitarias son offline y usan datos fabricados declarados. La CI de
Nory separa pruebas de Windows/Linux, navegador y una sonda pública optativa.
Consulta [VALIDATION.md](docs/VALIDATION.md) para resultados y límites de esta entrega.

## Almacenamiento y recuperación

- `data/nory.sqlite3`: SQLite WAL, `synchronous=FULL`, transacciones atómicas;
  snapshots de carteras y libro de llenados/órdenes/posiciones cerradas.
- Totales de vida calculados a partir de cada llenado y cierre registrado, dentro
  de la misma transacción. El panel muestra 200 registros recientes; el CSV de
  llenados contiene el historial completo. La tasa de acierto agrupa posiciones
  completamente cerradas, no cada venta parcial.
- Memoria de precios limitada a 1,800 muestras por símbolo; disco de cotizaciones
  limitado a 300,000 muestras o siete días, lo que ocurra primero. Los diagnósticos
  detallados retienen un día y hasta 100,000 cambios/muestras; equity, 30 días.
  Estas podas no borran llenados, órdenes, cierres ni sus totales de vida.
- `logs/nory.log`: rotación de 2 MB × 4 archivos. Ningún dato local se versiona.
- Bloqueo del sistema operativo impide dos procesos sobre la misma base. No uses
  `--workers`, recarga automática ni alojes este servicio como servidor público.
  Se limita a loopback, con controles de origen y token local para escrituras.

Para una copia consistente, detén el servicio y copia la carpeta `data` completa.
Para conservar otro experimento, usa `--db` sin eliminar archivos existentes.
Un fallo de escritura detiene las decisiones; revisa el registro y reinicia.

## Solución de problemas

| Síntoma | Acción |
|---|---|
| No compra | Revisa historial, margen después de costes, liquidez, correlación y diagnóstico. Conservar efectivo es válido. |
| Cotización antigua | El ticker puede permanecer inactivo. Espera un mensaje nuevo; el heartbeat no refresca el precio. |
| Reconectando | Revisa Internet, proxy/firewall, TLS y acceso a los dos hosts WebSocket. Se reintenta con backoff. |
| Ya existe un motor | Cierra el proceso anterior; un cierre inesperado libera el bloqueo del SO. No borres la base. |
| Puerto ocupado | Usa `run.py --port 8766` y abre `http://127.0.0.1:8766`. |
| Configuración difiere | Usa los parámetros originales o `--db` con otra ruta; no sobrescribas el historial. |
| Bloqueo por riesgo | Investiga el diagnóstico y el historial; crea otro experimento si procede. No hay reinicio automático del bloqueo. |
| No hay Internet | `run.py --offline` abre el panel sin datos nuevos ni precios sustitutos. |

Arquitectura y auditoría: [ARCHITECTURE.md](docs/ARCHITECTURE.md),
[REPOSITORY_AUDIT.md](docs/REPOSITORY_AUDIT.md).
