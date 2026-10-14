"""GW Explorer: GUI Streamlit sobre la base relacional de ondas gravitacionales (GWOSC).

Primer Parcial de Desarrollo de Software 2026 — Juan Diego Martínez Ayala.

La interfaz solo orquesta: la SQL vive en datos.py, las reglas físicas en fisica.py y las
consultas de análisis en db/consultas.sql.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import datos
import fisica
from consultas import leer_consultas
from datos import ErrorDatos

st.set_page_config(page_title="GW Explorer", page_icon="🌌", layout="wide")

COLORES_TIPO = {"BBH": "#4C78A8", "NSBH": "#F58518", "BNS": "#E45756"}
COLORES_CAMPANA = {"O1": "#72B7B2", "O2": "#54A24B", "O3a": "#B279A2", "O3b": "#9D755D"}
ETIQUETAS = {
    "evento": "Evento", "campana": "Campaña", "catalogo": "Catálogo", "utc": "Fecha (UTC)",
    "tipo_fuente": "Tipo", "masa_1": "m₁ [M☉]", "masa_2": "m₂ [M☉]",
    "masa_total": "M total [M☉]", "masa_chirp": "𝓜 chirp [M☉]", "masa_final": "M final [M☉]",
    "distancia_mpc": "Distancia [Mpc]", "corrimiento_al_rojo": "z", "espin_efectivo": "χ_eff",
    "snr_red": "SNR de red", "p_astrofisico": "p_astro", "red": "Red",
    "n_detectores": "N detectores", "archivos_strain": "Archivos de strain",
    "energia_radiada_msun": "E radiada [M☉c²]", "razon_masas": "q = m₂/m₁",
    "detector": "Detector", "eventos": "Eventos",
}
MODULOS = [
    "🏠 Inicio",
    "📊 Dashboard",
    "🔭 Explorador de eventos",
    "🧪 Análisis científico",
    "📡 Detectores y strain",
    "🗄️ Consultas SQL",
    "✏️ Gestión de datos (CRUD)",
]
MODULOS_CON_FILTROS = MODULOS[1:4]


# ---------------------------------------------------------------------------------------
#  Datos (con caché; toda escritura limpia la caché)
# ---------------------------------------------------------------------------------------

@st.cache_resource
def motor():
    return datos.crear_motor()


@st.cache_data(ttl=300, show_spinner="Consultando MySQL...")
def eventos() -> pd.DataFrame:
    marco = datos.leer_eventos(motor())
    marco["utc"] = pd.to_datetime(marco["utc"])
    marco["clasificacion_ambigua"] = marco["clasificacion_ambigua"].astype(bool)
    return marco


@st.cache_data(ttl=300)
def participaciones() -> pd.DataFrame:
    return datos.leer_participaciones(motor())


@st.cache_data(ttl=300)
def referencia(tabla: str) -> pd.DataFrame:
    return datos.leer_tabla_referencia(motor(), tabla)


@st.cache_data(ttl=300)
def conteos() -> dict[str, int]:
    return datos.contar_filas(motor())


@st.cache_data(ttl=300)
def mediciones(evento_id: int) -> pd.DataFrame:
    return datos.leer_mediciones(motor(), evento_id)


def tras_escribir(mensaje: str) -> None:
    st.session_state["aviso"] = mensaje
    st.cache_data.clear()
    st.rerun()


def explicacion(texto: str) -> None:
    """Recuadro de lectura: qué muestra el gráfico y cómo interpretarlo."""
    st.caption(f"💡 {texto}")


def tabla(marco: pd.DataFrame, **kwargs) -> None:
    st.dataframe(marco.rename(columns=ETIQUETAS), hide_index=True, width="stretch", **kwargs)


def url_gwosc(fila: pd.Series) -> str | None:
    """Página del evento en GWOSC, donde se descargan sus archivos de strain."""
    url = fila.get("url_json")
    if isinstance(url, str) and "/eventapi/json/" in url:
        return url.replace("/eventapi/json/", "/eventapi/html/")
    return None


# ---------------------------------------------------------------------------------------
#  Barra lateral
# ---------------------------------------------------------------------------------------

def barra_lateral(df: pd.DataFrame) -> tuple[str, dict]:
    st.sidebar.title("🌌 GW Explorer")
    st.sidebar.caption("Ondas gravitacionales · GWOSC · LIGO/Virgo/KAGRA")
    modulo = st.sidebar.radio("Módulo", MODULOS, label_visibility="collapsed")

    filtros: dict = {}
    if modulo in MODULOS_CON_FILTROS:
        st.sidebar.divider()
        st.sidebar.subheader("Filtros")
        campanas = sorted(df.campana.unique(), key=list(fisica.CAMPANAS_GPS).index)
        filtros["campanas"] = st.sidebar.multiselect("Campaña", campanas, default=campanas)
        tipos = [t for t in fisica.TIPOS_FUENTE if t in set(df.tipo_fuente)]
        filtros["tipos"] = st.sidebar.multiselect(
            "Tipo de fuente", tipos, default=tipos,
            format_func=lambda t: f"{t} — {fisica.DESCRIPCION_TIPOS[t]}")
        detectores = sorted(participaciones().detector.unique())
        filtros["detectores"] = st.sidebar.multiselect(
            "Observado por detector", detectores,
            help="Deja solo los eventos en los que participó al menos uno de estos detectores. "
                 "Vacío = sin filtro.")
        filtros["masa_total"] = _rango(df, "masa_total", "Masa total [M☉]")
        filtros["distancia_mpc"] = _rango(df, "distancia_mpc", "Distancia luminosa [Mpc]")
        snr_max = float(np.nanmax(df.snr_red)) if df.snr_red.notna().any() else 100.0
        filtros["snr_min"] = st.sidebar.slider("SNR de red mínima", 0.0, float(np.ceil(snr_max)),
                                               0.0, 0.5)
        filtros["ambiguos"] = st.sidebar.checkbox(
            "Incluir clasificación ambigua", True,
            help="Eventos con alguna componente entre 2 y 5 M☉: no se sabe si es estrella de "
                 "neutrones o agujero negro (p. ej. GW190814).")

    st.sidebar.divider()
    st.sidebar.caption(f"Conexión: `{datos.describir_conexion()}`")
    if st.sidebar.button("🔄 Recargar datos de MySQL", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    return modulo, filtros


def _rango(df: pd.DataFrame, columna: str, etiqueta: str) -> tuple[float, float, bool]:
    serie = df[columna].dropna()
    if serie.empty:
        return (0.0, 0.0, True)
    bajo, alto = float(np.floor(serie.min())), float(np.ceil(serie.max()))
    seleccion = st.sidebar.slider(etiqueta, bajo, alto, (bajo, alto))
    completo = seleccion == (bajo, alto)
    return (*seleccion, completo)


def aplicar_filtros(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    if not f:
        return df
    mascara = df.campana.isin(f["campanas"]) & df.tipo_fuente.isin(f["tipos"])
    if f["detectores"]:
        p = participaciones()
        mascara &= df.evento_id.isin(p.loc[p.detector.isin(f["detectores"]), "evento_id"])
    for columna in ("masa_total", "distancia_mpc"):
        bajo, alto, completo = f[columna]
        dentro = df[columna].between(bajo, alto)
        # Con el rango completo no se descartan eventos sin ese dato (p. ej. recién creados).
        mascara &= dentro | (df[columna].isna() if completo else False)
    if f["snr_min"] > 0:
        mascara &= df.snr_red >= f["snr_min"]
    if not f["ambiguos"]:
        mascara &= ~df.clasificacion_ambigua
    return df[mascara]


# ---------------------------------------------------------------------------------------
#  Módulo: Inicio
# ---------------------------------------------------------------------------------------

def modulo_inicio(df: pd.DataFrame) -> None:
    st.title("🌌 Sistema de gestión y análisis de ondas gravitacionales")
    st.markdown(
        "**Primer Parcial · Desarrollo de Software 2026 · Juan Diego Martínez Ayala**  \n"
        "Fuente: [GWOSC — Gravitational Wave Open Science Center](https://gwosc.org), "
        "catálogos GWTC-1, GWTC-2.1 y GWTC-3 (campañas O1 a O3b, 2015–2020).")

    n = conteos()
    c = st.columns(6)
    c[0].metric("Eventos", n["evento"])
    c[1].metric("Mediciones", n["medicion"])
    c[2].metric("Detectores", n["detector"])
    c[3].metric("Campañas", n["campana"])
    c[4].metric("Catálogos", n["catalogo"])
    c[5].metric("Archivos de strain", f"{int(participaciones().archivos_strain.sum()):,}")

    izquierda, derecha = st.columns([3, 2])
    with izquierda, st.container(border=True):
        st.subheader("¿Qué es una onda gravitacional?")
        st.markdown(r"""
