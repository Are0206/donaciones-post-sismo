"""
controlador.py — Fase 4: la lógica de la interfaz gráfica, sin Tkinter.

La ventana (interfaz.py) solo dibuja y reacciona a clics. Todo lo demás
está aquí:

  1. Ejecutor: corre las operaciones en un hilo de trabajo para que la
     ventana nunca se congele, y devuelve los resultados al hilo de la
     ventana.
  2. Validación de formularios: convierte lo que escribe el operador y
     reúne TODOS los errores, campo por campo.
  3. Datos de cada panel: resumen, tablas, alertas y mapa, ya listos
     para mostrar.

Como aquí no hay Tkinter, todo esto se prueba sin abrir ventanas.
"""
from __future__ import annotations

import functools
import math
import queue
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypeVar

from .estructuras import Criterio, Ruta
from .modelo import Categoria, ErrorValidacion, EstadoLote, EstadoVia, Lote, Urgencia, Via
from .operaciones import Alerta, ErrorOperacion, SistemaDonaciones
from .persistencia import (
    CARPETA_DATOS, campo_booleano, campo_entero, campo_enum, campo_fecha, campo_fecha_opcional,
    campo_real, campo_texto, cargar_csv,
)

T = TypeVar("T")


# ============================================================
# 1. Ejecución en segundo plano
# ============================================================

class Ejecutor:
    """Corre operaciones en un hilo de trabajo y entrega sus resultados
    al hilo de la ventana.

    Tkinter no es seguro entre hilos: solo el hilo principal puede tocar
    la ventana. Por eso el hilo de trabajo nunca llama a la interfaz: deja
    el resultado en una cola, y la ventana la revisa cada pocos
    milisegundos llamando a procesar_pendientes() desde su propio hilo.

    Hay un solo hilo de trabajo: las operaciones se ejecutan una a una, en
    el orden en que se pidieron.

    Acciones exclusivas: si se pide una acción con nombre (por ejemplo,
    "asignar") mientras otra con el mismo nombre está en curso, se ignora.
    Así un doble clic no la ejecuta dos veces.
    """

    def __init__(self) -> None:
        self._hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="operaciones")
        self._listos: queue.Queue[tuple[str | None, Callable[[], None]]] = queue.Queue()
        self._en_curso: set[str] = set()
        self._pendientes = 0
        self._candado = threading.Lock()

    @property
    def ocupado(self) -> bool:
        with self._candado:
            return self._pendientes > 0

    def en_curso(self, accion: str) -> bool:
        with self._candado:
            return accion in self._en_curso

    def ejecutar(self, tarea: Callable[[], T], al_terminar: Callable[[T], None],
                 al_fallar: Callable[[Exception], None], accion: str | None = None) -> bool:
        """Programa la tarea y vuelve de inmediato.

        al_terminar o al_fallar se llaman después, desde procesar_pendientes.
        Devuelve False si la acción exclusiva ya estaba en curso.
        """
        with self._candado:
            if accion is not None:
                if accion in self._en_curso:
                    return False
                self._en_curso.add(accion)
            self._pendientes += 1

        def trabajo() -> None:
            entregar: Callable[[], None]
            try:
                resultado = tarea()
            except Exception as error:           # cualquier error se lleva a la ventana
                entregar = functools.partial(al_fallar, error)
            else:
                entregar = functools.partial(al_terminar, resultado)
            self._listos.put((accion, entregar))

        self._hilo.submit(trabajo)
        return True

    def procesar_pendientes(self) -> int:
        """Entrega los resultados listos. Se llama SOLO desde el hilo de la ventana."""
        entregados = 0
        while True:
            try:
                accion, entregar = self._listos.get_nowait()
            except queue.Empty:
                return entregados
            with self._candado:
                self._pendientes -= 1
                if accion is not None:
                    self._en_curso.discard(accion)
            entregar()
            entregados += 1

    def cerrar(self) -> None:
        self._hilo.shutdown(wait=True)


# ============================================================
# Formatos (estilo colombiano: punto de miles, coma decimal)
# ============================================================

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

