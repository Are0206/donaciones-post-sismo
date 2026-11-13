"""Fase 3 — Estructuras de datos: casos de borde, invariantes y comparación con un oráculo.

El "oráculo" es una implementación obviamente correcta (dict, lista
ordenada, Bellman-Ford). Se aplican miles de operaciones al azar a la
estructura y al oráculo, y deben responder exactamente lo mismo.
"""
from __future__ import annotations

import math
import random
from datetime import date
from typing import Any

import pytest

from donaciones import benchmark
from donaciones.estructuras import ArbolAVL, Criterio, Grafo, MonticuloMinMax, TablaHash
from donaciones.generador import generar
from donaciones.modelo import FECHA_EVENTO, EstadoVia, Via


# ============================================================
# Tabla hash
# ============================================================

def test_tabla_hash_operaciones_basicas() -> None:
    t: TablaHash[str, int] = TablaHash()
    t["LOT-000001"] = 10
    t["LOT-000002"] = 20
    t["LOT-000001"] = 15                       # reemplaza, no duplica
    assert len(t) == 2 and t["LOT-000001"] == 15
    assert "LOT-000002" in t and "LOT-999999" not in t
    assert t.get("LOT-999999") is None
    del t["LOT-000002"]
    assert len(t) == 1 and "LOT-000002" not in t
    with pytest.raises(KeyError):
        t["LOT-000002"]
    with pytest.raises(KeyError):
        del t["LOT-000002"]


def test_tabla_hash_con_llave_compuesta() -> None:
    t: TablaHash[tuple[str, str], int] = TablaHash()
    t[("CA-01", "AGUA")] = 500
    t[("CA-01", "VIVERES")] = 300
    assert t[("CA-01", "AGUA")] == 500 and t[("CA-01", "VIVERES")] == 300


class _LlaveQueColisiona:
    """Todas sus instancias tienen el mismo hash: caen en la misma cubeta."""
    def __init__(self, n: int) -> None:
        self.n = n

    def __hash__(self) -> int:
        return 42

    def __eq__(self, otro: object) -> bool:
        return isinstance(otro, _LlaveQueColisiona) and otro.n == self.n


def test_tabla_hash_resuelve_colisiones() -> None:
    t: TablaHash[_LlaveQueColisiona, int] = TablaHash()
    for i in range(50):
        t[_LlaveQueColisiona(i)] = i
    assert t.cubeta_mas_larga() == 50          # el peor caso: una sola cubeta
    assert all(t[_LlaveQueColisiona(i)] == i for i in range(50))
    del t[_LlaveQueColisiona(10)]
    assert _LlaveQueColisiona(10) not in t and len(t) == 49


def test_tabla_hash_crece_y_mantiene_el_factor_de_carga() -> None:
    t: TablaHash[int, int] = TablaHash()
    for i in range(10_000):
        t[i] = i
        assert t.factor_de_carga <= TablaHash.CARGA_MAXIMA
    assert t.capacidad >= 10_000 / TablaHash.CARGA_MAXIMA
    assert all(t[i] == i for i in range(10_000))         # nada se perdió al crecer


def test_tabla_hash_contra_dict_con_operaciones_al_azar() -> None:
    azar = random.Random(1)
    t: TablaHash[str, int] = TablaHash()
    oraculo: dict[str, int] = {}
    for _ in range(20_000):
        llave = f"K{azar.randint(0, 2000)}"
        accion = azar.random()
        if accion < 0.6:
            valor = azar.randint(0, 1000)
            t[llave] = valor
            oraculo[llave] = valor
        elif accion < 0.85:
            assert t.get(llave) == oraculo.get(llave)
        elif llave in oraculo:
            del t[llave]
            del oraculo[llave]
    assert len(t) == len(oraculo)
    assert sorted(t.items()) == sorted(oraculo.items())


# ============================================================
# Montículo min-max
# ============================================================

def test_monticulo_vacio() -> None:
    m: MonticuloMinMax[int, str] = MonticuloMinMax()
    assert not m and len(m) == 0
    for operacion in (m.ver_min, m.ver_max, m.extraer_min, m.extraer_max):
        with pytest.raises(IndexError):
            operacion()


