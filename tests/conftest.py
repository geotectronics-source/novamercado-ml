"""Dobles de prueba: catálogos sintéticos, repositorio en memoria y modelo sin MLflow.

Las pruebas NO usan los archivos publicados (no forman parte del repositorio) ni un
servidor de MLflow/PostgreSQL: todo vive en memoria.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novamercado.catalogos import Catalogos  # noqa: E402
from novamercado.config import Config  # noqa: E402
from novamercado.modelo import Baseline  # noqa: E402

FAMILIAS = [("abarrotes", "Abarrotes", 1.0, 0.2), ("bebidas", "Bebidas", 1.0, 0.2), ("lacteos", "Lácteos", 1.0, 1.2),
            ("carnes", "Carnes", 1.5, 2.0), ("panaderia", "Panadería", 1.0, 2.5),
            ("frutas_verduras", "Frutas y verduras", 1.0, 2.0), ("limpieza", "Limpieza", 1.0, 0.1),
            ("cuidado_personal", "Cuidado personal", 1.0, 0.1), ("licores", "Licores", 2.0, 0.1),
            ("snacks", "Snacks y dulces", 1.0, 0.3), ("bebe", "Bebé", 1.5, 0.2), ("mascotas", "Mascotas", 1.0, 0.2)]
TIENDAS = [(1, "NovaMercado Zona 10", "Guatemala", "hipermercado", "2019-01-01"),
           (2, "NovaMercado Mixco", "Mixco", "supermercado", "2019-01-01"),
           (5, "NovaMercado Quetzaltenango", "Quetzaltenango", "hipermercado", "2019-01-01"),
           (10, "NovaMercado Express Zona 16", "Guatemala", "express", "2025-03-15")]
INICIO_HIST = date(2025, 1, 1)
FIN_HIST = date(2025, 12, 31)


@pytest.fixture(scope="session")
def cat() -> Catalogos:
    return Catalogos.desde_dataframes(
        tiendas=pd.DataFrame(TIENDAS, columns=["tienda_id", "nombre", "ciudad", "tipo", "fecha_apertura"])
        .assign(departamento="X"),
        familias=pd.DataFrame([(f, n) for f, n, _, _ in FAMILIAS], columns=["familia_id", "nombre"]),
        costos=pd.DataFrame([(f, a, b) for f, _, a, b in FAMILIAS],
                            columns=["familia_id", "costo_faltante", "costo_sobrante"]),
        feriados=pd.DataFrame([("2025-12-25", "Navidad", "feriado", "nacional"),
                               ("2026-12-31", "Fin de año", "medio_dia", "nacional"),
                               ("2025-08-15", "Asunción", "feriado", "Guatemala")],
                              columns=["fecha", "nombre", "tipo", "ambito"]),
    )


def historia_sintetica(cat: Catalogos, inicio=INICIO_HIST, fin=FIN_HIST, semilla=0) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    filas = []
    for t in cat.ids_tiendas:
        apertura = cat.fecha_apertura(t)
        for i, f in enumerate(cat.ids_familias):
            nivel = 50 + 20 * i + 10 * t
            d = max(inicio, apertura)
            while d <= fin:
                factor = 1.3 if d.weekday() >= 4 else 1.0
                filas.append((pd.Timestamp(d), t, f, int(rng.poisson(nivel * factor)), int(rng.integers(0, 3))))
                d += timedelta(days=1)
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


class RepoMemoria:
    """Implementa la misma interfaz que ``db.Repositorio`` sin PostgreSQL."""

    def __init__(self, cat: Catalogos, historia: pd.DataFrame):
        self._cat, self.historia = cat, historia
        self.observaciones: dict[tuple, int] = {}
        self.solicitudes: list[dict] = []
        self.predicciones: list[dict] = []
        self.reentrenamientos: dict[str, dict] = {}
        self.caida = False

    def verificar(self):
        if self.caida:
            raise ConnectionError("bd caída")

    def catalogos(self):
        return self._cat

    def historia_tienda(self, tienda_id, fecha):
        h = self.historia[(self.historia["tienda_id"] == tienda_id) & (self.historia["fecha"] < pd.Timestamp(fecha))]
        obs = pd.DataFrame([(pd.Timestamp(f), t, fam, v) for (t, fam, f), v in self.observaciones.items()
                            if t == tienda_id and f < fecha], columns=["fecha", "tienda_id", "familia_id", "ventas"])
        return pd.concat([h[["fecha", "tienda_id", "familia_id", "ventas"]], obs], ignore_index=True)

    def registrar_solicitud(self, tipo, cuerpo_crudo, codigo_http, **kw):
        self.solicitudes.append({"tipo": tipo, "codigo": codigo_http, **kw})
        return len(self.solicitudes)

    def registrar_prediccion(self, tipo, crudo, limpio, tienda_id, fecha, estado, version, correcciones, filas):
        self.solicitudes.append({"tipo": tipo, "codigo": 200, "estado": estado})
        self.predicciones.extend({"tienda_id": tienda_id, "fecha": fecha, "version": version, **f} for f in filas)
        return len(self.solicitudes)

    def guardar_observaciones(self, crudo, limpio, tienda_id, fecha, ventas, estado, correcciones):
        guardados, cambios = 0, []
        for fam, v in ventas.items():
            clave = (tienda_id, fam, fecha)
            previo = self.observaciones.get(clave)
            if previo is None or previo != v:
                guardados += 1
                if previo is not None:
                    cambios.append((fam, previo, v))
                self.observaciones[clave] = v
        self.solicitudes.append({"tipo": "observaciones", "codigo": 200})
        return guardados, cambios

    def crear_reentrenamiento(self, rid):
        self.reentrenamientos[rid] = {"estado": "en_curso", "promovido": None, "version": None, "motivo": None}

    def obtener_reentrenamiento(self, rid):
        return self.reentrenamientos.get(rid)

    def finalizar_reentrenamiento(self, rid, estado, promovido, version, motivo, *a, **k):
        self.reentrenamientos[rid] = {"estado": estado, "promovido": promovido, "version": version, "motivo": motivo}


class ModeloFijo:
    def __init__(self, modelo=None, version="1"):
        self._m, self._v = modelo, version

    def actual(self):
        return self._m, (self._v if self._m is not None else None)


class AirflowFalso:
    def __init__(self):
        self.disparados, self.estados, self.caido = [], {}, False

    def disparar(self, rid):
        if self.caido:
            raise ConnectionError("airflow caído")
        self.disparados.append(rid)

    def estado(self, rid):
        return self.estados.get(rid, "running")


class MonitorFalso:
    def __init__(self):
        self.estado = {"mlflow": "ok", "airflow": "ok"}


@pytest.fixture()
def cfg() -> Config:
    return Config.desde_entorno()


@pytest.fixture()
def deps(cat, cfg):
    from novamercado.api.servicio import Dependencias

    modelo = Baseline(multiplicadores={f"{f}|*": 1.1 for f in cat.ids_familias})
    return Dependencias(cfg=cfg, repo=RepoMemoria(cat, historia_sintetica(cat)), modelo=ModeloFijo(modelo, "3"),
                        airflow=AirflowFalso(), monitor=MonitorFalso())


@pytest.fixture()
def cliente(deps):
    from fastapi.testclient import TestClient

    from novamercado.api.main import crear_app

    with TestClient(crear_app(deps)) as c:
        yield c


def solicitud_valida(tienda=5, fecha="2026-01-05"):
    return {"tienda_id": tienda, "fecha": fecha,
            "familias": [{"familia_id": f, "en_promocion": 1 if f == "bebidas" else 0} for f, *_ in FAMILIAS]}


def observacion_valida(tienda=5, fecha="2026-01-05"):
    return {"tienda_id": tienda, "fecha": fecha,
            "ventas": [{"familia_id": f, "ventas": 100 + i} for i, (f, *_) in enumerate(FAMILIAS)]}
