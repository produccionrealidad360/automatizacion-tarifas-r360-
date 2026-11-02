"""Extractores con muestras sintéticas que imitan el formato de cada fuente (sin red)."""
from datetime import date

from tarifas import config
from tarifas.extractores import coderhouse_html, cpci_html, sica_pdf, sup_pdf_ocr, tarifario_js
from tarifas.extractores.sup_pdf_ocr import Caja
from tarifas.normalizar import clave

TEXTO_SICA = """SALARIOS MÍNIMOS ANIMACIÓN 2D
VIGENTES DESDE 01/10/2026 HASTA 30/11/2026
ASIGNACION CARGO
PRODUCCIÓN Coordinador/a de Produccion $ 3.000.000 $ 750.000 $ 225.000
Asistente de Produccion $ 2.000.000 $ 500.000 $ 150.000
DIRECCIÓN Director/a de Arte $ 3.000.000 $ 750.000 $ 225.000
ANIMACIÓN 2D Arte Conceptual $ 2.600.000 $ 650.000 $ 195.000
Animador/a Cutout $ 1.600.000 $ 400.000 $ 120.000
Clean up / Color $ 1.200.000 $ 300.000 $ 90.000
Storyboard $ 2.800.000 $ 700.000 $ 210.000
Layout $ 2.600.000 $ 650.000 $ 195.000
EDICIÓN Y POSTPRODUCCIÓN Director/a de Postproduccion $ 3.000.000 $ 750.000 $ 225.000
SONIDO Operador/a $ 1.600.000 $ 400.000 $ 999.999
ESTOS SALARIOS SON BÁSICOS"""


def test_sica_lee_areas_vigencia_y_descarta_filas_incoherentes():
    regs, meta, avisos = sica_pdf.parsear_texto(TEXTO_SICA, config.cargar().fuente("sica_animacion_2d")["patron_vigencia"])
    assert meta["desde"] == date(2026, 10, 1) and meta["hasta"] == date(2026, 11, 30)
    por_cat = {r.categoria: r for r in regs}
    assert por_cat["Asistente de Produccion"].area == "PRODUCCIÓN"  # hereda el área del renglón anterior
    assert por_cat["Arte Conceptual"].area == "ANIMACIÓN 2D"
    assert por_cat["Director/a de Postproduccion"].area == "EDICIÓN Y POSTPRODUCCIÓN"
    assert por_cat["Clean up / Color"].valores == {"mensual": 1_200_000, "semanal": 300_000, "diario": 90_000}
    # El diario de "Operador/a" no guarda la proporción del resto: se descarta con aviso
    assert "Operador/a" not in por_cat
    assert any("Operador/a" in a for a in avisos)


def _fila(y, etiqueta, montos, x0=100):
    cajas = [Caja(x=x0, y=y, texto=etiqueta)]
    cajas += [Caja(x=400 + i * 100, y=y + 1, texto=m) for i, m in enumerate(montos)]
    return cajas


def test_sup_detecta_tramos_y_valida_la_cadena_de_aumentos():
    encabezado = [Caja(400, 10, "DICIEMBRE"), Caja(500, 10, "FEBRERO"), Caja(400, 30, "2025"), Caja(500, 30, "2026"),
                  Caja(400, 50, "4 %"), Caja(500, 50, "8 %")]
    tramos = sup_pdf_ocr.detectar_tramos(encabezado)
    assert tramos == [{"desde": date(2025, 12, 1), "porcentaje": 4.0}, {"desde": date(2026, 2, 1), "porcentaje": 8.0}]
    cajas = (_fila(100, "ÁREA CREATIVA", []) + _fila(130, "DIRECTOR CREATIVO", ["$1,000,000.00", "$1,080,000.00"])
             + _fila(160, "REDACTOR", ["$500,000.00", "$590,000.00"])  # no es +8%: OCR leyó mal
             + _fila(190, "PASADOR", ["$1.,000.00", "$1,080.00"]))  # monto ilegible
    validas, invalidas = sup_pdf_ocr.parsear_renglones(sup_pdf_ocr.agrupar_renglones(cajas), tramos, 2.0)
    assert validas == [("ÁREA CREATIVA", "DIRECTOR CREATIVO", [1_000_000.0, 1_080_000.0])]
    assert {e for _, e, _ in invalidas} == {"REDACTOR", "PASADOR $1.,000.00"}


