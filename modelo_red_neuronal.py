import os
import re
import glob
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.callbacks import EarlyStopping

warnings.filterwarnings("ignore")

DATA_DIR = os.path.join("data", "processed")

df_ratings = pd.read_csv(os.path.join(DATA_DIR, "ratings_panel.csv"))

ind_pattern = os.path.join(DATA_DIR, "*indicadores*.[cx]*")
ind_files = glob.glob(ind_pattern)
if not ind_files:
    raise FileNotFoundError("No se encontraron archivos de indicadores.")

file_path = ind_files[0]
df_indicadores = pd.read_csv(file_path) if file_path.endswith(".csv") else pd.read_excel(file_path)


def clean_str(s):
    if pd.isna(s):
        return ""
    s = str(s).upper().strip()
    return re.sub(r"\s*-\s*", "-", s)


MESES = {
    "ENERO": "01", "FEBRERO": "02", "MARZO": "03", "ABRIL": "04",
    "MAYO": "05", "JUNIO": "06", "JULIO": "07", "AGOSTO": "08",
    "SEPTIEMBRE": "09", "SETIEMBRE": "09", "OCTUBRE": "10",
    "NOVIEMBRE": "11", "DICIEMBRE": "12",
}


def parse_periodo(periodo):
    p = clean_str(periodo)
    m = re.match(r"(\d{4})-([A-Z]+)", p)
    if not m:
        return p
    year, month_str = m.groups()
    month_num = MESES.get(month_str)
    return f"{year}-{month_num}" if month_num else p


df_ratings["entidad_clean"] = df_ratings["entidad"].apply(clean_str)
df_ratings["periodo_clean"] = df_ratings["periodo"].apply(parse_periodo)

df_indicadores["entidad_clean"] = df_indicadores["entidad"].apply(clean_str)
df_indicadores["periodo_clean"] = df_indicadores["periodo"].apply(clean_str)

df_indicadores["entidad_clean"] = df_indicadores["entidad_clean"].replace(
    "INTERBANK (CON SUCURSALES EN EL EXTERIOR",
    "INTERBANK (CON SUCURSALES EN EL EXTERIOR)"
)

ENTITY_MAP = {
    "ALFIN BANCO": "ALFIN BANCO",
    "BANCOM": "BANCOM",
    "COMPARTAMOS BANCO": "COMPARTAMOS BANCO",
    "MIBANCO": "MIBANCO",
    "INTERBANK": "INTERBANK",
    "BANBIF": "B. INTERAMERICANO DE FINANZAS",
    "BANCO BCI": "B. BCI PERÚ",
    "BANCO DE CREDITO": "B. DE CRÉDITO DEL PERÚ (CON SUCURSALES EN EL EXTERIOR)",
    "BANCO EFECTIVA": "B. EFECTIVA",
    "BANCO FALABELLA": "B. FALABELLA PERÚ",
    "BANCO GNB": "B. GNB",
    "BANCO PICHINCHA": "B. PICHINCHA",
    "BANCO RIPLEY": "B. RIPLEY",
    "BANK OF CHINA (PERU)": "BANK OF CHINA",
    "BN. SANTANDER CONS.": "SANTANDER CONSUMER BANK",
    "EMP.CRED.SANTANDER": "SANTANDER CONSUMER BANK",
    "CITIBANK DEL PERU": "CITIBANK",
    "ICBC PERU BANK S.A.": "B. ICBC",
    "SANTANDER PERU": "B. SANTANDER PERÚ",
    "SCOTIABANK PERU": "SCOTIABANK PERÚ"
}


def resolve_entity(entidad_clean, periodo_clean):
    year = int(periodo_clean[:4])
    if entidad_clean == "BBVA":
        return "B. CONTINENTAL" if year < 2019 else "B. BBVA PERÚ"
    return ENTITY_MAP.get(entidad_clean, entidad_clean)


df_ratings["entidad_match"] = df_ratings.apply(
    lambda r: resolve_entity(r["entidad_clean"], r["periodo_clean"]), axis=1
)

