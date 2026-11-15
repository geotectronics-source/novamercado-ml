"""Intérpretes generales de valores: números, fechas, tiendas y familias.

Cada intérprete devuelve ``Interpretacion(valor, accion, detalle)``:
* ``accion is None``  → el valor ya cumplía el contrato.
* ``accion == 'reparar'``  → corrección inequívoca.
* ``accion == 'advertir'`` → se asumió algo (se explica en ``detalle``).
* ``valor is None``   → no se pudo interpretar (quien llama decide: rechazar u omitir).

Nunca se consulta el reloj del sistema: las fechas son simuladas.
"""
from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from .normalizacion import canonico, compacto, forma_flexible, sin_acentos, tokens
from .reporte import ADVERTIR, REPARAR


@dataclass
class Interpretacion:
    valor: Any
    accion: str | None = None
    detalle: str | None = None


# ---------------------------------------------------------------------------- números
_ENTERO = re.compile(r"^[+-]?\d+$")
_DECIMAL_PUNTO = re.compile(r"^[+-]?\d*\.\d+$")
_MILES_COMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")  # 1,234 / 1,234.5
_MILES_PUNTO_MULTI = re.compile(r"^[+-]?\d{1,3}(\.\d{3}){2,}(,\d+)?$")  # 1.234.567
_MILES_PUNTO_COMA_DEC = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+,\d+$")  # 1.234,5
_DECIMAL_COMA = re.compile(r"^[+-]?\d+,\d{1,2}$")  # 812,0 / 812,25
_AMBIGUO_PUNTO = re.compile(r"^[+-]?\d{1,3}\.\d{3}$")  # 1.234 → ¿mil doscientos o 1,234?
_MILES_ESPACIO = re.compile(r"^[+-]?\d{1,3}( \d{3})+$")


def interpretar_numero(valor: Any) -> Interpretacion:
    """Interpreta un número que puede venir como texto con separadores.

    Convención de Guatemala: punto decimal y coma de miles. Una coma seguida de exactamente
    3 dígitos es separador de miles; seguida de 1–2 dígitos es coma decimal. Un único
    grupo '1.234' es ambiguo y no se interpreta (no se inventan datos).
    """
    if isinstance(valor, bool) or valor is None:
        return Interpretacion(None, detalle=f"valor {valor!r} no es numérico")
    if isinstance(valor, int):
        return Interpretacion(float(valor))
    if isinstance(valor, float):
        if valor != valor or valor in (float("inf"), float("-inf")):
            return Interpretacion(None, detalle="valor no finito")
        return Interpretacion(valor, REPARAR, f"{valor!r} (decimal) se interpretó como número")
    if not isinstance(valor, str):
        return Interpretacion(None, detalle=f"tipo {type(valor).__name__} no es numérico")

    s = valor.strip().replace(" ", " ")
    s_sin_esp = s.replace(" ", "") if _MILES_ESPACIO.match(s) else s
    if _ENTERO.match(s_sin_esp):
        return Interpretacion(float(s_sin_esp), REPARAR, f"'{valor}' (texto) se interpretó como {int(s_sin_esp)}")
    if _AMBIGUO_PUNTO.match(s):
        return Interpretacion(None, detalle=f"'{valor}' es ambiguo (¿separador de miles o decimal?)")
    if _DECIMAL_PUNTO.match(s):
        return Interpretacion(float(s), REPARAR, f"'{valor}' (texto) se interpretó como {float(s)}")
    if _MILES_COMA.match(s):
        v = float(s.replace(",", ""))
        return Interpretacion(v, REPARAR, f"'{valor}' usa coma de miles; se interpretó como {_fmt(v)}")
    if _MILES_PUNTO_MULTI.match(s) or _MILES_PUNTO_COMA_DEC.match(s):
        v = float(s.replace(".", "").replace(",", "."))
        return Interpretacion(v, REPARAR, f"'{valor}' usa punto de miles; se interpretó como {_fmt(v)}")
    if _DECIMAL_COMA.match(s):
        v = float(s.replace(",", "."))
        return Interpretacion(v, REPARAR, f"'{valor}' usa coma decimal; se interpretó como {_fmt(v)}")
    return Interpretacion(None, detalle=f"'{valor}' no es un número interpretable")


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def interpretar_conteo(valor: Any, nombre: str) -> Interpretacion:
    """Número entero no negativo (unidades, productos en promoción).

    * texto o decimal entero (``"3"``, ``2.0``) → reparar.
    * decimal no entero → advertir y redondear.
    * negativo → ``valor=None`` con detalle (quien llama decide).
    """
    r = interpretar_numero(valor)
    if r.valor is None:
        return r
    v = r.valor
    if v < 0:
        return Interpretacion(None, detalle=f"{nombre} negativo ({_fmt(v)})")
    if float(v).is_integer():
        if isinstance(valor, str):
            return Interpretacion(int(v), REPARAR, f"{nombre}: {r.detalle}")
        if r.accion:
            return Interpretacion(int(v), REPARAR, f"{nombre} {valor!r} se interpretó como el entero {int(v)}")
        return Interpretacion(int(v))
    entero = int(math.floor(v + 0.5))  # redondeo comercial (2.5 → 3)
    return Interpretacion(entero, ADVERTIR, f"{nombre} {valor!r} no es entero; se redondeó a {entero}")


