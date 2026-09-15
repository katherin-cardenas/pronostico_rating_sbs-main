"""
Diagnóstico final: captura la RESPUESTA cruda del servidor (no lo que
mandamos) para dos periodos distintos, y compara si el contenido de
'BANCO DE CREDITO' realmente cambia entre ellos.

Esto nos dice si el bug es:
  (a) del lado del SERVIDOR (ignora el periodo, responde siempre igual), o
  (b) de cómo LEEMOS la respuesta en el navegador (quedó una tabla vieja
      en el DOM y estamos parseando esa por error).
"""

import re
from playwright.sync_api import sync_playwright

URL_RESUMEN = "https://www.sbs.gob.pe/app/iece/paginas/MostrarResumenClasificaciones.aspx"
PATRON_PERIODO = re.compile(r"^\d{4}\s*-\s*[A-ZÁÉÍÓÚ]+$")


def _localizar_select_periodo(page):
    selects = page.locator("select")
    for i in range(selects.count()):
        opciones = [o.strip() for o in selects.nth(i).locator("option").all_text_contents()]
        if any(PATRON_PERIODO.match(o) for o in opciones):
            return selects.nth(i)
    raise RuntimeError("No se encontró el select de Periodo")


def consultar_y_capturar_respuesta(page, etiqueta_periodo: str) -> str:
    """Selecciona el periodo, hace clic en Consultar, y devuelve el
    cuerpo CRUDO de la respuesta del servidor (antes de que el navegador
    la procese/pinte).

    OJO: se usa expect_response() (context manager), NO un callback
    page.on("response", ...). Llamar a response.text() dentro de un
    callback de evento en la API síncrona de Playwright falla o da
    resultados truncados/erróneos -- expect_response() es el patrón
    correcto para esto."""
    select_periodo = _localizar_select_periodo(page)
    select_periodo.select_option(label=etiqueta_periodo)

    with page.expect_response(
        lambda r: r.url == URL_RESUMEN and r.request.method == "POST",
        timeout=15000,
    ) as response_info:
        page.get_by_role("button", name="Consultar").click()

    response = response_info.value
    page.wait_for_load_state("networkidle", timeout=15000)
    return response.text()


def extraer_fragmento_banco_credito(respuesta: str) -> str:
    """Busca 'BANCO DE CREDITO' en la respuesta cruda y devuelve ~300
    caracteres alrededor, para comparar visualmente entre periodos."""
    idx = respuesta.upper().find("BANCO DE CREDITO")
    if idx == -1:
        return "(no se encontró 'BANCO DE CREDITO' en la respuesta)"
    return respuesta[max(0, idx - 50): idx + 400]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(URL_RESUMEN, timeout=30000)
        page.wait_for_function("document.querySelectorAll('select').length > 0", timeout=15000)

        print("--> Consultando 2012 - MARZO...")
        resp_2012 = consultar_y_capturar_respuesta(page, "2012 - MARZO")
        print(f"    Longitud de la respuesta: {len(resp_2012)} caracteres")

        print("\n--> Consultando 2026 - SEPTIEMBRE...")
        resp_2026 = consultar_y_capturar_respuesta(page, "2026 - SEPTIEMBRE")
        print(f"    Longitud de la respuesta: {len(resp_2026)} caracteres")

        print("\n" + "=" * 70)
        print("¿Las dos respuestas son EXACTAMENTE iguales?")
        print("=" * 70)
        print("SÍ, son idénticas" if resp_2012 == resp_2026 else "NO, son distintas")

        print("\n" + "=" * 70)
        print("FRAGMENTO 'BANCO DE CREDITO' — respuesta de 2012 - MARZO")
        print("=" * 70)
        print(extraer_fragmento_banco_credito(resp_2012))

        print("\n" + "=" * 70)
        print("FRAGMENTO 'BANCO DE CREDITO' — respuesta de 2026 - SEPTIEMBRE")
        print("=" * 70)
        print(extraer_fragmento_banco_credito(resp_2026))

        browser.close()

    print("\n\nCopia y pega TODO este output.")


if __name__ == "__main__":
    main()