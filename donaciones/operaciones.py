"""
operaciones.py — Las operaciones del sistema (Fase 2), apoyadas en las
estructuras de datos (Fase 3).

  1. Registro de donaciones entrantes (lotes y aportes).
  2. Búsqueda por identificador, categoría, centro, estado o caducidad próxima;
     aportes por rango de monto.
  3. Asignación automática por triaje (montículo) y FEFO + cercanía (AVL + grafo).
  4. Despacho y descarte de lotes.
  5. Informes: balance de stock, inventario por centro, alertas y solicitudes en riesgo.
  6. Rutas óptimas por la red vial.

Índices que mantiene el sistema (todos se actualizan en cada cambio):

  Estructura                      Llave                    Para qué
  TablaHash  _pos_lote            id del lote              ubicar un lote en O(1)
  TablaHash  _centros, _municipios, _donantes   id         validar y consultar en O(1)
  TablaHash  _necesidades         (municipio, categoría)   necesidad de cada municipio
  TablaHash  _cubierto            (municipio, categoría)   cuánto ya se le asignó
  TablaHash  _stock_centro        (centro, categoría)      inventario disponible por centro
  TablaHash  _balance             (categoría, estado)      balance en O(1)
  ArbolAVL   _disponibles[cat]    (caducidad, id)          FEFO y "próximos a vencer"
  ArbolAVL   _aportes             (monto, id)              aportes por rango de monto
  Grafo      _grafo               —                        rutas y cercanía (Dijkstra)
  MonticuloMinMax (en cada asignación)                     cola de triaje

Los datos siguen guardándose también en las listas de `Datos`, que son
las que se escriben a los CSV; `_pos_lote` permite reemplazar un lote en
su lista en O(1).

Concurrencia: cada operación pública toma un candado (lock), así nunca
hay dos cambios a la vez sobre las estructuras.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Hashable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import TypeVar

from .estructuras import ArbolAVL, Criterio, Grafo, MonticuloMinMax, Ruta, TablaHash
from .modelo import (
    FECHA_EVENTO, TRANSICIONES, AporteEconomico, Categoria, CentroAcopio, Donante, EstadoLote,
    Lote, Municipio, Necesidad,
)
from .persistencia import Contexto, Datos, guardar_csv, validar_aporte, validar_lote


class ErrorOperacion(Exception):
    """La operación no se puede hacer en el estado actual del sistema."""


# ============================================================
# Resultados de las operaciones
# ============================================================

@dataclass(frozen=True)
class Asignacion:
    lote_id: str
    municipio_id: str
    categoria: Categoria
    cantidad: int


@dataclass(frozen=True)
class FilaBalance:
    """Cantidades de una categoría según el estado de sus lotes."""
    categoria: Categoria
    disponible: int        # remanente: en centros de acopio, sin destino
    asignado: int
    despachado: int
    descartado: int


@dataclass(frozen=True)
class Alerta:
    """Necesidad de un municipio que todavía no está cubierta."""
    municipio: Municipio
    categoria: Categoria
    necesidad: int
    cubierto: int            # asignado + despachado a ese municipio
    stock_disponible: int    # de esa categoría, en toda la red

    @property
    def faltante(self) -> int:
        return self.necesidad - self.cubierto

    @property
    def critica(self) -> bool:
        """No queda stock con qué cubrirla: hay que conseguir más donaciones."""
        return self.stock_disponible == 0


# Prioridad de una solicitud en la cola de triaje (menor = se atiende antes):
#   (urgencia, días hasta que vence el stock disponible de su categoría,
#    -población afectada, municipio, categoría)
Prioridad = tuple[int, int, int, str, str]

SIN_CADUCIDAD = 10**6      # días "infinitos" para categorías que no vencen

LlaveCaducidad = tuple[date, str]


def _llave_caducidad(lote: Lote) -> LlaveCaducidad:
    """Orden FEFO: la caducidad más próxima primero; sin caducidad, al final."""
    return (lote.fecha_caducidad or date.max, lote.id)


def _hasta_el_dia(dia: date) -> LlaveCaducidad | None:
    """Cota superior (excluyente) para "vence ese día o antes"."""
    return None if dia == date.max else (dia + timedelta(days=1), "")


L = TypeVar("L", bound=Hashable)


def _sumar(tabla: TablaHash[L, int], llave: L, cantidad: int) -> None:
    tabla[llave] = tabla.get(llave, 0) + cantidad


# ============================================================
# Sistema
# ============================================================

class SistemaDonaciones:

    def __init__(self, datos: Datos, fecha_evento: date = FECHA_EVENTO) -> None:
        self._datos = datos
        # RLock en vez de Lock: el mismo hilo puede volver a tomarlo sin bloquearse
        self._candado = threading.RLock()

        self._centros: TablaHash[str, CentroAcopio] = TablaHash()
        self._municipios: TablaHash[str, Municipio] = TablaHash()
        self._donantes: TablaHash[str, Donante] = TablaHash()
        self._necesidades: TablaHash[tuple[str, Categoria], Necesidad] = TablaHash()
        for c in datos.centros:
            self._centros[c.id] = c
        for m in datos.municipios:
            self._municipios[m.id] = m
        for x in datos.donantes:
            self._donantes[x.id] = x
        for n in datos.necesidades:
            self._necesidades[n.clave] = n
        self._contexto = Contexto(fecha_evento, self._centros, self._municipios, self._donantes)

        self._grafo = Grafo()
        for nodo in [*self._centros, *self._municipios]:
            self._grafo.agregar_nodo(nodo)
        for via in datos.vias:
            self._grafo.agregar_via(via)

        self._pos_lote: TablaHash[str, int] = TablaHash()
        self._disponibles: TablaHash[Categoria, ArbolAVL[LlaveCaducidad, Lote]] = TablaHash()
        for categoria in Categoria:
            self._disponibles[categoria] = ArbolAVL()
        self._cubierto: TablaHash[tuple[str, Categoria], int] = TablaHash()
        self._stock_centro: TablaHash[tuple[str, Categoria], int] = TablaHash()
        self._balance: TablaHash[tuple[Categoria, EstadoLote], int] = TablaHash()
        for posicion, lote in enumerate(datos.lotes):
            self._pos_lote[lote.id] = posicion
            self._indexar(lote, +1)

        self._aportes: ArbolAVL[tuple[int, str], AporteEconomico] = ArbolAVL()
        for a in datos.aportes:
            self._aportes.insertar((a.monto_cop, a.id), a)

        # Último número usado, para asignar ids nuevos sin recorrer nada
        self._ultimo_lote = max((int(l.id[4:]) for l in datos.lotes), default=0)
        self._ultimo_aporte = max((int(a.id[4:]) for a in datos.aportes), default=0)

    def _indexar(self, lote: Lote, signo: int) -> None:
        """Suma (signo +1) o resta (signo -1) un lote de los índices que dependen de su estado."""
        _sumar(self._balance, (lote.categoria, lote.estado), signo * lote.cantidad)
        if lote.estado is EstadoLote.DISPONIBLE:
            arbol = self._disponibles[lote.categoria]
            if signo > 0:
                arbol.insertar(_llave_caducidad(lote), lote)
            else:
                arbol.eliminar(_llave_caducidad(lote))
            _sumar(self._stock_centro, (lote.centro_id, lote.categoria), signo * lote.cantidad)
        if lote.municipio_destino_id is not None:
            _sumar(self._cubierto, (lote.municipio_destino_id, lote.categoria), signo * lote.cantidad)

    @property
    def datos(self) -> Datos:
        """Los datos actuales. Solo para leer: los cambios se hacen con las operaciones."""
        return self._datos

    def guardar(self, carpeta: Path) -> None:
        with self._candado:
            guardar_csv(carpeta, self._datos)

    # ========================================================
    # 1. Registro
    # ========================================================

    def registrar_lote(self, *, donante_id: str, centro_id: str, categoria: Categoria,
                       descripcion: str, cantidad: int, peso_kg: float, volumen_m3: float,
                       fecha_ingreso: date, fecha_caducidad: date | None,
                       requiere_frio: bool) -> Lote:
        """Registra un lote que llega a un centro de acopio. Queda DISPONIBLE.

        Aplica las mismas reglas que la carga de archivos: si algo no
        cumple, lanza ErrorValidacion y no se registra nada.
        Complejidad: O(log n) (validar en tablas hash e insertar en el AVL).
        """
        with self._candado:
            lote = Lote(
                id=f"LOT-{self._ultimo_lote + 1:06d}", donante_id=donante_id,
                centro_id=centro_id, categoria=categoria, descripcion=descripcion,
                cantidad=cantidad, peso_kg=peso_kg, volumen_m3=volumen_m3,
                fecha_ingreso=fecha_ingreso, fecha_caducidad=fecha_caducidad,
                requiere_frio=requiere_frio,
            )
            validar_lote(lote, self._contexto)
            self._datos.lotes.append(lote)
            self._pos_lote[lote.id] = len(self._datos.lotes) - 1
            self._indexar(lote, +1)
            self._ultimo_lote += 1          # solo si todo salió bien
            return lote

    def registrar_aporte(self, *, donante_id: str, monto_cop: int, fecha: date,
                         municipio_destino_id: str | None = None) -> AporteEconomico:
        """Complejidad: O(log n)."""
        with self._candado:
            aporte = AporteEconomico(f"APO-{self._ultimo_aporte + 1:05d}", donante_id,
                                     monto_cop, fecha, municipio_destino_id)
            validar_aporte(aporte, self._contexto)
            self._datos.aportes.append(aporte)
            self._aportes.insertar((aporte.monto_cop, aporte.id), aporte)
            self._ultimo_aporte += 1
            return aporte

    # ========================================================
    # 2. Búsqueda
    # ========================================================

    def lote(self, lote_id: str) -> Lote | None:
        """Complejidad: O(1) promedio (tabla hash)."""
        with self._candado:
            posicion = self._pos_lote.get(lote_id)
            return None if posicion is None else self._datos.lotes[posicion]

    def buscar_lotes(self, *, categoria: Categoria | None = None, centro_id: str | None = None,
                     estado: EstadoLote | None = None, donante_id: str | None = None,
                     vence_hasta: date | None = None) -> list[Lote]:
        """Lotes que cumplen TODOS los filtros dados (None = no filtrar).

        El resultado sale ordenado por caducidad, la más próxima primero;
        los lotes que no caducan quedan al final.

        Complejidad:
          - Con estado DISPONIBLE: se recorre solo el AVL de la categoría
            (o los cinco), O(log n + k) con k = lotes en el rango.
          - Sin ese filtro hay que revisar todos los lotes: O(n log n).
        """
        with self._candado:
            if estado is EstadoLote.DISPONIBLE:
                hasta = None if vence_hasta is None else _hasta_el_dia(vence_hasta)
                categorias = [categoria] if categoria is not None else list(Categoria)
                candidatos = [l for c in categorias for l in self._disponibles[c].rango(None, hasta)]
            else:
                candidatos = [
                    l for l in self._datos.lotes
                    if (categoria is None or l.categoria is categoria)
                    and (estado is None or l.estado is estado)
                    and (vence_hasta is None
                         or (l.fecha_caducidad is not None and l.fecha_caducidad <= vence_hasta))
                ]
            resultado = [l for l in candidatos
                         if (centro_id is None or l.centro_id == centro_id)
                         and (donante_id is None or l.donante_id == donante_id)]
            return sorted(resultado, key=_llave_caducidad)

    def proximos_a_vencer(self, hoy: date, dias: int) -> list[Lote]:
        """Lotes disponibles que vencen dentro de `dias` días (o ya vencieron)."""
        return self.buscar_lotes(estado=EstadoLote.DISPONIBLE, vence_hasta=hoy + timedelta(days=dias))

    def aportes_por_monto(self, minimo: int, maximo: int) -> list[AporteEconomico]:
        """Aportes con minimo ≤ monto ≤ maximo, de menor a mayor.

        Complejidad: O(log n + k) con el AVL ordenado por monto.
        """
        with self._candado:
            return self._aportes.rango((minimo, ""), (maximo + 1, ""))

    # ========================================================
    # 3 y 4. Cambios de estado
    # ========================================================

    def _cambiar_estado(self, lote_id: str, nuevo: EstadoLote, destino: str | None) -> Lote:
        """Reemplaza el lote por una copia con el nuevo estado y actualiza
        los índices. Quien llama tiene el candado. Complejidad: O(log n)."""
        posicion = self._pos_lote.get(lote_id)
        if posicion is None:
            raise ErrorOperacion(f"El lote {lote_id} no existe")
        actual = self._datos.lotes[posicion]
        if nuevo not in TRANSICIONES[actual.estado]:
            raise ErrorOperacion(f"El lote {lote_id} está {actual.estado.value}: "
                                 f"no puede pasar a {nuevo.value}")
        actualizado = replace(actual, estado=nuevo, municipio_destino_id=destino)
        self._indexar(actual, -1)
        self._datos.lotes[posicion] = actualizado
        self._indexar(actualizado, +1)
        return actualizado

    def asignar(self, lote_id: str, municipio_id: str, hoy: date) -> Lote:
        """Asigna un lote disponible a un municipio."""
        with self._candado:
            if municipio_id not in self._municipios:
                raise ErrorOperacion(f"El municipio {municipio_id} no existe")
            lote = self.lote(lote_id)
            if lote is not None and lote.vencido(hoy):
                raise ErrorOperacion(f"El lote {lote_id} venció el {lote.fecha_caducidad}")
            return self._cambiar_estado(lote_id, EstadoLote.ASIGNADO, municipio_id)

    def despachar(self, lote_id: str) -> Lote:
        """Marca como despachado un lote asignado. Conserva su destino."""
        with self._candado:
            lote = self.lote(lote_id)
            destino = lote.municipio_destino_id if lote is not None else None
            return self._cambiar_estado(lote_id, EstadoLote.DESPACHADO, destino)

    def descartar_vencidos(self, hoy: date) -> list[Lote]:
        """Descarta los lotes disponibles que ya vencieron.

        Complejidad: O(k log n): el AVL entrega directamente los k vencidos.
        """
        with self._candado:
            vencidos = [l for c in Categoria
                        for l in self._disponibles[c].rango(None, _hasta_el_dia(hoy))]
            return [self._cambiar_estado(l.id, EstadoLote.DESCARTADO, None)
                    for l in sorted(vencidos, key=_llave_caducidad)]

    # ========================================================
    # Asignación automática
    # ========================================================

    def _prioridad(self, necesidad: Necesidad, hoy: date) -> Prioridad:
        """Menor = más prioritaria.

        1. Urgencia del municipio (CRITICA primero).
        2. Vida útil: días hasta que vence el lote disponible más próximo
           de esa categoría. Lo que está por vencer se reparte antes.
        3. Más población afectada primero.
        4. Municipio y categoría, solo para desempatar siempre igual.
        """
        municipio = self._municipios[necesidad.municipio_id]
        proximo = self._disponibles[necesidad.categoria].primero_desde((hoy + timedelta(days=1), ""))
        dias = SIN_CADUCIDAD
        if proximo is not None and proximo[0][0] != date.max:
            dias = (proximo[0][0] - hoy).days
        return (municipio.urgencia.value, dias, -municipio.poblacion_afectada,
                municipio.id, necesidad.categoria.value)

    def _pendiente(self, necesidad: Necesidad) -> int:
        return necesidad.cantidad - self._cubierto.get(necesidad.clave, 0)

    def _cola_de_triaje(self, hoy: date) -> MonticuloMinMax[Prioridad, Necesidad]:
        """Las necesidades pendientes, ordenadas por prioridad. O(m log m)."""
        cola: MonticuloMinMax[Prioridad, Necesidad] = MonticuloMinMax()
        for necesidad in self._datos.necesidades:
            if self._pendiente(necesidad) > 0:
                cola.insertar(self._prioridad(necesidad, hoy), necesidad)
        return cola

    def _candidatos(self, categoria: Categoria, hoy: date,
                    cercania: TablaHash[str, float]) -> Iterator[Lote]:
        """Lotes disponibles y no vencidos, en orden FEFO.

        Entre lotes que vencen el mismo día, primero el del centro más
        cercano al municipio (por tiempo de viaje). Los centros sin ruta
        por carretera van al final.

        Se avanza por grupos de una misma fecha con primero_desde y rango
        (O(log n) cada uno), así se pueden asignar lotes mientras se recorre.
        """
        arbol = self._disponibles[categoria]
        desde: LlaveCaducidad = (hoy + timedelta(days=1), "")
        while True:
            primero = arbol.primero_desde(desde)
            if primero is None:
                return
            fecha = primero[0][0]
            hasta = _hasta_el_dia(fecha)
            grupo = arbol.rango((fecha, ""), hasta)
            grupo.sort(key=lambda l: (cercania.get(l.centro_id, math.inf), l.id))
            yield from grupo
            if hasta is None:
                return
            desde = hasta

    def asignar_automaticamente(self, hoy: date) -> list[Asignacion]:
        """Reparte los lotes disponibles entre las necesidades pendientes.

        1. Las necesidades salen del montículo en orden de triaje
           (ver _prioridad).
        2. Para cada una se usan primero los lotes que vencen antes
           (FEFO: first expired, first out) y, a igual caducidad, los del
           centro más cercano según Dijkstra.

        Se asignan lotes completos: el último puede pasarse un poco de lo
        necesario, a cambio de no partir lotes y conservar su trazabilidad.

        Complejidad: O(m log m) para la cola de m necesidades, más un
        Dijkstra O((V + E) log V) por necesidad, más O(log n) por lote asignado.
        """
        with self._candado:
            cola = self._cola_de_triaje(hoy)
            hechas: list[Asignacion] = []
            while cola:
                _, necesidad = cola.extraer_min()
                pendiente = self._pendiente(necesidad)
                if pendiente <= 0:
                    continue
                cercania = self._grafo.distancias(necesidad.municipio_id, Criterio.TIEMPO)
                for lote in self._candidatos(necesidad.categoria, hoy, cercania):
                    if pendiente <= 0:
                        break
                    self._cambiar_estado(lote.id, EstadoLote.ASIGNADO, necesidad.municipio_id)
                    pendiente -= lote.cantidad
                    hechas.append(Asignacion(lote.id, necesidad.municipio_id,
                                             lote.categoria, lote.cantidad))
            return hechas

    # ========================================================
    # 5. Informes (se calculan en el momento: siempre al día)
    # ========================================================

    def balance(self) -> list[FilaBalance]:
        """Por categoría: disponible (remanente), asignado, despachado y descartado.

        Complejidad: O(1): los totales se mantienen al día en una tabla hash.
        """
        with self._candado:
            def total(c: Categoria, e: EstadoLote) -> int:
                return self._balance.get((c, e), 0)
            return [FilaBalance(c, total(c, EstadoLote.DISPONIBLE), total(c, EstadoLote.ASIGNADO),
                                total(c, EstadoLote.DESPACHADO), total(c, EstadoLote.DESCARTADO))
                    for c in Categoria]

    def inventario_centro(self, centro_id: str) -> dict[Categoria, int]:
        """Cantidad disponible por categoría en un centro de acopio. O(1) por categoría."""
        with self._candado:
            if centro_id not in self._centros:
                raise ErrorOperacion(f"El centro {centro_id} no existe")
            return {c: self._stock_centro.get((centro_id, c), 0) for c in Categoria}

    def alertas_desabastecimiento(self) -> list[Alerta]:
        """Necesidades sin cubrir del todo.

        Primero las críticas (no queda stock), luego por urgencia del
        municipio y, a igual urgencia, por cantidad faltante.
        Complejidad: O(m log m) para m necesidades.
        """
        with self._candado:
            stock = {f.categoria: f.disponible for f in self.balance()}
            alertas = [
                Alerta(self._municipios[n.municipio_id], n.categoria, n.cantidad,
                       self._cubierto.get(n.clave, 0), stock[n.categoria])
                for n in self._datos.necesidades
                if self._pendiente(n) > 0
            ]
            return sorted(alertas, key=lambda a: (not a.critica, a.municipio.urgencia, -a.faltante))

    def solicitudes_en_riesgo(self, hoy: date, cuantas: int) -> list[Alerta]:
        """Las solicitudes que quedarían sin atender si no llega más ayuda.

        Solo se consideran las categorías donde lo pendiente supera el
        stock disponible. Entre esas solicitudes, las que se quedan sin
        cubrir son las de MENOR prioridad: se sacan por el lado max del
        montículo, la menos prioritaria primero. Son las que el operador
        debería escalar (por ejemplo, para comprarlas con aportes económicos).

        Complejidad: O(m log m) para armar la cola y O(log m) por cada una que se saca.
        """
        with self._candado:
            limite = (hoy + timedelta(days=1), "")
            stock = {c: sum(l.cantidad for l in self._disponibles[c].rango(limite, None))
                     for c in Categoria}
            pendiente = {c: 0 for c in Categoria}
            for n in self._datos.necesidades:
                pendiente[n.categoria] += max(0, self._pendiente(n))
            con_deficit = {c for c in Categoria if pendiente[c] > stock[c]}

            cola: MonticuloMinMax[Prioridad, Necesidad] = MonticuloMinMax()
            for n in self._datos.necesidades:
                if n.categoria in con_deficit and self._pendiente(n) > 0:
                    cola.insertar(self._prioridad(n, hoy), n)

            en_riesgo: list[Alerta] = []
            while cola and len(en_riesgo) < cuantas:
                _, n = cola.extraer_max()
                en_riesgo.append(Alerta(self._municipios[n.municipio_id], n.categoria, n.cantidad,
                                        self._cubierto.get(n.clave, 0), stock[n.categoria]))
            return en_riesgo

    # ========================================================
    # 6. Rutas
    # ========================================================

    def ruta(self, origen: str, destino: str, criterio: Criterio = Criterio.TIEMPO) -> Ruta | None:
        """Ruta óptima entre dos nodos (centros o municipios), evitando vías cerradas.

        Complejidad: O((V + E) log V) con Dijkstra.
        """
        with self._candado:
            return self._grafo.ruta(origen, destino, criterio)

    # ========================================================
    # Verificación
    # ========================================================

    def verificar_consistencia(self) -> list[str]:
        """Compara cada índice con lo que resulta de recorrer los datos desde cero.

        Lista vacía = todo consistente. Es O(n log n): es para pruebas, no
        para el uso normal.
        """
        with self._candado:
            problemas: list[str] = []
            lotes = self._datos.lotes

            if len(self._pos_lote) != len(lotes):
                problemas.append("el índice de posiciones no tiene la misma cantidad de lotes")
            for i, l in enumerate(lotes):
                if self._pos_lote.get(l.id) != i:
                    problemas.append(f"{l.id} no está en su posición del índice (¿id repetido?)")
                if l.municipio_destino_id is not None and l.municipio_destino_id not in self._municipios:
                    problemas.append(f"{l.id} va a un municipio inexistente")

            balance: dict[tuple[Categoria, EstadoLote], int] = {}
            cubierto: dict[tuple[str, Categoria], int] = {}
            stock: dict[tuple[str, Categoria], int] = {}
            for l in lotes:
                balance[(l.categoria, l.estado)] = balance.get((l.categoria, l.estado), 0) + l.cantidad
                if l.municipio_destino_id is not None:
                    k = (l.municipio_destino_id, l.categoria)
                    cubierto[k] = cubierto.get(k, 0) + l.cantidad
                if l.estado is EstadoLote.DISPONIBLE:
                    k = (l.centro_id, l.categoria)
                    stock[k] = stock.get(k, 0) + l.cantidad
            for nombre, indice, esperado in (("balance", dict(self._balance.items()), balance),
                                             ("cubierto", dict(self._cubierto.items()), cubierto),
                                             ("stock por centro", dict(self._stock_centro.items()), stock)):
                if {k: v for k, v in indice.items() if v != 0} != esperado:
                    problemas.append(f"el índice de {nombre} no coincide con los lotes")

            for c in Categoria:
                arbol = self._disponibles[c]
                esperados = sorted((l for l in lotes
                                    if l.categoria is c and l.estado is EstadoLote.DISPONIBLE),
                                   key=_llave_caducidad)
                if not arbol.es_valido() or [v for _, v in arbol.en_orden()] != esperados:
                    problemas.append(f"el árbol de disponibles de {c.value} no coincide con los lotes")
            return problemas