agencies = ["rating_moodys", "PCR (Pacific Credit Rating)", "Apoyo y Asociados Internacionales", "JCR Latino America"]
avail_agencies = [c for c in agencies if c in df_ratings.columns]
df_ratings["target_num"] = df_ratings[avail_agencies].bfill(axis=1).iloc[:, 0]
df_ratings_clean = df_ratings.dropna(subset=["target_num"]).copy()

df_ind_pivot = df_indicadores.pivot_table(
    index=["entidad_clean", "periodo_clean"],
    columns="indicador",
    values="valor",
    aggfunc="mean"
).reset_index()

df_dataset = pd.merge(
    df_ratings_clean,
    df_ind_pivot,
    left_on=["entidad_match", "periodo_clean"],
    right_on=["entidad_clean", "periodo_clean"],
    how="left",
    suffixes=("", "_ind")
)

ignore_cols = {
    "tipo_entidad", "entidad", "periodo", "entidad_clean", "entidad_clean_ind",
    "entidad_match", "periodo_clean", "Apoyo y Asociados Internacionales",
    "JCR Latino America", "Microrate", "rating_moodys", "PCR (Pacific Credit Rating)", "target_num"
}

feature_cols = [c for c in df_dataset.columns if c not in ignore_cols and np.issubdtype(df_dataset[c].dtype, np.number)]
valid_rows = df_dataset[feature_cols].notna().any(axis=1).sum()

print(f"Filas procesadas: {len(df_dataset)} | Con indicadores: {valid_rows} ({100 * valid_rows / len(df_dataset):.1f}%)")

if valid_rows == 0:
    raise RuntimeError("No se detectaron emparejamientos válidos entre entidades e indicadores.")

df_valid = df_dataset[df_dataset[feature_cols].notna().any(axis=1)].copy().reset_index(drop=True)

# Selección de features
MAX_PCT_NULOS = 40
MAX_FEATURES = 20

null_ratios = df_valid[feature_cols].isna().mean() * 100
candidate_features = null_ratios[null_ratios <= MAX_PCT_NULOS].index.tolist()

split_mask = np.zeros(len(df_valid), dtype=bool)
idx_train_tmp, _ = train_test_split(np.arange(len(df_valid)), test_size=0.2, random_state=42)
split_mask[idx_train_tmp] = True

X_imputed = df_valid[candidate_features].fillna(df_valid[candidate_features].mean())
corrs = X_imputed.loc[split_mask].apply(
    lambda col: abs(np.corrcoef(col, df_valid.loc[split_mask, "target_num"])[0, 1])
).dropna().sort_values(ascending=False)

selected_features = corrs.head(MAX_FEATURES).index.tolist()

print(f"Features seleccionadas ({len(selected_features)}):")
for f, c in corrs.head(MAX_FEATURES).items():
    print(f"  [{c:.3f}] {f}")

X = df_valid[selected_features].fillna(df_valid[selected_features].mean()).fillna(0).values
y = df_valid["target_num"].values

# Split y escalado
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Red Neuronal
model = models.Sequential([
    layers.Dense(32, activation="relu", kernel_regularizer=tf.keras.regularizers.l2(0.01), input_shape=(X_train_scaled.shape[1],)),
    layers.BatchNormalization(),
    layers.Dropout(0.4),
    layers.Dense(16, activation="relu", kernel_regularizer=tf.keras.regularizers.l2(0.01)),
    layers.Dropout(0.3),
    layers.Dense(1, activation="linear")
])

model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), loss="mse", metrics=["mae"])

es = EarlyStopping(patience=20, restore_best_weights=True)
history = model.fit(
    X_train_scaled, y_train,
    validation_data=(X_test_scaled, y_test),
    epochs=200, batch_size=32, verbose=0, callbacks=[es]
)

train_mae = history.history["mae"][-1]
val_mae = history.history["val_mae"][-1]
print(f"\nÉpoca final: {len(history.history['loss'])} | Train MAE: {train_mae:.3f} | Val MAE: {val_mae:.3f}")

# Gráfica de control
plt.figure(figsize=(10, 4))
plt.subplot(1, 2, 1)
plt.plot(history.history["loss"], label="Train")
plt.plot(history.history["val_loss"], label="Val")
plt.title("Loss (MSE)")
plt.legend()