Cuando dos objetos compactos (agujeros negros o estrellas de neutrones) orbitan uno alrededor
del otro, pierden energía emitiendo **ondas gravitacionales**: perturbaciones del espacio-tiempo
que viajan a la velocidad de la luz. La órbita se cierra, la frecuencia y la amplitud crecen
(el *chirp*) y los objetos se fusionan.

Al llegar a la Tierra, la onda estira y comprime los brazos de los interferómetros de
**LIGO** (Hanford H1, Livingston L1), **Virgo** (V1) y **KAGRA** (K1). Esa deformación relativa
es el **strain** $h(t)=\Delta L/L$, del orden de $10^{-21}$: una variación menor que el
diámetro de un protón en un brazo de 4 km.

A partir del strain, la colaboración infiere los parámetros de la fuente: **masas** $m_1, m_2$,
**masa de chirp** $\mathcal{M}=(m_1m_2)^{3/5}/(m_1+m_2)^{1/5}$, **distancia luminosa** $d_L$,
**espín efectivo** $\chi_{\rm eff}$ y la **relación señal-ruido (SNR)** de la red.
Esta app trabaja con esos parámetros publicados, no con la serie de tiempo cruda.
""")
    with derecha, st.container(border=True):
        st.subheader("Pregunta científica del parcial")
        st.info(
            "¿Cómo se distribuye la masa de los objetos compactos detectados, y en qué medida "
            "esa distribución está moldeada por el **sesgo de selección** del instrumento en "
            "lugar de por la astrofísica de las fuentes?")
        st.markdown("""
- **(a)** ¿Hay una supresión de eventos en 45–120 M☉ (hueco por inestabilidad de pares, PISN)?
- **(b)** ¿Crece la masa de chirp detectada con la distancia (sesgo de selección)?
- **(c)** ¿Mejora la SNR entre las campañas O1, O2, O3a y O3b?

Las respuestas, calculadas en vivo desde MySQL, están en **🧪 Análisis científico**.
""")

    with st.container(border=True):
        st.subheader("Sobre el strain en este proyecto")
        st.markdown("""
El strain es el **dato instrumental primario** de GWOSC: series de tiempo de 4096 Hz por
detector. La base de datos lo registra como **dato de procedencia** en la tabla
`participacion.archivos_strain`: cuántos archivos de strain publicó GWOSC para cada par
evento–detector.

El análisis **no usa la serie de tiempo** porque la pregunta científica trata sobre la población
de fuentes (masas, distancias, SNR), y esos son los parámetros que la colaboración ya infirió a
partir del strain mediante *matched filtering* e inferencia bayesiana. Reanalizar el strain
reproduciría ese trabajo sin aportar a la pregunta. En **🔭 Explorador** y **📡 Detectores y
strain** se muestran los archivos disponibles y el enlace para descargarlos de GWOSC.
""")

    with st.container(border=True):
        st.subheader("Modelo relacional (MySQL 8.4, 3FN)")
        st.markdown(
            "Cinco entidades y tres tablas de relación. Las magnitudes derivadas (energía "
            "radiada, razón de masas) se calculan en **vistas** y no se almacenan, para evitar "
            "dependencias transitivas.")
        modelo = pd.DataFrame([
            ("evento", "Entidad central: una coalescencia detectada", "campana, catalogo"),
            ("medicion", "Valor e intervalo al 90 % de cada parámetro (formato largo)",
             "evento (CASCADE), parametro"),
            ("participacion", "Qué detectores observaron cada evento + archivos de strain",
             "evento (CASCADE), detector"),
            ("parametro", "Catálogo de magnitudes: símbolo, unidad, descripción", "—"),
            ("detector", "Interferómetros: ubicación, brazo, operador", "—"),
            ("campana", "Periodos de observación O1–O3b", "—"),
            ("catalogo", "Publicaciones GWTC con su DOI", "—"),
            ("campana_detector", "Detectores activos en cada campaña", "campana, detector"),
        ], columns=["Tabla", "Qué guarda", "Claves foráneas hacia"])
        modelo.insert(1, "Filas", modelo.Tabla.map(n))
        tabla(modelo)
        st.caption("Vistas: `v_evento_resumen` (parámetros pivotados), "
                   "`v_magnitudes_derivadas`, `v_red_por_evento`.")

    st.markdown("""
