# NovaMercado — Servicio de ML en producción (Laboratorio 2)

Servicio de **pronóstico diario de ventas por familia de producto** para las 10 tiendas de
NovaMercado. Recibe solicitudes de pronóstico (aunque lleguen con datos en mal estado),
responde con la **venta esperada** y la **cantidad sugerida**, registra lo que predice y lo que
realmente ocurre, y **se reentrena** con esa información mediante Airflow + MLflow, todo con un
solo `docker compose up`.

| Componente | Tecnología | Puerto (host) |
|---|---|---|
| API (contrato del Anexo) | FastAPI + Pydantic | `8000` |
| BD del producto | PostgreSQL 16 (`db`) | `5433` |
| Seguimiento y registro de modelos | MLflow 2.19 (`mlflow`) | `5000` |
| Orquestación del reentrenamiento | Airflow 2.10 (`airflow-*`) + su propia PostgreSQL (`db-airflow`) | `8080` |
| Carga inicial y primer modelo | servicio de una sola vez (`bootstrap`) | — |

```
tiendas ─▶ api ──SQL──▶ db (PostgreSQL del producto)
            │  ▲                ▲
  dispara   │  │ carga alias    │ histórico + observaciones
  el DAG    ▼  │ @vigente       │
         airflow ──registra──▶ mlflow
```

## 1. Requisitos

* Docker Desktop (o Docker Engine) con **Docker Compose v2**; ~6 GB de RAM libres.
* Puertos `8000`, `5000`, `5433` y `8080` libres (los de MLflow y Airflow se pueden cambiar
  en `.env`: `MLFLOW_PUERTO_HOST`, `AIRFLOW_PUERTO_HOST`).

## 2. Levantar el producto desde cero

```bash
git clone --branch entrega-lab2 https://github.com/geotectronics-source/novamercado-ml.git
cd novamercado-ml
cp .env.example .env            # ajuste las claves si lo desea
```

**Coloque los archivos publicados en la carpeta [`datos/`](datos/LEEME.md)** (en la raíz del repositorio):

```
datos/tiendas.csv  datos/familias.csv  datos/costos.csv  datos/feriados.csv  datos/historico_ventas.csv
```

(También funciona si copia la carpeta descomprimida completa, p. ej. `datos/datos_lab2/…`: el
bootstrap busca la única subcarpeta que contenga `historico_ventas.csv`.)

```bash
docker compose up -d --build
```

Al levantarse desde cero, el servicio `bootstrap` crea el esquema, carga los CSV en PostgreSQL,
entrena el *baseline* y el modelo LightGBM, los registra en MLflow y promueve el mejor con el
alias `vigente`. La API lo detecta y lo carga sola. En nuestras pruebas, el producto queda listo
en **~45 s** sin contar la construcción de imágenes.

```bash
curl http://localhost:8000/health      # {"estado":"ok", ...} cuando está listo (503 mientras no hay modelo)
```

Al volver a levantarlo (`docker compose down` + `docker compose up -d`, **sin** `-v`) conserva
datos, observaciones y modelos, y el bootstrap no repite la carga ni el entrenamiento.
Para empezar de cero: `docker compose down -v`.

## 3. Uso

Documentación interactiva: <http://localhost:8000/docs>. MLflow: <http://localhost:5000>.
Airflow: <http://localhost:8080> (usuario/clave de `.env`).

```bash
# Pronóstico
curl -X POST localhost:8000/v1/prediccion -H "Content-Type: application/json" \
  -d '{"tienda_id": 5, "fecha": "2026-03-02", "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]}'

# Ventas reales del día (idempotente: reenviar lo mismo devuelve registros_guardados = 0)
curl -X POST localhost:8000/v1/observaciones -H "Content-Type: application/json" \
  -d '{"tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "abarrotes", "ventas": 994}]}'

# Reentrenamiento (202 con id) y su estado
curl -X POST localhost:8000/admin/reentrenar
curl localhost:8000/admin/reentrenar/<id>

curl localhost:8000/modelo
```

## 4. Pruebas

Las pruebas del contrato **no necesitan MLflow ni PostgreSQL** (usan dobles en memoria):

```bash
docker compose run --rm --no-deps api python -m pytest -q /app/tests
```

o localmente: `pip install -r requirements/app.txt && python -m pytest`.

Pruebas de operación contra el producto levantado (generan archivos en `evidencia/`):

```bash
python scripts/simulador.py --dias 28          # operación diaria simulada + reentrenamientos
python scripts/prueba_resiliencia.py           # caída de MLflow, reentrenamiento fallido, reinicio
python scripts/generar_evidencia.py            # ejemplos de API, MLflow, ejecuciones del DAG, BD
```

## 5. Estructura del repositorio

```
├── src/novamercado/
│   ├── calidad/          defensa del contrato: normalización, intérpretes, políticas
│   ├── api/              FastAPI (main), lógica de servicio, infraestructura (modelo, monitor, Airflow)
│   ├── contrato.py       modelos Pydantic del Anexo
│   ├── features.py       variables (MISMA función para entrenar y servir)
│   ├── modelo.py         baseline y LightGBM
│   ├── costos.py         métrica de negocio y cantidad sugerida (newsvendor)
│   ├── entrenamiento.py  protocolo de ventanas entrenamiento/calibración/validación
│   ├── ciclo.py          entrenar → registrar → decidir → promover (criterio de reemplazo)
│   ├── registro.py       MLflow (runs, Model Registry, alias)
│   ├── db.py             PostgreSQL (esquema, registro idempotente)
│   └── cli.py            bootstrap y pasos del DAG
├── dags/reentrenamiento.py
├── docker/               Dockerfiles (app y Airflow)
├── docker-compose.yml  .env.example
├── tests/                pytest (contrato, calidad, modelo)
├── scripts/              experimento, simulador, resiliencia, evidencia
├── evidencia/            resultados de las pruebas de operación
├── docs/                 plan de trabajo y guía paso a paso
├── datos/                ← aquí van los archivos publicados (no se versionan)
├── DECISIONES.md  CLAUDE.md
```

## 6. Evidencia de funcionamiento

| Archivo | Contenido |
|---|---|
| [`evidencia/ejemplos_api.md`](evidencia/ejemplos_api.md) | Respuestas a solicitudes válidas, E01–E10 y casos fuera del catálogo |
| [`evidencia/mlflow.json`](evidencia/mlflow.json) | Experimentos, runs con métricas, versiones del modelo, decisión y alias |
| [`evidencia/airflow_dag_runs.json`](evidencia/airflow_dag_runs.json) | Ejecuciones del DAG y estado de cada tarea |
| [`evidencia/simulacion.json`](evidencia/simulacion.json) | 28 días simulados: costo, estados de calidad, reentrenamientos |
| [`evidencia/resiliencia.json`](evidencia/resiliencia.json) | Caída de MLflow, reentrenamiento fallido y reinicio |
| [`evidencia/base_datos.json`](evidencia/base_datos.json) | Conteos de solicitudes, predicciones, correcciones y observaciones |

Las decisiones técnicas y de producto están en [`DECISIONES.md`](DECISIONES.md).
