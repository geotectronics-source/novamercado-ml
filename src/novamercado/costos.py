"""Métrica de negocio (costo asimétrico) y calibración de la cantidad sugerida.

costo = c_faltante · max(real − sugerido, 0) + c_sobrante · max(sugerido − real, 0)

Para un pronóstico probabilístico, la cantidad que minimiza el costo esperado es el
cuantil  τ = c_faltante / (c_faltante + c_sobrante)  de la demanda (problema del
*newsvendor*). Aquí se estima ese cuantil con un **multiplicador** k por grupo
(familia × tipo de tienda):  sugerido = round(k · venta_esperada), eligiendo k que
minimiza el costo observado en una ventana de calibración fuera de muestra.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GRILLA_K = np.round(np.arange(0.50, 2.505, 0.005), 3)


def costo_filas(real, sugerido, c_falt, c_sobr) -> np.ndarray:
    real = np.asarray(real, dtype=float)
    sugerido = np.asarray(sugerido, dtype=float)
    return (np.asarray(c_falt) * np.maximum(real - sugerido, 0)
            + np.asarray(c_sobr) * np.maximum(sugerido - real, 0))


def redondear_sugerido(valores) -> np.ndarray:
    """Entero no negativo, como exige el contrato."""
    v = np.nan_to_num(np.asarray(valores, dtype=float), nan=0.0)
    return np.maximum(np.rint(v), 0).astype(int)


def mejor_multiplicador(real, esperado, c_falt: float, c_sobr: float) -> float:
    real = np.asarray(real, float)[:, None]
    esperado = np.asarray(esperado, float)[:, None]
    sug = np.maximum(np.rint(esperado * GRILLA_K[None, :]), 0)
    costo = (c_falt * np.maximum(real - sug, 0) + c_sobr * np.maximum(sug - real, 0)).sum(axis=0)
    return float(GRILLA_K[int(np.argmin(costo))])


def calibrar_multiplicadores(df: pd.DataFrame, costos: dict[str, tuple[float, float]],
                             min_filas: int = 60) -> dict[str, float]:
    """df con columnas familia_id, tipo_tienda, ventas, esperado.

    Devuelve claves 'familia|tipo' y, como respaldo, 'familia|*' (si el grupo es chico).
    """
    df = df.dropna(subset=["ventas", "esperado"])
    k: dict[str, float] = {}
    for fam, g in df.groupby("familia_id", observed=True):
        cf, cs = costos[str(fam)]
        k[f"{fam}|*"] = mejor_multiplicador(g["ventas"], g["esperado"], cf, cs)
        for tipo, gt in g.groupby("tipo_tienda", observed=True):
            if len(gt) >= min_filas:
                k[f"{fam}|{tipo}"] = mejor_multiplicador(gt["ventas"], gt["esperado"], cf, cs)
    return k


def multiplicador_para(k: dict[str, float], familia: str, tipo: str) -> float:
    return k.get(f"{familia}|{tipo}", k.get(f"{familia}|*", 1.0))


def metricas(df: pd.DataFrame, costos: dict[str, tuple[float, float]]) -> dict[str, float]:
    """df con ventas, esperado, sugerido, familia_id. Métricas técnicas + de negocio."""
    df = df.dropna(subset=["ventas"])
    y, yhat, s = df["ventas"].values, df["esperado"].values, df["sugerido"].values
    cf = df["familia_id"].astype(str).map(lambda f: costos[f][0]).values
    cs = df["familia_id"].astype(str).map(lambda f: costos[f][1]).values
    costo = costo_filas(y, s, cf, cs)
    costo_media = costo_filas(y, redondear_sugerido(yhat), cf, cs)
    err = yhat - y
    return {
        "costo_total": float(costo.sum()),
        "costo_por_dia_tienda": float(costo.sum() / max(df.groupby(["fecha", "tienda_id"], observed=True).ngroups, 1)),
        "costo_sugerir_media": float(costo_media.sum()),
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "wape": float(np.abs(err).sum() / max(y.sum(), 1e-9)),
        "sesgo_pct": float(err.sum() / max(y.sum(), 1e-9)),
        "tasa_faltante": float((y > s).mean()),
        "n_filas": int(len(df)),
    }
