"""Capa de acceso a datos: lecturas para el dashboard y operaciones CRUD.

Toda la SQL de la aplicación vive aquí; la GUI solo llama funciones. Las sentencias usan
parámetros enlazados (nunca concatenación de texto) y cada escritura corre en su propia
transacción. Los errores de MySQL se traducen a `ErrorDatos` con un mensaje para el usuario.

Conexión por variables de entorno:
    DB_HOST (localhost), DB_PORT (3308), DB_NAME (gwosc), DB_USER (gwuser), DB_PASSWORD (gwpass)
"""

from __future__ import annotations

import os
import re

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError

import fisica

MAX_FILAS_CONSULTA = 5000

# Códigos de error de MySQL que el usuario puede provocar desde la GUI.
_MENSAJES_MYSQL = {
    1062: "Ya existe un registro con ese valor único",
    1451: "No se puede borrar: otros registros dependen de este (ON DELETE RESTRICT)",
    1452: "La referencia no existe en la tabla padre (clave foránea)",
    3819: "El valor viola una restricción CHECK del esquema",
    1406: "El texto es demasiado largo para la columna",
    1366: "Valor con formato incorrecto para la columna",
    1792: "La consola SQL es de solo lectura: no se permiten modificaciones",
    1064: "Error de sintaxis SQL",
    1054: "Columna desconocida",
    1146: "La tabla o vista no existe",
}


class ErrorDatos(Exception):
    """Error de validación o de base de datos, con un mensaje apto para mostrar."""


def crear_motor() -> Engine:
    host = os.environ.get("DB_HOST", "localhost")
    puerto = os.environ.get("DB_PORT", "3308")
    base = os.environ.get("DB_NAME", "gwosc")
    usuario = os.environ.get("DB_USER", "gwuser")
    clave = os.environ.get("DB_PASSWORD", "gwpass")
    url = f"mysql+pymysql://{usuario}:{clave}@{host}:{puerto}/{base}?charset=utf8mb4"
    # pool_pre_ping evita conexiones caducadas si el contenedor de MySQL se reinicia.
    return create_engine(url, pool_pre_ping=True)


def describir_conexion() -> str:
    return (f"{os.environ.get('DB_USER', 'gwuser')}@{os.environ.get('DB_HOST', 'localhost')}:"
            f"{os.environ.get('DB_PORT', '3308')}/{os.environ.get('DB_NAME', 'gwosc')}")


def _traducir(exc: DBAPIError) -> ErrorDatos:
    codigo = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
    detalle = exc.orig.args[1] if exc.orig is not None and len(exc.orig.args) > 1 else str(exc)
    base = _MENSAJES_MYSQL.get(codigo, "Error de la base de datos")
    return ErrorDatos(f"{base}. MySQL {codigo}: {detalle}")


def _leer(motor: Engine, sql: str, **parametros) -> pd.DataFrame:
    try:
        with motor.connect() as conexion:
            return pd.read_sql(text(sql), conexion, params=parametros)
    except OperationalError as exc:
        raise ErrorDatos(
            f"No hay conexión con MySQL ({describir_conexion()}). "
            "¿Está levantado el contenedor? Ejecute ./instalar.sh"
        ) from exc
    except DBAPIError as exc:
        raise _traducir(exc) from exc


def _escribir(motor: Engine, sentencias: list[tuple[str, dict]]) -> int:
    """Ejecuta varias sentencias en una transacción; devuelve las filas afectadas."""
    afectadas = 0
    try:
        with motor.begin() as conexion:
            for sql, parametros in sentencias:
                afectadas += conexion.execute(text(sql), parametros).rowcount
    except DBAPIError as exc:
        raise _traducir(exc) from exc
    return afectadas


# ---------------------------------------------------------------------------------------
#  Lecturas
# ---------------------------------------------------------------------------------------

