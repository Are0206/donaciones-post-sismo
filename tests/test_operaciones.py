"""Fase 2 — Lógica de negocio y consistencia del inventario."""
from __future__ import annotations

import dataclasses
import sys
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from donaciones.estructuras import Criterio
from donaciones.generador import CENTROS, generar
from donaciones.modelo import (
    FECHA_EVENTO, Categoria, Donante, ErrorValidacion, EstadoLote, EstadoVia, Lote, Municipio,
    Necesidad, TipoDonante, Urgencia, Via,
)
from donaciones.operaciones import ErrorOperacion, SistemaDonaciones
from donaciones.persistencia import Datos, cargar_csv

HOY = date(2026, 11, 10)
AGUA = Categoria.AGUA


# ============================================================
# Escenario pequeño, hecho a mano para saber el resultado exacto:
#   - Dos municipios con la misma necesidad de agua (1000 litros):
#     MUN-001 CRITICA y MUN-002 BAJA (puesto primero en la lista a propósito).
#   - Tres lotes de 600 litros (1800 en total, no alcanza para los dos),
#     con caducidades distintas para probar el orden FEFO.
# ============================================================

def _lote(numero: int, caducidad: date | None, **cambios: Any) -> Lote:
    base: dict[str, Any] = dict(
        id=f"LOT-{numero:06d}", donante_id="DON-0001", centro_id="CA-01", categoria=AGUA,
        descripcion="Agua potable", cantidad=600, peso_kg=630.0, volumen_m3=0.66,
        fecha_ingreso=date(2026, 11, 4), fecha_caducidad=caducidad, requiere_frio=False,
    )
    return Lote(**{**base, **cambios})


def _escenario() -> Datos:
    return Datos(
        centros=[CENTROS[0], CENTROS[5]],          # CA-01 con frío, CA-06 sin frío
        municipios=[
            Municipio("MUN-002", "Girón", "Santander", 7.0682, -73.1698, 5000, Urgencia.BAJA),
            Municipio("MUN-001", "Los Santos", "Santander", 6.7553, -73.1022, 1000, Urgencia.CRITICA),
        ],
        donantes=[Donante("DON-0001", "Ana Gómez", TipoDonante.PERSONA, "Colombia")],
        necesidades=[Necesidad("MUN-002", AGUA, 1000), Necesidad("MUN-001", AGUA, 1000)],
        lotes=[
            _lote(1, date(2027, 6, 1)),
            _lote(2, date(2026, 12, 1)),           # el que vence primero
            _lote(3, date(2027, 3, 1)),
        ],
    )


@pytest.fixture
def sistema() -> SistemaDonaciones:
    return SistemaDonaciones(_escenario())


def _registrar(s: SistemaDonaciones, **cambios: Any) -> Lote:
    datos: dict[str, Any] = dict(
        donante_id="DON-0001", centro_id="CA-01", categoria=AGUA, descripcion="Agua potable",
        cantidad=100, peso_kg=105.0, volumen_m3=0.11, fecha_ingreso=HOY,
        fecha_caducidad=date(2027, 1, 1), requiere_frio=False,
    )
    return s.registrar_lote(**{**datos, **cambios})


def _total_por_categoria(s: SistemaDonaciones) -> dict[Categoria, int]:
    """Suma de TODOS los lotes de cada categoría, en cualquier estado."""
    return {f.categoria: f.disponible + f.asignado + f.despachado + f.descartado for f in s.balance()}


# ============================================================
# 1. Registro
# ============================================================

def test_registrar_lote_queda_disponible_con_id_consecutivo(sistema: SistemaDonaciones) -> None:
    lote = _registrar(sistema)
    assert lote.id == "LOT-000004"
    assert lote.estado is EstadoLote.DISPONIBLE
    assert sistema.lote("LOT-000004") == lote