#### Cómo usar la app
1. **📊 Dashboard**: visión general con indicadores; los filtros de la barra lateral lo recalculan todo.
2. **🔭 Explorador**: tabla de eventos y la ficha completa de cada uno.
3. **🧪 Análisis científico**: las tres sub-preguntas, con su gráfico y su conclusión.
4. **📡 Detectores y strain**: la red de interferómetros y los datos de strain disponibles.
5. **🗄️ Consultas SQL**: las 20 consultas del parcial y una consola de solo lectura.
6. **✏️ Gestión de datos**: crear, editar y borrar eventos, mediciones y participaciones.
""")


# ---------------------------------------------------------------------------------------
#  Módulo: Dashboard
# ---------------------------------------------------------------------------------------

def modulo_dashboard(df: pd.DataFrame, total: int) -> None:
    st.title("📊 Dashboard")
    st.caption(f"{len(df)} de {total} eventos según los filtros de la barra lateral.")

    c = st.columns(6)
    c[0].metric("Eventos", len(df))
    c[1].metric("Agujeros negros (BBH)", f"{(df.tipo_fuente == 'BBH').mean():.0%}")
    c[2].metric("Masa total mediana", f"{df.masa_total.median():.1f} M☉")
    c[3].metric("Distancia mediana", f"{df.distancia_mpc.median():,.0f} Mpc")
    c[4].metric("SNR mediana", f"{df.snr_red.median():.1f}")
    c[5].metric("Vistos por ≥ 3 detectores", int((df.n_detectores >= 3).sum()))

    fila1 = st.columns(2)
    with fila1[0], st.container(border=True):
        st.subheader("Detecciones acumuladas")
        acumulado = df.sort_values("utc").assign(acumuladas=lambda d: np.arange(1, len(d) + 1))
        fig = px.scatter(acumulado, x="utc", y="acumuladas", color="campana",
                         color_discrete_map=COLORES_CAMPANA, hover_name="evento",
                         labels=ETIQUETAS | {"acumuladas": "Eventos acumulados"})
        fig.add_trace(go.Scatter(x=acumulado.utc, y=acumulado.acumuladas, mode="lines",
                                 line=dict(color="gray", width=1), showlegend=False,
                                 hoverinfo="skip"))
        st.plotly_chart(fig, width="stretch")
        explicacion("Cada punto es un evento. Los tramos planos son las pausas entre campañas "
                    "(mejoras del instrumento); la pendiente creciente muestra que cada campaña "
                    "detecta más rápido que la anterior.")

    with fila1[1], st.container(border=True):
        st.subheader("Eventos por campaña y tipo de fuente")
        conteo = df.groupby(["campana", "tipo_fuente"]).size().reset_index(name="eventos")
        fig = px.bar(conteo, x="campana", y="eventos", color="tipo_fuente",
                     color_discrete_map=COLORES_TIPO, labels=ETIQUETAS,
                     category_orders={"campana": list(fisica.CAMPANAS_GPS)})
        st.plotly_chart(fig, width="stretch")
        explicacion("BBH = dos agujeros negros, NSBH = estrella de neutrones + agujero negro, "
                    "BNS = dos estrellas de neutrones. Dominan las BBH porque son más masivas, "
                    "su señal es más fuerte y se ven desde más lejos, no porque sean más "
                    "comunes.")

    fila2 = st.columns(2)
    with fila2[0], st.container(border=True):
        st.subheader("Masas de las componentes")
        fig = px.scatter(df, x="masa_1", y="masa_2", color="tipo_fuente", hover_name="evento",
                         color_discrete_map=COLORES_TIPO, log_x=True, log_y=True,
                         labels=ETIQUETAS)
        limite = [1, float(np.nanmax(df.masa_1)) * 1.1 if df.masa_1.notna().any() else 100]
        fig.add_trace(go.Scatter(x=limite, y=limite, mode="lines", name="m₂ = m₁",
                                 line=dict(dash="dot", color="gray")))
        fig.add_hrect(y0=0.8, y1=fisica.LIMITE_TOV, fillcolor="#E45756", opacity=0.08,
                      line_width=0, annotation_text="estrellas de neutrones",
                      annotation_position="bottom right")
        st.plotly_chart(fig, width="stretch")
        explicacion("Ningún punto queda sobre la diagonal porque por convención m₁ ≥ m₂. La "
                    "franja roja (< 3 M☉) es la región de las estrellas de neutrones; por encima "
                    "solo caben agujeros negros.")

    with fila2[1], st.container(border=True):
        st.subheader("Distancia frente a masa de chirp")
        fig = px.scatter(df, x="distancia_mpc", y="masa_chirp", color="campana",
                         size="snr_red", hover_name="evento", log_x=True, log_y=True,
                         color_discrete_map=COLORES_CAMPANA, labels=ETIQUETAS)
        st.plotly_chart(fig, width="stretch")
        explicacion("El tamaño del punto es la SNR. Los sistemas ligeros solo se ven cerca y "
                    "los pesados llegan a miles de Mpc: es la huella del sesgo de selección "
                    "(detalle en Análisis científico → b).")

    with st.container(border=True):
        st.subheader("Resumen estadístico de los eventos filtrados")
        columnas = ["masa_1", "masa_2", "masa_total", "masa_chirp", "distancia_mpc",
                    "corrimiento_al_rojo", "espin_efectivo", "snr_red"]
        resumen = df[columnas].describe().T[["count", "mean", "50%", "min", "max"]]
        resumen.columns = ["N", "Media", "Mediana", "Mínimo", "Máximo"]
        resumen.index = [ETIQUETAS[c] for c in resumen.index]
        st.dataframe(resumen.round(2), width="stretch")


# ---------------------------------------------------------------------------------------
#  Módulo: Explorador
# ---------------------------------------------------------------------------------------

def modulo_explorador(df: pd.DataFrame) -> None:
    st.title("🔭 Explorador de eventos")
    st.caption("Tabla de los eventos filtrados. Elige uno abajo para ver su ficha completa.")
    columnas = ["evento", "utc", "campana", "tipo_fuente", "masa_1", "masa_2", "masa_total",
                "masa_chirp", "distancia_mpc", "snr_red", "red", "archivos_strain"]
    tabla(df[columnas].sort_values("utc", ascending=False),
          column_config={"utc": st.column_config.DatetimeColumn(ETIQUETAS["utc"],
                                                                format="YYYY-MM-DD HH:mm")})
    st.download_button("⬇️ Descargar CSV", df[columnas].to_csv(index=False).encode("utf-8"),
                       "eventos_filtrados.csv", "text/csv")

    nombres = df.sort_values("utc").evento.tolist()
    if not nombres:
        return
    indice = nombres.index("GW150914") if "GW150914" in nombres else 0
    nombre = st.selectbox("Ficha del evento", nombres, index=indice)
    fila = df.loc[df.evento == nombre].iloc[0]

    with st.container(border=True):
        st.subheader(f"{fila.evento} · {fisica.DESCRIPCION_TIPOS[fila.tipo_fuente]}")
        if fila.clasificacion_ambigua:
            st.warning("Clasificación ambigua: alguna componente está entre 2 y 5 M☉, donde no "
                       "se distingue una estrella de neutrones de un agujero negro.")
        c = st.columns(6)
        c[0].metric("Fecha (UTC)", f"{fila.utc:%Y-%m-%d}")
        c[1].metric("Masa total", _fmt(fila.masa_total, "M☉"))
        c[2].metric("Distancia", _fmt(fila.distancia_mpc, "Mpc", 0))
        c[3].metric("SNR de red", _fmt(fila.snr_red))
        c[4].metric("Energía radiada", _fmt(fila.energia_radiada_msun, "M☉c²", 2),
                    help="M total − M final: masa convertida en ondas gravitacionales.")
        c[5].metric("Red", fila.red)
        st.caption(f"GPS {fila.gps_tiempo:.4f} · campaña {fila.campana} · catálogo "
                   f"{fila.catalogo} · versión {fila.version} · masa total "
                   f"{fila.masa_total_origen}")

        izquierda, derecha = st.columns([3, 2])
        med = mediciones(int(fila.evento_id))
        with izquierda:
            st.markdown("**Parámetros medidos** (mediana e intervalo de credibilidad al 90 %)")
            vista = med.assign(intervalo=med.apply(_intervalo, axis=1))[
                ["simbolo", "descripcion", "valor", "intervalo", "unidad"]]
            vista.columns = ["Símbolo", "Descripción", "Valor", "Intervalo 90 %", "Unidad"]
            tabla(vista)
        with derecha:
            masas = med[med.unidad == "M_sun"].dropna(subset=["valor"])
            if not masas.empty:
                fig = go.Figure(go.Scatter(
                    x=masas.valor, y=masas.simbolo, mode="markers",
                    error_x=dict(type="data", symmetric=False,
                                 array=(masas.valor_max - masas.valor).fillna(0),
                                 arrayminus=(masas.valor - masas.valor_min).fillna(0))))
                fig.update_layout(title="Masas con su incertidumbre", xaxis_title="M☉",
                                  height=320, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig, width="stretch")
                explicacion("Las barras son el intervalo al 90 %. La masa final es menor que la "
                            "total: la diferencia se radió como ondas gravitacionales.")

    with st.container(border=True):
        st.subheader("Detectores y datos de strain")
        p = participaciones()
        p = p[p.evento_id == fila.evento_id][["detector", "nombre_detector", "archivos_strain"]]
        if p.empty:
            st.info("Este evento no tiene detectores registrados. Agrégalos en ✏️ Gestión de "
                    "datos → Participaciones.")
        else:
            p.columns = ["Sigla", "Detector", "Archivos de strain publicados"]
            tabla(p)
        enlace = url_gwosc(fila)
        if enlace:
            st.markdown(f"🔗 [Página del evento en GWOSC, con los archivos de strain]({enlace})")
        explicacion("Cada archivo de strain es una serie de tiempo h(t) del detector alrededor "
                    "del evento (32 s o 4096 s, a 4 o 16 kHz, en HDF5/GWF/TXT). El proyecto los "
                    "registra como procedencia; los parámetros de la tabla de arriba ya son el "
                    "resultado de analizarlos.")


def _fmt(valor, unidad: str = "", decimales: int = 1) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{valor:,.{decimales}f} {unidad}".strip()


def _intervalo(fila: pd.Series) -> str:
    if pd.isna(fila.valor_min) and pd.isna(fila.valor_max):
        return "sin intervalo publicado"
    return f"[{_num(fila.valor_min)}, {_num(fila.valor_max)}]"


def _num(valor) -> str:
    return "—" if pd.isna(valor) else f"{valor:.4g}"


# ---------------------------------------------------------------------------------------
#  Módulo: Análisis científico
# ---------------------------------------------------------------------------------------

def modulo_analisis(df: pd.DataFrame) -> None:
    st.title("🧪 Análisis científico")
    st.markdown("Cada pestaña responde una sub-pregunta del parcial con los datos filtrados. "
                "Las cifras se recalculan desde MySQL en cada consulta.")
    pestanas = st.tabs(["(a) Hueco de masa PISN", "(b) Sesgo de selección",
                        "(c) Evolución entre campañas", "Conclusión"])
    with pestanas[0]:
        analisis_pisn(df)
    with pestanas[1]:
        analisis_sesgo(df)
    with pestanas[2]:
        analisis_campanas(df)
    with pestanas[3]:
        st.success("**La distribución observada de masas está dominada por el sesgo de "
                   "selección, pero no se agota en él.**")
        st.markdown("""
