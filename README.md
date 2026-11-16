# AI Investment System (AIS) — v0.4 (experimental)

Proyecto educativo de análisis técnico y simulación. **No realiza operaciones reales**, no utiliza llaves de bróker y no genera recomendaciones personalizadas. Todo resultado debe tratarse como hipótesis a validar.

## Qué incluye
- Datos históricos de SPY, BTC-USD y EURUSD=X mediante `yfinance` (pueden estar retrasados o incompletos).
- Indicadores de v0.3: SMA10, SMA30, RSI14 y MACD.
- Motor determinista de señales: `CANDIDATO_COMPRA`, `CANDIDATO_VENTA`, `ESPERAR`, `SIN_SENAL`.
- Señales explicables, validación de datos, puntuación **heurística** de acuerdo (no precisión estadística).
- Riesgo histórico descriptivo: volatilidad de 20 cierres y máximo drawdown hasta 60 cierres.
- Pruebas unitarias offline, sin operar ni llamar servicios pagos.

## Instalación (PowerShell, Windows)
En la carpeta del proyecto, activa tu entorno virtual:
```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
python -m unittest discover -s tests -v
```

## Seguridad y límites
- No hay conexión a bróker, envío de órdenes, optimización de parámetros ni garantías de rendimiento.
- Las señales se calculan con datos históricos hasta la última vela disponible; un cierre del día puede no estar consolidado.
- El acuerdo de 3 indicadores correlacionados **no** representa 100% de certeza.
- SPY negocia en sesiones; BTC 24/7; Forex tiene otras convenciones. No compararlos directamente.
- No usar capital real sin backtesting fuera de muestra, costos de operación, deslizamiento y validación independiente.
- Usa `.gitignore` para no publicar `.venv`, credenciales ni archivos generados.
