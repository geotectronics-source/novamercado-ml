# Decisiones técnicas y de producto

Cada decisión indica **qué** se eligió, **alternativas** consideradas y **por qué**.

---

## 1. Política ante problemas en los datos de entrada

### 1.1 Principios (reglas generales, no casos particulares)

El catálogo de errores **no es exhaustivo**, así que no hay un `if` por ejemplo. Se definieron
principios y se implementaron intérpretes generales (`src/novamercado/calidad/`):

1. **Reparar** cuando la intención es **inequívoca**: existe una única interpretación posible
   (p. ej. `"T05"` → 5, `"LÁCTEOS"` → `lacteos`, `"17/11/2025"` → 2025-11-17 porque 17 > 12).
2. **Advertir** cuando se puede responder pero **hay que suponer algo**; el supuesto se escribe
   en `calidad.observaciones[].detalle` (p. ej. fecha `03/04/2026` ambigua → día/mes).
3. **Rechazar (422)** cuando no hay forma de responder **sin inventar** el dato esencial
   (tienda inexistente, fecha imposible, ninguna familia válida).
4. **Predicción ≠ observación.** En una predicción preferimos responder con un supuesto
   explícito (la tienda necesita su pedido). En una observación —que se usará para entrenar— un
   valor dudoso se **descarta** con advertencia: es preferible perder un registro que entrenar
   con un número inventado.

Cada acción queda en la respuesta (`calidad`) **y** en la tabla `correcciones` de la BD.
El estado es `advertencia` si hay alguna advertencia, `corregido` si solo hubo reparaciones y
`ok` sin observaciones.

### 1.2 Mecanismos generales

| Mecanismo | Regla | Cubre |
|---|---|---|
| Nombres de campos | forma canónica (sin acentos, minúsculas, camelCase→snake, separadores→`_`) + sinónimos ⇒ reparar; nombre parecido (similitud ≥ 0.85, sin empate) ⇒ advertir; desconocido ⇒ advertir e ignorar; obligatorio ausente ⇒ rechazar | E07 y variantes (`tiendaId`, `Store_ID`, `items`, `promo`…) |
| Números | punto decimal y coma de miles (convención de Guatemala). Coma + 3 dígitos = miles; coma + 1–2 dígitos = decimal; `1.234.567` y `1.234,5` inequívocos; `1.234` (un grupo) es **ambiguo** ⇒ no se interpreta | E03, E10 y variantes |
| Conteos | texto o decimal entero ⇒ reparar; decimal no entero ⇒ advertir y redondear; negativo ⇒ no válido | E03, E08 |
| Fechas | ISO ⇒ ok; ISO con hora, `AAAA/MM/DD`, `AAAAMMDD`, mes en texto ⇒ reparar; `dd/mm/aaaa` inequívoco ⇒ reparar; ambiguo ⇒ advertir (día/mes); año de 2 dígitos ⇒ advertir; imposible ⇒ rechazar | E04 y variantes |
| Tiendas | entero ⇒ ok; nombre de tienda, texto con un único número (`"5"`, `"T05"`, `"Tienda 5"`) o decimal entero ⇒ reparar; no existe en catálogo ⇒ rechazar | E01 y variantes |
| Familias | id exacto ⇒ ok; igual a id o nombre ignorando mayúsculas, acentos, espacios, conectores (`y`, `de`) y singular/plural ⇒ reparar; similitud ≥ 0.8 o palabras contenidas en un único nombre ⇒ advertir; sin coincidencia ⇒ advertir y omitir | E02 y variantes |

### 1.3 Política por tipo de problema

**`POST /v1/prediccion`**

