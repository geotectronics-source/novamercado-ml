# Guía paso a paso — cómo se construyó el Laboratorio 2

Esta guía recorre el [plan de trabajo](PLAN_DE_TRABAJO.md) fase por fase. Cada fase tiene:
**objetivo → qué se hizo → conceptos clave → dónde está el código → cómo verificarlo →
preguntas para comprobar que lo entendiste.** La idea es que puedas reproducirlo y defenderlo
en una revisión oral.

---

## Fase 0 · Leer el enunciado como un ingeniero de producto

Antes de escribir código, traduce el PDF a **requisitos verificables**. Ejemplos:

| Frase del enunciado | Requisito verificable |
|---|---|
| "no debe usar el reloj del sistema" | ninguna validación usa `date.today()` |
| "registros_guardados igual a 0" al reenviar | prueba automatizada de idempotencia |
| "a más tardar 2 minutos después" | recarga del modelo con sondeo ≤ 20 s |
| "GET /health … en menos de 1 minuto" | monitor cada 15 s, medido en la prueba de resiliencia |
| "las reglas deben ser generales" | intérpretes de números/fechas/nombres, no un `if` por ejemplo |

> **Lección:** la nota no depende solo del modelo; el evaluador ejecuta un programa automático
> que golpea el contrato, tumba MLflow y reinicia el producto.

---

## Fase 1 · Entorno y estructura

* Repositorio con `src/` (código instalable), `tests/`, `dags/`, `docker/`, `scripts/`, `docs/`.
* Entorno local con `uv` (Python 3.12): `uv venv .venv && uv pip install -r requirements/app.txt`.
* Los datos publicados van en `datos/`, que **no se versiona** (`.gitignore`).

**Pregunta:** ¿por qué el código vive en un paquete instalable (`pyproject.toml`) y no en scripts
sueltos? *(Pista: lo importan la API, el bootstrap y el DAG; y MLflow necesita poder
des-serializar las clases del modelo.)*

---

## Fase 2 · Análisis exploratorio

Hallazgos (`scripts/experimento.py` y el análisis inicial):

* 730 días (2024-03-01 → 2026-02-28), 10 tiendas × 12 familias, **sin huecos** ni negativos.
* La tienda 10 abrió el 2025-03-15 (menos historia) → validar fechas contra `fecha_apertura`.
* Estacionalidad semanal fuerte (viernes y sábado +20–40 %), picos en diciembre, tendencia
  creciente (~8 % anual).
* Todas las tiendas venden las 12 familias → si faltan familias en una solicitud es un error (E05).

**Pregunta:** ¿qué implica la tendencia creciente para un modelo de árboles? *(Fase 4.)*

---

## Fase 3 · Ingeniería de variables (`features.py`)

**Concepto clave — *training/serving skew*:** si calculas las variables de una forma al entrenar
y de otra al servir, el modelo falla en producción aunque el backtest se vea perfecto. Por eso
existe **una sola** función `construir_features(panel, catalogos)`:

* Entrenar: `panel` = histórico + observaciones.
* Servir: `panel` = historia de la tienda **antes** de la fecha + filas objetivo (ventas = NaN,
  promociones de la solicitud).

**Concepto clave — fuga de información:** todo rezago usa `shift(≥1)`, es decir, solo días
anteriores. La prueba `test_features_no_usan_el_futuro` multiplica por 10 las ventas del día
objetivo y del futuro y comprueba que las variables no cambian.

**Variables relativas:** en lugar de "ventas de ayer = 812", usamos "ventas de ayer / nivel
reciente = 1.07". Así el modelo aprende patrones que valen para tiendas grandes y pequeñas.

**Verificar:** `python -m pytest tests/test_modelo.py -k features`

---

## Fase 4 · Modelos (`modelo.py`, `entrenamiento.py`)

1. **Baseline** (`Baseline`): media del mismo día de la semana en las últimas 4 semanas. Siempre
   empieza con un baseline: si tu modelo de ML no le gana, no vale su complejidad.
2. **LightGBM global** (`ModeloLGBM`): un solo modelo para las 120 series; predice el
   **cociente** ventas / nivel reciente. Los árboles no extrapolan; el cociente sí se adapta a
   cambios de nivel porque el nivel entra como `base`.
3. **Ensamble** (`ModeloEnsamble`): promedio geométrico de LightGBM y una **regresión log-lineal**
   (`ModeloLogLineal`, Ridge con interacciones). Se agregó tras analizar los datos
   (`docs/ANALISIS_MODELOS.md`): la parte lineal extrapola, que es justo lo que a los árboles les falta.

