# Auditoría técnica independiente — Laboratorio 2 MLOps

**Fecha de auditoría:** 2026-11-14  
**Fuente de verdad:** `Laboratorio_2_PD_26_c.pdf`  
**Repositorio:** `https://github.com/geotectronics-source/novamercado-ml`  
**Tag auditado:** `entrega-lab2`  
**Objeto del tag:** `7ec7309d607485d0ad5a3bb0027e878c10f6d8c6`  
**Commit auditado:** `90a805f3e3c8d8760a1b224679a0b3cf6cd3b4f7`

## 1. Resumen ejecutivo

**Veredicto global: CUMPLE CON OBSERVACIONES.**

No se encontró un incumplimiento funcional crítico. La API, persistencia, MLflow, Airflow, reentrenamiento, recarga dinámica del modelo y operación degradada funcionaron en pruebas reales. El cliente independiente de caja negra pasó **41/41 casos**, incluyendo E01–E10, más de diez casos nuevos y concurrencia. Las **128 pruebas pytest** pasaron con MLflow detenido.

Las tres brechas o riesgos principales son:

1. **Riesgo de contrato estricto en `/health`.** Cuando no hay modelo, la implementación devuelve `estado="no_disponible"`, valor que no aparece entre los estados `ok/degradado` nombrados en el Anexo. El HTTP 503 es correcto, pero un evaluador que valide el enum literalmente podría rechazar el cuerpo.
2. **El OpenAPI no describe los cuerpos de entrada.** Los endpoints reciben `Request` crudo y luego aplican Pydantic internamente. La validación real funciona, pero un evaluador basado en `/openapi.json` no encontrará los esquemas de `POST /v1/prediccion` y `/v1/observaciones`.
3. **Reproducibilidad y robustez mejorables.** MLflow registró modelos sin `signature` ni `input_example`; además, `setuptools>=68` y los paquetes `apt` quedan sin versión exacta. El camino de fallo del reentrenamiento con MLflow detenido tardó 184.4 segundos, todavía bajo diez minutos, pero con reintentos innecesariamente largos.

No se pudo verificar si el tag fue creado antes de la fecha límite porque el PDF no especifica una fecha u hora de entrega.

## 2. Alcance y metodología

- Se extrajo y revisó el texto completo del PDF de siete páginas.
- Se clonó el repositorio remoto en una carpeta temporal nueva y se hizo checkout del tag `entrega-lab2`.
- Se copiaron los datos publicados dentro de `datos/datos_lab2` del clon temporal.
- Se creó un `.env` temporal desde `.env.example` con `AIRFLOW_PUERTO_HOST=8088`.
- Toda la operación Docker utilizó el nombre de proyecto `auditoria`.
- Se levantó el sistema desde volúmenes vacíos y se midió su arranque.
- Se escribió y ejecutó un cliente propio de caja negra.
- Se probaron persistencia, idempotencia, concurrencia, reentrenamientos seguidos, caída de MLflow, recuperación y recarga dinámica de una versión promovida.
- Al finalizar se ejecutó `docker compose -p auditoria down -v` y se confirmó que no quedaron contenedores ni volúmenes de la auditoría.
- No se modificó ningún archivo rastreado del repositorio: `git diff --exit-code` devolvió 0.

## 3. Matriz de cumplimiento

