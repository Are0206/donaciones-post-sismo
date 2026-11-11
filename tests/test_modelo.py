"""Fase 1 — Reglas internas de cada entidad: tipos, rangos y fechas."""
from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime
from typing import Any

import pytest

from donaciones.modelo import (
    AporteEconomico, Categoria, CentroAcopio, Donante, ErrorValidacion, EstadoLote, EstadoVia,
    Lote, Municipio, Necesidad, TipoCentro, TipoDonante, Urgencia, Via,
)


# ============================================================
# Constructores: un registro válido, con los cambios que pida cada prueba
# ============================================================

def lote(**cambios: Any) -> Lote:
    base: dict[str, Any] = dict(
        id="LOT-000001", donante_id="DON-0001", centro_id="CA-01", categoria=Categoria.MEDICO,
        descripcion="Kit de trauma", cantidad=10, peso_kg=5.0, volumen_m3=0.02,
        fecha_ingreso=date(2026, 11, 4), fecha_caducidad=date(2027, 5, 1), requiere_frio=False,
    )
    return Lote(**{**base, **cambios})


def centro(**cambios: Any) -> CentroAcopio:
    base: dict[str, Any] = dict(
        id="CA-01", nombre="Aeropuerto Palonegro", tipo=TipoCentro.AEROPUERTO, ciudad="Lebrija",
        latitud=7.1265, longitud=-73.1848, capacidad_m3=4000.0, tiene_frio=True,
    )
    return CentroAcopio(**{**base, **cambios})


def municipio(**cambios: Any) -> Municipio:
    base: dict[str, Any] = dict(
        id="MUN-001", nombre="Los Santos", departamento="Santander", latitud=6.7553,
        longitud=-73.1022, poblacion_afectada=11500, urgencia=Urgencia.CRITICA,
    )
    return Municipio(**{**base, **cambios})


def donante(**cambios: Any) -> Donante:
    base: dict[str, Any] = dict(id="DON-0001", nombre="Ana Gómez", tipo=TipoDonante.PERSONA, pais="Colombia")
    return Donante(**{**base, **cambios})


def necesidad(**cambios: Any) -> Necesidad:
    base: dict[str, Any] = dict(municipio_id="MUN-001", categoria=Categoria.AGUA, cantidad=1000)
    return Necesidad(**{**base, **cambios})


def aporte(**cambios: Any) -> AporteEconomico:
    base: dict[str, Any] = dict(id="APO-00001", donante_id="DON-0001", monto_cop=500_000,
                                fecha=date(2026, 11, 5), municipio_destino_id=None)
    return AporteEconomico(**{**base, **cambios})


def via(**cambios: Any) -> Via:
    base: dict[str, Any] = dict(origen_id="CA-01", destino_id="MUN-001", distancia_km=30.0,
                                tiempo_h=0.7, estado=EstadoVia.TRANSITABLE)
    return Via(**{**base, **cambios})


def _falla_en(fabrica: Any, campo: str, **cambios: Any) -> None:
    """Verifica que construir con esos cambios falle justo en ese campo."""
    with pytest.raises(ErrorValidacion) as error:
        fabrica(**cambios)
    assert error.value.campo == campo


# ============================================================
# Construcción válida e inmutabilidad
# ============================================================

@pytest.mark.parametrize("fabrica", [lote, centro, municipio, donante, necesidad, aporte, via])
def test_los_valores_base_son_validos(fabrica: Any) -> None:
    fabrica()


def test_las_entidades_son_inmutables() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        lote().cantidad = 5  # type: ignore[misc]


def test_replace_crea_una_copia_y_la_vuelve_a_validar() -> None:
    original = lote()
    asignado = dataclasses.replace(original, estado=EstadoLote.ASIGNADO)
    assert asignado.estado is EstadoLote.ASIGNADO
    assert original.estado is EstadoLote.DISPONIBLE        # el original no cambia
    with pytest.raises(ErrorValidacion):
        dataclasses.replace(original, cantidad=-1)          # replace no se salta las reglas


# ============================================================
# Lote: un caso por regla
# ============================================================