| Problema | Política | Justificación |
|---|---|---|
| Cuerpo no es JSON/objeto, falta `tienda_id`, `fecha` o `familias` | **Rechazar** | Sin esos datos no hay pronóstico posible |
| E01 tienda como texto / con prefijo / por nombre | **Reparar** | Una sola interpretación |
| Tienda inexistente o ininterpretable | **Rechazar** | Inventar la tienda sería inventar el pronóstico |
| E02 familia con mayúsculas, acentos, espacios, nombre largo, singular | **Reparar** | Una sola interpretación |
| Familia parecida (error tipográfico) | **Advertir** | Probable pero es una suposición |
| Familia desconocida | **Advertir y omitir** ese elemento | El resto de la solicitud sí es útil |
| Ninguna familia válida | **Rechazar** | No queda nada que pronosticar |
| E03 promoción como texto o `2.0` | **Reparar** | Valor idéntico |
| Promoción decimal no entera | **Advertir y redondear** | El campo es un conteo |
| Promoción ausente, negativa o ininterpretable | **Advertir, se asume 0** | Es el valor más frecuente (mediana 0); se marca `promocion_supuesta: true` |
| E04 fecha en otro formato inequívoco | **Reparar** | Una sola interpretación |
| Fecha ambigua (`03/04/2026`) | **Advertir**, se usa día/mes | Convención local (Guatemala) |
| Fecha imposible o ininterpretable | **Rechazar** | — |
| Fecha anterior a la apertura de la tienda | **Rechazar** | La tienda no operaba |
| Fecha sin historia previa en la BD | **Rechazar** | No hay base para pronosticar sin inventar |
| Fecha posterior a la cobertura de `feriados.csv` | **Advertir** | Se supone que no es feriado |
| Última venta conocida hace más de 7 días | **Advertir** | Se usa el último nivel conocido |
| E05 faltan familias que la tienda vende | **Advertir**, se pronostican con promoción 0 | La tienda necesita el pedido completo; el supuesto se indica por familia (`promocion_supuesta`) |
| E06 familia repetida con los mismos valores | **Reparar** (se deduplica) | No cambia nada |
| E06 familia repetida con valores distintos | **Advertir**, se usa la **última** aparición | Los sistemas suelen agregar correcciones al final; alternativa descartada: rechazar (detiene a la tienda por un detalle) |
| E07 nombre de campo distinto (sinónimo/formato) | **Reparar** | — |
| Campo con nombre parecido | **Advertir** | — |
| Campo desconocido | **Advertir e ignorar** | Se supone que no aporta al pronóstico |
| `familias` como objeto `{familia: promo}` o elementos como texto | **Reparar** | Estructura distinta, misma información |

**`POST /v1/observaciones`**

| Problema | Política | Justificación |
|---|---|---|
| Tienda, fecha, nombres de campo, familias | Igual que en predicción | Consistencia |
| E10 `"1,234"`, `"812,0"`, texto, `2.0` | **Reparar** | Una sola interpretación |
| Ventas decimal no entera | **Advertir y redondear** | Unidades enteras |
| E08 ventas negativas | **Advertir y no guardar ese registro** | Son devoluciones: la venta real es desconocida; guardarlas (o poner 0) contaminaría el entrenamiento |
| Ventas ausentes, ambiguas (`"1.234"`) o ininterpretables | **Advertir y no guardar** | No inventar la verdad |
| Ningún registro válido | **Rechazar** | — |
| E09 reenvío idéntico | **Idempotente**: 200, `registros_guardados = 0`, estado `ok` | La clave (tienda, familia, fecha) es primaria y el *upsert* solo escribe si el valor cambió |
| Reenvío con valor distinto | **Advertir y reemplazar** (cuenta como modificado) | La corrección más reciente prevalece; queda constancia del valor anterior y `n_cambios` |

---

## 2. Información que usa el modelo al predecir

Todas las variables se calculan con **la misma función** (`features.construir_features`) al
entrenar y al servir, para evitar diferencias entre entrenamiento y producción.

| Grupo | Variables | Fuente |
|---|---|---|
| Promoción del día | `en_promocion` | La **solicitud** (las observaciones no traen promociones) |
| Calendario | día de la semana, día del mes, mes, días para fin de mes | Fecha solicitada |
| Feriados por ciudad | es feriado / comercial / pago / medio día; días al próximo feriado, desde el último feriado, al próximo evento comercial y desde el último pago | `feriados.csv` filtrado por `ambito = nacional` o la `ciudad` de la tienda |
| Nivel reciente (`base`) | media de los últimos 28 días; si hay < 7 observaciones en esa ventana, media de las últimas 28 observaciones existentes | Histórico + observaciones **anteriores** a la fecha |
| Dinámica relativa al nivel | ayer, hace 7 y 14 días, media de 7 días, media del mismo día de la semana en 4 semanas, hace 364 días, coeficiente de variación de 28 días, días desde la última observación | Igual |
| Estacionalidad anual | cómo cambió hace un año la semana objetivo respecto a sus 4 semanas previas | Igual |
| Identidad | tienda, familia, tipo de tienda (categóricas) | Catálogos |

