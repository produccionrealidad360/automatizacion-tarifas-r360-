"""Backend Google con un cliente falso: verifica qué se lee y qué pedidos se mandan a la API."""
from unittest.mock import MagicMock

import gspread
import pytest

from tarifas import publicar
from tarifas.hojas.google import ErrorCredenciales, HojaGoogle, credenciales_desde_entorno

PLANTILLA = {"pestana_costos": "COSTOS X HORAS FACTURABLES", "columna_area": "A", "columna_rol": "B",
             "columna_costo_diario": "C", "fila_encabezado": 20, "fila_desde": 21, "fila_hasta": 25,
             "pestana_trazabilidad": "Fuentes_Tarifas", "escribir_notas": True}


def _hoja(trazabilidad_existe=True):
    ws = MagicMock(id=111, row_count=50, col_count=10)
    ws.get.side_effect = lambda rango, value_render_option: (
        [["Producción", "Coordinadora de producción", 267558], ["", "Asist. de producción", 140753], [], ["Rodaje", "Filmmaker"]]
        if rango.startswith("A") else [["267558"], ["=1400000/10"], [], []])
    traza = MagicMock(id=222, row_count=5, col_count=5)
    traza.get_values.return_value = [["Clave", "Aprobar"], ["k1", True], ["k2", False], ["k3", "VERDADERO"]]
    sh = MagicMock()
    sh.values_get.return_value = {"values": [[0.35]]}

    def worksheet(nombre):
        if nombre == "Fuentes_Tarifas" and not trazabilidad_existe:
            raise gspread.exceptions.WorksheetNotFound(nombre)
        return traza if nombre == "Fuentes_Tarifas" else ws

    sh.worksheet.side_effect = worksheet
    sh.add_worksheet.return_value = traza
    cliente = MagicMock()
    cliente.open_by_key.return_value = sh
    return HojaGoogle(PLANTILLA, "ID", {}, cliente=cliente), ws, sh, traza


def test_lee_roles_overhead_y_aprobaciones():
    hoja, ws, sh, _ = _hoja()
    filas = hoja.leer_roles()
    assert [(f.fila, f.area, f.rol, f.valor_actual, f.es_formula) for f in filas] == [
        (21, "Producción", "Coordinadora de producción", 267558.0, False),
        (22, "Producción", "Asist. de producción", 140753.0, True),
        (24, "Rodaje", "Filmmaker", None, False)]
    assert hoja.leer_overhead("Factor_Overhead") == 0.35
    assert hoja.leer_aprobaciones() == {"k1", "k3"}


def test_escribe_valores_raw_notas_y_trazabilidad():
    hoja, ws, sh, traza = _hoja(trazabilidad_existe=False)
    hoja.escribir_costos([(21, 279598.0, "nota de auditoría")])
    datos = ws.batch_update.call_args.args[0]
    assert datos == [{"range": "C21", "values": [[279598.0]]}]
    assert ws.batch_update.call_args.kwargs["value_input_option"].value == "RAW"
    nota = sh.batch_update.call_args.args[0]["requests"][0]["updateCells"]
    assert nota["range"] == {"sheetId": 111, "startRowIndex": 20, "endRowIndex": 21, "startColumnIndex": 2, "endColumnIndex": 3}
    assert nota["rows"][0]["values"][0]["note"] == "nota de auditoría"

    hoja.escribir_trazabilidad(publicar.ENCABEZADOS, [["x"] * len(publicar.ENCABEZADOS)])
    sh.add_worksheet.assert_called_once()
    traza.clear.assert_called_once()
    assert traza.update.call_args.kwargs["values"][0] == publicar.ENCABEZADOS
    pedidos = sh.batch_update.call_args.args[0]["requests"]
    assert any("setDataValidation" in p for p in pedidos)  # casilla Aprobar


def test_credenciales(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(ErrorCredenciales):
        credenciales_desde_entorno()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    assert credenciales_desde_entorno() == {"type": "service_account"}
