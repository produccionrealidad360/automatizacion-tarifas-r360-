"""Casos que aparecieron en la primera corrida real en GitHub Actions y bloque de versión de la plantilla."""
from datetime import date, datetime
from types import SimpleNamespace

import gspread
import openpyxl
import requests

from tarifas import descubrimiento, publicar
from tarifas.conciliacion import conciliar
from tarifas.ejecucion import explicar_error_planilla
from tarifas.extractores import sup_pdf_ocr
from tarifas.extractores.sup_pdf_ocr import Caja
from tarifas.hojas.xlsx import HojaXlsx
from tarifas.modelos import Propuesta, Registro, ResultadoFuente


def test_sup_montos_pegados_en_una_sola_caja():
    tramos = [{"desde": date(2025, 12, 1), "porcentaje": 4.0}, {"desde": date(2026, 2, 1), "porcentaje": 8.0}]
    cajas = [Caja(100, 100, "JEFE DE PROGRAMACIÓN"), Caja(400, 101, "$1,000,000.00$1,080,000.00"),
             Caja(100, 130, "ASISTENTE"), Caja(400, 131, "$500,000.00|$540,000.00")]
    validas, invalidas = sup_pdf_ocr.parsear_renglones(sup_pdf_ocr.agrupar_renglones(cajas), tramos, 2.0)
    assert [(e, v) for _, e, v in validas] == [("JEFE DE PROGRAMACIÓN", [1_000_000.0, 1_080_000.0]),
                                               ("ASISTENTE", [500_000.0, 540_000.0])]
    assert not invalidas


class _Resp:
    def __init__(self, ok):
        self.status_code = 200 if ok else 404
        self.raw = SimpleNamespace(read=lambda n: b"%PDF-" if ok else b"<html")

    def close(self):
        pass


class _ClienteFalso:
    """La página índice responde 403 (como sicacine.org.ar desde GitHub) y solo existe el PDF de diciembre."""
    timeout = 5

    def __init__(self, existentes):
        self.existentes = existentes
        self.sesion = SimpleNamespace(get=lambda url, **kw: _Resp(url in self.existentes))

    def texto(self, url, *a, **kw):
        resp = requests.Response()
        resp.status_code = 403
        raise requests.HTTPError(response=resp)


def test_descubrimiento_por_patron_cuando_la_pagina_bloquea():
    patron = "https://sica/docs/Salarios%20Animaci%C3%B3n%202D%20{mes}%20{anio}.pdf"
    assert descubrimiento.candidatas_por_patron(patron, date(2026, 11, 2), 1, 1) == [
        "https://sica/docs/Salarios%20Animaci%C3%B3n%202D%20Diciembre%202026.pdf",
        "https://sica/docs/Salarios%20Animaci%C3%B3n%202D%20Noviembre%202026.pdf",
        "https://sica/docs/Salarios%20Animaci%C3%B3n%202D%20Octubre%202026.pdf"]
    fuente = {"descubrimiento": {"pagina": "https://sica/", "texto_enlace": "Salarios", "patron_url": patron}}
    url, aviso = descubrimiento.descubrir(fuente, _ClienteFalso({patron.format(mes="Octubre", anio=2026)}), date(2026, 11, 2))
    assert url.endswith("Octubre%202026.pdf") and aviso is None
    url, aviso = descubrimiento.descubrir(fuente, _ClienteFalso(set()), date(2026, 11, 2))
    assert url is None and "HTTP 403" in aviso


def test_mensajes_de_error_de_acceso_a_la_planilla():
    email = "tarifas-r360@proyecto.iam.gserviceaccount.com"
    sin_permiso = PermissionError()
    assert "tarifas-r360@" in explicar_error_planilla(sin_permiso, email)
    assert "Compartir" in explicar_error_planilla(sin_permiso, email)
    causa = Exception("403")
    causa.response = SimpleNamespace(text='{"error": {"status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}}')
    api_apagada = PermissionError()
    api_apagada.__cause__ = causa
    assert "Habilitar" in explicar_error_planilla(api_apagada, email)
    assert "TARIFAS_SHEET_ID" in explicar_error_planilla(gspread.exceptions.SpreadsheetNotFound(), email)