@pytest.mark.parametrize(("cambios", "campo"), [
    ({"donante_id": "DON-9999"}, "donante_id"),                 # donante inexistente
    ({"centro_id": "CA-07"}, "centro_id"),                      # centro inexistente
    ({"cantidad": -10}, "cantidad"),
    ({"fecha_ingreso": date(2026, 11, 1)}, "fecha_ingreso"),    # antes del sismo
    ({"centro_id": "CA-06", "requiere_frio": True}, "centro_id"),   # frío en centro sin frío
])
def test_registro_invalido_no_deja_rastro(sistema: SistemaDonaciones,
                                          cambios: dict[str, Any], campo: str) -> None:
    antes = len(sistema.datos.lotes)
    with pytest.raises(ErrorValidacion) as error:
        _registrar(sistema, **cambios)
    assert error.value.campo == campo
    assert len(sistema.datos.lotes) == antes
    assert _registrar(sistema).id == "LOT-000004"               # el id fallido no se gastó


def test_registrar_aporte(sistema: SistemaDonaciones) -> None:
    aporte = sistema.registrar_aporte(donante_id="DON-0001", monto_cop=2_000_000, fecha=HOY,
                                      municipio_destino_id="MUN-001")
    assert aporte.id == "APO-00001" and aporte in sistema.datos.aportes
    with pytest.raises(ErrorValidacion):
        sistema.registrar_aporte(donante_id="DON-0001", monto_cop=1, fecha=HOY,
                                 municipio_destino_id="MUN-999")


# ============================================================
# 2. Búsqueda
# ============================================================

def test_buscar_por_identificador(sistema: SistemaDonaciones) -> None:
    lote = sistema.lote("LOT-000002")
    assert lote is not None and lote.fecha_caducidad == date(2026, 12, 1)
    assert sistema.lote("LOT-999999") is None


def test_buscar_por_categoria(sistema: SistemaDonaciones) -> None:
    _registrar(sistema, categoria=Categoria.REFUGIO, descripcion="Carpa", fecha_caducidad=None)
    refugio = sistema.buscar_lotes(categoria=Categoria.REFUGIO)
    assert [l.categoria for l in refugio] == [Categoria.REFUGIO]
    assert len(sistema.buscar_lotes(categoria=AGUA)) == 3


def test_busqueda_ordenada_por_caducidad_y_sin_caducidad_al_final(sistema: SistemaDonaciones) -> None:
    _registrar(sistema, categoria=Categoria.REFUGIO, descripcion="Carpa", fecha_caducidad=None)
    ids = [l.id for l in sistema.buscar_lotes()]
    assert ids == ["LOT-000002", "LOT-000003", "LOT-000001", "LOT-000004"]


