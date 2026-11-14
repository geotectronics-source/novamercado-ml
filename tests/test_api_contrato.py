"""Pruebas del contrato HTTP (Anexo) con TestClient y dobles de prueba: sin MLflow ni BD."""
from .conftest import ModeloFijo, observacion_valida, solicitud_valida

CAMPOS_PREDICCION = {"tienda_id", "fecha", "version_modelo", "predicciones", "calidad"}


def test_prediccion_valida_cumple_contrato(cliente, deps):
    r = cliente.post("/v1/prediccion", json=solicitud_valida())
    assert r.status_code == 200
    cuerpo = r.json()
    assert CAMPOS_PREDICCION <= set(cuerpo)
    assert cuerpo["tienda_id"] == 5 and cuerpo["fecha"] == "2026-01-05"
    assert isinstance(cuerpo["version_modelo"], str) and cuerpo["version_modelo"] == "3"
    assert cuerpo["calidad"] == {"estado": "ok", "observaciones": []}
    assert len(cuerpo["predicciones"]) == 12
    for p in cuerpo["predicciones"]:
        assert {"familia_id", "venta_esperada", "cantidad_sugerida"} <= set(p)
        assert isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0
        assert isinstance(p["venta_esperada"], float)
    # se registró la predicción con la versión del modelo
    assert len(deps.repo.predicciones) == 12 and deps.repo.predicciones[0]["version"] == "3"


def test_prediccion_respeta_orden_de_familias(cliente):
    s = solicitud_valida()
    s["familias"] = list(reversed(s["familias"]))
    r = cliente.post("/v1/prediccion", json=s).json()
    assert [p["familia_id"] for p in r["predicciones"]] == [f["familia_id"] for f in s["familias"]]


def test_prediccion_corregida_informa_observaciones(cliente):
    s = solicitud_valida()
    s["tienda_id"] = "T05"
    s["familias"][2]["familia_id"] = "LÁCTEOS"
    cuerpo = cliente.post("/v1/prediccion", json=s).json()
    assert cuerpo["calidad"]["estado"] == "corregido"
    obs = cuerpo["calidad"]["observaciones"]
    assert {"campo": "familias[2].familia_id", "accion": "reparar"}.items() <= obs[1].items()
    assert all(set(o) == {"campo", "accion", "detalle"} for o in obs)


def test_prediccion_con_advertencia(cliente):
    s = solicitud_valida()
    s["familias"] = s["familias"][:10]
    cuerpo = cliente.post("/v1/prediccion", json=s).json()
    assert cuerpo["calidad"]["estado"] == "advertencia"
    assert len(cuerpo["predicciones"]) == 12
    supuestas = [p["familia_id"] for p in cuerpo["predicciones"] if p["promocion_supuesta"]]
    assert sorted(supuestas) == ["bebe", "mascotas"]


def test_rechazo_responde_422_con_detail(cliente, deps):
    s = solicitud_valida()
    s["tienda_id"] = 99
    r = cliente.post("/v1/prediccion", json=s)
    assert r.status_code == 422
    assert "detail" in r.json() and "99" in r.json()["detail"]
    assert deps.repo.solicitudes[-1]["codigo"] == 422


def test_json_invalido_responde_422(cliente):
    r = cliente.post("/v1/prediccion", content=b"{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_fecha_sin_historia_previa_se_rechaza(cliente):
    r = cliente.post("/v1/prediccion", json=solicitud_valida(fecha="2024-06-01"))
    assert r.status_code == 422


def test_misma_fecha_puede_pedirse_dos_veces(cliente):
    a = cliente.post("/v1/prediccion", json=solicitud_valida()).json()
    b = cliente.post("/v1/prediccion", json=solicitud_valida()).json()
    assert a["predicciones"] == b["predicciones"]


def test_sin_modelo_responde_503(cliente, deps):
    deps.modelo = ModeloFijo(None)
    assert cliente.post("/v1/prediccion", json=solicitud_valida()).status_code == 503
    assert cliente.get("/health").status_code == 503
    assert cliente.get("/modelo").status_code == 503


# ----------------------------------------------------------------- observaciones
def test_observaciones_idempotentes(cliente):
    r1 = cliente.post("/v1/observaciones", json=observacion_valida())
    assert r1.status_code == 200
    assert r1.json() == {"registros_guardados": 12, "calidad": {"estado": "ok", "observaciones": []}}
    r2 = cliente.post("/v1/observaciones", json=observacion_valida())  # E09
    assert r2.json()["registros_guardados"] == 0
    assert r2.json()["calidad"]["estado"] == "ok"


def test_observacion_modificada_cuenta_y_advierte(cliente):
    cliente.post("/v1/observaciones", json=observacion_valida())
    o = observacion_valida()
    o["ventas"][0]["ventas"] = 999
    r = cliente.post("/v1/observaciones", json=o).json()
    assert r["registros_guardados"] == 1
    assert r["calidad"]["estado"] == "advertencia"


def test_observaciones_alimentan_la_siguiente_prediccion(cliente, deps):
    o = observacion_valida(fecha="2026-01-04")
    cliente.post("/v1/observaciones", json=o)
    assert (5, "abarrotes", __import__("datetime").date(2026, 1, 4)) in deps.repo.observaciones
    assert cliente.post("/v1/prediccion", json=solicitud_valida(fecha="2026-01-05")).status_code == 200


# ----------------------------------------------------------------- administración y salud
def test_reentrenar_flujo(cliente, deps):
    r = cliente.post("/admin/reentrenar")
    assert r.status_code == 202 and isinstance(r.json()["id"], str)
    rid = r.json()["id"]
    assert cliente.get(f"/admin/reentrenar/{rid}").json() == {"estado": "en_curso"}
    deps.repo.finalizar_reentrenamiento(rid, "exitoso", True, "4", "Costo en validación 1 vs 2 del vigente")
    estado = cliente.get(f"/admin/reentrenar/{rid}").json()
    assert estado == {"estado": "exitoso", "promovido": True, "version": "4",
                      "motivo": "Costo en validación 1 vs 2 del vigente"}


def test_reentrenamiento_fallido_no_cambia_modelo(cliente, deps):
    rid = cliente.post("/admin/reentrenar").json()["id"]
    deps.airflow.estados[rid] = "failed"
    estado = cliente.get(f"/admin/reentrenar/{rid}").json()
    assert estado["estado"] == "fallido" and estado["promovido"] is False and estado["version"] == "3"
    assert cliente.get("/modelo").json()["version"] == "3"


def test_reentrenar_sin_airflow_responde_503(cliente, deps):
    deps.airflow.caido = True
    assert cliente.post("/admin/reentrenar").status_code == 503


def test_id_desconocido_404(cliente):
    assert cliente.get("/admin/reentrenar/no-existe").status_code == 404


def test_modelo_vigente(cliente, cfg):
    assert cliente.get("/modelo").json() == {"nombre": cfg.nombre_modelo, "alias": cfg.alias_modelo, "version": "3"}


def test_health_ok_y_degradado(cliente, deps):
    r = cliente.get("/health")
    assert r.status_code == 200 and r.json()["estado"] == "ok"
    deps.monitor.estado = {"mlflow": "no disponible (ConnectionError)", "airflow": "ok"}
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "degradado" and "mlflow" in r.json()["motivo"]
    # La API sigue pronosticando con el modelo cargado aunque MLflow esté caído
    assert cliente.post("/v1/prediccion", json=solicitud_valida()).status_code == 200
