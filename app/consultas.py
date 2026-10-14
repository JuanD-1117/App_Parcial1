"""Lectura de las consultas de análisis del parcial (db/consultas.sql).

El archivo SQL es la fuente única: la app no duplica el texto de las consultas, lo lee y lo
separa en bloques `-- Cn. descripción` seguidos de su sentencia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ARCHIVO_CONSULTAS = Path(__file__).resolve().parent.parent / "db" / "consultas.sql"
_ENCABEZADO = re.compile(r"^-- (C\d+)\.\s*(.*)$")


@dataclass(frozen=True)
class Consulta:
    codigo: str
    descripcion: str
    sql: str


def leer_consultas(ruta: Path = ARCHIVO_CONSULTAS) -> list[Consulta]:
    """Devuelve las consultas en el orden del archivo."""
    if not ruta.exists():
        raise FileNotFoundError(f"No se encuentra {ruta}; la carpeta db/ debe acompañar a la app.")

    consultas: list[Consulta] = []
    codigo: str | None = None
    descripcion: list[str] = []
    sql: list[str] = []

    def cerrar() -> None:
        if codigo and sql:
            texto = "\n".join(sql).strip().rstrip(";").strip()
            consultas.append(Consulta(codigo, " ".join(descripcion), texto))

    for linea in ruta.read_text(encoding="utf-8").splitlines():
        encabezado = _ENCABEZADO.match(linea)
        if encabezado:
            cerrar()
            codigo, descripcion, sql = encabezado.group(1), [encabezado.group(2).strip()], []
        elif linea.lstrip().startswith("--"):
            # Las líneas de comentario que siguen al encabezado amplían la descripción; las de
            # separación de niveles (guiones o "NIVEL n") no pertenecen a ninguna consulta.
            contenido = linea.lstrip()[2:].strip()
            if codigo and not sql and contenido and not set(contenido) <= {"-", "="}:
                if not contenido.startswith("NIVEL"):
                    descripcion.append(contenido)
        elif codigo is not None:
            if linea.strip() or sql:
                sql.append(linea)
    cerrar()
    return consultas
