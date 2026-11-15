"""Compara modelos candidatos con el MISMO protocolo y la MISMA métrica de costo que producción.

Candidatos:
  * lightgbm_cociente   — modelo actual (L2 sobre ventas / nivel reciente)
  * lightgbm_tweedie    — mismo modelo con pérdida Tweedie p=1.9 (casi Gamma, enlace log): ruido multiplicativo
  * loglineal_ridge     — (novamercado.modelo.ModeloLogLineal) regresión log-lineal regularizada (GLM multiplicativo) con
                          interacciones explícitas: tipo×familia×día de semana, día del mes×tipo,
                          promoción (log) por familia, feriados por familia, mes por familia
  * ensamble            — promedio geométrico de lightgbm_cociente y loglineal_ridge

Uso:  python scripts/comparar_modelos.py datos
Requiere scikit-learn (solo para este experimento).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from novamercado import entrenamiento as E  # noqa: E402
from novamercado.catalogos import Catalogos  # noqa: E402
from novamercado.costos import calibrar_multiplicadores  # noqa: E402
from novamercado.features import construir_features  # noqa: E402
from novamercado.modelo import (PARAMS_LGBM, Baseline, ModeloEnsamble, ModeloLGBM,  # noqa: E402
                                ModeloLogLineal, Pronosticador)

@dataclass
class LGBMCosto(Pronosticador):
    """Dos boosters: la media (L2, para ``venta_esperada``) y otro que minimiza DIRECTAMENTE el
    costo de negocio para ``cantidad_sugerida``.

    costo = c_f·max(y−s,0) + c_s·max(s−y,0) = (c_f + c_s) · pinball_τ(y, s),  τ = c_f/(c_f+c_s)

    Pérdida cuantílica (pinball) con τ distinto por fila (según su familia), en escala de
    cociente y ponderada por (c_f + c_s)·nivel ⇒ minimizar esta pérdida = minimizar el costo.
    """
    nombre: str = "lightgbm_costo"
    media: object = None
    cuantil: object = None
    tau: dict = field(default_factory=dict)
    peso_costo: dict = field(default_factory=dict)

    def ajustar(self, X: pd.DataFrame, semilla: int = 42) -> "LGBMCosto":
        import lightgbm as lgb

        from novamercado.features import VARIABLES, VARIABLES_CATEGORICAS

        self.media = ModeloLGBM().ajustar(X, semilla=semilla)
        X = X[X["ventas"].notna() & (X["base"] > 0)].copy()
        rng = np.random.default_rng(semilla)
        X.loc[rng.random(len(X)) < 0.1, "rel_lag1"] = np.nan
        fam = X["familia_id"].astype(str)
        tau = fam.map(self.tau).values
        w = (fam.map(self.peso_costo) * X["base"]).values
        y = (X["ventas"] / X["base"]).clip(upper=10).values

        def pinball(pred, ds):
            grad = np.where(y > pred, -tau, 1 - tau) * w
            return grad, w

        params = dict(PARAMS_LGBM, objective=pinball)
        ds = lgb.Dataset(X[VARIABLES], label=y, init_score=np.ones(len(X)),
                         categorical_feature=VARIABLES_CATEGORICAS, free_raw_data=False)
        self.cuantil = lgb.train(params, ds, num_boost_round=800)
        return self

    def esperado(self, X):
        return self.media.esperado(X)

    def sugerido(self, X, esperado):
        from novamercado.costos import redondear_sugerido
        from novamercado.features import VARIABLES

        q = (1.0 + self.cuantil.predict(X[VARIABLES])) * X["base"].values
        q = np.where(np.isfinite(q), q, np.asarray(esperado))
        return redondear_sugerido(q)


@dataclass
class LGBMCuantilNativo(Pronosticador):
    """Un LightGBM con objetivo ``quantile`` NATIVO (reajusta las hojas al cuantil) por cada τ
    distinto de ``costos.csv``; cada familia usa el modelo de su τ para ``cantidad_sugerida``."""
    nombre: str = "lightgbm_cuantil"
    media: object = None
    modelos: dict = field(default_factory=dict)
    tau: dict = field(default_factory=dict)

    def ajustar(self, X: pd.DataFrame, semilla: int = 42) -> "LGBMCuantilNativo":
        import lightgbm as lgb

        from novamercado.features import VARIABLES, VARIABLES_CATEGORICAS

        self.media = ModeloLGBM().ajustar(X, semilla=semilla)
        X = X[X["ventas"].notna() & (X["base"] > 0)].copy()
        X.loc[np.random.default_rng(semilla).random(len(X)) < 0.1, "rel_lag1"] = np.nan
        y = (X["ventas"] / X["base"]).clip(upper=10)
        ds = lgb.Dataset(X[VARIABLES], label=y, weight=X["base"].values,
                         categorical_feature=VARIABLES_CATEGORICAS, free_raw_data=False)
        for t in sorted(set(round(v, 4) for v in self.tau.values())):
            params = dict(PARAMS_LGBM, objective="quantile", alpha=t)
            self.modelos[t] = lgb.train(params, ds, num_boost_round=400)
        return self

    def esperado(self, X):
        return self.media.esperado(X)

    def sugerido(self, X, esperado):
        from novamercado.costos import redondear_sugerido
        from novamercado.features import VARIABLES

        q = np.asarray(esperado, dtype=float).copy()
        taus = X["familia_id"].astype(str).map(lambda f: round(self.tau[f], 4)).values
        for t, m in self.modelos.items():
            filas = taus == t
            if filas.any():
                q[filas] = m.predict(X.loc[filas, VARIABLES]) * X.loc[filas, "base"].values
        e = np.asarray(esperado, dtype=float)
        # La pérdida cuantílica es inestable en τ extremos (licores τ=0.95 llegó a ×90):
        # se acota a [0.5, 2.5]× la venta esperada como control de sanidad.
        q = np.clip(np.where(np.isfinite(q), q, e), 0.5 * e, 2.5 * e)
        return redondear_sugerido(q)


def fabricas(cat: Catalogos):
    gamma = dict(PARAMS_LGBM, objective="tweedie", tweedie_variance_power=1.9)
    c = cat.costos_dict()
    tau = {f: cf / (cf + cs) for f, (cf, cs) in c.items()}
    peso = {f: cf + cs for f, (cf, cs) in c.items()}
    return {
        "lightgbm_costo": lambda tr: LGBMCosto(tau=tau, peso_costo=peso).ajustar(tr),
        "lightgbm_cuantil": lambda tr: LGBMCuantilNativo(tau=tau).ajustar(tr),
        "baseline_estacional": lambda tr: Baseline(),
        "lightgbm_cociente": lambda tr: ModeloLGBM().ajustar(tr),
        "lightgbm_tweedie": lambda tr: ModeloLGBM(nombre="lightgbm_tweedie", params=gamma).ajustar(tr),
        "loglineal_ridge": lambda tr: ModeloLogLineal().ajustar(tr),
        "ensamble": lambda tr: ModeloEnsamble(lgbm=ModeloLGBM().ajustar(tr), loglineal=ModeloLogLineal().ajustar(tr)),
    }


def backtest(X: pd.DataFrame, cat: Catalogos, cortes: list[str]) -> pd.DataFrame:
    costos = cat.costos_dict()
    filas = []
    for corte in cortes:
        Xc = X[X["fecha"] <= corte]
        v = E.definir_ventanas(Xc)
        ok = E._filas_entrenables(Xc)
        tr_a, tr_b = ok[ok["fecha"] <= v.fin_entrenamiento_a], ok[ok["fecha"] <= v.fin_calibracion]
        cal = ok[(ok["fecha"] > v.fin_entrenamiento_a) & (ok["fecha"] <= v.fin_calibracion)]
        val = Xc[(Xc["fecha"] > v.fin_calibracion) & Xc["ventas"].notna()]
        for nombre, fabricar in fabricas(cat).items():
            t0 = time.time()
            _, df_cal = E.evaluar(fabricar(tr_a), cal, costos)       # calibración fuera de muestra
            modelo = fabricar(tr_b)
            modelo.multiplicadores = calibrar_multiplicadores(df_cal, costos)
            m, _ = E.evaluar(modelo, val, costos)
            filas.append({"corte": corte, "modelo": nombre, "costo": round(m["costo_total"]),
                          "wape": round(m["wape"], 4), "sesgo": round(m["sesgo_pct"], 4),
                          "segundos": round(time.time() - t0, 1)})
            print(filas[-1], flush=True)
    return pd.DataFrame(filas)


if __name__ == "__main__":
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "datos"
    cat = Catalogos.desde_csv(carpeta)
    hist = pd.read_csv(f"{carpeta}/historico_ventas.csv", parse_dates=["fecha"])
    X = construir_features(hist, cat)
    t = backtest(X, cat, ["2025-06-30", "2025-09-30", "2025-12-31", "2026-02-28"])
    pd.set_option("display.width", 200)
    print(t.pivot(index="modelo", columns="corte", values="costo"))
    resumen = t.groupby("modelo").agg(costo_medio=("costo", "mean"), wape_medio=("wape", "mean"),
                                      segundos=("segundos", "mean")).sort_values("costo_medio")
    ref = resumen.loc["lightgbm_cociente", "costo_medio"]
    resumen["vs_actual"] = (resumen["costo_medio"] / ref - 1).map("{:+.1%}".format)
    print(resumen.round(4))
    t.to_csv("evidencia/comparacion_modelos.csv", index=False)