def test_filtros_combinados(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000003", "MUN-001", HOY)
    disponibles = sistema.buscar_lotes(categoria=AGUA, estado=EstadoLote.DISPONIBLE, centro_id="CA-01")
    assert [l.id for l in disponibles] == ["LOT-000002", "LOT-000001"]
    assert sistema.buscar_lotes(categoria=AGUA, centro_id="CA-06") == []


def test_proximos_a_vencer(sistema: SistemaDonaciones) -> None:
    assert [l.id for l in sistema.proximos_a_vencer(HOY, 30)] == ["LOT-000002"]
    assert [l.id for l in sistema.proximos_a_vencer(HOY, 150)] == ["LOT-000002", "LOT-000003"]
    sistema.asignar("LOT-000002", "MUN-001", HOY)
    assert sistema.proximos_a_vencer(HOY, 30) == []                  # ya no está disponible


# ============================================================
# 3 y 4. Estados: asignar, despachar, descartar
# ============================================================

def test_una_donacion_asignada_no_queda_disponible(sistema: SistemaDonaciones) -> None:
    lote = sistema.asignar("LOT-000001", "MUN-001", HOY)
    assert lote.estado is EstadoLote.ASIGNADO and lote.municipio_destino_id == "MUN-001"
    assert lote not in sistema.buscar_lotes(estado=EstadoLote.DISPONIBLE)
    assert all(l.id != "LOT-000001" for l in sistema.buscar_lotes(estado=EstadoLote.DISPONIBLE))


def test_no_se_puede_asignar_dos_veces(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000001", "MUN-001", HOY)
    with pytest.raises(ErrorOperacion, match="ASIGNADO"):
        sistema.asignar("LOT-000001", "MUN-002", HOY)
    lote = sistema.lote("LOT-000001")
    assert lote is not None and lote.municipio_destino_id == "MUN-001"   # no cambió de destino


def test_despachar_conserva_el_destino(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000001", "MUN-001", HOY)
    lote = sistema.despachar("LOT-000001")
    assert lote.estado is EstadoLote.DESPACHADO and lote.municipio_destino_id == "MUN-001"
    with pytest.raises(ErrorOperacion):
        sistema.despachar("LOT-000001")                               # ya se despachó


def test_no_se_despacha_un_lote_sin_asignar(sistema: SistemaDonaciones) -> None:
    with pytest.raises(ErrorOperacion, match="DISPONIBLE"):
        sistema.despachar("LOT-000001")


@pytest.mark.parametrize(("lote_id", "municipio_id", "hoy", "fragmento"), [
    ("LOT-999999", "MUN-001", HOY, "no existe"),
    ("LOT-000001", "MUN-999", HOY, "no existe"),
    ("LOT-000002", "MUN-001", date(2026, 12, 1), "venció"),          # vence ese mismo día
])
def test_asignaciones_imposibles(sistema: SistemaDonaciones, lote_id: str, municipio_id: str,
                                 hoy: date, fragmento: str) -> None:
    with pytest.raises(ErrorOperacion, match=fragmento):
        sistema.asignar(lote_id, municipio_id, hoy)


def test_descartar_vencidos_solo_toca_los_disponibles(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000003", "MUN-001", HOY)
    descartados = sistema.descartar_vencidos(date(2027, 4, 1))       # vencieron el 2 y el 3
    assert [l.id for l in descartados] == ["LOT-000002"]              # el 3 ya estaba asignado
    lote = sistema.lote("LOT-000002")
    assert lote is not None and lote.estado is EstadoLote.DESCARTADO
    with pytest.raises(ErrorOperacion):
        sistema.asignar("LOT-000002", "MUN-001", HOY)                 # descartado: no vuelve


# ============================================================
# Asignación automática por triaje
# ============================================================

def test_el_municipio_mas_urgente_se_atiende_primero(sistema: SistemaDonaciones) -> None:
    hechas = sistema.asignar_automaticamente(HOY)
    destino = {a.lote_id: a.municipio_id for a in hechas}
    # El crítico recibe los dos lotes que vencen antes (FEFO), aunque estaba segundo en la lista
    assert destino == {"LOT-000002": "MUN-001", "LOT-000003": "MUN-001", "LOT-000001": "MUN-002"}
    assert [a.lote_id for a in hechas] == ["LOT-000002", "LOT-000003", "LOT-000001"]


def test_respeta_lo_ya_asignado_a_mano(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000001", "MUN-001", HOY)                     # MUN-001 ya tiene 600
    destino = {a.lote_id: a.municipio_id for a in sistema.asignar_automaticamente(HOY)}
    assert destino == {"LOT-000002": "MUN-001", "LOT-000003": "MUN-002"}


def test_no_asigna_lotes_vencidos(sistema: SistemaDonaciones) -> None:
    hechas = sistema.asignar_automaticamente(date(2026, 12, 1))       # el lote 2 vence ese día
    assert "LOT-000002" not in {a.lote_id for a in hechas}


def test_una_necesidad_cubierta_no_recibe_mas(sistema: SistemaDonaciones) -> None:
    sistema.asignar_automaticamente(HOY)
    _registrar(sistema, cantidad=5000)
    hechas = sistema.asignar_automaticamente(HOY)
    assert [a.municipio_id for a in hechas] == ["MUN-002"]            # MUN-001 ya estaba cubierto


def test_volver_a_ejecutar_sin_stock_nuevo_no_hace_nada(sistema: SistemaDonaciones) -> None:
    sistema.asignar_automaticamente(HOY)
    assert sistema.asignar_automaticamente(HOY) == []


# ============================================================
# 5. Informes
# ============================================================

def test_balance_despachado_contra_remanente(sistema: SistemaDonaciones) -> None:
    sistema.asignar("LOT-000001", "MUN-001", HOY)
    sistema.despachar("LOT-000001")
    sistema.asignar("LOT-000002", "MUN-002", HOY)
    agua = next(f for f in sistema.balance() if f.categoria is AGUA)
    assert (agua.disponible, agua.asignado, agua.despachado, agua.descartado) == (600, 600, 600, 0)
    otras = [f for f in sistema.balance() if f.categoria is not AGUA]
    assert all(f.disponible == f.asignado == f.despachado == f.descartado == 0 for f in otras)


def test_alertas_cuando_hay_stock_sin_asignar(sistema: SistemaDonaciones) -> None:
    alertas = sistema.alertas_desabastecimiento()
    assert [(a.municipio.id, a.faltante, a.critica) for a in alertas] == [
        ("MUN-001", 1000, False), ("MUN-002", 1000, False)]           # el crítico primero


def test_alerta_critica_cuando_ya_no_queda_stock(sistema: SistemaDonaciones) -> None:
    sistema.asignar_automaticamente(HOY)
    alertas = sistema.alertas_desabastecimiento()
    assert [(a.municipio.id, a.faltante, a.critica) for a in alertas] == [("MUN-002", 400, True)]


def test_las_asignaciones_se_guardan_y_se_recuperan(sistema: SistemaDonaciones, tmp_path: Path) -> None:
    sistema.asignar_automaticamente(HOY)
    sistema.despachar("LOT-000002")
    sistema.guardar(tmp_path)
    carga = cargar_csv(tmp_path)
    assert carga.rechazos == []
    assert carga.datos.lotes == sistema.datos.lotes


# ============================================================
# Consistencia ante transacciones masivas
# ============================================================

@pytest.fixture
def cambios_de_hilo_frecuentes() -> Iterator[None]:
    """Hace que Python cambie de hilo muy seguido: si hubiera una condición
    de carrera, así es mucho más probable que aparezca en la prueba."""
    anterior = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(anterior)


def test_transacciones_masivas_secuenciales() -> None:
    s = SistemaDonaciones(generar(42, FECHA_EVENTO))
    iniciales = _total_por_categoria(s)
    nuevos = [_registrar(s, categoria=c, cantidad=10 + i % 50,
                         fecha_caducidad=None if not c.perecedera else date(2027, 1, 1))
              for i in range(3000) for c in [list(Categoria)[i % 5]]]
    s.descartar_vencidos(HOY)
    asignados = s.asignar_automaticamente(HOY)
    for a in asignados[::2]:
        s.despachar(a.lote_id)

    esperados = {c: iniciales[c] + sum(l.cantidad for l in nuevos if l.categoria is c) for c in Categoria}
    assert _total_por_categoria(s) == esperados          # no se pierde ni se duplica nada
    assert s.verificar_consistencia() == []
    assert len({l.id for l in s.datos.lotes}) == len(s.datos.lotes)


@pytest.mark.usefixtures("cambios_de_hilo_frecuentes")
def test_registros_concurrentes_no_repiten_ids() -> None:
    s = SistemaDonaciones(_escenario())
    hilos, por_hilo = 8, 250
    salida = threading.Barrier(hilos)                    # todos arrancan a la vez

    def trabajar() -> None:
        salida.wait()
        for _ in range(por_hilo):
            _registrar(s)

    corriendo = [threading.Thread(target=trabajar) for _ in range(hilos)]
    for h in corriendo:
        h.start()
    for h in corriendo:
        h.join()

    ids = [l.id for l in s.datos.lotes]
    assert len(ids) == 3 + hilos * por_hilo
    assert sorted(ids) == [f"LOT-{n:06d}" for n in range(1, len(ids) + 1)]   # únicos y sin huecos


@pytest.mark.usefixtures("cambios_de_hilo_frecuentes")
def test_dos_operadores_no_pueden_asignar_el_mismo_lote() -> None:
    s = SistemaDonaciones(_escenario())
    hilos = 20
    salida = threading.Barrier(hilos)
    exitos: list[str] = []
    fallos: list[str] = []

    def intentar(municipio: str) -> None:
        salida.wait()
        try:
            s.asignar("LOT-000001", municipio, HOY)
            exitos.append(municipio)
        except ErrorOperacion:
            fallos.append(municipio)

    corriendo = [threading.Thread(target=intentar, args=(f"MUN-00{1 + i % 2}",)) for i in range(hilos)]
    for h in corriendo:
        h.start()
    for h in corriendo:
        h.join()

    assert len(exitos) == 1 and len(fallos) == hilos - 1
    lote = s.lote("LOT-000001")
    assert lote is not None and lote.municipio_destino_id == exitos[0]


@pytest.mark.usefixtures("cambios_de_hilo_frecuentes")
def test_operaciones_concurrentes_mezcladas_conservan_el_inventario() -> None:
    s = SistemaDonaciones(generar(42, FECHA_EVENTO))
    iniciales = _total_por_categoria(s)
    registrados: list[Lote] = []
    candado_lista = threading.Lock()
    errores: list[BaseException] = []
    salida = threading.Barrier(6)

    def registrar() -> None:
        salida.wait()
        for i in range(200):
            lote = _registrar(s, cantidad=1 + i)
            with candado_lista:
                registrados.append(lote)

    def asignar() -> None:
        salida.wait()
        for _ in range(5):
            s.asignar_automaticamente(HOY)

    def despachar() -> None:
        salida.wait()
        for _ in range(300):
            for lote in s.buscar_lotes(estado=EstadoLote.ASIGNADO)[:3]:
                try:
                    s.despachar(lote.id)
                except ErrorOperacion:
                    pass                  # otro hilo lo despachó primero: es válido

    def con_registro(funcion: Any) -> Any:
        def envoltura() -> None:
            try:
                funcion()
            except BaseException as e:    # un error en un hilo no se ve en el principal
                errores.append(e)
        return envoltura

    tareas = [registrar, registrar, registrar, asignar, despachar, despachar]
    corriendo = [threading.Thread(target=con_registro(t)) for t in tareas]
    for h in corriendo:
        h.start()
    for h in corriendo:
        h.join()

    assert errores == []
    assert len(registrados) == 600
    esperados = dict(iniciales)
    esperados[AGUA] += sum(l.cantidad for l in registrados)
    assert _total_por_categoria(s) == esperados
    assert s.verificar_consistencia() == []


# ============================================================
# Fase 3: operaciones apoyadas en las estructuras
# ============================================================

def _con_red_vial() -> SistemaDonaciones:
    """MUN-001 queda a 5 h de CA-01 y a 1 h de CA-06."""
    datos = _escenario()
    datos.lotes = []
    datos.necesidades = [Necesidad("MUN-001", AGUA, 500)]
    datos.vias = [
        Via("CA-01", "MUN-001", 200.0, 5.0, EstadoVia.TRANSITABLE),
        Via("CA-06", "MUN-001", 30.0, 1.0, EstadoVia.TRANSITABLE),
    ]
    return SistemaDonaciones(datos)


def test_inventario_por_centro(sistema: SistemaDonaciones) -> None:
    assert sistema.inventario_centro("CA-01")[AGUA] == 1800
    _registrar(sistema, centro_id="CA-06", cantidad=100)
    assert sistema.inventario_centro("CA-06")[AGUA] == 100
    sistema.asignar("LOT-000001", "MUN-001", HOY)                     # sale del inventario disponible
    assert sistema.inventario_centro("CA-01")[AGUA] == 1200
    assert sistema.inventario_centro("CA-01")[Categoria.MEDICO] == 0
    with pytest.raises(ErrorOperacion):
        sistema.inventario_centro("CA-99")


def test_aportes_por_rango_de_monto(sistema: SistemaDonaciones) -> None:
    for monto in [50_000, 2_000_000, 10_000_000, 80_000_000]:
        sistema.registrar_aporte(donante_id="DON-0001", monto_cop=monto, fecha=HOY)
    montos = [a.monto_cop for a in sistema.aportes_por_monto(2_000_000, 10_000_000)]
    assert montos == [2_000_000, 10_000_000]                          # ambos extremos incluidos
    assert sistema.aportes_por_monto(100_000_000, 200_000_000) == []


def test_ruta_por_la_red_vial() -> None:
    s = _con_red_vial()
    ruta = s.ruta("CA-01", "CA-06", Criterio.TIEMPO)
    assert ruta is not None and ruta.nodos == ("CA-01", "MUN-001", "CA-06") and ruta.costo == 6.0
    assert s.ruta("CA-01", "MUN-999") is None


def test_a_igual_caducidad_prefiere_el_centro_mas_cercano() -> None:
    s = _con_red_vial()
    lejos = _registrar(s, centro_id="CA-01", cantidad=600)
    cerca = _registrar(s, centro_id="CA-06", cantidad=600)
    hechas = s.asignar_automaticamente(HOY)
    assert [a.lote_id for a in hechas] == [cerca.id]
    assert lejos.id in {l.id for l in s.buscar_lotes(estado=EstadoLote.DISPONIBLE)}


def test_la_caducidad_pesa_mas_que_la_cercania() -> None:
    s = _con_red_vial()
    lejos_vence_antes = _registrar(s, centro_id="CA-01", cantidad=600, fecha_caducidad=date(2026, 12, 1))
    _registrar(s, centro_id="CA-06", cantidad=600, fecha_caducidad=date(2027, 6, 1))
    assert [a.lote_id for a in s.asignar_automaticamente(HOY)] == [lejos_vence_antes.id]


def test_a_igual_urgencia_se_reparte_antes_lo_que_vence_antes(sistema: SistemaDonaciones) -> None:
    sistema.datos.necesidades.append(Necesidad("MUN-001", Categoria.MEDICO, 50))
    sistema = SistemaDonaciones(sistema.datos)                        # reconstruye los índices
    _registrar(sistema, categoria=Categoria.MEDICO, descripcion="Insulina", cantidad=50,
               centro_id="CA-01", fecha_caducidad=date(2026, 11, 20))  # vence en 10 días
    hechas = sistema.asignar_automaticamente(HOY)
    assert hechas[0].categoria is Categoria.MEDICO                    # antes que el agua del mismo municipio


def test_solicitudes_en_riesgo_salen_por_el_lado_max(sistema: SistemaDonaciones) -> None:
    sistema.datos.necesidades.append(Necesidad("MUN-002", Categoria.REFUGIO, 10))
    sistema = SistemaDonaciones(sistema.datos)
    _registrar(sistema, categoria=Categoria.REFUGIO, descripcion="Carpa", cantidad=50, fecha_caducidad=None)
    en_riesgo = sistema.solicitudes_en_riesgo(HOY, 5)
    # Agua: se piden 2000 y hay 1800 → hay déficit; refugio alcanza → no aparece.
    # La menos prioritaria (BAJA) sale primero.
    assert [(a.municipio.id, a.categoria) for a in en_riesgo] == [("MUN-002", AGUA), ("MUN-001", AGUA)]


def test_sin_deficit_no_hay_solicitudes_en_riesgo(sistema: SistemaDonaciones) -> None:
    _registrar(sistema, cantidad=5000)
    assert sistema.solicitudes_en_riesgo(HOY, 5) == []


def test_la_verificacion_detecta_indices_desincronizados(sistema: SistemaDonaciones) -> None:
    assert sistema.verificar_consistencia() == []
    # Cambiar un lote "por debajo", sin pasar por las operaciones, desincroniza los índices
    sistema.datos.lotes[0] = dataclasses.replace(sistema.datos.lotes[0], cantidad=999)
    problemas = sistema.verificar_consistencia()
    assert any("balance" in p for p in problemas) and any("árbol" in p for p in problemas)


def test_los_indices_se_reconstruyen_al_cargar(sistema: SistemaDonaciones, tmp_path: Path) -> None:
    sistema.asignar_automaticamente(HOY)
    sistema.despachar("LOT-000002")
    sistema.guardar(tmp_path)
    recargado = SistemaDonaciones(cargar_csv(tmp_path).datos)
    assert recargado.verificar_consistencia() == []
    assert recargado.balance() == sistema.balance()
