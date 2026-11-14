"""Registro de lo que la defensa del contrato hizo con cada solicitud.

Tres políticas posibles ante un problema:
* ``reparar``  → la corrección es inequívoca (estado ``corregido``).
* ``advertir`` → se responde con un supuesto explícito (estado ``advertencia``).
* rechazar     → se lanza ``Rechazo`` y la API responde 422 con ``detail``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

REPARAR = "reparar"
ADVERTIR = "advertir"


class Rechazo(Exception):
    """El problema no admite reparación ni supuesto razonable → HTTP 422."""

    def __init__(self, detalle: str, campo: str | None = None):
        self.detalle = detalle
        self.campo = campo
        super().__init__(detalle)

    @property
    def mensaje(self) -> str:
        return f"{self.campo}: {self.detalle}" if self.campo else self.detalle


@dataclass
class Observacion:
    campo: str
    accion: str
    detalle: str

    def como_dict(self) -> dict:
        return {"campo": self.campo, "accion": self.accion, "detalle": self.detalle}


@dataclass
class Reporte:
    observaciones: list[Observacion] = field(default_factory=list)

    def reparar(self, campo: str, detalle: str) -> None:
        self.observaciones.append(Observacion(campo, REPARAR, detalle))

    def advertir(self, campo: str, detalle: str) -> None:
        self.observaciones.append(Observacion(campo, ADVERTIR, detalle))

    def agregar(self, campo: str, accion: str | None, detalle: str | None) -> None:
        if accion == REPARAR:
            self.reparar(campo, detalle)
        elif accion == ADVERTIR:
            self.advertir(campo, detalle)

    @property
    def estado(self) -> str:
        acciones = {o.accion for o in self.observaciones}
        if ADVERTIR in acciones:
            return "advertencia"
        if REPARAR in acciones:
            return "corregido"
        return "ok"

    def como_dict(self) -> dict:
        return {"estado": self.estado, "observaciones": [o.como_dict() for o in self.observaciones]}
