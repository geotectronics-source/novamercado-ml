# Matriz de cumplimiento — Laboratorio 2 (Laboratorio_2_PD_26_c.pdf)

Cada requisito del enunciado, dónde se implementa y cómo se verificó. Las mediciones se
hicieron sobre un **clon limpio del repositorio**, levantado desde cero con la carpeta de
datos copiada tal como se publicó (`datos/datos_lab2/…`), igual que lo hará el evaluador.

Tras integrar el ensamble LightGBM + log-lineal, el producto se volvió a levantar desde cero y
se repitieron la simulación, la prueba de resiliencia, la evidencia y las capturas.

Leyenda: ✅ cumple y está verificado.

## Descripción del producto

| # | Requisito | Estado | Implementación | Evidencia |
|---|---|---|---|---|
| P1 | Pronóstico diario por familia con venta esperada y cantidad sugerida | ✅ | `api/servicio.py::predecir`, `modelo.py` | `evidencia/ejemplos_api.md` |
| P2 | Defensa del contrato: reparar / advertir / rechazar e informar qué hizo y por qué | ✅ | `calidad/` | `tests/test_calidad.py`, `ejemplos_api.md` (E01–E10 + N01–N06) |
| P3 | Registro de predicciones y observaciones con la versión del modelo | ✅ | `db.py` (`predicciones.version_modelo`, `observaciones`) | `evidencia/base_datos.json` |
| P4 | Reentrenamiento con lo registrado, criterio explícito y uso del nuevo modelo sin reinicio | ✅ | `ciclo.py`, `dags/`, `api/infraestructura.py::GestorModelo` | `simulacion.json` (modelo nuevo en uso en ≤ 15 s) |
| P5 | Cantidad sugerida evaluada con `costos.csv` (costo asimétrico por familia) | ✅ | `costos.py` | DECISIONES §4; `simulacion.json` (−30 % vs sugerir la media) |

## Datos

| # | Requisito | Estado | Implementación / evidencia |
|---|---|---|---|
| D1 | Usar tiendas, familias, histórico, feriados (nacional o por ciudad) y costos | ✅ | `db.py::cargar_csv`, `features.py::_calendario_eventos` (`ambito` = nacional o `ciudad`) |
| D2 | Al pronosticar una fecha, solo observaciones de días anteriores | ✅ | `features.py` (todo con `shift ≥ 1`), `db.py::historia_tienda` (`fecha < :fin`); prueba `test_features_no_usan_el_futuro` |
| D3 | Promociones del día desde la solicitud; las observaciones no las traen | ✅ | `servicio.py::predecir`; para entrenar, `db.py::datos_entrenamiento` toma la promoción de la última solicitud del día |
| D4 | No usar el reloj del sistema para validar fechas | ✅ | Ninguna validación usa `date.today()`; las fechas se validan contra apertura, historia y cobertura de feriados |
| D5 | Periodo de evaluación posterior al histórico, cubierto por `feriados.csv` | ✅ | Simulación de 2026-03-01 a 2026-03-28 |

## 1. Servicio con FastAPI

| # | Requisito | Estado | Implementación | Evidencia |
|---|---|---|---|---|
| 1.1 | Cumplir exactamente el contrato del Anexo (puede agregar campos, no omitir ni renombrar) | ✅ | `contrato.py` (`response_model`); campo extra `promocion_supuesta` | `tests/test_api_contrato.py` (19 pruebas) |
| 1.2 | Validación con modelos Pydantic | ✅ | `contrato.py` en modo estricto, después de la limpieza | `calidad/prediccion.py` |
| 1.3 | Limpieza en módulos Python con pruebas, no en los endpoints | ✅ | `calidad/*`; `api/main.py` solo traduce HTTP | `tests/test_parsers.py`, `tests/test_calidad.py` |
| 1.4 | Política explícita y consistente por tipo de problema; reglas generales | ✅ | Intérpretes generales (`parsers.py`, `normalizacion.py`) | DECISIONES §1; casos fuera del catálogo N01–N06 y errores inyectados por el simulador |
| 1.5 | Cada pronóstico indica la versión del modelo | ✅ | `version_modelo` (texto) | `ejemplos_api.md` |
| 1.6 | Pruebas pytest del contrato sin un servidor de MLflow | ✅ | Dobles en memoria (`tests/conftest.py`) | 126 pruebas pasan en local y dentro del contenedor |

