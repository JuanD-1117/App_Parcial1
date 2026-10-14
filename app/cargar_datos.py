"""Carga inicial de data/*.csv en MySQL (fase *load* del ETL del parcial).

Se ejecuta una vez, como servicio `carga` de docker compose, antes de levantar la app:

    python cargar_datos.py              # carga solo si la base está vacía
    python cargar_datos.py --reiniciar  # vacía las tablas y vuelve a cargar

Es idempotente a propósito: si la base ya tiene eventos no toca nada, de modo que reiniciar los
contenedores no borra los cambios hechos desde la GUI. Toda la carga ocurre en una única
transacción: o entran las 1327 filas o no entra ninguna.

Códigos de salida: 0 correcto, 1 error de carga o verificación.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from datos import crear_motor, describir_conexion

log = logging.getLogger("carga")

DIR_DATOS = Path(__file__).resolve().parent.parent / "data"

# Contrato con la limpieza del parcial: si la carga no reproduce estos recuentos, algo se
# perdió por el camino y el proceso debe fallar en lugar de servir datos incompletos.
RECUENTOS_ESPERADOS = {
    "catalogo": 3, "campana": 4, "detector": 5, "parametro": 11, "evento": 90,
    "medicion": 969, "participacion": 234, "campana_detector": 11,
}
ORDEN_BORRADO = ["medicion", "participacion", "campana_detector",
                 "evento", "parametro", "detector", "campana", "catalogo"]


def leer_csv() -> dict[str, pd.DataFrame]:
    tablas = {}
    for nombre in ("eventos", "parametros", "catalogo_parametros", "participaciones",
                   "detectores", "catalogos", "campanas"):
        ruta = DIR_DATOS / f"{nombre}.csv"
        if not ruta.exists():
            raise FileNotFoundError(f"Falta {ruta}: la carpeta data/ está incompleta.")
        tablas[nombre] = pd.read_csv(ruta)
    return tablas


def esperar_mysql(motor: Engine, intentos: int = 30, pausa_s: float = 2.0) -> None:
    """depends_on: service_healthy ya espera a MySQL; esto cubre la ejecución manual."""
    for intento in range(1, intentos + 1):
        try:
            with motor.connect() as conexion:
                conexion.execute(text("SELECT 1"))
            return
        except OperationalError:
            log.info("MySQL aún no responde (%d/%d)...", intento, intentos)
            time.sleep(pausa_s)
    raise RuntimeError(f"MySQL no respondió en {describir_conexion()}.")


def _registros(marco: pd.DataFrame) -> list[dict]:
    # NaN llegaría a MySQL como 'nan' o como error de tipo; None se traduce a NULL.
    return marco.astype(object).where(pd.notna(marco), None).to_dict(orient="records")


def _insertar(conexion: Connection, tabla: str, marco: pd.DataFrame) -> int:
    columnas = list(marco.columns)
    sentencia = text(f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                     f"VALUES ({', '.join(':' + c for c in columnas)})")
    registros = _registros(marco)
    conexion.execute(sentencia, registros)
    return len(registros)


def _mapa(conexion: Connection, tabla: str, natural: str, surrogada: str) -> dict:
    return dict(conexion.execute(text(f"SELECT {natural}, {surrogada} FROM {tabla}")).all())


def cargar(motor: Engine, t: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Inserta en orden de dependencias: referencias, eventos y luego tablas de relación."""
    n: dict[str, int] = {}
    with motor.begin() as conexion:
        n["catalogo"] = _insertar(conexion, "catalogo", t["catalogos"].rename(columns={
            "catalogo": "nombre", "ano_publicacion": "anio_publicacion"})[
            ["nombre", "anio_publicacion", "campanas_cubiertas", "referencia", "doi"]])
        n["campana"] = _insertar(conexion, "campana", t["campanas"].rename(columns={
            "campana": "nombre", "inicio": "fecha_inicio", "fin": "fecha_fin"})[
            ["nombre", "fecha_inicio", "fecha_fin"]])
        n["detector"] = _insertar(conexion, "detector", t["detectores"].rename(columns={
            "detector": "sigla", "ano_inicio": "anio_inicio"})[
            ["sigla", "nombre", "pais", "latitud", "longitud", "longitud_brazo_m",
             "operador", "anio_inicio"]])
        n["parametro"] = _insertar(conexion, "parametro", t["catalogo_parametros"].rename(
            columns={"parametro": "nombre"})[["nombre", "simbolo", "unidad", "descripcion"]])

        id_catalogo = _mapa(conexion, "catalogo", "nombre", "catalogo_id")
        id_campana = _mapa(conexion, "campana", "nombre", "campana_id")
        id_detector = _mapa(conexion, "detector", "sigla", "detector_id")
        id_parametro = _mapa(conexion, "parametro", "nombre", "parametro_id")

        # "H1, L1, V1" se expande en filas: la corrección de 1FN del modelo.
        pares = [{"campana_id": id_campana[f.campana], "detector_id": id_detector[s.strip()]}
                 for f in t["campanas"].itertuples() for s in f.detectores_activos.split(",")]
        n["campana_detector"] = _insertar(conexion, "campana_detector", pd.DataFrame(pares))

        ev = t["eventos"]
        n["evento"] = _insertar(conexion, "evento", pd.DataFrame({
            "nombre": ev.evento,
            "gwosc_id": ev.id,
            "version": ev.version.astype(int),
            "gps_tiempo": ev.gps,
            # El CSV guarda nanosegundos; DATETIME(3) admite milisegundos.
            "utc": pd.to_datetime(ev.utc, utc=True, format="ISO8601").dt.tz_localize(None).dt.round("ms"),
            "campana_id": ev.campana.map(id_campana),
            "catalogo_id": ev.catalogo.map(id_catalogo),
            "tipo_fuente": ev.tipo_fuente,
            "clasificacion_ambigua": ev.clasificacion_ambigua.astype(bool),
            "masa_total_origen": ev.total_mass_origen,
            "referencia": ev.reference,
            "url_json": ev.jsonurl,
        }))
        id_evento = _mapa(conexion, "evento", "nombre", "evento_id")

        me = t["parametros"]
        n["medicion"] = _insertar(conexion, "medicion", pd.DataFrame({
            "evento_id": me.evento.map(id_evento),
            "parametro_id": me.parametro.map(id_parametro),
            "valor": me.valor, "valor_min": me.valor_min, "valor_max": me.valor_max,
        }))

        pa = t["participaciones"]
        n["participacion"] = _insertar(conexion, "participacion", pd.DataFrame({
            "evento_id": pa.evento.map(id_evento),
            "detector_id": pa.detector.map(id_detector),
            "archivos_strain": pa.archivos_strain,
        }))
    return n


