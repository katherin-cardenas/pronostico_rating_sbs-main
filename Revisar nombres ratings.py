import os
import re
import pandas as pd
from difflib import SequenceMatcher

PATH_PROCESSED = os.path.join("data", "processed")
df = pd.read_csv(os.path.join(PATH_PROCESSED, "ratings_long.csv"))


def clean_str(s):
    if pd.isna(s):
        return ""
    return re.sub(r"\s+", " ", str(s).upper().strip())


df["entidad_clean"] = df["entidad"].apply(clean_str)

entidades = sorted(df["entidad_clean"].unique())
print(f"Total de nombres de entidad distintos encontrados: {len(entidades)}\n")
for e in entidades:
    print(" -", e)

print("\n" + "=" * 70)
print("POSIBLES VARIANTES DEL MISMO BANCO (nombres muy parecidos entre sí)")
print("Revisa cada par: puede ser el mismo banco con nombre distinto,")
print("o simplemente dos bancos distintos con nombre similar.")
print("=" * 70)

vistos = set()
for i, e1 in enumerate(entidades):
    for e2 in entidades[i + 1:]:
        similitud = SequenceMatcher(None, e1, e2).ratio()
        if similitud > 0.5 and (e1, e2) not in vistos:
            print(f"\n  '{e1}'  <->  '{e2}'   (similitud: {similitud:.2f})")
            vistos.add((e1, e2))

print("\n" + "=" * 70)
print("RANGO DE PERIODOS POR ENTIDAD (para detectar quiebras / entradas tardías)")
print("=" * 70)
resumen = (
    df.groupby("entidad_clean")["periodo"]
    .agg(primer_periodo="min", ultimo_periodo="max", n_periodos="nunique")
    .reset_index()
    .sort_values("n_periodos")
)
print(resumen.to_string(index=False))

print("\n\nCopia y pega todo este output.")