1. **El sesgo es medible**: el alcance del detector crece como 𝓜^(5/6), de modo que los
   sistemas ligeros solo se ven cerca (pestaña b).
2. **Aun así, el hueco PISN sigue deprimido**: la densidad de eventos cae por encima de 45 M☉
   *a pesar de que* el instrumento favorece esa región. La escasez es astrofísica (pestaña a).
3. **El crecimiento del catálogo mide el instrumento, no el universo**: de O1 a O3b la tasa de
   detección y el alcance crecen mientras la SNR típica no mejora (pestaña c).
""")


def analisis_pisn(df: pd.DataFrame) -> None:
    st.subheader("¿Faltan agujeros negros entre 45 y 120 M☉?")
    st.markdown("""
Las estrellas muy masivas pueden explotar como **supernovas de inestabilidad de pares**
sin dejar remanente. Si es así, no deberían existir agujeros negros (de origen estelar) entre
~45 y ~120 M☉. Se compara la **densidad de eventos por masa solar** de la componente primaria
m₁ dentro y fuera de esa ventana.
""")
    m1 = df.masa_1.dropna()
    if m1.empty:
        st.info("No hay eventos con m₁ en la selección.")
        return
    debajo = (m1 < fisica.PISN_INFERIOR).sum() / fisica.PISN_INFERIOR
    dentro = m1.between(fisica.PISN_INFERIOR, fisica.PISN_SUPERIOR, inclusive="left").sum() / (
        fisica.PISN_SUPERIOR - fisica.PISN_INFERIOR)
    c = st.columns(3)
    c[0].metric("Eventos/M☉ por debajo (0–45)", f"{debajo:.3f}")
    c[1].metric("Eventos/M☉ dentro (45–120)", f"{dentro:.3f}")
    c[2].metric("Caída de densidad", f"× {debajo / dentro:.1f}" if dentro else "sin eventos")

    fig = px.histogram(df.dropna(subset=["masa_1"]), x="masa_1", color="tipo_fuente", nbins=40,
                       color_discrete_map=COLORES_TIPO, labels=ETIQUETAS)
    fig.add_vrect(x0=fisica.PISN_INFERIOR, x1=fisica.PISN_SUPERIOR, fillcolor="#E45756",
                  opacity=0.12, line_width=0, annotation_text="hueco PISN",
                  annotation_position="top left")
    fig.update_layout(yaxis_title="Eventos", bargap=0.05)
    st.plotly_chart(fig, width="stretch")
    explicacion("La franja roja es la ventana PISN. Si la densidad dentro es mucho menor que "
                "fuera, hay supresión. El hueco no es vacío: los eventos que caen dentro "
                "(p. ej. GW190521) se discuten como fusiones jerárquicas.")


def analisis_sesgo(df: pd.DataFrame) -> None:
    st.subheader("¿La masa detectada crece con la distancia?")
    st.markdown(r"""