## 2. Persistencia

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 2.1 | PostgreSQL propia del producto, en Docker, separada de la de Airflow | ✅ | Servicios `db` y `db-airflow` en `docker-compose.yml` |
| 2.2 | Registrar solicitudes, predicciones, correcciones y observaciones | ✅ | Tablas `solicitudes`, `predicciones`, `correcciones`, `observaciones`; `base_datos.json` |
| 2.3 | Observaciones idempotentes | ✅ | `ON CONFLICT … WHERE … IS DISTINCT FROM`; reenvío ⇒ `registros_guardados = 0` (`ejemplos_api.md`, prueba `test_observaciones_idempotentes`) |
| 2.4 | Conservar la información al detener y volver a levantar | ✅ | Volúmenes nombrados; `down`/`up` y `stop`/`start` verificados (observaciones y modelo vigente se conservan) |

## 3. Modelado y gestión de modelos con MLflow

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 3.1 | Baseline simple y al menos un modelo de ML que lo mejore | ✅ | `baseline_estacional`, `lightgbm_cociente` y `ensamble_lgbm_loglineal` (LightGBM + log-lineal): −20 % de costo en el backtest (DECISIONES §3, `docs/ANALISIS_MODELOS.md`) |
| 3.2 | Métrica de negocio con `costos.csv` además de métricas técnicas | ✅ | `costo_total`, `costo_por_dia_tienda` + MAE, RMSE, WAPE, sesgo (`capturas/01b_mlflow_comparacion_metricas.png`) |
| 3.3 | Cantidad sugerida coherente con los costos | ✅ | Cuantil crítico del *newsvendor* por familia × tipo de tienda (DECISIONES §4) |
| 3.4 | Experimentos, modelos y linaje en MLflow; vigente identificado con alias | ✅ | Run → versión registrada, con etiquetas (`origen`, `fecha_max_datos`, `costo_validacion`, `decision`, `motivo`); alias `vigente` (`capturas/02_…png`, `mlflow.json`) |
| 3.5 | Criterio explícito y automatizado de reemplazo | ✅ | `ciclo.decidir`: sanidad + mejora de costo ≥ 1 % en la misma ventana fuera de muestra |

## 4. Ciclo de reentrenamiento con Airflow

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 4.1 | DAG que usa el histórico y las observaciones de la BD | ✅ | `dags/reentrenamiento.py` → `cli.dag_preparar` → `db.datos_entrenamiento` |
| 4.2 | Se dispara con el endpoint de administración; estado consultable | ✅ | `POST /admin/reentrenar` (202 + id), `GET /admin/reentrenar/{id}`; `capturas/05_…png`, `airflow_dag_runs.json` |
| 4.3 | Usar el modelo promovido sin reinicio en ≤ 2 min | ✅ | Sondeo del alias cada 20 s; medido ≤ 15 s |
| 4.4 | Un reentrenamiento que falla o no supera el criterio no afecta al vigente | ✅ | Falla con MLflow caído ⇒ `fallido` y v2 intacto (`resiliencia.json`); rechazos por criterio (`simulacion.json`) |

