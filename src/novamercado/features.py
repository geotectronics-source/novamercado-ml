"""Ingeniería de variables.

Regla de oro: **la misma función** construye las variables para entrenar y para servir.
Así se evita el *training/serving skew*.

Todas las variables de rezago se calculan con datos ESTRICTAMENTE anteriores a la fecha
que se pronostica (``shift(1)`` como mínimo). Las promociones del día sí se usan porque se
conocen por la solicitud de pronóstico.

Entrada ``panel``: filas (fecha, tienda_id, familia_id, ventas, en_promocion).
  * ``ventas`` puede ser NaN (día sin observación o fila objetivo a pronosticar).
  * ``en_promocion`` puede ser NaN (observaciones sin promoción conocida).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .catalogos import Catalogos

CLAVE = ["tienda_id", "familia_id", "fecha"]

# Variables numéricas que entran al modelo (el orden importa para LightGBM).
VARIABLES_NUMERICAS = [
    "en_promocion",
    "dow",
    "dia_mes",
    "mes",
    "dias_para_fin_mes",
    "es_feriado",
    "es_comercial",
    "es_pago",
    "es_medio_dia",
    "dias_a_feriado",
    "dias_desde_feriado",
    "dias_a_comercial",
    "dias_desde_pago",
    "rel_lag1",
    "rel_lag7",
    "rel_lag14",
    "rel_media7",
    "rel_media_dow",
    "rel_lag364",
    "estacional_anual",
    "cv28",
    "dias_sin_obs",
    "log_base",
]
VARIABLES_CATEGORICAS = ["tienda_id", "familia_id", "tipo_tienda"]
VARIABLES = VARIABLES_NUMERICAS + VARIABLES_CATEGORICAS

TOPE_DISTANCIA = 10  # distancias a eventos se truncan para que el árbol no extrapole


def _calendario_eventos(cat: Catalogos, fechas: pd.DatetimeIndex) -> pd.DataFrame:
    """Variables de feriados/fechas comerciales por (ciudad, fecha).

    ``ambito`` vale 'nacional' o el nombre de la ciudad, igual que ``tiendas.ciudad``.
    """
    inicio = fechas.min() - pd.Timedelta(days=TOPE_DISTANCIA + 1)
    fin = fechas.max() + pd.Timedelta(days=TOPE_DISTANCIA + 1)
    rango = pd.date_range(inicio, fin, freq="D")
    fer = cat.feriados.copy()
    fer["fecha"] = pd.to_datetime(fer["fecha"])
    salida = []
    for ciudad in cat.tiendas["ciudad"].unique():
        aplica = fer[(fer["ambito"] == "nacional") | (fer["ambito"] == ciudad)]
        df = pd.DataFrame(index=rango)
        for tipo, col in [("feriado", "es_feriado"), ("comercial", "es_comercial"),
                          ("pago", "es_pago"), ("medio_dia", "es_medio_dia")]:
            dias = set(aplica.loc[aplica["tipo"] == tipo, "fecha"])
            df[col] = df.index.isin(dias).astype(np.int8)
        cierre = (df["es_feriado"] | df["es_medio_dia"]).astype(bool)
        df["dias_a_feriado"] = _distancia_adelante(cierre)
        df["dias_desde_feriado"] = _distancia_atras(cierre)
        df["dias_a_comercial"] = _distancia_adelante(df["es_comercial"].astype(bool))
        df["dias_desde_pago"] = _distancia_atras(df["es_pago"].astype(bool))
        df["ciudad"] = ciudad
        salida.append(df.rename_axis("fecha").reset_index())
    return pd.concat(salida, ignore_index=True)


def _distancia_adelante(marca: pd.Series) -> np.ndarray:
    """Días hasta el próximo evento (0 si hoy), truncado en TOPE_DISTANCIA."""
    pos = np.where(marca.values, np.arange(len(marca)), np.nan)
    sig = pd.Series(pos).bfill().values
    dist = sig - np.arange(len(marca))
    return np.nan_to_num(np.minimum(dist, TOPE_DISTANCIA), nan=TOPE_DISTANCIA).astype(np.int16)


def _distancia_atras(marca: pd.Series) -> np.ndarray:
    pos = np.where(marca.values, np.arange(len(marca)), np.nan)
    ant = pd.Series(pos).ffill().values
    dist = np.arange(len(marca)) - ant
    return np.nan_to_num(np.minimum(dist, TOPE_DISTANCIA), nan=TOPE_DISTANCIA).astype(np.int16)


def _matriz(panel: pd.DataFrame, columna: str) -> pd.DataFrame:
    """Pivotea a matriz ancha fecha × (tienda, familia) con calendario diario completo."""
    ancho = panel.pivot_table(index="fecha", columns=["tienda_id", "familia_id"], values=columna,
                              aggfunc="last", dropna=False)
    rango = pd.date_range(panel["fecha"].min(), panel["fecha"].max(), freq="D")
    return ancho.reindex(rango)


def _apilar(ancho: pd.DataFrame, nombre: str) -> pd.Series:
    s = ancho.stack(level=[0, 1], future_stack=True)
    s.index = s.index.set_names(["fecha", "tienda_id", "familia_id"])
    return s.rename(nombre)


def construir_features(panel: pd.DataFrame, cat: Catalogos) -> pd.DataFrame:
    """Devuelve una fila por (tienda, familia, fecha) del panel con todas las variables.

    Columnas extra útiles: ``ventas`` (objetivo, puede ser NaN), ``base`` (nivel reciente
    contra el que se expresa el objetivo) y ``media_dow`` (baseline ingenuo estacional).
    """
    panel = panel.copy()
    panel["fecha"] = pd.to_datetime(panel["fecha"])
    panel["tienda_id"] = panel["tienda_id"].astype(int)
    panel = panel.drop_duplicates(CLAVE, keep="last")

    V = _matriz(panel, "ventas").astype(float)
    P = _matriz(panel, "en_promocion").astype(float)
    pasado = V.shift(1)  # todo lo que sigue usa SOLO días anteriores

    lags = {k: V.shift(k) for k in (1, 7, 14, 21, 28, 364)}
    media7 = pasado.rolling(7, min_periods=3).mean()
    media28 = pasado.rolling(28, min_periods=7).mean()
    std28 = pasado.rolling(28, min_periods=7).std()
    media_dow = pd.concat([lags[k] for k in (7, 14, 21, 28)]).groupby(level=0).mean()
    media_dow = media_dow.reindex(V.index)

    # Nivel conocido: media de las últimas 28 observaciones existentes (aunque sean viejas).
    nivel = pd.DataFrame(index=V.index, columns=V.columns, dtype=float)
    dias_sin = pd.DataFrame(index=V.index, columns=V.columns, dtype=float)
    idx = np.arange(len(V.index), dtype=float)
    for col in V.columns:
        s = V[col]
        obs = s.dropna()
        nivel[col] = obs.rolling(28, min_periods=1).mean().reindex(V.index).ffill().shift(1)
        ultima = pd.Series(np.where(s.notna(), idx, np.nan), index=V.index).ffill().shift(1)
        dias_sin[col] = idx - ultima.values

    base = media28.where(pasado.rolling(28, min_periods=1).count() >= 7, nivel)

    # Estacionalidad anual: cómo cambió hace un año la semana objetivo respecto
    # a las 4 semanas previas (misma definición que ``base``).
    semana_hace_anio = V.shift(361).rolling(7, min_periods=3).mean()
    base_hace_anio = V.shift(365).rolling(28, min_periods=7).mean()
    estacional = semana_hace_anio / base_hace_anio

    columnas = {
        "ventas": V, "en_promocion": P, "base": base, "media_dow": media_dow,
        "lag1": lags[1], "lag7": lags[7], "lag14": lags[14], "lag364": lags[364],
        "media7": media7, "media28": media28, "std28": std28,
        "estacional_anual": estacional, "dias_sin_obs": dias_sin,
    }
    largo = pd.concat([_apilar(m, n) for n, m in columnas.items()], axis=1).reset_index()
    # Solo filas presentes en el panel (no inventamos días que nadie pidió).
    largo = panel[CLAVE].merge(largo, on=CLAVE, how="left")

    b = largo["base"].where(largo["base"] > 0)
    for c in ("lag1", "lag7", "lag14", "media7", "media_dow", "lag364"):
        largo[f"rel_{c}"] = largo[c] / b
    largo["cv28"] = largo["std28"] / b
    largo["log_base"] = np.log1p(largo["base"])

    f = largo["fecha"]
    largo["dow"] = f.dt.dayofweek
    largo["dia_mes"] = f.dt.day
    largo["mes"] = f.dt.month
    largo["dias_para_fin_mes"] = (f.dt.days_in_month - f.dt.day).astype(int)

    tiendas = cat.tiendas[["tienda_id", "ciudad", "tipo"]].rename(columns={"tipo": "tipo_tienda"})
    largo = largo.merge(tiendas, on="tienda_id", how="left")
    eventos = _calendario_eventos(cat, pd.DatetimeIndex(largo["fecha"].unique()))
    largo = largo.merge(eventos, on=["ciudad", "fecha"], how="left")

    largo["tienda_id"] = pd.Categorical(largo["tienda_id"], categories=cat.ids_tiendas)
    largo["familia_id"] = pd.Categorical(largo["familia_id"], categories=cat.ids_familias)
    largo["tipo_tienda"] = pd.Categorical(largo["tipo_tienda"],
                                          categories=sorted(cat.tiendas["tipo"].unique()))
    return largo