La amplitud de la onda escala como $h \propto \mathcal{M}^{5/6}/d_L$. Para un umbral de SNR
fijo, la distancia máxima detectable crece como $d_{\max} \propto \mathcal{M}^{5/6}$, es decir,
la masa mínima detectable a una distancia dada sigue $\mathcal{M}_{\min} \propto d_L^{6/5}$.
Si la muestra está sesgada, los eventos deben quedar **por encima** de esa curva.
""")
    d = df.dropna(subset=["masa_chirp", "distancia_mpc"])
    if len(d) < 4:
        st.info("Se necesitan al menos 4 eventos con masa de chirp y distancia.")
        return
    # La curva se ancla al evento más exigente: k = min(𝓜 / d^1.2), que es el índice de
    # horizonte de la vista v_magnitudes_derivadas.
    k = (d.masa_chirp / d.distancia_mpc ** 1.2).min()
    malla = np.geomspace(d.distancia_mpc.min() * 0.8, d.distancia_mpc.max() * 1.2, 100)
    fig = px.scatter(d, x="distancia_mpc", y="masa_chirp", color="tipo_fuente",
                     hover_name="evento", log_x=True, log_y=True,
                     color_discrete_map=COLORES_TIPO, labels=ETIQUETAS)
    fig.add_trace(go.Scatter(x=malla, y=k * malla ** 1.2, mode="lines",
                             name="horizonte 𝓜 ∝ d^(6/5)", line=dict(dash="dash", color="gray")))
    st.plotly_chart(fig, width="stretch")

    d = d.assign(cuartil=pd.qcut(d.distancia_mpc, 4, labels=["Q1 (cerca)", "Q2", "Q3",
                                                              "Q4 (lejos)"]))
    resumen = d.groupby("cuartil", observed=True).agg(
        eventos=("evento", "size"), dl_min=("distancia_mpc", "min"),
        dl_max=("distancia_mpc", "max"), chirp_minima=("masa_chirp", "min"),
        chirp_media=("masa_chirp", "mean")).round(1).reset_index()
    resumen.columns = ["Cuartil de distancia", "Eventos", "d mín [Mpc]", "d máx [Mpc]",
                       "𝓜 mínima [M☉]", "𝓜 media [M☉]"]
    tabla(resumen)
    explicacion("La línea discontinua es la frontera de detección. La región vacía bajo ella no "
                "significa que no existan sistemas ligeros lejanos, sino que el instrumento no "
                "puede verlos. La 𝓜 mínima crece de un cuartil al siguiente: eso es el sesgo.")


def analisis_campanas(df: pd.DataFrame) -> None:
    st.subheader("¿Mejoró la red entre campañas?")
    st.markdown("Un detector más sensible observa un **volumen mayor**: detecta más eventos y "
                "más lejanos, pero la mayoría de los nuevos llegan justo por encima del umbral, "
                "así que la SNR típica **no** tiene por qué subir.")
    campanas = referencia("campana")
    resumen = df.groupby("campana").agg(
        eventos=("evento", "size"), snr_mediana=("snr_red", "median"),
        alcance=("distancia_mpc", "max")).reset_index()
    resumen = resumen.merge(campanas[["nombre", "dias"]], left_on="campana", right_on="nombre")
    resumen["eventos_mes"] = 30.4 * resumen.eventos / resumen.dias
    resumen["orden"] = resumen.campana.map(list(fisica.CAMPANAS_GPS).index)
    resumen = resumen.sort_values("orden")

    izquierda, derecha = st.columns(2)
    with izquierda:
        fig = px.bar(resumen, x="campana", y="eventos_mes", color="campana",
                     color_discrete_map=COLORES_CAMPANA, text_auto=".2f",
                     labels={"campana": "Campaña", "eventos_mes": "Detecciones por mes"})
        fig.update_layout(showlegend=False, title="Tasa de detección")
        st.plotly_chart(fig, width="stretch")
    with derecha:
        fig = px.box(df, x="campana", y="snr_red", color="campana", points="all",
                     hover_name="evento", color_discrete_map=COLORES_CAMPANA, labels=ETIQUETAS,
                     category_orders={"campana": list(fisica.CAMPANAS_GPS)})
        fig.update_layout(showlegend=False, title="SNR de red por campaña")
        st.plotly_chart(fig, width="stretch")

    vista = resumen[["campana", "eventos", "dias", "eventos_mes", "snr_mediana", "alcance"]]
    vista.columns = ["Campaña", "Eventos", "Días", "Eventos/mes", "SNR mediana",
                     "Alcance máx. [Mpc]"]
    tabla(vista.round(2))
    if len(resumen) >= 2:
        primera, ultima = resumen.iloc[0], resumen.iloc[-1]
        st.markdown(
            f"De **{primera.campana}** a **{ultima.campana}**: la tasa pasa de "
            f"{primera.eventos_mes:.2f} a {ultima.eventos_mes:.2f} eventos/mes "
            f"(× {ultima.eventos_mes / primera.eventos_mes:.1f}), el alcance de "
            f"{primera.alcance:,.0f} a {ultima.alcance:,.0f} Mpc y la SNR mediana de "
            f"{primera.snr_mediana:.1f} a {ultima.snr_mediana:.1f}.")
    explicacion("La mejora instrumental se ve en la tasa y en el alcance, no en la SNR.")


# ---------------------------------------------------------------------------------------
#  Módulo: Detectores y strain
# ---------------------------------------------------------------------------------------

def modulo_detectores() -> None:
    st.title("📡 Detectores y strain")
    st.markdown("""
