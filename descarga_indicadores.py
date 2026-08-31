"""
FASE 2 — Descarga de Indicadores Financieros (Banca Múltiple) de la SBS

Patrón de URL:
    https://intranet2.sbs.gob.pe/estadistica/financiera/{anio}/{MesNombre}/B-{COD_REPORTE}-{abrev}{anio}.XLS

Donde:
  - {anio}: año de 4 dígitos
  - {MesNombre}: nombre del mes en español, con mayúscula inicial (tal como
    aparece en la URL real, ej. "Mayo", "Noviembre", "Marzo", "Enero")
  - COD_REPORTE = 2401: Banca Múltiple / Indicadores Financieros (ROE, ROA,
    morosidad, CAMEL). CONFIRMADO contra B-2401-ma2026.XLS, que Andre
    descargó y cuya estructura ya está validada por el parser.
    OJO: 2402 es un reporte DISTINTO — Requerimiento de Patrimonio Efectivo
    por Tipo de Riesgo (columnas "POR RIESGO DE CRÉDITO/MERCADO/OPERACIONAL").
    Confundir los dos códigos fue justo el bug que produjo el archivo
    equivocado la primera vez.
  - {abrev}: abreviatura de 2 letras del mes, ESQUEMA CONFIRMADO con 4 puntos
    reales (en=Enero, ma=Marzo, my=Mayo, no=Noviembre). El resto de valores
    de la lista de abajo es una EXTRAPOLACIÓN razonable del mismo esquema,
    no verificada uno por uno — si algún mes falla, es el primer sospechoso.

ESTADO: la descarga en sí no se ha probado en vivo desde este entorno
(intranet2.sbs.gob.pe no es accesible aquí). El parseo del contenido SÍ
está validado (parser_indicadores_final.py) contra un archivo 2401 real.
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
    ("Febrero", "fe"),
    ("Marzo", "ma"),
    ("Abril", "ab"),
    ("Mayo", "my"),
    ("Junio", "jn"),
    ("Julio", "jl"),
    ("Agosto", "ag"),
    ("Setiembre", "se"),
    ("Octubre", "oc"),
    ("Noviembre", "no"),
    ("Diciembre", "di"),
]
# Las 12 abreviaturas están confirmadas contra archivos reales de la SBS
# (en, ma, my, no desde el inicio; fe, se, di confirmadas por Andre
# verificando manualmente las URLs de 2025). ab, jn, jl, ag, oc quedaron
# confirmadas indirectamente: descargaron con éxito en la corrida de
# descargar_historico(2015, 2026).
MESES_CONFIRMADOS = {m for m, _ in MESES}  # las 12 abreviaturas ya están validadas

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


def descargar_historico(anio_inicio: int, anio_fin: int) -> list[Path]:
    """Descarga todos los meses confirmados+extrapolados para un rango de
    años. Los meses que fallen (404, contenido inválido) se reportan pero
    no detienen el resto del histórico."""
    descargados = []
    fallidos = []
    for anio in range(anio_inicio, anio_fin + 1):
        for mes_nombre, abrev in MESES:
            ruta = descargar_indicador(anio, mes_nombre, abrev)
            if ruta:
                descargados.append(ruta)
            else:
                fallidos.append((anio, mes_nombre))
    log.info(f"Descargados: {len(descargados)} | Fallidos: {len(fallidos)}")
    if fallidos:
        log.warning(f"Meses/años sin archivo válido: {fallidos}")
    return descargados


def probar_abreviaturas(
    anio: int, mes_nombre: str, candidatos: list[str]
) -> str | None:
    """Prueba varias abreviaturas candidatas para un mes contra un año que
    ya sabemos tiene archivo publicado, y devuelve la primera que funcione."""
    for abrev in candidatos:
        url = construir_url(anio, mes_nombre, abrev)
        try:
            with httpx.Client(
                headers={"User-Agent": "Mozilla/5.0"}, verify=False
            ) as client:
                resp = client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                log.info(f"Abreviatura encontrada para {mes_nombre}: '{abrev}'")
                return abrev
            log.info(
                f"  '{abrev}' -> status {resp.status_code}, {len(resp.content)} bytes"
            )
        except httpx.HTTPError as e:
            log.info(f"  '{abrev}' -> error {e}")
    log.warning(f"Ninguna abreviatura candidata funcionó para {mes_nombre}")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "probar_abreviaturas":
        # Usa un año donde ya sabemos que SÍ hay archivo (2023 o 2024, no el
        # año actual, para no confundir "no publicado aún" con "abreviatura
        # mal escrita").
        anio_prueba = 2023
        candidatos = {
            "Febrero": ["fb", "fe", "f2"],
            "Setiembre": ["st", "se", "s9", "sp"],
            "Diciembre": ["dc", "di", "d1"],
        }
        for mes_nombre, cands in candidatos.items():
            print(f"\n--- {mes_nombre} {anio_prueba} ---")
            probar_abreviaturas(anio_prueba, mes_nombre, cands)
    elif len(sys.argv) >= 4 and sys.argv[1] == "historico":
        anio_inicio, anio_fin = int(sys.argv[2]), int(sys.argv[3])
        descargar_historico(anio_inicio, anio_fin)
    else:
        # PASO 1: descarga SOLO un archivo confirmado (Marzo 2026, o el mes/año
        # que prefieras de los 4 confirmados) para inspeccionar su estructura
        # antes de bajar todo el histórico.
        ruta = descargar_indicador(2026, "Marzo", "ma")
        if ruta:
            print(f"Archivo descargado en: {ruta}")
            print("Verifica que tenga las secciones CAMEL correctas corriendo:")
            print(f"  python parser_indicadores_final.py {ruta}")
            print("\nPara bajar todo el histórico:")
            print("  python descarga_indicadores.py historico 2015 2026")
        else:
            print("No se pudo descargar. Revisa el mensaje de warning de arriba.")