Resultado del backtest con origen móvil (4 cortes): LightGBM y el ensamble, **−20 % de costo**
frente al baseline. El ensamble gana en diciembre y en el corte más reciente; LightGBM, en los
otros dos. Por eso **los tres compiten en cada entrenamiento** y se registra el mejor.

**Verificar:** `python scripts/experimento.py datos`

**Preguntas:** ¿por qué se evalúa en varios cortes y no en uno solo? ¿Qué pasaría en diciembre
si el modelo predijera ventas absolutas?

---

## Fase 5 · Cantidad sugerida (`costos.py`)

**Concepto clave — problema del *newsvendor*:** con costo asimétrico, la cantidad óptima no es
la media sino el cuantil τ = c_falt / (c_falt + c_sobr).

* Panadería: τ = 1/(1+2.5) = 0.29 → sugerir **menos** que lo esperado (k ≈ 0.85).
* Licores: τ = 2/(2+0.1) = 0.95 → sugerir **más** (k ≈ 1.60).

Se elige `k` por familia × tipo de tienda minimizando el costo real en una **ventana de
calibración** que el modelo no vio. Resultado: ~25–30 % menos costo que sugerir la media.

**Verificar:** `test_multiplicador_sigue_el_cuantil_critico` comprueba con datos normales que el
`k` óptimo coincide con el cuantil teórico.

**Pregunta:** ¿por qué la calibración debe hacerse fuera de muestra?

---

## Fase 6 · MLflow (`registro.py`, `ciclo.py`)

* Cada entrenamiento crea **tres runs** (baseline, LightGBM y ensamble) con parámetros, métricas técnicas
  (MAE, RMSE, WAPE, sesgo) y de negocio (`costo_total`), artefactos (multiplicadores,
  predicciones de validación) y el modelo *pyfunc*.
* El mejor se registra como **versión** en el Model Registry, con etiquetas (`costo_validacion`,
  `decision`, `motivo`).
* El modelo vigente se identifica con el **alias `vigente`** (no con "stages", que están obsoletos).

**Criterio de reemplazo:** candidato y vigente se evalúan en la **misma** ventana de 28 días,
fuera de muestra para ambos; se promueve si mejora el costo ≥ 1 % y pasa la sanidad.

**Verificar:** UI en <http://localhost:5000> → experimento `novamercado_pronostico` y modelo
`novamercado_pronostico_ventas`; `evidencia/mlflow.json`.

**Pregunta:** ¿por qué no se re-entrena con todos los datos después de decidir? *(Ver DECISIONES §5.)*

---

## Fase 7 · Defensa del contrato (`calidad/`)

Tres políticas: **reparar** (inequívoco), **advertir** (supuesto explícito), **rechazar** (422).
En vez de un `if` por ejemplo del catálogo, se construyeron **intérpretes generales**:

| Intérprete | Idea general |
|---|---|
| `mapear_campos` | forma canónica + sinónimos + similitud de texto |
| `interpretar_numero` | reconoce separadores de miles/decimales; marca lo ambiguo |
| `interpretar_fecha` | varios formatos; usa la lógica "si un número > 12 es el día" |
| `interpretar_tienda` | nombre de tienda o texto con un único número |
| `interpretar_familia` | forma compacta, singular/plural, similitud, palabras contenidas |

Asimetría importante: en **predicción** se responde con supuestos; en **observaciones** un
valor dudoso se **descarta**, porque será la "verdad" con la que se entrena.

**Verificar:** `python -m pytest tests/test_calidad.py tests/test_parsers.py -v` y
`evidencia/ejemplos_api.md` (E01–E10 + 6 casos fuera del catálogo).

**Ejercicio:** inventa un error nuevo (p. ej. `"fecha": "2026.03.02"`) y predice qué hará el
servicio antes de probarlo.

---

## Fase 8 · API FastAPI (`api/`)

* `main.py` solo traduce HTTP ↔ funciones de `servicio.py` (la lógica no está en los endpoints).
* El cuerpo se lee **crudo** (`request.body()`): si FastAPI validara primero con Pydantic,
  respondería 422 antes de que pudiéramos reparar.
