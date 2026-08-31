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
from bs4 import BeautifulSoup
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
    # Ojo: "ENTIDAD" ya existe en el formulario de filtros ("Tipo de entidad")
    # antes de consultar, así que esperar por ese texto no garantiza que la
    # tabla de resultados ya cargó. Esperamos "MOODYS", que solo aparece en
    # el encabezado de la tabla de resultados.
    page.wait_for_selector("text=MOODYS", timeout=15000)
    time.sleep(0.5)  # margen para que termine de pintar toda la tabla


def limpiar_letra(texto: str) -> str | None:
    """Extrae solo el token de categoría válido de una celda, descartando
    flechas de tendencia (▲/▼) u otro texto pegado (ej. 'A- ↑' -> 'A-')."""
    if not texto:
        return None
    m = re.match(r"\s*([A-D][+\-]?)", texto.strip().upper())
    return m.group(1) if m else None


def extraer_tabla_resultado(page: Page, etiqueta_periodo: str) -> pd.DataFrame:
    """
    Extrae la tabla de resultados en formato long:
    columnas [periodo, tipo_entidad, entidad, clasificadora, rating_letra,
    rating_ordinal, link_pdf].

    Parseo manual con BeautifulSoup (no pandas.read_html): la fila de
    encabezado se ubica buscando la <tr> que contiene tanto "MOODYS" como
    "ENTIDAD" en su texto, y las columnas se mapean por POSICIÓN de celda,
    no por nombre — así evitamos el problema de columnas duplicadas o mal
    alineadas que read_html producía con esta tabla.
    """
    soup = BeautifulSoup(page.content(), "html.parser")

    header_tr = None
    for tr in soup.find_all("tr"):
        texto_fila = tr.get_text(" ", strip=True).upper()
        if "MOODYS" in texto_fila and "ENTIDAD" in texto_fila:
            header_tr = tr
            break
    if header_tr is None:
        raise RuntimeError(
            "No se encontró la fila de encabezado (buscando 'MOODYS' + 'ENTIDAD'). "
            "Puede que la tabla no haya cargado o cambió el texto del encabezado."
        )

    encabezados = [
        re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip()
        for c in header_tr.find_all(["th", "td"], recursive=False)
    ]
    log.info("Encabezados detectados: %s", encabezados)

    tabla = header_tr.find_parent("table")
    todas_las_filas = tabla.find_all("tr", recursive=False)
    if header_tr not in todas_las_filas:
        # el <tr> vive dentro de un <tbody> explícito
        tbody = tabla.find("tbody")
        todas_las_filas = (
            tbody.find_all("tr", recursive=False) if tbody else tabla.find_all("tr")
        )
    idx_header = todas_las_filas.index(header_tr)
    filas_datos = todas_las_filas[idx_header + 1 :]

    registros = []
    for tr in filas_datos:
        # recursive=False es la parte clave: evita contar las <td> internas
        # de la tabla anidada "tblInnerResumen" (categoria/cambio) que vive
        # DENTRO de cada celda de calificación.
        celdas = tr.find_all("td", recursive=False)
        if len(celdas) < 3:
            continue  # fila vacía o de otro propósito (paginación, etc.)

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
            enlace = celdas[j].find("a")
            registros.append(
                {
                    "periodo": etiqueta_periodo,
                    "tipo_entidad": tipo_entidad,
                    "entidad": entidad,
                    "clasificadora": encabezados[j],
                    "rating_letra": letra,
                    "rating_ordinal": rating_a_ordinal(letra),
                    "link_pdf": enlace["href"]
                    if enlace and enlace.has_attr("href")
                    else None,
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
        # Espera explícita a que el dropdown de período tenga opciones reales
        # cargadas (no solo el placeholder "SELECCIONE"), para evitar leerlo
        # antes de tiempo.
        page.wait_for_function(
            "document.querySelectorAll('select')[0]?.options.length > 1",
            timeout=15000,
        )

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

    # PASO 2 (ya validado con un período) — corre TODO el histórico:
    periodos_objetivo = [
        "2026 - SEPTIEMBRE",
        "2026 - MARZO",
        "2025 - SEPTIEMBRE",
        "2025 - MARZO",
        "2024 - SEPTIEMBRE",
        "2024 - MARZO",
        "2023 - SEPTIEMBRE",
        "2023 - MARZO",
        "2022 - SEPTIEMBRE",
        "2022 - MARZO",
        "2021 - SEPTIEMBRE",
        "2021 - MARZO",
        "2020 - SEPTIEMBRE",
        "2020 - MARZO",
        "2019 - SEPTIEMBRE",
        "2019 - MARZO",
        "2018 - SEPTIEMBRE",
        "2018 - MARZO",
        "2017 - SEPTIEMBRE",
        "2017 - MARZO",
        "2016 - SEPTIEMBRE",
        "2016 - MARZO",
        "2015 - SEPTIEMBRE",
        "2015 - MARZO",
        "2014 - SEPTIEMBRE",
        "2014 - MARZO",
        "2013 - SEPTIEMBRE",
        "2013 - MARZO",
        "2012 - SEPTIEMBRE",
        "2012 - MARZO",
    ]
    df_long = scrapear_periodos(periodos_objetivo, headless=False)
    print(f"Total filas extraídas (todos los períodos): {len(df_long)}")
    df_long.to_csv(PROCESSED_DIR / "ratings_long.csv", index=False)

    panel = construir_panel_ratings(df_long)
    panel.to_csv(PROCESSED_DIR / "ratings_panel.csv", index=False)
    print(f"Panel final: {panel.shape[0]} filas, columnas: {list(panel.columns)}")