| # | Requisito | Veredicto | Evidencia |
|---:|---|---|---|
| A1 | API en puerto 8000 | CUMPLE | `docker-compose.yml:123`; respuestas reales en `http://localhost:8000`. |
| A2 | Fechas `AAAA-MM-DD`; rechazo 422 con `detail` | CUMPLE | Fechas ISO aceptadas; fechas imposibles, cuerpos inválidos y ambigüedades no reparables devolvieron 422 con `detail`. Manejo en `src/novamercado/api/main.py:55-75`. |
| A3 | Contrato exacto de `/v1/prediccion` | CUMPLE | Tipos en `src/novamercado/contrato.py:21-44`; caja negra verificó enteros no negativos, versión textual y enums. |
| A4 | `advertir` implica `advertencia`; `ok` sin observaciones | CUMPLE | Agregación en `src/novamercado/calidad/reporte.py:55-65`; comprobado en E01–E10 y casos nuevos. |
| A5 | Misma fecha solicitada dos veces | CUMPLE | Dos solicitudes idénticas consecutivas devolvieron 200 y pronósticos válidos. |
| A6 | Observaciones nuevas o modificadas; reenvío idéntico = 0 | CUMPLE | `ON CONFLICT` en `src/novamercado/db.py:220-249`. En 20 reenvíos concurrentes idénticos, la suma de `registros_guardados` fue 1; los otros 19 devolvieron 0. |
| A7 | `POST /admin/reentrenar` sin cuerpo: 202 o 503 | CUMPLE | POST real devolvió 202 e identificador textual. Endpoint en `src/novamercado/api/main.py:90`. |
| A8 | Consulta del estado y campos terminales | CUMPLE | Se observaron `en_curso`, `exitoso` y `fallido`; los campos terminales aparecieron al terminar; id inexistente devolvió 404. |
| A9 | Versión terminal igual a la vigente | CUMPLE | Reentrenamiento no promovido terminó con versión 1; promovido con versión 3; fallido conservó e informó versión 3. |
| A10 | `/modelo`: nombre, alias y versión textual | CUMPLE | Respuesta real válida; versión cambió de `"1"` a `"3"`. |
| A11 | `/health`: ok/degradado; 503 sin modelo | PARCIAL | La operación `ok/degradado` funciona, pero `contrato.py:100` agrega `no_disponible` y `servicio.py:191` lo usa con 503. |
| B1 | Políticas E01–E10 | CUMPLE | Los diez archivos publicados fueron ejercitados por caja negra y coincidieron con la política documentada. |
| B2 | Al menos diez errores nuevos | CUMPLE | Se probaron 24 variantes nuevas: raíz lista/null, campos ausentes/desconocidos, tienda booleana o inexistente, fechas ambiguas/imposibles, familias aproximadas/desconocidas, promociones negativas/fraccionarias, duplicados y observaciones mal tipadas. |
| B3 | Política general sin inventar información | CUMPLE | Política en `DECISIONES.md:29-82`; los supuestos quedan marcados mediante `promocion_supuesta`. |
| B4 | Limpieza modular y probada | CUMPLE | `calidad/prediccion.py:64+` y `calidad/observaciones.py:55+`; los endpoints solo orquestan. |
| B5 | Validación con Pydantic | CUMPLE | Modelos estrictos en `contrato.py:21-44`. Observación: los esquemas no aparecen como request bodies en OpenAPI. |
| C1 | Solo datos anteriores a la fecha pronosticada | CUMPLE | Consulta `fecha < :fin` en `db.py:152-162`; `shift(1)` en `features.py:125`. |
| C2 | Promociones proceden de la solicitud | CUMPLE | Se persisten por predicción y se recuperan para entrenamiento en `db.py:164-181`. |
| C3 | No usar reloj del sistema para validar fechas | CUMPLE | Las decisiones se basan en catálogos, cobertura e histórico; existe prueba específica. No se encontró comparación funcional contra `today()`/`now()` en calidad. |
| C4 | Feriados nacionales o por ciudad | CUMPLE | Filtro nacional o ciudad en `features.py:56-80`. |
| D1 | PostgreSQL propia, separada de Airflow | CUMPLE | Servicios y volúmenes distintos en `docker-compose.yml:51-57`, `135-142` y `188-189`; bases reales `novamercado` y `airflow`. |
| D2 | Registrar solicitudes, predicciones, correcciones y observaciones | CUMPLE | Esquema en `db.py:25-66`. Conteos finales de prueba: 1,479 solicitudes, 8,892 predicciones, 49 correcciones y 8,412 observaciones. |
| D3 | Predicción registra versión del modelo | CUMPLE | Campo e inserción en `db.py:212-214`. |
| D4 | Idempotencia | CUMPLE | Verificación secuencial y concurrente; `ON CONFLICT` en `db.py:243-248`. |
| D5 | Persistencia después de down/up | CUMPLE | Antes y después: 78 solicitudes, 480 predicciones, 42 correcciones, 19 observaciones, un reentrenamiento y 83,052 filas históricas, sin cambios. |
| E1 | Baseline más un ML que lo mejore | CUMPLE | Baseline: costo 112,022.6; LightGBM: 89,947; ensamble: 89,114; mejora aproximada de 20.4%. `entrenamiento.py:72-108`. |
| E2 | Métricas técnicas y de negocio con costos | CUMPLE | MLflow registró MAE, RMSE, WAPE y costo. Lógica de costo/calibración en `costos.py:1-79`. |
| E3 | Cantidad sugerida coherente con costos | CUMPLE | Multiplicadores calibrados minimizando costo fuera de muestra; cantidades siempre enteras y no negativas. |
| E4 | Linaje en MLflow | CUMPLE CON OBSERVACIÓN | Run promovido `cf80bc99dc444555b330f51ba3905612`: 91,452 filas, 8,412 observaciones de BD, fecha máxima, tipo de modelo y métricas. Falta `signature` e `input_example`. |
| E5 | Alias del modelo vigente | CUMPLE | Versión 3 READY con alias `vigente`; asignación en `registro.py:88`. |
| E6 | Reemplazo explícito y automatizado | CUMPLE | Umbral del 1% en `ciclo.py:82-128`; se observó un candidato rechazado y otro promovido automáticamente. |
| F1 | DAG usa histórico y observaciones de BD | CUMPLE | `dags/reentrenamiento.py:23-49`; el linaje real registró ambos orígenes. |
| F2 | DAG disparado por endpoint y estado consultable | CUMPLE | Seis ejecuciones creadas por la API; estados consultables por id. |
| F3 | Modelo promovido usado sin reinicio en ≤2 min | CUMPLE | Promoción a v3; la API pasó de v1 a v3 en 15.2 segundos. Recarga configurada cada 20 segundos en `config.py:51`. |
| F4 | Fallo o falta de mejora no altera vigente | CUMPLE | Candidato sin mejora dejó v1; caída de MLflow produjo `fallido` y conservó v3. |
| F5 | Cada reentrenamiento ≤10 min | CUMPLE | Normal 21.8 s; promoción 21.0 s; fallo 184.4 s. DAG limita una ejecución activa y tareas a ocho minutos en `reentrenamiento.py:29-31`. |
| G1 | Todo con Docker Compose; servicio `mlflow` | CUMPLE | Arranque completo desde cero; servicio exacto `mlflow` en `docker-compose.yml:68`. |
| G2 | Carga y primer entrenamiento automáticos | CUMPLE | Se cargaron 10 tiendas, 12 familias, 12 costos, 61 feriados y 83,052 ventas; se entrenaron tres candidatos y se promovió v1 automáticamente. |
| G3 | Reinicio no repite carga ni entrenamiento | CUMPLE | Logs: `Datos publicados ya cargados` y `Ya existe el modelo vigente v1; no se reentrena`. |
| G4 | Imágenes con versiones fijas | CUMPLE CON OBSERVACIÓN | PostgreSQL 16.6, MLflow 2.19.0, Python 3.12.8 y Airflow 2.10.4. No se usan digests y los paquetes `apt` no tienen versión exacta. |
| G5 | Datos y credenciales fuera de imagen/repo; `.env.example` | CUMPLE | Solo `datos/LEEME.md` está versionado. `.dockerignore` excluye `.env` y datos; inspección de `/app` no encontró datos publicados ni credenciales. |
| G6 | API funciona con MLflow caído y salud se recupera | CUMPLE | Degradado en 12.3 s, predicción 200 con v1, recuperación a `ok` en 17.3 s. |
| G7 | Listo en ≤10 min | CUMPLE | Desde cero: `/health` ok en 42.5 s. Reinicio persistente: 43.2 s. |
| H1 | Pytest sin depender de MLflow | CUMPLE | Con MLflow detenido: 128 pruebas pasaron. Solo hubo dos avisos de permiso de `.pytest_cache`. |
| I1 | Estructura clara e instrucciones para agentes | CUMPLE | Existe `CLAUDE.md`. No existe `AGENTS.md`, pero el primero satisface la alternativa del enunciado. |
| I2 | README explica carpeta de datos y arranque | CUMPLE | `README.md:31-64`. |
| I3 | DECISIONES incluye las cuatro decisiones exigidas | CUMPLE | Política línea 7; información línea 86; cantidad línea 153; reemplazo línea 188; incluye alternativas y justificaciones. |
| I4 | Evidencia de MLflow, DAG y API | CUMPLE | JSON, Markdown y capturas versionadas, además reproducidas independientemente. |
| I5 | Tag y repositorio accesibles | CUMPLE | Clon remoto y checkout del tag exitosos. |
| I6 | Tag creado antes del límite | NO VERIFICADO | El tag existe, pero el PDF no contiene una fecha límite para comparar. |
| J1 | Problemas fuera del catálogo | CUMPLE | 24 casos adversariales nuevos sin excepciones 500. |
| J2 | Concurrencia de solicitudes | CUMPLE | 20 predicciones paralelas: 20 respuestas 200; observaciones paralelas conservaron idempotencia. |
| J3 | Reentrenamientos seguidos | CUMPLE CON OBSERVACIÓN | Tres ids distintos terminaron correctamente; fueron serializados en aproximadamente 20.2, 41.5 y 60.0 segundos. Una cola muy grande podría elevar la latencia desde la solicitud. |
| J4 | Interrupción de MLflow y reinicios | CUMPLE | Probados stop/start de MLflow, fallo del DAG, reinicio completo y persistencia. |
| J5 | Portabilidad Linux | CUMPLE | `git ls-files --eol` mostró LF; los contenedores Linux construyeron y operaron. |
| J6 | Dependencias fijadas | PARCIAL | Dependencias de ejecución usan `==`; `pyproject.toml:2` usa `setuptools>=68`, y `apt` no fija versiones. |
| J7 | Posibles errores lógicos | CUMPLE CON OBSERVACIONES | No surgieron fallos funcionales en la cobertura ejecutada; quedan los riesgos de contrato, OpenAPI y cola descritos abajo. |