# ---------------------------------------------------------------------------- fechas
_MESES = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1,
    "feb": 2, "febrero": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6, "june": 6,
    "jul": 7, "julio": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9, "september": 9,
    "oct": 10, "octubre": 10, "october": 10,
    "nov": 11, "noviembre": 11, "november": 11,
    "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_HORA = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_AMD = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
_COMPACTA = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DMA = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$")


def _fecha(a: int, m: int, d: int) -> date | None:
    try:
        return date(a, m, d)
    except ValueError:
        return None


def interpretar_fecha(valor: Any) -> Interpretacion:
    if isinstance(valor, bool) or valor is None:
        return Interpretacion(None, detalle="fecha ausente o no válida")
    if isinstance(valor, int) and 19000101 <= valor <= 21001231:
        valor = str(valor)
    elif isinstance(valor, (int, float)) and valor > 1e8:
        seg = valor / 1000 if valor > 1e11 else valor
        f = datetime.fromtimestamp(seg, tz=timezone.utc).date()
        return Interpretacion(f, ADVERTIR, f"{valor!r} se interpretó como marca de tiempo Unix (UTC) → {f}")
    if not isinstance(valor, str):
        return Interpretacion(None, detalle=f"fecha {valor!r} no es texto AAAA-MM-DD")

    s = valor.strip()
    if _ISO.match(s):
        f = _fecha(*map(int, s.split("-")))
        if f is None:
            return Interpretacion(None, detalle=f"'{valor}' no es una fecha del calendario")
        if s != valor:  # p. ej. espacios alrededor: corrección inequívoca, pero se informa
            return Interpretacion(f, REPARAR, f"'{valor}' tenía espacios; se interpretó como {f}")
        return Interpretacion(f)
    if m := _ISO_HORA.match(s):
        f = _fecha(int(m[1]), int(m[2]), int(m[3]))
        if f:
            return Interpretacion(f, REPARAR, f"'{valor}' incluía hora; se usó la fecha {f}")
    for patron in (_AMD, _COMPACTA):
        if m := patron.match(s):
            f = _fecha(int(m[1]), int(m[2]), int(m[3]))
            if f:
                return Interpretacion(f, REPARAR, f"'{valor}' (año-mes-día) se interpretó como {f}")
    if m := _DMA.match(s):
        return _dia_mes_anio(valor, int(m[1]), int(m[2]), m[3])
    return _fecha_con_mes_texto(valor)


def _dia_mes_anio(original: str, a: int, b: int, anio_txt: str) -> Interpretacion:
    anio = int(anio_txt)
    accion_anio = None
    if len(anio_txt) == 2:
        anio += 2000
        accion_anio = f"; el año '{anio_txt}' se asumió como {anio}"
    if a > 12 and b <= 12:
        f, accion, motivo = _fecha(anio, b, a), REPARAR, "día/mes/año"
    elif b > 12 and a <= 12:
        f, accion, motivo = _fecha(anio, a, b), REPARAR, "mes/día/año"
    elif a == b:
        f, accion, motivo = _fecha(anio, a, a), REPARAR, "día/mes/año"
    else:
        # Ambiguo (ambos ≤ 12): se usa la convención guatemalteca día/mes/año.
        f, accion, motivo = _fecha(anio, b, a), ADVERTIR, "día/mes/año (ambiguo; convención local)"
    if f is None:
        return Interpretacion(None, detalle=f"'{original}' no es una fecha del calendario")
    if accion_anio:
        accion = ADVERTIR
    return Interpretacion(f, accion, f"'{original}' ({motivo}) se interpretó como {f}{accion_anio or ''}")


