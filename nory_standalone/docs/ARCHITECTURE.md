# Arquitectura de NORY 2.0

## Elección tecnológica

FastAPI + asyncio + WebSockets + HTML/CSS/JavaScript sin framework cliente.
Un único proceso Python sirve el panel y coordina el motor. A diferencia del
ciclo de ejecución de un dashboard Streamlit, navegar o volver a renderizar
una vista no crea trabajadores ni vuelve a ejecutar la estrategia. El cliente
recibe snapshots por SSE una vez por segundo. No se necesita compilar frontend,
instalar Node ni mantener un servidor separado: `python run.py` abre el navegador.

El servicio y la interfaz están separados por una API local; cada fuente y
estrategia se puede extender sin modificar el panel. El núcleo de replay es el
mismo que en vivo, con reloj suministrado y ejecución posterior al evento de decisión.
SQLite escribe en un hilo mediante transacciones pequeñas, para no bloquear la
recepción de WebSockets. Lecturas WAL usan conexiones distintas.

```text
Coinbase WS ─┐                       ┌─ riesgo / presupuesto / reservas
            ├─ validación ─ buffer ─┼─ cinco reglas fijas ─ órdenes pendientes
Kraken WS ──┘   por proveedor       └─ cotización posterior ─ fills simulados
                       │                                 │
                 memoria acotada                  transacción SQLite WAL
                       │                                 │
                       └──────── API local / SSE ────────┘
                                      │
                        cuatro vistas web independientes
```

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `nory/config.py` | Parámetros validados, universo, versionado por huella. |
| `nory/models.py` | Cotizaciones, órdenes, posiciones y carteras tipadas. |
| `nory/feeds.py` | Subscripción pública, TLS, parseo, salud y reconexión. |
| `nory/strategies.py` | Indicadores pasados, reglas explicadas, correlaciones alineadas. |
| `nory/core.py` | Motor determinista, riesgo, reservas, ejecución y contabilidad. |
| `nory/storage.py` | WAL, atomicidad, libro, agregados, retención y consultas. |
| `nory/engine.py` | Coordinador asíncrono, bloqueo entre procesos, start/stop, recuperación. |
| `nory/backtest.py` | Replay, selección con entrenamiento, embargo y holdout. |
| `server.py` | Lifespan, API local, SSE, controles, exportación y validación en segundo plano. |
| `static/` | Cuatro vistas, gráficos SVG derivados del historial, filtros y diseño adaptable. |
| `run.py`, `__main__.py` | Lanzamiento, CLI, sonda pública y configuración. |

## Invariantes

1. Una cartera por proveedor/estrategia. Una moneda, USD ficticio. Sin cortos.
2. Dos motores no pueden escribir la misma base. Start repetido es idempotente.
3. Una orden por activo/cartera; reservas contabilizadas antes de nuevas entradas.
4. `exchange_ts > created_at`, `received_ts > created_at` y un identificador nuevo
   son necesarios para un fill. La misma actualización no llena dos veces la orden.
5. Una transacción guarda juntos cuenta, órdenes, fills, cierres y agregados.
   Un fallo hace rollback; el coordinador deja de decidir y muestra un error.
6. Reiniciar no reactiva trading: posiciones preservadas, pendientes canceladas,
   historial técnico calentado de nuevo y bloqueos persistidos.
7. Datos vencidos no compran ni llenan órdenes. Una posición sin marca fresca
   bloquea nuevas entradas; su valoración se etiqueta con última cotización conocida.
8. El replay recibe eventos en orden de recepción y solo utiliza el prefijo observado.
   La selección no consulta el holdout y no modifica la producción.

## Hipótesis y limitaciones

Las cantidades son `float` para investigación fraccional, con tolerancias explícitas
en cierres y reconciliación; no representan precisión, lotes ni saldos de un exchange.
Las posiciones se valoran como liquidación neta estimada. Comisiones registradas
no incluyen una futura salida hasta que ocurra; equity sí descuenta su coste estimado.

El buffer mantiene solo el mensaje más reciente entre evaluaciones; las anomalías
de caída se examinan también al recibir mensajes anteriores al agrupamiento. La
simulación no ve cada posible ejecución intraintervalo ni reconstruye el libro.
Las decisiones se basan en muestras de intervalos distintos; baja actividad aumenta
la duración efectiva de una ventana o reinicia el calentamiento si hay huecos grandes.

Todo el universo inicial pertenece a una categoría, cripto spot. El límite de esa
categoría es también un límite agregado de mercado. Un futuro proveedor de acciones
necesita esquema de categorías, calendario, licencias, ajustes y pruebas propias.
El motor no pretende inferir noticias ni exposición a mercados que no observa.

La carga objetivo es una laptop i5 / 16 GB con el universo predeterminado. No se
verificó hardware Windows físico ni se garantiza una cifra de capacidad. La memoria
de observaciones es acotada; el libro completo crece con los llenados y se debe
respaldar. El panel consulta agregados de vida y muestras acotadas.
