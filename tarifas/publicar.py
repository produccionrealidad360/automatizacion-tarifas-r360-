"""Escritura en la planilla con trazabilidad.

- Columna C (costo diario) de cada rol aplicado + una nota de auditoría en la celda (tooltip):
  fuente, URL, período de vigencia, fecha de extracción, cálculo y valor anterior.
- Pestaña Fuentes_Tarifas: una fila por rol y por cada categoría extraída, con todos los metadatos,
  el estado (aplicado, pendiente, etc.) y una casilla "Aprobar" para las pendientes.
"""
from __future__ import annotations

import re

from .calculo import hora_facturable
from .modelos import Propuesta, ResultadoFuente
from .normalizar import formato_ars

ENCABEZADOS = [
    "Fecha extracción", "Estado", "Área plantilla", "Rol plantilla", "Costo diario vigente",
    "Costo diario propuesto", "Variación", "Hora facturable (con overhead)", "Fuente", "Documento", "URL",
    "Período de vigencia", "Área en la fuente", "Categoría en la fuente", "Unidad", "Valor en la fuente",
    "Moneda", "Cálculo", "Motivo / nota", "Aprobar", "Clave",
]

ESTADOS = {
    "aplicar": "Aplicado",
    "sin_cambios": "Sin cambios",
    "revision": "Pendiente de revisión",
    "fuente_con_error": "Fuente con error",
    "no_encontrado": "No encontrado",
    "sin_fuente": "Sin fuente configurada",
    "referencia": "Referencia de mercado",
    "sin_mapear": "Categoría sin mapear",
}
ORDEN = ["revision", "fuente_con_error", "no_encontrado", "aplicar", "sin_cambios", "sin_fuente"]


