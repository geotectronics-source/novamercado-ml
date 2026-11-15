"""Lógica de negocio de cada endpoint (los endpoints solo traducen HTTP ↔ estas funciones)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..calidad import Rechazo, limpiar_observaciones, limpiar_prediccion
from ..config import Config
from ..contrato import (Calidad, EstadoReentrenamiento, ModeloVigente, PrediccionFamilia, RespuestaObservaciones,
                        RespuestaPrediccion, Salud)
from ..features import construir_features

log = logging.getLogger("novamercado.api")

DIAS_SIN_OBS_ADVERTIR = 7


class SinModelo(Exception):
    """Todavía no hay un modelo cargado → 503."""


class NoDisponible(Exception):
    """Una dependencia necesaria no responde → 503."""


@dataclass
class Dependencias:
    cfg: Config
    repo: object  # Repositorio (o un doble de prueba)
    modelo: object  # GestorModelo
    airflow: object  # ClienteAirflow
    monitor: object  # Monitor
    _catalogos: object = field(default=None, repr=False)

    def catalogos(self):
        """Se cargan una vez desde la BD; si el bootstrap aún no los cargó, no se cachean."""
        if self._catalogos is None:
            try:
                cat = self.repo.catalogos()
            except Exception as e:  # noqa: BLE001
                raise NoDisponible(f"base de datos no disponible: {type(e).__name__}") from e
            if cat.tiendas.empty or cat.familias.empty:
                raise NoDisponible("los catálogos aún no se han cargado (bootstrap en curso)")
            self._catalogos = cat
        return self._catalogos


# ---------------------------------------------------------------------------- predicción
def predecir(cuerpo, deps: Dependencias) -> RespuestaPrediccion:
    cat = deps.catalogos()
    try:
        limpia = limpiar_prediccion(cuerpo, cat)
    except Rechazo as r:
        _registrar_rechazo(deps, "prediccion", cuerpo, r)
        raise
    modelo, version = deps.modelo.actual()
    if modelo is None:
        raise SinModelo("todavía no hay un modelo cargado")

    s, reporte = limpia.solicitud, limpia.reporte
    historia = deps.repo.historia_tienda(s.tienda_id, s.fecha)
    if historia.empty:
        r = Rechazo(f"no hay ventas registradas de la tienda {s.tienda_id} antes del {s.fecha}; "
                    "no es posible pronosticar sin inventar datos", campo="fecha")
        _registrar_rechazo(deps, "prediccion", cuerpo, r)
        raise r

    objetivos = pd.DataFrame({
        "fecha": pd.Timestamp(s.fecha), "tienda_id": s.tienda_id,
        "familia_id": [f.familia_id for f in s.familias],
        "en_promocion": [float(f.en_promocion) for f in s.familias], "ventas": np.nan,
    })
    historia = historia.assign(en_promocion=np.nan)
    X = construir_features(pd.concat([historia, objetivos], ignore_index=True), cat)
    X = X[X["fecha"] == pd.Timestamp(s.fecha)].set_index("familia_id", drop=False)

    dias = X["dias_sin_obs"].min()
    if pd.notna(dias) and dias > DIAS_SIN_OBS_ADVERTIR:
        ultima = (pd.Timestamp(s.fecha) - pd.Timedelta(days=int(dias))).date()
        reporte.advertir("fecha", f"la última venta conocida de la tienda es del {ultima} (hace {int(dias)} días); "
                                  "el pronóstico usa el último nivel conocido")
    sin_nivel = X.index[X["base"].isna()].tolist()
    for fam in sin_nivel:
        reporte.advertir(f"familias.{fam}", f"no hay historia de '{fam}' en la tienda; se omitió del pronóstico")
    X = X.drop(index=sin_nivel)
    if X.empty:
        raise Rechazo("ninguna familia tiene historia suficiente para pronosticar", campo="familias")

    pred = modelo.predecir(X)
    filas = []
    for f in s.familias:
        if f.familia_id not in pred.index:
            continue
        p = pred.loc[f.familia_id]
        filas.append({"familia_id": f.familia_id, "venta_esperada": float(p["venta_esperada"]),
                      "cantidad_sugerida": int(p["cantidad_sugerida"]), "en_promocion": f.en_promocion,
                      "promocion_supuesta": f.familia_id in limpia.promociones_supuestas})
    calidad = reporte.como_dict()
    respuesta = RespuestaPrediccion(
        tienda_id=s.tienda_id, fecha=s.fecha.isoformat(), version_modelo=str(version),
        predicciones=[PrediccionFamilia(**{k: v for k, v in f.items() if k != "en_promocion"}) for f in filas],
        calidad=Calidad(**calidad),
    )
    deps.repo.registrar_prediccion("prediccion", cuerpo, s.model_dump(mode="json"), s.tienda_id, s.fecha,
                                   calidad["estado"], str(version), calidad["observaciones"], filas)
    return respuesta


# ---------------------------------------------------------------------------- observaciones
def observar(cuerpo, deps: Dependencias) -> RespuestaObservaciones:
    cat = deps.catalogos()
    try:
        limpia = limpiar_observaciones(cuerpo, cat)
    except Rechazo as r:
        _registrar_rechazo(deps, "observaciones", cuerpo, r)
        raise
    s, reporte = limpia.solicitud, limpia.reporte
    ventas = {v.familia_id: v.ventas for v in s.ventas}
    guardados, cambios = deps.repo.guardar_observaciones(
        cuerpo, s.model_dump(mode="json"), s.tienda_id, s.fecha, ventas, reporte.estado,
        [o.como_dict() for o in reporte.observaciones])
    for fam, previo, nuevo in cambios:
        reporte.advertir(f"ventas.{fam}", f"ya existía una observación de '{fam}' para {s.fecha} con {previo}; "
                                          f"se reemplazó por {nuevo}")
    return RespuestaObservaciones(registros_guardados=guardados, calidad=Calidad(**reporte.como_dict()))


def _registrar_rechazo(deps: Dependencias, tipo: str, cuerpo, r: Rechazo) -> None:
    try:
        deps.repo.registrar_solicitud(tipo, cuerpo, 422, detalle_rechazo=r.mensaje)
    except Exception as e:  # noqa: BLE001 - el registro no debe impedir responder
        log.warning("No se pudo registrar el rechazo: %s", e)


# ---------------------------------------------------------------------------- administración
def disparar_reentrenamiento(deps: Dependencias) -> str:
    rid = f"reent_{pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    try:
        deps.airflow.disparar(rid)
    except Exception as e:  # noqa: BLE001
        raise NoDisponible(f"no se pudo iniciar el reentrenamiento en Airflow: {e}") from e
    deps.repo.crear_reentrenamiento(rid)
    return rid


def estado_reentrenamiento(rid: str, deps: Dependencias) -> EstadoReentrenamiento | None:
    fila = deps.repo.obtener_reentrenamiento(rid)
    if fila is None:
        return None
    if fila["estado"] == "en_curso":
        try:
            estado_airflow = deps.airflow.estado(rid)
        except Exception:  # noqa: BLE001 - Airflow caído: seguimos reportando en curso
            estado_airflow = None
        if estado_airflow == "failed":
            _, version = deps.modelo.actual()
            deps.repo.finalizar_reentrenamiento(
                rid, "fallido", False, version, "La ejecución del DAG falló; el modelo vigente no cambió")
            fila = deps.repo.obtener_reentrenamiento(rid)
    if fila["estado"] == "en_curso":
        return EstadoReentrenamiento(estado="en_curso")
    version = fila["version"]
    if version is None:  # p. ej. el DAG falló con MLflow caído: la vigente es la que sirve la API
        _, version = deps.modelo.actual()
    return EstadoReentrenamiento(estado=fila["estado"], promovido=bool(fila["promovido"]),
                                 version=None if version is None else str(version), motivo=fila["motivo"])


def modelo_vigente(deps: Dependencias) -> ModeloVigente:
    _, version = deps.modelo.actual()
    if version is None:
        raise SinModelo("todavía no hay un modelo cargado")
    return ModeloVigente(nombre=deps.cfg.nombre_modelo, alias=deps.cfg.alias_modelo, version=str(version))


def salud(deps: Dependencias) -> tuple[int, Salud]:
    componentes = {"api": "ok"}
    try:
        deps.repo.verificar()
        componentes["base_datos"] = "ok"
    except Exception as e:  # noqa: BLE001
        componentes["base_datos"] = f"no disponible ({type(e).__name__})"
    componentes.update(deps.monitor.estado)
    _, version = deps.modelo.actual()
    componentes["modelo"] = f"v{version}" if version else "sin modelo"
    if version is None:
        return 503, Salud(estado="degradado", motivo="no hay un modelo cargado", componentes=componentes)
    problemas = [f"{k}: {v}" for k, v in componentes.items() if k != "modelo" and v != "ok"]
    if problemas:
        return 200, Salud(estado="degradado", motivo="; ".join(problemas), componentes=componentes)
    return 200, Salud(estado="ok", componentes=componentes)