def _fecha_con_mes_texto(original: str) -> Interpretacion:
    partes = [p for p in re.split(r"[\s,/.\-]+", sin_acentos(original).lower()) if p and p != "de"]
    mes = [(i, _MESES[p]) for i, p in enumerate(partes) if p in _MESES]
    nums = [int(p) for p in partes if p.isdigit()]
    if len(mes) == 1 and len(nums) == 2:
        anio = next((n for n in nums if n > 31), None)
        dia = next((n for n in nums if n <= 31), None)
        if anio and dia:
            f = _fecha(anio, mes[0][1], dia)
            if f:
                return Interpretacion(f, REPARAR, f"'{original}' se interpretó como {f}")
    return Interpretacion(None, detalle=f"'{original}' no tiene un formato de fecha reconocible (use AAAA-MM-DD)")


# ---------------------------------------------------------------------------- tiendas
_TIENDA_CODIGO = re.compile(r"^[a-z#\s_.\-]*?0*(\d+)$")


def interpretar_tienda(valor: Any, tiendas: dict[int, str]) -> Interpretacion:
    """``tiendas``: {tienda_id: nombre}. Devuelve el id entero o ``None``."""
    if isinstance(valor, bool) or valor is None:
        return Interpretacion(None, detalle="tienda_id ausente o no válido")
    if isinstance(valor, int):
        return Interpretacion(valor)
    if isinstance(valor, float):
        if valor.is_integer():
            return Interpretacion(int(valor), REPARAR, f"{valor!r} (decimal) se interpretó como {int(valor)}")
        return Interpretacion(None, detalle=f"tienda_id {valor!r} no es entero")
    if isinstance(valor, str):
        # 1) nombre completo de la tienda (con o sin la marca), p. ej. "NovaMercado Zona 10"
        objetivo = compacto(valor)
        for tid, nombre in tiendas.items():
            if objetivo in (compacto(nombre), compacto(nombre.replace("NovaMercado", ""))):
                return Interpretacion(tid, REPARAR, f"'{valor}' corresponde por nombre a la tienda {tid}")
        # 2) código con prefijo y un único número: "5", "T05", "T-5", "Tienda 5", "#5"
        s = sin_acentos(valor.strip()).lower()
        if m := _TIENDA_CODIGO.match(s):
            tid = int(m[1])
            return Interpretacion(tid, REPARAR, f"'{valor}' se interpretó como tienda {tid}")
    return Interpretacion(None, detalle=f"tienda_id {valor!r} no se pudo interpretar")


# ---------------------------------------------------------------------------- familias
def interpretar_familia(valor: Any, familias: dict[str, str]) -> Interpretacion:
    """``familias``: {familia_id: nombre}. Reglas, de más a menos estricta:

    1. id exacto → ok.
    2. Igual a id o nombre ignorando mayúsculas, acentos, espacios, conectores y
       singular/plural → reparar.
    3. Similitud alta (≥ 0.8) con un único candidato, o sus palabras son un subconjunto de
       las de un único nombre → advertir.
    4. Sin coincidencia → ``None``.
    """
    if not isinstance(valor, str) or not valor.strip():
        return Interpretacion(None, detalle=f"familia_id {valor!r} no es texto")
    if valor in familias:
        return Interpretacion(valor)
    claves = {}
    for fid, nombre in familias.items():
        for forma in (fid, nombre):
            claves.setdefault(compacto(forma), set()).add(fid)
            claves.setdefault(forma_flexible(forma), set()).add(fid)
    for forma in (compacto(valor), forma_flexible(valor)):
        if len(claves.get(forma, ())) == 1:
            fid = next(iter(claves[forma]))
            return Interpretacion(fid, REPARAR, f"'{valor}' se interpretó como '{fid}'")

    parecidos = difflib.get_close_matches(compacto(valor), list(claves), n=3, cutoff=0.8)
    destinos = {fid for p in parecidos for fid in claves[p]}
    if len(destinos) != 1:
        palabras = {t for t in tokens(valor)}
        destinos = {fid for fid, nombre in familias.items()
                    if palabras and palabras <= set(tokens(nombre)) | set(tokens(fid))}
    if len(destinos) == 1:
        fid = destinos.pop()
        return Interpretacion(fid, ADVERTIR, f"'{valor}' se interpretó como '{fid}' por similitud")
    return Interpretacion(None, detalle=f"familia '{valor}' no existe en el catálogo")


__all__ = ["Interpretacion", "interpretar_numero", "interpretar_conteo", "interpretar_fecha",
           "interpretar_tienda", "interpretar_familia", "canonico"]