## 4. Hallazgos ordenados por severidad

No se observaron hallazgos **CRÍTICOS** ni **ALTOS** reproducibles.

### MEDIO — M01: estado adicional en `/health`

**Descripción:** el modelo Pydantic admite `ok`, `degradado` y `no_disponible`; este último se devuelve con HTTP 503 cuando no existe un modelo cargado. El Anexo nombra solamente `ok/degradado`.

**Cómo reproducirlo:** arrancar la API sin un modelo cargado y consultar `GET /health`, o revisar `src/novamercado/contrato.py:100` y `src/novamercado/api/servicio.py:191`.

**Impacto:** un evaluador que valide literalmente el enum puede marcar el cuerpo como incompatible, aunque el código HTTP 503 sea correcto.

**Corrección sugerida:** usar `estado="degradado"` también para el 503, o confirmar/documentar explícitamente que `no_disponible` forma parte del contrato permitido.

### MEDIO — M02: OpenAPI sin esquemas de entrada

**Descripción:** los endpoints reciben `Request` directamente. Pydantic se aplica después de la limpieza, pero FastAPI no publica el esquema de los request bodies.

**Cómo reproducirlo:** consultar `/openapi.json` o `/docs`; `POST /v1/prediccion` y `/v1/observaciones` no muestran un modelo de entrada tipado. Código en `src/novamercado/api/main.py:79-87`.

