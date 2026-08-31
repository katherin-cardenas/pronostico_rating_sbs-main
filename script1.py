"""
FASE 1 — Recolección y preparación de datos
Proyecto: Predicción de ratings SBS (Moody's Local PE / Apoyo & Asociados / PCR / Class)

ESTADO DE CADA PIEZA (léelo antes de correr nada):

  [CONFIRMADO]  Endpoint de descarga de informes de clasificación:
                https://extranet.sbs.gob.pe/iece/descargar?codClasificadora=..&codPeriodo=..&numArchivo=..&numVersion=1
                Códigos de clasificadora ya vistos en informes reales:
                    000406 -> Moody's Local Perú
                    000407 -> Class & Asociados
                    000408 -> Apoyo & Asociados (asociada a FitchRatings)
                PCR y Microrate: código sin confirmar todavía (ver TODO 1).

  [NO CONFIRMADO] La página índice que dice "para el período 2024-II, la entidad X
                fue clasificada por Moody's con numArchivo=17" es una vista dinámica
                (ASP.NET / JS). No pude renderizarla desde aquí porque:
                  - web_fetch solo trae el HTML estático inicial (sin JS ejecutado)
                  - mi sandbox de bash no tiene salida de red a dominios .gob.pe
                Por eso el listado de (entidad, período) -> numArchivo está marcado
                como TODO: necesitas abrir la página en tu navegador, ir a
                DevTools > Network > XHR, y ver qué URL/JSON devuelve el listado.
                Con eso reemplazas `descubrir_archivos_periodo()`.

  [NO CONFIRMADO] El Boletín Estadístico de indicadores financieros
                (bancos/cajas/financieras) usa el mismo patrón de portal ASP.NET
                con postbacks (__VIEWSTATE, __EVENTTARGET). Playwright sí puede
                manejarlo (clickeando el botón "Exportar a Excel" si existe), pero
                los selectores hay que sacarlos inspeccionando la página real.

Estructura de salida:
    data/raw/ratings/{clasificadora}/{periodo}/{numArchivo}.pdf
    data/raw/financieros/{tipo_entidad}/{periodo}.xlsx
    data/processed/ratings_panel.csv
    data/processed/financieros_panel.csv
    data/processed/panel_final.csv   (Fase 1 -> input de Fase 2)
"""

from __future__ import annotations

import re
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field

import httpx
import fitz  # PyMuPDF
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sbs_fase1")

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_URL = "https://extranet.sbs.gob.pe/iece/descargar"

# TODO 1: confirmar codClasificadora de PCR y Microrate inspeccionando informes
# suyos descargados manualmente (el PDF trae el código en la URL de origen).
CLASIFICADORAS = {
    "000406": "Moodys Local",
    "000407": "Class y Asociados",
    "000408": "Apoyo y Asociados",
    # "0004XX": "PCR",
    # "0004XX": "Microrate",
}

# ---------------------------------------------------------------------------
# 1. Escala ordinal de ratings
# ---------------------------------------------------------------------------
# Definí la escala como lista ordenada (peor -> mejor) para que sea fácil
# ajustarla si aparecen categorías que no contemplaste (AA, AA+, AAA aparecen
# en algunos informes de seguros/fondos, no solo bancos).
ESCALA_ORDINAL: list[str] = [
    "D",
    "D+",
    "C-",
    "C",
    "C+",
    "B-",
    "B",
    "B+",
    "A-",
    "A",
    "A+",
]
RATING_A_NUM: dict[str, int] = {cat: i for i, cat in enumerate(ESCALA_ORDINAL)}
NUM_A_RATING: dict[int, str] = {i: cat for cat, i in RATING_A_NUM.items()}


def rating_a_ordinal(categoria: str) -> int | None:
    """Convierte 'CATEGORÍA A+' o 'A+(pe)' o 'A +' a su valor ordinal."""
    if not categoria:
        return None
    limpio = categoria.upper()
    limpio = re.sub(r"CATEGOR[IÍ]A\s*", "", limpio)
    limpio = re.sub(r"\(PE\)", "", limpio)
    limpio = limpio.replace(" ", "").strip(".:")
    return RATING_A_NUM.get(limpio)


