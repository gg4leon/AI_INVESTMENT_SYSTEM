# Lanzador 2.1.1: puerto ocupado / WinError 10048

El error indica que otro proceso utiliza `127.0.0.1:8765`. Podía quedar una
instancia anterior abierta mientras el nuevo proceso iniciaba su motor y luego
fallaba al enlazar el puerto. El temporizador del navegador tampoco esperaba
que el servicio terminara de arrancar.

Ahora el lanzador reserva un socket TCP de loopback **antes** de construir el
servicio y entrega ese mismo socket a Uvicorn. No hay una comprobación seguida
de un segundo bind que deje libre una ventana de carrera. Windows usa
`SO_EXCLUSIVEADDRUSE`; otros sistemas usan `SO_REUSEADDR` para permitir reiniciar
tras conexiones cerradas sin permitir dos listeners activos.

Si detecta una instancia Nory del mismo experimento mediante `/api/health`,
abre su dirección y termina sin crear otro motor. La identidad usa un hash de
la ruta canónica de la base y la configuración, sin publicar la ruta ni el saldo.
Para versiones antiguas sin ese endpoint, reconoce su OpenAPI en el lanzamiento
predeterminado y avisa si la versión activa difiere de la instalada. No lee el
token de sesión ni envía controles de trading al reconocer una instancia.

Si el puerto pertenece a otro servicio o experimento, prueba hasta diez puertos
siguientes y muestra la dirección que realmente utiliza. El navegador solo se
abre tras el startup del servidor. Si falla el motor, no abre un panel que todavía
no está disponible. Se mantiene el bloqueo del SO por base de datos.

El `.bat` transmite opciones al programa, como `--port 8766` o `--offline`.
Las estrategias, carteras, costes y diseño no cambian en este parche.

Las pruebas incluyen sockets reales, un servicio HTTP ajeno, reconocimiento de
Nory actual y anterior, identidades de bases distintas, agotamiento de puertos,
y dos lanzamientos reales del CLI sobre la misma base y puerto: el segundo sale
correctamente y el primero continúa activo. La suite completa también se ejecuta
en CI Windows; no equivale a probar manualmente la laptop del usuario.

Validación local: **71 pruebas pasaron**, incluidas las siete regresiones del
lanzador y tres comprobaciones Chromium. Ruff, formato y compilación correctos.
