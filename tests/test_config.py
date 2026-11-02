import json

import pytest

from tarifas import config


def test_la_configuracion_del_repo_es_valida():
    cfg = config.cargar()
    assert cfg.fuente("sica_animacion_2d")["extractor"] == "sica_pdf"
    assert all(m["fuente"] in {f["id"] for f in cfg.fuentes} for m in cfg.mapeo)


def test_detecta_errores_de_configuracion(tmp_path):
    for nombre in ("sources.json", "mapeo_roles.json", "calculo.json", "plantilla.json"):
        (tmp_path / nombre).write_text((config.DIR_CONFIG / nombre).read_text(encoding="utf-8"), encoding="utf-8")
    mapeo = json.loads((tmp_path / "mapeo_roles.json").read_text(encoding="utf-8"))
    mapeo["roles"][0]["fuente"] = "fuente_inexistente"
    mapeo["roles"][1]["unidad"] = "anual"
    (tmp_path / "mapeo_roles.json").write_text(json.dumps(mapeo), encoding="utf-8")
    with pytest.raises(config.ErrorConfiguracion) as exc:
        config.cargar(tmp_path)
    assert "fuente_inexistente" in str(exc.value) and "anual" in str(exc.value)
