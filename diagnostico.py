import os
import re
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.max_rows", 50)
pd.set_option("display.width", 150)

print("=" * 70)
print("DIAGNÓSTICO: por qué el modelo predice siempre el mismo valor")
print("=" * 70)

PATH_PROCESSED = os.path.join("data", "processed")

# 1. Cargar Datos
df_ratings = pd.read_csv(os.path.join(PATH_PROCESSED, "ratings_panel.csv"))

ind_files = [
    f
    for f in os.listdir(PATH_PROCESSED)
    if "indicadores" in f and (f.endswith(".csv") or f.endswith(".xlsx"))
]
file_path = os.path.join(PATH_PROCESSED, ind_files[0])
df_indicadores = (
    pd.read_csv(file_path) if file_path.endswith(".csv") else pd.read_excel(file_path)
)


def clean_str(s):
    if pd.isna(s):
        return ""
    s = str(s).upper().strip()
    s = re.sub(r"\s*-\s*", "-", s)
    return s


df_ratings["entidad_clean"] = df_ratings["entidad"].apply(clean_str)
df_ratings["periodo_clean"] = df_ratings["periodo"].apply(clean_str)

df_indicadores["entidad_clean"] = df_indicadores["entidad"].apply(clean_str)
df_indicadores["periodo_clean"] = df_indicadores["periodo"].apply(clean_str)

# --------------------------------------------------------------
print("\n--- [A] FORMATOS DE 'periodo_clean' ---")
print("Ratings (muestra):", sorted(df_ratings["periodo_clean"].unique())[:10])
print("Indicadores (muestra):", sorted(df_indicadores["periodo_clean"].unique())[:10])

# --------------------------------------------------------------
print("\n--- [B] FORMATOS DE 'entidad_clean' ---")
print("Ratings (muestra):", sorted(df_ratings["entidad_clean"].unique())[:10])
print("Indicadores (muestra):", sorted(df_indicadores["entidad_clean"].unique())[:10])

ent_ratings = set(df_ratings["entidad_clean"])
ent_indicadores = set(df_indicadores["entidad_clean"])
print(f"\nEntidades únicas en ratings: {len(ent_ratings)}")
print(f"Entidades únicas en indicadores: {len(ent_indicadores)}")
print(f"Entidades en ratings SIN match en indicadores: {len(ent_ratings - ent_indicadores)}")
if ent_ratings - ent_indicadores:
    print("Ejemplos sin match:", list(ent_ratings - ent_indicadores)[:15])

# --------------------------------------------------------------
print("\n--- [C] TARGET (rating real) ---")
rating_agencies = [
    "rating_moodys",
    "PCR (Pacific Credit Rating)",
    "Apoyo y Asociados Internacionales",
    "JCR Latino America",
]
available_agencies = [c for c in rating_agencies if c in df_ratings.columns]
df_ratings["target_num"] = df_ratings[available_agencies].bfill(axis=1).iloc[:, 0]
df_ratings_clean = df_ratings.dropna(subset=["target_num"]).copy()

print("Agencias disponibles:", available_agencies)
print("Filas con target válido:", len(df_ratings_clean), "de", len(df_ratings))
print("\nDistribución del target (value_counts):")
print(df_ratings_clean["target_num"].value_counts().sort_index())
print("\nEstadísticos del target:")
print(df_ratings_clean["target_num"].describe())

# --------------------------------------------------------------
print("\n--- [D] PIVOT DE INDICADORES ---")
df_ind_pivot = df_indicadores.pivot_table(
    index=["entidad_clean", "periodo_clean"],
    columns="indicador",
    values="valor",
    aggfunc="mean",
).reset_index()
print("Filas en pivot (combinaciones entidad+periodo únicas):", len(df_ind_pivot))
print("Columnas de indicadores generadas:", len(df_ind_pivot.columns) - 2)
print("Nombres de indicadores:", list(df_ind_pivot.columns)[2:12], "...")

# --------------------------------------------------------------
print("\n--- [E] RESULTADO DEL MERGE ---")
df_dataset = pd.merge(
    df_ratings_clean,
    df_ind_pivot,
    on=["entidad_clean", "periodo_clean"],
    how="left",
)

ignore_cols = [
    "tipo_entidad",
    "entidad",
    "periodo",
    "entidad_clean",
    "periodo_clean",
    "Apoyo y Asociados Internacionales",
    "JCR Latino America",
    "Microrate",
    "rating_moodys",
    "PCR (Pacific Credit Rating)",
    "target_num",
]
feature_cols = [
    c
    for c in df_dataset.columns
    if c not in ignore_cols and np.issubdtype(df_dataset[c].dtype, np.number)
]

print("Total filas en dataset final:", len(df_dataset))
print("Total columnas de features detectadas:", len(feature_cols))

filas_con_datos = df_dataset[feature_cols].notna().any(axis=1).sum()
filas_sin_datos = df_dataset[feature_cols].isna().all(axis=1).sum()
print(f"\nFilas con AL MENOS un indicador no-nulo: {filas_con_datos}")
print(f"Filas 100% nulas en TODOS los indicadores (sin match real): {filas_sin_datos}")
print(f"-> % de filas sin ningún dato financiero real: {100*filas_sin_datos/len(df_dataset):.1f}%")

print("\n--- [F] VARIANZA POR COLUMNA DE FEATURES (antes de fillna) ---")
print("Si la mayoría de columnas tienen std = 0 o NaN, no hay señal para el modelo:")
varianzas = df_dataset[feature_cols].std().sort_values()
print(varianzas)

print("\n--- [G] % DE NULOS POR COLUMNA ---")
pct_nulos = (df_dataset[feature_cols].isna().mean() * 100).sort_values(ascending=False)
print(pct_nulos)

print("\n" + "=" * 70)
print("RESUMEN")
print("=" * 70)
if filas_sin_datos / len(df_dataset) > 0.3:
    print("⚠️  Más del 30% de las filas NO están encontrando indicadores en el merge.")
    print("    Esto sugiere que 'entidad_clean' o 'periodo_clean' no coinciden entre")
    print("    ambos archivos (revisa las secciones [A] y [B] arriba).")
if df_ratings_clean["target_num"].std() < 1:
    print("⚠️  El target tiene muy poca varianza — casi todos los ratings reales son iguales.")
if (varianzas < 0.01).sum() > len(feature_cols) * 0.5:
    print("⚠️  Más de la mitad de las columnas de features tienen varianza casi nula.")
    print("    Esas columnas no aportan nada al modelo.")

print("\nCopia y pega TODO este output para que podamos revisarlo juntos.")