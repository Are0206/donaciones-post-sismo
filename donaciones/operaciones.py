"""
operaciones.py — Fase 2: las operaciones del sistema.

  1. Registro de donaciones entrantes (lotes y aportes).
  2. Búsqueda por identificador, categoría, centro, estado o caducidad próxima.
  3. Asignación automática según la urgencia de cada municipio.
  4. Despacho y descarte de lotes.
  5. Informes: balance de stock y alertas de desabastecimiento.

Todo se hace sobre las listas de la Fase 1: buscar es recorrerlas, O(n).
Es a propósito la versión "ingenua". En la Fase 3 estas mismas
operaciones se apoyan en tabla hash, montículo, árbol AVL y grafo, y los
benchmarks comparan ambas versiones.

Concurrencia: varios operadores pueden registrar o asignar al mismo
tiempo. Cada operación pública toma un candado (lock), así nunca hay dos
cambios a la vez sobre las listas y el inventario no queda inconsistente.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from .modelo import (
    FECHA_EVENTO, TRANSICIONES, AporteEconomico, Categoria, EstadoLote, Lote, Municipio,
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


# ============================================================
# Sistema
# ============================================================

class SistemaDonaciones:

    def __init__(self, datos: Datos, fecha_evento: date = FECHA_EVENTO) -> None:
        self._datos = datos
        self._fecha_evento = fecha_evento
        # RLock en vez de Lock: el mismo hilo puede volver a tomarlo sin bloquearse
        self._candado = threading.RLock()
        # Último número usado, para asignar ids nuevos sin recorrer la lista
        self._ultimo_lote = max((int(l.id[4:]) for l in datos.lotes), default=0)
        self._ultimo_aporte = max((int(a.id[4:]) for a in datos.aportes), default=0)

    @property
    def datos(self) -> Datos:
        """Los datos actuales. Solo para leer: los cambios se hacen con las operaciones."""
        return self._datos

    def guardar(self, carpeta: Path) -> None:
        with self._candado:
            guardar_csv(carpeta, self._datos)

    def _contexto(self) -> Contexto:
        d = self._datos
        return Contexto(self._fecha_evento,
                        centros={c.id: c for c in d.centros},
                        municipios={m.id for m in d.municipios},
                        donantes={x.id for x in d.donantes})

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
        """
        with self._candado:
            lote = Lote(
                id=f"LOT-{self._ultimo_lote + 1:06d}", donante_id=donante_id,
                centro_id=centro_id, categoria=categoria, descripcion=descripcion,
                cantidad=cantidad, peso_kg=peso_kg, volumen_m3=volumen_m3,
                fecha_ingreso=fecha_ingreso, fecha_caducidad=fecha_caducidad,
                requiere_frio=requiere_frio,
            )
            validar_lote(lote, self._contexto())
            self._datos.lotes.append(lote)
            self._ultimo_lote += 1          # solo si todo salió bien
            return lote

    def registrar_aporte(self, *, donante_id: str, monto_cop: int, fecha: date,
                         municipio_destino_id: str | None = None) -> AporteEconomico:
        with self._candado:
            aporte = AporteEconomico(f"APO-{self._ultimo_aporte + 1:05d}", donante_id,
                                     monto_cop, fecha, municipio_destino_id)
            validar_aporte(aporte, self._contexto())
            self._datos.aportes.append(aporte)
            self._ultimo_aporte += 1
            return aporte

    # ========================================================
    # 2. Búsqueda
    # ========================================================

    def lote(self, lote_id: str) -> Lote | None:
        with self._candado:
            for l in self._datos.lotes:             # O(n)
                if l.id == lote_id:
                    return l
            return None

    def buscar_lotes(self, *, categoria: Categoria | None = None, centro_id: str | None = None,
                     estado: EstadoLote | None = None, donante_id: str | None = None,
                     vence_hasta: date | None = None) -> list[Lote]:
        """Lotes que cumplen TODOS los filtros dados (None = no filtrar).

        El resultado sale ordenado por caducidad, la más próxima primero;
        los lotes que no caducan quedan al final.
        """
        with self._candado:
            resultado = [
                l for l in self._datos.lotes
                if (categoria is None or l.categoria is categoria)
                and (centro_id is None or l.centro_id == centro_id)
                and (estado is None or l.estado is estado)
                and (donante_id is None or l.donante_id == donante_id)
                and (vence_hasta is None
                     or (l.fecha_caducidad is not None and l.fecha_caducidad <= vence_hasta))
            ]
            return sorted(resultado, key=_por_caducidad)

    def proximos_a_vencer(self, hoy: date, dias: int) -> list[Lote]:
        """Lotes disponibles que vencen dentro de `dias` días (o ya vencieron)."""
        return self.buscar_lotes(estado=EstadoLote.DISPONIBLE, vence_hasta=hoy + timedelta(days=dias))

    # ========================================================
    # 3 y 4. Cambios de estado
    # ========================================================

    def _cambiar_estado(self, lote_id: str, nuevo: EstadoLote, destino: str | None) -> Lote:
        """Reemplaza el lote por una copia con el nuevo estado. Quien llama tiene el candado."""
        lotes = self._datos.lotes
        for i, actual in enumerate(lotes):          # O(n)
            if actual.id == lote_id:
                if nuevo not in TRANSICIONES[actual.estado]:
                    raise ErrorOperacion(f"El lote {lote_id} está {actual.estado.value}: "
                                         f"no puede pasar a {nuevo.value}")
                lotes[i] = replace(actual, estado=nuevo, municipio_destino_id=destino)
                return lotes[i]
        raise ErrorOperacion(f"El lote {lote_id} no existe")

    def asignar(self, lote_id: str, municipio_id: str, hoy: date) -> Lote:
        """Asigna un lote disponible a un municipio."""
        with self._candado:
            if all(m.id != municipio_id for m in self._datos.municipios):
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
        """Descarta los lotes disponibles que ya vencieron. Devuelve los descartados."""
        with self._candado:
            vencidos = [l for l in self._datos.lotes
                        if l.estado is EstadoLote.DISPONIBLE and l.vencido(hoy)]
            return [self._cambiar_estado(l.id, EstadoLote.DESCARTADO, None) for l in vencidos]

    def asignar_automaticamente(self, hoy: date) -> list[Asignacion]:
        """Reparte los lotes disponibles entre las necesidades pendientes.

        Orden de atención (triaje):
          1. Municipios más urgentes primero (CRITICA antes que BAJA).
          2. A igual urgencia, el de más población afectada.
        Para cada necesidad se usan primero los lotes que vencen antes
        (FEFO: first expired, first out), así se pierde menos por vencimiento.

        Se asignan lotes completos: el último puede pasarse un poco de lo
        necesario, a cambio de no partir lotes y conservar su trazabilidad.
        """
        with self._candado:
            cubierto = self._cubierto()
            hechas: list[Asignacion] = []
            orden = sorted(self._datos.municipios,
                           key=lambda m: (m.urgencia, -m.poblacion_afectada, m.id))

            for municipio in orden:
                for necesidad in self._datos.necesidades:
                    if necesidad.municipio_id != municipio.id:
                        continue
                    pendiente = necesidad.cantidad - cubierto.get(necesidad.clave, 0)
                    if pendiente <= 0:
                        continue
                    candidatos = sorted(
                        (l for l in self._datos.lotes
                         if l.estado is EstadoLote.DISPONIBLE
                         and l.categoria is necesidad.categoria and not l.vencido(hoy)),
                        key=_por_caducidad)
                    for lote in candidatos:
                        if pendiente <= 0:
                            break
                        self._cambiar_estado(lote.id, EstadoLote.ASIGNADO, municipio.id)
                        pendiente -= lote.cantidad
                        hechas.append(Asignacion(lote.id, municipio.id, lote.categoria, lote.cantidad))
            return hechas

    # ========================================================
    # 5. Informes (se calculan en el momento: siempre al día)
    # ========================================================

    def _cubierto(self) -> dict[tuple[str, Categoria], int]:
        """Cantidad ya asignada o despachada a cada (municipio, categoría)."""
        total: dict[tuple[str, Categoria], int] = {}
        for l in self._datos.lotes:
            if l.municipio_destino_id is not None:
                clave = (l.municipio_destino_id, l.categoria)
                total[clave] = total.get(clave, 0) + l.cantidad
        return total

    def balance(self) -> list[FilaBalance]:
        """Por categoría: cuánto hay disponible (remanente), asignado, despachado y descartado."""
        with self._candado:
            suma = {(c, e): 0 for c in Categoria for e in EstadoLote}
            for l in self._datos.lotes:
                suma[(l.categoria, l.estado)] += l.cantidad
            return [FilaBalance(c, suma[(c, EstadoLote.DISPONIBLE)], suma[(c, EstadoLote.ASIGNADO)],
                                suma[(c, EstadoLote.DESPACHADO)], suma[(c, EstadoLote.DESCARTADO)])
                    for c in Categoria]

    def alertas_desabastecimiento(self) -> list[Alerta]:
        """Necesidades sin cubrir del todo.

        Primero las críticas (no queda stock), luego por urgencia del
        municipio y, a igual urgencia, por cantidad faltante.
        """
        with self._candado:
            cubierto = self._cubierto()
            stock = {f.categoria: f.disponible for f in self.balance()}
            municipios = {m.id: m for m in self._datos.municipios}
            alertas = [
                Alerta(municipios[n.municipio_id], n.categoria, n.cantidad,
                       cubierto.get(n.clave, 0), stock[n.categoria])
                for n in self._datos.necesidades
                if cubierto.get(n.clave, 0) < n.cantidad
            ]
            return sorted(alertas, key=lambda a: (not a.critica, a.municipio.urgencia, -a.faltante))

    def verificar_consistencia(self) -> list[str]:
        """Revisa invariantes del inventario. Lista vacía = todo consistente."""
        with self._candado:
            problemas: list[str] = []
            vistos: set[str] = set()
            municipios = {m.id for m in self._datos.municipios}
            for l in self._datos.lotes:
                if l.id in vistos:
                    problemas.append(f"{l.id} aparece dos veces")
                vistos.add(l.id)
                if l.municipio_destino_id is not None and l.municipio_destino_id not in municipios:
                    problemas.append(f"{l.id} va a un municipio inexistente")
            return problemas


def _por_caducidad(lote: Lote) -> tuple[date, str]:
    """Orden FEFO: la caducidad más próxima primero; sin caducidad, al final."""
    return (lote.fecha_caducidad or date.max, lote.id)
