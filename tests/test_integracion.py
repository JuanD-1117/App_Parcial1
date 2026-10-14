"""Pruebas contra el MySQL de docker compose (localhost:3308).

Se omiten si la base no está levantada. Cada prueba deja la base como la encontró.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

os.environ.setdefault("DB_PORT", "3308")
import datos  # noqa: E402
import fisica  # noqa: E402

NOMBRE_PRUEBA = "GW200101_120000"
GPS_PRUEBA = 1261915218.0   # 2020-01-01 12:00:00 UTC, dentro de O3b


@pytest.fixture(scope="module")
def motor():
    m = datos.crear_motor()
    try:
        with m.connect() as c:
            c.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("MySQL no disponible en localhost:3308 (ejecute ./instalar.sh)")
    return m


def _id(motor, tabla, columna, valor):
    with motor.connect() as c:
        return c.execute(text(f"SELECT {tabla}_id FROM {tabla} WHERE {columna} = :v"),
                         {"v": valor}).scalar_one()


@pytest.fixture(scope="module")
def catalogo_id(motor):
    return _id(motor, "catalogo", "nombre", "GWTC-3-confident")


@pytest.fixture(scope="module")
def h1_id(motor):
    return _id(motor, "detector", "sigla", "H1")


@pytest.fixture
def evento_prueba(motor, catalogo_id):
    """Crea un evento temporal y lo borra al terminar, pase lo que pase."""
    with motor.begin() as c:
        c.execute(text("DELETE FROM evento WHERE nombre = :n"), {"n": NOMBRE_PRUEBA})
    datos.crear_evento(motor, nombre=NOMBRE_PRUEBA, gwosc_id=f"{NOMBRE_PRUEBA}-v1", version=1,
                       gps=GPS_PRUEBA, catalogo_id=catalogo_id, tipo_fuente="BBH",
                       clasificacion_ambigua=False, referencia=None, url_json=None)
    eventos = datos.leer_eventos(motor)
    yield int(eventos.loc[eventos.evento == NOMBRE_PRUEBA, "evento_id"].iloc[0])
    with motor.begin() as c:
        c.execute(text("DELETE FROM evento WHERE nombre = :n"), {"n": NOMBRE_PRUEBA})


def test_contar_filas_datos_originales_cargados(motor):
    n = datos.contar_filas(motor)
    assert n["detector"] == 5 and n["campana"] == 4 and n["parametro"] == 11
    assert n["evento"] >= 90


def test_leer_eventos_gw150914_tiene_parametros_publicados(motor):
    fila = datos.leer_eventos(motor).set_index("evento").loc["GW150914"]
    assert fila.masa_1 == pytest.approx(34.6)
    assert fila.campana == "O1" and fila.red == "H1+L1"
    assert fila.archivos_strain == 24


def test_crear_evento_asigna_campana_y_utc_desde_gps(motor, evento_prueba):
    fila = datos.leer_eventos(motor).set_index("evento_id").loc[evento_prueba]
    assert fila.campana == "O3b"
    assert str(fila.utc).startswith("2020-01-01 12:00:00")


def test_crear_evento_nombre_duplicado_falla_con_1062(motor, evento_prueba, catalogo_id):
    with pytest.raises(datos.ErrorDatos, match="1062"):
        datos.crear_evento(motor, nombre=NOMBRE_PRUEBA, gwosc_id="x", version=1,
                           gps=GPS_PRUEBA, catalogo_id=catalogo_id, tipo_fuente="BBH",
                           clasificacion_ambigua=False, referencia=None, url_json=None)


def test_guardar_medicion_upsert_actualiza_valor(motor, evento_prueba):
    datos.guardar_medicion(motor, evento_prueba, "mass_1_source", 30.0, 25.0, 35.0)
    datos.guardar_medicion(motor, evento_prueba, "mass_1_source", 31.0, 26.0, 36.0)
    med = datos.leer_mediciones(motor, evento_prueba).set_index("parametro")
    assert med.loc["mass_1_source", "valor"] == 31.0 and len(med) == 1


def test_guardar_medicion_m2_mayor_que_m1_falla(motor, evento_prueba):
    datos.guardar_medicion(motor, evento_prueba, "mass_1_source", 20.0, None, None)
    with pytest.raises(datos.ErrorDatos, match="m₂ ≤ m₁"):
        datos.guardar_medicion(motor, evento_prueba, "mass_2_source", 25.0, None, None)


def test_guardar_medicion_intervalo_invalido_falla_antes_de_mysql(motor, evento_prueba):
    with pytest.raises(datos.ErrorDatos, match="cota"):
        datos.guardar_medicion(motor, evento_prueba, "redshift", 0.1, 0.2, 0.3)


def test_borrar_evento_elimina_dependientes_en_cascada(motor, evento_prueba, h1_id):
    datos.guardar_medicion(motor, evento_prueba, "snr_red", 12.0, None, None)
    datos.agregar_participacion(motor, evento_prueba, h1_id, 12)
    assert datos.dependientes_evento(motor, evento_prueba) == {"mediciones": 1,
                                                               "participaciones": 1}
    datos.borrar_evento(motor, evento_prueba)
    assert datos.dependientes_evento(motor, evento_prueba) == {"mediciones": 0,
                                                               "participaciones": 0}


def test_agregar_participacion_duplicada_falla(motor, evento_prueba, h1_id):
    datos.agregar_participacion(motor, evento_prueba, h1_id, 12)
    with pytest.raises(datos.ErrorDatos, match="1062"):
        datos.agregar_participacion(motor, evento_prueba, h1_id, 12)


def test_consulta_solo_lectura_rechaza_escrituras(motor):
    with pytest.raises(datos.ErrorDatos):
        datos.consulta_solo_lectura(motor, "DELETE FROM evento")
    with pytest.raises(datos.ErrorDatos):
        datos.consulta_solo_lectura(motor, "SELECT 1; DELETE FROM evento")
    # Aunque el prefijo sea SELECT, la transacción READ ONLY impide escribir.
    with pytest.raises(datos.ErrorDatos):
        datos.consulta_solo_lectura(motor, "SELECT * FROM evento FOR UPDATE")


def test_consultas_del_parcial_corren_todas(motor):
    from consultas import leer_consultas
    for c in leer_consultas():
        assert not datos.consulta_solo_lectura(motor, c.sql).empty, c.codigo


def test_utc_almacenado_coincide_con_gps(motor):
    eventos = datos.leer_eventos(motor)
    diferencia = (eventos.utc - eventos.gps_tiempo.map(
        lambda g: fisica.gps_a_utc(float(g)).replace(tzinfo=None))).abs()
    assert diferencia.max().total_seconds() < 0.01
