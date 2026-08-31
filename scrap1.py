"""
FASE 1 (v2) — Scraper del Resumen de Clasificaciones SBS
https://www.sbs.gob.pe/app/iece/paginas/MostrarResumenClasificaciones.aspx

Este reemplaza el enfoque de "fuerza bruta con numArchivo" del primer borrador.
Andre encontró la página correcta: una tabla ya consolidada de
(tipo_entidad, entidad, clasificadora -> letra) filtrable por período, con
botones "Consultar" y "Exportar".

ESTADO:
  [NO PROBADO EN VIVO] No tengo acceso de red a sbs.gob.pe desde este entorno,
  así que este script está escrito pero no ejecutado contra el sitio real.
  Corre primero con headless=False (ver main) para verlo actuar y ajustar
  donde falle.

Estrategia de selección de elementos:
  - Los selects (Periodo, Tipo de entidad) se ubican por posición en el DOM
    (el primer <select> de la página = Periodo, el segundo = Tipo de entidad),
    porque en formularios ASP.NET Web Forms rara vez hay <label for="...">
    asociado correctamente. Si esto falla, dímelo y ajustamos por índice o
    pedimos el name/id exacto del <select> (clic derecho > Inspeccionar).
  - Los botones se ubican por el texto visible ("Consultar", "Exportar"),
    que Playwright soporta también para <input type="submit">.
  - La tabla de resultados se ubica buscando la que contiene el texto
    "ENTIDAD" en su encabezado, y se parsea con pandas.read_html.

Requiere: pip install playwright pandas --break-system-packages
          python -m playwright install chromium
"""

from __future__ import annotations

import io
import re
import time
import logging
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sbs_resumen_scraper")

URL_RESUMEN = (
    "https://www.sbs.gob.pe/app/iece/paginas/MostrarResumenClasificaciones.aspx"
)
RAW_DIR = Path("data/raw/resumen_clasificaciones")
PROCESSED_DIR = Path("data/processed")
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

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


def rating_a_ordinal(letra: str) -> int | None:
    if not letra:
        return None
    limpio = letra.upper().strip()
    limpio = re.sub(r"\s+", "", limpio)
    return RATING_A_NUM.get(limpio)


def listar_periodos_disponibles(page: Page) -> list[str]:
    """Devuelve las etiquetas de texto de todas las opciones del dropdown
    de Periodo (ej. '2026 - MARZO', '2025 - SETIEMBRE', ...)."""
    selects = page.locator("select")
    periodo_select = selects.nth(0)  # TODO: ajustar índice si falla
    opciones = periodo_select.locator("option").all_text_contents()
    return [o.strip() for o in opciones if o.strip()]


def seleccionar_periodo(page: Page, etiqueta_periodo: str) -> None:
    selects = page.locator("select")
    periodo_select = selects.nth(0)
    periodo_select.select_option(label=etiqueta_periodo)


def consultar(page: Page) -> None:
    page.get_by_role("button", name="Consultar").click()
    # Los postbacks ASP.NET no siempre disparan 'networkidle' de forma limpia;
    # esperamos a que la tabla de resultados tenga texto "ENTIDAD".
    page.wait_for_selector("text=ENTIDAD", timeout=15000)
    time.sleep(0.5)  # margen para que termine de pintar toda la tabla


def extraer_tabla_resultado(page: Page, etiqueta_periodo: str) -> pd.DataFrame:
    """
    Extrae la tabla de resultados como DataFrame, en formato long:
    columnas [periodo, tipo_entidad, entidad, clasificadora, rating_letra,
    rating_ordinal, link_pdf].
    """
    # Ubica el <table> que contiene el encabezado "ENTIDAD"
    tabla_locator = page.locator("table").filter(has_text="ENTIDAD").first
    html_tabla = tabla_locator.evaluate("el => el.outerHTML")

    df_wide = pd.read_html(io.StringIO(html_tabla))[0]
    # Normaliza nombres de columna (pandas puede traer multi-index si hay
    # encabezados con saltos de línea, ej. "MOODYS LOCAL PE CLASIFICADORA DE\nRIESGO")
    df_wide.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df_wide.columns]

    columnas_fijas = ["TIPO DE ENTIDAD", "ENTIDAD"]
    columnas_clasificadoras = [c for c in df_wide.columns if c not in columnas_fijas]

    # Recolecta también los links (href) de cada celda con rating, para
    # trazabilidad / descarga posterior del PDF si hace falta.
    links_por_celda: dict[tuple[int, str], str] = {}
    filas = tabla_locator.locator("tr")
    n_filas = filas.count()
    for i in range(1, n_filas):  # fila 0 = encabezado
        celdas = filas.nth(i).locator("td")
        n_celdas = celdas.count()
        for j in range(n_celdas):
            link = celdas.nth(j).locator("a")
            if link.count() > 0:
                href = link.first.get_attribute("href")
                if href:
                    links_por_celda[(i - 1, j)] = href

    registros = []
    for idx, fila in df_wide.iterrows():
        tipo_entidad = fila.get("TIPO DE ENTIDAD")
        entidad = fila.get("ENTIDAD")
        for j, clasificadora in enumerate(columnas_clasificadoras, start=2):
            valor = fila.get(clasificadora)
            if pd.isna(valor) or str(valor).strip() == "":
                continue
            letra = str(valor).strip()
            registros.append(
                {
                    "periodo": etiqueta_periodo,
                    "tipo_entidad": tipo_entidad,
                    "entidad": entidad,
                    "clasificadora": clasificadora,
                    "rating_letra": letra,
                    "rating_ordinal": rating_a_ordinal(letra),
                    "link_pdf": links_por_celda.get((idx, j)),
                }
            )

    return pd.DataFrame(registros)


