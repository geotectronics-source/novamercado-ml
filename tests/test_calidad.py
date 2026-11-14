"""Política ante datos defectuosos: un caso por cada código del catálogo (E01–E10) y casos
fuera del catálogo para comprobar que las reglas son generales."""
import copy

import pytest

from novamercado.calidad import Rechazo, limpiar_observaciones, limpiar_prediccion

from .conftest import observacion_valida, solicitud_valida


def acciones(reporte):
    return [(o.campo, o.accion) for o in reporte.observaciones]


def test_prediccion_valida_queda_ok(cat):
    r = limpiar_prediccion(solicitud_valida(), cat)
    assert r.reporte.estado == "ok" and r.reporte.observaciones == []
    assert len(r.solicitud.familias) == 12


@pytest.mark.parametrize("tienda", ["T05", "5", "05", 5.0])
def test_E01_tienda_texto_se_repara(cat, tienda):
    s = solicitud_valida()
    s["tienda_id"] = tienda
    r = limpiar_prediccion(s, cat)
    assert r.solicitud.tienda_id == 5
    assert ("tienda_id", "reparar") in acciones(r.reporte)
    assert r.reporte.estado == "corregido"


def test_E02_familia_otra_forma_se_repara(cat):
    s = solicitud_valida()
    s["familias"][2]["familia_id"] = "LÁCTEOS"
    s["familias"][5]["familia_id"] = "Frutas y Verduras"
    r = limpiar_prediccion(s, cat)
    assert ("familias[2].familia_id", "reparar") in acciones(r.reporte)
    assert {f.familia_id for f in r.solicitud.familias} == set(cat.ids_familias)


def test_E03_promocion_texto_o_decimal(cat):
    s = solicitud_valida()
    s["familias"][0]["en_promocion"] = "3"
    s["familias"][1]["en_promocion"] = 2.0
    r = limpiar_prediccion(s, cat)
    promos = {f.familia_id: f.en_promocion for f in r.solicitud.familias}
    assert promos["abarrotes"] == 3 and promos["bebidas"] == 2
    assert r.reporte.estado == "corregido"


@pytest.mark.parametrize("fecha", ["2026-01-05T00:00:00", "15/01/2026", "2026/01/05"])
def test_E04_fecha_otro_formato(cat, fecha):
    s = solicitud_valida()
    s["fecha"] = fecha
    r = limpiar_prediccion(s, cat)
    assert ("fecha", "reparar") in acciones(r.reporte)


def test_E05_faltan_familias_se_completan_con_advertencia(cat):
    s = solicitud_valida()
    s["familias"] = s["familias"][:10]
    r = limpiar_prediccion(s, cat)
    assert r.reporte.estado == "advertencia"
    assert len(r.solicitud.familias) == 12
    assert r.promociones_supuestas == {"bebe", "mascotas"}


def test_E06_familia_repetida_valores_distintos_usa_ultimo(cat):
    s = solicitud_valida()
    s["familias"].append({"familia_id": "abarrotes", "en_promocion": 3})
    r = limpiar_prediccion(s, cat)
    assert r.reporte.estado == "advertencia"
    assert {f.familia_id: f.en_promocion for f in r.solicitud.familias}["abarrotes"] == 3


def test_familia_repetida_identica_se_deduplica(cat):
    s = solicitud_valida()
    s["familias"].append(copy.deepcopy(s["familias"][0]))
    r = limpiar_prediccion(s, cat)
    assert r.reporte.estado == "corregido" and len(r.solicitud.familias) == 12


@pytest.mark.parametrize("nombre", ["tienda", "store_id", "tiendaId", "Tienda_ID"])
def test_E07_campo_renombrado(cat, nombre):
    s = solicitud_valida()
    s[nombre] = s.pop("tienda_id")
    r = limpiar_prediccion(s, cat)
    assert r.solicitud.tienda_id == 5
    assert ("tienda_id", "reparar") in acciones(r.reporte)


def test_E08_ventas_negativas_no_se_guardan(cat):
    o = observacion_valida()
    o["ventas"][5]["ventas"] = -4
    r = limpiar_observaciones(o, cat)
    assert r.reporte.estado == "advertencia"
    assert "frutas_verduras" not in {v.familia_id for v in r.solicitud.ventas}


def test_E10_numero_con_formato(cat):
    o = observacion_valida()
    o["ventas"][1]["ventas"] = "1,292"
    o["ventas"][2]["ventas"] = "50,0"
    r = limpiar_observaciones(o, cat)
    v = {x.familia_id: x.ventas for x in r.solicitud.ventas}
    assert v["bebidas"] == 1292 and v["lacteos"] == 50
    assert r.reporte.estado == "corregido"


# ----------------------------------------------------------------- rechazos (422)
@pytest.mark.parametrize("mutar, texto", [
    (lambda s: s.pop("tienda_id"), "tienda_id"),
    (lambda s: s.update(tienda_id=99), "no existe"),
    (lambda s: s.update(fecha="2026-02-30"), "calendario"),
    (lambda s: s.update(fecha="mañana"), "fecha"),
    (lambda s: s.update(familias=[]), "lista"),
    (lambda s: s.update(familias=[{"familia_id": "electronica", "en_promocion": 1}]), "ninguna familia"),
])
def test_rechazos(cat, mutar, texto):
    s = solicitud_valida()
    mutar(s)
    with pytest.raises(Rechazo) as e:
        limpiar_prediccion(s, cat)
    assert texto in e.value.mensaje


def test_fecha_antes_de_apertura_se_rechaza(cat):
    with pytest.raises(Rechazo, match="abrió"):
        limpiar_prediccion(solicitud_valida(tienda=10, fecha="2025-01-01"), cat)


def test_cuerpo_no_objeto_se_rechaza(cat):
    with pytest.raises(Rechazo):
        limpiar_prediccion([1, 2, 3], cat)


# ----------------------------------------------------------------- fuera del catálogo
def test_problemas_no_catalogados(cat):
    s = {"Store_ID": "NovaMercado Mixco", "date": "11/17/2025", "origen": "pos-v2",
         "items": {"Lacteo": "2", "BEBIDAS": 1, "electronica": 4, "snacks": -1}}
    r = limpiar_prediccion(s, cat)
    assert r.solicitud.tienda_id == 2
    assert str(r.solicitud.fecha) == "2025-11-17"
    promos = {f.familia_id: f.en_promocion for f in r.solicitud.familias}
    assert promos["lacteos"] == 2 and promos["bebidas"] == 1 and promos["snacks"] == 0
    assert r.reporte.estado == "advertencia"  # campo desconocido, familia desconocida, promo negativa, faltantes
    campos = [o.campo for o in r.reporte.observaciones]
    assert "origen" in campos


def test_fecha_fuera_de_cobertura_de_feriados_advierte(cat):
    r = limpiar_prediccion(solicitud_valida(fecha="2027-03-01"), cat)
    assert ("fecha", "advertir") in acciones(r.reporte)


def test_observacion_ambigua_se_descarta(cat):
    o = observacion_valida()
    o["ventas"][0]["ventas"] = "1.234"
    r = limpiar_observaciones(o, cat)
    assert "abarrotes" not in {v.familia_id for v in r.solicitud.ventas}
    assert r.reporte.estado == "advertencia"


def test_observacion_sin_registros_validos_se_rechaza(cat):
    o = observacion_valida()
    o["ventas"] = [{"familia_id": "abarrotes", "ventas": -1}]
    with pytest.raises(Rechazo):
        limpiar_observaciones(o, cat)
