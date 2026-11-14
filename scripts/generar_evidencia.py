"""Genera la evidencia de funcionamiento en ``evidencia/``:

* ``ejemplos_api.md``: solicitudes válidas y defectuosas (catálogo + casos nuevos) y sus respuestas.
* ``mlflow.json``: experimentos, runs con métricas y versiones del modelo con sus etiquetas/alias.
* ``airflow_dag_runs.json``: ejecuciones del DAG de reentrenamiento y el estado de sus tareas.
* ``base_datos.json``: conteos de las tablas de operación.

Uso:  python scripts/generar_evidencia.py --datos datos
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import requests

CASOS_NUEVOS = {
    "N01 campos camelCase, lista como objeto, nombre de tienda": {
        "tiendaId": "NovaMercado Mixco", "Fecha": "2026-03-02",
        "items": {"Lácteo": "2", "BEBIDAS": 1, "Snacks y Dulces": 0}},
    "N02 fecha ambigua y promoción negativa": {
        "tienda_id": 7, "fecha": "03/04/2026",
        "familias": [{"familia_id": "carnes", "en_promocion": -2}, {"familia_id": "abarrotes", "en_promocion": 1}]},
    "N03 familia inexistente y campo desconocido": {
        "tienda_id": 1, "fecha": "2026-03-02", "sistema": "pos-v3",
        "familias": [{"familia_id": "electronica", "en_promocion": 1}, {"familia_id": "licores", "en_promocion": 0}]},
    "N04 tienda inexistente (rechazo)": {"tienda_id": 42, "fecha": "2026-03-02",
                                         "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]},
    "N05 fecha imposible (rechazo)": {"tienda_id": 5, "fecha": "2026-02-30",
                                      "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]},
    "N06 tienda 10 antes de su apertura (rechazo)": {"tienda_id": 10, "fecha": "2025-01-10",
                                                     "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]},
}


def recortar(cuerpo, n=3):
    """Acorta listas largas de la respuesta para que el documento sea legible."""
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("predicciones"), list) and len(cuerpo["predicciones"]) > n:
        cuerpo = {**cuerpo, "predicciones": cuerpo["predicciones"][:n] + [f"... ({len(cuerpo['predicciones']) - n} más)"]}
    return cuerpo


def ejemplos_api(api: str, datos: Path) -> str:
    lineas = ["# Ejemplos de respuestas de la API", "",
              "Generado con `scripts/generar_evidencia.py` contra el producto levantado con Docker Compose.", ""]
    casos = [("Predicción válida", "/v1/prediccion", datos / "ejemplos/prediccion_valida.json")]
    for f in sorted((datos / "ejemplos/errores").glob("*.json")):
        ruta = "/v1/observaciones" if f.name >= "E08" else "/v1/prediccion"
        casos.append((f.stem, ruta, f))
    casos.append(("Observación válida", "/v1/observaciones", datos / "ejemplos/observacion_valida.json"))
    casos.append(("E09 reenvío idéntico (idempotencia)", "/v1/observaciones", datos / "ejemplos/observacion_valida.json"))
    for titulo, ruta, archivo in casos:
        cuerpo = json.loads(archivo.read_text(encoding="utf-8"))
        r = requests.post(f"{api}{ruta}", json=cuerpo, timeout=30)
        lineas += [f"## {titulo}", "", f"`POST {ruta}` (archivo `{archivo.name}`) → **HTTP {r.status_code}**", "",
                   "```json", json.dumps(recortar(r.json()), indent=2, ensure_ascii=False), "```", ""]
    lineas += ["# Casos fuera del catálogo", ""]
    for titulo, cuerpo in CASOS_NUEVOS.items():
        r = requests.post(f"{api}/v1/prediccion", json=cuerpo, timeout=30)
        lineas += [f"## {titulo}", "", "Solicitud:", "```json", json.dumps(cuerpo, indent=2, ensure_ascii=False), "```",
                   f"Respuesta **HTTP {r.status_code}**:", "```json",
                   json.dumps(recortar(r.json()), indent=2, ensure_ascii=False), "```", ""]
    for ruta in ["/modelo", "/health"]:
        r = requests.get(f"{api}{ruta}", timeout=30)
        lineas += [f"## GET {ruta} → HTTP {r.status_code}", "```json", json.dumps(r.json(), indent=2, ensure_ascii=False),
                   "```", ""]
    return "\n".join(lineas)


def evidencia_mlflow(url: str, nombre_modelo: str) -> dict:
    exps = requests.post(f"{url}/api/2.0/mlflow/experiments/search", json={"max_results": 50}).json()["experiments"]
    salida = {"experimentos": [], "modelo_registrado": None}
    for e in exps:
        runs = requests.post(f"{url}/api/2.0/mlflow/runs/search",
                             json={"experiment_ids": [e["experiment_id"]], "max_results": 200,
                                   "order_by": ["attributes.start_time ASC"]}).json().get("runs", [])
        salida["experimentos"].append({
            "nombre": e["name"], "id": e["experiment_id"],
            "runs": [{"nombre": r["info"].get("run_name"), "run_id": r["info"]["run_id"],
                      "metricas": {m["key"]: round(m["value"], 4) for m in r["data"].get("metrics", [])
                                   if m["key"] in ("costo_total", "wape", "mae", "sesgo_pct", "costo_sugerir_media")},
                      "etiquetas": {t["key"]: t["value"] for t in r["data"].get("tags", [])
                                    if not t["key"].startswith("mlflow.")}} for r in runs]})
    rm = requests.get(f"{url}/api/2.0/mlflow/registered-models/get", params={"name": nombre_modelo}).json()
    versiones = requests.get(f"{url}/api/2.0/mlflow/model-versions/search",
                             params={"filter": f"name='{nombre_modelo}'", "max_results": 100}).json()
    salida["modelo_registrado"] = {
        "nombre": nombre_modelo, "aliases": rm.get("registered_model", {}).get("aliases", []),
        "versiones": sorted([{"version": v["version"], "run_id": v["run_id"],
                              "etiquetas": {t["key"]: t["value"] for t in v.get("tags", [])}}
                             for v in versiones.get("model_versions", [])], key=lambda v: int(v["version"]))}
    return salida


def evidencia_airflow(url: str, auth) -> dict:
    base = f"{url}/api/v1/dags/reentrenamiento_modelo"
    runs = requests.get(f"{base}/dagRuns", params={"order_by": "start_date"}, auth=auth).json().get("dag_runs", [])
    salida = []
    for r in runs:
        tareas = requests.get(f"{base}/dagRuns/{r['dag_run_id']}/taskInstances", auth=auth).json()
        salida.append({"dag_run_id": r["dag_run_id"], "estado": r["state"], "inicio": r["start_date"],
                       "fin": r["end_date"],
                       "tareas": {t["task_id"]: t["state"] for t in tareas.get("task_instances", [])}})
    return {"dag_id": "reentrenamiento_modelo", "ejecuciones": salida}


def conteos_bd() -> dict:
    consulta = ("SELECT json_build_object("
                "'solicitudes', (SELECT count(*) FROM solicitudes),"
                "'solicitudes_por_estado', (SELECT json_object_agg(k, n) FROM (SELECT tipo||':'||codigo_http||':'||"
                "coalesce(estado_calidad,'-') k, count(*) n FROM solicitudes GROUP BY 1) s),"
                "'predicciones', (SELECT count(*) FROM predicciones),"
                "'correcciones', (SELECT count(*) FROM correcciones),"
                "'observaciones', (SELECT count(*) FROM observaciones),"
                "'reentrenamientos', (SELECT json_agg(r) FROM (SELECT id, estado, promovido, "
                "version, motivo FROM reentrenamientos ORDER BY solicitado_en) r))")
    usuario = os.environ.get("APP_DB_USER", "novamercado")
    base = os.environ.get("APP_DB_NAME", "novamercado")
    r = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", usuario, "-d", base, "-At", "-c", consulta],
                       capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--mlflow", default="http://localhost:5000")
    p.add_argument("--airflow", default=os.environ.get("AIRFLOW_URL_HOST", "http://localhost:8080"))
    p.add_argument("--airflow-usuario", default=os.environ.get("AIRFLOW_ADMIN_USER", "admin"))
    p.add_argument("--airflow-clave", default=os.environ.get("AIRFLOW_ADMIN_PASSWORD", "admin"))
    p.add_argument("--datos", default="datos")
    a = p.parse_args()
    out = Path("evidencia")
    out.mkdir(exist_ok=True)
    (out / "ejemplos_api.md").write_text(ejemplos_api(a.api, Path(a.datos)), encoding="utf-8")
    (out / "mlflow.json").write_text(json.dumps(evidencia_mlflow(a.mlflow, "novamercado_pronostico_ventas"),
                                                indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "airflow_dag_runs.json").write_text(json.dumps(evidencia_airflow(a.airflow, (a.airflow_usuario, a.airflow_clave)),
                                                          indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "base_datos.json").write_text(json.dumps(conteos_bd(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("Evidencia generada en", out.resolve())


if __name__ == "__main__":
    main()