Los interferómetros son de tipo Michelson con brazos de kilómetros. Una red de varios
detectores separados miles de kilómetros permite **descartar ruido local** (una señal real
llega a todos con milisegundos de diferencia) y **triangular** la posición de la fuente en el
cielo.
""")
    detectores = referencia("detector")
    p = participaciones()
    por_detector = p.groupby("detector").agg(eventos=("evento_id", "nunique"),
                                             archivos=("archivos_strain", "sum")).reset_index()
    detectores = detectores.merge(por_detector, left_on="sigla", right_on="detector", how="left")
    detectores[["eventos", "archivos"]] = detectores[["eventos", "archivos"]].fillna(0).astype(int)

    izquierda, derecha = st.columns([3, 2])
    with izquierda, st.container(border=True):
        st.subheader("Ubicación de la red")
        fig = px.scatter_geo(detectores, lat="latitud", lon="longitud", text="sigla",
                             size=detectores.eventos.clip(lower=1), hover_name="nombre",
                             hover_data={"pais": True, "eventos": True, "latitud": False,
                                         "longitud": False}, projection="natural earth")
        fig.update_traces(textposition="top center")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=380)
        st.plotly_chart(fig, width="stretch")
        explicacion("El tamaño del punto es el número de eventos observados.")
    with derecha, st.container(border=True):
        st.subheader("Instrumentos")
        vista = detectores[["sigla", "nombre", "pais", "longitud_brazo_m", "anio_inicio",
                            "eventos", "archivos"]]
        vista.columns = ["Sigla", "Nombre", "País", "Brazo [m]", "Desde", "Eventos",
                         "Archivos de strain"]
        tabla(vista)

    izquierda, derecha = st.columns(2)
    with izquierda, st.container(border=True):
        st.subheader("Participaciones por campaña")
        matriz = p.pivot_table(index="detector", columns="campana", values="evento_id",
                               aggfunc="nunique", fill_value=0)
        matriz = matriz[[c for c in fisica.CAMPANAS_GPS if c in matriz.columns]]
        fig = px.imshow(matriz, text_auto=True, color_continuous_scale="Blues", aspect="auto",
                        labels={"x": "Campaña", "y": "Detector", "color": "Eventos"})
        st.plotly_chart(fig, width="stretch")
        explicacion("Virgo (V1) se une en agosto de 2017 (final de O2); GEO 600 (G1) y KAGRA "
                    "(K1) aportan datos solo en algunos eventos de O3.")
    with derecha, st.container(border=True):
        st.subheader("Archivos de strain publicados")
        strain = p.groupby(["campana", "detector"]).archivos_strain.sum().reset_index()
        fig = px.bar(strain, x="campana", y="archivos_strain", color="detector",
                     labels={"campana": "Campaña", "archivos_strain": "Archivos de strain",
                             "detector": "Detector"},
                     category_orders={"campana": list(fisica.CAMPANAS_GPS)})
        st.plotly_chart(fig, width="stretch")
        explicacion("Total de productos de strain que GWOSC ofrece por campaña y detector.")

    with st.container(border=True):
        st.subheader("¿Qué es el strain y por qué no entra en el análisis?")
        st.markdown(r"""
- **Qué es**: la serie de tiempo $h(t)=\Delta L/L$ que registra cada detector. GWOSC publica,
  por evento y detector, ventanas de 32 s y 4096 s muestreadas a 4 kHz y 16 kHz, en formatos
  HDF5, GWF y TXT. De ahí sale el conteo de `archivos_strain`.
- **Cómo se usa en la colaboración**: se compara con miles de plantillas teóricas de la señal
  (*matched filtering*) y luego se hace inferencia bayesiana. El resultado son los parámetros
  publicados en el catálogo, con su intervalo de credibilidad al 90 %.
- **Por qué este proyecto no lo reanaliza**: la pregunta científica es sobre la **población**
  de fuentes. Los parámetros del catálogo ya contienen la información del strain que importa
  para esa pregunta. El strain queda en la base como dato de procedencia y trazabilidad, con
  enlace a GWOSC para descargarlo.
""")


# ---------------------------------------------------------------------------------------
#  Módulo: Consultas SQL
# ---------------------------------------------------------------------------------------

def modulo_consultas() -> None:
    st.title("🗄️ Consultas SQL")
    st.markdown("Las 20 consultas del parcial (`db/consultas.sql`), de básicas a funciones de "
                "ventana, ejecutadas en vivo contra MySQL.")
    try:
        consultas = leer_consultas()
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    niveles = {"Nivel 1 · Básicas": range(1, 4), "Nivel 2 · Agregación": range(4, 8),
               "Nivel 3 · JOIN": range(8, 11), "Nivel 4 · Subconsultas y CTE": range(11, 14),
               "Nivel 5 · Funciones de ventana": range(14, 17),
               "Nivel 6 · Pregunta científica": range(17, 21)}

    def nivel(codigo: str) -> str:
        numero = int(codigo[1:])
        return next((n for n, r in niveles.items() if numero in r), "")

    pestanas = st.tabs(["Consultas del parcial", "Consola de solo lectura"])
    with pestanas[0]:
        opciones = {f"{c.codigo} · {nivel(c.codigo)} — {c.descripcion[:70]}…": c
                    for c in consultas}
        consulta = opciones[st.selectbox("Consulta", list(opciones))]
        st.info(consulta.descripcion)
        st.code(consulta.sql, language="sql")
        try:
            resultado = datos.consulta_solo_lectura(motor(), consulta.sql)
            st.caption(f"{len(resultado)} filas")
            st.dataframe(resultado, hide_index=True, width="stretch")
        except ErrorDatos as exc:
            st.error(str(exc))

    with pestanas[1]:
        st.markdown("Escribe una consulta `SELECT`. Corre en una transacción **READ ONLY**: "
                    "MySQL rechaza cualquier intento de modificar datos. Máximo "
                    f"{datos.MAX_FILAS_CONSULTA} filas.")
        sql = st.text_area("SQL", height=160, value=(
            "SELECT evento, campana, masa_total, distancia_mpc, snr_red\n"
            "FROM v_evento_resumen\nORDER BY masa_total DESC\nLIMIT 10"))
        if st.button("▶️ Ejecutar", type="primary"):
            try:
                resultado = datos.consulta_solo_lectura(motor(), sql)
                st.caption(f"{len(resultado)} filas")
                st.dataframe(resultado, hide_index=True, width="stretch")
            except ErrorDatos as exc:
                st.error(str(exc))
        with st.expander("Tablas y vistas disponibles"):
            st.markdown("Tablas: `evento`, `medicion`, `parametro`, `participacion`, `detector`, "
                        "`campana`, `campana_detector`, `catalogo`.  \nVistas: "
                        "`v_evento_resumen`, `v_magnitudes_derivadas`, `v_red_por_evento`.")


# ---------------------------------------------------------------------------------------
#  Módulo: CRUD
# ---------------------------------------------------------------------------------------

def modulo_crud(df: pd.DataFrame) -> None:
    st.title("✏️ Gestión de datos (CRUD)")
    st.markdown("""