def test_monticulo_con_un_elemento_es_minimo_y_maximo() -> None:
    m: MonticuloMinMax[int, str] = MonticuloMinMax()
    m.insertar(5, "único")
    assert m.ver_min() == m.ver_max() == (5, "único")
    assert m.extraer_max() == (5, "único") and not m


def test_monticulo_saca_por_los_dos_extremos() -> None:
    m: MonticuloMinMax[int, str] = MonticuloMinMax()
    for p in [5, 1, 9, 3, 7, 2, 8]:
        m.insertar(p, f"v{p}")
    assert m.extraer_min() == (1, "v1")
    assert m.extraer_max() == (9, "v9")
    assert m.extraer_min() == (2, "v2")
    assert m.extraer_max() == (8, "v8")
    assert [m.extraer_min()[0] for _ in range(len(m))] == [3, 5, 7]


def test_monticulo_resuelve_empates_por_orden_de_llegada() -> None:
    m: MonticuloMinMax[int, str] = MonticuloMinMax()
    for nombre in ["primero", "segundo", "tercero"]:
        m.insertar(1, nombre)
    assert [m.extraer_min()[1] for _ in range(3)] == ["primero", "segundo", "tercero"]


@pytest.mark.parametrize("semilla", range(5))
def test_monticulo_contra_lista_ordenada(semilla: int) -> None:
    azar = random.Random(semilla)
    m: MonticuloMinMax[int, int] = MonticuloMinMax()
    oraculo: list[int] = []
    for _ in range(5_000):
        accion = azar.random()
        if accion < 0.5 or not oraculo:
            p = azar.randint(-1000, 1000)
            m.insertar(p, p)
            oraculo.append(p)
        elif accion < 0.75:
            oraculo.sort()
            assert m.extraer_min()[0] == oraculo.pop(0)
        else:
            oraculo.sort()
            assert m.extraer_max()[0] == oraculo.pop()
        if oraculo:
            assert m.ver_min()[0] == min(oraculo) and m.ver_max()[0] == max(oraculo)
    assert m.es_valido() and len(m) == len(oraculo)


def test_monticulo_conserva_su_propiedad_en_cada_paso() -> None:
    azar = random.Random(9)
    m: MonticuloMinMax[float, None] = MonticuloMinMax()
    for _ in range(500):
        m.insertar(azar.random(), None)
        assert m.es_valido()
    while m:
        (m.extraer_min if azar.random() < 0.5 else m.extraer_max)()
        assert m.es_valido()


# ============================================================
# Árbol AVL
# ============================================================

def test_avl_operaciones_basicas() -> None:
    a: ArbolAVL[int, str] = ArbolAVL()
    for k in [50, 20, 70, 10, 30]:
        a.insertar(k, f"v{k}")
    a.insertar(30, "nuevo")                    # reemplaza
    assert len(a) == 5 and a.buscar(30) == "nuevo" and a.buscar(99) is None
    assert [k for k, _ in a.en_orden()] == [10, 20, 30, 50, 70]
    assert a.eliminar(20) and not a.eliminar(20)
    assert [k for k, _ in a.en_orden()] == [10, 30, 50, 70]
    assert a.es_valido()


def test_avl_no_se_degenera_con_datos_ordenados() -> None:
    """El peor caso de un árbol de búsqueda común: insertar en orden."""
    a: ArbolAVL[int, None] = ArbolAVL()
    n = 10_000
    for k in range(n):
        a.insertar(k, None)
    cota = 1.4405 * math.log2(n + 2) - 0.3277  # altura máxima teórica de un AVL
    assert a.altura <= cota                    # un árbol sin balancear tendría altura 10.000
    assert a.es_valido()


def test_avl_rango_semiabierto() -> None:
    a: ArbolAVL[int, int] = ArbolAVL()
    for k in range(0, 100, 5):
        a.insertar(k, k)
    assert a.rango(10, 30) == [10, 15, 20, 25]          # incluye 10, excluye 30
    assert a.rango(None, 10) == [0, 5]
    assert a.rango(90, None) == [90, 95]
    assert a.rango(11, 14) == []
    assert a.rango(None, None) == list(range(0, 100, 5))


