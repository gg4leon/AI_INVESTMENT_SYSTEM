# Motor 2.1: horizontes de análisis y logo oscuro

## Problema corregido

El motor 2.0 contrastaba fluctuaciones de unas 120 observaciones de un segundo
con costes de ida/vuelta más margen adicional de aproximadamente 1.65 % Coinbase
y 1.25 % Kraken, más spread. Su buffer se reiniciaba tras ocho segundos sin
ticker. El resultado podía ser un calentamiento repetido o entradas prácticamente
inexistentes por desproporción entre costes y horizonte.

## Comportamiento actual

- La evaluación sigue cada 0.5–1 s, con precios nuevos. El contexto de las reglas
  pasa a intervalos de un minuto: medias de 15/60 minutos y ventana de hasta cuatro
  horas, configurables como experimento. No se rebajan comisiones ni controles.
- Al iniciar se consultan velas públicas cerradas del mismo exchange. La prueba
  de red cargó 300 cierres por activo en los seis pares de Coinbase y seis de
  Kraken. Los datos se guardan para reutilizarlos después de reiniciar.
- Una pausa breve no borra el análisis. Un hueco grande o cobertura escasa solicita
  recuperación limitada. Cotizaciones de más de ocho segundos siguen sin poder
  comprar ni ejecutar órdenes; preservar contexto no convierte un precio viejo en nuevo.
- El historial tiene la hora de cierre y la hora a la que la app lo adquirió.
  Se omite la vela REST todavía abierta. El replay no accede a los puntos antes
  de `known_at`. Una captura demasiado corta y sin contexto suficiente se rechaza
  como backtest, en lugar de presentar un calentamiento como resultado válido.
- Los cierres históricos nunca llenan órdenes. Las ejecuciones siguen necesitando
  una nueva cotización bid/ask recibida y fechada después de la decisión.
- El panel conserva su diseño y ahora muestra evaluaciones, ejecuciones, margen
  técnico y umbral en porcentaje. Una curva plana sin posiciones dice explícitamente
  que el capital permanece en efectivo.

El margen sigue siendo una hipótesis técnica, no beneficio esperado demostrado.
Un mercado tranquilo puede seguir sin ofrecer entradas que compensen los costes.
La corrección permite considerar el contexto adecuado; no garantiza operaciones
continuas ni beneficios.

## Conservación del historial y Windows

Una base de reglas 2.0 se deja intacta y el motor selecciona otra base con sufijo
`v2_1_<huella>`. Se informa en el panel de que es un experimento nuevo. Así se
conservan las carteras antiguas sin mezclar sus resultados con las reglas nuevas.
Los cambios de parámetros dentro de 2.1 siguen exigiendo una base independiente.

El `.bat` detecta dependencias nuevas o versiones diferentes antes de ejecutar,
incluyendo el cliente HTTP usado para adquirir el contexto público.

## Logo

`ais_original.svg` y el recurso original de AIS permanecen intactos.
`ais_dark.svg` usa las mismas rutas SVG y las mismas formas rojas; cambia solo
el relleno de las letras de negro a blanco. El contenedor CSS ahora es transparente.
Se comprobó visualmente en Chromium en escritorio y móvil y se compararon las
rutas de ambos SVG. No se generó ni redibujó un logo.

## Validación ejecutada

- **64 pruebas locales pasaron**, incluidas tres vistas de navegador a 1440,
  768 y 390 px. Ruff, compilación y sintaxis JavaScript correctos.
- Regresión con costes predeterminados: contexto pasado de varias horas → señal
  válida → orden pendiente → cotización posterior → fill, comisión y cambio de
  capital. Los precios de esa regresión son **fabricados**, no una prueba de red.
- Se comprueba que contexto sin quotes no puede crear órdenes ni fills; una
  cotización vencida no opera aunque haya cuatro horas guardadas; un primer tick
  con caída no explicada sigue bloqueándose.
- El contexto adquirido durante el holdout no cambia entrenamiento ni selección.
  La caché sobrevive al reinicio sin crear precios nuevos. El archivo de una cartera
  2.0 conserva exactamente sus bytes al seleccionar el experimento 2.1.
- Conexión **real**: carga de contexto y WebSocket verificados para los 12 flujos;
  después de reiniciar, el proceso quedó detenido y recuperó más de 120 puntos de
  contexto por activo. Véase [context-21-live.json](evidence/context-21-live.json).
- Replay del historial de la sesión real con contexto adquirido en su momento:
  [context-21-replay.json](evidence/context-21-replay.json). Un resultado sin fills
  continúa siendo válido cuando hay evaluaciones maduras que rechazan entradas;
  no se interpreta como prueba de ventaja.

La sonda de red y la regresión sintética prueban cosas distintas. No se certifica
rentabilidad, disponibilidad de los proveedores ni funcionamiento durante días.
