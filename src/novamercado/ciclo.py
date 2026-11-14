"""Ciclo de mejora continua: entrenar → registrar → decidir → (promover).

Lo usan el bootstrap (primer modelo) y las tareas del DAG de Airflow.

Criterio de reemplazo (explícito y automatizado)
-----------------------------------------------
El candidato reemplaza al vigente si y solo si:
  1. Pasa los controles de sanidad (predicciones finitas y no negativas en TODAS las
     filas de validación, costo finito y no más de 3 veces el del baseline).
  2. Su costo de negocio en la ventana de validación (últimos 28 días, fuera de muestra
     para ambos modelos) es menor que el del vigente por al menos ``MARGEN_REEMPLAZO``
     (1 % por defecto):  costo_candidato < costo_vigente · (1 − margen).
Si no existe un vigente, el candidato se promueve si pasa la sanidad.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from . import registro
from .catalogos import Catalogos
from .config import Config
from .costos import metricas
from .entrenamiento import entrenar_candidatos, evaluar

log = logging.getLogger(__name__)


def _miles(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def entrenar_y_registrar(datos: pd.DataFrame, cat: Catalogos, cfg: Config, origen: str) -> dict:
    """Entrena baseline y LightGBM, registra ambos runs y registra como versión al mejor."""
    resultados, ventanas, X = entrenar_candidatos(datos, cat)
    n_obs = int(datos.attrs.get("n_observaciones", 0))
    comunes = {"fecha_max_datos": str(datos["fecha"].max().date()), "n_filas_datos": len(datos),
               "n_observaciones_bd": n_obs, **{f"ventana_{k}": v for k, v in ventanas.como_dict().items()}}
    runs = {}
    for nombre, r in resultados.items():
        params = {"modelo": nombre, **comunes}
        if hasattr(r.modelo, "params"):
            params.update({f"lgbm_{k}": v for k, v in r.modelo.params.items()} | {"lgbm_n_arboles": r.modelo.n_arboles})
        runs[nombre] = registro.registrar_run(
            cfg, f"{origen}_{nombre}", r.modelo, r.metricas_validacion, params,
            etiquetas={"origen": origen, "tipo_modelo": nombre},
            extras={"predicciones_validacion.csv": r.predicciones_validacion})

    mejor = min(resultados, key=lambda n: resultados[n].metricas_validacion["costo_total"])
    costo_mejor = resultados[mejor].metricas_validacion["costo_total"]
    version = registro.registrar_version(cfg, runs[mejor], {
        "origen": origen, "tipo_modelo": mejor, "costo_validacion": round(costo_mejor, 2),
        "fecha_max_datos": comunes["fecha_max_datos"], "decision": "pendiente"})
    return {
        "version_candidata": version, "run_id": runs[mejor], "tipo_modelo": mejor, "ventanas": ventanas.como_dict(),
        "metricas": {n: r.metricas_validacion for n, r in resultados.items()},
        "costo_baseline": resultados["baseline_estacional"].metricas_validacion["costo_total"],
    }


def sanidad(modelo, X_val: pd.DataFrame, costo: float, costo_baseline: float) -> tuple[bool, str]:
    pred = modelo.predecir(X_val)
    if len(pred) == 0:
        return False, "no hay filas de validación"
    if not np.isfinite(pred["venta_esperada"]).all() or (pred["venta_esperada"] < 0).any():
        return False, "predicciones no finitas o negativas"
    if not math.isfinite(costo):
        return False, "costo no finito"
    if costo > 3 * costo_baseline:
        return False, f"costo {_miles(costo)} supera 3× el del baseline ({_miles(costo_baseline)})"
    return True, "ok"


def decidir(datos: pd.DataFrame, cat: Catalogos, cfg: Config, entrenamiento: dict) -> dict:
    """Compara candidato vs vigente en la MISMA ventana de validación."""
    from .features import construir_features

    costos = cat.costos_dict()
    v = entrenamiento["ventanas"]
    X = construir_features(datos, cat)
    X_val = X[(X["fecha"] > pd.Timestamp(v["fin_calibracion"])) & (X["fecha"] <= pd.Timestamp(v["fin_validacion"]))
              & X["ventas"].notna()]

    version_cand = entrenamiento["version_candidata"]
    candidato = registro.cargar_version(cfg, version_cand)
    m_cand, _ = evaluar(candidato, X_val, costos)
    ok, motivo_sanidad = sanidad(candidato, X_val, m_cand["costo_total"], entrenamiento["costo_baseline"])

    version_vig = registro.version_vigente(cfg)
    costo_vig = None
    if version_vig is not None:
        vigente = registro.cargar_version(cfg, version_vig)
        m_vig, _ = evaluar(vigente, X_val, costos)
        costo_vig = m_vig["costo_total"]

    c = m_cand["costo_total"]
    if not ok:
        promover, motivo = False, f"Candidato v{version_cand} no pasó controles de sanidad: {motivo_sanidad}"
    elif costo_vig is None:
        promover, motivo = True, f"No había modelo vigente; costo en validación {_miles(c)}"
    else:
        umbral = costo_vig * (1 - cfg.margen_reemplazo)
        mejora = (costo_vig - c) / costo_vig if costo_vig else 0.0
        promover = c < umbral
        motivo = (f"Costo en validación {_miles(c)} vs {_miles(costo_vig)} del vigente "
                  f"(mejora {mejora:.1%}; se exige ≥ {cfg.margen_reemplazo:.0%})")
    return {"promover": promover, "motivo": motivo, "version_candidata": version_cand,
            "version_vigente_previa": version_vig, "costo_candidato": c, "costo_vigente": costo_vig,
            "metricas_candidato": m_cand}


def aplicar_decision(cfg: Config, decision: dict) -> str | None:
    """Mueve el alias si corresponde. Devuelve la versión vigente al terminar."""
    vc = decision["version_candidata"]
    if decision["promover"]:
        registro.promover(cfg, vc)
        registro.etiquetar_version(cfg, vc, {"decision": "promovido", "motivo": decision["motivo"]})
        return vc
    registro.etiquetar_version(cfg, vc, {"decision": "rechazado", "motivo": decision["motivo"]})
    return decision["version_vigente_previa"]
