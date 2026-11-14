"""Pruebas de operación (requieren el producto levantado con docker compose).

1. Caída de MLflow: /health debe pasar a 'degradado' en < 60 s, la API debe seguir
   pronosticando y un reentrenamiento debe fallar SIN cambiar el modelo vigente.
2. Regreso de MLflow: /health vuelve a 'ok' en < 120 s.
3. Reinicio del producto (down + up, sin borrar volúmenes): conserva modelo y datos, no
   repite el bootstrap y queda listo en < 10 min.

Uso:  python scripts/prueba_resiliencia.py [--api http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import requests

SOLICITUD = {"tienda_id": 3, "fecha": "2026-03-02",
             "familias": [{"familia_id": "abarrotes", "en_promocion": 2}, {"familia_id": "lacteos", "en_promocion": 0}]}


def compose(*args):
    print("$ docker compose", " ".join(args))
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def esperar(api, condicion, limite, pausa=3):
    t0 = time.time()
    while time.time() - t0 < limite:
        try:
            r = requests.get(f"{api}/health", timeout=5)
            if condicion(r):
                return round(time.time() - t0, 1), r.json()
        except requests.RequestException:
            pass
        time.sleep(pausa)
    return None, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--salida", default="evidencia/resiliencia.json")
    api = p.parse_args().api
    resultado = {}

    version_antes = requests.get(f"{api}/modelo").json()["version"]
    resultado["modelo_antes"] = version_antes

    # 1) caída de MLflow
    compose("stop", "mlflow")
    t, cuerpo = esperar(api, lambda r: r.json().get("estado") == "degradado", 90)
    resultado["segundos_hasta_degradado"] = t
    resultado["health_degradado"] = cuerpo
    r = requests.post(f"{api}/v1/prediccion", json=SOLICITUD, timeout=30)
    resultado["prediccion_con_mlflow_caido"] = {"codigo": r.status_code, "version": r.json().get("version_modelo")}
    rid = requests.post(f"{api}/admin/reentrenar", timeout=30).json()["id"]
    t0 = time.time()
    while True:
        e = requests.get(f"{api}/admin/reentrenar/{rid}", timeout=30).json()
        if e["estado"] != "en_curso" or time.time() - t0 > 600:
            break
        time.sleep(5)
    resultado["reentrenamiento_con_mlflow_caido"] = {**e, "duracion_s": round(time.time() - t0, 1)}
    resultado["modelo_tras_fallo"] = requests.get(f"{api}/modelo").json()["version"]

    # 2) regreso de MLflow
    compose("start", "mlflow")
    t, cuerpo = esperar(api, lambda r: r.json().get("estado") == "ok", 180)
    resultado["segundos_hasta_ok"] = t

    # 3) reinicio completo conservando volúmenes
    compose("down")
    t0 = time.time()
    compose("up", "-d")
    t, cuerpo = esperar(api, lambda r: r.status_code == 200 and r.json().get("estado") == "ok", 600, pausa=5)
    resultado["reinicio_segundos_hasta_ok"] = round(time.time() - t0, 1) if t is not None else None
    resultado["modelo_tras_reinicio"] = requests.get(f"{api}/modelo").json()["version"]
    log = subprocess.run(["docker", "compose", "logs", "bootstrap"], capture_output=True, text=True).stdout
    resultado["bootstrap_tras_reinicio"] = [l.split("novamercado.cli: ")[-1] for l in log.splitlines()
                                            if "novamercado.cli" in l][-2:]
    r = requests.post(f"{api}/v1/prediccion", json=SOLICITUD, timeout=30)
    resultado["prediccion_tras_reinicio"] = r.status_code

    ok = (resultado["segundos_hasta_degradado"] is not None and resultado["segundos_hasta_degradado"] < 60
          and resultado["prediccion_con_mlflow_caido"]["codigo"] == 200
          and resultado["reentrenamiento_con_mlflow_caido"]["estado"] == "fallido"
          and resultado["modelo_tras_fallo"] == version_antes
          and resultado["segundos_hasta_ok"] is not None and resultado["segundos_hasta_ok"] < 120
          and resultado["modelo_tras_reinicio"] == version_antes and resultado["prediccion_tras_reinicio"] == 200)
    resultado["todas_las_verificaciones_ok"] = ok
    Path(p.parse_args().salida).write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
