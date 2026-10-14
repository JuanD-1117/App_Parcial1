"""Reglas físicas y temporales del dominio de ondas gravitacionales.

Lógica pura, sin base de datos ni interfaz: la usan la carga, la capa de datos y la GUI, y se
prueba sin levantar MySQL (ver tests/test_fisica.py).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

# El tiempo GPS no incorpora segundos intercalares: son 18 desde 2017 y no cambiaron durante
# O1-O3b. Tratar el GPS como tiempo Unix desplazaría las fechas unos diez años.
EPOCA_GPS = datetime(1980, 1, 6, tzinfo=timezone.utc)
SEGUNDOS_INTERCALARES = 18

# Límites GPS oficiales de cada campaña. La campaña de un evento se deduce de su tiempo, no se
# elige a mano: así un evento nuevo no puede quedar en una campaña que no le corresponde.
CAMPANAS_GPS: dict[str, tuple[int, int]] = {
    "O1": (1126051217, 1137254417),
    "O2": (1164556817, 1187733618),
    "O3a": (1238166018, 1253977218),
    "O3b": (1256655618, 1269363618),
}

# Hueco de masa por inestabilidad de pares (PISN), en masas solares.
PISN_INFERIOR = 45.0
PISN_SUPERIOR = 120.0

# Masa máxima de una estrella de neutrones (límite TOV aproximado), en masas solares.
LIMITE_TOV = 3.0

TIPOS_FUENTE = ("BBH", "NSBH", "BNS")
DESCRIPCION_TIPOS = {
    "BBH": "Binaria de agujeros negros",
    "NSBH": "Estrella de neutrones + agujero negro",
    "BNS": "Binaria de estrellas de neutrones",
}

# Nombre público de un evento: GWaammdd, con sufijo _hhmmss desde O3.
PATRON_NOMBRE = re.compile(r"^GW\d{6}(_\d{6})?$")

# Rango físicamente admisible de cada parámetro: (mínimo, máximo, mínimo excluido).
# Son las mismas comprobaciones de consistencia que el parcial aplica a los datos de GWOSC.
RANGOS_PARAMETROS: dict[str, tuple[float, float, bool]] = {
    "mass_1_source": (0.0, math.inf, True),
    "mass_2_source": (0.0, math.inf, True),
    "total_mass_source": (0.0, math.inf, True),
    "chirp_mass_source": (0.0, math.inf, True),
    "final_mass_source": (0.0, math.inf, True),
    "luminosity_distance": (0.0, math.inf, True),
    "redshift": (0.0, math.inf, False),
    "chi_eff": (-1.0, 1.0, False),
    "snr_red": (0.0, math.inf, True),
    "far": (0.0, math.inf, False),
    "p_astro": (0.0, 1.0, False),
}


def gps_a_utc(gps: float) -> datetime:
    """Convierte tiempo GPS (s) a UTC, descontando los segundos intercalares."""
    return EPOCA_GPS + timedelta(seconds=gps - SEGUNDOS_INTERCALARES)


def campana_por_gps(gps: float) -> str | None:
    """Devuelve la campaña que contiene el instante GPS, o None si no cae en ninguna."""
    for nombre, (inicio, fin) in CAMPANAS_GPS.items():
        if inicio <= gps <= fin:
            return nombre
    return None


def validar_evento(nombre: str, gps: float, version: int, tipo_fuente: str) -> list[str]:
    """Errores de un evento antes de enviarlo a la base de datos. Lista vacía si es válido."""
    errores = []
    if not PATRON_NOMBRE.match(nombre or ""):
        errores.append(
            f"Nombre '{nombre}' inválido: use GWaammdd o GWaammdd_hhmmss (p. ej. GW150914)."
        )
    if gps is None or gps <= 0:
        errores.append("El tiempo GPS debe ser positivo.")
    elif campana_por_gps(gps) is None:
        errores.append(
            f"El GPS {gps:.1f} ({gps_a_utc(gps):%Y-%m-%d}) no cae en ninguna campaña "
            "registrada (O1, O2, O3a, O3b)."
        )
    if version is None or not 1 <= version <= 127:
        errores.append("La versión debe estar entre 1 y 127.")
    if tipo_fuente not in TIPOS_FUENTE:
        errores.append(f"Tipo de fuente inválido: use uno de {', '.join(TIPOS_FUENTE)}.")
    if nombre and gps and gps > 0 and PATRON_NOMBRE.match(nombre):
        fecha_nombre = nombre[2:8]
        fecha_gps = f"{gps_a_utc(gps):%y%m%d}"
        if fecha_nombre != fecha_gps:
            errores.append(
                f"El nombre indica la fecha {fecha_nombre} pero el GPS corresponde a "
                f"{fecha_gps} (aammdd, UTC)."
            )
    return errores


def validar_medicion(
    parametro: str, valor: float, valor_min: float | None, valor_max: float | None
) -> list[str]:
    """Errores de una medición: rango físico del parámetro y coherencia del intervalo."""
    errores = []
    if valor is None or not math.isfinite(valor):
        return ["El valor central es obligatorio y debe ser finito."]
    if parametro in RANGOS_PARAMETROS:
        minimo, maximo, excluido = RANGOS_PARAMETROS[parametro]
        fuera_inferior = valor <= minimo if excluido else valor < minimo
        if fuera_inferior or valor > maximo:
            simbolo = "(" if excluido else "["
            errores.append(f"{parametro} = {valor} fuera del rango físico {simbolo}{minimo}, {maximo}].")
    if valor_min is not None and valor_min > valor:
        errores.append(f"La cota inferior ({valor_min}) supera al valor central ({valor}).")
    if valor_max is not None and valor_max < valor:
        errores.append(f"La cota superior ({valor_max}) es menor que el valor central ({valor}).")
    return errores
