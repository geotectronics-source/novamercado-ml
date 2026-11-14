# Ejemplos de respuestas de la API

Generado con `scripts/generar_evidencia.py` contra el producto levantado con Docker Compose.

## Predicción válida

`POST /v1/prediccion` (archivo `prediccion_valida.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## E01_tienda_texto

`POST /v1/prediccion` (archivo `E01_tienda_texto.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "'T05' se interpretó como tienda 5"
      }
    ]
  }
}
```

## E02_familia_otra_forma

`POST /v1/prediccion` (archivo `E02_familia_otra_forma.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[5].familia_id",
        "accion": "reparar",
        "detalle": "'Frutas y Verduras' se interpretó como 'frutas_verduras'"
      },
      {
        "campo": "familias[6].familia_id",
        "accion": "reparar",
        "detalle": "'LÁCTEOS' se interpretó como 'lacteos'"
      }
    ]
  }
}
```

## E03_promocion_texto

`POST /v1/prediccion` (archivo `E03_promocion_texto.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[2].en_promocion",
        "accion": "reparar",
        "detalle": "en_promocion 8.0 se interpretó como el entero 8"
      },
      {
        "campo": "familias[11].en_promocion",
        "accion": "reparar",
        "detalle": "en_promocion: '9' (texto) se interpretó como 9"
      }
    ]
  }
}
```

## E04_fecha_formato

`POST /v1/prediccion` (archivo `E04_fecha_formato.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "'17/11/2025' (día/mes/año) se interpretó como 2025-11-17"
      }
    ]
  }
}
```

## E05_faltan_familias

`POST /v1/prediccion` (archivo `E05_faltan_familias.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    {
      "familia_id": "carnes",
      "venta_esperada": 200.87,
      "cantidad_sugerida": 187,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "faltan 2 familias que la tienda vende (bebe, mascotas); se pronosticaron suponiendo en_promocion = 0"
      }
    ]
  }
}
```

## E06_familia_repetida

`POST /v1/prediccion` (archivo `E06_familia_repetida.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 1148.46,
      "cantidad_sugerida": 1349,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias[12]",
        "accion": "advertir",
        "detalle": "familia 'abarrotes' repetida con en_promocion distinto (0 en familias[0] vs 3); se usó el último valor"
      }
    ]
  }
}
```

## E07_campo_renombrado

`POST /v1/prediccion` (archivo `E07_campo_renombrado.json`) → **HTTP 200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 975.57,
      "cantidad_sugerida": 1146,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 63.48,
      "cantidad_sugerida": 83,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1053.12,
      "cantidad_sugerida": 1285,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "campo 'tienda' se interpretó como 'tienda_id'"
      }
    ]
  }
}
```

## E08_ventas_negativas

`POST /v1/observaciones` (archivo `E08_ventas_negativas.json`) → **HTTP 200**

```json
{
  "registros_guardados": 11,
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "ventas[5].ventas",
        "accion": "advertir",
        "detalle": "ventas negativo (-4); no se guardó el registro de 'frutas_verduras'"
      }
    ]
  }
}
```

## E09_envio_repetido

`POST /v1/observaciones` (archivo `E09_envio_repetido.json`) → **HTTP 200**

```json
{
  "registros_guardados": 1,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## E10_numero_formato

`POST /v1/observaciones` (archivo `E10_numero_formato.json`) → **HTTP 200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "ventas[1].ventas",
        "accion": "reparar",
        "detalle": "ventas: '50,0' usa coma decimal; se interpretó como 50"
      },
      {
        "campo": "ventas[2].ventas",
        "accion": "reparar",
        "detalle": "ventas: '1,292' usa coma de miles; se interpretó como 1292"
      }
    ]
  }
}
```

## Observación válida

`POST /v1/observaciones` (archivo `observacion_valida.json`) → **HTTP 200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## E09 reenvío idéntico (idempotencia)

`POST /v1/observaciones` (archivo `observacion_valida.json`) → **HTTP 200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

# Casos fuera del catálogo

## N01 campos camelCase, lista como objeto, nombre de tienda