# ---------------------------------------------------------------------------
# 2. Descarga de informes de clasificación (Fase 1 - fuente Ratings)
# ---------------------------------------------------------------------------
@dataclass
class ArchivoClasificacion:
    cod_clasificadora: str
    periodo: str  # formato YYYYMM, ej. "202402" = 2024-II
    num_archivo: int
    num_version: int = 1


def descargar_informe(
    archivo: ArchivoClasificacion, client: httpx.Client
) -> Path | None:
    dest_dir = RAW_DIR / "ratings" / archivo.cod_clasificadora / archivo.periodo
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{archivo.num_archivo}.pdf"
    if dest.exists():
        return dest

    params = {
        "codClasificadora": archivo.cod_clasificadora,
        "codPeriodo": archivo.periodo,
        "numArchivo": archivo.num_archivo,
        "numVersion": archivo.num_version,
    }
    try:
        resp = client.get(
            DOWNLOAD_URL, params=params, timeout=30, follow_redirects=True
        )
        resp.raise_for_status()
        if "pdf" not in resp.headers.get("content-type", "").lower():
            log.warning(
                "Respuesta no-PDF para %s (numArchivo=%s), se omite",
                archivo.periodo,
                archivo.num_archivo,
            )
            return None
        dest.write_bytes(resp.content)
        return dest
    except httpx.HTTPStatusError as e:
        log.debug(
            "numArchivo=%s no existe para %s/%s (%s)",
            archivo.num_archivo,
            archivo.cod_clasificadora,
            archivo.periodo,
            e,
        )
        return None


def descubrir_archivos_periodo(
    cod_clasificadora: str, periodo: str, max_intentos: int = 60
) -> list[Path]:
    """
    TODO 2 (el paso clave que falta verificar):
    Fuerza bruta de numArchivo=1..max_intentos, descargando todo lo que responda
    200 + content-type pdf. Es lento e imperfecto (no sabes a priori cuántos
    archivos hay por período), pero funciona sin conocer la API de listado.

    Alternativa mejor (recomendada): abre la página
    https://www.sbs.gob.pe/supervisados-y-registros/registros/otros-registros/empresas-clasificadoras-de-riesgo
    con DevTools > Network > Fetch/XHR abierto, filtra por período/clasificadora
    en la UI, y copia la URL JSON que se dispara. Esa URL normalmente trae
    directamente la lista de (entidad, numArchivo) sin necesidad de fuerza bruta.
    Reemplaza esta función por una que llame a esa URL y parsee el JSON.
    """
    encontrados = []
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for n in range(1, max_intentos + 1):
            archivo = ArchivoClasificacion(cod_clasificadora, periodo, n)
            ruta = descargar_informe(archivo, client)
            if ruta:
                encontrados.append(ruta)
            time.sleep(0.3)  # cortesía: no martillar el servidor de la SBS
    log.info(
        "Período %s / clasificadora %s: %d informes descargados",
        periodo,
        cod_clasificadora,
        len(encontrados),
    )
    return encontrados


# ---------------------------------------------------------------------------
# 3. Extracción de (entidad, categoría) desde el PDF
# ---------------------------------------------------------------------------
# Patrones vistos en informes reales de Moody's/Apoyo/Class:
#   "...acordó la siguiente clasificación de riesgo para BBVA Perú: ... CATEGORÍA A"
#   "afirma la categoría B+ como Entidad a Banco Ripley Perú S.A."
#   "CATEGORÍA A(pe): Muy buena fortaleza financiera..."
PATRON_ENTIDAD_CATEGORIA = re.compile(
    r"(?:clasificaci[oó]n[^.]{0,80}?para|categor[ií]a)\s+"
    r"([A-Z\+\-]{1,4}(?:\(pe\))?)\s*(?:como\s+Entidad\s+a)?\s*"
    r"([A-ZÁÉÍÓÚÑ][\w\.\sÁÉÍÓÚÑ&]{3,60}?(?:S\.A\.?A?\.?|Perú))",
    re.IGNORECASE,
)


