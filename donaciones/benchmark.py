"""
benchmark.py — Fase 3: cada estructura contra su alternativa ingenua.

  Operación              Estructura                    Alternativa ingenua
  Buscar por llave       TablaHash          O(1)       recorrer una lista        O(n)
  Cola de prioridad      MonticuloMinMax    O(log n)   buscar el mínimo en lista O(n)
  Consulta de rango      ArbolAVL           O(log n+k) filtrar toda la lista     O(n)
  Rutas más cortas       Dijkstra+montículo O(E log V) Dijkstra con búsqueda     O(V²)
                                                       lineal del mínimo

En cada comparación se verifica primero que ambas versiones den el mismo
resultado: no tiene sentido comparar la velocidad de código que no hace
lo mismo. Como Python es interpretado, lo que importa no son los
milisegundos absolutos sino cómo crece el tiempo al crecer n.

Uso:  python -m donaciones.benchmark
"""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from .estructuras import ArbolAVL, Criterio, Grafo, MonticuloMinMax, TablaHash
from .modelo import EstadoVia, Via

R = TypeVar("R")
SEMILLA = 7


@dataclass(frozen=True)
class Medicion:
    operacion: str
    n: int
    estructura_ms: float
    ingenua_ms: float

    @property
    def veces_mas_rapida(self) -> float:
        return self.ingenua_ms / self.estructura_ms if self.estructura_ms > 0 else math.inf


def _cronometrar(funcion: Callable[[], R]) -> tuple[float, R]:
    inicio = time.perf_counter()
    resultado = funcion()
    return (time.perf_counter() - inicio) * 1000, resultado


# ============================================================
# 1. Buscar por llave
# ============================================================

def comparar_busqueda(n: int, consultas: int = 500) -> Medicion:
    azar = random.Random(SEMILLA)
    llaves = [f"LOT-{i:06d}" for i in range(n)]
    buscadas = [azar.choice(llaves) for _ in range(consultas)]

    tabla: TablaHash[str, int] = TablaHash()
    lista: list[tuple[str, int]] = []
    for i, llave in enumerate(llaves):
        tabla[llave] = i
        lista.append((llave, i))

    def con_tabla() -> list[int]:
        return [tabla[k] for k in buscadas]

    def con_lista() -> list[int]:
        encontrados = []
        for buscada in buscadas:
            for llave, valor in lista:            # O(n) por consulta
                if llave == buscada:
                    encontrados.append(valor)
                    break
        return encontrados

    t_tabla, r_tabla = _cronometrar(con_tabla)
    t_lista, r_lista = _cronometrar(con_lista)
    assert r_tabla == r_lista
    return Medicion("Buscar por llave", n, t_tabla, t_lista)


# ============================================================
# 2. Cola de prioridad: n inserciones y n extracciones del mínimo
# ============================================================

def comparar_cola(n: int) -> Medicion:
    azar = random.Random(SEMILLA)
    prioridades = [azar.random() for _ in range(n)]

    def con_monticulo() -> list[float]:
        m: MonticuloMinMax[float, None] = MonticuloMinMax()
        for p in prioridades:
            m.insertar(p, None)
        return [m.extraer_min()[0] for _ in range(n)]

    def con_lista() -> list[float]:
        pendientes = list(prioridades)
        salida = []
        while pendientes:
            minimo = min(pendientes)              # O(n) en cada extracción
            pendientes.remove(minimo)
            salida.append(minimo)
        return salida

    t_mont, r_mont = _cronometrar(con_monticulo)
    t_lista, r_lista = _cronometrar(con_lista)
    assert r_mont == r_lista
    return Medicion("Cola de prioridad", n, t_mont, t_lista)


# ============================================================
# 3. Consulta de rango (lotes que vencen entre dos fechas)
# ============================================================

def comparar_rango(n: int, consultas: int = 200) -> Medicion:
    azar = random.Random(SEMILLA)
    llaves = azar.sample(range(n * 10), n)        # "días" hasta la caducidad
    arbol: ArbolAVL[int, int] = ArbolAVL()
    for k in llaves:
        arbol.insertar(k, k)
    rangos = []
    for _ in range(consultas):
        desde = azar.randrange(n * 10)
        rangos.append((desde, desde + 100))       # unos 10 resultados por consulta

    def con_arbol() -> list[list[int]]:
        return [arbol.rango(d, h) for d, h in rangos]

    def con_lista() -> list[list[int]]:
        return [sorted(k for k in llaves if d <= k < h) for d, h in rangos]   # O(n) cada una

    t_arbol, r_arbol = _cronometrar(con_arbol)
    t_lista, r_lista = _cronometrar(con_lista)
    assert r_arbol == r_lista
    return Medicion("Consulta de rango", n, t_arbol, t_lista)


