# Validación de la entrega

Este documento registra la entrega inicial del motor 2.0. La corrección de
horizontes y logo oscuro del motor 2.1 se valida en [CONTEXT_FIX.md](CONTEXT_FIX.md).

Fecha: **16 de noviembre de 2026**. Entorno local de comprobación: Linux cloud,
Python 3.12.14 y Chromium real en modo headless. No se usó dinero real.

## Resultados ejecutados

| Comprobación | Resultado y alcance |
|---|---|
| Nory: suite completa con navegador habilitado | **52 pruebas pasaron**. Incluye datos, riesgo, ejecución, persistencia, API, train/test, escenarios, memoria, reconexión y 3 tamaños de navegador. |
| AIS original | **117 pruebas pasaron**, sin editar sus fuentes ni sus pruebas. |
| Compilación, Ruff y sintaxis JavaScript | Correctos. Código Python formateado con Ruff. |
| Conexión pública inicial, 20 s | Coinbase: **473** tickers válidos. Kraken: **2,813**. Cero mensajes inválidos; ambos endpoints respondieron. |
| Conexión pública sobre el código final, 20 s | Coinbase: **532** tickers válidos. Kraken: **2,023**. Cero mensajes inválidos, reconexiones o errores de suscripción. |
| Sesión paper autónoma con red real | **770 s (12 min 50 s)** desde inicio del motor; **70,536** actualizaciones aceptadas acumuladas, **1,715** ciclos del coordinador. Sin error fatal. Los contadores incluyen observación previa al inicio, como indica el historial. |
| Replay de cotizaciones registradas | Split 70/30, embargo de 18 s, selección solo con entrenamiento. La estrategia elegida fue **efectivo**; el informe preserva los resultados de cada hipótesis. |
| Navegador | Dashboard, Mercados, Operaciones e Inteligencia; pestañas internas, selectores, filtros, start/stop. Vistas de **1440, 768 y 390 px** sin desbordamiento horizontal ni errores JavaScript. |
| Continuidad al navegar | Se comprobó con el motor activo: las cuatro vistas mantuvieron el estado de ejecución y siguieron llegando datos reales. |
| Reinicio y bloqueo | La recuperación conserva posiciones y cancela pendientes; un segundo motor sobre la misma base es rechazado. El bloqueo de emergencia sobrevive al reinicio. |
| Carga offline prolongada | **9,000 eventos fabricados**, seis activos, **3 h 20 min virtuales**. Varias posiciones simultáneas, saldo no negativo, límites de posiciones y memoria de historial acotada. No es una prueba de conectividad. |
| Conservación del original | Los 61 archivos base se inventariaron. Solo se añaden Nory y su workflow. SVG original y copia con bytes idénticos. |

Los valores exactos y fechas de las conexiones están en:

- [Sonda inicial](evidence/live-probe.json).
- [Sonda del código final](evidence/live-probe-final.json).
- [Sesión autónoma y diagnósticos por mercado](evidence/live-soak.json).
- [Validación con cotizaciones públicas registradas](evidence/recorded-validation.json).

La sesión prolongada se ejecutó durante el desarrollo; después se reforzaron
reintentos de persistencia y se volvió a ejecutar la suite completa y la conexión
pública sobre el código final. Las evidencias no se presentan como una prueba
de funcionamiento durante días ni de rentabilidad.

## Casos de riesgo y contabilidad comprobados

- Un precio conocido, recibido antes de decidir o fechado antes de la decisión
  no puede llenar una orden. Fechas del fill y recepción deben ser posteriores.
- Repetir start, mensajes, checkpoints o un fill parcial no duplica trabajadores,
  gasto ni comisiones. Las reservas de entradas cuentan para capacidad y efectivo.
- Comisiones por ambos lados, spread y slippage reducen equity incluso con precios
  constantes; venta y cierre reconcilian con saldo y resultados registrados.
- Una caída no explicada del 5 %, datos vencidos, posiciones sin precio fresco,
  correlación desconocida, drawdown y límites de entrada bloquean compras.
- Una entrada parcial no impide cancelar el resto y registrar una salida de riesgo.
- Una transacción fallida hace rollback. Un reintento conserva el lote completo
  de quotes, órdenes y fills, evitando guardar saldo sin su historial.
- Alterar solo el futuro del holdout no cambia entrenamiento ni selección.
- Mercados sintéticos alcista, bajista y lateral, siempre etiquetados como pruebas.
- Sin suficientes cierres, el intervalo de evidencia no se calcula ni se inventa
  ventaja. Una serie de pérdidas permanece negativa en el bootstrap descriptivo.

## Reproducir los checks

Desde la raíz, usando un entorno Python con `requirements-browser.txt` instalado:

```bash
python -m ruff check nory_standalone
python -m ruff format --check nory_standalone
python -m compileall -q nory_standalone
python -m playwright install chromium
NORY_BROWSER_TESTS=1 python -m pytest nory_standalone/tests -q
python -m nory_standalone probe --seconds 20
```

En PowerShell, habilita navegador con `$env:NORY_BROWSER_TESTS="1"` y ejecuta
`python -m pytest nory_standalone/tests -q`. Si Chromium ya está instalado,
`NORY_CHROMIUM_EXECUTABLE` puede apuntar a su ejecutable. La suite normal sin esa
variable ejecuta **49** pruebas y omite explícitamente las 3 de navegador.

La CI nueva configura Python 3.11/3.12 en Linux, Python 3.12 en Windows y un job
Chromium separado. La sonda real es optativa mediante `workflow_dispatch` y no
confunde fixtures offline con disponibilidad de un proveedor. El estado remoto
y los logs se consultan en el PR/Actions; los resultados locales anteriores no
se presentan como resultados de Windows.

## Límites de estas verificaciones

No se ejecutó manualmente el `.bat` en una laptop Windows física i5/16 GB. Las
pruebas de proceso/archivos se incluyen en CI Windows, pero eso no mide ese
hardware. La observación Linux mostró un proceso de unas decenas de MB de RAM;
no es un benchmark reproducible de capacidad máxima.

La desconexión/reconexión se fuerza con un socket controlado en pruebas. Las
sondas públicas no sufrieron una interrupción real en esa ventana, por lo que
no constituyen una prueba de reconexión de los exchanges bajo un corte real.

Los históricos públicos registrados cubren minutos, no un conjunto multianual
representativo. No hay evidencia estadística suficiente de ventaja; tampoco se
ha certificado funcionamiento continuo nocturno o durante días. Los llenados,
las comisiones configuradas y la liquidez obtenible siguen siendo supuestos de
paper trading. Se necesita historial prospectivo extenso antes de valorar una
hipótesis, y esta aplicación no implementa ejecución con dinero real.
