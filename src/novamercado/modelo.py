"""Modelos de pronóstico.

* ``Baseline``: ingenuo estacional = promedio del mismo día de la semana en las últimas
  4 semanas (con respaldo al nivel reciente). Simple, explicable, difícil de superar mal.
* ``ModeloLGBM``: LightGBM global (todas las tiendas y familias) que predice el **cociente**
  ventas / nivel_reciente. Predecir un cociente hace al modelo robusto a cambios de nivel
  de la demanda: si una tienda crece 20 %, el nivel reciente lo refleja y el árbol no
  necesita extrapolar.

Ambos producen ``esperado`` y, con los multiplicadores calibrados por costo, la
``cantidad_sugerida``. El objeto completo se guarda en MLflow como modelo *pyfunc*.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costos import multiplicador_para, redondear_sugerido
from .features import VARIABLES, VARIABLES_CATEGORICAS

PARAMS_LGBM = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "seed": 42,
    "num_threads": 2,
}
N_ARBOLES = 600


@dataclass
class Pronosticador:
    """Interfaz común: ``esperado(X)`` y ``sugerido(X, esperado)``."""

    nombre: str
    multiplicadores: dict = field(default_factory=dict)
    metadatos: dict = field(default_factory=dict)

    def esperado(self, X: pd.DataFrame) -> np.ndarray:  # pragma: no cover - abstracto
        raise NotImplementedError

    def sugerido(self, X: pd.DataFrame, esperado: np.ndarray) -> np.ndarray:
        k = np.array([multiplicador_para(self.multiplicadores, str(f), str(t))
                      for f, t in zip(X["familia_id"], X["tipo_tienda"])])
        return redondear_sugerido(np.asarray(esperado) * k)

    def predecir(self, X: pd.DataFrame) -> pd.DataFrame:
        e = np.maximum(np.nan_to_num(self.esperado(X), nan=0.0), 0.0)
        return pd.DataFrame({"venta_esperada": np.round(e, 2), "cantidad_sugerida": self.sugerido(X, e)},
                            index=X.index)


def _respaldo(X: pd.DataFrame, *columnas) -> np.ndarray:
    out = pd.Series(np.nan, index=X.index)
    for c in columnas:
        out = out.fillna(X[c])
    return out.values.astype(float)


@dataclass
class Baseline(Pronosticador):
    nombre: str = "baseline_estacional"

    def esperado(self, X: pd.DataFrame) -> np.ndarray:
        return _respaldo(X, "media_dow", "base")


@dataclass
class ModeloLGBM(Pronosticador):
    nombre: str = "lightgbm_cociente"
    booster: object = None
    params: dict = field(default_factory=lambda: dict(PARAMS_LGBM))
    n_arboles: int = N_ARBOLES

    def ajustar(self, X: pd.DataFrame, semilla: int = 42, prob_ocultar_lag1: float = 0.1) -> "ModeloLGBM":
        import lightgbm as lgb

        X = X[X["ventas"].notna() & (X["base"] > 0)].copy()
        # Aumento de datos: a veces falta la observación de ayer en producción.
        rng = np.random.default_rng(semilla)
        ocultar = rng.random(len(X)) < prob_ocultar_lag1
        X.loc[ocultar, "rel_lag1"] = np.nan
        y = (X["ventas"] / X["base"]).clip(upper=10)
        ds = lgb.Dataset(X[VARIABLES], label=y, weight=X["base"].values,
                         categorical_feature=VARIABLES_CATEGORICAS, free_raw_data=False)
        self.booster = lgb.train(self.params, ds, num_boost_round=self.n_arboles)
        return self

    def esperado(self, X: pd.DataFrame) -> np.ndarray:
        cociente = self.booster.predict(X[VARIABLES])
        e = np.maximum(cociente, 0) * X["base"].values
        # Si no hay nivel conocido, no hay pronóstico posible: respaldo al baseline.
        return np.where(np.isfinite(e), e, _respaldo(X, "media_dow", "base"))
