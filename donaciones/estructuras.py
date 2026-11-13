"""
estructuras.py — Fase 3: las cuatro estructuras de datos, implementadas a mano.

  1. TablaHash        búsqueda por llave en O(1) promedio
  2. MonticuloMinMax  cola de prioridad doble: mínimo y máximo en O(log n)
  3. ArbolAVL         árbol de búsqueda balanceado: orden y rangos en O(log n)
  4. Grafo            red vial con listas de adyacencia + Dijkstra

No se usan dict, set, heapq ni bisect de Python para la lógica de las
estructuras. Las listas de Python solo se usan como arreglos (posiciones
contiguas en memoria), que es lo que cada estructura necesita por debajo.

Cada operación indica su complejidad en el tiempo (n = número de elementos).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Iterator, MutableMapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from .modelo import EstadoVia, Via


class _Comparable(Protocol):
    def __lt__(self, otro: Any, /) -> bool: ...


K = TypeVar("K", bound=Hashable)
C = TypeVar("C", bound=_Comparable)
V = TypeVar("V")


# ============================================================
# 1. Tabla hash
# ============================================================

class TablaHash(MutableMapping[K, V]):
    """Tabla hash con encadenamiento separado.

    Cada cubeta es una lista de pares (llave, valor). Una llave va a la
    cubeta hash(llave) % capacidad; si dos llaves caen en la misma cubeta
    (colisión), quedan una detrás de otra. Cuando el factor de carga
    (elementos / cubetas) supera 0.75, la capacidad se duplica y todo se
    reubica (rehash), para que las cubetas sigan siendo cortas.

    La función hash() de Python solo da el número que dispersa las llaves;
    las cubetas, las colisiones y el crecimiento son de esta clase.

    Hereda de MutableMapping: al implementar las 5 operaciones básicas,
    Python le agrega get, items, `in`, etc. Así se usa igual que un dict.

    Complejidad (α = factor de carga ≤ 0.75):
        obtener, poner, quitar   O(1 + α) = O(1) promedio; O(n) peor caso
                                 (todas las llaves en una misma cubeta)
        crecer                   O(n), pero solo cada vez que n se duplica:
                                 repartido entre inserciones, O(1) amortizado
        espacio                  O(n)
    """

    CAPACIDAD_INICIAL = 8
    CARGA_MAXIMA = 0.75

    def __init__(self) -> None:
        self._cubetas: list[list[tuple[K, V]]] = [[] for _ in range(self.CAPACIDAD_INICIAL)]
        self._n = 0

    def _cubeta(self, llave: K) -> list[tuple[K, V]]:
        return self._cubetas[hash(llave) % len(self._cubetas)]

    def __getitem__(self, llave: K) -> V:
        for k, v in self._cubeta(llave):
            if k == llave:
                return v
        raise KeyError(llave)

    def __setitem__(self, llave: K, valor: V) -> None:
        cubeta = self._cubeta(llave)
        for i, (k, _) in enumerate(cubeta):
            if k == llave:
                cubeta[i] = (llave, valor)        # ya existía: se reemplaza
                return
        cubeta.append((llave, valor))
        self._n += 1
        if self._n > self.CARGA_MAXIMA * len(self._cubetas):
            self._crecer()

    def __delitem__(self, llave: K) -> None:
        cubeta = self._cubeta(llave)
        for i, (k, _) in enumerate(cubeta):
            if k == llave:
                # El orden dentro de la cubeta no importa: se trae el último
                # a este lugar y se quita el final, O(1) en vez de O(cubeta)
                cubeta[i] = cubeta[-1]
                cubeta.pop()
                self._n -= 1
                return
        raise KeyError(llave)

    def __iter__(self) -> Iterator[K]:
        for cubeta in self._cubetas:
            for k, _ in cubeta:
                yield k

    def __len__(self) -> int:
        return self._n

    def _crecer(self) -> None:
        viejas = self._cubetas
        self._cubetas = [[] for _ in range(2 * len(viejas))]
        for cubeta in viejas:
            for k, v in cubeta:
                self._cubeta(k).append((k, v))

    @property
    def capacidad(self) -> int:
        return len(self._cubetas)

    @property
    def factor_de_carga(self) -> float:
        return self._n / len(self._cubetas)

    def cubeta_mas_larga(self) -> int:
        return max(len(c) for c in self._cubetas)


# ============================================================
# 2. Montículo min-max
# ============================================================

class MonticuloMinMax(Generic[C, V]):
    """Cola de prioridad doble: da el mínimo y el máximo.

    Es un árbol binario completo guardado en un arreglo (hijos de i en
    2i+1 y 2i+2), con niveles alternados:
      - niveles pares (0, 2, 4…) = niveles min: cada elemento es menor o
        igual que todos sus descendientes;
      - niveles impares (1, 3…)  = niveles max: mayor o igual que todos
        sus descendientes.
    Por eso el mínimo está en la raíz y el máximo en uno de sus dos hijos.

    Los empates de prioridad se resuelven por orden de llegada: cada
    elemento lleva un número de secuencia.

    Complejidad (altura = ⌊log₂ n⌋):
        ver_min, ver_max          O(1)
        insertar                  O(log n): sube saltando de abuelo en abuelo
        extraer_min, extraer_max  O(log n): baja saltando de nieto en nieto
        espacio                   O(n)
    """

    def __init__(self) -> None:
        self._a: list[tuple[C, int, V]] = []
        self._secuencia = 0

    def __len__(self) -> int:
        return len(self._a)

    def __bool__(self) -> bool:
        return bool(self._a)

    @staticmethod
    def _es_nivel_min(i: int) -> bool:
        # nivel(i) = bit_length(i + 1) - 1; es min si el nivel es par
        return (i + 1).bit_length() % 2 == 1

    def _menor(self, i: int, j: int) -> bool:
        # Las tuplas se comparan por prioridad y, si empatan, por secuencia.
        # La secuencia nunca se repite, así que nunca se llega a comparar el valor.
        return self._a[i] < self._a[j]

    def _intercambiar(self, i: int, j: int) -> None:
        self._a[i], self._a[j] = self._a[j], self._a[i]

    # ---------- Insertar ----------

    def insertar(self, prioridad: C, valor: V) -> None:
        self._a.append((prioridad, self._secuencia, valor))
        self._secuencia += 1
        self._subir(len(self._a) - 1)

    def _subir(self, i: int) -> None:
        if i == 0:
            return
        padre = (i - 1) // 2
        if self._es_nivel_min(i):
            if self._menor(padre, i):              # es más grande que su padre (max)
                self._intercambiar(i, padre)
                self._subir_por_abuelos(padre, en_max=True)
            else:
                self._subir_por_abuelos(i, en_max=False)
        else:
            if self._menor(i, padre):              # es más pequeño que su padre (min)
                self._intercambiar(i, padre)
                self._subir_por_abuelos(padre, en_max=False)
            else:
                self._subir_por_abuelos(i, en_max=True)

    def _subir_por_abuelos(self, i: int, en_max: bool) -> None:
        while i >= 3:                              # tiene abuelo
            abuelo = ((i - 1) // 2 - 1) // 2
            debe_subir = self._menor(abuelo, i) if en_max else self._menor(i, abuelo)
            if not debe_subir:
                return
            self._intercambiar(i, abuelo)
            i = abuelo

    # ---------- Consultar y extraer ----------

    def ver_min(self) -> tuple[C, V]:
        if not self._a:
            raise IndexError("el montículo está vacío")
        prioridad, _, valor = self._a[0]
        return prioridad, valor

    def _posicion_max(self) -> int:
        n = len(self._a)
        if n <= 2:
            return n - 1                           # solo raíz, o raíz y un hijo
        return 1 if self._menor(2, 1) else 2

    def ver_max(self) -> tuple[C, V]:
        if not self._a:
            raise IndexError("el montículo está vacío")
        prioridad, _, valor = self._a[self._posicion_max()]
        return prioridad, valor

    def extraer_min(self) -> tuple[C, V]:
        if not self._a:
            raise IndexError("el montículo está vacío")
        return self._extraer(0)

    def extraer_max(self) -> tuple[C, V]:
        if not self._a:
            raise IndexError("el montículo está vacío")
        return self._extraer(self._posicion_max())

    def _extraer(self, i: int) -> tuple[C, V]:
        prioridad, _, valor = self._a[i]
        ultimo = self._a.pop()
        if i < len(self._a):                       # si no era el último, su lugar lo ocupa el último
            self._a[i] = ultimo
            self._bajar(i)
        return prioridad, valor

    def _bajar(self, i: int) -> None:
        es_min = self._es_nivel_min(i)
        n = len(self._a)
        while True:
            # Hijos (2i+1, 2i+2) y nietos (4i+3 … 4i+6) que existan
            candidatos = [j for j in (2 * i + 1, 2 * i + 2, 4 * i + 3, 4 * i + 4, 4 * i + 5, 4 * i + 6)
                          if j < n]
            if not candidatos:
                return
            m = candidatos[0]
            for j in candidatos[1:]:
                if (self._menor(j, m) if es_min else self._menor(m, j)):
                    m = j
            fuera_de_orden = self._menor(m, i) if es_min else self._menor(i, m)
            if not fuera_de_orden:
                return
            self._intercambiar(m, i)
            if m <= 2 * i + 2:                     # era un hijo: ya quedó en su lugar
                return
            padre = (m - 1) // 2                   # era un nieto: revisar contra su nuevo padre
            if (self._menor(padre, m) if es_min else self._menor(m, padre)):
                self._intercambiar(m, padre)
            i = m

    def es_valido(self) -> bool:
        """Verifica la propiedad min-max contra padre y abuelo de cada nodo."""
        for i in range(1, len(self._a)):
            for ancestro in ((i - 1) // 2, ((i - 1) // 2 - 1) // 2 if i >= 3 else -1):
                if ancestro < 0:
                    continue
                if self._es_nivel_min(ancestro) and self._menor(i, ancestro):
                    return False
                if not self._es_nivel_min(ancestro) and self._menor(ancestro, i):
                    return False
        return True


# ============================================================
# 3. Árbol AVL
# ============================================================

class _Nodo(Generic[C, V]):
    __slots__ = ("llave", "valor", "izq", "der", "altura")

    def __init__(self, llave: C, valor: V) -> None:
        self.llave = llave
        self.valor = valor
        self.izq: _Nodo[C, V] | None = None
        self.der: _Nodo[C, V] | None = None
        self.altura = 1


def _altura(nodo: _Nodo[Any, Any] | None) -> int:
    return nodo.altura if nodo is not None else 0


class ArbolAVL(Generic[C, V]):
    """Árbol binario de búsqueda autobalanceado (Adelson-Velsky y Landis).

    En cada nodo, la diferencia de altura entre sus subárboles izquierdo y
    derecho (factor de balance) es -1, 0 o 1. Si una inserción o un borrado
    la lleva a ±2, una o dos rotaciones la corrigen en O(1).

    Eso garantiza una altura h < 1.4405·log₂(n + 2): el árbol nunca se
    degenera en una lista, aunque los datos lleguen ordenados.

    Las llaves deben ser únicas. Para guardar varios lotes con la misma
    fecha se usa la llave (fecha, id).

    Complejidad:
        buscar, insertar, eliminar, primero_desde   O(log n)
        rango (k resultados)                        O(log n + k)
        recorrido en orden                          O(n)
        espacio                                     O(n)
    """

    def __init__(self) -> None:
        self._raiz: _Nodo[C, V] | None = None
        self._n = 0

    def __len__(self) -> int:
        return self._n

    @property
    def altura(self) -> int:
        return _altura(self._raiz)

    # ---------- Rotaciones ----------

    @staticmethod
    def _actualizar(nodo: _Nodo[C, V]) -> None:
        nodo.altura = 1 + max(_altura(nodo.izq), _altura(nodo.der))

    def _rotar_derecha(self, y: _Nodo[C, V]) -> _Nodo[C, V]:
        #       y            x
        #      / \          / \
        #     x   C   →    A   y
        #    / \              / \
        #   A   B            B   C
        x = y.izq
        assert x is not None
        y.izq = x.der
        x.der = y
        self._actualizar(y)
        self._actualizar(x)
        return x

    def _rotar_izquierda(self, x: _Nodo[C, V]) -> _Nodo[C, V]:
        y = x.der
        assert y is not None
        x.der = y.izq
        y.izq = x
        self._actualizar(x)
        self._actualizar(y)
        return y

    def _balancear(self, nodo: _Nodo[C, V]) -> _Nodo[C, V]:
        self._actualizar(nodo)
        balance = _altura(nodo.izq) - _altura(nodo.der)
        if balance > 1:                                       # cargado a la izquierda
            assert nodo.izq is not None
            if _altura(nodo.izq.izq) < _altura(nodo.izq.der): # caso izquierda-derecha
                nodo.izq = self._rotar_izquierda(nodo.izq)
            return self._rotar_derecha(nodo)
        if balance < -1:                                      # cargado a la derecha
            assert nodo.der is not None
            if _altura(nodo.der.der) < _altura(nodo.der.izq): # caso derecha-izquierda
                nodo.der = self._rotar_derecha(nodo.der)
            return self._rotar_izquierda(nodo)
        return nodo

    # ---------- Insertar y eliminar ----------

    def insertar(self, llave: C, valor: V) -> None:
        """Agrega la llave, o reemplaza su valor si ya existía."""
        self._raiz = self._insertar(self._raiz, llave, valor)

    def _insertar(self, nodo: _Nodo[C, V] | None, llave: C, valor: V) -> _Nodo[C, V]:
        if nodo is None:
            self._n += 1
            return _Nodo(llave, valor)
        if llave < nodo.llave:
            nodo.izq = self._insertar(nodo.izq, llave, valor)
        elif nodo.llave < llave:
            nodo.der = self._insertar(nodo.der, llave, valor)
        else:
            nodo.valor = valor
            return nodo
        return self._balancear(nodo)            # al regresar de la recursión, se rebalancea

    def eliminar(self, llave: C) -> bool:
        """Quita la llave. Devuelve False si no estaba."""
        antes = self._n
        self._raiz = self._eliminar(self._raiz, llave)
        return self._n < antes

    def _eliminar(self, nodo: _Nodo[C, V] | None, llave: C) -> _Nodo[C, V] | None:
        if nodo is None:
            return None
        if llave < nodo.llave:
            nodo.izq = self._eliminar(nodo.izq, llave)
        elif nodo.llave < llave:
            nodo.der = self._eliminar(nodo.der, llave)
        else:
            self._n -= 1
            if nodo.izq is None:
                return nodo.der
            if nodo.der is None:
                return nodo.izq
            # Dos hijos: lo reemplaza su sucesor (el menor del subárbol derecho)
            sucesor = nodo.der
            while sucesor.izq is not None:
                sucesor = sucesor.izq
            sucesor.der = self._quitar_minimo(nodo.der)
            sucesor.izq = nodo.izq
            nodo = sucesor
        return self._balancear(nodo)

    def _quitar_minimo(self, nodo: _Nodo[C, V]) -> _Nodo[C, V] | None:
        if nodo.izq is None:
            return nodo.der
        nodo.izq = self._quitar_minimo(nodo.izq)
        return self._balancear(nodo)

    # ---------- Consultas ----------

    def buscar(self, llave: C) -> V | None:
        nodo = self._raiz
        while nodo is not None:
            if llave < nodo.llave:
                nodo = nodo.izq
            elif nodo.llave < llave:
                nodo = nodo.der
            else:
                return nodo.valor
        return None

    def primero_desde(self, cota: C) -> tuple[C, V] | None:
        """El par con la menor llave que sea ≥ cota (o None)."""
        mejor: _Nodo[C, V] | None = None
        nodo = self._raiz
        while nodo is not None:
            if nodo.llave < cota:
                nodo = nodo.der
            else:
                mejor = nodo                    # candidato; quizá hay uno menor a la izquierda
                nodo = nodo.izq
        return (mejor.llave, mejor.valor) if mejor is not None else None

    def rango(self, desde: C | None, hasta: C | None) -> list[V]:
        """Valores con desde ≤ llave < hasta, en orden. None = sin límite.

        Solo baja por las ramas que pueden tener llaves dentro del rango.
        """
        resultado: list[V] = []

        def visitar(nodo: _Nodo[C, V] | None) -> None:
            if nodo is None:
                return
            mayor_que_desde = desde is None or not nodo.llave < desde
            menor_que_hasta = hasta is None or nodo.llave < hasta
            if mayor_que_desde:
                visitar(nodo.izq)               # a la izquierda puede haber llaves en el rango
            if mayor_que_desde and menor_que_hasta:
                resultado.append(nodo.valor)
            if menor_que_hasta:
                visitar(nodo.der)

        visitar(self._raiz)
        return resultado

    def en_orden(self) -> Iterator[tuple[C, V]]:
        """Recorre todo el árbol de la menor a la mayor llave. No modificar mientras tanto."""
        pila: list[_Nodo[C, V]] = []
        nodo = self._raiz
        while pila or nodo is not None:
            while nodo is not None:
                pila.append(nodo)
                nodo = nodo.izq
            nodo = pila.pop()
            yield nodo.llave, nodo.valor
            nodo = nodo.der

    def es_valido(self) -> bool:
        """Verifica orden, alturas y balance de todo el árbol."""
        def revisar(nodo: _Nodo[C, V] | None, minimo: C | None, maximo: C | None) -> int:
            if nodo is None:
                return 0
            if (minimo is not None and not minimo < nodo.llave) or \
               (maximo is not None and not nodo.llave < maximo):
                raise ValueError("orden")
            hi = revisar(nodo.izq, minimo, nodo.llave)
            hd = revisar(nodo.der, nodo.llave, maximo)
            if abs(hi - hd) > 1 or nodo.altura != 1 + max(hi, hd):
                raise ValueError("balance")
            return nodo.altura
        try:
            revisar(self._raiz, None, None)
        except ValueError:
            return False
        return sum(1 for _ in self.en_orden()) == self._n


# ============================================================
# 4. Grafo de la red vial
# ============================================================

class Criterio(Enum):
    DISTANCIA = "DISTANCIA"     # kilómetros
    TIEMPO = "TIEMPO"           # horas: ya penaliza las vías restringidas


def peso(criterio: Criterio) -> Callable[[Via], float]:
    """Función que da el peso de una vía según el criterio."""
    if criterio is Criterio.DISTANCIA:
        return lambda via: via.distancia_km
    return lambda via: via.tiempo_h


@dataclass(frozen=True)
class Ruta:
    nodos: tuple[str, ...]      # del origen al destino
    vias: tuple[Via, ...]
    costo: float                # km u horas, según el criterio


class Grafo:
    """Grafo no dirigido y ponderado, con listas de adyacencia.

    Vértices: centros de acopio y municipios. Aristas: vías.
    Se eligieron listas de adyacencia y no una matriz porque la red es
    dispersa (E ≈ V): la matriz ocuparía O(V²) casi toda vacía.

    Complejidad (V vértices, E aristas):
        agregar vía                 O(1) promedio
        Dijkstra                    O((V + E) log V)
        espacio                     O(V + E)
    """

    def __init__(self) -> None:
        self._adyacencia: TablaHash[str, list[Via]] = TablaHash()
        self._aristas = 0

    @property
    def cantidad_nodos(self) -> int:
        return len(self._adyacencia)

    @property
    def cantidad_aristas(self) -> int:
        return self._aristas

    def nodos(self) -> Iterator[str]:
        return iter(self._adyacencia)

    def agregar_nodo(self, nodo: str) -> None:
        if nodo not in self._adyacencia:
            self._adyacencia[nodo] = []

    def agregar_via(self, via: Via) -> None:
        """Una vía se guarda en las listas de sus dos extremos (no tiene sentido)."""
        self.agregar_nodo(via.origen_id)
        self.agregar_nodo(via.destino_id)
        self._adyacencia[via.origen_id].append(via)
        self._adyacencia[via.destino_id].append(via)
        self._aristas += 1

    def vecinos(self, nodo: str) -> Iterator[tuple[str, Via]]:
        """Vecinos alcanzables: las vías cerradas no cuentan."""
        for via in self._adyacencia.get(nodo, []):
            if via.estado is not EstadoVia.CERRADA:
                otro = via.destino_id if via.origen_id == nodo else via.origen_id
                yield otro, via

    def _dijkstra(self, origen: str, criterio: Criterio, destino: str | None = None
                  ) -> tuple[TablaHash[str, float], TablaHash[str, tuple[str, Via]]]:
        """Distancias mínimas desde el origen.

        La cola es el montículo min-max (se usa su lado min). Cuando se
        encuentra un camino mejor a un nodo, se inserta otra vez en lugar
        de actualizarlo; la entrada vieja se ignora al salir ("borrado
        perezoso"). La cola llega a tener a lo sumo E entradas, así que
        cada operación cuesta O(log E) = O(log V).

        Si se da un destino, se detiene al sacarlo de la cola: en ese
        momento su distancia ya es definitiva.
        """
        peso_de = peso(criterio)
        distancia: TablaHash[str, float] = TablaHash()
        previo: TablaHash[str, tuple[str, Via]] = TablaHash()
        if origen not in self._adyacencia:
            return distancia, previo

        distancia[origen] = 0.0
        cola: MonticuloMinMax[float, str] = MonticuloMinMax()
        cola.insertar(0.0, origen)
        while cola:
            d, nodo = cola.extraer_min()
            if d > distancia[nodo]:
                continue                        # entrada vieja: ya se encontró algo mejor
            if nodo == destino:
                break
            for vecino, via in self.vecinos(nodo):
                nueva = d + peso_de(via)
                if nueva < distancia.get(vecino, math.inf):
                    distancia[vecino] = nueva
                    previo[vecino] = (nodo, via)
                    cola.insertar(nueva, vecino)
        return distancia, previo

    def distancias(self, origen: str, criterio: Criterio) -> TablaHash[str, float]:
        """Costo mínimo desde el origen a cada nodo alcanzable."""
        return self._dijkstra(origen, criterio)[0]

    def ruta(self, origen: str, destino: str, criterio: Criterio) -> Ruta | None:
        """Ruta de menor costo, o None si no hay camino (o algún nodo no existe)."""
        if destino not in self._adyacencia:
            return None
        distancia, previo = self._dijkstra(origen, criterio, destino)
        if destino not in distancia:
            return None
        nodos = [destino]
        vias: list[Via] = []
        while nodos[-1] != origen:              # se reconstruye de atrás hacia adelante
            anterior, via = previo[nodos[-1]]
            nodos.append(anterior)
            vias.append(via)
        return Ruta(tuple(reversed(nodos)), tuple(reversed(vias)), distancia[destino])
