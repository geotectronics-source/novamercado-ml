"""Protocolo de entrenamiento y evaluación (sin dependencias de MLflow ni de la BD).

Con T = última fecha con ventas conocidas:

    ──────── entrenamiento A ────────┬── calibración ──┬── validación ──┐
                                     T-28-56          T-28              T
    ──────────── entrenamiento B ─────────────────────┘

* Modelo A (datos ≤ T-84) pronostica la ventana de calibración → multiplicadores k
  que minimizan el costo (fuera de muestra).
* Modelo B (datos ≤ T-28) + multiplicadores = **candidato**. Se evalúa en la ventana de
  validación, que ningún componente vio. Lo que se valida es exactamente lo que se despliega.
* El modelo vigente se evalúa en la misma ventana de validación (también fuera de muestra
  para él, porque fue entrenado antes) ⇒ comparación justa para el criterio de reemplazo.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .catalogos import Catalogos
from .costos import calibrar_multiplicadores, metricas
from .features import construir_features
from .modelo import Baseline, ModeloEnsamble, ModeloLGBM, ModeloLogLineal, Pronosticador

DIAS_VALIDACION = 28
DIAS_CALIBRACION = 56
MIN_DIAS_HISTORIA_FEATURES = 35  # primeras semanas sin rezagos suficientes


@dataclass
class Ventanas:
    fin_entrenamiento_a: pd.Timestamp
    fin_calibracion: pd.Timestamp  # = fin de entrenamiento B
    fin_validacion: pd.Timestamp

    def como_dict(self) -> dict:
        return {k: str(v.date()) for k, v in self.__dict__.items()}


@dataclass
class ResultadoCandidato:
    modelo: Pronosticador
    metricas_validacion: dict
    predicciones_validacion: pd.DataFrame


def definir_ventanas(features: pd.DataFrame, dias_val=DIAS_VALIDACION, dias_cal=DIAS_CALIBRACION) -> Ventanas:
    # T = último día con una cantidad "normal" de registros: una observación aislada con una
    # fecha muy posterior (p. ej. un error de captura) no debe desplazar las ventanas.
    por_dia = features.loc[features["ventas"].notna()].groupby("fecha").size()
    t = por_dia[por_dia >= 0.25 * por_dia.median()].index.max()
    fin_cal = t - pd.Timedelta(days=dias_val)
    return Ventanas(fin_entrenamiento_a=fin_cal - pd.Timedelta(days=dias_cal), fin_calibracion=fin_cal,
                    fin_validacion=t)


def _filas_entrenables(X: pd.DataFrame) -> pd.DataFrame:
    inicio = X["fecha"].min() + pd.Timedelta(days=MIN_DIAS_HISTORIA_FEATURES)
    return X[(X["fecha"] >= inicio) & X["ventas"].notna() & (X["base"] > 0)]


def evaluar(modelo: Pronosticador, X_val: pd.DataFrame, costos) -> tuple[dict, pd.DataFrame]:
    pred = modelo.predecir(X_val)
    df = X_val[["fecha", "tienda_id", "familia_id", "tipo_tienda", "ventas"]].copy()
    df["esperado"] = pred["venta_esperada"].values
    df["sugerido"] = pred["cantidad_sugerida"].values
    return metricas(df, costos), df


def entrenar_candidatos(datos: pd.DataFrame, cat: Catalogos, semilla: int = 42,
                        features: pd.DataFrame | None = None) -> tuple[dict[str, ResultadoCandidato], Ventanas, pd.DataFrame]:
    """Entrena baseline, LightGBM y el ensamble LightGBM + log-lineal con el protocolo descrito arriba."""
    costos = cat.costos_dict()
    X = construir_features(datos, cat) if features is None else features
    v = definir_ventanas(X)
    X_ok = _filas_entrenables(X)
    tr_a = X_ok[X_ok["fecha"] <= v.fin_entrenamiento_a]
    cal = X_ok[(X_ok["fecha"] > v.fin_entrenamiento_a) & (X_ok["fecha"] <= v.fin_calibracion)]
    tr_b = X_ok[X_ok["fecha"] <= v.fin_calibracion]
    val = X[(X["fecha"] > v.fin_calibracion) & (X["fecha"] <= v.fin_validacion) & X["ventas"].notna()]

    resultados: dict[str, ResultadoCandidato] = {}
    metadatos = {"ventanas": v.como_dict(), "n_entrenamiento": int(len(tr_b))}

    # ---- baseline: no se entrena, solo se calibran sus multiplicadores
    base = Baseline(metadatos=dict(metadatos))
    _, df_cal = evaluar(base, cal, costos)
    base.multiplicadores = calibrar_multiplicadores(df_cal, costos)
    m, df_val = evaluar(base, val, costos)
    resultados[base.nombre] = ResultadoCandidato(base, m, df_val)

    # ---- LightGBM
    modelo_a = ModeloLGBM().ajustar(tr_a, semilla=semilla)
    _, df_cal = evaluar(modelo_a, cal, costos)
    k = calibrar_multiplicadores(df_cal, costos)
    modelo_b = ModeloLGBM(multiplicadores=k, metadatos=dict(metadatos)).ajustar(tr_b, semilla=semilla)
    m, df_val = evaluar(modelo_b, val, costos)
    resultados[modelo_b.nombre] = ResultadoCandidato(modelo_b, m, df_val)

    # ---- Ensamble LightGBM + log-lineal (reutiliza los LightGBM A y B ya entrenados)
    ens_a = ModeloEnsamble(lgbm=modelo_a, loglineal=ModeloLogLineal().ajustar(tr_a))
    _, df_cal = evaluar(ens_a, cal, costos)
    ens_b = ModeloEnsamble(lgbm=modelo_b, loglineal=ModeloLogLineal().ajustar(tr_b),
                           multiplicadores=calibrar_multiplicadores(df_cal, costos), metadatos=dict(metadatos))
    m, df_val = evaluar(ens_b, val, costos)
    resultados[ens_b.nombre] = ResultadoCandidato(ens_b, m, df_val)
    return resultados, v, X
