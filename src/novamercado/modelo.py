"""Modelos de pronóstico.

* ``Baseline``: ingenuo estacional = promedio del mismo día de la semana en las últimas
  4 semanas (con respaldo al nivel reciente). Simple, explicable, difícil de superar mal.
* ``ModeloLGBM``: LightGBM global (todas las tiendas y familias) que predice el **cociente**
  ventas / nivel_reciente. Predecir un cociente hace al modelo robusto a cambios de nivel
  de la demanda: si una tienda crece 20 %, el nivel reciente lo refleja y el árbol no
  necesita extrapolar.
* ``ModeloLogLineal``: regresión log-lineal regularizada (modelo multiplicativo con interacciones).
* ``ModeloEnsamble``: promedio geométrico de LightGBM y log-lineal (retador en cada reentrenamiento).

Todos producen ``esperado`` y, con los multiplicadores calibrados por costo, la
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


# --------------------------------------------------------------------------- modelo log-lineal
# Interacciones categóricas que el análisis de datos mostró relevantes (docs/ANALISIS_MODELOS.md):
# el patrón semanal cambia por tipo de tienda y familia, el día del mes por tipo de tienda, etc.
INTERACCIONES = {
    "serie": ["tienda_id", "familia_id"],
    "tipo_fam_dow": ["tipo_tienda", "familia_id", "dow"],
    "tienda_dow": ["tienda_id", "dow"],
    "tipo_dia_mes": ["tipo_tienda", "dia_mes"],
    "fam_mes": ["familia_id", "mes"],
    "fam_feriado": ["familia_id", "es_feriado"],
    "fam_comercial": ["familia_id", "es_comercial"],
    "fam_pago": ["familia_id", "es_pago"],
    "fam_medio_dia": ["familia_id", "es_medio_dia"],
    "dias_a_feriado": ["dias_a_feriado"],
    "dias_desde_feriado": ["dias_desde_feriado"],
    "fam_promo_sn": ["familia_id", "promo_sn"],
}
RELATIVAS_LOG = ["rel_media_dow", "rel_lag1", "rel_media7", "estacional_anual"]


def _diseno_categorico(X: pd.DataFrame) -> pd.DataFrame:
    p = X["en_promocion"]
    columnas = {c: X[c].astype(str).values for c in {c for cs in INTERACCIONES.values() for c in cs} if c in X}
    # promoción desconocida (días observados sin solicitud) es su propia categoría
    columnas["promo_sn"] = np.where(p.isna(), "?", np.where(p.fillna(0) > 0, "1", "0"))
    d = {}
    for nombre, cols in INTERACCIONES.items():
        valor = columnas[cols[0]].astype(object)
        for c in cols[1:]:
            valor = valor + "|" + columnas[c]
        d[nombre] = valor
    return pd.DataFrame(d, index=X.index)


@dataclass
class ModeloLogLineal(Pronosticador):
    """Regresión log-lineal regularizada (Ridge) = modelo multiplicativo:

        log(1 + ventas) − log(1 + nivel) = Σ efectos(tienda×familia, tipo×familia×día, …)
                                          + Σ_f β_f · log(1 + promoción) + rezagos relativos (log)

    Al ser lineal en escala log, **extrapola** efectos (promociones, cambios de nivel) que los
    árboles no pueden; por eso complementa bien a LightGBM en el ensamble.
    """
    nombre: str = "loglineal_ridge"
    alpha: float = 3.0
    codificador: object = None
    regresion: object = None
    varianza_residual: float = 0.0
    familias: list = field(default_factory=list)

    def _matriz(self, X: pd.DataFrame):
        from scipy import sparse

        fam = X["familia_id"].astype(str).values
        promo = np.log1p(X["en_promocion"].fillna(0).values)
        numericas = [promo * (fam == f) for f in self.familias]  # pendiente de promoción por familia
        for c in RELATIVAS_LOG:
            numericas += [np.log(X[c].clip(0.05, 20)).fillna(0).values, X[c].isna().astype(float).values]
        return sparse.hstack([self.codificador.transform(_diseno_categorico(X)),
                              sparse.csr_matrix(np.column_stack(numericas))]).tocsr()

    def ajustar(self, X: pd.DataFrame) -> "ModeloLogLineal":
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import OneHotEncoder

        X = X[X["ventas"].notna() & (X["base"] > 0)]
        self.familias = sorted(X["familia_id"].astype(str).unique())
        self.codificador = OneHotEncoder(handle_unknown="ignore", min_frequency=5).fit(_diseno_categorico(X))
        y = np.log1p(X["ventas"].values) - np.log1p(X["base"].values)
        M = self._matriz(X)
        self.regresion = Ridge(alpha=self.alpha).fit(M, y, sample_weight=np.sqrt(X["base"].values))
        self.varianza_residual = float(np.var(y - self.regresion.predict(M)))
        return self

    def esperado(self, X: pd.DataFrame) -> np.ndarray:
        log_pred = self.regresion.predict(self._matriz(X)) + np.log1p(X["base"].values)
        e = np.expm1(log_pred + self.varianza_residual / 2)  # corrección de sesgo log-normal
        return np.where(np.isfinite(e), np.maximum(e, 0), _respaldo(X, "media_dow", "base"))


@dataclass
class ModeloEnsamble(Pronosticador):
    """Promedio geométrico de LightGBM (no lineal) y log-lineal (extrapola).

    Combina dos modelos de naturaleza distinta: en el backtest ganó en los cortes de diciembre
    y del periodo más reciente (docs/ANALISIS_MODELOS.md). Tiene sus propios multiplicadores.
    """
    nombre: str = "ensamble_lgbm_loglineal"
    lgbm: ModeloLGBM | None = None
    loglineal: ModeloLogLineal | None = None

    def esperado(self, X: pd.DataFrame) -> np.ndarray:
        a = np.maximum(self.lgbm.esperado(X), 0)
        b = np.maximum(self.loglineal.esperado(X), 0)
        return np.sqrt(a * b)
