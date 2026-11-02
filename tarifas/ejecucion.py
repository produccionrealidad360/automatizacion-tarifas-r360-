"""Orquestación de una corrida completa."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import alertas, config, publicar
from .conciliacion import conciliar
from .extractores import Contexto, ejecutar_todas
from .http import ClienteHttp
from .normalizar import formato_ars

log = logging.getLogger(__name__)


def tipo_cambio(cliente: ClienteHttp, calc: dict) -> float | None:
    conf = calc.get("tipo_cambio") or {}
    if not conf.get("url"):
        return None
    try:
        return float(cliente.get(conf["url"]).json()[conf.get("campo", "venta")])
    except Exception as exc:  # noqa: BLE001 - solo afecta a la columna informativa de referencias
        log.warning("No se pudo obtener el tipo de cambio (%s); las referencias en USD quedan sin equivalente", exc.__class__.__name__)
        return None


def abrir_hoja(opciones, cfg: config.Configuracion):
    if opciones.backend == "xlsx":
        from .hojas.xlsx import HojaXlsx

        return HojaXlsx(cfg.plantilla, opciones.xlsx_entrada, opciones.xlsx_salida)
    from .hojas.google import HojaGoogle, credenciales_desde_entorno

    sheet_id = os.environ.get("TARIFAS_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("Falta la variable TARIFAS_SHEET_ID con el ID de la planilla")
    credenciales = credenciales_desde_entorno()
    try:
        return HojaGoogle(cfg.plantilla, sheet_id, credenciales)
    except Exception as exc:
        raise RuntimeError(explicar_error_planilla(exc, credenciales.get("client_email", ""))) from exc


def explicar_error_planilla(exc: Exception, email: str) -> str:
    """Traduce el error de Google a la acción concreta. No incluye montos ni el ID de la planilla."""
    import gspread

    causa = exc.__cause__ or exc
    detalle = ""
    respuesta = getattr(causa, "response", None)
    if respuesta is not None:
        detalle = getattr(respuesta, "text", "") or ""
    cuenta = email.split("@")[0] + "@…iam.gserviceaccount.com" if email else "la cuenta de servicio"
    if "SERVICE_DISABLED" in detalle or "has not been used" in detalle or "is disabled" in detalle:
        return ("La API de Google Sheets no está habilitada en el proyecto de Google Cloud de la cuenta de servicio: "
                "console.cloud.google.com > APIs y servicios > Biblioteca > Google Sheets API > Habilitar")
    if isinstance(exc, gspread.exceptions.SpreadsheetNotFound):
        return (f"No existe una planilla con ese TARIFAS_SHEET_ID visible para {cuenta}: revisar que el ID "
                "sea la parte de la URL entre /d/ y /edit, y que la planilla esté compartida con esa cuenta")
    if isinstance(exc, PermissionError) or "PERMISSION_DENIED" in detalle:
        return (f"{cuenta} no tiene acceso a la planilla: abrirla, Compartir, y agregar el e-mail completo de la "
                "cuenta de servicio (client_email del JSON) como Editor")
    return f"{exc.__class__.__name__}: {exc}"


def actualizar(opciones) -> int:
    cfg = config.cargar()
    ctx = Contexto.actual()
    cliente = ClienteHttp()
    resultados = ejecutar_todas(cfg.fuentes, cliente, ctx, set(opciones.solo) if opciones.solo else None)
    if not any(r.ok for r in resultados):
        log.error("Ninguna fuente devolvió datos: no se toca la planilla")

    try:
        hoja = abrir_hoja(opciones, cfg)
        filas = hoja.leer_roles()
        overhead = hoja.leer_overhead(cfg.calculo["overhead"]["rango_con_nombre"])
        aprobadas = hoja.leer_aprobaciones()
    except Exception as exc:  # noqa: BLE001 - error fatal: sin planilla no hay nada que hacer
        log.error("No se pudo abrir la planilla: %s: %s", exc.__class__.__name__, exc)
        return 2
    if overhead is None:
        overhead = float(cfg.calculo["overhead"].get("valor_si_no_existe", 0))
        log.warning("No se encontró el rango %s; se usa overhead = %s", cfg.calculo["overhead"]["rango_con_nombre"], overhead)
    log.info("Planilla: %d roles leídos, overhead %.0f%%, %d aprobaciones manuales", len(filas), overhead * 100, len(aprobadas))

    propuestas, usados = conciliar(resultados, filas, cfg.mapeo, cfg.calculo, overhead, aprobadas,
                                   cfg.plantilla.get("areas_sin_tarifa_salarial"))
    tc = tipo_cambio(cliente, cfg.calculo)
    traza = publicar.construir_trazabilidad(propuestas, resultados, usados, cfg.calculo, tc, opciones.simulacion)
    aplicadas = 0
    if any(r.ok for r in resultados):
        maestro = os.environ.get("TARIFAS_SHEET_ID", "").strip() if opciones.backend == "google" else "(archivo local de prueba)"
        aplicadas = publicar.publicar(hoja, propuestas, traza, cfg.plantilla, opciones.simulacion, resultados,
                                      ctx.ahora.strftime("%d/%m/%Y %H:%M (ART)"), maestro)

    res = alertas.resumen(propuestas, resultados, aplicadas, opciones.simulacion)
    log.info("Resultado: %s", ", ".join(f"{k}={v}" for k, v in sorted(res["estados"].items())))
    if opciones.mostrar_montos:
        for p in propuestas:
            if p.estado in ("aplicar", "revision"):
                log.info("  %-24s %-34s %14s -> %14s  %s", p.estado, p.rol[:34], formato_ars(p.valor_actual),
                         formato_ars(p.valor_nuevo), f"{p.variacion:+.1%}" if p.variacion is not None else "")
    if opciones.salida:
        alertas.guardar_json(res, Path(opciones.salida) / "resumen.json")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not opciones.sin_alertas:
        alertas.publicar_en_github(res)
    return 0 if any(r.ok for r in resultados) else 1


def extraer(opciones) -> int:
    """Solo extrae y muestra lo leído de cada fuente (para depurar un extractor)."""
    cfg = config.cargar()
    resultados = ejecutar_todas(cfg.fuentes, ClienteHttp(), Contexto.actual(), set(opciones.solo) if opciones.solo else None)
    for r in resultados:
        print(f"\n[{r.fuente_id}] ok={r.ok} registros={len(r.registros)} vigencia='{r.periodo}'")
        print(f"  url: {r.url_usada}")
        if r.error:
            print(f"  error: {r.error}")
        for adv in r.advertencias:
            print(f"  aviso: {adv}")
        for reg in r.registros:
            print(f"  - [{reg.area}] {reg.categoria}: " + ", ".join(f"{k}={formato_ars(v)}" for k, v in reg.valores.items()))
    return 0 if all(r.ok for r in resultados) else 1
