"""Aplicación FastAPI. Los endpoints solo traducen HTTP ↔ ``servicio``.

Ejecutar:  uvicorn novamercado.api.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..calidad import Rechazo
from ..config import Config
from ..contrato import (EstadoReentrenamiento, ModeloVigente, RespuestaObservaciones, RespuestaPrediccion,
                        RespuestaReentrenar, Salud)
from . import servicio
from .servicio import Dependencias, NoDisponible, SinModelo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

EJEMPLO_PREDICCION = {"tienda_id": 5, "fecha": "2026-03-02",
                      "familias": [{"familia_id": "abarrotes", "en_promocion": 0},
                                   {"familia_id": "bebidas", "en_promocion": 8}]}
EJEMPLO_OBSERVACION = {"tienda_id": 5, "fecha": "2026-03-01",
                       "ventas": [{"familia_id": "abarrotes", "ventas": 994}]}


def _dependencias_produccion() -> Dependencias:
    from ..db import Repositorio
    from .infraestructura import ClienteAirflow, GestorModelo, Monitor

    cfg = Config.desde_entorno()
    deps = Dependencias(cfg=cfg, repo=Repositorio(cfg.db_url), modelo=GestorModelo(cfg),
                        airflow=ClienteAirflow(cfg), monitor=Monitor(cfg))
    deps.modelo.iniciar()
    deps.monitor.iniciar()
    return deps


def crear_app(deps: Dependencias | None = None) -> FastAPI:
    @asynccontextmanager
    async def ciclo_vida(app: FastAPI):
        if getattr(app.state, "deps", None) is None:
            app.state.deps = await run_in_threadpool(_dependencias_produccion)
        yield

    app = FastAPI(title="NovaMercado — Pronóstico diario de ventas", version="1.0.0", lifespan=ciclo_vida)
    app.state.deps = deps

    async def _cuerpo(request: Request):
        try:
            return json.loads(await request.body() or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(422, detail=f"el cuerpo no es JSON válido: {e}") from e

    @app.exception_handler(Rechazo)
    async def _rechazo(_, exc: Rechazo):
        return JSONResponse(status_code=422, content={"detail": exc.mensaje})

    @app.exception_handler(SinModelo)
    async def _sin_modelo(_, exc: SinModelo):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(NoDisponible)
    async def _no_disponible(_, exc: NoDisponible):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validacion(_, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.post("/v1/prediccion", response_model=RespuestaPrediccion, tags=["servicio"],
              openapi_extra={"requestBody": {"content": {"application/json": {"example": EJEMPLO_PREDICCION}}}})
    async def prediccion(request: Request):
        cuerpo = await _cuerpo(request)
        return await run_in_threadpool(servicio.predecir, cuerpo, request.app.state.deps)

    @app.post("/v1/observaciones", response_model=RespuestaObservaciones, tags=["servicio"],
              openapi_extra={"requestBody": {"content": {"application/json": {"example": EJEMPLO_OBSERVACION}}}})
    async def observaciones(request: Request):
        cuerpo = await _cuerpo(request)
        return await run_in_threadpool(servicio.observar, cuerpo, request.app.state.deps)

    @app.post("/admin/reentrenar", status_code=202, response_model=RespuestaReentrenar, tags=["administración"])
    async def reentrenar(request: Request):
        rid = await run_in_threadpool(servicio.disparar_reentrenamiento, request.app.state.deps)
        return RespuestaReentrenar(id=rid)

    @app.get("/admin/reentrenar/{rid}", response_model=EstadoReentrenamiento, response_model_exclude_none=True,
             tags=["administración"])
    async def estado_reentrenamiento(rid: str, request: Request):
        r = await run_in_threadpool(servicio.estado_reentrenamiento, rid, request.app.state.deps)
        if r is None:
            raise HTTPException(404, detail=f"no existe la ejecución '{rid}'")
        return r

    @app.get("/modelo", response_model=ModeloVigente, tags=["administración"])
    async def modelo(request: Request):
        return servicio.modelo_vigente(request.app.state.deps)

    @app.get("/health", response_model=Salud, response_model_exclude_none=True, tags=["operación"])
    async def health(request: Request):
        codigo, cuerpo = await run_in_threadpool(servicio.salud, request.app.state.deps)
        return JSONResponse(status_code=codigo, content=cuerpo.model_dump(exclude_none=True))

    return app


app = crear_app()
