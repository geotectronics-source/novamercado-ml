"""Variables sin fuga de información, métrica de costo, cantidad sugerida y criterio de reemplazo."""
import numpy as np
import pandas as pd
import pytest

from novamercado import ciclo
from novamercado.costos import costo_filas, mejor_multiplicador, redondear_sugerido
from novamercado.entrenamiento import entrenar_candidatos
from novamercado.features import construir_features

from .conftest import historia_sintetica


def test_features_no_usan_el_futuro(cat):
    h = historia_sintetica(cat)
    dia = pd.Timestamp("2025-10-15")
    a = construir_features(h, cat)
    h2 = h.copy()
    h2.loc[h2["fecha"] >= dia, "ventas"] *= 10  # alterar el día objetivo y el futuro
    b = construir_features(h2, cat)
    cols = ["base", "rel_lag1", "rel_lag7", "rel_media_dow", "media_dow", "dias_sin_obs"]
    fa = a[a["fecha"] == dia].sort_values(["tienda_id", "familia_id"])[cols].reset_index(drop=True)
    fb = b[b["fecha"] == dia].sort_values(["tienda_id", "familia_id"])[cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(fa, fb)


def test_nivel_conocido_cuando_faltan_observaciones_recientes(cat):
    h = historia_sintetica(cat)
    h = h[h["fecha"] <= "2025-10-01"]
    obj = pd.DataFrame({"fecha": pd.Timestamp("2025-11-01"), "tienda_id": 5, "familia_id": ["abarrotes"],
                        "en_promocion": [0.0], "ventas": [np.nan]})
    X = construir_features(pd.concat([h, obj]), cat)
    fila = X[X["fecha"] == "2025-11-01"].iloc[0]
    assert fila["base"] > 0 and fila["dias_sin_obs"] == 31


def test_costo_asimetrico():
    assert costo_filas([10], [8], 1.0, 2.0)[0] == 2.0  # faltan 2 a costo 1
    assert costo_filas([10], [13], 1.0, 2.0)[0] == 6.0  # sobran 3 a costo 2


def test_multiplicador_sigue_el_cuantil_critico():
    rng = np.random.default_rng(1)
    real = rng.normal(100, 20, 5000)
    esperado = np.full(5000, 100.0)
    k_caro_faltar = mejor_multiplicador(real, esperado, c_falt=2.0, c_sobr=0.1)  # τ≈0.95 ⇒ k≈1.33
    k_caro_sobrar = mejor_multiplicador(real, esperado, c_falt=1.0, c_sobr=2.5)  # τ≈0.29 ⇒ k≈0.89
    assert 1.25 < k_caro_faltar < 1.40
    assert 0.83 < k_caro_sobrar < 0.94


def test_sugerido_entero_no_negativo():
    s = redondear_sugerido([-3.2, 0.4, 7.6, np.nan])
    assert s.tolist() == [0, 0, 8, 0] and s.dtype.kind == "i"


def test_lightgbm_mejora_al_baseline_en_datos_sinteticos(cat):
    res, ventanas, _ = entrenar_candidatos(historia_sintetica(cat), cat)
    assert set(res) == {"baseline_estacional", "lightgbm_cociente"}
    for r in res.values():
        assert np.isfinite(r.metricas_validacion["costo_total"])
    assert ventanas.fin_validacion == pd.Timestamp("2025-12-31")


@pytest.mark.parametrize("costo_cand, costo_vig, promueve", [(90.0, 100.0, True), (99.5, 100.0, False),
                                                              (120.0, 100.0, False), (50.0, None, True)])
def test_criterio_de_reemplazo(monkeypatch, cat, cfg, costo_cand, costo_vig, promueve):
    """El candidato reemplaza al vigente solo si mejora el costo ≥ 1 %."""
    class Falso:
        def __init__(self, costo):
            self.costo = costo

    monkeypatch.setattr(ciclo.registro, "cargar_version", lambda c, v: Falso(costo_cand if v == "9" else costo_vig))
    monkeypatch.setattr(ciclo.registro, "version_vigente", lambda c: None if costo_vig is None else "8")
    monkeypatch.setattr(ciclo, "evaluar", lambda m, X, c: ({"costo_total": m.costo}, None))
    monkeypatch.setattr(ciclo, "sanidad", lambda *a: (True, "ok"))
    h = historia_sintetica(cat)
    ent = {"version_candidata": "9", "costo_baseline": 200.0,
           "ventanas": {"fin_calibracion": "2025-12-03", "fin_validacion": "2025-12-31"}}
    dec = ciclo.decidir(h, cat, cfg, ent)
    assert dec["promover"] is promueve
    assert "Costo en validación" in dec["motivo"] or "No había" in dec["motivo"]
