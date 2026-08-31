import os
import re
import warnings
import pandas as pd
from difflib import get_close_matches

warnings.filterwarnings("ignore")
pd.set_option("display.max_rows", 200)
pd.set_option("display.width", 150)

PATH_PROCESSED = os.path.join("data", "processed")

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
df_indicadores["entidad_clean"] = df_indicadores["entidad"].apply(clean_str)

ent_ratings = sorted(df_ratings["entidad_clean"].unique())
ent_indicadores = sorted(df_indicadores["entidad_clean"].unique())

print("=" * 70)
print(f"ENTIDADES EN RATINGS ({len(ent_ratings)}):")
print("=" * 70)
for e in ent_ratings:
    print(" -", e)

print("\n" + "=" * 70)
print(f"ENTIDADES EN INDICADORES ({len(ent_indicadores)}):")
print("=" * 70)
for e in ent_indicadores:
    print(" -", e)

print("\n" + "=" * 70)
print("SUGERENCIAS AUTOMÁTICAS DE MATCH (por similitud de texto)")
print("Revisa cada una: puede estar bien, mal, o no tener equivalente real.")
print("=" * 70)
for e in ent_ratings:
    candidatos = get_close_matches(e, ent_indicadores, n=3, cutoff=0.3)
    print(f"\nRATING: '{e}'")
    if candidatos:
        for c in candidatos:
            print(f"    posible match -> '{c}'")
    else:
        print("    (sin candidato similar -> probablemente no tiene indicadores SBS, ej. aseguradora)")

print("\n" + "=" * 70)
print("PERIODOS ÚNICOS (para revisar conversión de fecha)")
print("=" * 70)
print("Ratings:", sorted(df_ratings["periodo"].astype(str).str.upper().str.strip().unique()))
print("\nIndicadores (muestra 20):", sorted(df_indicadores["periodo"].astype(str).str.upper().str.strip().unique())[:20])

print("\n\nCopia y pega TODO este output (es largo, pero lo necesitamos completo).")