def _fecha(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M (ART)") if dt else ""


def nota_auditoria(p: Propuesta) -> str:
    return "\n".join([
        f"Actualizado automáticamente: {_fecha(p.fecha_extraccion)}",
        f"Fuente: {p.entidad} · {p.documento}",
        f"URL: {p.url}",
        f"Vigencia: {p.periodo or 'sin dato'}",
        f"Categoría en la fuente: {p.area_fuente} › {p.categoria_fuente}",
        f"Cálculo: {p.detalle_calculo}",
        f"Valor anterior: {formato_ars(p.valor_actual) or 'vacío'}",
        "Detalle completo en la pestaña Fuentes_Tarifas.",
    ])


def fila_propuesta(p: Propuesta, simulacion: bool) -> list:
    estado = ESTADOS.get(p.estado, p.estado)
    if simulacion and p.estado == "aplicar":
        estado = "Se aplicaría (simulación)"
    return [
        _fecha(p.fecha_extraccion), estado, p.area_plantilla, p.rol, p.valor_actual, p.valor_nuevo,
        p.variacion, p.hora_facturable, p.entidad, p.documento, p.url, p.periodo, p.area_fuente,
        p.categoria_fuente, p.unidad, p.valor_fuente, p.moneda if p.valor_fuente is not None else "",
        p.detalle_calculo, p.motivo, False if p.estado == "revision" else "",
        p.clave_aprobacion() if p.estado == "revision" else "",
    ]


def filas_catalogo(resultados: list[ResultadoFuente], usados: set, calc: dict, tipo_cambio: float | None) -> list[list]:
    """Todo lo extraído que no está mapeado: el 'listado por área' de cada fuente y las referencias."""
    filas = []
    for res in resultados:
        if not res.ok:
            filas.append([_fecha(res.fecha_extraccion), ESTADOS["fuente_con_error"], "", "", None, None, None, None,
                          res.entidad, res.nombre, res.url_usada, res.periodo, "", "", "", None, "", "",
                          f"{res.error} | " + " | ".join(res.advertencias[:3]), "", ""])
            continue
        es_referencia = res.tipo == "referencia_mercado"
        for reg in res.registros:
            if (res.fuente_id, id(reg)) in usados:
                continue
            unidad, valor = next(iter(reg.valores.items()))
            calculo = ""
            if reg.moneda == "USD" and tipo_cambio:
                if unidad == "mensual_usd":
                    diario = valor * tipo_cambio / calc.get("dias_laborables_mes", 21)
                    calculo = (f"USD {formato_ars(valor, 0)}/mes × {formato_ars(tipo_cambio)} (dólar oficial) ÷ "
                               f"{calc.get('dias_laborables_mes', 21)} = {formato_ars(diario)} diario (solo referencia)")
                else:
                    calculo = f"USD {formato_ars(valor, 0)} × {formato_ars(tipo_cambio)} = $ {formato_ars(valor * tipo_cambio)} (solo referencia)"
            nota = reg.extra.get("tipo_precio") or ""
            if es_referencia:
                nota = (nota + " · " if nota else "") + "Referencia de mercado: no se aplica a la planilla"
            else:
                nota = "Categoría disponible para mapear en config/mapeo_roles.json"
            filas.append([
                _fecha(res.fecha_extraccion), ESTADOS["referencia" if es_referencia else "sin_mapear"], "", "",
                None, None, None, None, res.entidad, res.nombre, res.url_usada, res.periodo, reg.area,
                reg.categoria, unidad, valor, reg.moneda, calculo, nota, "", "",
            ])
    return filas


def construir_trazabilidad(propuestas: list[Propuesta], resultados: list[ResultadoFuente], usados: set,
                           calc: dict, tipo_cambio: float | None, simulacion: bool) -> list[list]:
    ordenadas = sorted(propuestas, key=lambda p: (ORDEN.index(p.estado) if p.estado in ORDEN else 99,
                                                  p.area_plantilla, p.rol))
    return [fila_propuesta(p, simulacion) for p in ordenadas] + filas_catalogo(resultados, usados, calc, tipo_cambio)


def etiqueta_fuente(res: ResultadoFuente) -> str:
    return f"{res.entidad.split(' (')[0]} · {res.nombre}"


def armar_vigencia(propuestas: list[Propuesta], resultados: list[ResultadoFuente], anterior: str | None) -> str:
    """Una línea por fuente cuyas tarifas están cargadas: 'SICA-APMA · Salarios mínimos Animación 2D: 01/10/2026 a 30/11/2026'.

    Si una fuente falló en esta corrida, se conserva su línea anterior: sus tarifas siguen cargadas.
    """
    previas = {}
    for linea in str(anterior or "").splitlines():
        if ": " in linea:
            clave_linea, valor = linea.split(": ", 1)
            previas[clave_linea.strip()] = valor.strip()
    en_uso = {p.fuente_id for p in propuestas if p.estado in ("aplicar", "sin_cambios")}
    lineas = {}
    for res in resultados:
        nombre = etiqueta_fuente(res)
        if res.ok and res.fuente_id in en_uso:
            lineas[nombre] = res.periodo or "sin dato de vigencia"
        elif not res.ok and nombre in previas:
            lineas[nombre] = previas[nombre]
    return "\n".join(f"{k}: {v}" for k, v in lineas.items())


def bloque_version(fecha_version: str, vigencia: str, ahora: str, maestro: str) -> list[list]:
    return [
        ["Versión de tarifas", "", "Lo completa la actualización automática del Template Maestro. En una copia de "
                                   "presupuesto estos datos quedan fijos y muestran con qué tarifas se armó."],
        ["Fecha de versión de plantilla", fecha_version, "Última vez que la actualización automática cambió alguna tarifa."],
        ["Vigencia de tarifas aplicada", vigencia, "Período de cada escala o tarifario cargado en COSTOS X HORAS FACTURABLES."],
        ["Última verificación automática", ahora, "Última ejecución sobre el Template Maestro. En una copia esta fecha "
                                                  "queda vieja: es normal, las copias no se actualizan."],
        ["ID del Template Maestro", maestro, "Si la URL de este archivo no contiene este ID, es una copia: sus tarifas "
                                             "no cambian solas."],
    ]


def publicar(hoja, propuestas: list[Propuesta], trazabilidad: list[list], plantilla: dict, simulacion: bool,
             resultados: list[ResultadoFuente] | None = None, ahora: str = "", maestro: str = "") -> int:
    """Escribe en la planilla. En simulación no escribe nada. Devuelve la cantidad de costos aplicados."""
    a_aplicar = [p for p in propuestas if p.estado == "aplicar" and p.fila and p.valor_nuevo is not None]
    if simulacion:
        return 0
    hoja.escribir_costos([(p.fila, p.valor_nuevo, nota_auditoria(p)) for p in a_aplicar])
    if a_aplicar and plantilla.get("texto_encabezado"):
        hoja.escribir_texto(f"{plantilla['columna_costo_diario']}{plantilla['fila_encabezado']}",
                            plantilla["texto_encabezado"])
    hoja.escribir_trazabilidad(ENCABEZADOS, trazabilidad)
    if plantilla.get("pestana_parametros") and plantilla.get("bloque_version"):
        pestana = plantilla["pestana_parametros"]
        inicio = plantilla["bloque_version"]["celda_inicio"]
        col, fila = re.match(r"([A-Z]+)(\d+)", inicio).groups()
        col_valor = chr(ord(col) + 1)
        previo = hoja.leer_rango(pestana, f"{col_valor}{int(fila) + 1}:{col_valor}{int(fila) + 2}")
        fecha_previa = previo[0][0] if previo and previo[0] else None
        vigencia_previa = previo[1][0] if len(previo) > 1 and previo[1] else None
        fecha_version = ahora if (a_aplicar or not fecha_previa) else str(fecha_previa)
        vigencia = armar_vigencia(propuestas, resultados or [], vigencia_previa)
        hoja.escribir_rango(pestana, inicio, bloque_version(fecha_version, vigencia, ahora, maestro))
    hoja.guardar()
    return len(a_aplicar)


__all__ = ["ENCABEZADOS", "construir_trazabilidad", "publicar", "nota_auditoria", "hora_facturable"]