**Impacto:** clientes generados o evaluadores que inspeccionen OpenAPI no podrán comprobar ni construir automáticamente el contrato.

**Corrección sugerida:** declarar modelos de entrada o personalizar `openapi_extra/requestBody`, manteniendo la capa previa de normalización necesaria para las entradas reparables.

### MEDIO — M03: artefactos MLflow sin firma

**Descripción:** durante el bootstrap, MLflow emitió para los tres modelos: `Model logged without a signature and input example`.

**Cómo reproducirlo:** levantar desde volúmenes vacíos y revisar los logs del bootstrap. El registro llama `mlflow.pyfunc.log_model` en `src/novamercado/registro.py:73`.

**Impacto:** el linaje existe, pero MLflow no puede validar formalmente el esquema de entrada y salida. Aumenta el riesgo de incompatibilidad silenciosa.

**Corrección sugerida:** registrar `signature`, `input_example` y el ambiente exacto del modelo.

### MEDIO — M04: fallo de MLflow tarda más de tres minutos

**Descripción:** un reentrenamiento iniciado con MLflow detenido tardó 184.4 segundos en terminar como fallido. La tarea de entrenamiento consumió unos 91 segundos y el manejador de fallo otros 87 segundos.

**Cómo reproducirlo:** detener MLflow con `docker compose -p auditoria stop mlflow`, disparar `/admin/reentrenar` y consultar el estado hasta llegar a `fallido`.