Crear, editar y borrar registros directamente en MySQL. Cada operación se valida dos veces:
primero con las **reglas físicas** de la app (rangos, convención m₁ ≥ m₂, coherencia entre
nombre y tiempo GPS) y luego con las **restricciones del esquema** (claves foráneas, `UNIQUE`,
`CHECK`). Los cambios se ven al instante en el resto de módulos.
""")
    pestanas = st.tabs(["Eventos", "Mediciones", "Detectores del evento (participaciones)"])
    with pestanas[0]:
        crud_eventos(df)
    with pestanas[1]:
        crud_mediciones(df)
    with pestanas[2]:
        crud_participaciones(df)


def _seleccionar_evento(df: pd.DataFrame, clave: str) -> pd.Series | None:
    if df.empty:
        st.info("No hay eventos en la base.")
        return None
    ordenados = df.sort_values("utc", ascending=False)
    nombre = st.selectbox("Evento", ordenados.evento.tolist(), key=clave)
    return ordenados.loc[ordenados.evento == nombre].iloc[0]


def crud_eventos(df: pd.DataFrame) -> None:
    accion = st.radio("Acción", ["Crear", "Editar", "Borrar"], horizontal=True, key="acc_ev")
    catalogos = referencia("catalogo")

    if accion == "Borrar":
        fila = _seleccionar_evento(df, "ev_borrar")
        if fila is None:
            return
        dependientes = datos.dependientes_evento(motor(), int(fila.evento_id))
        st.warning(f"Se borrará **{fila.evento}** y, por `ON DELETE CASCADE`, sus "
                   f"{dependientes['mediciones']} mediciones y "
                   f"{dependientes['participaciones']} participaciones. No se puede deshacer "
                   "desde la app (`./instalar.sh --reiniciar` recarga los datos originales).")
        confirmar = st.checkbox(f"Confirmo que quiero borrar {fila.evento}")
        if st.button("🗑️ Borrar evento", type="primary", disabled=not confirmar):
            _ejecutar(lambda: datos.borrar_evento(motor(), int(fila.evento_id)),
                      f"Evento {fila.evento} borrado.")
        return

    fila = _seleccionar_evento(df, "ev_editar") if accion == "Editar" else None
    if accion == "Editar" and fila is None:
        return
    sufijo = f"_{int(fila.evento_id)}" if fila is not None else "_nuevo"

    c = st.columns(3)
    nombre = c[0].text_input("Nombre", fila.evento if fila is not None else "GW200101_120000",
                             key="nombre" + sufijo, help="GWaammdd o GWaammdd_hhmmss (UTC).")
    gps = c[1].number_input("Tiempo GPS [s]", min_value=0.0, format="%.4f", step=1.0,
                            value=float(fila.gps_tiempo) if fila is not None else 1261915218.0,
                            key="gps" + sufijo)
    version = c[2].number_input("Versión", 1, 127, int(fila.version) if fila is not None else 1,
                                key="version" + sufijo)

    utc = fisica.gps_a_utc(gps) if gps > 0 else None
    campana = fisica.campana_por_gps(gps) if gps > 0 else None
    if utc:
        st.caption(f"⏱️ UTC calculado del GPS: **{utc:%Y-%m-%d %H:%M:%S}** · campaña deducida: "
                   f"**{campana or 'ninguna (fuera de O1–O3b)'}**")

    c = st.columns(3)
    gwosc_id = c[0].text_input("Identificador GWOSC",
                               fila.gwosc_id if fila is not None else "GW200101_120000-v1",
                               key="gwosc" + sufijo)
    nombres_cat = catalogos.nombre.tolist()
    indice_cat = nombres_cat.index(fila.catalogo) if fila is not None else len(nombres_cat) - 1
    catalogo = c[1].selectbox("Catálogo", nombres_cat, index=indice_cat, key="cat" + sufijo)
    tipos = list(fisica.TIPOS_FUENTE)
    tipo = _elegir(c[2], "Tipo de fuente",
                   {f"{t} — {fisica.DESCRIPCION_TIPOS[t]}": t for t in tipos},
                   tipos.index(fila.tipo_fuente) if fila is not None else 0, "tipo" + sufijo)
    ambigua = st.checkbox("Clasificación ambigua (alguna componente entre 2 y 5 M☉)",
                          bool(fila.clasificacion_ambigua) if fila is not None else False,
                          key="amb" + sufijo)
    referencia_txt = st.text_input("Referencia (DOI o URL)",
                                   _texto(fila.referencia) if fila is not None else "",
                                   key="ref" + sufijo)
    url_json = st.text_input("URL del JSON en GWOSC",
                             _texto(fila.url_json) if fila is not None else "",
                             key="url" + sufijo)

    campos = dict(nombre=nombre.strip(), gwosc_id=gwosc_id.strip(), version=int(version),
                  gps=float(gps), tipo_fuente=tipo, clasificacion_ambigua=ambigua,
                  catalogo_id=int(catalogos.loc[catalogos.nombre == catalogo,
                                                "catalogo_id"].iloc[0]),
                  referencia=referencia_txt.strip(), url_json=url_json.strip())
    if accion == "Crear":
        if st.button("➕ Crear evento", type="primary"):
            _ejecutar(lambda: datos.crear_evento(motor(), **campos),
                      f"Evento {campos['nombre']} creado. Agrega sus mediciones y detectores "
                      "en las otras pestañas.")
    elif st.button("💾 Guardar cambios", type="primary"):
        _ejecutar(lambda: datos.actualizar_evento(motor(), int(fila.evento_id), **campos),
                  f"Evento {campos['nombre']} actualizado.")


def crud_mediciones(df: pd.DataFrame) -> None:
    fila = _seleccionar_evento(df, "med_evento")
    if fila is None:
        return
    evento_id = int(fila.evento_id)
    med = mediciones(evento_id)
    st.markdown(f"**{len(med)} mediciones registradas para {fila.evento}**")
    vista = med[["simbolo", "parametro", "valor", "valor_min", "valor_max", "unidad"]]
    vista.columns = ["Símbolo", "Parámetro", "Valor", "Cota inferior", "Cota superior", "Unidad"]
    tabla(vista)

    parametros = referencia("parametro")
    izquierda, derecha = st.columns(2)
    with izquierda, st.container(border=True):
        st.markdown("**Agregar o actualizar una medición**")
        nombre = _elegir(st, "Parámetro",
                         {f"{p.simbolo} — {p.nombre} [{p.unidad}]": p.nombre
                          for p in parametros.itertuples()}, 0, f"par_{evento_id}")
        actual = med.loc[med.parametro == nombre]
        previo = actual.iloc[0] if not actual.empty else None
        sufijo = f"{evento_id}_{nombre}"
        valor = st.number_input("Valor central", value=_float(previo, "valor"),
                                format="%.6g", key=f"val_{sufijo}")
        c = st.columns(2)
        valor_min = c[0].number_input("Cota inferior (opcional)",
                                      value=_float(previo, "valor_min"), format="%.6g",
                                      key=f"min_{sufijo}")
        valor_max = c[1].number_input("Cota superior (opcional)",
                                      value=_float(previo, "valor_max"), format="%.6g",
                                      key=f"max_{sufijo}")
        st.caption(parametros.set_index("nombre").descripcion[nombre])
        etiqueta = "💾 Actualizar" if previo is not None else "➕ Agregar"
        if st.button(etiqueta, type="primary", key=f"guardar_{sufijo}"):
            if valor is None:
                st.error("El valor central es obligatorio.")
            else:
                _ejecutar(lambda: datos.guardar_medicion(motor(), evento_id, nombre, valor,
                                                         valor_min, valor_max),
                          f"{nombre} = {valor} guardado para {fila.evento}.")
    with derecha, st.container(border=True):
        st.markdown("**Borrar una medición**")
        if med.empty:
            st.caption("Este evento no tiene mediciones.")
        else:
            borrar = st.selectbox("Medición", med.parametro.tolist(), key=f"bm_{evento_id}")
            if st.button("🗑️ Borrar medición", key=f"btn_bm_{evento_id}"):
                parametro_id = int(med.loc[med.parametro == borrar, "parametro_id"].iloc[0])
                _ejecutar(lambda: datos.borrar_medicion(motor(), evento_id, parametro_id),
                          f"Medición {borrar} de {fila.evento} borrada.")


def crud_participaciones(df: pd.DataFrame) -> None:
    fila = _seleccionar_evento(df, "par_evento")
    if fila is None:
        return
    evento_id = int(fila.evento_id)
    detectores = referencia("detector")
    actuales = participaciones()
    actuales = actuales[actuales.evento_id == evento_id]
    vista = actuales[["detector", "nombre_detector", "archivos_strain"]]
    vista.columns = ["Sigla", "Detector", "Archivos de strain"]
    tabla(vista)

    izquierda, derecha = st.columns(2)
    with izquierda, st.container(border=True):
        st.markdown("**Agregar detector**")
        libres = detectores[~detectores.detector_id.isin(actuales.detector_id)]
        if libres.empty:
            st.caption("Todos los detectores ya participan en este evento.")
        else:
            sigla = _elegir(st, "Detector", {f"{d.sigla} — {d.nombre}": d.sigla
                                             for d in libres.itertuples()}, 0, f"ad_{evento_id}")
            archivos = st.number_input("Archivos de strain publicados", min_value=0, value=12,
                                       key=f"arch_{evento_id}")
            if st.button("➕ Agregar", type="primary", key=f"btn_ad_{evento_id}"):
                detector_id = int(libres.loc[libres.sigla == sigla, "detector_id"].iloc[0])
                _ejecutar(lambda: datos.agregar_participacion(motor(), evento_id, detector_id,
                                                              int(archivos)),
                          f"{sigla} agregado a {fila.evento}.")
    with derecha, st.container(border=True):
        st.markdown("**Quitar detector**")
        if actuales.empty:
            st.caption("Este evento no tiene detectores.")
        else:
            sigla = st.selectbox("Detector", actuales.detector.tolist(), key=f"qd_{evento_id}")
            if st.button("🗑️ Quitar", key=f"btn_qd_{evento_id}"):
                detector_id = int(actuales.loc[actuales.detector == sigla,
                                               "detector_id"].iloc[0])
                _ejecutar(lambda: datos.quitar_participacion(motor(), evento_id, detector_id),
                          f"{sigla} quitado de {fila.evento}.")


def _ejecutar(operacion, mensaje: str) -> None:
    try:
        operacion()
    except ErrorDatos as exc:
        st.error(f"❌ {exc}")
        return
    tras_escribir(mensaje)


def _elegir(contenedor, etiqueta: str, opciones: dict, indice: int, clave: str):
    """Selectbox que muestra etiquetas descriptivas y devuelve el valor asociado."""
    return opciones[contenedor.selectbox(etiqueta, list(opciones), index=indice, key=clave)]


def _float(fila: pd.Series | None, columna: str) -> float | None:
    if fila is None or pd.isna(fila[columna]):
        return None
    return float(fila[columna])


def _texto(valor) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor)


# ---------------------------------------------------------------------------------------
#  Punto de entrada
# ---------------------------------------------------------------------------------------

def main() -> None:
    try:
        df = eventos()
    except ErrorDatos as exc:
        st.title("🌌 GW Explorer")
        st.error(str(exc))
        st.stop()

    modulo, filtros = barra_lateral(df)
    if aviso := st.session_state.pop("aviso", None):
        st.success(f"✅ {aviso}")

    filtrado = aplicar_filtros(df, filtros)
    if modulo in MODULOS_CON_FILTROS and filtrado.empty:
        st.warning("Ningún evento cumple los filtros. Amplía la selección en la barra lateral.")
        st.stop()

    try:
        match modulo:
            case "🏠 Inicio":
                modulo_inicio(df)
            case "📊 Dashboard":
                modulo_dashboard(filtrado, len(df))
            case "🔭 Explorador de eventos":
                modulo_explorador(filtrado)
            case "🧪 Análisis científico":
                modulo_analisis(filtrado)
            case "📡 Detectores y strain":
                modulo_detectores()
            case "🗄️ Consultas SQL":
                modulo_consultas()
            case "✏️ Gestión de datos (CRUD)":
                modulo_crud(df)
    except ErrorDatos as exc:
        st.error(str(exc))


main()
