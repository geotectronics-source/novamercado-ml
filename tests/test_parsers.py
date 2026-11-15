"""Pruebas unitarias de los intérpretes generales (números, fechas, tiendas, familias)."""
from datetime import date

import pytest

from novamercado.calidad.parsers import (interpretar_conteo, interpretar_familia, interpretar_fecha,
                                         interpretar_numero, interpretar_tienda)
from novamercado.calidad.reporte import ADVERTIR, REPARAR


@pytest.mark.parametrize("entrada, valor, accion", [
    (5, 5.0, None),
    ("5", 5.0, REPARAR),
    (" 12 ", 12.0, REPARAR),
    (2.0, 2.0, REPARAR),
    ("1,234", 1234.0, REPARAR),          # E10: coma de miles
    ("812,0", 812.0, REPARAR),           # E10: coma decimal
    ("1,234,567", 1234567.0, REPARAR),
    ("1.234.567", 1234567.0, REPARAR),
    ("1.234,5", 1234.5, REPARAR),
    ("1 234", 1234.0, REPARAR),
    ("12.5", 12.5, REPARAR),
    ("1.234", None, None),               # ambiguo → no se interpreta
    ("abc", None, None),
    (True, None, None),
    (None, None, None),
    ([1], None, None),
])
def test_interpretar_numero(entrada, valor, accion):
    r = interpretar_numero(entrada)
    assert r.valor == valor
    if valor is not None:
        assert r.accion == accion


@pytest.mark.parametrize("entrada, valor, accion", [
    (3, 3, None), ("3", 3, REPARAR), (2.0, 2, REPARAR), (2.5, 3, ADVERTIR), ("812,0", 812, REPARAR),
    (-4, None, None), ("-4", None, None),
])
def test_interpretar_conteo(entrada, valor, accion):
    r = interpretar_conteo(entrada, "x")
    assert r.valor == valor
    assert r.accion == accion


@pytest.mark.parametrize("entrada, valor, accion", [
    ("2025-11-17", date(2025, 11, 17), None),
    (" 2025-11-17 ", date(2025, 11, 17), REPARAR),
    ("2025-11-17T00:00:00", date(2025, 11, 17), REPARAR),     # E04
    ("2025-11-17 08:30", date(2025, 11, 17), REPARAR),
    ("2025-11-17T00:00:00Z", date(2025, 11, 17), REPARAR),
    ("17/11/2025", date(2025, 11, 17), REPARAR),               # E04: día > 12 ⇒ inequívoco
    ("11/17/2025", date(2025, 11, 17), REPARAR),               # mes/día inequívoco
    ("03/04/2026", date(2026, 4, 3), ADVERTIR),                # ambiguo ⇒ convención dd/mm
    ("05/05/2026", date(2026, 5, 5), REPARAR),
    ("2025/11/17", date(2025, 11, 17), REPARAR),
    ("20251117", date(2025, 11, 17), REPARAR),
    (20251117, date(2025, 11, 17), REPARAR),
    ("17-11-25", date(2025, 11, 17), ADVERTIR),                # año de 2 dígitos
    ("17 de noviembre de 2025", date(2025, 11, 17), REPARAR),
    ("Nov 17, 2025", date(2025, 11, 17), REPARAR),
    ("2025-02-30", None, None),
    ("ayer", None, None),
    (None, None, None),
])
def test_interpretar_fecha(entrada, valor, accion):
    r = interpretar_fecha(entrada)
    assert r.valor == valor
    if valor is not None:
        assert r.accion == accion


TIENDAS = {1: "NovaMercado Zona 10", 2: "NovaMercado Mixco", 10: "NovaMercado Express Zona 16"}


@pytest.mark.parametrize("entrada, valor, accion", [
    (5, 5, None), ("5", 5, REPARAR), ("T05", 5, REPARAR), ("t-5", 5, REPARAR), ("Tienda 5", 5, REPARAR),
    (5.0, 5, REPARAR), ("NovaMercado Zona 10", 1, REPARAR), ("Mixco", 2, REPARAR),
    ("Express Zona 16", 10, REPARAR), (5.5, None, None), ("cinco", None, None), (True, None, None),
])
def test_interpretar_tienda(entrada, valor, accion):
    r = interpretar_tienda(entrada, TIENDAS)
    assert r.valor == valor
    if valor is not None:
        assert r.accion == accion


FAMILIAS = {"lacteos": "Lácteos", "frutas_verduras": "Frutas y verduras", "snacks": "Snacks y dulces",
            "panaderia": "Panadería", "cuidado_personal": "Cuidado personal", "bebidas": "Bebidas"}


@pytest.mark.parametrize("entrada, valor, accion", [
    ("lacteos", "lacteos", None),
    ("LÁCTEOS", "lacteos", REPARAR),            # E02
    ("lacteos ", "lacteos", REPARAR),           # E02
    ("Frutas y Verduras", "frutas_verduras", REPARAR),  # E02
    ("frutas-verduras", "frutas_verduras", REPARAR),
    ("Lácteo", "lacteos", REPARAR),             # singular
    ("cuidadoPersonal", "cuidado_personal", REPARAR),
    ("Snacks y Dulces", "snacks", REPARAR),
    ("panaderya", "panaderia", ADVERTIR),       # error tipográfico
    ("dulces", "snacks", ADVERTIR),             # palabra contenida en un único nombre
    ("electronica", None, None),
    (7, None, None),
])
def test_interpretar_familia(entrada, valor, accion):
    r = interpretar_familia(entrada, FAMILIAS)
    assert r.valor == valor
    if valor is not None:
        assert r.accion == accion