# ============================================================
# 4. Rutas más cortas desde un origen
# ============================================================

def red_al_azar(nodos: int, aristas_por_nodo: int = 3) -> Grafo:
    """Red conexa al azar: un camino que une todo, más vías extra."""
    azar = random.Random(SEMILLA)
    ids = [f"MUN-{i:03d}" for i in range(nodos)]
    grafo = Grafo()
    usados: set[tuple[str, str]] = set()

    def agregar(a: str, b: str) -> None:
        if a != b and (a, b) not in usados and (b, a) not in usados:
            usados.add((a, b))
            km = float(azar.randint(1, 100))
            grafo.agregar_via(Via(a, b, km, km / 45, EstadoVia.TRANSITABLE))

    for a, b in zip(ids, ids[1:]):
        agregar(a, b)
    while len(usados) < nodos * aristas_por_nodo:
        agregar(azar.choice(ids), azar.choice(ids))
    return grafo


def dijkstra_ingenuo(grafo: Grafo, origen: str) -> dict[str, float]:
    """Dijkstra sin montículo: en cada paso busca el mínimo recorriendo
    todos los nodos pendientes. O(V²).

    Guarda las distancias en la misma TablaHash que la versión con
    montículo: así la comparación mide SOLO la diferencia entre usar el
    montículo y buscar el mínimo recorriendo la lista.
    """
    distancia: TablaHash[str, float] = TablaHash()
    for nodo in grafo.nodos():
        distancia[nodo] = math.inf
    distancia[origen] = 0.0
    pendientes = list(grafo.nodos())
    while pendientes:
        posicion = 0                              # O(V) en cada paso: buscar el mínimo
        for i in range(1, len(pendientes)):
            if distancia[pendientes[i]] < distancia[pendientes[posicion]]:
                posicion = i
        actual = pendientes[posicion]
        if distancia[actual] == math.inf:
            break
        pendientes[posicion] = pendientes[-1]     # quitarlo en O(1)
        pendientes.pop()
        for vecino, via in grafo.vecinos(actual):
            nueva = distancia[actual] + via.distancia_km
            if nueva < distancia[vecino]:
                distancia[vecino] = nueva
    return {k: v for k, v in distancia.items() if v < math.inf}


def comparar_dijkstra(nodos: int) -> Medicion:
    grafo = red_al_azar(nodos)
    origen = "MUN-000"
    t_mont, r_mont = _cronometrar(lambda: dict(grafo.distancias(origen, Criterio.DISTANCIA).items()))
    t_ingenuo, r_ingenuo = _cronometrar(lambda: dijkstra_ingenuo(grafo, origen))
    assert r_mont.keys() == r_ingenuo.keys()
    assert all(math.isclose(r_mont[k], r_ingenuo[k]) for k in r_mont)
    return Medicion("Rutas más cortas", nodos, t_mont, t_ingenuo)


# ============================================================
# Ejecución
# ============================================================

COMPARACIONES: list[tuple[Callable[[int], Medicion], tuple[int, ...]]] = [
    (comparar_busqueda, (1_000, 10_000, 100_000)),
    (comparar_cola, (1_000, 4_000, 16_000)),
    (comparar_rango, (1_000, 10_000, 100_000)),
    (comparar_dijkstra, (125, 250, 500, 1_000)),  # los ids MUN-### admiten hasta 1000 nodos
]


def _veces(nuevo: float, anterior: float | None) -> str:
    return "" if anterior is None or anterior <= 0 else f"x{nuevo / anterior:.1f}"


def main() -> None:
    print(f"{'Operación':<19}{'n':>8}  {'Estructura':>10} {'crece':>6}  {'Ingenua':>10} {'crece':>6}  {'Mejora':>7}")
    print("-" * 76)
    for comparar, tamanos in COMPARACIONES:
        anterior: Medicion | None = None
        for n in tamanos:
            m = comparar(n)
            print(f"{m.operacion:<19}{m.n:>8,}  {m.estructura_ms:>7.1f} ms "
                  f"{_veces(m.estructura_ms, anterior.estructura_ms if anterior else None):>6}  "
                  f"{m.ingenua_ms:>7.1f} ms {_veces(m.ingenua_ms, anterior.ingenua_ms if anterior else None):>6}  "
                  f"{m.veces_mas_rapida:>6.1f}x")
            anterior = m
        print()
    print("crece  = cuántas veces aumentó el tiempo respecto a la fila anterior.")
    print("Mejora = cuántas veces más rápida es la estructura que la alternativa ingenua.")


if __name__ == "__main__":
    main()
