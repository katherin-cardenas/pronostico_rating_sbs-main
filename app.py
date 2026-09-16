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
import re
from io import BytesIO

import pandas as pd
import streamlit as st
import altair as alt

PATH_PROCESSED = os.path.join("data", "processed")

ESCALA_ORDINAL = ["D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
NUM_A_RATING = {i: cat for i, cat in enumerate(ESCALA_ORDINAL)}

st.set_page_config(page_title="Calificación crediticia SBS", page_icon="🏦", layout="centered")


def _prox_periodo(periodo):
    ultimo_per = str(periodo).upper()
    if "MARZO" in ultimo_per:
        return ultimo_per.replace("MARZO", "SEPTIEMBRE")
    if "SEPTIEMBRE" in ultimo_per or "SETIEMBRE" in ultimo_per:
        partes = ultimo_per.split("-")
        try:
            anio_prox = int(partes[0].strip()) + 1
            return f"{anio_prox} - MARZO"
        except (ValueError, IndexError):
            return "Siguiente Periodo"
    return "Siguiente Periodo"


def construir_reporte_excel(entidad, df_historico, df_mensual, df_indicadores):
    if entidad not in df_historico["entidad"].astype(str).tolist():
        return b""

    fila = df_historico[df_historico["entidad"] == entidad].iloc[0]
    historia = df_mensual[df_mensual["entidad_norm"] == entidad].copy()
    if not historia.empty:
        historia = historia.sort_values("periodo").reset_index(drop=True)
        historia = historia[
            [
                "periodo",
                "calificacion_mes_num",
                "calificacion_mes_letra",
                "n_agencias",
                "agencias",
            ]
        ].copy()
        historia["n_agencias"] = historia["n_agencias"].astype(str)

    resumen = pd.DataFrame(
        [
            ["Entidad", entidad],
            ["Último periodo real", fila["ultimo_periodo"]],
            ["Calificación histórica", fila["calificacion_historica_letra"]],
            ["Pronóstico EWMA", fila["calificacion_historica_letra"]],
            ["Semestres analizados", int(fila["n_periodos_considerados"])],
            ["Primer periodo", fila["primer_periodo"]],
        ],
        columns=["Indicador", "Valor"],
    )

    hojas = {"Resumen": resumen}
    if not historia.empty:
        hojas["Historial"] = historia

    if not df_indicadores.empty:
        indicadores_entidad = df_indicadores[df_indicadores["entidad"].astype(str).str.upper() == entidad.upper()].copy()
        if not indicadores_entidad.empty:
            indicadores_entidad = indicadores_entidad[["periodo", "indicador", "valor"]].reset_index(drop=True)
            hojas["Indicadores"] = indicadores_entidad

    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for nombre_hoja, df_hoja in hojas.items():
                df_hoja.to_excel(writer, sheet_name=nombre_hoja[:31], index=False)
    except ImportError:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for nombre_hoja, df_hoja in hojas.items():
                df_hoja.to_excel(writer, sheet_name=nombre_hoja[:31], index=False)

    return output.getvalue()


def construir_reporte_general(df_historico, df_mensual, df_indicadores=None):
    if df_historico is None or df_historico.empty:
        return b""

    historico = df_historico.copy()
    if "ultima_calificacion_num" not in historico.columns:
        historico["ultima_calificacion_num"] = historico.get("calificacion_historica_num", pd.Series(dtype=float))
    if "ultima_calificacion_letra" not in historico.columns:
        historico["ultima_calificacion_letra"] = historico.get("calificacion_historica_letra", pd.Series(dtype=object))
    historico["n_periodos_considerados"] = pd.to_numeric(historico["n_periodos_considerados"], errors="coerce")
    historico["calificacion_historica_num"] = pd.to_numeric(historico["calificacion_historica_num"], errors="coerce")
    historico["proximo_periodo"] = historico["ultimo_periodo"].apply(_prox_periodo)
    historico["formula_pronostico"] = (
        "EWMA con alpha=0.5. "
        "Paso 1: calificacion_mes = promedio del rating ordinal de todas las agencias del periodo. "
        "Paso 2: calificacion_historica = ewm(alpha=0.5, adjust=True).mean() del historial mensual."
    )

    resumen = historico[[
        "entidad",
        "ultimo_periodo",
        "proximo_periodo",
        "calificacion_historica_num",
        "calificacion_historica_letra",
        "ultima_calificacion_num",
        "ultima_calificacion_letra",
        "n_periodos_considerados",
        "primer_periodo",
        "formula_pronostico",
    ]].copy().sort_values("calificacion_historica_num", ascending=False)
    resumen = resumen.rename(columns={
        "entidad": "Entidad",
        "ultimo_periodo": "Último periodo real",
        "proximo_periodo": "Próximo periodo estimado",
        "calificacion_historica_num": "EWMA histórico (num)",
        "calificacion_historica_letra": "EWMA histórico (letra)",
        "ultima_calificacion_num": "Última calificación real (num)",
        "ultima_calificacion_letra": "Última calificación real (letra)",
        "n_periodos_considerados": "N° periodos",
        "primer_periodo": "Primer periodo",
        "formula_pronostico": "Fórmula de pronóstico",
    })

    historial_mensual = df_mensual.copy()
    historial_mensual["n_agencias"] = historial_mensual["n_agencias"].astype(str)
    historial_mensual["agencias"] = historial_mensual["agencias"].fillna("")

    agencias = historial_mensual[["entidad_norm", "periodo", "agencias", "n_agencias"]].copy()
    agencias = agencias.rename(columns={
        "entidad_norm": "Entidad",
        "periodo": "Periodo",
        "agencias": "Agencias que calificaron",
        "n_agencias": "N° agencias",
    })

    if df_indicadores is not None and not df_indicadores.empty:
        indicadores = df_indicadores.copy()
    else:
        indicadores = pd.DataFrame({
            "Nota": ["No se encontró el archivo de indicadores financieros (indicadores_historico.csv). "
                      "El pronóstico EWMA se basa en la serie de calificación mensual y no en un archivo de indicadores separado."]
        })

    hojas = {
        "Resumen_Global": resumen,
        "Historial_Mensual_Todos": historial_mensual,
        "Agencias_Que_Rankearon": agencias,
        "Historico_EWMA_Entidades": historico[[
            "entidad",
            "n_periodos_considerados",
            "primer_periodo",
            "ultimo_periodo",
            "ultima_calificacion_num",
            "ultima_calificacion_letra",
            "calificacion_historica_num",
            "calificacion_historica_letra",
            "proximo_periodo",
        ]].rename(columns={
            "entidad": "Entidad",
            "n_periodos_considerados": "N° periodos",
            "primer_periodo": "Primer periodo",
            "ultimo_periodo": "Último periodo real",
            "ultima_calificacion_num": "Última calificación real (num)",
            "ultima_calificacion_letra": "Última calificación real (letra)",
            "calificacion_historica_num": "EWMA histórico (num)",
            "calificacion_historica_letra": "EWMA histórico (letra)",
            "proximo_periodo": "Próximo periodo estimado",
        }),
    }

    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for nombre_hoja, df_hoja in hojas.items():
                df_hoja.to_excel(writer, sheet_name=nombre_hoja[:31], index=False)
    except ImportError:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for nombre_hoja, df_hoja in hojas.items():
                df_hoja.to_excel(writer, sheet_name=nombre_hoja[:31], index=False)

    return output.getvalue()


@st.cache_data
def cargar_datos():
    historico = pd.read_csv(os.path.join(PATH_PROCESSED, "rating_historico_ewma.csv"))
    mensual = pd.read_csv(os.path.join(PATH_PROCESSED, "rating_mensual_promedio.csv"))
    # Limpieza cosmética del periodo (algunos vienen sin espacio: "2012- MARZO")
    mensual["periodo"] = mensual["periodo"].str.replace(r"\s*-\s*", " - ", regex=True)
    return historico, mensual


def main():
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
    # Tarjetas de resumen y PRONÓSTICO
    # ---------------------------------------------------------------
    # Lógica para calcular el nombre del próximo periodo (Marzo -> Septiembre, Septiembre -> Marzo del año siguiente)
    ultimo_per = str(fila["ultimo_periodo"]).upper()
    if "MARZO" in ultimo_per:
        prox_per = ultimo_per.replace("MARZO", "SEPTIEMBRE")
    elif "SEPTIEMBRE" in ultimo_per or "SETIEMBRE" in ultimo_per:
        partes = ultimo_per.split("-")
        anio_prox = int(partes[0].strip()) + 1
        prox_per = f"{anio_prox} - MARZO"
    else:
        prox_per = "Siguiente Periodo"

    st.markdown("###  Resultados del Modelo Predictivo")

    col1, col2, col3 = st.columns(3)
    col1.metric(
        label=f"Proyección: {prox_per}",
        value=fila["calificacion_historica_letra"],
        delta="Basado en EWMA",
        delta_color="normal",
        help="Pronóstico para el próximo periodo asumiendo la inercia de la tendencia suavizada reciente."
    )
    col2.metric(
        label="Última Calificación Real",
        value=fila["ultima_calificacion_letra"],
        help=f"Calificación bruta correspondiente al periodo {fila['ultimo_periodo']}"
    )
    col3.metric(
        label="Historial Analizado",
        value=f"{int(fila['n_periodos_considerados'])} semestres",
        help=f"Desde {fila['primer_periodo']} hasta {fila['ultimo_periodo']}"
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
    # Gráfico de evolución en el tiempo con PRONÓSTICO
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
        historia_entidad["Tipo"] = "Historial Real"

        # 1. Crear la fila del pronóstico futuro
        ultimo_per = str(fila["ultimo_periodo"]).upper()
        if "MARZO" in ultimo_per:
            prox_per = ultimo_per.replace("MARZO", "SEPTIEMBRE")
        elif "SEPTIEMBRE" in ultimo_per or "SETIEMBRE" in ultimo_per:
            partes = ultimo_per.split("-")
            anio_prox = int(partes[0].strip()) + 1
            prox_per = f"{anio_prox} - MARZO"
        else:
            prox_per = "Siguiente Periodo"

        fila_pred = pd.DataFrame([{
            "periodo": prox_per,
            "calificacion_mes_num": fila["calificacion_historica_num"],
            "calificacion_mes_letra": fila["calificacion_historica_letra"],
            "rating_letra_punto": fila["calificacion_historica_letra"],
            "n_agencias": "-",
            "agencias": "Modelo Predictivo EWMA",
            "Tipo": "Proyección EWMA"
        }])

        # 2. Unir el historial con el pronóstico
        df_chart = pd.concat([historia_entidad, fila_pred], ignore_index=True)
        df_chart["n_agencias"] = df_chart["n_agencias"].astype(str)
        orden_periodos = list(historia_entidad["periodo"]) + [prox_per]

        # 3. Dibujar el gráfico usando capas (Línea continua + Puntos de colores)
        base = alt.Chart(df_chart).encode(
            x=alt.X("periodo:N", sort=orden_periodos, title="Periodo"),
            y=alt.Y(
                "calificacion_mes_num:Q",
                title="Calificación (ordinal)",
                scale=alt.Scale(domain=[0, len(ESCALA_ORDINAL) - 1]),
                axis=alt.Axis(
                    values=list(range(len(ESCALA_ORDINAL))),
                    labelExpr="[" + ",".join(f"'{v}'" for v in ESCALA_ORDINAL) + "][datum.value]",
                ),
            )
        )

        # Capa 1: La línea base (sin distinguir color para que no se rompa)
        linea = base.mark_line(color="#5c92d1", strokeWidth=2)

        # Capa 2: Los puntos sobre la línea (distinguiendo entre Real y Proyección)
        puntos = base.mark_point(size=90, opacity=1, filled=True).encode(
            color=alt.Color(
                "Tipo:N",
                scale=alt.Scale(domain=["Historial Real", "Proyección EWMA"], range=["#5c92d1", "#ff4b4b"]),
                legend=alt.Legend(title="Leyenda", orient="bottom")
            ),
            tooltip=["periodo", "rating_letra_punto", "calificacion_mes_num", "agencias", "Tipo"]
        )

        # Gráfico con la altura ampliada a 500
        grafico = alt.layer(linea, puntos).properties(height=500)
        st.altair_chart(grafico, width='stretch')

        # 4. Actualizar la tabla expandible
        with st.expander("Ver tabla completa de periodos"):
            st.dataframe(
                df_chart[
                    ["periodo", "calificacion_mes_letra", "Tipo", "n_agencias", "agencias"]
                ].rename(columns={
                    "periodo": "Periodo",
                    "calificacion_mes_letra": "Calificación",
                    "Tipo": "Origen del Dato",
                    "n_agencias": "N° agencias",
                    "agencias": "Agencias Evaluadoras",
                }),
                width="stretch",
                hide_index=True,
            )

    st.subheader(f"Contexto Financiero — {entidad_seleccionada}")
    st.markdown(
        "Evolución de los principales indicadores financieros (Rentabilidad y Solvencia) "
        "para respaldar el nivel de riesgo de la entidad."
    )

    @st.cache_data
    def cargar_indicadores():
        ruta_ind = os.path.join("data", "processed", "indicadores_historico.csv")
        if not os.path.exists(ruta_ind):
            return pd.DataFrame()
        return pd.read_csv(ruta_ind)

    df_indicadores = cargar_indicadores()

    st.download_button(
        label="📥 Descargar reporte en Excel",
        data=construir_reporte_excel(entidad_seleccionada, df_historico, df_mensual, df_indicadores),
        file_name=f"reporte_{re.sub(r'[^a-z0-9]+', '-', entidad_seleccionada.lower()).strip('-') or 'entidad'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if df_indicadores.empty:
        st.info(
            "📊 Ejecuta el script `parser_indicadores_final.py` (modo histórico) para generar "
            "`indicadores_historico.csv` y poder visualizar el contexto financiero aquí."
        )
    else:
        def limpiar_para_cruce(texto):
            if pd.isna(texto): return ""
            t = ''.join(c for c in unicodedata.normalize('NFD', str(texto).upper()) if unicodedata.category(c) != 'Mn')
            for palabra in ["BANCO DE ", "BANCO ", "BCO. ", "BCO ", "PERU"]:
                t = t.replace(palabra, "")
            return t.strip()

        entidad_query = limpiar_para_cruce(entidad_seleccionada)
        mascara_entidad = df_indicadores["entidad"].apply(
            lambda x: entidad_query in limpiar_para_cruce(x) or limpiar_para_cruce(x) in entidad_query if limpiar_para_cruce(x) else False
        )
        ind_entidad = df_indicadores[mascara_entidad].copy()

        if ind_entidad.empty:
            st.info(
                f"💡 El diagnóstico financiero detallado se encuentra actualmente habilitado solo para "
                f"el módulo de Banca Múltiple. Los datos de **{entidad_seleccionada}** se integrarán en la siguiente fase."
            )
        else:
            # Filtro estricto para evitar el problema de los picos caóticos
            palabras_clave = ["ROE", "RENTABILIDAD PATRIMONIAL", "CAPITAL GLOBAL", "UTILIDAD NETA ANUALIZADA / PATRIMONIO PROMEDIO"]
            mascara_ind = ind_entidad["indicador"].str.upper().str.contains("|".join(palabras_clave))
            df_plot = ind_entidad[mascara_ind].copy()

            if df_plot.empty:
                st.write("No se encontraron los ratios específicos en los datos de esta entidad.")
            else:
                def unificar_nombre(nombre):
                    n = str(nombre).upper()
                    if "ROE" in n or "RENTABILIDAD PATRIMONIAL" in n or "UTILIDAD NETA ANUALIZADA / PATRIMONIO PROMEDIO" in n:
                        return "ROE (%)"
                    if "CAPITAL GLOBAL" in n:
                        return "Ratio de Capital Global (%)"
                    return n

                df_plot["indicador_agrupado"] = df_plot["indicador"].apply(unificar_nombre)

                # --- DIBUJAR EN GRÁFICOS APILADOS VERTICALMENTE (DISEÑO MINIMALISTA) ---

                # Función para crear un gráfico simple y formal (Controlando color de puntos)
                def crear_grafico_limpio(df_datos, titulo, color_linea, color_punto):
                    # EXTRAEMOS Y ORDENAMOS CRONOLÓGICAMENTE LOS PERIODOS
                    periodos_ordenados = sorted(list(df_datos["periodo"].unique()))

                    grafico = (
                        alt.Chart(df_datos)
                        .mark_line(
                            point=alt.OverlayMarkDef(color=color_punto, size=70, filled=True, opacity=1),
                            strokeWidth=2.5,
                            color=color_linea
                        )
                        .encode(
                            x=alt.X(
                                "periodo:N",
                                title="Periodo",
                                sort=periodos_ordenados,
                                axis=alt.Axis(labelAngle=-45)
                            ),
                            y=alt.Y(
                                "valor:Q",
                                title="Porcentaje (%)",
                                scale=alt.Scale(zero=False)
                            ),
                            tooltip=["periodo", "indicador_agrupado", "valor"]
                        )
                        .properties(height=280, title=titulo)
                    )
                    return grafico

                # Gráfico 1 (Arriba): Solvencia
                df_solvencia = df_plot[df_plot["indicador_agrupado"] == "Ratio de Capital Global (%)"]
                if not df_solvencia.empty:
                    grafico_solvencia = crear_grafico_limpio(
                        df_solvencia,
                        "Evolución de Solvencia (Ratio de Capital Global)",
                        "#3b82f6", # Azul clásico (línea)
                        "#93c5fd"  # Azul marino (puntos)
                    )
                    st.altair_chart(grafico_solvencia, width='stretch')
                else:
                    st.write("Datos de Solvencia no disponibles.")

                st.divider()

                # Gráfico 2 (Abajo): Rentabilidad
                df_roe = df_plot[df_plot["indicador_agrupado"] == "ROE (%)"]
                if not df_roe.empty:
                    grafico_roe = crear_grafico_limpio(
                        df_roe,
                        "Evolución de Rentabilidad (ROE)",
                        "#93c5fd", # Naranja (línea)
                        "#dc2626"  # Rojo oscuro (puntos)
                    )
                    st.altair_chart(grafico_roe, width='stretch')
                else:
                    st.write("Datos de Rentabilidad no disponibles.")

    # ---------------------------------------------------------------
    # Panorama Global del Sistema Financiero
    # ---------------------------------------------------------------
    st.divider()
    st.subheader(" Panorama Global del Sistema Financiero")

    st.download_button(
        label="📥 Descargar reporte general en Excel",
        data=construir_reporte_general(df_historico, df_mensual, cargar_indicadores()),
        file_name="reporte_general_sbs.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("Ver proyecciones EWMA para todas las entidades"):
        st.markdown(
            "Esta tabla muestra la proyección de calificación crediticia para el siguiente periodo "
            "de todas las entidades analizadas, ordenadas de menor a mayor riesgo."
        )

        ruta_ewma = os.path.join("data", "processed", "rating_historico_ewma.csv")

        if os.path.exists(ruta_ewma):
            df_global_bruto = pd.read_csv(ruta_ewma)

            df_global = df_global_bruto[[
                "entidad",
                "ultimo_periodo",
                "calificacion_historica_letra",
                "calificacion_historica_num"
            ]].copy()

            df_global = df_global.sort_values(by="calificacion_historica_num", ascending=False)

            df_global = df_global.rename(columns={
                "entidad": "Entidad Financiera",
                "ultimo_periodo": "Último Dato Real",
                "calificacion_historica_letra": "Proyección EWMA (Próx. Periodo)"
            })

            st.dataframe(
                df_global[["Entidad Financiera", "Último Dato Real", "Proyección EWMA (Próx. Periodo)"]],
                width="stretch",
                hide_index=True
            )
        else:
            st.error("No se encontró el archivo de proyecciones en `data/processed/`.")


if __name__ == "__main__":
    main()