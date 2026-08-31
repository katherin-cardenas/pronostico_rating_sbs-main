"""
FASE 2 — Descarga de Indicadores Financieros (Banca Múltiple) de la SBS

Patrón de URL descubierto navegando manualmente (Andre confirmó 4 ejemplos
reales):
    https://intranet2.sbs.gob.pe/estadistica/financiera/{anio}/{MesNombre}/B-2402-{abrev}{anio}.XLS

Donde:
  - {anio}: año de 4 dígitos
  - {MesNombre}: nombre del mes en español, con mayúscula inicial (tal como
    aparece en la URL real, ej. "Mayo", "Noviembre", "Marzo", "Enero")
  - B-2402: código fijo = Banca Múltiple / reporte "Indicadores Financieros".
    Confirmado constante en 2023, 2025 y 2026 — no depende de la fecha.
  - {abrev}: abreviatura de 2 letras del mes, ESQUEMA CONFIRMADO con 4 puntos
    reales (en=Enero, ma=Marzo, my=Mayo, no=Noviembre). El resto de valores
    de la lista de abajo es una EXTRAPOLACIÓN razonable del mismo esquema,
    no verificada uno por uno — si algún mes falla, es el primer sospechoso.

ESTADO: descarga no probada en vivo (intranet2.sbs.gob.pe no es accesible
desde este entorno). El parseo del contenido del .XLS tampoco está hecho
todavía — depende de cómo esté estructurado el archivo por dentro (hojas,
si las entidades son filas o columnas, si hay encabezados multi-fila como
en el caso de ratings). Necesito que corras esto, bajes UN archivo, y me
digas qué ves con `pd.ExcelFile(archivo).sheet_names` y una vista previa de
una hoja, para escribir el parser correctamente en vez de adivinar.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sbs_indicadores")

RAW_DIR = Path("data/raw/indicadores_financieros")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Meses en el orden y forma exacta en que aparecen en la URL real
MESES = [
    ("Enero", "en"),
    ("Febrero", "fb"),
    ("Marzo", "ma"),
    ("Abril", "ab"),
    ("Mayo", "my"),
    ("Junio", "jn"),
    ("Julio", "jl"),
    ("Agosto", "ag"),
    ("Setiembre", "st"),
    ("Octubre", "oc"),
    ("Noviembre", "no"),
    ("Diciembre", "dc"),
]
# Confirmados directamente por Andre en la URL real: Enero, Marzo, Mayo, Noviembre.
# Febrero, Abril, Junio, Julio, Agosto, Setiembre, Octubre, Diciembre son
# extrapolación del mismo esquema (primeras 2 letras, con Mayo/my como caso
# especial para no chocar con Marzo/ma) — no verificados uno por uno.
MESES_CONFIRMADOS = {"Enero", "Marzo", "Mayo", "Noviembre"}

COD_REPORTE = "2401"  # Banca Múltiple / Indicadores Financieros — fijo


def construir_url(anio: int, mes_nombre: str, abrev: str) -> str:
    return (
        f"https://intranet2.sbs.gob.pe/estadistica/financiera/"
        f"{anio}/{mes_nombre}/B-{COD_REPORTE}-{abrev}{anio}.XLS"
    )


def descargar_indicador(anio: int, mes_nombre: str, abrev: str) -> Path | None:
    dest = RAW_DIR / f"{anio}_{mes_nombre}.xls"
    if dest.exists():
        return dest

    url = construir_url(anio, mes_nombre, abrev)
    try:
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0"}, verify=False
        ) as client:
            resp = client.get(url, timeout=30, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 1000:
            log.warning(
                "Sin archivo válido para %s %s -> %s (status %s, %d bytes)",
                mes_nombre,
                anio,
                url,
                resp.status_code,
                len(resp.content),
            )
            return None
        dest.write_bytes(resp.content)
        log.info("Descargado: %s (%d bytes)", dest.name, len(resp.content))
        return dest
    except httpx.HTTPError as e:
        log.warning("Error descargando %s %s: %s", mes_nombre, anio, e)
        return None


if __name__ == "__main__":
    # PASO 1: descarga SOLO un archivo confirmado (Marzo 2026, o el mes/año
    # que prefieras de los 4 confirmados) para inspeccionar su estructura
    # antes de bajar todo el histórico.
    ruta = descargar_indicador(2026, "Marzo", "ma")
    if ruta:
        print(f"Archivo descargado en: {ruta}")
        print("Ahora corre esto para ver su estructura:")
        print(f"""
import pandas as pd
xls = pd.ExcelFile(r"{ruta}")
print("Hojas:", xls.sheet_names)
df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], header=None)
print(df.head(20))
""")
    else:
        print("No se pudo descargar. Revisa el mensaje de warning de arriba.")
