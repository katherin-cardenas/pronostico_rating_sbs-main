"""
FASE 1 (v4) — Descarga vía botón "Exportar" en vez de parsear HTML en vivo
----------------------------------------------------------------------------
Más robusto que parsear la tabla AJAX: solo seleccionamos el periodo y
hacemos clic en "Exportar", capturando el archivo que el navegador
descarga. Sin necesidad de esperar renders de tabla ni lidiar con
UpdatePanels.

Guarda cada archivo en data/raw/exportados/{periodo}.xxx (la extensión
depende de lo que realmente exporte el sitio - .xls, .xlsx o .csv).

NOTA: uso headless=False por defecto acá, porque se observó que el modo
headless=True puede estar siendo bloqueado/limitado por el sitio de la
SBS (los 3 periodos que sí funcionaron bien fueron todos con headless=False).
Si confirmas que headless=True funciona bien para las descargas, cámbialo.
"""

from __future__ import annotations

import re
import time
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sbs_exportador")

URL_RESUMEN = "https://www.sbs.gob.pe/app/iece/paginas/MostrarResumenClasificaciones.aspx"
DESCARGAS_DIR = Path("data/raw/exportados")
DESCARGAS_DIR.mkdir(parents=True, exist_ok=True)

PATRON_PERIODO = re.compile(r"^\d{4}\s*-\s*[A-ZÁÉÍÓÚ]+$")


def _localizar_select_periodo(page: Page):
    selects = page.locator("select")
    for i in range(selects.count()):
        opciones = [o.strip() for o in selects.nth(i).locator("option").all_text_contents()]
        if any(PATRON_PERIODO.match(o) for o in opciones):
            return selects.nth(i)
    raise RuntimeError("No se encontró el select de Periodo")


def descargar_periodo(page: Page, etiqueta_periodo: str) -> Path | None:
    select_periodo = _localizar_select_periodo(page)
    select_periodo.select_option(label=etiqueta_periodo)

    # Primero hay que consultar (si el botón Exportar solo exporta lo que
    # ya está en pantalla). Si tu sitio exporta directo sin consultar antes,
    # borra estas 2 líneas.
    page.get_by_role("button", name="Consultar").click()
    page.wait_for_load_state("networkidle", timeout=20000)

    with page.expect_download(timeout=20000) as download_info:
        page.get_by_role("button", name="Exportar").click()
    download = download_info.value

    nombre_sugerido = download.suggested_filename
    extension = Path(nombre_sugerido).suffix or ".xls"
    destino = DESCARGAS_DIR / f"{etiqueta_periodo.replace(' ', '_')}{extension}"
    download.save_as(destino)
    return destino


def descargar_todos(etiquetas_periodo: list[str], headless: bool = False) -> dict[str, Path]:
    resultados: dict[str, Path] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        page = browser.new_page()
        page.goto(URL_RESUMEN, timeout=30000)
        page.wait_for_function(
            "document.querySelectorAll('select').length > 0", timeout=30000
        )
        select_periodo = _localizar_select_periodo(page)
        disponibles = [o.strip() for o in select_periodo.locator("option").all_text_contents()]
        log.info("Períodos disponibles: %s", disponibles)
        page.close()

        for etiqueta in etiquetas_periodo:
            if etiqueta not in disponibles:
                log.warning("Período '%s' no está en el dropdown, se omite", etiqueta)
                continue

            for intento in range(1, 4):
                try:
                    log.info("Descargando %s (intento %d/3)...", etiqueta, intento)
                    page = browser.new_page()
                    page.goto(URL_RESUMEN, timeout=30000)
                    page.wait_for_function(
                        "document.querySelectorAll('select').length > 0", timeout=30000
                    )
                    ruta = descargar_periodo(page, etiqueta)
                    log.info("  -> Guardado en %s", ruta)
                    resultados[etiqueta] = ruta
                    page.close()
                    break
                except Exception as e:
                    log.warning("⚠️ Falló intento %d/3 para %s: %s", intento, etiqueta, e)
                    try:
                        page.close()
                    except Exception:
                        pass
                    time.sleep(3.0)
            else:
                log.error("❌ No se pudo descargar %s tras 3 intentos", etiqueta)

            time.sleep(1.0)

        browser.close()

    return resultados


if __name__ == "__main__":
    # Ya confirmado que la descarga funciona (.xls). Corremos el histórico completo.
    periodos_objetivo = [
        "2026 - SEPTIEMBRE", "2026 - MARZO", "2025 - SEPTIEMBRE", "2025 - MARZO",
        "2024 - SEPTIEMBRE", "2024 - MARZO", "2023 - SEPTIEMBRE", "2023 - MARZO",
        "2022 - SEPTIEMBRE", "2022 - MARZO", "2021 - SEPTIEMBRE", "2021 - MARZO",
        "2020 - SEPTIEMBRE", "2020 - MARZO", "2019 - SEPTIEMBRE", "2019 - MARZO",
        "2018 - SEPTIEMBRE", "2018 - MARZO", "2017 - SEPTIEMBRE", "2017 - MARZO",
        "2016 - SEPTIEMBRE", "2016 - MARZO", "2015 - SEPTIEMBRE", "2015 - MARZO",
        "2014 - SEPTIEMBRE", "2014 - MARZO", "2013 - SEPTIEMBRE", "2013 - MARZO",
        "2012 - SEPTIEMBRE", "2012 - MARZO",
    ]
    resultados = descargar_todos(periodos_objetivo, headless=False)
    print(f"\nTotal de periodos descargados: {len(resultados)} de {len(periodos_objetivo)}")
    for periodo, ruta in resultados.items():
        print(f"  {periodo}: {ruta}")