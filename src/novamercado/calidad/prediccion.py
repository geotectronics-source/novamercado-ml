"""Limpieza de ``POST /v1/prediccion``.

Política (resumen; detalle y justificación en DECISIONES.md):

| Problema                                   | Política  |
|--------------------------------------------|-----------|
| cuerpo no es objeto / falta campo obligatorio | rechazar |
| nombre de campo sinónimo o con otro formato  | reparar   |
| nombre de campo parecido (error tipográfico) | advertir  |
| campo desconocido                            | advertir (se ignora) |
| tienda como texto/prefijo/nombre             | reparar   |
| tienda inexistente o ininterpretable         | rechazar  |
| fecha en otro formato inequívoco             | reparar   |
| fecha ambigua (dd/mm vs mm/dd)               | advertir (convención dd/mm) |
| fecha inválida / antes de apertura           | rechazar  |
| fecha sin cobertura de feriados              | advertir  |
| familia escrita de otra forma                | reparar   |
| familia parecida                             | advertir  |
| familia desconocida                          | advertir (se omite) |
| ninguna familia válida                       | rechazar  |
| familia repetida (mismos valores)            | reparar (se deduplica) |
| familia repetida (valores distintos)         | advertir (se usa la última) |
| promoción como texto o decimal entero        | reparar   |
| promoción ausente/negativa/ininterpretable   | advertir (se asume 0) |
| promoción decimal no entera                  | advertir (se redondea) |
| faltan familias del catálogo                 | advertir (se pronostican con promoción 0) |
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..catalogos import Catalogos
from ..contrato import SolicitudPrediccion
from .comun import (SIN_FAMILIA, SIN_FECHA, SIN_TIENDA, exigir_objeto, familia_de_item, limpiar_fecha,
                    limpiar_tienda, lista_de_items)
from .normalizacion import mapear_campos
from .parsers import interpretar_conteo
from .reporte import Rechazo, Reporte

ESQUEMA = {
    "tienda_id": SIN_TIENDA,
    "fecha": SIN_FECHA,
    "familias": {"familia", "items", "productos", "lineas", "detalle", "familias_producto", "categorias",
                 "families", "lista_familias", "pronosticos", "solicitudes"},
}
ESQUEMA_ITEM = {
    "familia_id": SIN_FAMILIA,
    "en_promocion": {"promocion", "promociones", "en_promo", "promo", "promos", "productos_en_promocion",
                     "num_promocion", "cantidad_promocion", "on_promotion", "onpromotion",
                     "en_promociones", "items_en_promocion"},
}


@dataclass
class PrediccionLimpia:
    solicitud: SolicitudPrediccion
    reporte: Reporte
    promociones_supuestas: set[str] = field(default_factory=set)


def limpiar_prediccion(cuerpo: Any, cat: Catalogos) -> PrediccionLimpia:
    reporte = Reporte()
    obj = exigir_objeto(cuerpo)
    campos = mapear_campos(obj, ESQUEMA, "", reporte, obligatorios={"tienda_id", "fecha", "familias"})
    tienda_id = limpiar_tienda(campos["tienda_id"], cat, reporte)
    fecha = limpiar_fecha(campos["fecha"], tienda_id, cat, reporte)
    _, fin_feriados = cat.cobertura_feriados
    if fecha > fin_feriados:
        reporte.advertir("fecha", f"{fecha} está fuera de la cobertura de feriados.csv (hasta {fin_feriados}); "
                                  "se supuso que no es feriado")

    items = lista_de_items(campos["familias"], "familias", "en_promocion", reporte)
    elegidas: dict[str, tuple[int, int, bool]] = {}  # familia → (en_promocion, índice, supuesta)
    for i, item in enumerate(items):
        ruta = f"familias[{i}]"
        if isinstance(item, str):
            item = {"familia_id": item}
            reporte.reparar(ruta, "el elemento era solo el nombre de la familia; se convirtió a objeto")
        if not isinstance(item, dict):
            reporte.advertir(ruta, f"elemento {item!r} no es un objeto; se omitió")
            continue
        try:
            c = mapear_campos(item, ESQUEMA_ITEM, ruta, reporte, obligatorios={"familia_id"})
        except Rechazo as r:
            reporte.advertir(r.campo or ruta, f"{r.detalle}; se omitió el elemento")
            continue
        familia = familia_de_item(c["familia_id"], f"{ruta}.familia_id", cat, reporte)
        if familia is None:
            continue
        promo, supuesta = _promocion(c, f"{ruta}.en_promocion", reporte)
        if familia in elegidas:
            previa, j, _ = elegidas[familia]
            if previa == promo:
                reporte.reparar(ruta, f"familia '{familia}' repetida (igual a familias[{j}]); se eliminó el duplicado")
                continue
            reporte.advertir(ruta, f"familia '{familia}' repetida con en_promocion distinto "
                                   f"({previa} en familias[{j}] vs {promo}); se usó el último valor")
        elegidas[familia] = (promo, i, supuesta)

    if not elegidas:
        raise Rechazo("ninguna familia de la solicitud es válida", campo="familias")

    faltantes = [f for f in cat.ids_familias if f not in elegidas]
    if faltantes:
        reporte.advertir("familias", f"faltan {len(faltantes)} familias que la tienda vende ({', '.join(faltantes)}); "
                                     "se pronosticaron suponiendo en_promocion = 0")
        for f in faltantes:
            elegidas[f] = (0, -1, True)

    try:
        solicitud = SolicitudPrediccion(
            tienda_id=tienda_id, fecha=fecha,
            familias=[{"familia_id": f, "en_promocion": p} for f, (p, _, _) in elegidas.items()],
        )
    except ValidationError as e:  # defensa en profundidad: no debería ocurrir
        raise Rechazo(f"la solicitud no cumple el contrato tras la limpieza: {e.errors()[0]['msg']}") from e
    return PrediccionLimpia(solicitud, reporte, {f for f, (_, _, s) in elegidas.items() if s})


def _promocion(c: dict, ruta: str, reporte: Reporte) -> tuple[int, bool]:
    if "en_promocion" not in c or c["en_promocion"] is None:
        reporte.advertir(ruta, "en_promocion ausente; se asumió 0")
        return 0, True
    r = interpretar_conteo(c["en_promocion"], "en_promocion")
    if r.valor is None:
        reporte.advertir(ruta, f"{r.detalle}; se asumió 0")
        return 0, True
    reporte.agregar(ruta, r.accion, r.detalle)
    return r.valor, False
