import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarifas.extractores import Contexto  # noqa: E402

ZONA = timezone(timedelta(hours=-3))


@pytest.fixture
def ctx():
    return Contexto(hoy=date(2026, 11, 2), ahora=datetime(2026, 11, 2, 8, 0, tzinfo=ZONA))


@pytest.fixture
def calc():
    return {"horas_jornada": 8, "dias_laborables_mes": 21, "dias_laborables_semana": 5, "cargas_sociales": 0.0,
            "factor_multiplicador": 1.0,
            "validacion": {"variacion_minima": -0.02, "variacion_maxima": 0.40, "completitud_minima": 0.8}}
