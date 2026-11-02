"""Cruza lo extraído de las fuentes con los roles de la planilla y decide qué hacer con cada uno.

Estados posibles de una propuesta:
  aplicar           pasa todas las validaciones (o fue aprobada a mano) -> se escribe en la planilla
  sin_cambios       el valor de la fuente coincide con el vigente
  revision          queda pendiente: mapeo en modo revisión, variación fuera de rango o sin valor previo
  fuente_con_error  la fuente no se pudo leer o vino incompleta -> no se toca la planilla
  no_encontrado     el rol no está en la planilla o la categoría no está en la fuente
  sin_fuente        rol de la planilla que ninguna fuente cubre (se mantiene a mano)
"""
from __future__ import annotations

import logging

from .calculo import ErrorCalculo, costo_diario, hora_facturable
from .modelos import FilaRol, Propuesta, Registro, ResultadoFuente
from .normalizar import clave

log = logging.getLogger(__name__)


def _alternativas(categoria) -> list[str]:
    return [categoria] if isinstance(categoria, str) else list(categoria)


def buscar_registro(res: ResultadoFuente, mapeo: dict) -> Registro | None:
    area = clave(mapeo["area_fuente"]) if mapeo.get("area_fuente") else None
    for alternativa in _alternativas(mapeo["categoria"]):
        reg = res.buscar(clave(alternativa), area)
        if reg:
            return reg
    return None


def completitud_por_fuente(resultados: dict[str, ResultadoFuente], mapeo: list[dict]) -> dict[str, float]:
    """Porcentaje de las categorías mapeadas a cada fuente que efectivamente aparecieron."""
    totales: dict[str, list[bool]] = {}
    for m in mapeo:
        res = resultados.get(m["fuente"])
        if res and res.ok:
            totales.setdefault(m["fuente"], []).append(buscar_registro(res, m) is not None)
    return {f: sum(v) / len(v) for f, v in totales.items() if v}


def _base(m: dict, res: ResultadoFuente | None, fila: FilaRol | None) -> Propuesta:
    return Propuesta(
        fila=fila.fila if fila else None, area_plantilla=m["area"], rol=m["rol"],
        valor_actual=fila.valor_actual if fila else None, valor_nuevo=None, estado="",
        fuente_id=m["fuente"], entidad=res.entidad if res else "", documento=res.nombre if res else "",
        url=res.url_usada if res else "", periodo=res.periodo if res else "",
        fecha_extraccion=res.fecha_extraccion if res else None, unidad=m["unidad"], modo=m.get("modo", "auto"),
    )


def conciliar(resultados: list[ResultadoFuente], filas: list[FilaRol], mapeo: list[dict], calc: dict,
              overhead: float, aprobadas: set[str] | None = None,
              areas_excluidas: list[str] | None = None) -> tuple[list[Propuesta], set[tuple[str, int]]]:
    """Devuelve (propuestas, registros_usados). registros_usados = {(fuente_id, id(registro))}."""
    aprobadas = aprobadas or set()
    por_fuente = {r.fuente_id: r for r in resultados}
    validacion = calc.get("validacion", {})
    var_min = validacion.get("variacion_minima", -0.02)
    var_max = validacion.get("variacion_maxima", 0.40)
    completitud_min = validacion.get("completitud_minima", 0.8)
    completitud = completitud_por_fuente(por_fuente, mapeo)

    indice = {(clave(f.area), clave(f.rol)): f for f in filas}
    propuestas: list[Propuesta] = []
    usados: set[tuple[str, int]] = set()
    roles_mapeados = set()

    for m in mapeo:
        fila = indice.get((clave(m["area"]), clave(m["rol"])))
        roles_mapeados.add((clave(m["area"]), clave(m["rol"])))
        res = por_fuente.get(m["fuente"])
        p = _base(m, res, fila)
        if fila is None:
            p.estado, p.motivo = "no_encontrado", (f"El rol '{m['rol']}' del área '{m['area']}' no está en la planilla "
                                                   "(¿se renombró?). Corregir mapeo_roles.json.")
            propuestas.append(p)
            continue
        if res is None:
            p.estado, p.motivo = "fuente_con_error", f"La fuente {m['fuente']} está deshabilitada o no se ejecutó"
            propuestas.append(p)
            continue
        if not res.ok:
            p.estado, p.motivo = "fuente_con_error", f"No se pudo leer la fuente: {res.error}"
            propuestas.append(p)
            continue
        reg = buscar_registro(res, m)
        if reg is None:
            p.estado = "no_encontrado"
            p.motivo = (f"La categoría '{_alternativas(m['categoria'])[0]}' no aparece en la fuente "
                        "(¿cambió el nombre en el documento?)")
            propuestas.append(p)
            continue
        usados.add((res.fuente_id, id(reg)))
        p.area_fuente, p.categoria_fuente, p.moneda = reg.area, reg.categoria, reg.moneda
        p.valor_fuente = reg.valores.get(m["unidad"])
        try:
            p.valor_nuevo, p.detalle_calculo = costo_diario(reg.valores, m["unidad"], calc, float(m.get("factor", 1)))
        except ErrorCalculo as exc:
            p.estado, p.motivo = "no_encontrado", str(exc)
            propuestas.append(p)
            continue
        p.hora_facturable = hora_facturable(p.valor_nuevo, overhead, calc)

        if completitud.get(res.fuente_id, 1) < completitud_min:
            p.estado = "fuente_con_error"
            p.motivo = (f"La fuente vino incompleta ({completitud[res.fuente_id]:.0%} de las categorías mapeadas); "
                        "no se aplica nada de ella")
        elif p.valor_actual is not None and abs(p.valor_nuevo - p.valor_actual) < 0.5:
            p.estado, p.motivo = "sin_cambios", ""
        elif p.valor_actual in (None, 0):
            p.estado, p.motivo = "revision", "La celda no tiene un valor previo para comparar"
        elif not (var_min <= p.variacion <= var_max):
            p.estado = "revision"
            p.motivo = (f"Variación {p.variacion:+.1%} fuera del rango automático "
                        f"({var_min:+.0%} a {var_max:+.0%})")
        elif p.modo == "revision":
            p.estado, p.motivo = "revision", m.get("nota") or "Mapeo marcado para revisión manual"
        else:
            p.estado, p.motivo = "aplicar", m.get("nota", "")
        if p.estado == "revision" and p.clave_aprobacion() in aprobadas:
            p.estado, p.motivo = "aplicar", "Aprobado a mano en la pestaña Fuentes_Tarifas"
        propuestas.append(p)

    excluidas = {clave(a) for a in (areas_excluidas or [])}
    for f in filas:
        if (clave(f.area), clave(f.rol)) in roles_mapeados or clave(f.area) in excluidas:
            continue
        propuestas.append(Propuesta(fila=f.fila, area_plantilla=f.area, rol=f.rol, valor_actual=f.valor_actual,
                                    valor_nuevo=None, estado="sin_fuente",
                                    motivo="Ninguna fuente configurada cubre este rol: se mantiene a mano",
                                    hora_facturable=hora_facturable(f.valor_actual, overhead, calc)))
    return propuestas, usados