**Impacto:** cumple el límite de diez minutos, pero una red más lenta o varios reentrenamientos en cola reducen el margen frente al evaluador.

**Corrección sugerida:** prevalidar disponibilidad de MLflow, reducir timeouts/reintentos y permitir que el manejador de fallo registre la versión vigente desde la BD o caché sin volver a esperar a MLflow.

### BAJO — B01: construcción no totalmente reproducible

**Descripción:** las dependencias Python de ejecución están fijadas, pero `setuptools>=68`, paquetes `apt` sin versión y tags Docker sin digest permiten variación futura.

**Cómo reproducirlo:** revisar `pyproject.toml:2`, `docker/app.Dockerfile:5-6` y `docker/airflow.Dockerfile:6-7`.

**Impacto:** una reconstrucción futura podría generar imágenes diferentes aunque el tag Git sea el mismo.

**Corrección sugerida:** fijar `setuptools`, usar imágenes por digest y, si el entorno lo requiere, snapshots/versiones de paquetes del sistema.

### BAJO — B02: avisos de permisos en pytest

**Descripción:** las 128 pruebas pasaron, pero pytest no pudo escribir `/app/.pytest_cache`.

**Impacto:** no afecta la funcionalidad, pero ensucia la salida y puede ocultar otras advertencias.

**Corrección sugerida:** desactivar el plugin de caché o configurar `cache_dir` en una ubicación escribible.

### BAJO — B03: límite temporal del tag no verificable

**Descripción:** el tag existe y tiene fecha, pero el enunciado proporcionado no indica la fecha límite.

**Impacto:** no es posible emitir un `CUMPLE` respaldado para ese requisito administrativo.

**Corrección sugerida:** conservar evidencia del aula o sistema de entrega con la hora límite y la hora de publicación del tag.

## 5. Mediciones independientes

| Medición | Resultado |
|---|---:|
| Primera respuesta `/health` desde arranque limpio | HTTP 503 en 18.3 s |
| `/health` degradado durante bootstrap | 26.4 s |
| `/health` ok desde arranque limpio | **42.5 s** |
| `/health` ok tras down/up conservando volúmenes | **43.2 s** |
| MLflow detenido → `/health` degradado | **12.3 s** |
| Predicción con MLflow detenido | HTTP 200, modelo v1 |
| MLflow iniciado → `/health` ok | **17.3 s** |
| Reentrenamiento sin mejora | **21.8 s**, exitoso, no promovido, vigente v1 |
| Reentrenamiento con cambio de demanda | **21.0 s**, exitoso, promovió v3 |
| Promoción terminal → API usando v3 | **15.2 s** |
| Reentrenamiento con MLflow caído | **184.4 s**, fallido, vigente v3 intacto |
| Tres reentrenamientos seguidos | 20.2 s / 41.5 s / 60.0 s |
| Suite con MLflow detenido | **128 passed** |
| Cliente independiente de caja negra | **41/41 passed** |
| Predicciones concurrentes | 20/20 HTTP 200 |
| Observaciones idénticas concurrentes | 20/20 HTTP 200; suma guardada = 1 |

El cambio de demanda empleado para comprobar una promoción real comprendió 70 días, 10 tiendas y 12 familias: 1,400 solicitudes sin fallo. El candidato v3 redujo el costo de validación de 443,682 a 214,455, una mejora del 51.7%.

## 6. Respuestas y resultados relevantes

### Primer reentrenamiento, sin mejora