Solicitud:
```json
{
  "tiendaId": "NovaMercado Mixco",
  "Fecha": "2026-03-02",
  "items": {
    "Lácteo": "2",
    "BEBIDAS": 1,
    "Snacks y Dulces": 0
  }
}
```
Respuesta **HTTP 200**:
```json
{
  "tienda_id": 2,
  "fecha": "2026-03-02",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "lacteos",
      "venta_esperada": 269.77,
      "cantidad_sugerida": 251,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 363.86,
      "cantidad_sugerida": 448,
      "promocion_supuesta": false
    },
    {
      "familia_id": "snacks",
      "venta_esperada": 188.03,
      "cantidad_sugerida": 218,
      "promocion_supuesta": false
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "campo 'tiendaId' se interpretó como 'tienda_id'"
      },
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "campo 'Fecha' se interpretó como 'fecha'"
      },
      {
        "campo": "familias",
        "accion": "reparar",
        "detalle": "campo 'items' se interpretó como 'familias'"
      },
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "'NovaMercado Mixco' corresponde por nombre a la tienda 2"
      },
      {
        "campo": "familias",
        "accion": "reparar",
        "detalle": "'familias' llegó como objeto {familia: valor}; se convirtió a lista"
      },
      {
        "campo": "familias[0].familia_id",
        "accion": "reparar",
        "detalle": "'Lácteo' se interpretó como 'lacteos'"
      },
      {
        "campo": "familias[0].en_promocion",
        "accion": "reparar",
        "detalle": "en_promocion: '2' (texto) se interpretó como 2"
      },
      {
        "campo": "familias[1].familia_id",
        "accion": "reparar",
        "detalle": "'BEBIDAS' se interpretó como 'bebidas'"
      },
      {
        "campo": "familias[2].familia_id",
        "accion": "reparar",
        "detalle": "'Snacks y Dulces' se interpretó como 'snacks'"
      },
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "faltan 9 familias que la tienda vende (abarrotes, bebe, carnes, cuidado_personal, frutas_verduras, licores, limpieza, mascotas, panaderia); se pronosticaron suponiendo en_promocion = 0"
      }
    ]
  }
}
```

## N02 fecha ambigua y promoción negativa

Solicitud:
```json
{
  "tienda_id": 7,
  "fecha": "03/04/2026",
  "familias": [
    {
      "familia_id": "carnes",
      "en_promocion": -2
    },
    {
      "familia_id": "abarrotes",
      "en_promocion": 1
    }
  ]
}
```
Respuesta **HTTP 200**:
```json
{
  "tienda_id": 7,
  "fecha": "2026-04-03",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "carnes",
      "venta_esperada": 167.91,
      "cantidad_sugerida": 161,
      "promocion_supuesta": true
    },
    {
      "familia_id": "abarrotes",
      "venta_esperada": 673.79,
      "cantidad_sugerida": 822,
      "promocion_supuesta": false
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 37.67,
      "cantidad_sugerida": 48,
      "promocion_supuesta": true
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "advertir",
        "detalle": "'03/04/2026' (día/mes/año (ambiguo; convención local)) se interpretó como 2026-04-03"
      },
      {
        "campo": "familias[0].en_promocion",
        "accion": "advertir",
        "detalle": "en_promocion negativo (-2); se asumió 0"
      },
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "faltan 10 familias que la tienda vende (bebe, bebidas, cuidado_personal, frutas_verduras, lacteos, licores, limpieza, mascotas, panaderia, snacks); se pronosticaron suponiendo en_promocion = 0"
      }
    ]
  }
}
```

## N03 familia inexistente y campo desconocido

Solicitud:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-02",
  "sistema": "pos-v3",
  "familias": [
    {
      "familia_id": "electronica",
      "en_promocion": 1
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    }
  ]
}
```
Respuesta **HTTP 200**:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-02",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "licores",
      "venta_esperada": 81.56,
      "cantidad_sugerida": 128,
      "promocion_supuesta": false
    },
    {
      "familia_id": "abarrotes",
      "venta_esperada": 550.35,
      "cantidad_sugerida": 647,
      "promocion_supuesta": true
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 64.32,
      "cantidad_sugerida": 85,
      "promocion_supuesta": true
    },
    "... (9 más)"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "sistema",
        "accion": "advertir",
        "detalle": "campo 'sistema' no pertenece al contrato; se ignoró"
      },
      {
        "campo": "familias[0].familia_id",
        "accion": "advertir",
        "detalle": "familia 'electronica' no existe en el catálogo; se omitió el elemento"
      },
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "faltan 11 familias que la tienda vende (abarrotes, bebe, bebidas, carnes, cuidado_personal, frutas_verduras, lacteos, limpieza, mascotas, panaderia, snacks); se pronosticaron suponiendo en_promocion = 0"
      }
    ]
  }
}
```

## N04 tienda inexistente (rechazo)

Solicitud:
```json
{
  "tienda_id": 42,
  "fecha": "2026-03-02",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    }
  ]
}
```
Respuesta **HTTP 422**:
```json
{
  "detail": "tienda_id: la tienda 42 no existe en el catálogo (válidas: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])"
}
```

## N05 fecha imposible (rechazo)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2026-02-30",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    }
  ]
}
```
Respuesta **HTTP 422**:
```json
{
  "detail": "fecha: '2026-02-30' no es una fecha del calendario"
}
```

## N06 tienda 10 antes de su apertura (rechazo)

Solicitud:
```json
{
  "tienda_id": 10,
  "fecha": "2025-01-10",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    }
  ]
}
```
Respuesta **HTTP 422**:
```json
{
  "detail": "fecha: la tienda 10 abrió el 2025-03-15; no hay operación el 2025-01-10"
}
```

## GET /modelo → HTTP 200
```json
{
  "nombre": "novamercado_pronostico_ventas",
  "alias": "vigente",
  "version": "2"
}
```

## GET /health → HTTP 200
```json
{
  "estado": "ok",
  "componentes": {
    "api": "ok",
    "base_datos": "ok",
    "mlflow": "ok",
    "airflow": "ok",
    "modelo": "v2"
  }
}
```
