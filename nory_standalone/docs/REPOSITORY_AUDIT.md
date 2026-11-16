# Inspección del proyecto de referencia

Base: `gg4leon/AI_INVESTMENT_SYSTEM`, rama `main`, commit
`772c9c6b75d1774a8aa29a039782ddd85d2a496a`.

Se comprobó el HEAD remoto antes de crear `feature/nory-2-standalone`.
La revisión inicial incluyó inventario completo de archivos, análisis AST de
todos los módulos Python y lectura de los motores, proveedores, almacenamiento,
políticas, validación, interfaz, pruebas, dependencias y CI. No había AGENTS.md
en el checkout. La aplicación AIS y sus archivos existentes se conservan intactos.

## Componentes útiles y decisión de reutilización

| Componente original | Aporte | Uso en Nory 2.0 |
|---|---|---|
| `assets/ais_original.svg` | Identidad AIS original. | Copia exacta, sin transformación ni logo generado. |
| `nory/coinbase_public.py`, `nory/kraken_public.py` | Esquemas públicos ticker, bid/ask, tamaños, frescura y backoff. | Referencia de protocolo; nuevos adaptadores asyncio autónomos, contrastados con documentación oficial y conexión real. |
| `nory/live_paper.py`, `nory/book.py` | Libro común por cuenta, costes y precio posterior a decisión. | Principios conservados, ejecución y persistencia nuevas sin importar AIS ni migrar su base. |
| `nory/engine.py`, `analysis/` | Señales explicadas e indicadores. | Reglas transparentes con listas acotadas; sin pandas para cada tick. |
| `nory/performance.py` | Agregados de vida y benchmark con advertencia de exposición. | Métricas del libro nuevo; cierres agrupados por posición completa. |
| `nory/validation.py`, `backtesting/engine.py` | Señal con información pasada, siguiente precio y train/test. | Replay del mismo núcleo usado en vivo, separación temporal y embargo. |
| `tests/` | Casos de coste, look-ahead, pausa, fuentes y recuperación. | Se conservan sin editar; además se añaden pruebas independientes de Nory. |

## Hallazgos concretos

1. `streamlit_app.py` agrupa siete áreas, fuentes históricas y modos sintéticos/en
   vivo en 1,132 líneas. No es una base adecuada para las cuatro vistas centradas
   exclusivamente en Nory; se entrega interfaz independiente.
2. `LivePaperRunner`, `MicroAutoRunner` y lectores públicos usan hilos por proceso.
   La protección local no coordina procesos distintos sobre una misma base.
   Nory añade un bloqueo del SO y un coordinador asíncrono único.
3. Las conexiones SQLite originales revisadas no activan WAL; parte del DDL se
   ejecuta al abrir cada conexión. Nory prepara el esquema una vez, separa lectores
   y escritor y mantiene transacciones con snapshots y contabilidad atómicas.
4. `LivePolicy.initial_cash` existe, pero el esquema de `live_state` fija los valores
   iniciales a 10,000 y el procesador no aplica ese campo al crear la cuenta. Nory
   inicializa todas sus carteras a partir del capital configurado y prueba su persistencia.
5. `live_orders` borra órdenes ejecutadas/canceladas/vencidas. El historial de fills
   no explica por sí solo órdenes sin ejecución. Nory conserva las órdenes y estados.
6. `summarize_live` cuenta eventos SELL como cierres, incluyendo parciales. Nory
   distingue llenados, ventas y posiciones completamente cerradas para tasa de
   acierto y medias por operación.
7. La política pasada como argumento no queda congelada con una huella del
   experimento en el libro live. Nory rechaza reutilizar una base con costes,
   universo o parámetros diferentes para evitar reinterpretar resultados.
8. El feed Kraken original limita una lista fija de cinco pares y Coinbase una
   lista fija de quince. Nory acepta un universo configurado, con límite local
   de recursos, y muestra confirmaciones/rechazos del exchange.
9. `risk/risk_manager.py`, `strategies/signals.py`, `trading/simulator.py` y
   `config/settings.py` son archivos vacíos; no hay lógica reutilizable allí.
10. AIS ya separa fuentes y evita presentar su MicroLab como mercado auténtico.
    Se conserva ese criterio: Nory no importa el generador sintético ni usa
    yfinance, RSS o noticias para llenar órdenes en vivo.

No se cambiaron estos módulos originales. Las mejoras están aisladas en
`nory_standalone/`; la única adición externa es su workflow de CI.

## Verificación de conservación

La suite original pasó: **117 pruebas** con `python -m unittest discover -s tests -v`.
El logo copiado tiene el mismo SHA-256. `git diff --name-status` contra la base
solo debe mostrar archivos añadidos bajo Nory y el workflow nuevo.

El inventario siguiente registra todos los archivos versionados de la base,
incluidos módulos vacíos, configuración, tests y recursos binarios. Las cantidades
de funciones/clases se obtuvieron mediante AST, sin ejecutar módulos para inspeccionarlos.


