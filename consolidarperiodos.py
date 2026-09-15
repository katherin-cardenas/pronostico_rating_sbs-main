"""
Consolida los archivos exportados (data/raw/exportados/*.xls, que en
realidad son HTML con extensión .xls -- típico truco de ASP.NET) en un
único ratings_long.csv, mismo formato que usábamos antes:
    periodo, tipo_entidad, entidad, clasificadora, rating_letra,
    rating_ordinal
"""

import os
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

DESCARGAS_DIR = Path("data/raw/exportados")
PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

ESCALA_ORDINAL = ["D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
RATING_A_NUM = {cat: i for i, cat in enumerate(ESCALA_ORDINAL)}


def rating_a_ordinal(letra: str) -> int | None:
    if not letra:
        return None
    limpio = re.sub(r"\s+", "", letra.upper().strip())
    return RATING_A_NUM.get(limpio)


def limpiar_letra(texto: str) -> str | None:
    if not texto:
        return None
    m = re.match(r"\s*([A-D][+\-]?)", texto.strip().upper())
    return m.group(1) if m else None


def periodo_desde_nombre_archivo(nombre_archivo: str) -> str:
    """'2012_-_MARZO.xls' -> '2012 - MARZO'"""
    base = Path(nombre_archivo).stem
    return base.replace("_", " ")


def parsear_archivo_exportado(ruta: Path) -> pd.DataFrame:
    etiqueta_periodo = periodo_desde_nombre_archivo(ruta.name)
    with open(ruta, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")
    filas = soup.find_all("tr")
    if not filas:
        print(f"  ⚠️ {ruta.name}: no se encontraron filas")
        return pd.DataFrame()

    # Primera fila = encabezado
    header_tr = filas[0]
    encabezados = [
        re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip()
        for c in header_tr.find_all(["th", "td"])
    ]

    registros = []
    for tr in filas[1:]:
        celdas = tr.find_all("td", recursive=False)
        if len(celdas) < 3:
            continue  # fila "spacer" u otra fila sin datos reales
        tipo_entidad = celdas[0].get_text(strip=True)
        entidad = celdas[1].get_text(strip=True)
        if not entidad:
            continue

        for j in range(2, min(len(celdas), len(encabezados))):
            texto_celda = celdas[j].get_text(strip=True)
            if not texto_celda:
                continue
            letra = limpiar_letra(texto_celda)
            if letra is None:
                continue
            registros.append({
                "periodo": etiqueta_periodo,
                "tipo_entidad": tipo_entidad,
                "entidad": entidad,
                "clasificadora": encabezados[j],
                "rating_letra": letra,
                "rating_ordinal": rating_a_ordinal(letra),
            })

    return pd.DataFrame(registros)


def main():
    archivos = sorted(DESCARGAS_DIR.glob("*.xls")) + sorted(DESCARGAS_DIR.glob("*.xlsx"))
    print(f"--> Archivos encontrados: {len(archivos)}")

    todos = []
    for ruta in archivos:
        df = parsear_archivo_exportado(ruta)
        print(f"  {ruta.name}: {len(df)} registros extraídos")
        todos.append(df)

    df_long = pd.concat(todos, ignore_index=True) if todos else pd.DataFrame()
    print(f"\n--> Total filas consolidadas: {len(df_long)}")
    print(f"--> Entidades únicas: {df_long['entidad'].nunique()}")
    print(f"--> Periodos únicos: {df_long['periodo'].nunique()}")

    out = PROCESSED_DIR / "ratings_long.csv"
    df_long.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n✅ Guardado: {out}")


if __name__ == "__main__":
    main()