def scrapear_periodos(
    etiquetas_periodo: list[str], headless: bool = True
) -> pd.DataFrame:
    resultados = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(URL_RESUMEN, timeout=30000)

        disponibles = listar_periodos_disponibles(page)
        log.info("Períodos disponibles en el dropdown: %s", disponibles)

        for etiqueta in etiquetas_periodo:
            if etiqueta not in disponibles:
                log.warning("Período '%s' no está en el dropdown, se omite", etiqueta)
                continue
            log.info("Consultando período %s...", etiqueta)
            seleccionar_periodo(page, etiqueta)
            consultar(page)
            df_periodo = extraer_tabla_resultado(page, etiqueta)
            log.info("  -> %d registros extraídos", len(df_periodo))
            resultados.append(df_periodo)

            # Guarda snapshot crudo del HTML por período, por si algo falla
            (RAW_DIR / f"{etiqueta.replace(' ', '_')}.html").write_text(
                page.content(), encoding="utf-8"
            )
            time.sleep(1.0)  # cortesía entre consultas

        browser.close()

    if not resultados:
        return pd.DataFrame()
    return pd.concat(resultados, ignore_index=True)


def construir_panel_ratings(df_long: pd.DataFrame) -> pd.DataFrame:
    """Pivotea a wide: una fila por (entidad, periodo), una columna por
    clasificadora. Deja 'rating_moodys' como columna principal (target)."""
    if df_long.empty:
        return df_long

    panel = df_long.pivot_table(
        index=["tipo_entidad", "entidad", "periodo"],
        columns="clasificadora",
        values="rating_ordinal",
        aggfunc="first",
    ).reset_index()

    col_moodys = next((c for c in panel.columns if "MOODYS" in c.upper()), None)
    if col_moodys:
        panel = panel.rename(columns={col_moodys: "rating_moodys"})

    return panel


if __name__ == "__main__":
    # PASO 1 (recomendado antes de correr todo): descubre qué períodos existen
    # con headless=False para ver el navegador actuar y confirmar que los
    # selectores funcionan. Ajusta la lista de abajo según lo que veas.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(URL_RESUMEN, timeout=30000)
        print("Períodos disponibles:", listar_periodos_disponibles(page))
        browser.close()

    # PASO 2 (prueba con UN solo período, headless=False para ver qué pasa):
    periodos_objetivo = ["2026 - SEPTIEMBRE"]
    df_long = scrapear_periodos(periodos_objetivo, headless=False)
    print(df_long.head(20))
    print(f"\nTotal filas extraídas: {len(df_long)}")
    df_long.to_csv(PROCESSED_DIR / "ratings_long_prueba.csv", index=False)

    # Una vez que esto funcione bien, comenta el bloque de arriba y descomenta
    # esto para correr todos los períodos que quieras, en modo headless=True:
    #
    # periodos_objetivo = ["2026 - SEPTIEMBRE", "2026 - MARZO", "2025 - SEPTIEMBRE", ...]
    # df_long = scrapear_periodos(periodos_objetivo, headless=True)
    # df_long.to_csv(PROCESSED_DIR / "ratings_long.csv", index=False)
    #
    # panel = construir_panel_ratings(df_long)
    # panel.to_csv(PROCESSED_DIR / "ratings_panel.csv", index=False)
    #