NOMBRE_CATEGORIA = {
    Categoria.MEDICO: "Médico", Categoria.VIVERES: "Víveres", Categoria.AGUA: "Agua",
    Categoria.REFUGIO: "Refugio", Categoria.RESCATE: "Rescate",
}
UNIDAD_PLURAL = {"unidad": "unidades", "kg": "kg", "litro": "litros", "kit": "kits"}
NOMBRE_URGENCIA = {Urgencia.CRITICA: "Crítica", Urgencia.ALTA: "Alta",
                   Urgencia.MEDIA: "Media", Urgencia.BAJA: "Baja"}
NOMBRE_ESTADO = {EstadoLote.DISPONIBLE: "Disponible", EstadoLote.ASIGNADO: "Asignado",
                 EstadoLote.DESPACHADO: "Despachado", EstadoLote.DESCARTADO: "Descartado"}


def numero(n: float, decimales: int = 0) -> str:
    texto = f"{n:,.{decimales}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def cantidad(n: int, categoria: Categoria) -> str:
    return f"{numero(n)} {UNIDAD_PLURAL[categoria.unidad]}"


def fecha_corta(f: date | None) -> str:
    return "No vence" if f is None else f"{f.day} {MESES[f.month - 1]} {f.year}"


# ============================================================
# 2. Formulario de ingreso
# ============================================================

CAMPOS_INGRESO = ("donante_id", "centro_id", "categoria", "descripcion", "cantidad", "peso_kg",
                  "volumen_m3", "fecha_ingreso", "fecha_caducidad", "requiere_frio")


@dataclass(frozen=True)
class ValidacionIngreso:
    errores: dict[str, str]              # campo → mensaje; vacío si todo está bien
    datos: dict[str, Any] | None         # argumentos listos para registrar_lote

    @property
    def valida(self) -> bool:
        return not self.errores


def _primera_mayuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


# ============================================================
# 3. Datos que muestra cada panel
# ============================================================

@dataclass(frozen=True)
class Opcion:
    id: str
    etiqueta: str


@dataclass(frozen=True)
class Indicador:
    titulo: str
    valor: str
    detalle: str
    tono: str                            # "neutro", "critico", "alerta" u "ok"


@dataclass(frozen=True)
class Cobertura:
    categoria: Categoria
    necesidad: int
    cubierto: int
    disponible: int

    @property
    def fraccion(self) -> float:
        return min(1.0, self.cubierto / self.necesidad) if self.necesidad else 1.0


@dataclass(frozen=True)
class Resumen:
    indicadores: list[Indicador]
    coberturas: list[Cobertura]
    atender_primero: list[Alerta]


@dataclass(frozen=True)
class FiltrosInventario:
    texto: str = ""
    categoria: Categoria | None = None
    centro_id: str | None = None
    estado: EstadoLote | None = None
    vence_en_dias: int | None = None


@dataclass(frozen=True)
class Fila:
    """Una fila de tabla: los textos de cada columna, una etiqueta de estilo
    y, por columna, el valor por el que se ordena (el texto "1.200 kg" no se
    ordena bien como texto)."""
    id: str
    valores: tuple[str, ...]
    tono: str = ""                       # "critico", "alerta", "ok" o ""
    claves: tuple[Any, ...] = ()

    def clave(self, columna: int) -> Any:
        return self.claves[columna] if self.claves else self.valores[columna].lower()


@dataclass(frozen=True)
class Tabla:
    filas: list[Fila]
    pie: str                             # resumen debajo de la tabla


@dataclass(frozen=True)
class NodoMapa:
    id: str
    nombre: str
    latitud: float
    longitud: float
    es_centro: bool
    urgencia: Urgencia | None
    poblacion: int


@dataclass(frozen=True)
class TramoMapa:
    via: Via
    toneladas: float                     # ayuda asignada o despachada que pasa por aquí


@dataclass(frozen=True)
class Mapa:
    nodos: list[NodoMapa]
    tramos: list[TramoMapa]


@dataclass(frozen=True)
class ResultadoDespacho:
    despachados: list[str]
    errores: list[str]


