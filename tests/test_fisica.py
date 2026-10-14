"""Reglas físicas y temporales: casos con valor conocido."""

import pandas as pd
import pytest

import fisica

DATOS = __import__("pathlib").Path(__file__).resolve().parent.parent / "data"


def test_gps_a_utc_gw150914_coincide_con_fecha_publicada():
    # GW150914: 14 de septiembre de 2015, 09:50:45 UTC (Abbott et al. 2016).
    utc = fisica.gps_a_utc(1126259462.4)
    assert (utc.year, utc.month, utc.day, utc.hour, utc.minute) == (2015, 9, 14, 9, 50)
    assert utc.second == 44


@pytest.mark.parametrize("gps, campana", [
    (1126259462.4, "O1"), (1187008882.4, "O2"), (1239082262.2, "O3a"),
    (1264316116.4, "O3b"), (1150000000.0, None),
])
def test_campana_por_gps_asigna_campana_correcta(gps, campana):
    assert fisica.campana_por_gps(gps) == campana


def test_validar_evento_todos_los_eventos_del_catalogo_son_validos():
    eventos = pd.read_csv(DATOS / "eventos.csv")
    errores = {
        fila.evento: fisica.validar_evento(fila.evento, fila.gps, int(fila.version),
                                           fila.tipo_fuente)
        for fila in eventos.itertuples()
    }
    assert {k: v for k, v in errores.items() if v} == {}


def test_validar_evento_nombre_y_gps_incoherentes_falla():
    errores = fisica.validar_evento("GW150915", 1126259462.4, 1, "BBH")
    assert any("fecha" in e for e in errores)


@pytest.mark.parametrize("nombre", ["GW15091", "gw150914", "S190425z", "GW150914_1"])
def test_validar_evento_nombre_mal_formado_falla(nombre):
    assert fisica.validar_evento(nombre, 1126259462.4, 1, "BBH")


def test_validar_evento_gps_fuera_de_campanas_falla():
    assert any("campaña" in e for e in fisica.validar_evento("GW160601", 1148774417.0, 1, "BBH"))


def test_validar_medicion_valida_sin_errores():
    assert fisica.validar_medicion("mass_1_source", 35.6, 30.0, 40.0) == []


@pytest.mark.parametrize("parametro, valor", [
    ("mass_1_source", 0.0), ("luminosity_distance", -10.0), ("chi_eff", 1.5), ("p_astro", 1.2),
])
def test_validar_medicion_fuera_de_rango_fisico_falla(parametro, valor):
    assert fisica.validar_medicion(parametro, valor, None, None)


def test_validar_medicion_intervalo_que_no_contiene_valor_falla():
    assert len(fisica.validar_medicion("redshift", 0.1, 0.2, 0.05)) == 2


def test_validar_medicion_todas_las_mediciones_del_catalogo_son_validas():
    med = pd.read_csv(DATOS / "parametros.csv")
    invalidas = [
        (f.evento, f.parametro)
        for f in med.itertuples()
        if fisica.validar_medicion(f.parametro, f.valor,
                                   None if pd.isna(f.valor_min) else f.valor_min,
                                   None if pd.isna(f.valor_max) else f.valor_max)
    ]
    assert invalidas == []
