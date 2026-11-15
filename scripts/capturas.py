"""Capturas de pantalla de MLflow, Airflow y la API como evidencia (``evidencia/capturas/``).

Requiere el producto levantado y Playwright (usa Edge o Chrome ya instalados):
    pip install playwright==1.49.1
    python scripts/capturas.py --airflow http://localhost:8080 --canal chrome
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests
from playwright.sync_api import sync_playwright

MODELO = "novamercado_pronostico_ventas"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--mlflow", default="http://localhost:5000")
    p.add_argument("--airflow", default="http://localhost:8080")
    p.add_argument("--usuario", default=os.environ.get("AIRFLOW_ADMIN_USER", "admin"))
    p.add_argument("--clave", default=os.environ.get("AIRFLOW_ADMIN_PASSWORD", "admin"))
    p.add_argument("--canal", default="chrome", help="chrome o msedge")
    a = p.parse_args()
    out = Path("evidencia/capturas")
    out.mkdir(parents=True, exist_ok=True)

    exp = requests.get(f"{a.mlflow}/api/2.0/mlflow/experiments/get-by-name",
                       params={"experiment_name": "novamercado_pronostico"}).json()["experiment"]["experiment_id"]
    vigente = requests.get(f"{a.mlflow}/api/2.0/mlflow/registered-models/alias",
                           params={"name": MODELO, "alias": "vigente"}).json()["model_version"]

    with sync_playwright() as pw:
        nav = pw.chromium.launch(channel=a.canal, headless=True)
        pag = nav.new_page(viewport={"width": 1600, "height": 1000})

        def foto(url, nombre, espera=3500, completa=False):
            pag.goto(url, wait_until="networkidle")
            pag.wait_for_timeout(espera)
            # cierra avisos emergentes de la interfaz (p. ej. "new Model Registry UI" de MLflow)
            for selector in ("button[aria-label='Close']", ".ant-modal-close", "[data-testid='close-button']"):
                for boton in pag.locator(selector).all():
                    if boton.is_visible():
                        boton.click(timeout=2000)
                        pag.wait_for_timeout(500)
            pag.screenshot(path=str(out / nombre), full_page=completa)
            print("captura:", nombre)

        runs = requests.post(f"{a.mlflow}/api/2.0/mlflow/runs/search",
                             json={"experiment_ids": [exp], "max_results": 50}).json()["runs"]
        ids = json.dumps([r["info"]["run_id"] for r in runs])

        # MLflow: experimentos, comparación de métricas, modelo registrado (versiones + alias), run vigente
        foto(f"{a.mlflow}/#/experiments/{exp}", "01_mlflow_experimento_runs.png")
        foto(f"{a.mlflow}/#/compare-runs?runs={quote(ids)}&experiments={quote(json.dumps([exp]))}",
             "01b_mlflow_comparacion_metricas.png", espera=5000, completa=True)
        foto(f"{a.mlflow}/#/models/{MODELO}", "02_mlflow_modelo_versiones_alias.png", completa=True)
        foto(f"{a.mlflow}/#/models/{MODELO}/versions/{vigente['version']}", "03_mlflow_version_vigente.png", completa=True)
        foto(f"{a.mlflow}/#/experiments/{exp}/runs/{vigente['run_id']}", "04_mlflow_run_vigente_metricas.png",
             completa=True)

        # Airflow: iniciar sesión y mostrar las ejecuciones del DAG
        pag.goto(f"{a.airflow}/login/", wait_until="networkidle")
        pag.fill("input#username", a.usuario)
        pag.fill("input#password", a.clave)
        pag.click("input[type=submit], button[type=submit]")
        pag.wait_for_load_state("networkidle")
        foto(f"{a.airflow}/dags/reentrenamiento_modelo/grid", "05_airflow_dag_ejecuciones.png", espera=5000)
        foto(f"{a.airflow}/dags/reentrenamiento_modelo/grid?tab=graph", "06_airflow_dag_grafo.png", espera=5000)
        foto(f"{a.airflow}/dagrun/list/", "07_airflow_lista_ejecuciones.png", espera=3000)

        # API
        foto(f"{a.api}/docs", "08_api_docs.png", completa=True)
        nav.close()


if __name__ == "__main__":
    main()
