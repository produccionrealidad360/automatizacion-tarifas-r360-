"""Línea de comandos.

    python -m tarifas actualizar                  # producción (Google Sheets, usa variables de entorno)
    python -m tarifas actualizar --simulacion     # calcula todo y no escribe nada
    python -m tarifas actualizar --backend xlsx --xlsx-entrada plantilla.xlsx --xlsx-salida salida/plantilla.xlsx
    python -m tarifas extraer --solo sica_animacion_2d
    python -m tarifas validar-config
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import config, ejecucion


def _logging(directorio: str | None, detallado: bool) -> None:
    manejadores: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if directorio:
        Path(directorio).mkdir(parents=True, exist_ok=True)
        archivo = Path(directorio) / f"tarifas-{datetime.now():%Y%m%d-%H%M%S}.log"
        manejadores.append(logging.FileHandler(archivo, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if detallado else logging.INFO, handlers=manejadores,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for ruidoso in ("urllib3", "pdfminer", "RapidOCR", "rapidocr_onnxruntime"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="tarifas", description="Actualización trazable de tarifas del template R360")
    sub = parser.add_subparsers(dest="comando", required=True)

    act = sub.add_parser("actualizar", help="Extraer, conciliar y publicar en la planilla")
    act.add_argument("--backend", choices=["google", "xlsx"], default="google")
    act.add_argument("--xlsx-entrada", help="Export .xlsx de la planilla (backend xlsx)")
    act.add_argument("--xlsx-salida", default="salida/plantilla_actualizada.xlsx")
    act.add_argument("--simulacion", action="store_true", help="No escribe nada en la planilla")
    act.add_argument("--solo", nargs="*", help="Ids de fuentes a ejecutar")
    act.add_argument("--salida", default="salida", help="Carpeta para resumen.json")
    act.add_argument("--log-dir", default=None)
    act.add_argument("--mostrar-montos", action="store_true",
                     help="Muestra montos en consola (no usar en GitHub Actions: los logs son públicos)")
    act.add_argument("--sin-alertas", action="store_true", help="No crea ni actualiza el issue de alerta")
    act.add_argument("-v", "--detallado", action="store_true")

    ext = sub.add_parser("extraer", help="Solo leer las fuentes y mostrar lo extraído")
    ext.add_argument("--solo", nargs="*")
    ext.add_argument("-v", "--detallado", action="store_true")

    sub.add_parser("validar-config", help="Validar config/*.json")

    args = parser.parse_args(argv)
    if args.comando == "validar-config":
        try:
            cfg = config.cargar()
        except config.ErrorConfiguracion as exc:
            print(f"Configuración inválida:\n{exc}")
            return 2
        print(f"OK: {len(cfg.fuentes)} fuentes, {len(cfg.mapeo)} roles mapeados")
        return 0

    _logging(getattr(args, "log_dir", None), args.detallado)
    if args.comando == "extraer":
        return ejecucion.extraer(args)
    if args.backend == "xlsx" and not args.xlsx_entrada:
        parser.error("--backend xlsx requiere --xlsx-entrada")
    try:
        return ejecucion.actualizar(args)
    except config.ErrorConfiguracion as exc:
        logging.getLogger("tarifas").error("Configuración inválida:\n%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
