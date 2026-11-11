"""Datos compartidos por todas las pruebas."""
from __future__ import annotations

from pathlib import Path

import pytest

from donaciones.generador import generar
from donaciones.modelo import FECHA_EVENTO
from donaciones.persistencia import Datos, guardar_csv


@pytest.fixture
def datos_pequenos() -> Datos:
    """Un conjunto pequeño pero completo, válido por construcción."""
    return generar(semilla=7, evento=FECHA_EVENTO, n_donantes=10, n_lotes=40, n_aportes=8)


@pytest.fixture
def carpeta(tmp_path: Path, datos_pequenos: Datos) -> Path:
    """Carpeta temporal con los siete CSV válidos. Cada prueba recibe la suya."""
    guardar_csv(tmp_path, datos_pequenos)
    return tmp_path
