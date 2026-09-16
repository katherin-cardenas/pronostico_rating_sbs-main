import pandas as pd

from app import construir_reporte_excel, construir_reporte_general


def test_construir_reporte_excel_generates_workbook():
    df_historico = pd.DataFrame([
        {
            "entidad": "Banco de Crédito",
            "ultimo_periodo": "2025 - MARZO",
            "calificacion_historica_letra": "A",
            "calificacion_historica_num": 8,
            "n_periodos_considerados": 10,
            "primer_periodo": "2012 - MARZO",
        }
    ])
    df_mensual = pd.DataFrame([
        {
            "entidad_norm": "Banco de Crédito",
            "periodo": "2024 - MARZO",
            "calificacion_mes_num": 8,
            "calificacion_mes_letra": "A",
            "n_agencias": 4,
            "agencias": "S&P",
        }
    ])
    df_indicadores = pd.DataFrame([
        {
            "entidad": "Banco de Crédito",
            "indicador": "ROE (%)",
            "periodo": "2025 - MARZO",
            "valor": 20.5,
        }
    ])

    report = construir_reporte_excel("Banco de Crédito", df_historico, df_mensual, df_indicadores)

    assert isinstance(report, bytes)
    assert len(report) > 0
    assert report.startswith(b"PK")


def test_construir_reporte_general_generates_workbook():
    df_historico = pd.DataFrame([
        {
            "entidad": "Banco de Crédito",
            "ultimo_periodo": "2025 - MARZO",
            "calificacion_historica_letra": "A",
            "calificacion_historica_num": 8,
            "n_periodos_considerados": 10,
            "primer_periodo": "2012 - MARZO",
        },
        {
            "entidad": "Interbank",
            "ultimo_periodo": "2025 - MARZO",
            "calificacion_historica_letra": "B+",
            "calificacion_historica_num": 7,
            "n_periodos_considerados": 8,
            "primer_periodo": "2013 - MARZO",
        },
    ])
    df_mensual = pd.DataFrame([
        {
            "entidad_norm": "Banco de Crédito",
            "periodo": "2024 - MARZO",
            "calificacion_mes_num": 8,
            "calificacion_mes_letra": "A",
            "n_agencias": 4,
            "agencias": "S&P, Fitch",
        },
        {
            "entidad_norm": "Interbank",
            "periodo": "2024 - MARZO",
            "calificacion_mes_num": 7,
            "calificacion_mes_letra": "B+",
            "n_agencias": 3,
            "agencias": "Moody's",
        },
    ])
    df_indicadores = pd.DataFrame([
        {
            "entidad": "Banco de Crédito",
            "indicador": "ROE (%)",
            "periodo": "2025 - MARZO",
            "valor": 20.5,
        }
    ])

    report = construir_reporte_general(df_historico, df_mensual, df_indicadores)

    assert isinstance(report, bytes)
    assert len(report) > 0
    assert report.startswith(b"PK")