Restricciones respetadas:

* **Solo datos anteriores a la fecha** (prueba `test_features_no_usan_el_futuro`).
* **Nunca el reloj del sistema**: la validez de una fecha depende del catálogo (apertura,
  cobertura de feriados) y de la historia existente.
* Si falta la observación de ayer, el modelo sigue funcionando: durante el entrenamiento se
  oculta aleatoriamente el rezago de 1 día en 10 % de las filas para que aprenda a usar las
  demás señales.

## 3. Modelos

| Modelo | Descripción |
|---|---|
| **Baseline** `baseline_estacional` | Media del mismo día de la semana en las últimas 4 semanas (respaldo: nivel reciente) |
| **ML** `lightgbm_cociente` | LightGBM global (todas las tiendas y familias) que predice el **cociente** ventas / nivel reciente, ponderado por el nivel; 600 árboles, 63 hojas, `min_data_in_leaf=100` |
| **ML** `ensamble_lgbm_loglineal` | Promedio geométrico del LightGBM anterior y de una **regresión log-lineal** regularizada (Ridge, α = 3) con interacciones tipo × familia × día de la semana, día del mes × tipo de tienda, promoción (log) por familia, feriados y mes por familia |

**Los tres compiten en cada entrenamiento.** Se registra como versión candidata el de menor
costo en validación, y luego el criterio de reemplazo (§5) lo compara con el vigente. El
ensamble se agregó tras el análisis de [`docs/ANALISIS_MODELOS.md`](docs/ANALISIS_MODELOS.md):
* la parte lineal **extrapola** efectos (promociones, niveles) que los árboles no pueden, lo que
  da robustez ante cambios de demanda;
* ganó en los dos cortes más exigentes (diciembre y el más reciente);
* en promedio queda a 0,9 % del LightGBM solo, así que el sistema elige en cada momento el que
  mejor funcione en lugar de fijar uno de antemano.

**¿Por qué predecir un cociente?** Los árboles no extrapolan: si la demanda sube 20 %, un modelo
de nivel absoluto se queda en los valores que vio. Al expresar el objetivo relativo al nivel
reciente, un cambio de nivel lo absorbe la variable `base` y el modelo solo aprende la forma
(día de la semana, promociones, feriados). Es la principal defensa ante **cambios en el
comportamiento de la demanda**, que el periodo de evaluación puede incluir.

Backtest con origen móvil (validación de 28 días después de cada corte; `scripts/experimento.py`):

| Corte | Costo baseline | Costo LightGBM | Costo ensamble | WAPE baseline | WAPE LightGBM | WAPE ensamble |
|---|---:|---:|---:|---:|---:|---:|
| 2025-06-30 | 101 222 | **87 545** | 88 985 | 0.213 | 0.179 | 0.181 |
| 2025-09-30 | 102 038 | **88 298** | 93 210 | 0.213 | 0.180 | 0.183 |
| 2025-12-31 | 167 089 | 118 684 | **116 626** | 0.255 | 0.190 | 0.188 |
| 2026-02-28 | 112 023 | 89 947 | **89 109** | 0.215 | 0.176 | 0.177 |
| **Promedio** | 120 593 | **96 119 (−20 %)** | 96 983 (−20 %) | 0.224 | 0.181 | 0.182 |

Alternativas evaluadas: hojas más pequeñas, tasa de aprendizaje menor y pérdida L1 (diferencias
< 0.5 % en costo, la L1 fue peor en diciembre); pérdida Tweedie (+1,7 %), log-lineal solo
(+7,8 %) y optimización directa del costo con pérdida cuantílica (+15 % a +20 %, inestable en
cuantiles extremos). El detalle está en `docs/ANALISIS_MODELOS.md`. Se descartaron modelos por serie (ARIMA/Prophet:
120 modelos que mantener, peores con pocas observaciones nuevas) y redes neuronales (más costo
operativo sin evidencia de mejora con 2 años de datos).

Métricas registradas en MLflow por run: `costo_total` (negocio), `costo_por_dia_tienda`,
`costo_sugerir_media`, `mae`, `rmse`, `wape`, `sesgo_pct`, `tasa_faltante`.