- HTTP inicial: 202.
- Estado terminal: `exitoso`.
- `promovido`: `false`.
- Versión vigente: `"1"`.
- Costo candidato: 89,114.
- Costo vigente: 89,114.
- Mejora: 0%, inferior al margen requerido del 1%.

### Reentrenamiento tras cambio de demanda

- Estado terminal: `exitoso`.
- `promovido`: `true`.
- Nueva versión vigente: `"3"`.
- Costo candidato: 214,455.
- Costo vigente anterior: 443,682.
- Mejora: 51.7%.
- Tiempo hasta que la API sirvió v3: 15.2 segundos.

### Reentrenamiento con MLflow detenido

- Solicitud inicial: HTTP 202.
- Estado terminal: `fallido`.
- `promovido`: `false`.
- Versión vigente conservada: `"3"`.
- Duración: 184.4 segundos.

### Persistencia

Antes y después de `docker compose down` seguido de `up`, sin `-v`:

- solicitudes: 78
- predicciones: 480
- correcciones: 42
- observaciones: 19
- reentrenamientos: 1
- histórico: 83,052
- versión vigente: 1

No se observaron pérdidas ni repeticiones del bootstrap.

## 7. Comandos ejecutados

Se omiten únicamente los valores secretos escritos en el `.env` temporal.

```powershell
pdfinfo Laboratorio_2_PD_26_c.pdf
pdftotext Laboratorio_2_PD_26_c.pdf -
python <script pypdf para extraer las 7 páginas>
pdftoppm -png Laboratorio_2_PD_26_c.pdf <directorio-temporal>

git clone https://github.com/geotectronics-source/novamercado-ml <clon-temporal>
git checkout entrega-lab2
git rev-parse HEAD
git show --no-patch --format=fuller HEAD
git for-each-ref refs/tags/entrega-lab2
git status --short
git diff --exit-code
git ls-files
git ls-files --eol

Copy-Item datos_lab2 <clon>\datos\datos_lab2 -Recurse
Copy-Item .env.example .env
# AIRFLOW_PUERTO_HOST=8088 en el .env temporal

docker version
docker compose version
docker compose -p auditoria config
docker compose -p auditoria build
docker compose -p auditoria up -d
docker compose -p auditoria ps
docker compose -p auditoria logs bootstrap
docker compose -p auditoria logs api
docker compose -p auditoria logs airflow-scheduler

python blackbox_audit.py
python simulate_shift.py

docker compose -p auditoria stop mlflow
docker compose -p auditoria start mlflow
docker compose -p auditoria run --rm --no-deps api python -m pytest -q /app/tests

Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/modelo
Invoke-RestMethod -Method Post http://localhost:8000/admin/reentrenar
Invoke-RestMethod http://localhost:8000/admin/reentrenar/<id>

docker compose -p auditoria exec db psql <consultas de tablas, conteos e idempotencia>
docker compose -p auditoria exec db-airflow psql <consultas de DAG runs y tareas>
docker compose -p auditoria exec api python <consultas al cliente MLflow>
docker run --rm <imagen-api> find /app <inspección de la imagen>

docker compose -p auditoria down
docker compose -p auditoria up -d
docker compose -p auditoria down -v

docker ps -a --filter label=com.docker.compose.project=auditoria
docker volume ls --filter label=com.docker.compose.project=auditoria

rg -n <patrones> docker-compose.yml src dags README.md DECISIONES.md
Get-Content requirements/app.txt
Get-Content requirements/ml.txt
```

## 8. Prioridad recomendada para correcciones

Para reducir al máximo el riesgo frente al evaluador automático, atender en este orden:

1. Alinear el cuerpo 503 de `/health` con el enum literal esperado por el Anexo.
2. Publicar los esquemas de entrada en OpenAPI sin perder la capacidad de reparar entradas.
3. Agregar `signature` e `input_example` a los modelos MLflow.
4. Acortar el camino de fallo cuando MLflow no está disponible.
5. Fijar el backend de construcción y reforzar la reproducibilidad de las imágenes.
6. Eliminar los avisos de permisos de pytest.

Estas recomendaciones no fueron aplicadas durante la auditoría.