## 5. Contenedores y operación

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 5.1 | Todo con `docker compose up` siguiendo el README; el servicio se llama `mlflow` | ✅ | `docker-compose.yml`, README §2 |
| 5.2 | Desde cero: carga los datos y entrena y registra el primer modelo solo | ✅ | Servicio `bootstrap` (logs: carga de 83 052 filas → modelo v1) |
| 5.3 | Al volver a levantarse conserva lo que tiene sin repetir el trabajo | ✅ | Logs del bootstrap: "ya cargados… no se repite", "ya existe el modelo vigente… no se reentrena" |
| 5.4 | Imágenes con versiones fijas | ✅ | `python:3.12.8-slim-bookworm`, `postgres:16.6-alpine`, `ghcr.io/mlflow/mlflow:v2.19.0`, `apache/airflow:2.10.4-python3.12`; dependencias en `requirements/*.txt` |
| 5.5 | Datos y credenciales fuera de las imágenes y del repositorio; `.env.example` | ✅ | `.gitignore`, `.dockerignore`, `.env.example`; en GitHub, `datos/` solo contiene `LEEME.md` |
| 5.6 | Con MLflow caído la API sigue respondiendo; `/health` lo refleja en < 1 min y vuelve a ok en < 2 min | ✅ | 12 s y 3–15 s (`resiliencia.json`) |
| 5.7 | Listo (`/health` ok) en ≤ 10 min sin contar la construcción | ✅ | 43–45 s desde cero; 42–47 s tras `down`/`up`; 30 s tras `stop`/`start` |
| 5.8 | Cada reentrenamiento termina en ≤ 10 min | ✅ | ~20 s con tres candidatos (≈ 3 min el que falla con MLflow caído); `dagrun_timeout` de 10 min |

## 6. Documentación y decisiones

| # | Requisito | Estado | Archivo |
|---|---|---|---|
| 6.1 | Repositorio en GitHub con estructura clara (código, configuración, DAGs, Docker, pruebas) | ✅ | `src/`, `dags/`, `docker/`, `tests/`, `docker-compose.yml` |
| 6.2 | Archivo de contexto para el agente de programación | ✅ | `CLAUDE.md` |
| 6.3 | README con instrucciones desde cero, incluida la carpeta de los datos | ✅ | `README.md` §2, `datos/LEEME.md` |
| 6.4 | DECISIONES con alternativas y justificación: política de datos, información del modelo, cantidad sugerida y criterio de reemplazo | ✅ | `DECISIONES.md` §1, §2, §4 y §5 |

## Contrato del Anexo

| Endpoint / regla | Estado | Verificación |
|---|---|---|
| Puerto 8000; fechas AAAA-MM-DD; rechazo = 422 con `detail` | ✅ | `test_rechazo_responde_422_con_detail`, `test_json_invalido_responde_422` |
| `POST /v1/prediccion`: campos, `calidad.estado` (ok / corregido / advertencia), `ok` sin observaciones, `version_modelo` texto, `cantidad_sugerida` entera ≥ 0, misma fecha más de una vez | ✅ | `test_prediccion_*`, `test_misma_fecha_puede_pedirse_dos_veces` |
| `POST /v1/observaciones`: `registros_guardados` = nuevos o modificados; reenvío idéntico = 0 | ✅ | `test_observaciones_idempotentes`, `test_observacion_modificada_cuenta_y_advierte` |
| `POST /admin/reentrenar`: 202 con `id` (texto), o 503 si no se puede iniciar | ✅ | `test_reentrenar_flujo`, `test_reentrenar_sin_airflow_responde_503` |
| `GET /admin/reentrenar/{id}`: en_curso / exitoso / fallido; promovido, versión y motivo al terminar; 404 si no existe | ✅ | `test_reentrenar_flujo`, `test_reentrenamiento_fallido_no_cambia_modelo`, `test_id_desconocido_404` |
| `GET /modelo`: nombre, alias y versión como texto | ✅ | `test_modelo_vigente` |
| `GET /health`: ok / degradado + motivo; 503 sin modelo | ✅ | `test_health_ok_y_degradado`, `test_sin_modelo_responde_503` |

## Entregables

| Entregable | Estado |
|---|---|
| Código de la API, el modelo, los DAGs, la configuración de Docker y las pruebas | ✅ |
| Tag `entrega-lab2` | ✅ (debe apuntar al último commit antes de la fecha límite) |
| README.md y DECISIONES.md | ✅ |
| Evidencia: experimentos y versiones en MLflow, ejecuciones del DAG y respuestas de la API a solicitudes válidas y defectuosas | ✅ `evidencia/` (JSON + capturas) |
| Repositorio accesible al equipo docente | ✅ público |