## 4. Cantidad sugerida

El costo es asimétrico: `c_falt · max(real − sug, 0) + c_sobr · max(sug − real, 0)`. La cantidad
que minimiza el costo esperado es el **cuantil crítico** de la demanda (problema del *newsvendor*):

  τ = c_faltante / (c_faltante + c_sobrante)

Implementación: `cantidad_sugerida = round(k · venta_esperada)`, con un multiplicador `k` por
**familia × tipo de tienda** (respaldo: por familia) elegido para **minimizar el costo
observado** en una ventana de calibración que el modelo no vio (`costos.calibrar_multiplicadores`).
Minimizar el costo empírico equivale a estimar el cuantil τ de la distribución real/esperado.

| Familia | τ | k (todas las tiendas) |
|---|---:|---:|
| licores | 0.95 | 1.60 |
| cuidado_personal, limpieza | 0.91 | 1.30–1.34 |
| bebe | 0.88 | 1.32 |
| abarrotes, bebidas, mascotas | 0.83 | 1.18–1.26 |
| snacks | 0.77 | 1.17 |
| lacteos | 0.45 | 0.96 |
| carnes | 0.43 | 0.94 |
| frutas_verduras | 0.33 | 0.92 |
| panaderia | 0.29 | 0.85 |

Coherencia con los costos: donde sobrar es barato (licores) se sugiere 60 % por encima de lo
esperado; donde sobrar es caro (pan) se sugiere 15 % por debajo. Frente a sugerir la venta
esperada, el costo baja ~25 % en validación y ~30 % en la simulación de 28 días.

Alternativas: regresión cuantílica con un LightGBM por τ (12 modelos más, mismo resultado
esperado y más difícil de operar); `media + z·σ` suponiendo normalidad (las ventas son
asimétricas y de conteo). El multiplicador multiplicativo se eligió porque el error crece con el
volumen, y separarlo por tipo de tienda corrige que las tiendas express (volúmenes bajos) tengan
más ruido relativo.

## 5. Criterio de reemplazo del modelo

**Protocolo de evaluación (sin fuga de información).** Con T = última fecha con ventas:

```
──── entrenamiento A ────┬─ calibración (56 d) ─┬─ validación (28 d) ─┐ T
──────────── entrenamiento B ───────────────────┘
```

* El modelo A (datos ≤ T−84) calibra los multiplicadores `k` en la ventana de calibración.
* El modelo B (datos ≤ T−28) + `k` es el **candidato**: se valida en los últimos 28 días.
* **Lo que se valida es exactamente lo que se despliega** (no se re-ajusta después).
* El vigente se evalúa en **la misma** ventana. Como fue entrenado en un corte anterior, la
  ventana también es fuera de muestra para él ⇒ comparación justa.

**Criterio (automático, en `ciclo.decidir`).** El candidato reemplaza al vigente si y solo si:

1. pasa la sanidad: predicciones finitas y no negativas en todas las filas, costo finito y no
   mayor que 3 veces el del baseline; y
2. `costo_candidato < costo_vigente × (1 − 0.01)` (mejora ≥ 1 %, configurable con
   `MARGEN_REEMPLAZO`).

Si no hay vigente (primer arranque) basta la sanidad. El motivo queda en la respuesta de
`GET /admin/reentrenar/{id}`, en la tabla `reentrenamientos` y como etiqueta de la versión en
MLflow (`decision = promovido | rechazado`, `motivo`).

**Por qué un margen del 1 %:** evita cambiar de modelo por ruido (en la simulación, las
diferencias sin cambios reales fueron de ±0.2 %), y cada cambio tiene costo operativo
(trazabilidad, riesgo). Alternativas descartadas: *promover siempre el más reciente* (riesgo de
promover un modelo peor), *prueba estadística de Diebold-Mariano* (más compleja de explicar a
operaciones con beneficio dudoso en 28 días) y *re-ajustar con todos los datos tras decidir*
(el modelo desplegado no sería el validado y el vigente tendría ventaja dentro de muestra en la
siguiente comparación).

**Versionado.** Cada reentrenamiento registra tres runs (baseline, LightGBM y ensamble) y registra como
versión al mejor de ellos; el alias `vigente` solo se mueve si se cumple el criterio. Un
reentrenamiento que falla o no supera el criterio **no toca el alias**.