| Archivo base | Líneas / bytes | Funciones / clases | SHA-256 (12) |
|---|---:|---:|---|
| `.github/workflows/ci.yml` | 43 líneas | — | `f3c145aa979f` |
| `.gitignore` | 26 líneas | — | `9848664e8430` |
| `.streamlit/config.toml` | 13 líneas | — | `0d5497283381` |
| `INICIAR_AIS.bat` | 17 líneas | — | `65a285401e46` |
| `README.md` | 626 líneas | — | `86b6f85c7a2c` |
| `analysis/indicators.py` | 125 líneas | 3 / 0 | `848a5aed9acb` |
| `analysis/risk_engine.py` | 39 líneas | 1 / 1 | `24f25b73b122` |
| `analysis/signal_engine.py` | 128 líneas | 4 / 2 | `c087a0f6ee77` |
| `app/__init__.py` | 1 líneas | 0 / 0 | `ae14fa406ffc` |
| `app/markets.py` | 80 líneas | 1 / 1 | `40d7eda6be49` |
| `app/news.py` | 79 líneas | 4 / 1 | `fe40d55c854b` |
| `app/performance_ui.py` | 277 líneas | 4 / 0 | `807e5008b0ab` |
| `app/service.py` | 107 líneas | 1 / 0 | `f003e09457d4` |
| `app/storage.py` | 87 líneas | 4 / 0 | `ce38563b3e57` |
| `assets/ais_original.svg` | 5 líneas | — | `091ae5d4b338` |
| `automation/__init__.py` | 1 líneas | 0 / 0 | `a243aaf6aecb` |
| `automation/paper.py` | 246 líneas | 8 / 1 | `25bafd3b6087` |
| `automation/worker.py` | 109 líneas | 3 / 0 | `6ba5dc29f49c` |
| `backtesting/__init__.py` | 1 líneas | 0 / 0 | `d01a5488527c` |
| `backtesting/engine.py` | 214 líneas | 3 / 2 | `2829c27c3ef2` |
| `config/settings.py` | 0 líneas | 0 / 0 | `e3b0c44298fc` |
| `data/demo_data.py` | 29 líneas | 1 / 0 | `9c993447b314` |
| `data/market_data.py` | 51 líneas | 1 / 0 | `ea1b689b6e5c` |
| `main.py` | 129 líneas | 2 / 0 | `bc2c8c6fe8f9` |
| `nory/__init__.py` | 1 líneas | 0 / 0 | `6b92e1431192` |
| `nory/auto_runner.py` | 157 líneas | 5 / 1 | `49c988fa9d42` |
| `nory/book.py` | 466 líneas | 13 / 0 | `211d4c934123` |
| `nory/coinbase_probe.py` | 44 líneas | 1 / 0 | `7574bc2a2aaa` |
| `nory/coinbase_public.py` | 184 líneas | 10 / 1 | `4b416970eed9` |
| `nory/engine.py` | 141 líneas | 6 / 2 | `1f6758d3be0b` |
| `nory/kraken_probe.py` | 46 líneas | 1 / 0 | `93d55e91a3d5` |
| `nory/kraken_public.py` | 296 líneas | 21 / 3 | `b4511f78b3fc` |
| `nory/live_paper.py` | 474 líneas | 14 / 1 | `8cb7899d8286` |
| `nory/live_runner.py` | 157 líneas | 5 / 1 | `01cae16db984` |
| `nory/micro_feed.py` | 96 líneas | 3 / 1 | `dfb058ad036a` |
| `nory/micro_lab.py` | 545 líneas | 16 / 1 | `e41d0aac577f` |
| `nory/micro_worker.py` | 82 líneas | 2 / 0 | `fbd7d24235ac` |
| `nory/performance.py` | 196 líneas | 5 / 1 | `82b4b139b009` |
| `nory/validation.py` | 175 líneas | 5 / 1 | `413b6a03b4d7` |
| `nory/worker.py` | 157 líneas | 5 / 0 | `178ba0c50a36` |
| `reports/first_analysis.png` | 95122 bytes | — | `533103ea0d0e` |
| `requirements.txt` | 7 líneas | — | `402ced52b2b9` |
| `risk/risk_manager.py` | 0 líneas | 0 / 0 | `e3b0c44298fc` |
| `strategies/signals.py` | 0 líneas | 0 / 0 | `e3b0c44298fc` |
| `streamlit_app.py` | 1132 líneas | 12 / 0 | `3c95e02496b2` |
| `tests/test_app_service.py` | 51 líneas | 4 / 1 | `f989fdb8e4a7` |
| `tests/test_app_storage.py` | 44 líneas | 3 / 1 | `f9db5d22da52` |
| `tests/test_auto_runner.py` | 122 líneas | 13 / 1 | `0517d46e3b83` |
| `tests/test_backtest.py` | 123 líneas | 13 / 1 | `0d64af595f99` |
| `tests/test_coinbase_and_performance.py` | 177 líneas | 15 / 2 | `cb916f6e903b` |
| `tests/test_integration.py` | 32 líneas | 1 / 1 | `a4d4c3c52abd` |
| `tests/test_kraken_live.py` | 253 líneas | 22 / 2 | `3b69cad83e52` |
| `tests/test_live_runner.py` | 89 líneas | 11 / 2 | `30399592b643` |
| `tests/test_micro_lab.py` | 199 líneas | 18 / 1 | `6a9ce14ed0cb` |
| `tests/test_news.py` | 41 líneas | 2 / 1 | `38acbcd5adab` |
| `tests/test_nory.py` | 246 líneas | 21 / 1 | `5118e4d7e497` |
| `tests/test_paper_automation.py` | 119 líneas | 12 / 1 | `f821cb198889` |
| `tests/test_signal_engine.py` | 77 líneas | 11 / 1 | `c3194a6595bd` |
| `tests/test_streamlit_app.py` | 40 líneas | 3 / 1 | `4517be1fb60c` |
| `tests/test_validation.py` | 84 líneas | 6 / 1 | `68acefe468f2` |
| `trading/simulator.py` | 0 líneas | 0 / 0 | `e3b0c44298fc` |
