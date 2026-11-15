"""Persistencia en la base PostgreSQL propia del producto.

Tablas:
* catálogos: ``tiendas``, ``familias``, ``costos``, ``feriados``
* ``historico_ventas``: datos publicados (se cargan una sola vez)
* ``solicitudes``: cada llamada a /v1/* con cuerpo crudo, cuerpo limpio, estado y código HTTP
* ``predicciones``: una fila por familia pronosticada, con la versión del modelo
* ``correcciones``: cada acción reparar/advertir aplicada a una solicitud
* ``observaciones``: ventas reales; clave (tienda, familia, fecha) ⇒ **idempotente**
* ``reentrenamientos``: estado y resultado de cada ejecución del DAG
* ``estado_sistema``: banderas clave-valor (p. ej. bootstrap terminado)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .catalogos import Catalogos

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS tiendas (
    tienda_id INT PRIMARY KEY, nombre TEXT NOT NULL, ciudad TEXT NOT NULL, departamento TEXT,
    tipo TEXT NOT NULL, fecha_apertura DATE NOT NULL);
CREATE TABLE IF NOT EXISTS familias (familia_id TEXT PRIMARY KEY, nombre TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS costos (
    familia_id TEXT PRIMARY KEY REFERENCES familias(familia_id),
    costo_faltante DOUBLE PRECISION NOT NULL, costo_sobrante DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS feriados (
    fecha DATE NOT NULL, nombre TEXT NOT NULL, tipo TEXT NOT NULL, ambito TEXT NOT NULL,
    PRIMARY KEY (fecha, nombre, ambito));
CREATE TABLE IF NOT EXISTS historico_ventas (
    fecha DATE NOT NULL, tienda_id INT NOT NULL, familia_id TEXT NOT NULL,
    ventas INT NOT NULL, en_promocion INT NOT NULL,
    PRIMARY KEY (tienda_id, familia_id, fecha));
CREATE TABLE IF NOT EXISTS solicitudes (
    id BIGSERIAL PRIMARY KEY, tipo TEXT NOT NULL, recibida_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    cuerpo_crudo JSONB, cuerpo_limpio JSONB, tienda_id INT, fecha DATE, codigo_http INT NOT NULL,
    estado_calidad TEXT, detalle_rechazo TEXT, version_modelo TEXT);
CREATE TABLE IF NOT EXISTS predicciones (
    id BIGSERIAL PRIMARY KEY, solicitud_id BIGINT NOT NULL REFERENCES solicitudes(id),
    tienda_id INT NOT NULL, fecha DATE NOT NULL, familia_id TEXT NOT NULL, en_promocion INT NOT NULL,
    promocion_supuesta BOOLEAN NOT NULL DEFAULT FALSE, venta_esperada DOUBLE PRECISION NOT NULL,
    cantidad_sugerida INT NOT NULL, version_modelo TEXT NOT NULL,
    creada_en TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ix_predicciones_clave ON predicciones (tienda_id, fecha, familia_id, id);
CREATE TABLE IF NOT EXISTS correcciones (
    id BIGSERIAL PRIMARY KEY, solicitud_id BIGINT NOT NULL REFERENCES solicitudes(id),
    campo TEXT NOT NULL, accion TEXT NOT NULL, detalle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observaciones (
    tienda_id INT NOT NULL, familia_id TEXT NOT NULL, fecha DATE NOT NULL, ventas INT NOT NULL,
    solicitud_id BIGINT REFERENCES solicitudes(id),
    recibida_en TIMESTAMPTZ NOT NULL DEFAULT now(), actualizada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_cambios INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tienda_id, familia_id, fecha));
CREATE TABLE IF NOT EXISTS reentrenamientos (
    id TEXT PRIMARY KEY, estado TEXT NOT NULL, promovido BOOLEAN, version TEXT, motivo TEXT,
    version_candidata TEXT, metricas JSONB,
    solicitado_en TIMESTAMPTZ NOT NULL DEFAULT now(), finalizado_en TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS estado_sistema (
    clave TEXT PRIMARY KEY, valor TEXT, actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now());
"""

