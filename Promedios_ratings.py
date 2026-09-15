"""
FASE 2 (nueva metodología) — Promedio de calificaciones por entidad
--------------------------------------------------------------------
Reemplaza el enfoque de red neuronal. En vez de predecir el rating con
indicadores financieros, se calcula:

  1. "Calificación del mes": el promedio de TODAS las agencias que
     calificaron a una entidad en un periodo dado (puede ser 1, 2 o 3
     agencias). Esto da una sola nota consolidada por (entidad, periodo).

  2. "Calificación histórica": un promedio de todas las calificaciones
     mensuales de una entidad a lo largo del tiempo, pero ponderado con
     EWMA (Exponentially Weighted Moving Average) para que los periodos
     más recientes pesen más que los antiguos.

Entrada esperada: el CSV "long" que produce scrap.py
    (columnas: periodo, tipo_entidad, entidad, clasificadora,
     rating_letra, rating_ordinal, link_pdf)

Requiere: pip install pandas --break-system-packages
"""

import re
import os
import pandas as pd
import numpy as np

PATH_PROCESSED = os.path.join("data", "processed")
ARCHIVO_ENTRADA = os.path.join(PATH_PROCESSED, "ratings_long.csv")

# ---------------------------------------------------------------
# Escala ordinal CORRECTA (confirmada contra el sitio real de la SBS,
# 11 niveles). La escala anterior de 0-12 con "AAA" estaba mal y se
# descarta.
# ---------------------------------------------------------------
ESCALA_ORDINAL = ["D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
RATING_A_NUM = {cat: i for i, cat in enumerate(ESCALA_ORDINAL)}
NUM_A_RATING = {i: cat for cat, i in RATING_A_NUM.items()}

MESES_ORDEN = {
    "ENERO": 0, "FEBRERO": 1, "MARZO": 2, "ABRIL": 3, "MAYO": 4, "JUNIO": 5,
    "JULIO": 6, "AGOSTO": 7, "SEPTIEMBRE": 8, "SETIEMBRE": 8, "OCTUBRE": 9,
    "NOVIEMBRE": 10, "DICIEMBRE": 11,
}

# ---------------------------------------------------------------
# FIX: normalización de nombres de entidad a través del tiempo.
# Algunas entidades cambiaron de nombre (ej. BBVA Continental -> BBVA
# Perú) o quebraron/fueron absorbidas. Sin esto, el histórico de una
# misma entidad quedaría partido en dos "entidades" distintas.
#
# IMPORTANTE: esta lista hay que completarla revisando el listado real
# de nombres de entidad que aparece en 'ratings_long.csv' una vez
# corras el scraper contra todos los periodos. Corre primero:
#   df = pd.read_csv("data/processed/ratings_long.csv")
#   print(sorted(df["entidad"].unique()))
# y busca variantes del mismo banco a través de los años.
# ---------------------------------------------------------------
ALIAS_ENTIDAD = {
    # Cambio real de tipo de entidad confirmado (Credinka pasó de Caja Rural
    # a Financiera ~2015, misma institución):
    "CRAC CREDINKA": "CREDINKA",
    "FINANC. CREDINKA": "CREDINKA",
    # Agregar aquí más casos de cambio de nombre / fusión que encuentren.
}

# Sufijos que indican que la fila NO es la calificación de la entidad en
# sí, sino de un INSTRUMENTO específico que emitió (ej. bonos de
# titulización / Asset-Backed Securities). Se excluyen del promedio de
# la entidad porque mezclan cosas distintas: el riesgo de un bono que
# venció en 2017 no es el "historial de rating" de la aseguradora.
# Confirmado con: MAPFRE PERU (ABS) y PACIFICO SEGUROS-ABS, que dejan de
# aparecer en cierto año mientras la entidad "normal" sigue calificándose
# con normalidad el resto de periodos.
SUFIJOS_EXCLUIR_INSTRUMENTO = ["(ABS)", "-ABS"]


def es_instrumento_no_entidad(nombre_entidad):
    limpio = clean_str(nombre_entidad)
    return any(sufijo in limpio for sufijo in SUFIJOS_EXCLUIR_INSTRUMENTO)


def clean_str(s):
    if pd.isna(s):
        return ""
    s = str(s).upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalizar_entidad(nombre):
    limpio = clean_str(nombre)
    return ALIAS_ENTIDAD.get(limpio, limpio)


def orden_periodo(periodo):
    """Convierte '2012 - MARZO' en una clave numérica ordenable: (año, mes)."""
    p = clean_str(periodo)
    m = re.match(r"(\d{4})\s*-\s*([A-ZÁÉÍÓÚ]+)", p)
    if not m:
        return (0, 0)
    anio, mes_nombre = m.groups()
    mes_num = MESES_ORDEN.get(mes_nombre, 0)
    return (int(anio), mes_num)


def main(alpha_ewma: float = 0.5):
    print(f"--> Cargando {ARCHIVO_ENTRADA}...")
    df = pd.read_csv(ARCHIVO_ENTRADA)

    if "rating_ordinal" not in df.columns:
        raise SystemExit(
            "El archivo no tiene columna 'rating_ordinal'. "
            "¿Seguro que es la salida de scrap.py (ratings_long.csv)?"
        )

    df = df.dropna(subset=["rating_ordinal"]).copy()

    # Excluye filas que son calificaciones de INSTRUMENTOS (bonos ABS),
    # no de la entidad como tal.
    antes = len(df)
    df = df[~df["entidad"].apply(es_instrumento_no_entidad)].copy()
    if antes != len(df):
        print(f"--> Excluidas {antes - len(df)} filas de calificaciones de instrumentos (ABS), no de entidades")

    df["entidad_norm"] = df["entidad"].apply(normalizar_entidad)
    df["orden"] = df["periodo"].apply(orden_periodo)

    print(f"--> Registros con rating válido: {len(df)}")
    print(f"--> Entidades únicas (tras normalizar nombres): {df['entidad_norm'].nunique()}")

    # -------------------------------------------------------------
    # PASO 1: Calificación del mes = promedio de todas las agencias
    # que calificaron a esa entidad en ese periodo.
    # -------------------------------------------------------------
    rating_mensual = (
        df.groupby(["entidad_norm", "periodo", "orden"])
        .agg(
            calificacion_mes_num=("rating_ordinal", "mean"),
            n_agencias=("rating_ordinal", "count"),
            agencias=("clasificadora", lambda x: ", ".join(sorted(set(x)))),
        )
        .reset_index()
    )
    rating_mensual["calificacion_mes_letra"] = (
        rating_mensual["calificacion_mes_num"]
        .round()
        .clip(0, len(ESCALA_ORDINAL) - 1)
        .map(NUM_A_RATING)
    )
    rating_mensual = rating_mensual.sort_values(["entidad_norm", "orden"])

    out_mensual = os.path.join(PATH_PROCESSED, "rating_mensual_promedio.csv")
    rating_mensual.drop(columns=["orden"]).to_csv(out_mensual, index=False, encoding="utf-8-sig")
    print(f"--> Guardado: {out_mensual} ({len(rating_mensual)} filas)")

    # -------------------------------------------------------------
    # PASO 2: Calificación histórica ponderada por recencia (EWMA).
    # alpha alto (cerca de 1) = casi todo el peso al último periodo.
    # alpha bajo (cerca de 0) = promedio casi uniforme entre todos los
    # periodos. alpha=0.5 es un punto medio razonable para empezar;
    # ajústalo y compáralo si el profesor pide justificar el valor.
    # -------------------------------------------------------------
    filas_historico = []
    for entidad, grupo in rating_mensual.groupby("entidad_norm"):
        grupo = grupo.sort_values("orden")
        serie = grupo["calificacion_mes_num"]
        ewma = serie.ewm(alpha=alpha_ewma, adjust=True).mean()
        valor_final = ewma.iloc[-1]
        filas_historico.append(
            {
                "entidad": entidad,
                "calificacion_historica_num": round(valor_final, 3),
                "calificacion_historica_letra": NUM_A_RATING.get(
                    int(np.clip(round(valor_final), 0, len(ESCALA_ORDINAL) - 1))
                ),
                "n_periodos_considerados": len(grupo),
                "primer_periodo": grupo["periodo"].iloc[0],
                "ultimo_periodo": grupo["periodo"].iloc[-1],
                "ultima_calificacion_num": round(serie.iloc[-1], 3),
                "ultima_calificacion_letra": NUM_A_RATING.get(
                    int(np.clip(round(serie.iloc[-1]), 0, len(ESCALA_ORDINAL) - 1))
                ),
            }
        )

    rating_historico = pd.DataFrame(filas_historico).sort_values(
        "calificacion_historica_num", ascending=False
    )

    out_historico = os.path.join(PATH_PROCESSED, "rating_historico_ewma.csv")
    rating_historico.to_csv(out_historico, index=False, encoding="utf-8-sig")
    print(f"--> Guardado: {out_historico} ({len(rating_historico)} entidades)")

    print(f"\n--> Parámetro usado: alpha_ewma = {alpha_ewma}")
    print("\nMuestra del ranking histórico (top 10 mejor calificadas):")
    print(rating_historico.head(10).to_string(index=False))

    print("\n--- Entidades con pocos periodos (posible quiebra/salida reciente o entrada tardía) ---")
    pocas = rating_historico[rating_historico["n_periodos_considerados"] <= 3]
    print(pocas[["entidad", "n_periodos_considerados", "primer_periodo", "ultimo_periodo"]].to_string(index=False))


if __name__ == "__main__":
    main(alpha_ewma=0.5)