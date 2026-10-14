"""Separación de db/consultas.sql en consultas individuales."""

import consultas


def test_leer_consultas_devuelve_las_veinte_en_orden():
    lista = consultas.leer_consultas()
    assert [c.codigo for c in lista] == [f"C{i}" for i in range(1, 21)]


def test_leer_consultas_cada_una_es_una_sola_sentencia_de_lectura():
    for c in consultas.leer_consultas():
        assert c.sql.split(None, 1)[0].upper() in ("SELECT", "WITH"), c.codigo
        assert ";" not in c.sql, c.codigo
        assert c.descripcion, c.codigo


def test_leer_consultas_descripcion_no_incluye_separadores_de_nivel():
    for c in consultas.leer_consultas():
        assert "NIVEL" not in c.descripcion and "----" not in c.descripcion