plt.subplot(1, 2, 2)
plt.plot(history.history["mae"], label="Train")
plt.plot(history.history["val_mae"], label="Val")
plt.title("MAE")
plt.legend()

plt.tight_layout()
plt.savefig("curva_entrenamiento.png", dpi=150)

# Mapeo y exportación
RATING_MAP = {
    12: "AAA", 11: "AA+", 10: "AA", 9: "AA-", 8: "A+", 7: "A", 6: "A-",
    5: "BBB+", 4: "BBB", 3: "BB", 2: "B", 1: "C", 0: "D"
}


def to_rating_label(val):
    if pd.isna(val):
        return "N/A"
    idx = int(np.clip(round(val), 0, 12))
    return RATING_MAP.get(idx, "N/A")


preds = np.clip(model.predict(scaler.transform(X)).flatten(), 0, 12)

df_out = pd.DataFrame({
    "Entidad": df_valid["entidad"].values,
    "Periodo": df_valid["periodo"].values,
    "Rating Real Num": np.round(y, 2),
    "Rating Predicho Num": np.round(preds, 2),
    "Rating Real": [to_rating_label(v) for v in y],
    "Rating Predicho": [to_rating_label(v) for v in preds]
})

output_path = "predicciones_reporte_completo.csv"
df_out.to_csv(output_path, index=False, encoding="utf-8-sig")

print(f"Reporte exportado a {output_path} | MAE Global: {mean_absolute_error(y, preds):.2f}\n")
print(df_out.sample(min(10, len(df_out))).to_string(index=False))


# PROYECCIÓN A FUTURO (OUT-OF-SAMPLE PREDICTION)

print("\n" + "="*50)
print("INICIANDO PROYECCIÓN PARA EL PRÓXIMO BOLETÍN SBS")
print("="*50)

# 1. Identificar el periodo más reciente de los indicadores financieros
# Asumimos que los datos más recientes en df_ind_pivot son el "presente"
periodos_disponibles = df_ind_pivot["periodo_clean"].sort_values().unique()
ultimo_periodo_ind = periodos_disponibles[-1] 
print(f"-> Usando indicadores financieros del periodo: {ultimo_periodo_ind}")

# 2. Filtrar las entidades en ese último periodo (donde aún no hay rating oficial)
df_futuro = df_ind_pivot[df_ind_pivot["periodo_clean"] == ultimo_periodo_ind].copy()

# 3. Preparar la matriz X_futuro con las mismas features (las 20 seleccionadas)
# Si hay datos nulos en este mes, los rellenamos con la media histórica calculada en df_valid
for col in selected_features:
    if col in df_futuro.columns:
        df_futuro[col] = df_futuro[col].fillna(df_valid[col].mean())
    else:
        df_futuro[col] = 0  # Prevención por si una columna falta por completo

X_futuro = df_futuro[selected_features].values

# 4. Estandarizar usando el scaler ya entrenado con el pasado
X_futuro_scaled = scaler.transform(X_futuro)

# 5. Ejecutar la Red Neuronal para predecir el rating futuro
preds_futuro = np.clip(model.predict(X_futuro_scaled).flatten(), 0, 12)

# 6. Estructurar el reporte de proyección
df_prediccion_final = pd.DataFrame({
    "Entidad": df_futuro["entidad_clean"].values,
    "Periodo Indicadores": df_futuro["periodo_clean"].values,
    "Proyección septiembre 2026 (Num)": np.round(preds_futuro, 2),
    "Proyección SBS (Letra)": [to_rating_label(v) for v in preds_futuro]
})

# Ordenamos alfabéticamente para mejor presentación
df_prediccion_final = df_prediccion_final.sort_values(by="Entidad")

# 7. Mostrar y exportar
print("\n--- PREDICCIÓN PARA LA PRÓXIMA PUBLICACIÓN DE LA SBS ---")
print(df_prediccion_final.to_string(index=False))

output_futuro = "proyeccion_futura_sbs.csv"
df_prediccion_final.to_csv(output_futuro, index=False, encoding="utf-8-sig")
print(f"\n¡Proyección exitosa! Archivo guardado en: {output_futuro}")