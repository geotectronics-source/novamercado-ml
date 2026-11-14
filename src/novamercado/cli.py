"""Línea de comandos: bootstrap del producto y pasos del DAG de reentrenamiento.

    python -m novamercado.cli bootstrap
    python -m novamercado.cli dag-preparar  --run-id ID
    python -m novamercado.cli dag-entrenar  --run-id ID
    python -m novamercado.cli dag-decidir   --run-id ID
    python -m novamercado.cli dag-publicar  --run-id ID
    python -m novamercado.cli dag-fallo     --run-id ID --motivo "..."

Cada paso del DAG lee/escribe en ``$CARPETA_TRABAJO/<run_id>/`` para pasar resultados al
siguiente (los pasos corren en procesos separados).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from . import ciclo, registro
from .config import Config
from .db import Repositorio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("novamercado.cli")


def esperar(nombre: str, prueba, intentos: int = 90, pausa: float = 2.0):
    for i in range(intentos):
        try:
            return prueba()
        except Exception as e:  # noqa: BLE001 - reintento genérico de infraestructura
            if i == intentos - 1:
                raise
            log.info("Esperando %s (%s)...", nombre, type(e).__name__)
            time.sleep(pausa)


def _mlflow_arriba(cfg: Config):
    r = requests.get(f"{cfg.mlflow_url}/health", timeout=3)
    r.raise_for_status()


# ------------------------------------------------------------------------- bootstrap
def bootstrap(cfg: Config) -> None:
    repo = Repositorio(cfg.db_url)
    esperar("base de datos", repo.verificar)
    repo.crear_esquema()
    if repo.datos_cargados():
        log.info("Datos publicados ya cargados; no se repite la carga.")
    else:
        log.info("Cargando archivos publicados desde %s", cfg.carpeta_datos)
        conteo = repo.cargar_csv(cfg.carpeta_datos)
        log.info("Carga terminada: %s", conteo)
        repo.fijar_estado("datos_cargados", json.dumps(conteo))

    esperar("MLflow", lambda: _mlflow_arriba(cfg))
    vigente = registro.version_vigente(cfg)
    if vigente is not None:
        log.info("Ya existe el modelo vigente v%s; no se reentrena.", vigente)
        return
    log.info("No existe modelo vigente: entrenando el primero.")
    cat = repo.catalogos()
    datos = repo.datos_entrenamiento()
    ent = ciclo.entrenar_y_registrar(datos, cat, cfg, origen="bootstrap")
    dec = ciclo.decidir(datos, cat, cfg, ent)
    version = ciclo.aplicar_decision(cfg, dec)
    if version is None:
        raise SystemExit(f"El primer modelo no pasó la sanidad: {dec['motivo']}")
    repo.fijar_estado("bootstrap_modelo", version)
    log.info("Primer modelo registrado y promovido: v%s (%s)", version, dec["motivo"])


# ------------------------------------------------------------------------- pasos del DAG
def _carpeta(run_id: str) -> Path:
    d = Path(os.environ.get("CARPETA_TRABAJO", "/tmp/novamercado")) / run_id.replace(":", "_").replace("+", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def dag_preparar(cfg: Config, run_id: str) -> None:
    repo = Repositorio(cfg.db_url)
    datos = repo.datos_entrenamiento()
    with repo.engine.connect() as c:
        n_obs = pd.read_sql("SELECT count(*) AS n FROM observaciones", c)["n"].iloc[0]
    if datos.empty:
        raise SystemExit("No hay datos para entrenar")
    datos.to_pickle(_carpeta(run_id) / "datos.pkl")
    resumen = {"filas": len(datos), "observaciones": int(n_obs), "fecha_max": str(datos["fecha"].max().date())}
    (_carpeta(run_id) / "datos.json").write_text(json.dumps(resumen))
    log.info("Datos preparados: %s", resumen)


def _datos(run_id: str) -> pd.DataFrame:
    datos = pd.read_pickle(_carpeta(run_id) / "datos.pkl")
    datos.attrs["n_observaciones"] = json.loads((_carpeta(run_id) / "datos.json").read_text())["observaciones"]
    return datos


def dag_entrenar(cfg: Config, run_id: str) -> None:
    repo = Repositorio(cfg.db_url)
    ent = ciclo.entrenar_y_registrar(_datos(run_id), repo.catalogos(), cfg, origen=f"reentrenamiento_{run_id}")
    (_carpeta(run_id) / "entrenamiento.json").write_text(json.dumps(ent, default=str))
    log.info("Candidato registrado: v%s (%s)", ent["version_candidata"], ent["tipo_modelo"])


def dag_decidir(cfg: Config, run_id: str) -> None:
    repo = Repositorio(cfg.db_url)
    ent = json.loads((_carpeta(run_id) / "entrenamiento.json").read_text())
    dec = ciclo.decidir(_datos(run_id), repo.catalogos(), cfg, ent)
    (_carpeta(run_id) / "decision.json").write_text(json.dumps(dec, default=str))
    log.info("Decisión: promover=%s — %s", dec["promover"], dec["motivo"])


def dag_publicar(cfg: Config, run_id: str) -> None:
    """Último paso: mueve el alias (si corresponde) y registra el resultado en la BD.
    Si falla la escritura en la BD tras mover el alias, se revierte el alias."""
    repo = Repositorio(cfg.db_url)
    dec = json.loads((_carpeta(run_id) / "decision.json").read_text())
    ent = json.loads((_carpeta(run_id) / "entrenamiento.json").read_text())
    version_final = ciclo.aplicar_decision(cfg, dec)
    try:
        repo.finalizar_reentrenamiento(run_id, "exitoso", bool(dec["promover"]), version_final, dec["motivo"],
                                       dec["version_candidata"], {"decision": dec, "entrenamiento": ent["metricas"]})
    except Exception:
        if dec["promover"] and dec["version_vigente_previa"]:
            registro.promover(cfg, dec["version_vigente_previa"])
        raise
    log.info("Reentrenamiento %s terminado. Vigente: v%s", run_id, version_final)


def dag_fallo(cfg: Config, run_id: str, motivo: str) -> None:
    repo = Repositorio(cfg.db_url)
    try:
        version = registro.version_vigente(cfg)
    except Exception:  # noqa: BLE001
        version = None
    repo.finalizar_reentrenamiento(run_id, "fallido", False, version, motivo)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="novamercado")
    p.add_argument("comando", choices=["bootstrap", "dag-preparar", "dag-entrenar", "dag-decidir", "dag-publicar",
                                       "dag-fallo"])
    p.add_argument("--run-id")
    p.add_argument("--motivo", default="La ejecución falló")
    a = p.parse_args(argv)
    cfg = Config.desde_entorno()
    if a.comando == "bootstrap":
        bootstrap(cfg)
        return
    if not a.run_id:
        sys.exit("--run-id es obligatorio para los pasos del DAG")
    {"dag-preparar": dag_preparar, "dag-entrenar": dag_entrenar, "dag-decidir": dag_decidir,
     "dag-publicar": dag_publicar}.get(a.comando, lambda c, r: dag_fallo(c, r, a.motivo))(cfg, a.run_id)


if __name__ == "__main__":
    main()
