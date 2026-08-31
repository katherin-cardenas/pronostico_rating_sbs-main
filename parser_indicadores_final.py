from __future__ import annotations

import re
import logging
import unicodedata
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sbs_indicadores_parser")

FILA_BUSQUEDA_MAX = 15  # cuántas filas iniciales revisar buscando fecha/entidades


def _es_encabezado_seccion(texto: str) -> bool:
    if not isinstance(texto, str):
        return False
    return texto.strip().isupper() and "/" not in texto


def _detectar_periodo(df: pd.DataFrame) -> str | None:
    for i in range(min(FILA_BUSQUEDA_MAX, len(df))):
        celda = df.iloc[i, 0]
        if isinstance(celda, pd.Timestamp) or (
            hasattr(celda, "year") and hasattr(celda, "month")
        ):
            return pd.Timestamp(celda).strftime("%Y-%m")
        if isinstance(celda, str):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", celda)
            if m:
                return pd.Timestamp(m.group(1)).strftime("%Y-%m")
    log.warning(
        "No se pudo detectar la fecha de corte en las primeras filas; periodo=None"
    )
    return None


def _detectar_fila_entidades(df: pd.DataFrame) -> int:
    """La fila de entidades es la que tiene más celdas de texto no vacías
    (excluyendo la columna 0) dentro de las primeras filas del archivo."""
    mejor_fila, mejor_conteo = None, -1
    for i in range(min(FILA_BUSQUEDA_MAX, len(df))):
        fila = df.iloc[i, 1:]
        conteo = fila.apply(lambda v: isinstance(v, str) and v.strip() != "").sum()
        if conteo > mejor_conteo:
            mejor_fila, mejor_conteo = i, conteo
    if mejor_fila is None or mejor_conteo < 1:
        raise ValueError(
            "No se pudo detectar la fila de nombres de entidad en el archivo."
        )
    log.info(
        f"Fila de entidades detectada: {mejor_fila} ({mejor_conteo} entidades/columnas con texto)"
    )
    return mejor_fila


def parsear_archivo_indicadores(ruta: Path) -> pd.DataFrame:
    xls = pd.ExcelFile(ruta)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], header=None)
    ncols = df.shape[1]

    periodo = _detectar_periodo(df)
    fila_entidades = _detectar_fila_entidades(df)

    # Clasificar cada columna >0 como "etiqueta" (repite el indicador, como la
    # columna 0) o "entidad" (tiene un nombre de banco en fila_entidades).
    # Una columna es de etiqueta si en fila_entidades está vacía.
    columnas_etiqueta = [0]
    columna_entidad_de = {}  # columna de datos -> columna de etiqueta que la rige
    etiqueta_actual = 0
    for c in range(1, ncols):
        valor_entidad = df.iloc[fila_entidades, c]
        if (
            pd.isna(valor_entidad)
            or not isinstance(valor_entidad, str)
            or valor_entidad.strip() == ""
        ):
            columnas_etiqueta.append(c)
            etiqueta_actual = c
        else:
            columna_entidad_de[c] = etiqueta_actual

    entidades = {c: df.iloc[fila_entidades, c] for c in columna_entidad_de}
    log.info(
        f"Columnas de etiqueta: {columnas_etiqueta} | Columnas de entidad: {list(columna_entidad_de)}"
    )

    registros = []
    seccion_actual = {c: None for c in columnas_etiqueta}

    for i in range(fila_entidades + 1, len(df)):
        for col_lbl in columnas_etiqueta:
            etiqueta = df.iloc[i, col_lbl]
            if pd.isna(etiqueta) or not isinstance(etiqueta, str):
                continue
            if _es_encabezado_seccion(etiqueta):
                seccion_actual[col_lbl] = etiqueta.strip()
                continue

            # Es una fila de indicador para este bloque. Recorre las columnas
            # de entidad que pertenecen a este bloque de etiqueta.
            for col_dato, col_lbl_de in columna_entidad_de.items():
                if col_lbl_de != col_lbl:
                    continue
                entidad = entidades.get(col_dato)
                if pd.isna(entidad):
                    continue
                entidad_txt = normalizar_nombre_entidad(str(entidad))
                if entidad_txt.lower().startswith("total"):
                    continue  # fila de agregado del sistema, no es una entidad clasificable
                valor = df.iloc[i, col_dato]
                if pd.isna(valor):
                    continue
                try:
                    valor = float(valor)
                except (TypeError, ValueError):
                    continue
                registros.append(
                    {
                        "periodo": periodo,
                        "seccion": seccion_actual[col_lbl],
                        "indicador": etiqueta.strip(),
                        "entidad": entidad_txt,
                        "valor": valor,
                    }
                )

    return pd.DataFrame(registros)