@pytest.mark.parametrize(("cambios", "campo"), [
    ({"cantidad": 0}, "cantidad"),
    ({"cantidad": -5}, "cantidad"),
    ({"cantidad": 2.5}, "cantidad"),                 # float donde va entero
    ({"cantidad": True}, "cantidad"),                # bool no es un número
    ({"cantidad": "10"}, "cantidad"),                # texto no es un número
    ({"peso_kg": 0}, "peso_kg"),
    ({"peso_kg": -1.0}, "peso_kg"),
    ({"peso_kg": math.nan}, "peso_kg"),
    ({"peso_kg": math.inf}, "peso_kg"),
    ({"volumen_m3": 0.0}, "volumen_m3"),
    ({"id": "LOT-1"}, "id"),
    ({"id": "lot-000001"}, "id"),
    ({"donante_id": "MUN-001"}, "donante_id"),
    ({"descripcion": ""}, "descripcion"),
    ({"descripcion": "   "}, "descripcion"),
    ({"descripcion": "x" * 121}, "descripcion"),
    ({"categoria": "MEDICO"}, "categoria"),          # texto en vez del Enum
    ({"estado": "DISPONIBLE"}, "estado"),
    ({"fecha_ingreso": "2026-11-04"}, "fecha_ingreso"),
    ({"fecha_ingreso": datetime(2026, 11, 4, 8, 0)}, "fecha_ingreso"),
    ({"requiere_frio": "SI"}, "requiere_frio"),
    ({"fecha_caducidad": date(2026, 11, 4)}, "fecha_caducidad"),   # igual al ingreso
    ({"fecha_caducidad": date(2026, 11, 1)}, "fecha_caducidad"),   # antes del ingreso
    ({"fecha_caducidad": None}, "fecha_caducidad"),                # MEDICO es perecedero
])
def test_lote_invalido(cambios: dict[str, Any], campo: str) -> None:
    _falla_en(lote, campo, **cambios)


def test_categoria_no_perecedera_puede_no_tener_caducidad() -> None:
    sin_caducidad = lote(categoria=Categoria.REFUGIO, fecha_caducidad=None)
    assert sin_caducidad.dias_para_vencer(date(2026, 11, 10)) is None


def test_un_lote_con_frio_debe_tener_caducidad_aunque_su_categoria_no_la_exija() -> None:
    _falla_en(lote, "fecha_caducidad", categoria=Categoria.REFUGIO,
              fecha_caducidad=None, requiere_frio=True)


def test_dias_para_vencer() -> None:
    proximo = lote(fecha_caducidad=date(2026, 11, 20))
    assert proximo.dias_para_vencer(date(2026, 11, 10)) == 10
    assert proximo.dias_para_vencer(date(2026, 11, 25)) == -5


def test_unidad_depende_de_la_categoria() -> None:
    assert lote(categoria=Categoria.AGUA).unidad == "litro"
    assert lote(categoria=Categoria.VIVERES).unidad == "kg"


# ============================================================
# Otras entidades
# ============================================================

@pytest.mark.parametrize(("cambios", "campo"), [
    ({"latitud": 40.4}, "latitud"),               # Madrid: fuera de Colombia
    ({"longitud": 73.18}, "longitud"),            # signo equivocado
    ({"latitud": math.nan}, "latitud"),
    ({"capacidad_m3": 0}, "capacidad_m3"),
    ({"tiene_frio": 1}, "tiene_frio"),
    ({"id": "CA-1"}, "id"),
])
def test_centro_invalido(cambios: dict[str, Any], campo: str) -> None:
    _falla_en(centro, campo, **cambios)


@pytest.mark.parametrize(("cambios", "campo"), [
    ({"poblacion_afectada": -1}, "poblacion_afectada"),
    ({"urgencia": 1}, "urgencia"),                # int en vez de Urgencia
    ({"nombre": ""}, "nombre"),
])
def test_municipio_invalido(cambios: dict[str, Any], campo: str) -> None:
    _falla_en(municipio, campo, **cambios)


def test_poblacion_afectada_puede_ser_cero() -> None:
    municipio(poblacion_afectada=0)


def test_menor_numero_de_urgencia_es_mas_urgente() -> None:
    assert Urgencia.CRITICA < Urgencia.ALTA < Urgencia.MEDIA < Urgencia.BAJA
    assert min([Urgencia.BAJA, Urgencia.CRITICA, Urgencia.MEDIA]) is Urgencia.CRITICA


def test_necesidad_usa_llave_compuesta() -> None:
    n = necesidad(municipio_id="MUN-002", categoria=Categoria.REFUGIO)
    assert n.clave == ("MUN-002", Categoria.REFUGIO)
    _falla_en(necesidad, "cantidad", cantidad=0)


@pytest.mark.parametrize(("cambios", "campo"), [
    ({"monto_cop": 0}, "monto_cop"),
    ({"monto_cop": 1500.5}, "monto_cop"),         # el dinero va en entero
    ({"municipio_destino_id": "Zapatoca"}, "municipio_destino_id"),
    ({"donante_id": "DON-1"}, "donante_id"),
])
def test_aporte_invalido(cambios: dict[str, Any], campo: str) -> None:
    _falla_en(aporte, campo, **cambios)


@pytest.mark.parametrize(("cambios", "campo"), [
    ({"destino_id": "CA-01"}, "destino_id"),      # consigo mismo
    ({"origen_id": "DON-0001"}, "origen_id"),     # un donante no es un nodo vial
    ({"distancia_km": 0}, "distancia_km"),
    ({"tiempo_h": -2.0}, "tiempo_h"),
])
def test_via_invalida(cambios: dict[str, Any], campo: str) -> None:
    _falla_en(via, campo, **cambios)


def test_la_clave_de_una_via_no_depende_del_sentido() -> None:
    assert via(origen_id="CA-01", destino_id="MUN-001").clave == \
        via(origen_id="MUN-001", destino_id="CA-01").clave
