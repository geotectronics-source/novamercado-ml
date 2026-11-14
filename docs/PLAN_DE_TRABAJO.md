# Plan de trabajo — Laboratorio 2: Servicio de ML en producción (NovaMercado)

> Rol: desarrollador de productos de IA + científico de datos.
> Objetivo académico: que cada fase se entienda, se pueda reproducir y se pueda justificar.

## 0. Lectura del enunciado → qué se evalúa realmente

El enunciado lo dice explícitamente: **la complejidad no está en el modelo sino en operar el
servicio**. Por eso el plan dedica la mayor parte del esfuerzo a:

1. Un **contrato** (Anexo del PDF) que se cumpla al pie de la letra.
2. Una **defensa del contrato** con reglas *generales* (no `if` por cada ejemplo del catálogo).
3. **Persistencia** idempotente en PostgreSQL.
4. Un **ciclo de reentrenamiento** con Airflow + MLflow que promueva modelos sin reiniciar la API.
5. **Operación**: todo con `docker compose up`, tolerante a caídas de MLflow y a reinicios.

El modelo debe ser bueno (se evalúa el costo de las sugerencias), pero simple y robusto.

## 1. Arquitectura objetivo

```
                ┌──────────────┐  POST /v1/prediccion, /v1/observaciones, /admin/...
 tiendas ──────▶│  api (8000)  │──────────────┐
                │  FastAPI     │              │ SQL
                └──┬───────┬───┘              ▼
     carga modelo  │       │ dispara DAG   ┌───────────┐
     (alias        │       │ (REST API)    │ db-app    │ PostgreSQL del producto
      @vigente)    ▼       ▼               └───────────┘
             ┌─────────┐ ┌──────────────────┐   ▲
             │ mlflow  │◀│ airflow (DAG      │───┘ lee histórico + observaciones
             │ (5000)  │ │ reentrenamiento)  │
             └─────────┘ └──────────────────┘
                  ▲            │ usa su propia BD: db-airflow
                  │
            ┌───────────┐  servicio de una sola vez: crea esquema, carga CSV,
            │ bootstrap │  entrena y registra el PRIMER modelo si no existe.
            └───────────┘
```

## 2. Fases (cada una con: qué, por qué, cómo verificar)

| # | Fase | Entregable | Verificación |
|---|------|-----------|--------------|
| 1 | **Entorno y estructura del repo** | carpetas `src/`, `dags/`, `docker/`, `tests/`, `docs/` | `tree`, `git status` |
| 2 | **Análisis exploratorio (EDA)** | `notebooks/` o script `scripts/eda.py` + hallazgos | tendencias, estacionalidad, feriados |
| 3 | **Ingeniería de variables** | `novamercado/features.py` (MISMA función para entrenar y servir) | prueba de que no hay fuga de información (solo datos < fecha) |
| 4 | **Modelos**: baseline + LightGBM | `novamercado/modelo.py`, `entrenamiento.py` | métricas técnicas (MAE, WAPE, sesgo) y **costo** |
| 5 | **Cantidad sugerida** (problema del *newsvendor*) | multiplicadores por familia/tipo de tienda calibrados con costos | costo en validación vs. sugerir la media |
| 6 | **MLflow**: experimentos, registro, alias `vigente`, criterio de reemplazo | `novamercado/registro.py` | UI de MLflow con runs y versiones |
| 7 | **Defensa del contrato** (limpieza) | `novamercado/calidad/*.py` con reglas generales | `pytest` con los 10 ejemplos + casos nuevos |
| 8 | **API FastAPI** con modelos Pydantic | `novamercado/api/` | `pytest` con `TestClient` (sin MLflow) |
| 9 | **Persistencia** PostgreSQL (solicitudes, predicciones, correcciones, observaciones idempotentes) | `novamercado/db.py`, `sql/esquema.sql` | reenviar observación ⇒ `registros_guardados = 0` |
| 10 | **Airflow**: DAG de reentrenamiento + endpoints admin | `dags/reentrenamiento.py` | `POST /admin/reentrenar` → `GET /admin/reentrenar/{id}` |
| 11 | **Docker Compose** (api, db-app, mlflow, airflow, db-airflow, bootstrap) | `docker-compose.yml`, Dockerfiles, `.env.example` | `docker compose up` desde cero → `/health` ok < 10 min |
| 12 | **Pruebas de operación**: caída de MLflow, reinicio, recarga en caliente | `scripts/simulador.py` | health degradado < 1 min y ok < 2 min |
| 13 | **Documentación**: README, DECISIONES, CLAUDE.md, evidencia | `README.md`, `DECISIONES.md`, `evidencia/` | revisión final contra el enunciado |
| 14 | **Git + GitHub + tag `entrega-lab2`** | repositorio | `git tag`, enlace |

## 3. Decisiones clave a tomar (y que se documentan en DECISIONES.md)

1. **Política por tipo de problema** (reparar / advertir / rechazar) con reglas generales:
   normalización de nombres de campos y familias, parser de números y fechas, deduplicación.
2. **Información que usa el modelo al predecir**: calendario, feriados por ciudad,
   promociones de la solicitud y rezagos calculados SOLO con observaciones anteriores a la fecha.
3. **Cantidad sugerida**: cuantil crítico del *newsvendor* `c_faltante / (c_faltante + c_sobrante)`.
4. **Criterio de reemplazo**: el candidato reemplaza al vigente si su costo en una ventana de
   validación fuera de muestra es al menos 1 % menor y pasa controles de sanidad.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Cambio de comportamiento de la demanda | variable objetivo relativa al nivel reciente + reentrenamiento con observaciones |
| Conflictos de dependencias Airflow ↔ ML | entorno virtual separado dentro de la imagen de Airflow |
| MLflow caído | la API mantiene el modelo en memoria y en caché local en disco |
| Reinicio del producto | volúmenes nombrados; el bootstrap detecta lo existente y no repite trabajo |
| Fechas simuladas | nunca se usa el reloj del sistema para validar fechas |
