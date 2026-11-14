"""Modelos Pydantic del contrato (Anexo del enunciado).

Las solicitudes se validan en **dos etapas**:
1. ``calidad.*`` limpia el JSON crudo con reglas generales (reparar / advertir / rechazar).
2. El resultado limpio se valida con estos modelos en modo estricto. Si algo pasa la
   limpieza pero no cumple el contrato, es un error nuestro y no llega al modelo.

Las respuestas también se construyen con estos modelos, así FastAPI garantiza que nunca
se omite ni se renombra un campo del contrato.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, StrictInt, StrictStr

# ------------------------------------------------------------------ solicitudes (limpias)


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FamiliaSolicitud(_Estricto):
    familia_id: StrictStr
    en_promocion: NonNegativeInt


class SolicitudPrediccion(_Estricto):
    tienda_id: StrictInt = Field(ge=1)
    fecha: date
    familias: list[FamiliaSolicitud] = Field(min_length=1)


class VentaObservada(_Estricto):
    familia_id: StrictStr
    ventas: NonNegativeInt


class SolicitudObservaciones(_Estricto):
    tienda_id: StrictInt = Field(ge=1)
    fecha: date
    ventas: list[VentaObservada] = Field(min_length=1)


# ------------------------------------------------------------------ respuestas


class ObservacionCalidad(BaseModel):
    campo: str
    accion: Literal["reparar", "advertir"]
    detalle: str


class Calidad(BaseModel):
    estado: Literal["ok", "corregido", "advertencia"]
    observaciones: list[ObservacionCalidad] = []


class PrediccionFamilia(BaseModel):
    familia_id: str
    venta_esperada: float
    cantidad_sugerida: NonNegativeInt
    # Campo adicional (permitido por el contrato): la promoción fue supuesta, no enviada.
    promocion_supuesta: bool = False


class RespuestaPrediccion(BaseModel):
    tienda_id: int
    fecha: str
    version_modelo: str
    predicciones: list[PrediccionFamilia]
    calidad: Calidad


class RespuestaObservaciones(BaseModel):
    registros_guardados: NonNegativeInt
    calidad: Calidad


class RespuestaReentrenar(BaseModel):
    id: str


class EstadoReentrenamiento(BaseModel):
    estado: Literal["en_curso", "exitoso", "fallido"]
    promovido: bool | None = None
    version: str | None = None
    motivo: str | None = None


class ModeloVigente(BaseModel):
    nombre: str
    alias: str
    version: str


class Salud(BaseModel):
    estado: Literal["ok", "degradado", "no_disponible"]
    motivo: str | None = None
    componentes: dict[str, str] = {}
