"""Configuración por variables de entorno (las credenciales nunca van en el código)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(nombre: str, defecto: str | None = None) -> str:
    valor = os.environ.get(nombre, defecto)
    if valor is None:
        raise RuntimeError(f"Falta la variable de entorno {nombre}")
    return valor


@dataclass(frozen=True)
class Config:
    db_url: str
    mlflow_url: str
    airflow_url: str
    airflow_usuario: str
    airflow_clave: str
    nombre_modelo: str
    alias_modelo: str
    experimento: str
    carpeta_datos: str
    carpeta_cache: str
    intervalo_monitor_s: int
    intervalo_recarga_s: int
    margen_reemplazo: float
    dag_id: str

    @classmethod
    def desde_entorno(cls) -> "Config":
        usuario = _env("APP_DB_USER", "novamercado")
        clave = _env("APP_DB_PASSWORD", "novamercado")
        host = _env("APP_DB_HOST", "localhost")
        puerto = _env("APP_DB_PORT", "5432")
        base = _env("APP_DB_NAME", "novamercado")
        return cls(
            db_url=os.environ.get("APP_DB_URL") or f"postgresql+psycopg2://{usuario}:{clave}@{host}:{puerto}/{base}",
            mlflow_url=_env("MLFLOW_TRACKING_URI", "http://localhost:5000"),
            airflow_url=_env("AIRFLOW_URL", "http://localhost:8080"),
            airflow_usuario=_env("AIRFLOW_API_USER", "admin"),
            airflow_clave=_env("AIRFLOW_API_PASSWORD", "admin"),
            nombre_modelo=_env("MODELO_NOMBRE", "novamercado_pronostico_ventas"),
            alias_modelo=_env("MODELO_ALIAS", "vigente"),
            experimento=_env("MLFLOW_EXPERIMENTO", "novamercado_pronostico"),
            carpeta_datos=_env("CARPETA_DATOS", "/datos"),
            carpeta_cache=_env("CARPETA_CACHE_MODELO", "/cache_modelo"),
            intervalo_monitor_s=int(_env("INTERVALO_MONITOR_S", "15")),
            intervalo_recarga_s=int(_env("INTERVALO_RECARGA_S", "20")),
            margen_reemplazo=float(_env("MARGEN_REEMPLAZO", "0.01")),
            dag_id=_env("DAG_REENTRENAMIENTO", "reentrenamiento_modelo"),
        )
