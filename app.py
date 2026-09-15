"""
App de Streamlit — Buscador de calificación crediticia por entidad
--------------------------------------------------------------------
Lee los archivos generados por promedio_ratings.py:
    data/processed/rating_historico_ewma.csv
    data/processed/rating_mensual_promedio.csv

Corre con:
    pip install streamlit altair --break-system-packages
    streamlit run app.py
"""

import os
import pandas as pd
import streamlit as st
import altair as alt

PATH_PROCESSED = os.path.join("data", "processed")

ESCALA_ORDINAL = ["D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
NUM_A_RATING = {i: cat for i, cat in enumerate(ESCALA_ORDINAL)}

st.set_page_config(page_title="Calificación crediticia SBS", page_icon="🏦", layout="centered")


@st.cache_data
def cargar_datos():
    historico = pd.read_csv(os.path.join(PATH_PROCESSED, "rating_historico_ewma.csv"))
    mensual = pd.read_csv(os.path.join(PATH_PROCESSED, "rating_mensual_promedio.csv"))
    # Limpieza cosmética del periodo (algunos vienen sin espacio: "2012- MARZO")
    mensual["periodo"] = mensual["periodo"].str.replace(r"\s*-\s*", " - ", regex=True)
    return historico, mensual


try:
    df_historico, df_mensual = cargar_datos()
except FileNotFoundError:
    st.error(
        "No se encontraron los archivos en `data/processed/`. "
        "Corre primero `promedio_ratings.py` para generarlos."
    )
    st.stop()

st.title("🏦 Calificación crediticia histórica — SBS Perú")
st.caption(
    "Promedio ponderado por recencia (EWMA) de las calificaciones otorgadas por "
    "las agencias clasificadoras de riesgo registradas en la SBS."
)

# ---------------------------------------------------------------
# Buscador de entidad
# ---------------------------------------------------------------
entidades = sorted(df_historico["entidad"].unique())
entidad_seleccionada = st.selectbox(
    "Busca una entidad:",
    options=entidades,
    index=None,
    placeholder="Escribe para buscar (ej. BANCO DE CREDITO, INTERBANK...)",
)

if entidad_seleccionada is None:
    st.info("👆 Selecciona una entidad para ver su calificación.")
    st.stop()

fila = df_historico[df_historico["entidad"] == entidad_seleccionada].iloc[0]

# ---------------------------------------------------------------
# Tarjetas de resumen
# ---------------------------------------------------------------
col1, col2, col3 = st.columns(3)
col1.metric(
    "Calificación histórica ponderada",
    fila["calificacion_historica_letra"],
    help="Promedio EWMA de todas las calificaciones mensuales, dando más peso a los periodos recientes.",
)
col2.metric(
    "Última calificación conocida",
    fila["ultima_calificacion_letra"],
    help=f"Correspondiente al periodo {fila['ultimo_periodo']}",
)
col3.metric(
    "Periodos con datos",
    int(fila["n_periodos_considerados"]),
    help=f"Desde {fila['primer_periodo']} hasta {fila['ultimo_periodo']}",
)

if fila["n_periodos_considerados"] <= 3:
    st.warning(
        f"⚠️ Esta entidad solo tiene {int(fila['n_periodos_considerados'])} periodo(s) "
        "con calificación registrada. Puede tratarse de una entidad que salió del "
        "mercado (quiebra/fusión) o que ingresó recientemente al sistema supervisado "
        "por la SBS."
    )

st.divider()

# ---------------------------------------------------------------
# Gráfico de evolución en el tiempo
# ---------------------------------------------------------------
st.subheader(f"Evolución de calificación — {entidad_seleccionada}")

historia_entidad = df_mensual[df_mensual["entidad_norm"] == entidad_seleccionada].copy()

if historia_entidad.empty:
    st.write("No hay historial mensual detallado para esta entidad.")
else:
    historia_entidad = historia_entidad.sort_values("periodo")
    historia_entidad["rating_letra_punto"] = historia_entidad["calificacion_mes_num"].round().map(
        lambda x: NUM_A_RATING.get(int(x), "?")
    )

    grafico = (
        alt.Chart(historia_entidad)
        .mark_line(point=True)
        .encode(
            x=alt.X("periodo:N", sort=list(historia_entidad["periodo"]), title="Periodo"),
            y=alt.Y(
                "calificacion_mes_num:Q",
                title="Calificación (ordinal)",
                scale=alt.Scale(domain=[0, len(ESCALA_ORDINAL) - 1]),
                axis=alt.Axis(
                    values=list(range(len(ESCALA_ORDINAL))),
                    labelExpr="[" + ",".join(f"'{v}'" for v in ESCALA_ORDINAL) + "][datum.value]",
                ),
            ),
            tooltip=["periodo", "calificacion_mes_num", "rating_letra_punto", "n_agencias", "agencias"],
        )
        .properties(height=350)
    )
    st.altair_chart(grafico, use_container_width=True)

    with st.expander("Ver tabla completa de periodos"):
        st.dataframe(
            historia_entidad[
                ["periodo", "calificacion_mes_letra", "n_agencias", "agencias"]
            ].rename(columns={
                "periodo": "Periodo",
                "calificacion_mes_letra": "Calificación",
                "n_agencias": "N° agencias",
                "agencias": "Agencias que calificaron",
            }),
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.caption(
    "Metodología: para cada periodo se promedian todas las agencias que calificaron "
    "a la entidad ese semestre. Luego se calcula un promedio ponderado por recencia "
    "(EWMA) sobre todo el historial, dando más peso a los periodos más recientes."
)