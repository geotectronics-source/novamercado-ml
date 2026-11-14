"""Reglas compartidas entre predicción y observaciones."""
from __future__ import annotations

from datetime import date
from typing import Any

from ..catalogos import Catalogos
from .parsers import interpretar_familia, interpretar_fecha, interpretar_tienda
from .reporte import Rechazo, Reporte

SIN_TIENDA = {"tienda", "id_tienda", "tiendaid", "store", "store_id", "storeid", "codigo_tienda",
              "cod_tienda", "sucursal", "sucursal_id", "id_sucursal", "tienda_codigo", "no_tienda",
              "numero_tienda", "tienda_no"}
SIN_FECHA = {"fecha_pronostico", "fecha_prediccion", "fecha_venta", "fecha_ventas", "fecha_observacion",
             "dia", "date", "day", "fecha_dia"}
SIN_FAMILIA = {"familia", "id_familia", "familiaid", "family", "family_id", "categoria", "categoria_id",
               "nombre_familia", "familia_nombre", "linea", "departamento"}


def exigir_objeto(cuerpo: Any) -> dict:
    if not isinstance(cuerpo, dict):
        raise Rechazo("el cuerpo de la solicitud debe ser un objeto JSON")
    return cuerpo


def limpiar_tienda(valor: Any, cat: Catalogos, reporte: Reporte) -> int:
    nombres = dict(zip(cat.tiendas["tienda_id"], cat.tiendas["nombre"]))
    r = interpretar_tienda(valor, nombres)
    if r.valor is None:
        raise Rechazo(r.detalle, campo="tienda_id")
    if r.valor not in nombres:
        raise Rechazo(f"la tienda {r.valor} no existe en el catálogo (válidas: {sorted(nombres)})",
                      campo="tienda_id")
    reporte.agregar("tienda_id", r.accion, r.detalle)
    return r.valor


def limpiar_fecha(valor: Any, tienda_id: int, cat: Catalogos, reporte: Reporte) -> date:
    r = interpretar_fecha(valor)
    if r.valor is None:
        raise Rechazo(r.detalle, campo="fecha")
    apertura = cat.fecha_apertura(tienda_id)
    if r.valor < apertura:
        raise Rechazo(f"la tienda {tienda_id} abrió el {apertura}; no hay operación el {r.valor}", campo="fecha")
    reporte.agregar("fecha", r.accion, r.detalle)
    return r.valor


def lista_de_items(valor: Any, nombre: str, campo_valor: str, reporte: Reporte) -> list:
    """Acepta lista de objetos; un objeto {familia: valor} se repara a lista."""
    if isinstance(valor, list) and valor:
        return valor
    if isinstance(valor, dict) and valor:
        reporte.reparar(nombre, f"'{nombre}' llegó como objeto {{familia: valor}}; se convirtió a lista")
        return [{"familia_id": k, campo_valor: v} for k, v in valor.items()]
    raise Rechazo(f"'{nombre}' debe ser una lista no vacía", campo=nombre)


def familia_de_item(valor: Any, ruta: str, cat: Catalogos, reporte: Reporte) -> str | None:
    familias = dict(zip(cat.familias["familia_id"], cat.familias["nombre"]))
    r = interpretar_familia(valor, familias)
    if r.valor is None:
        reporte.advertir(ruta, f"{r.detalle}; se omitió el elemento")
        return None
    reporte.agregar(ruta, r.accion, r.detalle)
    return r.valor