DIAS_HISTORIA_SERVICIO = 400  # suficiente para rezagos de 364 días + ventana anual
ARCHIVOS_PUBLICADOS = ["tiendas.csv", "familias.csv", "costos.csv", "feriados.csv", "historico_ventas.csv"]


def ubicar_carpeta_datos(carpeta: str | Path) -> Path:
    """Devuelve la carpeta que contiene los CSV publicados.

    Tolera que se haya copiado la carpeta descomprimida completa (p. ej. ``datos/datos_lab2/``):
    si los archivos no están en la raíz, busca la única subcarpeta que tenga ``historico_ventas.csv``.
    """
    carpeta = Path(carpeta)
    if (carpeta / "historico_ventas.csv").exists():
        return carpeta
    candidatas = sorted({p.parent for p in carpeta.rglob("historico_ventas.csv")})
    if len(candidatas) == 1:
        return candidatas[0]
    if len(candidatas) > 1:
        raise FileNotFoundError(f"Hay varias copias de historico_ventas.csv en {carpeta}: {candidatas}")
    return carpeta


class Repositorio:
    def __init__(self, url: str | None = None, engine: Engine | None = None):
        self.engine = engine or create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                                              connect_args={"connect_timeout": 3})

    # ------------------------------------------------------------------ infraestructura
    def verificar(self) -> None:
        with self.engine.connect() as c:
            c.execute(text("SELECT 1"))

    def crear_esquema(self) -> None:
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(424242)"))  # evita carreras entre contenedores
            for sentencia in ESQUEMA_SQL.split(";"):
                if sentencia.strip():
                    c.execute(text(sentencia))

    def obtener_estado(self, clave: str) -> str | None:
        with self.engine.connect() as c:
            return c.execute(text("SELECT valor FROM estado_sistema WHERE clave=:k"), {"k": clave}).scalar()

    def fijar_estado(self, clave: str, valor: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO estado_sistema (clave, valor) VALUES (:k, :v)
                              ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado_en=now()"""),
                      {"k": clave, "v": valor})

    # ------------------------------------------------------------------ carga inicial
    def datos_cargados(self) -> bool:
        with self.engine.connect() as c:
            n = c.execute(text("SELECT count(*) FROM historico_ventas")).scalar()
            t = c.execute(text("SELECT count(*) FROM tiendas")).scalar()
        return bool(n) and bool(t)

    def cargar_csv(self, carpeta: str | Path) -> dict:
        carpeta = ubicar_carpeta_datos(carpeta)
        faltan = [f for f in ARCHIVOS_PUBLICADOS if not (carpeta / f).exists()]
        if faltan:
            raise FileNotFoundError(f"Faltan archivos publicados en {carpeta}: {faltan}")
        conteo = {}
        with self.engine.begin() as c:
            c.execute(text("TRUNCATE historico_ventas, costos, feriados, familias, tiendas"))
            for tabla in ["tiendas", "familias", "costos", "feriados", "historico_ventas"]:
                df = pd.read_csv(carpeta / f"{tabla}.csv")
                df.to_sql(tabla, c, if_exists="append", index=False, method="multi", chunksize=5000)
                conteo[tabla] = len(df)
        return conteo

    def catalogos(self) -> Catalogos:
        with self.engine.connect() as c:
            leer = lambda q: pd.read_sql(text(q), c)  # noqa: E731
            return Catalogos.desde_dataframes(
                tiendas=leer("SELECT * FROM tiendas ORDER BY tienda_id"),
                familias=leer("SELECT * FROM familias ORDER BY familia_id"),
                costos=leer("SELECT * FROM costos ORDER BY familia_id"),
                feriados=leer("SELECT * FROM feriados ORDER BY fecha"),
            )

    # ------------------------------------------------------------------ lectura de ventas
    def historia_tienda(self, tienda_id: int, fecha: date) -> pd.DataFrame:
        """Ventas conocidas de la tienda ANTES de ``fecha`` (las observaciones mandan)."""
        q = text("""
            SELECT fecha, tienda_id, familia_id, ventas FROM observaciones
             WHERE tienda_id=:t AND fecha >= :ini AND fecha < :fin
            UNION ALL
            SELECT h.fecha, h.tienda_id, h.familia_id, h.ventas FROM historico_ventas h
             WHERE h.tienda_id=:t AND h.fecha >= :ini AND h.fecha < :fin
               AND NOT EXISTS (SELECT 1 FROM observaciones o WHERE o.tienda_id=h.tienda_id
                               AND o.familia_id=h.familia_id AND o.fecha=h.fecha)""")
        with self.engine.connect() as c:
            df = pd.read_sql(q, c, params={"t": tienda_id, "ini": fecha - timedelta(days=DIAS_HISTORIA_SERVICIO),
                                           "fin": fecha})
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    def datos_entrenamiento(self) -> pd.DataFrame:
        """Histórico + observaciones. La promoción de un día observado se toma de la última
        solicitud de pronóstico de ese día (las observaciones no traen promociones)."""
        q = text("""
            SELECT o.fecha, o.tienda_id, o.familia_id, o.ventas, p.en_promocion
              FROM observaciones o
              LEFT JOIN LATERAL (
                   SELECT en_promocion FROM predicciones p
                    WHERE p.tienda_id=o.tienda_id AND p.fecha=o.fecha AND p.familia_id=o.familia_id
                    ORDER BY p.promocion_supuesta ASC, p.id DESC LIMIT 1) p ON TRUE
            UNION ALL
            SELECT h.fecha, h.tienda_id, h.familia_id, h.ventas, h.en_promocion FROM historico_ventas h
             WHERE NOT EXISTS (SELECT 1 FROM observaciones o WHERE o.tienda_id=h.tienda_id
                               AND o.familia_id=h.familia_id AND o.fecha=h.fecha)""")
        with self.engine.connect() as c:
            df = pd.read_sql(q, c)
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df.sort_values(["fecha", "tienda_id", "familia_id"]).reset_index(drop=True)

    # ------------------------------------------------------------------ registro de la operación
    def registrar_solicitud(self, tipo: str, cuerpo_crudo, codigo_http: int, cuerpo_limpio=None,
                            tienda_id=None, fecha=None, estado_calidad=None, detalle_rechazo=None,
                            version_modelo=None, correcciones: list[dict] | None = None, conexion=None) -> int:
        def _hacer(c):
            sid = c.execute(text("""
                INSERT INTO solicitudes (tipo, cuerpo_crudo, cuerpo_limpio, tienda_id, fecha, codigo_http,
                                         estado_calidad, detalle_rechazo, version_modelo)
                VALUES (:tipo, CAST(:crudo AS JSONB), CAST(:limpio AS JSONB), :t, :f, :cod, :est, :det, :ver)
                RETURNING id"""), {
                "tipo": tipo, "crudo": _json(cuerpo_crudo), "limpio": _json(cuerpo_limpio), "t": tienda_id,
                "f": fecha, "cod": codigo_http, "est": estado_calidad, "det": detalle_rechazo, "ver": version_modelo,
            }).scalar()
            if correcciones:
                c.execute(text("INSERT INTO correcciones (solicitud_id, campo, accion, detalle) "
                               "VALUES (:s, :campo, :accion, :detalle)"),
                          [{"s": sid, **o} for o in correcciones])
            return sid
        if conexion is not None:
            return _hacer(conexion)
        with self.engine.begin() as c:
            return _hacer(c)

    def registrar_prediccion(self, tipo: str, cuerpo_crudo, cuerpo_limpio, tienda_id, fecha, estado_calidad,
                             version_modelo, correcciones, filas: list[dict]) -> int:
        with self.engine.begin() as c:
            sid = self.registrar_solicitud(tipo, cuerpo_crudo, 200, cuerpo_limpio, tienda_id, fecha, estado_calidad,
                                           None, version_modelo, correcciones, conexion=c)
            c.execute(text("""
                INSERT INTO predicciones (solicitud_id, tienda_id, fecha, familia_id, en_promocion,
                                          promocion_supuesta, venta_esperada, cantidad_sugerida, version_modelo)
                VALUES (:s, :tienda_id, :fecha, :familia_id, :en_promocion, :promocion_supuesta,
                        :venta_esperada, :cantidad_sugerida, :version_modelo)"""),
                [{"s": sid, "tienda_id": tienda_id, "fecha": fecha, "version_modelo": version_modelo, **f}
                 for f in filas])
            return sid

    def guardar_observaciones(self, cuerpo_crudo, cuerpo_limpio, tienda_id: int, fecha: date,
                              ventas: dict[str, int], estado_calidad: str, correcciones: list[dict]):
        """Upsert idempotente. Devuelve (registros_guardados, cambios[(familia, previo, nuevo)]).

        Solo cuenta filas nuevas o cuyo valor cambió: reenviar lo mismo ⇒ 0.
        """
        with self.engine.begin() as c:
            previos = dict(c.execute(text(
                "SELECT familia_id, ventas FROM observaciones WHERE tienda_id=:t AND fecha=:f FOR UPDATE"),
                {"t": tienda_id, "f": fecha}).fetchall())
            cambios = [(fam, previos[fam], v) for fam, v in ventas.items() if fam in previos and previos[fam] != v]
            correcciones = list(correcciones) + [
                {"campo": f"ventas.{fam}", "accion": "advertir",
                 "detalle": f"ya existía una observación de '{fam}' para {fecha} con {prev}; se reemplazó por {nuevo}"}
                for fam, prev, nuevo in cambios]
            estado = "advertencia" if cambios else estado_calidad
            sid = self.registrar_solicitud("observaciones", cuerpo_crudo, 200, cuerpo_limpio, tienda_id, fecha,
                                           estado, None, None, correcciones, conexion=c)
            guardados = 0
            for fam, v in ventas.items():
                fila = c.execute(text("""
                    INSERT INTO observaciones (tienda_id, familia_id, fecha, ventas, solicitud_id)
                    VALUES (:t, :fam, :f, :v, :s)
                    ON CONFLICT (tienda_id, familia_id, fecha) DO UPDATE
                       SET ventas=EXCLUDED.ventas, solicitud_id=EXCLUDED.solicitud_id,
                           actualizada_en=now(), n_cambios=observaciones.n_cambios + 1
                     WHERE observaciones.ventas IS DISTINCT FROM EXCLUDED.ventas
                    RETURNING 1"""), {"t": tienda_id, "fam": fam, "f": fecha, "v": v, "s": sid}).fetchone()
                guardados += 1 if fila else 0
        return guardados, cambios

    # ------------------------------------------------------------------ reentrenamientos
    def crear_reentrenamiento(self, rid: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO reentrenamientos (id, estado) VALUES (:i, 'en_curso')"), {"i": rid})

    def obtener_reentrenamiento(self, rid: str) -> dict | None:
        with self.engine.connect() as c:
            fila = c.execute(text("SELECT * FROM reentrenamientos WHERE id=:i"), {"i": rid}).mappings().fetchone()
        return dict(fila) if fila else None

    def finalizar_reentrenamiento(self, rid: str, estado: str, promovido: bool, version: str | None, motivo: str,
                                  version_candidata: str | None = None, metricas: dict | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(text("""
                INSERT INTO reentrenamientos (id, estado, promovido, version, motivo, version_candidata, metricas,
                                              finalizado_en)
                VALUES (:i, :e, :p, :v, :m, :vc, CAST(:met AS JSONB), now())
                ON CONFLICT (id) DO UPDATE SET estado=EXCLUDED.estado, promovido=EXCLUDED.promovido,
                    version=EXCLUDED.version, motivo=EXCLUDED.motivo, version_candidata=EXCLUDED.version_candidata,
                    metricas=EXCLUDED.metricas, finalizado_en=now()"""),
                {"i": rid, "e": estado, "p": promovido, "v": version, "m": motivo, "vc": version_candidata,
                 "met": _json(metricas)})


def _json(obj) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False, default=str)
