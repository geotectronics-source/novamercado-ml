"""Limpieza de ``POST /v1/observaciones``.

Principio: una observación es la **verdad** con la que se entrena el modelo; es preferible
perder un registro que guardar un número inventado. Por eso, a diferencia de la
predicción, un valor dudoso se **descarta** (con advertencia) en lugar de suponerse.

| Problema                                        | Política  |
|-------------------------------------------------|-----------|
| tienda/fecha/nombres de campo                   | igual que en predicción |
| ventas con separador de miles o coma decimal     | reparar   |
| ventas como texto o decimal entero               | reparar   |
| ventas decimal no entera                         | advertir (se redondea) |
| ventas negativas (devoluciones)                  | advertir (no se guarda ese registro) |
| ventas ausentes, ambiguas o ininterpretables     | advertir (no se guarda ese registro) |
| familia desconocida                              | advertir (no se guarda) |
| familia repetida igual / distinta                | reparar / advertir (se usa la última) |
| ningún registro válido                           | rechazar  |
| envío repetido idéntico                          | idempotente: 200, registros_guardados = 0 |
| envío repetido con otro valor                    | se actualiza y se advierte (lo hace la capa de persistencia) |
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..catalogos import Catalogos
from ..contrato import SolicitudObservaciones
from .comun import (SIN_FAMILIA, SIN_FECHA, SIN_TIENDA, exigir_objeto, familia_de_item, limpiar_fecha,
                    limpiar_tienda, lista_de_items)
from .normalizacion import mapear_campos
from .parsers import interpretar_conteo
from .reporte import Rechazo, Reporte

ESQUEMA = {
    "tienda_id": SIN_TIENDA,
    "fecha": SIN_FECHA,
    "ventas": {"ventas_reales", "observaciones", "items", "detalle", "familias", "sales", "registros",
               "lineas", "productos"},
}
ESQUEMA_ITEM = {
    "familia_id": SIN_FAMILIA,
    "ventas": {"venta", "ventas_reales", "venta_real", "unidades", "unidades_vendidas", "cantidad", "sales",
               "real", "valor", "total"},
}


@dataclass
class ObservacionesLimpias:
    solicitud: SolicitudObservaciones
    reporte: Reporte


def limpiar_observaciones(cuerpo: Any, cat: Catalogos) -> ObservacionesLimpias:
    reporte = Reporte()
    obj = exigir_objeto(cuerpo)
    campos = mapear_campos(obj, ESQUEMA, "", reporte, obligatorios={"tienda_id", "fecha", "ventas"})
    tienda_id = limpiar_tienda(campos["tienda_id"], cat, reporte)
    fecha = limpiar_fecha(campos["fecha"], tienda_id, cat, reporte)
    items = lista_de_items(campos["ventas"], "ventas", "ventas", reporte)

    elegidas: dict[str, tuple[int, int]] = {}
    for i, item in enumerate(items):
        ruta = f"ventas[{i}]"
        if not isinstance(item, dict):
            reporte.advertir(ruta, f"elemento {item!r} no es un objeto; no se guardó")
            continue
        try:
            c = mapear_campos(item, ESQUEMA_ITEM, ruta, reporte, obligatorios={"familia_id", "ventas"})
        except Rechazo as r:
            reporte.advertir(r.campo or ruta, f"{r.detalle}; no se guardó el registro")
            continue
        familia = familia_de_item(c["familia_id"], f"{ruta}.familia_id", cat, reporte)
        if familia is None:
            continue
        r = interpretar_conteo(c["ventas"], "ventas")
        if r.valor is None:
            reporte.advertir(f"{ruta}.ventas", f"{r.detalle}; no se guardó el registro de '{familia}'")
            continue
        reporte.agregar(f"{ruta}.ventas", r.accion, r.detalle)
        if familia in elegidas:
            previa, j = elegidas[familia]
            if previa == r.valor:
                reporte.reparar(ruta, f"familia '{familia}' repetida (igual a ventas[{j}]); se eliminó el duplicado")
                continue
            reporte.advertir(ruta, f"familia '{familia}' repetida con ventas distintas "
                                   f"({previa} en ventas[{j}] vs {r.valor}); se usó el último valor")
        elegidas[familia] = (r.valor, i)

    if not elegidas:
        raise Rechazo("la solicitud no contiene ningún registro de ventas válido", campo="ventas")
    try:
        solicitud = SolicitudObservaciones(
            tienda_id=tienda_id, fecha=fecha,
            ventas=[{"familia_id": f, "ventas": v} for f, (v, _) in elegidas.items()],
        )
    except ValidationError as e:
        raise Rechazo(f"la solicitud no cumple el contrato tras la limpieza: {e.errors()[0]['msg']}") from e
    return ObservacionesLimpias(solicitud, reporte)
