"""Simulador de operación diaria (imita al programa de evaluación del enunciado).

Para cada día simulado D:
  1. Envía las observaciones (ventas reales) del día D-1.
  2. Cada tienda solicita el pronóstico de D; una fracción llega con errores (incluidos
     errores que NO están en el catálogo).
  3. Cada ``--reentrenar-cada`` días dispara un reentrenamiento y espera el resultado.
Al final calcula el costo de las cantidades sugeridas con ``costos.csv``.

Las ventas "reales" son sintéticas: el valor del mismo día de la semana del año anterior,
escalado por el crecimiento observado, con ruido de Poisson y un **cambio de demanda**
a partir de ``--dia-cambio`` (bebidas y licores +40 %, panadería −30 %).

Uso:
    python scripts/simulador.py --api http://localhost:8000 --datos datos --dias 21
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

CAMBIO = {"bebidas": 1.4, "licores": 1.4, "panaderia": 0.7}


def generar_reales(hist: pd.DataFrame, inicio: date, dias: int, dia_cambio: int, semilla: int) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    h = hist.copy()
    h["fecha"] = pd.to_datetime(h["fecha"])
    fin_hist = h["fecha"].max()
    recientes = h[h["fecha"] > fin_hist - pd.Timedelta(days=56)].groupby(["tienda_id", "familia_id"])["ventas"].mean()
    hace_anio = h[(h["fecha"] > fin_hist - pd.Timedelta(days=56 + 364)) & (h["fecha"] <= fin_hist - pd.Timedelta(days=364))]
    crec = (recientes / hace_anio.groupby(["tienda_id", "familia_id"])["ventas"].mean()).fillna(1.0).clip(0.5, 2.0)
    indice = h.set_index(["fecha", "tienda_id", "familia_id"])
    filas = []
    for i in range(dias):
        d = pd.Timestamp(inicio + timedelta(days=i))
        for (t, f), g in crec.items():
            ref = d - pd.Timedelta(days=364)
            if (ref, t, f) in indice.index:
                base, promo = indice.loc[(ref, t, f), ["ventas", "en_promocion"]]
            else:  # tienda nueva sin historia de hace un año
                base, promo = recientes[(t, f)], 0
                g = 1.0
            factor = CAMBIO.get(f, 1.0) if i >= dia_cambio else 1.0
            filas.append((d.date(), t, f, int(rng.poisson(max(base * g * factor, 0.1))), int(promo)))
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


# --------------------------------------------------------------------------- errores inyectados
def _e_tienda(s):
    s["tienda_id"] = random.choice([f"T{s['tienda_id']:02d}", str(s["tienda_id"]), float(s["tienda_id"])])


def _e_familia(s):
    i = random.randrange(len(s["familias"]))
    s["familias"][i]["familia_id"] = random.choice([s["familias"][i]["familia_id"].upper() + " ",
                                                    s["familias"][i]["familia_id"].replace("_", " ").title()])


def _e_fecha(s):
    d = date.fromisoformat(s["fecha"])
    s["fecha"] = random.choice([d.strftime("%d/%m/%Y"), f"{s['fecha']}T00:00:00", d.strftime("%Y%m%d")])


def _e_promo(s):
    i = random.randrange(len(s["familias"]))
    s["familias"][i]["en_promocion"] = random.choice([str(s["familias"][i]["en_promocion"]),
                                                      float(s["familias"][i]["en_promocion"])])


def _e_faltan(s):
    s["familias"] = s["familias"][2:]


def _e_campo(s):  # fuera del catálogo: camelCase y lista con otro nombre
    s["tiendaId"] = s.pop("tienda_id")
    s["items"] = s.pop("familias")


def _e_extra(s):  # fuera del catálogo: campo desconocido y familia inexistente
    s["sistema"] = "pos-v3"
    s["familias"].append({"familia_id": "electronica", "en_promocion": 1})


def _e_rechazo(s):  # debe responder 422
    s["tienda_id"] = random.choice([99, "tienda desconocida", None])


ERRORES = [_e_tienda, _e_familia, _e_fecha, _e_promo, _e_faltan, _e_campo, _e_extra, _e_rechazo]


def _obs_con_errores(o):
    i = random.randrange(len(o["ventas"]))
    v = o["ventas"][i]["ventas"]
    o["ventas"][i]["ventas"] = random.choice([f"{v:,}", f"{v},0", -abs(v) - 1])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--datos", default="datos")
    p.add_argument("--inicio", default="2026-03-01")
    p.add_argument("--dias", type=int, default=21)
    p.add_argument("--dia-cambio", type=int, default=7)
    p.add_argument("--reentrenar-cada", type=int, default=7)
    p.add_argument("--prob-error", type=float, default=0.25)
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--salida", default="evidencia/simulacion.json")
    a = p.parse_args()
    random.seed(a.semilla)

    datos = Path(a.datos)
    hist = pd.read_csv(datos / "historico_ventas.csv")
    costos = pd.read_csv(datos / "costos.csv").set_index("familia_id")
    inicio = date.fromisoformat(a.inicio)
    reales = generar_reales(hist, inicio, a.dias, a.dia_cambio, a.semilla)
    sesion = requests.Session()
    registro, reentrenamientos, estados = [], [], {}

    for i in range(a.dias):
        d = inicio + timedelta(days=i)
        # 1) observaciones del día anterior
        if i > 0:
            ayer = reales[reales["fecha"] == d - timedelta(days=1)]
            for t, g in ayer.groupby("tienda_id"):
                o = {"tienda_id": int(t), "fecha": str(d - timedelta(days=1)),
                     "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(g["familia_id"], g["ventas"])]}
                if random.random() < a.prob_error / 2:
                    _obs_con_errores(o)
                r = sesion.post(f"{a.api}/v1/observaciones", json=o, timeout=30)
                estados[f"obs_{r.status_code}"] = estados.get(f"obs_{r.status_code}", 0) + 1
        # 2) solicitudes de pronóstico
        hoy = reales[reales["fecha"] == d]
        for t, g in hoy.groupby("tienda_id"):
            s = {"tienda_id": int(t), "fecha": str(d),
                 "familias": [{"familia_id": f, "en_promocion": int(pr)} for f, pr in zip(g["familia_id"], g["en_promocion"])]}
            error = None
            if random.random() < a.prob_error:
                fn = random.choice(ERRORES)
                error = fn.__name__
                s = copy.deepcopy(s)
                fn(s)
            t0 = time.time()
            r = sesion.post(f"{a.api}/v1/prediccion", json=s, timeout=30)
            lat = time.time() - t0
            clave = f"pred_{r.status_code}" + (f"_{r.json()['calidad']['estado']}" if r.ok else "")
            estados[clave] = estados.get(clave, 0) + 1
            if r.ok:
                cuerpo = r.json()
                real = dict(zip(g["familia_id"], g["ventas"]))
                for pr in cuerpo["predicciones"]:
                    y = real[pr["familia_id"]]
                    cf, cs = costos.loc[pr["familia_id"], ["costo_faltante", "costo_sobrante"]]
                    registro.append({"fecha": str(d), "tienda_id": int(t), "familia_id": pr["familia_id"],
                                     "real": int(y), "esperado": pr["venta_esperada"],
                                     "sugerido": pr["cantidad_sugerida"], "version": cuerpo["version_modelo"],
                                     "error_inyectado": error, "latencia_s": round(lat, 3),
                                     "costo": cf * max(y - pr["cantidad_sugerida"], 0) + cs * max(pr["cantidad_sugerida"] - y, 0),
                                     "costo_media": cf * max(y - round(pr["venta_esperada"]), 0)
                                     + cs * max(round(pr["venta_esperada"]) - y, 0)})
            elif error != "_e_rechazo":
                print(f"  ! {d} tienda {t}: {r.status_code} {r.text[:150]} (error {error})")
        # 3) reentrenamiento periódico
        if (i + 1) % a.reentrenar_cada == 0:
            r = sesion.post(f"{a.api}/admin/reentrenar", timeout=30)
            rid = r.json().get("id")
            t0 = time.time()
            while True:
                e = sesion.get(f"{a.api}/admin/reentrenar/{rid}", timeout=30).json()
                if e["estado"] != "en_curso" or time.time() - t0 > 660:
                    break
                time.sleep(5)
            e["duracion_s"] = round(time.time() - t0, 1)
            e["dia"] = str(d)
            # ¿El servicio ya usa el modelo vigente? (debe ocurrir en < 2 min, sin reinicio)
            t1 = time.time()
            while e.get("promovido") and sesion.get(f"{a.api}/modelo").json()["version"] != e["version"]:
                if time.time() - t1 > 150:
                    break
                time.sleep(5)
            e["segundos_hasta_usar_modelo"] = round(time.time() - t1, 1) if e.get("promovido") else None
            reentrenamientos.append(e)
            print(f"{d} reentrenamiento: {e}")
        dia = pd.DataFrame([x for x in registro if x["fecha"] == str(d)])
        if not dia.empty:
            print(f"{d}: costo {dia['costo'].sum():,.0f} (sugerir media: {dia['costo_media'].sum():,.0f}) "
                  f"WAPE {abs(dia['esperado'] - dia['real']).sum() / dia['real'].sum():.3f} v{dia['version'].iloc[-1]}")

    df = pd.DataFrame(registro)
    resumen = {
        "dias": a.dias, "solicitudes_por_estado": estados, "reentrenamientos": reentrenamientos,
        "costo_total": round(float(df["costo"].sum()), 1),
        "costo_si_se_sugiriera_la_media": round(float(df["costo_media"].sum()), 1),
        "wape": round(float(abs(df["esperado"] - df["real"]).sum() / df["real"].sum()), 4),
        "latencia_p95_s": round(float(df.groupby(["fecha", "tienda_id"])["latencia_s"].first().quantile(0.95)), 3),
        "costo_por_semana": {str(k): round(float(v), 1) for k, v in
                             df.assign(semana=pd.to_datetime(df["fecha"]).dt.isocalendar().week)
                             .groupby("semana")["costo"].sum().items()},
    }
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
