# AIS v0.6 — Investment Terminal

**Aplicación de análisis financiero y backtesting histórico en modo simulación.** No realiza transacciones reales ni solicita acceso a bancos, brókeres o claves API.

## Inicia la app en Windows (VS Code)

Abre la carpeta `AI_INVESTMENT_SYSTEM` en VS Code y, en la terminal PowerShell:

```powershell
git status
git pull origin main
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Si la terminal ya muestra `(.venv)`, puedes omitir la activación. Si `git status` muestra archivos locales modificados, guárdalos o respáldalos primero; no sobrescribas trabajo.

Tras instalar dependencias, en Windows también puedes abrir **`INICIAR_AIS.bat` con doble clic** para arrancar el dashboard sin introducir comandos. La app se enlaza a `127.0.0.1` (solo este equipo).

Streamlit inicia un servidor **local** que normalmente se abre en `http://localhost:8501` desde el navegador. Para cerrarlo, vuelve a la terminal y pulsa `Ctrl+C`.

La primera pantalla no contiene datos hasta ejecutar una simulación. Empieza por **Demo sintética (sin Internet)** y presiona **Ejecutar análisis y simulación**. Después prueba **Históricos de Yahoo** para descargar precios reales históricos cuando haya Internet. Los datos reales pueden estar demorados o incompletos. **Nunca se sustituyen por precios inventados si la descarga falla.**

## Qué hace la interfaz

- **Resumen:** capital ficticio, curva de equity, drawdown, exposición, señales experimentales y riesgo.
- **Mercado:** velas OHLC y gráficos interactivos de SMA10, SMA30, RSI14 y MACD.
- **Operaciones:** historial de operaciones cerradas (simuladas) y exportación CSV.
- **Historial:** sesiones y parámetros guardados localmente en SQLite, más exportación JSON.
- **Metodología:** supuestos y limitaciones.
- **Barra lateral:** origen de datos, mercado, historial, capital ficticio, porcentaje por entrada, stop, comisiones y deslizamiento.

**No hay inversión en vivo.** Los importes del panel son ficticios y están en **unidades de la moneda de cotización del activo**, no implican saldo real en MXN ni requieren depositar dinero.

## Ejecuta pruebas

```powershell
python -m unittest discover -s tests -v
python main.py --demo --symbols SPY
```

El CLI de v0.5 continúa disponible: `python main.py` o `python main.py --mode backtest --period 5y --symbols SPY`.

## Diseño y datos

```text
streamlit_app.py           # interfaz local (Streamlit + Plotly)
app/service.py             # orquestación de análisis/simulación
app/storage.py             # base SQLite local
data/demo_data.py          # fuente sintética determinista
data/market_data.py        # fuente histórica Yahoo
analysis/                  # SMA, RSI, MACD, señales y riesgo
backtesting/engine.py      # motor histórico long-only/cash
data/ais_history.sqlite3   # se crea localmente; ignorada por Git
```

Cada sesión contiene el origen de datos, velas, señales, métricas, curva de capital y operaciones simuladas. SQLite **no está cifrado**; mantenlo en tu equipo y no publiques archivos con información privada. La aplicación se ejecuta localmente; **no proporciona usuarios, contraseñas, hosting, acceso remoto, ni autenticación**. No la expongas directamente a Internet ni la publiques como servicio sin medidas de seguridad adicionales.

## Reglas del backtest

1. El indicador histórico se calcula con velas anteriores a la apertura de ejecución: no usa el futuro.
2. La señal se ejecuta a la siguiente apertura; comisión y deslizamiento se aplican en la simulación.
3. Solo posiciones largas con asignación parcial de efectivo, sin margen ni venta corta.
4. Stop aproximado basado en el cierre anterior; el precio siguiente puede abrir más abajo (gap).
5. Registra operaciones cerradas, retornos netos, drawdown, volatilidad anualizada, Sharpe simplificado y exposición.
6. Línea de **comprar y mantener**: benchmark bruto sin comisiones ni misma exposición, por lo que no es una comparación ajustada al riesgo.

**No equivale a una estrategia probada o rentable.** Falta validación fuera de muestra, walk-forward, comprobación de sesgos, spreads variables, intereses del efectivo, fiscalidad y análisis estadístico. Yahoo Finance puede no ofrecer datos adecuados para operar y el último precio puede no estar cerrado. La "puntuación" del motor de señales indica acuerdo de reglas, **no probabilidad de acierto**.

AIS v0.6 mantiene el módulo de consola y agrega una interfaz para experimentación, no un asesor de inversiones ni un sistema de transacciones reales.