def test_sup_elige_el_tramo_vigente():
    tramos = [{"desde": date(2025, 12, 1)}, {"desde": date(2026, 2, 1)}, {"desde": date(2026, 7, 1)}, {"desde": date(2026, 11, 1)}]
    assert sup_pdf_ocr.tramo_vigente(tramos, date(2026, 10, 31)) == 2
    assert sup_pdf_ocr.tramo_vigente(tramos, date(2026, 11, 2)) == 3
    assert sup_pdf_ocr.tramo_vigente(tramos, date(2025, 1, 1)) == 0


HTML_CPCI = """<p>Actualización al: 09-2026</p><table>
<tr><th>Agrupamiento</th><th>Perfil</th><th>$ Mensual</th><th>$ Hora</th><th>Unid.</th></tr>
<tr><td>Desarrollador de Aplicaciones</td><td>Programador Aplicaciones Junior</td><td>$ 1.896.448,98</td><td>$ 52.373,39</td><td>IPIM CPCE</td></tr>
<tr><td>Consultoría</td><td>Consultor Informático</td><td>$ 0,00</td><td>$ 112.154,51</td><td>IPIM CPCE</td></tr>
</table>"""


def test_cpci_tabla_y_fecha():
    regs, desde = cpci_html.parsear_html(HTML_CPCI)
    assert desde == date(2026, 9, 1)
    assert regs[0].valores == {"mensual": 1896448.98, "hora": 52373.39}
    assert regs[1].valores == {"hora": 112154.51}  # mensual en 0 = no informado


def test_coderhouse_rangos_y_medianas_con_los_patrones_de_sources():
    cfg = config.cargar()
    local = cfg.fuente("coderhouse_ai_automation_2025")["opciones"]["niveles"]
    texto = ("Junior (0–2 años): USD 1,200–1,600 mensuales Semi Senior (2–5 años): USD 1,900–2,800 "
             "Senior (5+ años): USD 3,100–4,300 (más variable/bonos)")
    regs, faltantes = coderhouse_html.parsear(texto, local)
    assert not faltantes
    assert {r.categoria: r.valores["mensual_usd"] for r in regs} == {"Junior": 1400, "Semi Senior": 2350, "Senior": 3700}
    remoto = cfg.fuente("coderhouse_ai_automation_ar")["opciones"]["niveles"]
    texto = ("Junior (aprox. 1–2 años): mediana orientativa ~USD 3.700/mes Mid (aprox. 2–4 años): mediana "
             "orientativa ~USD 4.550/mes Senior (aprox. 4+ años): mediana orientativa ~USD 8.400/mes")
    regs, faltantes = coderhouse_html.parsear(texto, remoto)
    assert {r.categoria: r.valores["mensual_usd"] for r in regs} == {"Junior": 3700, "Semi Senior": 4550, "Senior": 8400}


def test_tarifario_objetos_js():
    js = ('x=[{id:"3d-1",category:"servicios-3d",title:"Modelado 3D de Producto",description:"Creación.",'
          'priceUSD:200,priceType:"minimum"},{id:"web-1",category:"desarrollo-web",title:"Landing",priceUSD:300}]')
    regs = tarifario_js.parsear_js(js, "servicios-3d")
    assert len(regs) == 1 and regs[0].categoria == "Modelado 3D de Producto"
    assert regs[0].valores == {"precio_usd": 200.0} and regs[0].extra["tipo_precio"] == "minimum"


def test_claves_de_comparacion_toleran_ocr_y_acentos():
    assert clave("ÁREA DE PRODUCCIÓN GRÁFICA") == clave("AREADEPRODUCCIONGRAFICA")
    assert clave("Técnico/a Rigging & Settings") == clave("Tecnico/a Rigging & Settings")
