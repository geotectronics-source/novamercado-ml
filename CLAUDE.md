# CLAUDE.md — contexto para agentes de programación

Servicio de pronóstico diario de ventas (NovaMercado, Laboratorio 2). Lea primero
`README.md` (cómo levantarlo) y `DECISIONES.md` (por qué está hecho así).

## Comandos

```bash
python -m pytest                                   # pruebas (sin MLflow ni PostgreSQL)
docker compose up -d --build                       # producto completo (requiere .env y datos/)
docker compose run --rm --no-deps api python -m pytest -q /app/tests
python scripts/experimento.py datos                # backtest baseline vs LightGBM
python scripts/simulador.py --dias 28              # operación simulada contra la API
python scripts/prueba_resiliencia.py               # caída de MLflow y reinicio
```

## Mapa del código (`src/novamercado/`)

* `contrato.py` — modelos Pydantic del Anexo. **No renombrar ni quitar campos**; solo agregar.
* `calidad/` — defensa del contrato. `parsers.py` (intérpretes generales), `normalizacion.py`
  (nombres de campos), `prediccion.py` / `observaciones.py` (políticas). Cada acción va al
  `Reporte` como `reparar` o `advertir`; rechazar = lanzar `Rechazo` (→ 422).
* `features.py` — **una sola función** para entrenar y servir. Solo datos anteriores a la fecha.
* `modelo.py`, `costos.py`, `entrenamiento.py`, `ciclo.py` — modelo, métrica de costo,
  protocolo de ventanas y criterio de reemplazo.
* `registro.py` — MLflow. `db.py` — PostgreSQL. `cli.py` — bootstrap y pasos del DAG.
* `api/main.py` (HTTP), `api/servicio.py` (lógica), `api/infraestructura.py` (recarga del
  modelo, monitor de salud, cliente de Airflow).

## Invariantes (no romper)

1. Nunca usar el reloj del sistema para validar fechas (fechas simuladas).
2. Las variables solo usan observaciones con fecha < fecha pronosticada.
3. `cantidad_sugerida` es entero ≥ 0; `version_modelo` es texto.
4. Observaciones idempotentes: reenviar lo mismo ⇒ `registros_guardados = 0`.
5. El alias `vigente` solo lo mueve `ciclo.aplicar_decision` cuando se cumple el criterio.
6. La lógica no va en los endpoints; las pruebas no dependen de servicios externos
   (usar los dobles de `tests/conftest.py`).
7. Si cambia una política de calidad: actualizar `DECISIONES.md` §1 y las pruebas.

## Convenciones

Código y documentación en español; nombres en `snake_case`; versiones fijadas en
`requirements/*.txt` y en las imágenes. Datos y credenciales nunca en el repositorio.
