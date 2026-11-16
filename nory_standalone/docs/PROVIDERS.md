# Fuentes y permisos

Consulta de documentación oficial: **16 de noviembre de 2026**. Los planes,
tarifas y disponibilidad pueden cambiar. No se integran cuentas de inversión.

| Fuente | Cobertura y conexión | Requisitos / decisión |
|---|---|---|
| Coinbase Exchange | Cripto spot USD; WebSocket público `ticker` y `heartbeat`. | Implementado sin autenticación. Ticker se actualiza con matches, no con cada latido. Tamaño bid/ask del mejor nivel. |
| Kraken v2 | Cripto spot USD; `ticker`, `event_trigger=bbo`, sin snapshot inicial. | Implementado sin autenticación. Se aceptan solo updates con timestamp y tamaños válidos. |
| Alpaca Market Data | Acciones y ETF de EE. UU. Basic ofrece IEX en vivo, 30 símbolos; la documentación consultada lista cobertura consolidada en Algo Trader Plus a 99 USD/mes. | Necesita credenciales y autorización de datos. IEX no representa todo el mercado. No implementado: no se proporcionaron permisos/credenciales y no se añade autenticación de inversión. |
| Twelve Data | Acciones/ETF y otros mercados. Basic consultado: 8 solicitudes/minuto, 800/día y 8 créditos WebSocket de prueba. | Requiere clave, verificar derechos de uso y cobertura por instrumento. El streaming de precios no garantiza bid/ask y profundidad para este modelo. No implementado por incompatibilidad no resuelta. |

Los precios se consultan directamente en las páginas oficiales; no se promete
que una modalidad gratuita dé datos consolidados o permiso de redistribución.
Para uso no visual/automatizado también hay que verificar los derechos del plan.
Yahoo/yfinance del proyecto original es análisis histórico no oficial, no una
fuente equivalente de bid/ask en tiempo real; no se importa en Nory standalone.

## Límites de suscripción

El límite de 40 símbolos en la configuración es **local**. Los productos y las
suscripciones reales dependen del proveedor. Coinbase publica restricciones de
conexión/suscripción por producto y canal, no una garantía de disponibilidad de
todos los productos configurados. Nory usa una conexión por proveedor, una petición
de suscripción al conectar y backoff de 1–30 s con jitter al reconectar. El panel
muestra confirmaciones y rechazos; no lanza consultas HTTP de precios repetidas.

El motor 2.1 añade una carga inicial y recuperación puntual de contexto mediante
los endpoints públicos de velas. Coinbase recibe `granularity=60` y Kraken
`interval=1` por defecto. Se descarta todo intervalo no terminado; los cierres se
guardan con su fecha de adquisición y no se usan como cotizaciones de ejecución.
Se espacian peticiones (1.1 s Kraken, 0.25 s Coinbase) y un fallo por activo espera
al menos 90 s antes de reintentar al recibir nuevos datos. No es polling de precios.

Kraken permite una lista de símbolos y confirma suscripciones individualmente;
`bbo` dispara cambios del mejor bid/offer. No se cuenta el heartbeat como una
actualización. Los relojes y la actividad de un producto pueden dejar precios
antiguos aunque el socket siga conectado.

## Comisiones

Los valores por defecto son **supuestos** configurables por experimento, no una
afirmación de la tarifa vigente de una cuenta: Coinbase 60 bps/lado, Kraken
40 bps/lado, slippage 5 bps/lado más spread real observado. Se modela ejecución
taker porque no hay evidencia de prioridad maker. El motor conserva efectivo
cuando la amplitud observada no compensa el coste. No se garantiza rentabilidad.

## Documentación primaria

- [Coinbase Exchange: canales públicos y esquema ticker](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels)
- [Coinbase Exchange: conexiones y límites](https://help.coinbase.com/en/exchange/managing-my-account/market-data-connections)
- [Kraken: ticker v2, BBO y campos](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker)
- [Coinbase: velas históricas públicas](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)
- [Kraken: OHLC público y vela pendiente](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)
- [Alpaca: planes de Market Data](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca: datos de acciones en tiempo real](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
- [Twelve Data: planes individuales](https://twelvedata.com/pricing)
- [Twelve Data: WebSocket](https://twelvedata.com/docs/websocket/websocket-getting-started)
