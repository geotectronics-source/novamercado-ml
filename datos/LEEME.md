# Carpeta de datos publicados

Coloque aquí **los archivos publicados en el GES** (esta carpeta se monta en solo lectura en el
contenedor `bootstrap` como `/datos`):

```
datos/
├── tiendas.csv
├── familias.csv
├── costos.csv
├── feriados.csv
├── historico_ventas.csv
├── catalogo_errores.md      (opcional, solo referencia)
└── ejemplos/                (opcional, solo referencia)
```

Los datos no se versionan (`.gitignore`) ni se copian a las imágenes (`.dockerignore`).
