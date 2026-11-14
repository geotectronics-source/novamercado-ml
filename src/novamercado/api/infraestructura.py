"""Componentes de operación de la API.

* ``GestorModelo``: mantiene el modelo vigente en memoria, lo recarga en caliente cuando el
  alias cambia en MLflow (sondeo cada ``INTERVALO_RECARGA_S``) y guarda una copia en disco
  para poder arrancar aunque MLflow no esté disponible.
* ``Monitor``: revisa periódicamente MLflow y Airflow para ``GET /health``.
* ``ClienteAirflow``: dispara y consulta ejecuciones del DAG por la API REST de Airflow.
"""
from __future__ import annotations

import logging
import os
import pickle
import tempfile
import threading
import time
from pathlib import Path

import requests

from ..config import Config

log = logging.getLogger("novamercado.api")


class GestorModelo:
    def __init__(self, cfg: Config, cargador=None, consultor_version=None):
        from .. import registro

        self.cfg = cfg
        self._lock = threading.Lock()
        self._modelo = None
        self._version: str | None = None
        self._cargar = cargador or (lambda v: registro.cargar_version(cfg, v))
        self._version_vigente = consultor_version or (lambda: registro.version_vigente(cfg))
        self.ultimo_error: str | None = None
        self._cache = Path(cfg.carpeta_cache) / "modelo_vigente.pkl"

    def actual(self):
        with self._lock:
            return self._modelo, self._version

    def fijar(self, modelo, version: str) -> None:
        with self._lock:
            self._modelo, self._version = modelo, str(version)

    # ---------------------------------------------------------------- caché local
    def cargar_cache(self) -> bool:
        try:
            if self._cache.exists():
                with open(self._cache, "rb") as f:
                    datos = pickle.load(f)
                self.fijar(datos["modelo"], datos["version"])
                log.info("Modelo v%s cargado desde la caché local", datos["version"])
                return True
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo leer la caché del modelo: %s", e)
        return False

    def _guardar_cache(self, modelo, version: str) -> None:
        try:
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._cache.parent)
            with os.fdopen(fd, "wb") as f:
                pickle.dump({"modelo": modelo, "version": version}, f)
            os.replace(tmp, self._cache)  # escritura atómica
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo guardar la caché del modelo: %s", e)

    # ---------------------------------------------------------------- recarga
    def actualizar(self) -> bool:
        """Consulta el alias; si apunta a otra versión, la carga y la intercambia. True si cambió."""
        version = self._version_vigente()
        if version is None or version == self._version:
            return False
        modelo = self._cargar(version)
        self.fijar(modelo, version)
        self._guardar_cache(modelo, version)
        log.info("Modelo vigente actualizado a v%s", version)
        return True

    def iniciar(self) -> None:
        self.cargar_cache()
        threading.Thread(target=self._bucle, name="recarga-modelo", daemon=True).start()

    def _bucle(self) -> None:
        while True:
            try:
                self.actualizar()
                self.ultimo_error = None
            except Exception as e:  # noqa: BLE001 - MLflow caído no debe tumbar la API
                self.ultimo_error = f"{type(e).__name__}: {e}"[:300]
                log.warning("No se pudo consultar/cargar el modelo vigente: %s", self.ultimo_error)
            time.sleep(self.cfg.intervalo_recarga_s if self._modelo is not None else 5)


class Monitor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.estado: dict[str, str] = {"mlflow": "desconocido", "airflow": "desconocido"}

    def revisar(self) -> dict[str, str]:
        nuevo = {}
        try:
            r = requests.get(f"{self.cfg.mlflow_url}/health", timeout=3)
            nuevo["mlflow"] = "ok" if r.ok else f"http {r.status_code}"
        except requests.RequestException as e:
            nuevo["mlflow"] = f"no disponible ({type(e).__name__})"
        try:
            r = requests.get(f"{self.cfg.airflow_url}/health", timeout=3)
            cuerpo = r.json() if r.ok else {}
            malos = [k for k in ("metadatabase", "scheduler") if cuerpo.get(k, {}).get("status") != "healthy"]
            nuevo["airflow"] = "ok" if r.ok and not malos else f"no saludable ({', '.join(malos) or r.status_code})"
        except (requests.RequestException, ValueError) as e:
            nuevo["airflow"] = f"no disponible ({type(e).__name__})"
        self.estado = nuevo
        return nuevo

    def iniciar(self) -> None:
        def bucle():
            while True:
                try:
                    self.revisar()
                except Exception as e:  # noqa: BLE001
                    log.warning("Monitor: %s", e)
                time.sleep(self.cfg.intervalo_monitor_s)

        threading.Thread(target=bucle, name="monitor", daemon=True).start()


class ClienteAirflow:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.auth = (cfg.airflow_usuario, cfg.airflow_clave)
        self.base = f"{cfg.airflow_url}/api/v1/dags/{cfg.dag_id}"

    def disparar(self, run_id: str) -> None:
        # Asegura que el DAG no esté en pausa (idempotente).
        requests.patch(self.base, json={"is_paused": False}, auth=self.auth, timeout=5)
        r = requests.post(f"{self.base}/dagRuns", json={"dag_run_id": run_id, "conf": {}}, auth=self.auth, timeout=10)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Airflow respondió {r.status_code}: {r.text[:200]}")

    def estado(self, run_id: str) -> str | None:
        r = requests.get(f"{self.base}/dagRuns/{run_id}", auth=self.auth, timeout=5)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("state")