def test_avl_primero_desde() -> None:
    a: ArbolAVL[int, str] = ArbolAVL()
    for k in [10, 20, 30]:
        a.insertar(k, f"v{k}")
    assert a.primero_desde(15) == (20, "v20")
    assert a.primero_desde(20) == (20, "v20")
    assert a.primero_desde(31) is None


def test_avl_con_llave_fecha_id() -> None:
    """Así se guardan los lotes: varios pueden vencer el mismo día."""
    a: ArbolAVL[tuple[date, str], str] = ArbolAVL()
    a.insertar((date(2026, 12, 1), "LOT-000002"), "b")
    a.insertar((date(2026, 12, 1), "LOT-000001"), "a")
    a.insertar((date(2026, 11, 20), "LOT-000003"), "c")
    a.insertar((date.max, "LOT-000004"), "sin caducidad")
    hasta_diciembre = a.rango(None, (date(2026, 12, 2), ""))
    assert hasta_diciembre == ["c", "a", "b"]


@pytest.mark.parametrize("semilla", range(5))
def test_avl_contra_lista_ordenada(semilla: int) -> None:
    azar = random.Random(semilla)
    a: ArbolAVL[int, int] = ArbolAVL()
    oraculo: set[int] = set()
    for paso in range(5_000):
        k = azar.randint(0, 1500)
        if azar.random() < 0.6:
            a.insertar(k, k * 10)
            oraculo.add(k)
        else:
            assert a.eliminar(k) == (k in oraculo)
            oraculo.discard(k)
        if paso % 500 == 0:
            assert a.es_valido()
            desde, hasta = sorted(azar.sample(range(1500), 2))
            assert a.rango(desde, hasta) == [x * 10 for x in sorted(oraculo) if desde <= x < hasta]
    assert [k for k, _ in a.en_orden()] == sorted(oraculo)
    assert len(a) == len(oraculo) and a.es_valido()


# ============================================================
# Grafo y Dijkstra
# ============================================================

T, R, X = EstadoVia.TRANSITABLE, EstadoVia.RESTRINGIDA, EstadoVia.CERRADA


def _via(a: str, b: str, km: float, h: float, estado: EstadoVia = T) -> Via:
    return Via(a, b, km, h, estado)


def _grafo(*vias: Via) -> Grafo:
    g = Grafo()
    for v in vias:
        g.agregar_via(v)
    return g


def test_ruta_mas_corta_y_reconstruccion() -> None:
    g = _grafo(_via("CA-01", "MUN-001", 10, 1), _via("MUN-001", "MUN-002", 10, 1),
               _via("CA-01", "MUN-002", 50, 5))
    ruta = g.ruta("CA-01", "MUN-002", Criterio.DISTANCIA)
    assert ruta is not None
    assert ruta.nodos == ("CA-01", "MUN-001", "MUN-002") and ruta.costo == 20
    assert len(ruta.vias) == 2


def test_la_ruta_se_recorre_en_ambos_sentidos() -> None:
    g = _grafo(_via("CA-01", "MUN-001", 10, 1))
    ruta = g.ruta("MUN-001", "CA-01", Criterio.DISTANCIA)
    assert ruta is not None and ruta.nodos == ("MUN-001", "CA-01")


def test_evita_las_vias_cerradas() -> None:
    g = _grafo(_via("CA-01", "MUN-001", 5, 0.1, X), _via("CA-01", "MUN-002", 10, 1),
               _via("MUN-002", "MUN-001", 10, 1))
    ruta = g.ruta("CA-01", "MUN-001", Criterio.DISTANCIA)
    assert ruta is not None and ruta.nodos == ("CA-01", "MUN-002", "MUN-001")


def test_el_criterio_cambia_la_ruta() -> None:
    # Corta pero restringida (lenta) contra larga y despejada
    g = _grafo(_via("CA-01", "MUN-001", 20, 2.0, R),
               _via("CA-01", "MUN-002", 25, 0.5), _via("MUN-002", "MUN-001", 25, 0.5))
    por_distancia = g.ruta("CA-01", "MUN-001", Criterio.DISTANCIA)
    por_tiempo = g.ruta("CA-01", "MUN-001", Criterio.TIEMPO)
    assert por_distancia is not None and por_distancia.nodos == ("CA-01", "MUN-001")
    assert por_tiempo is not None and por_tiempo.nodos == ("CA-01", "MUN-002", "MUN-001")
    assert por_tiempo.costo == 1.0


