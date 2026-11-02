"""Backend .xlsx local (openpyxl). Lee un export de la planilla y escribe el resultado en OTRO archivo:
sirve para probar todo el circuito sin credenciales y sin tocar la planilla real."""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Font

from .base import HojaDeCalculo


class HojaXlsx(HojaDeCalculo):
    def __init__(self, plantilla: dict, entrada: str | Path, salida: str | Path):
        super().__init__(plantilla)
        if Path(entrada).resolve() == Path(salida).resolve():
            raise ValueError("La salida tiene que ser un archivo distinto de la entrada")
        self.salida = Path(salida)
        self.wb = openpyxl.load_workbook(entrada)
        self.wb_valores = openpyxl.load_workbook(entrada, data_only=True)
        self.ws = self.wb[plantilla["pestana_costos"]]
        self.ws_valores = self.wb_valores[plantilla["pestana_costos"]]
        self.col_costo = plantilla["columna_costo_diario"]

    def _valor(self, formula_celda, valor_celda):
        """openpyxl no recalcula: si un archivo guardado por openpyxl perdió el valor de una fórmula del
        tipo ='HOJA'!A1, se resuelve leyendo esa celda (alcanza para los nombres de área y rol)."""
        if valor_celda is not None or not isinstance(formula_celda, str):
            return valor_celda
        m = re.fullmatch(r"=\s*'?([^'!]+)'?!\$?([A-Z]+)\$?(\d+)", formula_celda.strip())
        if m and m.group(1) in self.wb_valores.sheetnames:
            return self.wb_valores[m.group(1)][f"{m.group(2)}{m.group(3)}"].value
        return None

    def _leer_bloque_roles(self):
        d, h = self.cfg["fila_desde"], self.cfg["fila_hasta"]
        a, c = self.cfg["columna_area"], self.col_costo
        rango = f"{a}{d}:{c}{h}"
        valores = [[self._valor(cf.value, cv.value) for cf, cv in zip(ff, fv)]
                   for ff, fv in zip(self.ws[rango], self.ws_valores[rango])]
        formulas = [fila[0].value for fila in self.ws[f"{c}{d}:{c}{h}"]]
        return valores, formulas

    def leer_overhead(self, nombre_rango: str) -> float | None:
        definido = self.wb_valores.defined_names.get(nombre_rango)
        if definido is None:
            return None
        for hoja, ref in definido.destinations:
            v = self.wb_valores[hoja][ref.replace("$", "").split(":")[0]].value
            return float(v) if isinstance(v, (int, float)) else None
        return None

    def _leer_trazabilidad(self):
        nombre = self.cfg["pestana_trazabilidad"]
        if nombre not in self.wb_valores.sheetnames:
            return []
        return [list(f) for f in self.wb_valores[nombre].iter_rows(values_only=True)]

    def escribir_costos(self, cambios):
        for fila, valor, nota in cambios:
            celda = self.ws[f"{self.col_costo}{fila}"]
            celda.value = valor
            if nota and self.cfg.get("escribir_notas", True):
                celda.comment = Comment(nota, "automatizacion-tarifas", width=420, height=220)

    def escribir_texto(self, celda: str, texto: str) -> None:
        self.ws[celda].value = texto

    def escribir_trazabilidad(self, encabezados, filas):
        nombre = self.cfg["pestana_trazabilidad"]
        if nombre in self.wb.sheetnames:
            del self.wb[nombre]
        ws = self.wb.create_sheet(nombre)
        ws.append(encabezados)
        for celda in ws[1]:
            celda.font = Font(bold=True)
        for fila in filas:
            ws.append(fila)
        ws.freeze_panes = "A2"

    def guardar(self) -> None:
        self.salida.parent.mkdir(parents=True, exist_ok=True)
        self.wb.save(self.salida)
