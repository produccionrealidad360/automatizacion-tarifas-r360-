from tarifas.calculo import costo_diario, hora_facturable
from tarifas.conciliacion import conciliar
from tarifas.http import decodificar
from tarifas.modelos import FilaRol, Registro, ResultadoFuente
from tarifas.normalizar import monto


def test_montos_en_todos_los_formatos():
    assert monto("$ 3.727.974") == 3727974
    assert monto("$1,303,128.64") == 1303128.64
    assert monto("$ 2.324.329,63") == 2324329.63
    assert monto("1,200") == 1200 and monto("3.700") == 3700
    assert monto("$1.,069,289.72") is None


def test_formula_configurable(calc):
    assert costo_diario({"diario": 279598}, "diario", calc)[0] == 279598
    assert costo_diario({"mensual": 2100000}, "mensual", calc)[0] == 100000
    assert costo_diario({"hora": 10000}, "hora", calc)[0] == 80000
    assert costo_diario({"semanal": 500000}, "semanal", calc)[0] == 100000
    assert costo_diario({"diario": 100000}, "diario", calc, factor_rol=1.4)[0] == 140000
    con_cargas = dict(calc, cargas_sociales=0.25, factor_multiplicador=1.1)
    valor, detalle = costo_diario({"diario": 100000}, "diario", con_cargas)
    assert valor == 137500 and "cargas sociales" in detalle
    assert hora_facturable(80000, 0.35, calc) == 13500


def test_decodifica_utf8_con_un_byte_suelto_sin_romper_los_acentos():
    contenido = "Junior (0–2 años): USD 1,200".encode("utf-8") + b"\xff" + " más texto".encode("utf-8") * 50
    texto = decodificar(contenido)
    assert "0–2 años" in texto
    assert decodificar("Remuneración".encode("cp1252")) == "Remuneración"


def _res(fid, registros, ok=True):
    from datetime import datetime

    return ResultadoFuente(fuente_id=fid, entidad="Ent", nombre="Doc", url_usada="https://x", ok=ok,
                           fecha_extraccion=datetime(2026, 11, 2), periodo="01/10/2026 a 30/11/2026",
                           registros=registros, error=None if ok else "caída")


def test_estados_de_la_conciliacion(calc):
    regs = [Registro("PRODUCCIÓN", "Coordinador/a de Produccion", {"diario": 104500}),
            Registro("DIRECCIÓN", "Director/a de Arte", {"diario": 100000}),
            Registro("ANIMACIÓN 2D", "Layout", {"diario": 200000}),
            Registro("ANIMACIÓN 2D", "Fondista", {"diario": 104500})]
    filas = [FilaRol(23, "Producción", "Coordinadora de producción", 100000),
             FilaRol(24, "Animación 2D", "Director/a de arte 2D", 100000),
             FilaRol(25, "Animación 2D", "2D Layout", 100000),
             FilaRol(26, "Animación 2D", "Fondista", 100000),
             FilaRol(27, "Rodaje", "Filmmaker", 300000),
             FilaRol(28, "Equipamiento", "TV", 150000)]
    mapeo = [
        {"area": "Producción", "rol": "Coordinadora de producción", "fuente": "s", "categoria": "Coordinador/a de Producción", "unidad": "diario"},
        {"area": "Animación 2D", "rol": "Director/a de arte 2D", "fuente": "s", "categoria": "Director/a de Arte", "unidad": "diario"},
        {"area": "Animación 2D", "rol": "2D Layout", "fuente": "s", "categoria": "Layout", "unidad": "diario"},
        {"area": "Animación 2D", "rol": "Fondista", "fuente": "s", "categoria": "Fondista", "unidad": "diario", "modo": "revision"},
        {"area": "Animación 2D", "rol": "Rol que no existe", "fuente": "s", "categoria": "Fondista", "unidad": "diario"},
    ]
    props, _ = conciliar([_res("s", regs)], filas, mapeo, calc, overhead=0.35, areas_excluidas=["Equipamiento"])
    estado = {p.rol: p.estado for p in props}
    assert estado["Coordinadora de producción"] == "aplicar"  # +4,5%
    assert estado["Director/a de arte 2D"] == "sin_cambios"
    assert estado["2D Layout"] == "revision"  # +100%: fuera de rango
    assert estado["Fondista"] == "revision"  # modo revisión
    assert estado["Rol que no existe"] == "no_encontrado"
    assert estado["Filmmaker"] == "sin_fuente" and "TV" not in estado
    coord = next(p for p in props if p.rol == "Coordinadora de producción")
    assert coord.hora_facturable == round(104500 * 1.35 / 8, 2)

    # Aprobación manual desde Fuentes_Tarifas
    fondista = next(p for p in props if p.rol == "Fondista")
    props2, _ = conciliar([_res("s", regs)], filas, mapeo, calc, 0.35, aprobadas={fondista.clave_aprobacion()})
    assert next(p for p in props2 if p.rol == "Fondista").estado == "aplicar"


def test_fuente_caida_o_incompleta_no_toca_la_planilla(calc):
    filas = [FilaRol(23, "Producción", "Coordinadora de producción", 100000), FilaRol(24, "Producción", "Asist", 50000)]
    mapeo = [{"area": "Producción", "rol": "Coordinadora de producción", "fuente": "s", "categoria": "Coord", "unidad": "diario"},
             {"area": "Producción", "rol": "Asist", "fuente": "s", "categoria": "Asistente", "unidad": "diario"}]
    props, _ = conciliar([_res("s", [], ok=False)], filas, mapeo, calc, 0)
    assert {p.estado for p in props} == {"fuente_con_error"}
    # Vino solo 1 de 2 categorías (50% < 80%): no se aplica nada de esa fuente
    props, _ = conciliar([_res("s", [Registro("A", "Coord", {"diario": 104000})])], filas, mapeo, calc, 0)
    assert {p.rol: p.estado for p in props} == {"Coordinadora de producción": "fuente_con_error", "Asist": "no_encontrado"}
