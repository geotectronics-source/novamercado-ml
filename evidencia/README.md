# Evidencia de funcionamiento

Generada sobre un clon limpio del repositorio, levantado desde cero con `docker compose up`.

## Capturas (`capturas/`)

| Archivo | Muestra |
|---|---|
| `01_mlflow_experimento_runs.png` | Experimento `novamercado_pronostico`: runs del bootstrap y de cada reentrenamiento (baseline y LightGBM) |
| `01b_mlflow_comparacion_metricas.png` | Comparación de los runs: parámetros y métricas (`costo_total`, MAE, RMSE, WAPE…) |
| `02_mlflow_modelo_versiones_alias.png` | Model Registry: 5 versiones con origen, costo, decisión y motivo; alias `@vigente` en la v2 |
| `03_mlflow_version_vigente.png` | Detalle de la versión vigente y su run de origen (linaje) |
| `04_mlflow_run_vigente_metricas.png` | Run que produjo el modelo vigente: parámetros, métricas y artefactos |
| `05_airflow_dag_ejecuciones.png` | DAG `reentrenamiento_modelo`: 4 ejecuciones exitosas y 1 fallida (MLflow caído) |
| `06_airflow_dag_grafo.png` | Grafo de tareas del DAG |
| `07_airflow_lista_ejecuciones.png` | Lista de ejecuciones del DAG |
| `08_api_docs.png` | Documentación OpenAPI de la API |

## Archivos

| Archivo | Contenido | Generado con |
|---|---|---|
| `ejemplos_api.md` | Respuestas a solicitudes válidas, E01–E10 y casos fuera del catálogo | `scripts/generar_evidencia.py` |
| `mlflow.json` | Experimentos, runs con métricas, versiones con etiquetas y alias | `scripts/generar_evidencia.py` |
| `airflow_dag_runs.json` | Ejecuciones del DAG y estado de cada tarea | `scripts/generar_evidencia.py` |
| `base_datos.json` | Conteos de solicitudes por estado, predicciones, correcciones y observaciones | `scripts/generar_evidencia.py` |
| `simulacion.json` | 28 días de operación simulada: costo, calidad y reentrenamientos | `scripts/simulador.py` |
| `resiliencia.json` | Caída de MLflow, reentrenamiento fallido y reinicio | `scripts/prueba_resiliencia.py` |
