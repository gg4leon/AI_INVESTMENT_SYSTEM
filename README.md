# AI Investment System (AIS) — v0.5

**Sistema de investigacion cuantitativa y backtesting historico (NO hace trading real).**

AIS consulta datos historicos de Yahoo Finance (`yfinance`), calcula indicadores y compara una estrategia experimental long-only/cash con comprar y mantener. El modo `--demo` usa **precios sinteticos generados localmente** y funciona sin acceso a Internet.

## Requisitos
- Python 3.11+ (Windows PowerShell, Linux o macOS).
- Las bibliotecas de `requirements.txt` (`pandas`, `numpy`, `yfinance`).
- Internet solo para analizar **datos reales historicos**. No hay ninguna conexion a broker ni envio de ordenes.

## Comandos en VS Code (PowerShell)

Desde la carpeta AIS:

```powershell
git pull origin main
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py --demo --symbols SPY
python main.py
```

**El comando con `--demo` es una prueba offline y usa DATOS INVENTADOS.** `python main.py` descarga un historial de aproximadamente 2 años para SPY, BTC-USD y EURUSD=X. Si Yahoo no responde, el sistema no inventa cotizaciones y muestra el error.

Otros modos:
```powershell
python main.py --mode analyze --symbols SPY
python main.py --mode backtest --period 5y --symbols BTC-USD
python main.py --demo --mode backtest --symbols EURUSD=X
```

## Arquitectura

- `data/market_data.py`: acceso a datos historicos de Yahoo.
- `data/demo_data.py`: serie OHLCV reproducible 100% sintetica.
- `analysis/indicators.py`: SMA10/30, RSI14 y MACD.
- `analysis/signal_engine.py`: clasificacion determinista explicable; sin parametros entrenados.
- `analysis/risk_engine.py`: mediciones descriptivas de volatilidad y drawdown.
- `backtesting/engine.py`: simulador historico long-only/cash, 0 apalancamiento, sin operacion real.
- `tests/`: tests unitarios e integracion offline.
- `.github/workflows/ci.yml`: GitHub Actions verifica codigo, pruebas y CLI demo.

## Diseño del backtest

1. Recibe velas **Open y Close**, en orden cronologico, con indicadores calculados. Rechaza precios invalidos y filas desordenadas.
2. Tras 50 velas de calentamiento, crea cada señal con **solo las velas anteriores** a la fecha de ejecucion; nunca consulta la vela actual para decidir.
3. Ejecuta la orden simulada **a la apertura siguiente**; suma comision de 10 puntos basicos por lado y 5 puntos basicos de deslizamiento por lado.
4. Estrategia experimental: `CANDIDATO_COMPRA` entra largo si no hay posicion; `CANDIDATO_VENTA` sale si hay posicion. Ademas, salida si el cierre anterior queda 8% bajo el precio de entrada, ejecutada a la siguiente apertura (puede haber gaps).
5. Asigna solo el **25% del efectivo disponible** en cada entrada; no hace ventas en corto, margen, prestamos ni compras adicionales.
6. Registra toda entrada/salida completada, curva de capital, rendimiento neto, drawdown, volatilidad anualizada, Sharpe simplificado, exposicion y porcentaje de operaciones cerradas positivas.
7. Comparacion con buy-and-hold **bruto** sin comisiones desde final del calentamiento (no es perfectamente comparable con la estrategia de asignacion parcial de capital).

**Capital inicial: 10,000 unidades FICTICIAS de la moneda de cotizacion (usualmente USD), NO son pesos de la cuenta real ni requieren deposito alguno.**

Las clases de activos tienen sesiones distintas (acciones, forex, cripto 24/7). La anualizacion usa 252 periodos diarios para SPY/forex y 365 para BTC, sin corregir festivos; es una aproximacion. El Sharpe supone tasa libre de riesgo 0. Los reportes no incluyen intereses del efectivo, impuestos, liquidez, spreads variables, dividendos por separado ni beneficios del lending. Una posicion abierta al final se valora al ultimo cierre sin comision de liquidacion estimada.

## Archivos de salida (locales, ignorados por Git)

```
data/SPY_analyzed.csv
data/SPY_report.json
data/SPY_backtest_equity.csv
data/SPY_backtest_trades.csv
data/SPY_backtest_summary.json
```

Los nombres BTC y EURUSD se construyen del mismo modo. Nunca subir claves de APIs.

## Limitaciones y proximos pasos

Este programa **funciona como analizador y backtester**, no es una estrategia validada o rentable. Tres indicadores correlacionados no dan probabilidad de exito. Backtesting historico puede sobreajustarse o tener sesgo de seleccion. Para evaluar utilidad real faltan validacion fuera de muestra, pruebas walk-forward, analisis estadistico, comparadores con costos equivalentes y paper trading cronologico con mercado actual. Las fuentes de Yahoo pueden estar incompletas o demoradas. No usar dinero real basandose en estas etiquetas.

En caso de duda, comienza con `python main.py --demo` y luego `python main.py`. Revisa el resultado de las pruebas de GitHub Actions antes de fusionar una propuesta de cambios.