# Normalización de nombres de entidad. El mismo banco aparece escrito con
# espacios/tabs internos distintos según el año, y con marcadores de nota al
# pie pegados al nombre (*, **, ***, "1/", etc.) que no son parte del nombre
# real. Esto NO fusiona bancos que de verdad dejaron de operar (B. Continental,
# B. Financiero, Deutsche Bank Perú, etc.) — esos siguen siendo entidades
# distintas, solo se les limpia el texto.
# ---------------------------------------------------------------------------
_RE_ESPACIOS = re.compile(r"\s+")
_RE_NOTA_PIE = re.compile(r"(\*+|\d+/)\s*$")


def normalizar_nombre_entidad(nombre: str) -> str:
    n = unicodedata.normalize("NFKC", nombre)
    n = _RE_ESPACIOS.sub(" ", n).strip()
    # quita marcadores de nota al pie al final, pueden venir encadenados
    # (ej. "Alfin Banco*** 1/" -> dos pasadas)
    while True:
        n2 = _RE_NOTA_PIE.sub("", n).strip()
        if n2 == n:
            break
        n = n2
    return n


def parsear_directorio_historico(directorio: Path) -> pd.DataFrame:
    """Corre parsear_archivo_indicadores() sobre todos los .xls de un
    directorio y devuelve un único DataFrame long con todo el histórico."""
    archivos = sorted(directorio.glob("*.xls")) + sorted(directorio.glob("*.XLS"))
    if not archivos:
        raise FileNotFoundError(f"No se encontraron archivos .xls en {directorio}")

    piezas = []
    fallidos = []
    for archivo in archivos:
        try:
            df_mes = parsear_archivo_indicadores(archivo)
            if df_mes.empty:
                log.warning(
                    f"{archivo.name}: 0 registros extraídos, revisar estructura"
                )
                fallidos.append(archivo.name)
                continue
            piezas.append(df_mes)
            log.info(
                f"{archivo.name}: {len(df_mes)} registros, período {df_mes['periodo'].iloc[0]}"
            )
        except Exception as e:
            log.warning(f"{archivo.name}: error al parsear -> {e}")
            fallidos.append(archivo.name)

    if fallidos:
        log.warning(
            f"Archivos que no se pudieron parsear ({len(fallidos)}): {fallidos}"
        )

    df_total = pd.concat(piezas, ignore_index=True)
    log.info(
        f"Total histórico: {len(df_total)} registros, {df_total['periodo'].nunique()} períodos"
    )
    return df_total


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "historico":
        directorio = (
            Path(sys.argv[2])
            if len(sys.argv) > 2
            else Path("data/raw/indicadores_financieros")
        )
        df_hist = parsear_directorio_historico(directorio)
        salida = Path("data/processed/indicadores_historico.csv")
        salida.parent.mkdir(parents=True, exist_ok=True)
        df_hist.to_csv(salida, index=False)
        print(f"\nGuardado histórico completo en {salida}: {len(df_hist)} registros")
        print(f"Períodos: {sorted(df_hist['periodo'].unique())}")
        print(
            f"Entidades ({df_hist['entidad'].nunique()}): {sorted(df_hist['entidad'].unique())}"
        )
        sys.exit(0)

    ruta = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("data/raw/indicadores_financieros/2026_Marzo.xls")
    )
    df_largo = parsear_archivo_indicadores(ruta)
    print(f"Registros extraídos: {len(df_largo)}")
    print(
        f"Período detectado: {df_largo['periodo'].iloc[0] if len(df_largo) else 'N/A'}"
    )
    print(f"Secciones encontradas: {sorted(df_largo['seccion'].dropna().unique())}")
    print(
        f"Entidades encontradas ({df_largo['entidad'].nunique()}): {sorted(df_largo['entidad'].unique())}"
    )
    print(f"Indicadores encontrados ({df_largo['indicador'].nunique()}):")
    for ind in sorted(df_largo["indicador"].unique()):
        print(f"  - {ind}")
    print("\nMuestra:")
    print(df_largo.head(15).to_string())

    salida = Path("data/processed/indicadores_long_prueba.csv")
    salida.parent.mkdir(parents=True, exist_ok=True)
    df_largo.to_csv(salida, index=False)
    print(f"\nGuardado en {salida}")