def extraer_rating_de_pdf(ruta_pdf: Path) -> list[dict]:
    """
    Devuelve lista de dicts {entidad, categoria, rating_ordinal} encontrados
    en el PDF. Un mismo informe puede mencionar varias entidades/instrumentos
    (bonos, CDs, depósitos) — filtra después por el que te interese (rating
    de la entidad como emisor, no de instrumentos específicos).

    OJO: esta regex es un punto de partida, no una solución cerrada. Cada
    clasificadora redacta distinto. Recomiendo correrla sobre ~10 PDFs de
    prueba y ajustar el patrón antes de lanzar el pipeline completo (así
    trabajaste los bugs de `clean_text` en el proyecto del Congreso).
    """
    resultados = []
    try:
        doc = fitz.open(ruta_pdf)
        texto = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        log.error("No se pudo abrir %s: %s", ruta_pdf, e)
        return resultados

    for match in PATRON_ENTIDAD_CATEGORIA.finditer(texto):
        categoria_raw, entidad_raw = match.group(1), match.group(2)
        ordinal = rating_a_ordinal(categoria_raw)
        if ordinal is None:
            continue
        resultados.append(
            {
                "entidad_raw": entidad_raw.strip(),
                "categoria": categoria_raw.upper(),
                "rating_ordinal": ordinal,
                "archivo_fuente": ruta_pdf.name,
            }
        )
    return resultados


# ---------------------------------------------------------------------------
# 4. Normalización de nombres de entidad (fuzzy matching, como en tu pipeline
#    de resolución de legisladores en CongressAnalysis)
# ---------------------------------------------------------------------------
def normalizar_nombre_entidad(nombre: str, catalogo: dict[str, str]) -> str | None:
    """
    catalogo: mapea variantes conocidas -> nombre canónico, ej.
        {"BBVA Perú": "Banco BBVA", "Banco BBVA Perú S.A.": "Banco BBVA", ...}
    Empieza con match exacto tras limpieza; si tu dataset crece, cambia a
    rapidfuzz.process.extractOne como hiciste con los legisladores.
    """
    limpio = re.sub(r"\s+", " ", nombre).strip().rstrip(".")
    return catalogo.get(limpio)


# ---------------------------------------------------------------------------
# 5. Construcción del panel (Entidad, Semestre)
# ---------------------------------------------------------------------------
def construir_panel_ratings(registros: list[dict]) -> pd.DataFrame:
    """
    registros: lista de dicts con al menos
        {entidad, periodo, clasificadora, rating_ordinal}
    Devuelve un panel wide: una fila por (entidad, periodo), una columna por
    clasificadora + una columna 'rating_moodys' que Fase 3 usará como target.
    """
    df = pd.DataFrame(registros)
    if df.empty:
        log.warning("No hay registros para construir el panel todavía")
        return df

    panel = df.pivot_table(
        index=["entidad", "periodo"],
        columns="clasificadora",
        values="rating_ordinal",
        aggfunc="first",
    ).reset_index()

    panel = panel.rename(columns={"Moodys Local": "rating_moodys"})
    return panel


def agregar_features_temporales(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega rating_t1 (lag de un semestre) por entidad, ordenando por periodo.
    Requiere que 'periodo' sea comparable como string YYYYS (ej. '2024-I').
    """
    panel = panel.sort_values(["entidad", "periodo"]).copy()
    panel["rating_t1"] = panel.groupby("entidad")["rating_moodys"].shift(1)
    return panel


# ---------------------------------------------------------------------------
# MAIN — orquestación de Fase 1 (ejemplo de uso)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Ejemplo: descargar todo el período 2024-II para Moody's Local.
    # Cuando tengas 'descubrir_archivos_periodo' reemplazado por la versión
    # basada en la API real, este loop cambia poco.
    periodos_a_descargar = ["202402"]  # 2024-II

    registros = []
    for cod, nombre_clasificadora in CLASIFICADORAS.items():
        for periodo in periodos_a_descargar:
            archivos = descubrir_archivos_periodo(cod, periodo, max_intentos=50)
            for pdf in archivos:
                for r in extraer_rating_de_pdf(pdf):
                    registros.append(
                        {
                            "entidad": r["entidad_raw"],
                            "periodo": periodo,
                            "clasificadora": nombre_clasificadora,
                            "rating_ordinal": r["rating_ordinal"],
                        }
                    )

    panel = construir_panel_ratings(registros)
    panel = agregar_features_temporales(panel) if not panel.empty else panel
    panel.to_csv(PROCESSED_DIR / "ratings_panel.csv", index=False)
    log.info(
        "Panel de ratings guardado en %s (%d filas)",
        PROCESSED_DIR / "ratings_panel.csv",
        len(panel),
    )