## 6. Ciclo de reentrenamiento (Airflow)

* `POST /admin/reentrenar` dispara el DAG `reentrenamiento_modelo` por la API REST de Airflow
  con un `dag_run_id` propio, que es el `id` devuelto (202). Si Airflow no responde: 503.
* Tareas: `preparar_datos` (histórico + observaciones de la BD; la promoción de un día observado
  se toma de la última solicitud de pronóstico de ese día) → `entrenar_candidato` →
  `evaluar_y_decidir` → `publicar_resultado` (mueve el alias y escribe el resultado; si la
  escritura falla, revierte el alias). Si cualquier tarea falla, `marcar_fallo` registra el
  motivo y deja la corrida en `failed`.
* Las tareas corren con el Python de un **entorno virtual separado** (`/opt/venv-ml`) dentro de
  la imagen de Airflow: las dependencias del modelo no chocan con las restricciones de Airflow.
* `GET /admin/reentrenar/{id}` lee la BD del producto y, si sigue en curso, consulta el estado
  en Airflow (si Airflow reporta `failed`, se marca `fallido`).
* Duración medida: ~20 s por ejecución con los tres candidatos (límite 10 min; `dagrun_timeout` = 10 min).

## 7. Servir el modelo sin reinicio y tolerar fallas

* **Recarga en caliente:** un hilo de la API consulta el alias cada 20 s; si cambió, carga la
  nueva versión y la intercambia atómicamente. Medido: el servicio usa el modelo nuevo ≤ 20 s
  después de terminar el DAG (límite: 2 min).
* **MLflow caído:** el modelo está en memoria y además en una **caché en disco** (volumen
  `api-cache`) para poder arrancar aunque MLflow no esté. Un monitor revisa MLflow y Airflow
  cada 15 s: `/health` pasó a `degradado` en 12 s y volvió a `ok` en 3–18 s (según la corrida).
* **`/health`:** `ok` si API, BD, MLflow, Airflow y modelo están bien; `degradado` + `motivo`
  si alguna dependencia falla pero se puede responder; 503 mientras no hay modelo.
* **Arranque e idempotencia:** el `bootstrap` usa un *advisory lock* para crear el esquema, solo
  carga los CSV si la tabla está vacía y solo entrena si no existe el alias `vigente`.

## 8. Persistencia

PostgreSQL del producto (`db`), separada de la de Airflow (`db-airflow`); MLflow usa SQLite y
artefactos en su propio volumen. Tablas: `solicitudes` (cuerpo crudo y limpio, código HTTP,
estado de calidad, versión del modelo), `predicciones` (por familia, con versión),
`correcciones`, `observaciones` (clave primaria tienda-familia-fecha ⇒ idempotencia),
`reentrenamientos`, catálogos e histórico. Todo vive en volúmenes nombrados, que sobreviven a
`docker compose down`.

## 9. Otras decisiones

* **Contrato estricto en dos etapas:** limpieza (reglas) → validación Pydantic en modo estricto.
  Si algo pasara la limpieza sin cumplir el contrato, es un error nuestro y no llega al modelo.
* **Campo adicional `promocion_supuesta`** en cada predicción (el contrato permite agregar campos).
* **Imágenes con versiones fijas** (`python:3.12.8-slim-bookworm`, `postgres:16.6-alpine`,
  `ghcr.io/mlflow/mlflow:v2.19.0`, `apache/airflow:2.10.4-python3.12`) y dependencias fijadas.
* **Datos y credenciales fuera del repositorio y de las imágenes** (`.gitignore`, `.dockerignore`,
  `.env.example`). La carpeta `datos/` se monta en solo lectura.

## 10. Limitaciones conocidas

* La ventana de validación de 28 días mezcla datos anteriores y posteriores a un cambio de
  demanda; tras un cambio brusco el criterio puede tardar uno o dos reentrenamientos en
  promover. El cociente sobre el nivel reciente mitiga el impacto mientras tanto.
* Un único proceso de API (estado del modelo en memoria); para escalar horizontalmente cada
  réplica recargaría el modelo por su cuenta (el diseño ya lo permite).
* Las fechas ambiguas usan la convención local día/mes; si un sistema de tienda usa mes/día de
  forma sistemática, convendría una regla por tienda aprendida del historial de solicitudes.
