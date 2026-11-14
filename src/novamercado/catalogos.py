"""Catálogos del negocio: tiendas, familias, costos y feriados.

Se representan con una sola clase inmutable que puede construirse desde los CSV
publicados (bootstrap, pruebas) o desde la base de datos del producto (API, DAG).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Catalogos:
    tiendas: pd.DataFrame  # tienda_id, nombre, ciudad, departamento, tipo, fecha_apertura
    familias: pd.DataFrame  # familia_id, nombre
    costos: pd.DataFrame  # familia_id, costo_faltante, costo_sobrante
    feriados: pd.DataFrame  # fecha, nombre, tipo, ambito
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    # ------------------------------------------------------------------ fábricas
    @classmethod
    def desde_csv(cls, carpeta: str | Path) -> "Catalogos":
        carpeta = Path(carpeta)
        return cls.desde_dataframes(
            tiendas=pd.read_csv(carpeta / "tiendas.csv"),
            familias=pd.read_csv(carpeta / "familias.csv"),
            costos=pd.read_csv(carpeta / "costos.csv"),
            feriados=pd.read_csv(carpeta / "feriados.csv"),
        )

    @classmethod
    def desde_dataframes(cls, tiendas, familias, costos, feriados) -> "Catalogos":
        tiendas = tiendas.copy()
        tiendas["tienda_id"] = tiendas["tienda_id"].astype(int)
        tiendas["fecha_apertura"] = pd.to_datetime(tiendas["fecha_apertura"]).dt.date
        feriados = feriados.copy()
        feriados["fecha"] = pd.to_datetime(feriados["fecha"]).dt.date
        costos = costos.copy()
        costos["costo_faltante"] = costos["costo_faltante"].astype(float)
        costos["costo_sobrante"] = costos["costo_sobrante"].astype(float)
        return cls(tiendas=tiendas.reset_index(drop=True), familias=familias.reset_index(drop=True),
                   costos=costos.reset_index(drop=True), feriados=feriados.reset_index(drop=True))

    # ------------------------------------------------------------------ consultas
    @property
    def ids_tiendas(self) -> list[int]:
        return sorted(self.tiendas["tienda_id"].tolist())

    @property
    def ids_familias(self) -> list[str]:
        return self.familias["familia_id"].tolist()

    def tienda(self, tienda_id: int) -> dict | None:
        fila = self.tiendas[self.tiendas["tienda_id"] == tienda_id]
        return None if fila.empty else fila.iloc[0].to_dict()

    def fecha_apertura(self, tienda_id: int) -> date:
        return self.tienda(tienda_id)["fecha_apertura"]

    @property
    def cobertura_feriados(self) -> tuple[date, date]:
        return min(self.feriados["fecha"]), max(self.feriados["fecha"])

    def ratio_critico(self) -> dict[str, float]:
        """Cuantil óptimo del problema del vendedor de periódicos por familia."""
        c = self.costos
        return dict(zip(c["familia_id"], c["costo_faltante"] / (c["costo_faltante"] + c["costo_sobrante"])))

    def costos_dict(self) -> dict[str, tuple[float, float]]:
        c = self.costos
        return {f: (cf, cs) for f, cf, cs in zip(c["familia_id"], c["costo_faltante"], c["costo_sobrante"])}
