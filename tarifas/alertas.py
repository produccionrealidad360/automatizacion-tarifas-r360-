"""Resumen de cada ejecución y alertas.

El repositorio es público: los logs y los issues de GitHub NO llevan montos, solo nombres de
fuentes, roles y estados. Los montos quedan en la planilla (pestaña Fuentes_Tarifas).
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter

import requests

from .modelos import Propuesta, ResultadoFuente

log = logging.getLogger(__name__)
ETIQUETA = "alerta-tarifas"


def resumen(propuestas: list[Propuesta], resultados: list[ResultadoFuente], aplicadas: int, simulacion: bool) -> dict:
    estados = Counter(p.estado for p in propuestas)
    return {
        "simulacion": simulacion,
        "aplicadas": aplicadas,
        "estados": dict(estados),
        "fuentes": [{"id": r.fuente_id, "ok": r.ok, "registros": len(r.registros), "periodo": r.periodo,
                     "error": r.error, "advertencias": len(r.advertencias)} for r in resultados],
        "fuentes_con_error": [r.fuente_id for r in resultados if not r.ok],
        "pendientes": [f"{p.area_plantilla} › {p.rol}: {p.motivo}" for p in propuestas if p.estado == "revision"],
        "no_encontrados": [f"{p.area_plantilla} › {p.rol}: {p.motivo}" for p in propuestas if p.estado == "no_encontrado"],
    }


def requiere_atencion(r: dict) -> bool:
    return bool(r["fuentes_con_error"] or r["pendientes"] or r["no_encontrados"])


def markdown(r: dict, url_ejecucion: str | None = None) -> str:
    lineas = ["## Actualización de tarifas" + (" (simulación)" if r["simulacion"] else ""), ""]
    lineas.append(f"- Costos aplicados: **{r['aplicadas']}**")
    for estado, n in sorted(r["estados"].items()):
        lineas.append(f"- {estado}: {n}")
    lineas += ["", "| Fuente | Estado | Registros | Vigencia |", "|---|---|---|---|"]
    for f in r["fuentes"]:
        lineas.append(f"| {f['id']} | {'OK' if f['ok'] else 'ERROR: ' + (f['error'] or '')[:80]} | "
                      f"{f['registros']} | {f['periodo']} |")
    if r["pendientes"]:
        lineas += ["", "### Pendientes de revisión", "Marcar **Aprobar** en la pestaña `Fuentes_Tarifas` "
                   "y se aplican en la próxima ejecución.", ""]
        lineas += [f"- {x}" for x in r["pendientes"]]
    if r["no_encontrados"]:
        lineas += ["", "### No encontrados (revisar config/mapeo_roles.json)", ""]
        lineas += [f"- {x}" for x in r["no_encontrados"]]
    if url_ejecucion:
        lineas += ["", f"[Ver la ejecución]({url_ejecucion})"]
    return "\n".join(lineas)


def _url_ejecucion() -> str | None:
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return None


def publicar_en_github(r: dict) -> None:
    """Resumen de la ejecución + un único issue abierto con la etiqueta alerta-tarifas (se actualiza, no se duplica)."""
    texto = markdown(r, _url_ejecucion())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(texto + "\n")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo) or r["simulacion"]:
        return
    api = f"https://api.github.com/repos/{repo}/issues"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        abiertos = requests.get(api, headers=h, params={"labels": ETIQUETA, "state": "open"}, timeout=30).json()
        existente = abiertos[0] if isinstance(abiertos, list) and abiertos else None
        if requiere_atencion(r):
            if existente:
                requests.patch(f"{api}/{existente['number']}", headers=h, json={"body": texto}, timeout=30)
            else:
                requests.post(api, headers=h, timeout=30, json={
                    "title": "Tarifas: hay fuentes con error o cambios pendientes de revisión",
                    "body": texto, "labels": [ETIQUETA]})
        elif existente:
            requests.post(f"{api}/{existente['number']}/comments", headers=h, timeout=30,
                          json={"body": "Todo en orden en la última ejecución. Se cierra la alerta."})
            requests.patch(f"{api}/{existente['number']}", headers=h, json={"state": "closed"}, timeout=30)
    except requests.RequestException as exc:
        log.warning("No se pudo actualizar el issue de alerta: %s", exc.__class__.__name__)


def guardar_json(r: dict, ruta) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
