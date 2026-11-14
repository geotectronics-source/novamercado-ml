"""Normalización de texto y de nombres de campos.

Reglas generales (no dependen de los ejemplos del catálogo):
1. Forma canónica de un texto: sin acentos, minúsculas, camelCase → snake_case y cualquier
   separador (espacio, guion, punto) → ``_``.
2. Un campo cuyo nombre, en forma canónica, coincide con el del contrato o con un sinónimo
   conocido se **repara** (la intención es inequívoca).
3. Un campo con nombre *parecido* (error tipográfico, similitud ≥ 0.85 y sin empate) se
   interpreta con **advertencia** (es una suposición).
4. Campos desconocidos se ignoran con **advertencia** (suponemos que no aportan).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from .reporte import Reporte

CONECTORES = {"y", "e", "de", "del", "la", "el", "las", "los", "and", "of", "the"}


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def canonico(texto: Any) -> str:
    s = str(texto).strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)  # camelCase → camel_Case
    s = sin_acentos(s).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def tokens(texto: str) -> list[str]:
    return [t for t in canonico(texto).split("_") if t and t not in CONECTORES]


def compacto(texto: str) -> str:
    """Canónico sin conectores ni separadores: 'Frutas y Verduras' → 'frutasverduras'."""
    return "".join(tokens(texto))


def singular(palabra: str) -> str:
    for suf in ("es", "s"):
        if palabra.endswith(suf) and len(palabra) - len(suf) >= 3:
            return palabra[: -len(suf)]
    return palabra


def forma_flexible(texto: str) -> str:
    """Compacto y en singular por palabra: 'Lácteo' y 'LACTEOS' → 'lacte'."""
    return "".join(singular(t) for t in tokens(texto))


def mapear_campos(obj: dict, esquema: dict[str, set[str]], ruta: str, reporte: Reporte,
                  obligatorios: set[str]) -> dict:
    """Devuelve {campo_contrato: valor} a partir de un objeto con nombres posiblemente distintos.

    ``esquema``: campo del contrato → conjunto de sinónimos (en forma canónica).
    Lanza ``Rechazo`` si falta un obligatorio. Ver reglas en el docstring del módulo.
    """
    from .reporte import Rechazo

    prefijo = f"{ruta}." if ruta else ""
    candidatos: dict[str, list[tuple[int, str, Any]]] = {c: [] for c in esquema}
    # prioridad: 0 = nombre exacto, 1 = canónico/sinónimo, 2 = parecido
    todos_nombres = {s: c for c, sins in esquema.items() for s in sins | {c}}
    for clave, valor in obj.items():
        if clave in esquema:
            candidatos[clave].append((0, clave, valor))
            continue
        can = canonico(clave)
        if can in todos_nombres:
            candidatos[todos_nombres[can]].append((1, clave, valor))
            continue
        parecidos = difflib.get_close_matches(can, list(todos_nombres), n=2, cutoff=0.85)
        destinos = {todos_nombres[p] for p in parecidos}
        if len(destinos) == 1:
            candidatos[destinos.pop()].append((2, clave, valor))
        else:
            reporte.advertir(f"{prefijo}{clave}", f"campo '{clave}' no pertenece al contrato; se ignoró")

    salida = {}
    for campo, lista in candidatos.items():
        if not lista:
            if campo in obligatorios:
                raise Rechazo(f"falta el campo obligatorio '{campo}'", campo=f"{prefijo}{campo}")
            continue
        lista.sort(key=lambda t: t[0])
        prioridad, clave, valor = lista[0]
        if prioridad == 1:
            reporte.reparar(f"{prefijo}{campo}", f"campo '{clave}' se interpretó como '{campo}'")
        elif prioridad == 2:
            reporte.advertir(f"{prefijo}{campo}",
                             f"campo '{clave}' se interpretó como '{campo}' por similitud de nombre")
        for _, otra, otro_valor in lista[1:]:
            if otro_valor == valor:
                reporte.reparar(f"{prefijo}{otra}", f"campo '{otra}' duplica a '{clave}' con el mismo valor; se ignoró")
            else:
                reporte.advertir(f"{prefijo}{otra}",
                                 f"campo '{otra}' duplica a '{clave}' con otro valor; se usó el de '{clave}'")
        salida[campo] = valor
    return salida