class Controlador:
    """Puente entre la ventana y el sistema. Sus métodos son los que la
    ventana manda a ejecutar en segundo plano."""

    DIAS_POR_VENCER = 7
    LIMITE_FILAS = 2000                  # más filas no ayudan al operador y vuelven lenta la tabla

    def __init__(self, sistema: SistemaDonaciones, hoy: date, carpeta: Path = CARPETA_DATOS) -> None:
        self.sistema = sistema
        self.hoy = hoy
        self.carpeta = carpeta
        self.ejecutor = Ejecutor()
        self._cambios_sin_guardar = False
        self._candado = threading.Lock()

    @classmethod
    def desde_carpeta(cls, carpeta: Path, hoy: date) -> tuple[Controlador, int]:
        """Carga los CSV. Devuelve el controlador y cuántos registros se rechazaron."""
        carga = cargar_csv(carpeta)
        return cls(SistemaDonaciones(carga.datos), hoy, carpeta), len(carga.rechazos)

    @property
    def cambios_sin_guardar(self) -> bool:
        with self._candado:
            return self._cambios_sin_guardar

    def _marcar_cambios(self) -> None:
        with self._candado:
            self._cambios_sin_guardar = True

    def guardar(self) -> None:
        self.sistema.guardar(self.carpeta)
        with self._candado:
            self._cambios_sin_guardar = False

    # ---------- Opciones de las listas desplegables ----------

    def donantes(self) -> list[Opcion]:
        return [Opcion(d.id, f"{d.nombre} ({d.id})") for d in self.sistema.datos.donantes]

    def centros(self) -> list[Opcion]:
        return [Opcion(c.id, f"{c.nombre} ({c.id})") for c in self.sistema.datos.centros]

    def municipios(self) -> list[Opcion]:
        return [Opcion(m.id, f"{m.nombre} ({m.id})") for m in self.sistema.datos.municipios]

    def nodos(self) -> list[Opcion]:
        return self.centros() + self.municipios()

    def centro_tiene_frio(self, centro_id: str) -> bool:
        return any(c.id == centro_id and c.tiene_frio for c in self.sistema.datos.centros)

    def _nombre(self, nodo_id: str | None) -> str:
        if nodo_id is None:
            return ""
        for c in self.sistema.datos.centros:
            if c.id == nodo_id:
                return c.nombre
        for m in self.sistema.datos.municipios:
            if m.id == nodo_id:
                return m.nombre
        return nodo_id

    # ---------- Resumen ----------

    def resumen(self) -> Resumen:
        s = self.sistema
        balance = {f.categoria: f for f in s.balance()}
        necesidad = {c: 0 for c in Categoria}
        for n in s.datos.necesidades:
            necesidad[n.categoria] += n.cantidad
        alertas = s.alertas_desabastecimiento()
        cubiertas = len(s.datos.necesidades) - len(alertas)
        criticas = [a for a in alertas if a.critica]
        por_vencer = s.proximos_a_vencer(self.hoy, self.DIAS_POR_VENCER)
        disponibles = sum(len(s.buscar_lotes(estado=EstadoLote.DISPONIBLE, categoria=c)) for c in Categoria)

        coberturas = [
            Cobertura(c, necesidad[c], max(0, necesidad[c] - sum(a.faltante for a in alertas
                                                                  if a.categoria is c)),
                      balance[c].disponible)
            for c in Categoria if necesidad[c] > 0
        ]
        indicadores = [
            Indicador("Necesidades cubiertas", f"{cubiertas} de {len(s.datos.necesidades)}",
                      "municipio y categoría", "ok" if not alertas else "neutro"),
            Indicador("Sin stock para cubrir", str(len(criticas)),
                      "necesidades críticas" if criticas else "ninguna", "critico" if criticas else "ok"),
            Indicador(f"Vencen en {self.DIAS_POR_VENCER} días", str(len(por_vencer)),
                      "lotes disponibles", "alerta" if por_vencer else "ok"),
            Indicador("Lotes disponibles", numero(disponibles),
                      f"en {len(s.datos.centros)} centros de acopio", "neutro"),
        ]
        return Resumen(indicadores, coberturas, alertas[:6])

    # ---------- Inventario ----------

    def inventario(self, filtros: FiltrosInventario) -> Tabla:
        vence_hasta = None
        if filtros.vence_en_dias is not None:
            vence_hasta = self.hoy + timedelta(days=filtros.vence_en_dias)
        lotes = self.sistema.buscar_lotes(categoria=filtros.categoria, centro_id=filtros.centro_id,
                                          estado=filtros.estado, vence_hasta=vence_hasta)
        texto = filtros.texto.strip().lower()
        if texto:
            lotes = [l for l in lotes if texto in l.id.lower() or texto in l.descripcion.lower()]

        filas = [self._fila_lote(l) for l in lotes[:self.LIMITE_FILAS]]
        toneladas = sum(l.peso_kg for l in lotes) / 1000
        pie = f"{numero(len(lotes))} lotes, {numero(toneladas, 1)} toneladas"
        if len(lotes) > self.LIMITE_FILAS:
            pie += f". Se muestran los primeros {numero(self.LIMITE_FILAS)}: use los filtros para acotar."
        return Tabla(filas, pie)

    def _fila_lote(self, l: Lote) -> Fila:
        dias = l.dias_para_vencer(self.hoy)
        tono = ""
        if l.estado is EstadoLote.DISPONIBLE and dias is not None:
            tono = "critico" if dias <= 0 else "alerta" if dias <= self.DIAS_POR_VENCER else ""
        return Fila(l.id, (
            l.id, NOMBRE_CATEGORIA[l.categoria], l.descripcion, cantidad(l.cantidad, l.categoria),
            self._nombre(l.centro_id), fecha_corta(l.fecha_caducidad),
            "" if dias is None else ("Vencido" if dias <= 0 else f"{dias} días"),
            NOMBRE_ESTADO[l.estado], self._nombre(l.municipio_destino_id),
        ), tono, (
            l.id, l.categoria.value, l.descripcion.lower(), l.cantidad, self._nombre(l.centro_id),
            l.fecha_caducidad or date.max, 10**6 if dias is None else dias, l.estado.value,
            self._nombre(l.municipio_destino_id),
        ))

    def inventario_por_centro(self) -> Tabla:
        filas = []
        for c in self.sistema.datos.centros:
            stock = self.sistema.inventario_centro(c.id)
            filas.append(Fila(c.id, (c.nombre, *(numero(stock[k]) for k in Categoria),
                                     "Sí" if c.tiene_frio else "No"), "",
                              (c.nombre, *(stock[k] for k in Categoria), c.tiene_frio)))
        return Tabla(filas, "Cantidades disponibles. Agua en litros, víveres en kg, "
                            "médico en unidades, refugio y rescate en kits.")

    # ---------- Registro de ingresos ----------

    def validar_ingreso(self, valores: Mapping[str, object]) -> ValidacionIngreso:
        """Revisa el formulario y devuelve TODOS los errores a la vez.

        Primero convierte cada campo por separado (un error no impide
        revisar los demás). Si todos se pueden convertir, pide al sistema
        que valide el lote completo con las reglas del modelo y de
        integridad: así el formulario aplica exactamente las mismas reglas
        que la carga de archivos.
        """
        errores: dict[str, str] = {}

        def tomar(campo: str, convertir: Callable[[Mapping[str, object], str], T]) -> T | None:
            try:
                return convertir(valores, campo)
            except ErrorValidacion as e:
                errores[campo] = _primera_mayuscula(e.mensaje)
                return None

        datos: dict[str, Any] = {
            "donante_id": tomar("donante_id", campo_texto),
            "centro_id": tomar("centro_id", campo_texto),
            "categoria": tomar("categoria", lambda r, c: campo_enum(r, c, Categoria)),
            "descripcion": tomar("descripcion", campo_texto),
            "cantidad": tomar("cantidad", campo_entero),
            "peso_kg": tomar("peso_kg", campo_real),
            "volumen_m3": tomar("volumen_m3", campo_real),
            "fecha_ingreso": tomar("fecha_ingreso", campo_fecha),
            "fecha_caducidad": tomar("fecha_caducidad", campo_fecha_opcional),
            "requiere_frio": tomar("requiere_frio", campo_booleano),
        }
        if errores:
            return ValidacionIngreso(errores, None)
        try:
            self.sistema.validar_nuevo_lote(**datos)
        except ErrorValidacion as e:
            return ValidacionIngreso({e.campo: _primera_mayuscula(e.mensaje)}, None)
        return ValidacionIngreso({}, datos)

    def registrar_ingreso(self, valores: Mapping[str, object]) -> Lote:
        """Lanza ErrorFormulario con todos los errores si algo no es válido."""
        validacion = self.validar_ingreso(valores)
        if validacion.datos is None:
            raise ErrorFormulario(validacion.errores)
        lote = self.sistema.registrar_lote(**validacion.datos)
        self._marcar_cambios()
        return lote

    # ---------- Alertas y despacho ----------

    def alertas(self) -> Tabla:
        filas = [
            Fila(f"{a.municipio.id}/{a.categoria.value}", (
                "Sin stock" if a.critica else "Pendiente",
                a.municipio.nombre, NOMBRE_URGENCIA[a.municipio.urgencia],
                NOMBRE_CATEGORIA[a.categoria], cantidad(a.faltante, a.categoria),
                f"{round(100 * a.cubierto / a.necesidad)} %",
            ), "critico" if a.critica else "alerta",
                (not a.critica, a.municipio.nombre, a.municipio.urgencia, a.categoria.value,
                 a.faltante, a.cubierto / a.necesidad))
            for a in self.sistema.alertas_desabastecimiento()
        ]
        criticas = sum(1 for f in filas if f.tono == "critico")
        pie = (f"{len(filas)} necesidades sin cubrir, {criticas} sin stock para cubrirlas"
               if filas else "Todas las necesidades están cubiertas.")
        return Tabla(filas, pie)

    def en_riesgo(self, cuantas: int = 5) -> Tabla:
        filas = [
            Fila(f"{a.municipio.id}/{a.categoria.value}", (
                a.municipio.nombre, NOMBRE_CATEGORIA[a.categoria], cantidad(a.faltante, a.categoria)),
                "", (a.municipio.nombre, a.categoria.value, a.faltante))
            for a in self.sistema.solicitudes_en_riesgo(self.hoy, cuantas)
        ]
        pie = ("Las de menor prioridad en categorías sin stock suficiente: candidatas a "
               "comprarse con aportes económicos." if filas else "No hay categorías con déficit.")
        return Tabla(filas, pie)

    def por_despachar(self) -> Tabla:
        lotes = self.sistema.buscar_lotes(estado=EstadoLote.ASIGNADO)
        filas = [Fila(l.id, (l.id, NOMBRE_CATEGORIA[l.categoria], cantidad(l.cantidad, l.categoria),
                             self._nombre(l.centro_id), self._nombre(l.municipio_destino_id)),
                     "", (l.id, l.categoria.value, l.cantidad, self._nombre(l.centro_id),
                          self._nombre(l.municipio_destino_id)))
                 for l in lotes[:self.LIMITE_FILAS]]
        return Tabla(filas, f"{numero(len(lotes))} lotes asignados esperan despacho")

    def asignar_automaticamente(self) -> int:
        hechas = self.sistema.asignar_automaticamente(self.hoy)
        if hechas:
            self._marcar_cambios()
        return len(hechas)

    def descartar_vencidos(self) -> int:
        descartados = self.sistema.descartar_vencidos(self.hoy)
        if descartados:
            self._marcar_cambios()
        return len(descartados)

    def despachar(self, lote_ids: list[str]) -> ResultadoDespacho:
        """Despacha varios lotes. Si uno falla, los demás igual se despachan."""
        hechos, errores = [], []
        for lote_id in lote_ids:
            try:
                self.sistema.despachar(lote_id)
                hechos.append(lote_id)
            except ErrorOperacion as e:
                errores.append(str(e))
        if hechos:
            self._marcar_cambios()
        return ResultadoDespacho(hechos, errores)

    # ---------- Red de distribución ----------

    def mapa(self) -> Mapa:
        """Nodos, vías y cuántas toneladas de ayuda asignada pasan por cada vía.

        La ayuda de un centro a un municipio se reparte por la ruta más
        rápida entre ellos (Dijkstra por tiempo); se suma el peso en cada
        vía de esa ruta. Se usan toneladas porque es la única medida común
        a todas las categorías.
        """
        datos = self.sistema.datos
        nodos = [NodoMapa(c.id, c.nombre, c.latitud, c.longitud, True, None, 0) for c in datos.centros]
        nodos += [NodoMapa(m.id, m.nombre, m.latitud, m.longitud, False, m.urgencia, m.poblacion_afectada)
                  for m in datos.municipios]

        por_par: dict[tuple[str, str], float] = {}
        for l in datos.lotes:
            if l.municipio_destino_id is not None:
                par = (l.centro_id, l.municipio_destino_id)
                por_par[par] = por_par.get(par, 0.0) + l.peso_kg / 1000

        por_via: dict[tuple[str, str], float] = {}
        for (centro, municipio), toneladas in por_par.items():
            ruta = self.sistema.ruta(centro, municipio, Criterio.TIEMPO)
            if ruta is not None:
                for via in ruta.vias:
                    por_via[via.clave] = por_via.get(via.clave, 0.0) + toneladas
        tramos = [TramoMapa(v, por_via.get(v.clave, 0.0)) for v in datos.vias]
        return Mapa(nodos, tramos)

    def ruta(self, origen: str, destino: str, criterio: Criterio) -> Ruta | None:
        return self.sistema.ruta(origen, destino, criterio)

    def describir_ruta(self, ruta: Ruta | None, criterio: Criterio) -> str:
        if ruta is None:
            return "No hay ruta por carretera: todas las vías posibles están cerradas."
        nombres = " → ".join(self._nombre(n) for n in ruta.nodos)
        if criterio is Criterio.TIEMPO:
            horas = int(ruta.costo)
            minutos = round((ruta.costo - horas) * 60)
            costo = f"{horas} h {minutos} min" if horas else f"{minutos} min"
        else:
            costo = f"{numero(ruta.costo, 1)} km"
        restringidas = sum(1 for v in ruta.vias if v.estado is EstadoVia.RESTRINGIDA)
        aviso = f" Incluye {restringidas} tramo(s) restringido(s)." if restringidas else ""
        return f"{nombres}\n{costo}, {len(ruta.vias)} tramo(s).{aviso}"

    def describir_municipio(self, municipio_id: str) -> str:
        m = next((x for x in self.sistema.datos.municipios if x.id == municipio_id), None)
        if m is None:
            return self._nombre(municipio_id)
        lineas = [f"{m.nombre}, urgencia {NOMBRE_URGENCIA[m.urgencia].lower()}",
                  f"{numero(m.poblacion_afectada)} personas afectadas", ""]
        pendientes = {a.categoria: a for a in self.sistema.alertas_desabastecimiento()
                      if a.municipio.id == municipio_id}
        for n in self.sistema.datos.necesidades:
            if n.municipio_id != municipio_id:
                continue
            alerta = pendientes.get(n.categoria)
            if alerta is None:
                lineas.append(f"{NOMBRE_CATEGORIA[n.categoria]}: cubierto")
            else:
                lineas.append(f"{NOMBRE_CATEGORIA[n.categoria]}: faltan {cantidad(alerta.faltante, n.categoria)}")
        return "\n".join(lineas)


    def describir_centro(self, centro_id: str) -> str:
        c = next((x for x in self.sistema.datos.centros if x.id == centro_id), None)
        if c is None:
            return self._nombre(centro_id)
        tipo = c.tipo.name.replace("_", " ").capitalize()
        lineas = [c.nombre, f"{tipo}, {numero(c.capacidad_m3)} m³"
                  + (", con cadena de frío" if c.tiene_frio else ", sin cadena de frío"), "",
                  "Disponible:"]
        stock = self.sistema.inventario_centro(centro_id)
        lineas += [f"  {NOMBRE_CATEGORIA[k]}: {cantidad(v, k)}" for k, v in stock.items()]
        return "\n".join(lineas)


class ErrorFormulario(Exception):
    """El formulario tiene errores. `errores` dice cuáles, campo por campo."""

    def __init__(self, errores: dict[str, str]) -> None:
        super().__init__(", ".join(f"{c}: {m}" for c, m in errores.items()))
        self.errores = errores


def escala_flujo(toneladas: float, maximo: float) -> float:
    """Grosor relativo (0 a 1) de una vía según su flujo. Raíz cuadrada: así
    las vías con poco flujo se siguen viendo."""
    return math.sqrt(toneladas / maximo) if maximo > 0 else 0.0