def test_sin_camino_o_nodo_inexistente() -> None:
    g = _grafo(_via("CA-01", "MUN-001", 10, 1), _via("MUN-002", "MUN-003", 10, 1, X))
    assert g.ruta("CA-01", "MUN-003", Criterio.DISTANCIA) is None   # solo por una vía cerrada
    assert g.ruta("CA-01", "MUN-999", Criterio.DISTANCIA) is None
    assert g.ruta("CA-99", "MUN-001", Criterio.DISTANCIA) is None


def test_ruta_al_mismo_nodo() -> None:
    g = _grafo(_via("CA-01", "MUN-001", 10, 1))
    ruta = g.ruta("CA-01", "CA-01", Criterio.TIEMPO)
    assert ruta is not None and ruta.nodos == ("CA-01",) and ruta.costo == 0


def _bellman_ford(vias: list[Via], origen: str) -> dict[str, float]:
    """Oráculo: lento (O(V·E)) pero muy simple de verificar."""
    distancia = {origen: 0.0}
    for _ in range(len(vias) + 1):
        for v in vias:
            if v.estado is X:
                continue
            for a, b in ((v.origen_id, v.destino_id), (v.destino_id, v.origen_id)):
                if a in distancia and distancia[a] + v.distancia_km < distancia.get(b, math.inf):
                    distancia[b] = distancia[a] + v.distancia_km
    return distancia


@pytest.mark.parametrize("semilla", range(5))
def test_dijkstra_contra_bellman_ford(semilla: int) -> None:
    azar = random.Random(semilla)
    nodos = [f"MUN-{i:03d}" for i in range(60)]
    vias: list[Via] = []
    vistos: set[tuple[str, str]] = set()
    while len(vias) < 150:
        a, b = azar.sample(nodos, 2)
        if (a, b) in vistos or (b, a) in vistos:
            continue
        vistos.add((a, b))
        vias.append(_via(a, b, azar.randint(1, 100), 1.0, azar.choice([T, T, R, X])))
    g = _grafo(*vias)
    esperado = _bellman_ford(vias, nodos[0])
    obtenido = g.distancias(nodos[0], Criterio.DISTANCIA)
    assert dict(obtenido.items()) == pytest.approx(esperado)


def test_red_vial_real_evita_las_vias_cerradas() -> None:
    datos = generar(42, FECHA_EVENTO)
    g = _grafo(*datos.vias)
    assert g.cantidad_nodos == len(datos.centros) + len(datos.municipios)
    assert g.cantidad_aristas == len(datos.vias)
    # Jordán (MUN-003): la vía directa desde Los Santos está cerrada
    ruta = g.ruta("CA-04", "MUN-003", Criterio.TIEMPO)
    assert ruta is not None
    assert all(v.estado is not EstadoVia.CERRADA for v in ruta.vias)
    assert ruta.nodos[0] == "CA-04" and ruta.nodos[-1] == "MUN-003"


# ============================================================
# Benchmarks: con tamaños pequeños, solo para verificar que las dos
# versiones de cada comparación den el mismo resultado
# ============================================================

@pytest.mark.parametrize(("comparar", "n"), [
    (benchmark.comparar_busqueda, 300),
    (benchmark.comparar_cola, 300),
    (benchmark.comparar_rango, 300),
    (benchmark.comparar_dijkstra, 60),
])
def test_benchmark_compara_versiones_equivalentes(comparar: Any, n: int) -> None:
    medicion = comparar(n)              # cada comparación verifica por dentro que coincidan
    assert medicion.n == n and medicion.estructura_ms >= 0 and medicion.ingenua_ms >= 0


def test_dijkstra_ingenuo_coincide_en_la_red_real() -> None:
    g = _grafo(*generar(42, FECHA_EVENTO).vias)
    con_monticulo = dict(g.distancias("CA-01", Criterio.DISTANCIA).items())
    assert benchmark.dijkstra_ingenuo(g, "CA-01") == pytest.approx(con_monticulo)