def leer_eventos(motor: Engine) -> pd.DataFrame:
    """Un registro por evento: parámetros pivotados, red de detectores y magnitudes derivadas.

    Parte de la vista v_evento_resumen; LEFT JOIN para no perder eventos recién creados que
    aún no tienen detectores o mediciones.
    """
    return _leer(motor, """
        SELECT r.evento_id, r.evento, r.campana, r.catalogo, r.utc, e.gps_tiempo,
               e.version, e.gwosc_id, r.tipo_fuente, r.clasificacion_ambigua,
               e.masa_total_origen, e.referencia, e.url_json,
               r.masa_1, r.masa_2, r.masa_total, r.masa_chirp, r.masa_final,
               r.distancia_mpc, r.corrimiento_al_rojo, r.espin_efectivo, r.snr_red,
               r.tasa_falsa_alarma, r.p_astrofisico,
               d.razon_masas, d.energia_radiada_msun, d.fraccion_radiada,
               COALESCE(red.n_detectores, 0) AS n_detectores,
               COALESCE(red.red, '—')        AS red,
               COALESCE(st.archivos_strain, 0) AS archivos_strain
        FROM v_evento_resumen r
        JOIN evento e ON e.evento_id = r.evento_id
        LEFT JOIN v_magnitudes_derivadas d ON d.evento_id = r.evento_id
        LEFT JOIN v_red_por_evento red     ON red.evento_id = r.evento_id
        LEFT JOIN (SELECT evento_id, SUM(archivos_strain) AS archivos_strain
                   FROM participacion GROUP BY evento_id) st ON st.evento_id = r.evento_id
        ORDER BY r.utc
    """)


def leer_participaciones(motor: Engine) -> pd.DataFrame:
    return _leer(motor, """
        SELECT e.evento_id, e.nombre AS evento, c.nombre AS campana, d.detector_id,
               d.sigla AS detector, d.nombre AS nombre_detector, p.archivos_strain
        FROM participacion p
        JOIN evento   e ON e.evento_id   = p.evento_id
        JOIN campana  c ON c.campana_id  = e.campana_id
        JOIN detector d ON d.detector_id = p.detector_id
        ORDER BY e.utc, d.sigla
    """)


def leer_mediciones(motor: Engine, evento_id: int) -> pd.DataFrame:
    return _leer(motor, """
        SELECT p.parametro_id, p.nombre AS parametro, p.simbolo, p.unidad, p.descripcion,
               m.valor, m.valor_min, m.valor_max
        FROM medicion m
        JOIN parametro p ON p.parametro_id = m.parametro_id
        WHERE m.evento_id = :evento_id
        ORDER BY p.parametro_id
    """, evento_id=evento_id)


def leer_tabla_referencia(motor: Engine, tabla: str) -> pd.DataFrame:
    consultas = {
        "campana": """SELECT c.campana_id, c.nombre, c.fecha_inicio, c.fecha_fin,
                             DATEDIFF(c.fecha_fin, c.fecha_inicio) AS dias,
                             GROUP_CONCAT(d.sigla ORDER BY d.sigla SEPARATOR '+') AS detectores
                      FROM campana c
                      LEFT JOIN campana_detector cd ON cd.campana_id = c.campana_id
                      LEFT JOIN detector d ON d.detector_id = cd.detector_id
                      GROUP BY c.campana_id, c.nombre, c.fecha_inicio, c.fecha_fin
                      ORDER BY c.fecha_inicio""",
        "catalogo": "SELECT * FROM catalogo ORDER BY anio_publicacion",
        "detector": "SELECT * FROM detector ORDER BY detector_id",
        "parametro": "SELECT * FROM parametro ORDER BY parametro_id",
    }
    if tabla not in consultas:
        raise ValueError(f"Tabla de referencia desconocida: {tabla}")
    return _leer(motor, consultas[tabla])


def contar_filas(motor: Engine) -> dict[str, int]:
    tablas = ("evento", "medicion", "participacion", "detector", "campana", "catalogo",
              "parametro", "campana_detector")
    union = " UNION ALL ".join(f"SELECT '{t}' AS tabla, COUNT(*) AS n FROM {t}" for t in tablas)
    marco = _leer(motor, union)
    return dict(zip(marco.tabla, marco.n.astype(int)))


