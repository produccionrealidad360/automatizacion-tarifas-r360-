"""Circuito completo de publicación sobre un .xlsx chico con el mismo formato que la planilla."""
from datetime import datetime

import openpyxl

from tarifas import publicar
from tarifas.conciliacion import conciliar
from tarifas.hojas.xlsx import HojaXlsx
from tarifas.modelos import Registro, ResultadoFuente

PLANTILLA = {"pestana_costos": "COSTOS X HORAS FACTURABLES", "columna_area": "A", "columna_rol": "B",
             "columna_costo_diario": "C", "fila_encabezado": 20, "fila_desde": 21, "fila_hasta": 30,
             "pestana_trazabilidad": "Fuentes_Tarifas", "escribir_notas": True, "texto_encabezado": "TOTAL BÁSICO DIARIO"}


def _libro(ruta):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COSTOS X HORAS FACTURABLES"
    ws["C20"] = "TOTAL BÁSICO DIARIO AGOSTO 2026"
    ws["A21"], ws["B21"], ws["C21"] = "Producción", "Coordinadora de producción", 267558
    ws["B22"], ws["C22"] = "Asist. de producción", 140753
    ws["A23"], ws["B23"], ws["C23"] = "Rodaje", "Filmmaker", 396835
    wb.save(ruta)


def test_publica_costo_nota_y_trazabilidad(tmp_path, calc):
    entrada, salida = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    _libro(entrada)
    hoja = HojaXlsx(PLANTILLA, entrada, salida)
    filas = hoja.leer_roles()
    assert [(f.fila, f.area, f.rol) for f in filas] == [(21, "Producción", "Coordinadora de producción"),
                                                        (22, "Producción", "Asist. de producción"), (23, "Rodaje", "Filmmaker")]
    res = ResultadoFuente(fuente_id="sica", entidad="SICA", nombre="Animación 2D", url_usada="https://sica/pdf", ok=True,
                          fecha_extraccion=datetime(2026, 11, 2, 8), periodo="01/10/2026 a 30/11/2026",
                          registros=[Registro("PRODUCCIÓN", "Coordinador/a de Produccion", {"diario": 279598}),
                                     Registro("PRODUCCIÓN", "Asistente de Produccion", {"diario": 147087}),
                                     Registro("SONIDO", "Operador/a", {"diario": 155334})])
    mapeo = [{"area": "Producción", "rol": "Coordinadora de producción", "fuente": "sica", "categoria": "Coordinador/a de Producción", "unidad": "diario"},
             {"area": "Producción", "rol": "Asist. de producción", "fuente": "sica", "categoria": "Asistente de Producción", "unidad": "diario", "modo": "revision"}]
    props, usados = conciliar([res], filas, mapeo, calc, 0.0)
    traza = publicar.construir_trazabilidad(props, [res], usados, calc, None, simulacion=False)
    assert publicar.publicar(hoja, props, traza, PLANTILLA, simulacion=False) == 1

    wb = openpyxl.load_workbook(salida)
    ws = wb["COSTOS X HORAS FACTURABLES"]
    assert ws["C21"].value == 279598 and ws["C22"].value == 140753  # el pendiente no se toca
    nota = ws["C21"].comment.text
    assert "https://sica/pdf" in nota and "01/10/2026 a 30/11/2026" in nota and "2026-11-02" in nota
    assert ws["C20"].value == "TOTAL BÁSICO DIARIO"
    t = wb["Fuentes_Tarifas"]
    encabezado = [c.value for c in t[1]]
    assert encabezado == publicar.ENCABEZADOS
    estados = [r[1] for r in t.iter_rows(min_row=2, values_only=True)]
    assert estados.count("Pendiente de revisión") == 1 and "Aplicado" in estados
    assert "Categoría sin mapear" in estados  # Operador/a quedó en el listado de la fuente

    # Segunda corrida: se marca Aprobar en el pendiente y se aplica
    i_ap = encabezado.index("Aprobar") + 1
    for r in range(2, t.max_row + 1):
        if t.cell(r, 2).value == "Pendiente de revisión":
            t.cell(r, i_ap).value = True
    wb.save(entrada)
    hoja2 = HojaXlsx(PLANTILLA, entrada, tmp_path / "out2.xlsx")
    props2, _ = conciliar([res], hoja2.leer_roles(), mapeo, calc, 0.0, hoja2.leer_aprobaciones())
    assert {p.rol: p.estado for p in props2}["Asist. de producción"] == "aplicar"


def test_simulacion_no_escribe(tmp_path, calc):
    entrada, salida = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    _libro(entrada)
    hoja = HojaXlsx(PLANTILLA, entrada, salida)
    assert publicar.publicar(hoja, [], [], PLANTILLA, simulacion=True) == 0
    assert not salida.exists()
