"""Backend Google Sheets con cuenta de servicio (gspread).

Credenciales (en este orden):
  GOOGLE_SERVICE_ACCOUNT_JSON  contenido JSON de la clave (secreto de GitHub Actions)
  GOOGLE_APPLICATION_CREDENTIALS  ruta a un archivo .json (uso local; nunca subirlo al repositorio)
La planilla tiene que estar compartida como Editor con el e-mail de la cuenta de servicio.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
from gspread.utils import ValueInputOption, ValueRenderOption, a1_to_rowcol

from .base import HojaDeCalculo


class ErrorCredenciales(RuntimeError):
    pass


def credenciales_desde_entorno() -> dict:
    contenido = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if contenido:
        try:
            return json.loads(contenido)
        except json.JSONDecodeError as exc:
            raise ErrorCredenciales("GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON válido") from exc
    ruta = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if ruta and Path(ruta).is_file():
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    raise ErrorCredenciales("Faltan las credenciales: definir GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_APPLICATION_CREDENTIALS")


class HojaGoogle(HojaDeCalculo):
    def __init__(self, plantilla: dict, sheet_id: str, credenciales: dict, cliente: gspread.Client | None = None):
        super().__init__(plantilla)
        self.gc = cliente or gspread.service_account_from_dict(credenciales)
        self.sh = self.gc.open_by_key(sheet_id)
        self.ws = self.sh.worksheet(plantilla["pestana_costos"])
        self.col_costo = plantilla["columna_costo_diario"]

    # --- lectura -------------------------------------------------------------------------------
    def _leer_bloque_roles(self):
        d, h = self.cfg["fila_desde"], self.cfg["fila_hasta"]
        a, c = self.cfg["columna_area"], self.col_costo
        valores = self.ws.get(f"{a}{d}:{c}{h}", value_render_option=ValueRenderOption.unformatted)
        formulas = self.ws.get(f"{c}{d}:{c}{h}", value_render_option=ValueRenderOption.formula)
        return list(valores), [f[0] if f else None for f in formulas]

    def leer_overhead(self, nombre_rango: str) -> float | None:
        try:
            datos = self.sh.values_get(nombre_rango, params={"valueRenderOption": "UNFORMATTED_VALUE"})
        except gspread.exceptions.APIError:
            return None
        valores = datos.get("values") or [[None]]
        v = valores[0][0] if valores[0] else None
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _hoja_trazabilidad(self, crear: bool = False, filas: int = 100, columnas: int = 26):
        nombre = self.cfg["pestana_trazabilidad"]
        try:
            return self.sh.worksheet(nombre)
        except gspread.exceptions.WorksheetNotFound:
            return self.sh.add_worksheet(title=nombre, rows=filas, cols=columnas) if crear else None

    def _leer_trazabilidad(self):
        ws = self._hoja_trazabilidad()
        return ws.get_values(value_render_option=ValueRenderOption.unformatted) if ws else []

    # --- escritura -----------------------------------------------------------------------------
    def escribir_costos(self, cambios):
        if not cambios:
            return
        datos = [{"range": f"{self.col_costo}{fila}", "values": [[valor]]} for fila, valor, _ in cambios]
        self.ws.batch_update(datos, value_input_option=ValueInputOption.raw)
        if self.cfg.get("escribir_notas", True):
            _, col = a1_to_rowcol(f"{self.col_costo}1")
            pedidos = [{
                "updateCells": {
                    "range": {"sheetId": self.ws.id, "startRowIndex": fila - 1, "endRowIndex": fila,
                              "startColumnIndex": col - 1, "endColumnIndex": col},
                    "rows": [{"values": [{"note": nota}]}],
                    "fields": "note",
                }
            } for fila, _, nota in cambios if nota]
            if pedidos:
                self.sh.batch_update({"requests": pedidos})

    def escribir_texto(self, celda: str, texto: str) -> None:
        self.ws.update(values=[[texto]], range_name=celda, value_input_option=ValueInputOption.raw)

    def escribir_trazabilidad(self, encabezados, filas):
        total_filas, total_cols = len(filas) + 1, len(encabezados)
        ws = self._hoja_trazabilidad(crear=True, filas=total_filas + 20, columnas=total_cols)
        if ws.row_count < total_filas or ws.col_count < total_cols:
            ws.resize(rows=max(ws.row_count, total_filas + 20), cols=max(ws.col_count, total_cols))
        ws.clear()
        ws.update(values=[encabezados] + filas, range_name="A1", value_input_option=ValueInputOption.raw)
        self._dar_formato(ws, encabezados, total_filas)

    def _dar_formato(self, ws, encabezados: list[str], total_filas: int) -> None:
        def col(nombre: str) -> int:
            return encabezados.index(nombre)

        def rango(c: int) -> dict:
            return {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": total_filas,
                    "startColumnIndex": c, "endColumnIndex": c + 1}

        pedidos = [
            {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                       "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}},
            {"setDataValidation": {"range": rango(col("Aprobar")),
                                   "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}},
            {"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS",
                                                     "startIndex": col("Clave"), "endIndex": col("Clave") + 1},
                                           "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        ]
        for nombre in ("Costo diario vigente", "Costo diario propuesto", "Hora facturable (con overhead)",
                       "Valor en la fuente"):
            pedidos.append({"repeatCell": {"range": rango(col(nombre)),
                                           "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
                                           "fields": "userEnteredFormat.numberFormat"}})
        pedidos.append({"repeatCell": {"range": rango(col("Variación")),
                                       "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}},
                                       "fields": "userEnteredFormat.numberFormat"}})
        self.sh.batch_update({"requests": pedidos})