def consulta_solo_lectura(motor: Engine, sql: str) -> pd.DataFrame:
    """Ejecuta una única sentencia SELECT/WITH dentro de una transacción READ ONLY.

    La comprobación de prefijo es solo para dar un mensaje claro; la garantía real es la
    transacción de solo lectura, que hace que MySQL rechace cualquier escritura (error 1792).
    """
    sentencia = sql.strip().rstrip(";").strip()
    if not sentencia:
        raise ErrorDatos("Escriba una consulta.")
    if ";" in _sin_literales(sentencia):
        raise ErrorDatos("Solo se permite una sentencia por ejecución.")
    if not re.match(r"^(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", sentencia, re.IGNORECASE):
        raise ErrorDatos("La consola solo acepta consultas de lectura (SELECT, WITH, SHOW...).")
    try:
        with motor.connect() as conexion:
            conexion.exec_driver_sql("START TRANSACTION READ ONLY")
            try:
                resultado = conexion.execute(text(sentencia))
                filas = resultado.fetchmany(MAX_FILAS_CONSULTA)
                columnas = list(resultado.keys())
            finally:
                conexion.rollback()
    except OperationalError as exc:
        raise _traducir(exc) from exc
    except DBAPIError as exc:
        raise _traducir(exc) from exc
    return pd.DataFrame(filas, columns=columnas)


def _sin_literales(sql: str) -> str:
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", sql)


# ---------------------------------------------------------------------------------------
#  CRUD: eventos
# ---------------------------------------------------------------------------------------

def _datos_evento(motor: Engine, nombre: str, gwosc_id: str, version: int, gps: float,
                  catalogo_id: int, tipo_fuente: str, clasificacion_ambigua: bool,
                  referencia: str | None, url_json: str | None) -> dict:
    errores = fisica.validar_evento(nombre, gps, version, tipo_fuente)
    if not gwosc_id:
        errores.append("El identificador GWOSC es obligatorio.")
    if errores:
        raise ErrorDatos(" ".join(errores))
    campanas = leer_tabla_referencia(motor, "campana")
    campana = fisica.campana_por_gps(gps)
    campana_id = campanas.loc[campanas.nombre == campana, "campana_id"]
    if campana_id.empty:
        raise ErrorDatos(f"La campaña {campana} no existe en la tabla campana.")
    return {
        "nombre": nombre, "gwosc_id": gwosc_id, "version": int(version), "gps": float(gps),
        "utc": fisica.gps_a_utc(gps).replace(tzinfo=None),
        "campana_id": int(campana_id.iloc[0]), "catalogo_id": int(catalogo_id),
        "tipo_fuente": tipo_fuente, "ambigua": bool(clasificacion_ambigua),
        "referencia": referencia or None, "url_json": url_json or None,
    }


def crear_evento(motor: Engine, **campos) -> None:
    datos = _datos_evento(motor, **campos)
    _escribir(motor, [("""
        INSERT INTO evento (nombre, gwosc_id, version, gps_tiempo, utc, campana_id,
                            catalogo_id, tipo_fuente, clasificacion_ambigua, referencia, url_json)
        VALUES (:nombre, :gwosc_id, :version, :gps, :utc, :campana_id, :catalogo_id,
                :tipo_fuente, :ambigua, :referencia, :url_json)
    """, datos)])


def actualizar_evento(motor: Engine, evento_id: int, **campos) -> None:
    datos = _datos_evento(motor, **campos) | {"evento_id": int(evento_id)}
    afectadas = _escribir(motor, [("""
        UPDATE evento SET nombre = :nombre, gwosc_id = :gwosc_id, version = :version,
               gps_tiempo = :gps, utc = :utc, campana_id = :campana_id,
               catalogo_id = :catalogo_id, tipo_fuente = :tipo_fuente,
               clasificacion_ambigua = :ambigua, referencia = :referencia, url_json = :url_json
        WHERE evento_id = :evento_id
    """, datos)])
    if afectadas == 0:
        # MySQL devuelve 0 también si los valores no cambiaron; se distingue comprobando.
        existe = _leer(motor, "SELECT 1 FROM evento WHERE evento_id = :i", i=int(evento_id))
        if existe.empty:
            raise ErrorDatos(f"El evento {evento_id} ya no existe.")


