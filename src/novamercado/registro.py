"""Integración con MLflow: experimentos, Model Registry, alias del modelo vigente.

El modelo se guarda como *pyfunc* que envuelve un ``Pronosticador``. El servicio y el DAG
comparten el paquete ``novamercado``, así que el objeto se des-serializa sin código extra.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import mlflow
import mlflow.pyfunc
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from .config import Config
from .modelo import Pronosticador

REQUISITOS_MODELO = ["pandas==2.2.3", "numpy==1.26.4", "lightgbm==4.5.0", "scikit-learn==1.5.2", "scipy==1.17.1"]


class ModeloPyfunc(mlflow.pyfunc.PythonModel):
    """Envoltorio MLflow. ``predict`` recibe las variables ya construidas."""

    def __init__(self, pronosticador: Pronosticador):
        self.pronosticador = pronosticador

    def predict(self, context, model_input, params=None):  # noqa: D401 - firma de MLflow
        return self.pronosticador.predecir(model_input)


def cliente(cfg: Config) -> MlflowClient:
    mlflow.set_tracking_uri(cfg.mlflow_url)
    return MlflowClient(tracking_uri=cfg.mlflow_url)


def version_vigente(cfg: Config, c: MlflowClient | None = None) -> str | None:
    c = c or cliente(cfg)
    try:
        return str(c.get_model_version_by_alias(cfg.nombre_modelo, cfg.alias_modelo).version)
    except MlflowException as e:
        if "RESOURCE_DOES_NOT_EXIST" in str(e.error_code) or "not found" in str(e).lower():
            return None
        raise


def cargar_version(cfg: Config, version: str) -> Pronosticador:
    mlflow.set_tracking_uri(cfg.mlflow_url)
    modelo = mlflow.pyfunc.load_model(f"models:/{cfg.nombre_modelo}/{version}")
    return modelo.unwrap_python_model().pronosticador


def registrar_run(cfg: Config, nombre_run: str, modelo: Pronosticador, metricas: dict, params: dict,
                  etiquetas: dict, extras: dict | None = None) -> str:
    """Crea un run con métricas, parámetros, artefactos y el modelo pyfunc. Devuelve run_id."""
    mlflow.set_tracking_uri(cfg.mlflow_url)
    mlflow.set_experiment(cfg.experimento)
    with mlflow.start_run(run_name=nombre_run) as run:
        mlflow.set_tags(etiquetas)
        mlflow.log_params({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()})
        mlflow.log_metrics({k: float(v) for k, v in metricas.items()})
        with tempfile.TemporaryDirectory() as d:
            Path(d, "multiplicadores.json").write_text(json.dumps(modelo.multiplicadores, indent=2))
            Path(d, "metadatos.json").write_text(json.dumps(modelo.metadatos, indent=2, default=str))
            for nombre, contenido in (extras or {}).items():
                ruta = Path(d, nombre)
                if hasattr(contenido, "to_csv"):
                    contenido.to_csv(ruta, index=False)
                else:
                    ruta.write_text(json.dumps(contenido, indent=2, default=str, ensure_ascii=False))
            mlflow.log_artifacts(d, artifact_path="reportes")
        mlflow.pyfunc.log_model(artifact_path="modelo", python_model=ModeloPyfunc(modelo),
                                pip_requirements=REQUISITOS_MODELO)
        return run.info.run_id


def registrar_version(cfg: Config, run_id: str, etiquetas: dict) -> str:
    mlflow.set_tracking_uri(cfg.mlflow_url)
    mv = mlflow.register_model(f"runs:/{run_id}/modelo", cfg.nombre_modelo)
    c = cliente(cfg)
    for k, v in etiquetas.items():
        c.set_model_version_tag(cfg.nombre_modelo, mv.version, k, str(v))
    return str(mv.version)


def promover(cfg: Config, version: str) -> None:
    cliente(cfg).set_registered_model_alias(cfg.nombre_modelo, cfg.alias_modelo, version)


def etiquetar_version(cfg: Config, version: str, etiquetas: dict) -> None:
    c = cliente(cfg)
    for k, v in etiquetas.items():
        c.set_model_version_tag(cfg.nombre_modelo, version, k, str(v))