* Después de limpiar, el resultado se valida con Pydantic en **modo estricto** (`contrato.py`).
* Las respuestas usan `response_model`: imposible omitir o renombrar un campo del contrato.
* Inyección de dependencias (`Dependencias`): en producción, PostgreSQL/MLflow/Airflow; en
  pruebas, dobles en memoria (`tests/conftest.py`). Por eso pytest no necesita MLflow.

**Verificar:** `python -m pytest tests/test_api_contrato.py -v` y <http://localhost:8000/docs>.

---

## Fase 9 · Persistencia (`db.py`)

* Se registra todo: `solicitudes` (crudo + limpio), `predicciones` (con versión del modelo),
  `correcciones`, `observaciones`, `reentrenamientos`.
* **Idempotencia** con SQL:

  ```sql
  INSERT ... ON CONFLICT (tienda_id, familia_id, fecha) DO UPDATE SET ventas = EXCLUDED.ventas
   WHERE observaciones.ventas IS DISTINCT FROM EXCLUDED.ventas RETURNING 1
  ```

  Solo devuelve fila si insertó o si el valor cambió ⇒ `registros_guardados` cuenta exactamente
  "nuevos o modificados".

**Verificar:** enviar dos veces `datos/ejemplos/observacion_valida.json` → 12 y luego 0.

---

## Fase 10 · Airflow (`dags/reentrenamiento.py`)

```
preparar_datos → entrenar_candidato → evaluar_y_decidir → publicar_resultado
       └───────────────┴─────────────────┴────────────────────┴──→ marcar_fallo (ONE_FAILED)
```

* La API dispara el DAG con la API REST de Airflow usando su propio `dag_run_id` = `id`.
* Las tareas usan un **entorno virtual separado** dentro de la imagen de Airflow (evita
  conflictos de dependencias entre Airflow y LightGBM/MLflow).
* El alias solo se mueve en la última tarea ⇒ un fallo intermedio **no afecta** al vigente.

**Verificar:** <http://localhost:8080> → DAG `reentrenamiento_modelo`; `evidencia/airflow_dag_runs.json`.

---

## Fase 11 · Docker Compose

* 8 servicios: `db`, `mlflow`, `bootstrap`, `api`, `db-airflow`, `airflow-init`,
  `airflow-webserver`, `airflow-scheduler`. El de MLflow se llama `mlflow` (requisito).
* `depends_on` con `condition: service_healthy` / `service_completed_successfully` ordena el arranque.
* Volúmenes nombrados ⇒ los datos sobreviven a `docker compose down` (no a `down -v`).
* `bootstrap` es **idempotente**: carga datos solo si faltan, entrena solo si no hay alias.
* Credenciales en `.env` (no versionado); `${VAR:?}` hace que compose falle con un mensaje
  claro si falta una variable.

**Verificar:** `docker compose down -v && docker compose up -d` → `/health` ok en ~45 s.

---

## Fase 12 · Pruebas de operación

| Script | Qué simula | Resultado obtenido |
|---|---|---|
| `scripts/simulador.py` | 28 días: observaciones, 280 solicitudes (25 % con errores), cambio de demanda, 4 reentrenamientos | sin intervención manual; costo −30 % vs sugerir la media; 1 promoción usada en 15 s |
| `scripts/prueba_resiliencia.py` | MLflow caído, reentrenamiento que falla, reinicio | degradado en 12 s, ok en 15 s, modelo intacto, reinicio en 47 s |

**Pregunta:** ¿qué pasaría si la API no guardara una copia local del modelo y MLflow estuviera
caído justo al reiniciar?

---

## Fase 13–14 · Documentación, Git y entrega

* `README.md` (cómo levantarlo, carpeta de datos), `DECISIONES.md` (qué, alternativas, por qué),
  `CLAUDE.md` (contexto para agentes).
* Entrega: commit + `git tag entrega-lab2` + `git push --tags`; en el GES solo va el enlace.

---

## Autoevaluación final (lo que te pueden preguntar)

1. ¿Por qué el estado es `advertencia` y no `corregido` cuando faltan familias?
2. ¿Qué diferencia hay entre `venta_esperada` y `cantidad_sugerida`, y de dónde sale el 1.60 de licores?
3. ¿Cómo garantizas que el modelo nunca vea el futuro?
4. ¿Qué evita que un reentrenamiento malo llegue a producción?
5. ¿Cómo se entera la API de que hay un modelo nuevo sin reiniciarla?
6. ¿Por qué hay dos bases PostgreSQL?
7. Si mañana llega `"ventas": "1.234"`, ¿qué hace el servicio y por qué?