def _res(fid, entidad, nombre, periodo, ok=True):
    return ResultadoFuente(fuente_id=fid, entidad=entidad, nombre=nombre, url_usada="u", ok=ok, periodo=periodo,
                           fecha_extraccion=datetime(2026, 11, 2, 8), tipo="escala_sindical")


def _prop(fid, estado):
    return Propuesta(fila=1, area_plantilla="A", rol="R", valor_actual=1, valor_nuevo=1, estado=estado, fuente_id=fid)


def test_vigencia_por_fuente_y_conserva_la_anterior_si_una_fuente_falla():
    resultados = [_res("sica", "SICA-APMA (Sindicato…)", "Animación 2D", "01/10/2026 a 30/11/2026"),
                  _res("sup", "SUP (Sindicato Único…)", "Agencias", "", ok=False),
                  _res("coder", "Coderhouse (Coderlibrary)", "Nota", "2026")]
    anterior = "SUP · Agencias: Tramo desde 01/07/2026\nSICA-APMA · Animación 2D: 01/08/2026 a 30/09/2026"
    vigencia = publicar.armar_vigencia([_prop("sica", "aplicar"), _prop("sup", "fuente_con_error")], resultados, anterior)
    assert vigencia.splitlines() == ["SICA-APMA · Animación 2D: 01/10/2026 a 30/11/2026",
                                     "SUP · Agencias: Tramo desde 01/07/2026"]  # Coderhouse no se aplica: no figura


PLANTILLA = {"pestana_costos": "COSTOS X HORAS FACTURABLES", "columna_area": "A", "columna_rol": "B",
             "columna_costo_diario": "C", "fila_encabezado": 20, "fila_desde": 21, "fila_hasta": 30,
             "pestana_trazabilidad": "Fuentes_Tarifas", "escribir_notas": True, "texto_encabezado": "T",
             "pestana_parametros": "Parámetros", "bloque_version": {"celda_inicio": "A4"}}


def test_bloque_de_version_en_parametros_como_texto_fijo(tmp_path, calc):
    entrada = tmp_path / "in.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COSTOS X HORAS FACTURABLES"
    ws["A21"], ws["B21"], ws["C21"] = "Producción", "Coordinadora de producción", 267558
    wb.create_sheet("Parámetros")["B2"] = 0.35
    wb.save(entrada)
    res = _res("sica", "SICA-APMA (Sindicato…)", "Animación 2D", "01/10/2026 a 30/11/2026")
    res.registros = [Registro("PRODUCCIÓN", "Coordinador/a de Produccion", {"diario": 279598})]
    mapeo = [{"area": "Producción", "rol": "Coordinadora de producción", "fuente": "sica",
              "categoria": "Coordinador/a de Producción", "unidad": "diario"}]

    def correr(archivo_in, archivo_out, ahora):
        hoja = HojaXlsx(PLANTILLA, archivo_in, archivo_out)
        props, usados = conciliar([res], hoja.leer_roles(), mapeo, calc, 0.35)
        traza = publicar.construir_trazabilidad(props, [res], usados, calc, None, False)
        publicar.publicar(hoja, props, traza, PLANTILLA, False, [res], ahora, "ID-MAESTRO")
        return openpyxl.load_workbook(archivo_out)["Parámetros"]

    p = correr(entrada, tmp_path / "v1.xlsx", "02/11/2026 08:00 (ART)")
    assert p["B2"].value == 0.35  # el overhead no se toca
    assert [p.cell(r, 1).value for r in range(4, 9)] == ["Versión de tarifas", "Fecha de versión de plantilla",
                                                        "Vigencia de tarifas aplicada", "Última verificación automática",
                                                        "ID del Template Maestro"]
    assert p["B5"].value == "02/11/2026 08:00 (ART)"
    assert p["B6"].value == "SICA-APMA · Animación 2D: 01/10/2026 a 30/11/2026"
    assert p["B8"].value == "ID-MAESTRO"
    assert all(not str(p.cell(r, 2).value or "").startswith("=") for r in range(4, 9))  # sin fórmulas

    # Al día siguiente no cambia ninguna tarifa: la fecha de versión se mantiene y la verificación avanza
    p2 = correr(tmp_path / "v1.xlsx", tmp_path / "v2.xlsx", "03/11/2026 08:00 (ART)")
    assert p2["B5"].value == "02/11/2026 08:00 (ART)" and p2["B7"].value == "03/11/2026 08:00 (ART)"