def vaciar(motor: Engine) -> None:
    with motor.begin() as conexion:
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for tabla in ORDEN_BORRADO:
                conexion.execute(text(f"TRUNCATE TABLE {tabla}"))
        finally:
            conexion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def verificar(motor: Engine) -> list[str]:
    with motor.connect() as conexion:
        reales = {tabla: conexion.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar_one()
                  for tabla in RECUENTOS_ESPERADOS}
    for tabla, esperado in RECUENTOS_ESPERADOS.items():
        log.info("  %-17s %5d filas (esperadas %d)", tabla, reales[tabla], esperado)
    return [f"{t}: esperadas {e}, hay {reales[t]}"
            for t, e in RECUENTOS_ESPERADOS.items() if reales[t] != e]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga data/*.csv en la base gwosc.")
    parser.add_argument("--reiniciar", action="store_true",
                        help="Vacía las tablas antes de cargar (descarta cambios hechos en la GUI).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    try:
        tablas = leer_csv()
        motor = crear_motor()
        esperar_mysql(motor)
        with motor.connect() as conexion:
            eventos = conexion.execute(text("SELECT COUNT(*) FROM evento")).scalar_one()
        if eventos and not args.reiniciar:
            log.info("La base ya tiene %d eventos: no se carga nada (use --reiniciar para "
                     "recargar desde cero).", eventos)
            return 0
        if args.reiniciar:
            log.info("Vaciando tablas...")
            vaciar(motor)
        insertados = cargar(motor, tablas)
        log.info("Insertadas %d filas en una transacción.", sum(insertados.values()))
        problemas = verificar(motor)
    except (FileNotFoundError, RuntimeError, SQLAlchemyError, KeyError, ValueError) as exc:
        log.error("La carga falló (la transacción se revirtió): %s", exc)
        return 1
    if problemas:
        log.error("Verificación fallida: %s", "; ".join(problemas))
        return 1
    log.info("Carga verificada: todos los recuentos coinciden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