def dependientes_evento(motor: Engine, evento_id: int) -> dict[str, int]:
    marco = _leer(motor, """
        SELECT (SELECT COUNT(*) FROM medicion      WHERE evento_id = :i) AS mediciones,
               (SELECT COUNT(*) FROM participacion WHERE evento_id = :i) AS participaciones
    """, i=int(evento_id))
    return {k: int(v) for k, v in marco.iloc[0].items()}


def borrar_evento(motor: Engine, evento_id: int) -> None:
    """Borra el evento; sus mediciones y participaciones caen por ON DELETE CASCADE."""
    if _escribir(motor, [("DELETE FROM evento WHERE evento_id = :i", {"i": int(evento_id)})]) == 0:
        raise ErrorDatos(f"El evento {evento_id} ya no existe.")


# ---------------------------------------------------------------------------------------
#  CRUD: mediciones y participaciones
# ---------------------------------------------------------------------------------------

def guardar_medicion(motor: Engine, evento_id: int, parametro: str, valor: float,
                     valor_min: float | None, valor_max: float | None) -> None:
    """Inserta o actualiza (upsert) el valor de un parámetro para un evento."""
    errores = fisica.validar_medicion(parametro, valor, valor_min, valor_max)

    # Convención del catálogo: m1 es la componente más masiva. Se comprueba contra la otra masa
    # ya registrada, que es una regla entre filas que un CHECK de MySQL no puede expresar.
    if parametro in ("mass_1_source", "mass_2_source") and not errores:
        otra = "mass_2_source" if parametro == "mass_1_source" else "mass_1_source"
        actuales = leer_mediciones(motor, evento_id).set_index("parametro").valor
        if otra in actuales:
            m1 = valor if parametro == "mass_1_source" else actuales[otra]
            m2 = valor if parametro == "mass_2_source" else actuales[otra]
            if m2 > m1:
                errores.append(f"Por convención m₂ ≤ m₁, pero quedaría m₁ = {m1} y m₂ = {m2}.")
    if errores:
        raise ErrorDatos(" ".join(errores))

    _escribir(motor, [("""
        INSERT INTO medicion (evento_id, parametro_id, valor, valor_min, valor_max)
        SELECT :evento_id, parametro_id, :valor, :valor_min, :valor_max
        FROM parametro WHERE nombre = :parametro
        ON DUPLICATE KEY UPDATE valor = VALUES(valor), valor_min = VALUES(valor_min),
                                valor_max = VALUES(valor_max)
    """, {"evento_id": int(evento_id), "parametro": parametro, "valor": float(valor),
          "valor_min": valor_min, "valor_max": valor_max})])


def borrar_medicion(motor: Engine, evento_id: int, parametro_id: int) -> None:
    _escribir(motor, [("DELETE FROM medicion WHERE evento_id = :e AND parametro_id = :p",
                       {"e": int(evento_id), "p": int(parametro_id)})])


def agregar_participacion(motor: Engine, evento_id: int, detector_id: int,
                          archivos_strain: int | None) -> None:
    if archivos_strain is not None and archivos_strain < 0:
        raise ErrorDatos("El número de archivos de strain no puede ser negativo.")
    _escribir(motor, [("""
        INSERT INTO participacion (evento_id, detector_id, archivos_strain)
        VALUES (:e, :d, :a)
    """, {"e": int(evento_id), "d": int(detector_id), "a": archivos_strain})])


def quitar_participacion(motor: Engine, evento_id: int, detector_id: int) -> None:
    _escribir(motor, [("DELETE FROM participacion WHERE evento_id = :e AND detector_id = :d",
                       {"e": int(evento_id), "d": int(detector_id)})])
