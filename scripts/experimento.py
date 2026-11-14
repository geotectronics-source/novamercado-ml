"""Experimento offline (fase 4-5 del plan): compara baseline vs LightGBM en varios cortes.

Uso:  python scripts/experimento.py datos/
Simula reentrenamientos en distintas fechas (backtesting con origen móvil) para ver si
la mejora del modelo es estable y no producto de una sola ventana.
"""
import sys
import time

import pandas as pd

sys.path.insert(0, "src")
from novamercado.catalogos import Catalogos  # noqa: E402
from novamercado.entrenamiento import entrenar_candidatos  # noqa: E402
from novamercado.features import construir_features  # noqa: E402

carpeta = sys.argv[1] if len(sys.argv) > 1 else "datos"
cat = Catalogos.desde_csv(carpeta)
hist = pd.read_csv(f"{carpeta}/historico_ventas.csv", parse_dates=["fecha"])
t0 = time.time()
X_full = construir_features(hist, cat)
print(f"features: {X_full.shape} en {time.time()-t0:.1f}s")

filas = []
for corte in ["2025-06-30", "2025-09-30", "2025-12-31", "2026-02-28"]:
    t0 = time.time()
    datos = hist[hist["fecha"] <= corte]
    X = X_full[X_full["fecha"] <= corte]
    res, v, _ = entrenar_candidatos(datos, cat, features=X)
    for nombre, r in res.items():
        m = r.metricas_validacion
        filas.append({"corte": corte, "modelo": nombre, **{k: round(m[k], 4) for k in
                      ("costo_total", "costo_sugerir_media", "wape", "sesgo_pct", "mae", "tasa_faltante")}})
    print(f"corte {corte} listo en {time.time()-t0:.1f}s")

tabla = pd.DataFrame(filas)
pd.set_option("display.width", 200)
print(tabla.to_string(index=False))
print(tabla.groupby("modelo")[["costo_total", "wape"]].mean())
