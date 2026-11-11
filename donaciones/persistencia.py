"""
persistencia.py — Leer y escribir los datos en CSV y JSON.

Contenido, en el orden en que se usa al cargar:
  1. Conversión: valores crudos (texto de CSV o valores de JSON) → tipos.
  2. Esquemas: columnas de cada entidad y cómo construirla.
  3. Reglas entre entidades: referencias, fechas frente al sismo, frío.
  4. Lectura de CSV y JSON.
  5. Escritura segura.

Dos tipos de problema se tratan distinto:

  * ErrorArchivo: el archivo COMPLETO no sirve (no existe, no es UTF-8,
    le faltan columnas, el JSON está roto). Se lanza como excepción
    porque no hay nada que rescatar.

  * Rechazo: UN registro está mal (un número con letras, una fecha que
    no existe, un donante inexistente). Se anota con su línea y se
    sigue con los demás: un error en la fila 812 no debe impedir cargar
    las otras 1.499.

Uso:  python -m donaciones.persistencia [carpeta]   valida los CSV
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TextIO, TypeVar

from .modelo import (
    FECHA_EVENTO, AporteEconomico, Categoria, CentroAcopio, Donante, ErrorValidacion,
    EstadoLote, EstadoVia, Lote, Municipio, Necesidad, TipoCentro, TipoDonante, Urgencia, Via,
)

T = TypeVar("T")
E = TypeVar("E", bound=Enum)
Registro = Mapping[str, object]

CARPETA_DATOS = Path("datos")
FORMATO_JSON = "donaciones-v1"


class ErrorArchivo(Exception):
    """El archivo completo no se puede usar."""


@dataclass(frozen=True)
class Rechazo:
    archivo: str
    linea: int        # en CSV: línea del archivo (1 = encabezado); en JSON: posición en la lista
    campo: str
    mensaje: str

    def __str__(self) -> str:
        return f"{self.archivo}, línea {self.linea}: {self.campo}: {self.mensaje}"


# ============================================================
# 1. Conversión de valores crudos
#
# Un valor crudo puede venir de un CSV (siempre texto: "12", "SI", "")
# o de un JSON (ya tipado: 12, true, null). Estas funciones aceptan
# ambos, así CSV y JSON usan exactamente el mismo código.
#
# Aquí solo se CONVIERTE. Las reglas de negocio (cantidad > 0, fechas
# en orden...) están en modelo.py.
# ============================================================

_ENTERO = re.compile(r"[+-]?\d+")
_REAL = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERDADERO = {"SI", "SÍ"}
_FALSO = {"NO"}


def _crudo(registro: Registro, campo: str) -> object:
    """Valor del campo, sin espacios sobrantes si es texto."""
    if campo not in registro:
        raise ErrorValidacion(campo, "falta el campo")
    valor = registro[campo]
    return valor.strip() if isinstance(valor, str) else valor


def _es_vacio(valor: object) -> bool:
    return valor is None or valor == ""


def _obligatorio(registro: Registro, campo: str) -> object:
    valor = _crudo(registro, campo)
    if _es_vacio(valor):
        raise ErrorValidacion(campo, "es obligatorio y está vacío")
    return valor


def campo_texto(registro: Registro, campo: str) -> str:
    valor = _obligatorio(registro, campo)
    if not isinstance(valor, str):
        raise ErrorValidacion(campo, f"debe ser texto, se recibió {type(valor).__name__}")
    return valor


def campo_texto_opcional(registro: Registro, campo: str) -> str | None:
    return None if _es_vacio(_crudo(registro, campo)) else campo_texto(registro, campo)


def campo_entero(registro: Registro, campo: str) -> int:
    valor = _obligatorio(registro, campo)
    if isinstance(valor, bool):                       # True no es 1
        raise ErrorValidacion(campo, "debe ser un número entero")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and _ENTERO.fullmatch(valor):
        return int(valor)
    raise ErrorValidacion(campo, f"'{valor}' no es un número entero")


def campo_real(registro: Registro, campo: str) -> float:
    valor = _obligatorio(registro, campo)
    if isinstance(valor, bool):
        raise ErrorValidacion(campo, "debe ser un número")
    if isinstance(valor, (int, float)):
        numero = float(valor)
    elif isinstance(valor, str) and _REAL.fullmatch(valor):
        # El patrón ya excluye "nan", "inf" y la coma decimal "3,5"
        numero = float(valor)
    else:
        raise ErrorValidacion(campo, f"'{valor}' no es un número (use punto decimal)")
    if not math.isfinite(numero):
        raise ErrorValidacion(campo, "debe ser un número finito")
    return numero


def campo_fecha(registro: Registro, campo: str) -> date:
    valor = _obligatorio(registro, campo)
    # Se exige AAAA-MM-DD exacto: "03/11/2026" es ambiguo (¿día o mes primero?)
    if not isinstance(valor, str) or not _FECHA.fullmatch(valor):
        raise ErrorValidacion(campo, f"'{valor}' no tiene el formato AAAA-MM-DD")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorValidacion(campo, f"'{valor}' no es una fecha que exista") from None


def campo_fecha_opcional(registro: Registro, campo: str) -> date | None:
    return None if _es_vacio(_crudo(registro, campo)) else campo_fecha(registro, campo)


def campo_booleano(registro: Registro, campo: str) -> bool:
    valor = _obligatorio(registro, campo)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        if valor.upper() in _VERDADERO:
            return True
        if valor.upper() in _FALSO:
            return False
    raise ErrorValidacion(campo, f"'{valor}' no es válido, use SI o NO")


def campo_enum(registro: Registro, campo: str, tipo: type[E]) -> E:
    valor = _obligatorio(registro, campo)
    if isinstance(valor, str):
        miembro = tipo.__members__.get(valor.upper())
        if miembro is not None:
            return miembro
    opciones = ", ".join(tipo.__members__)
    raise ErrorValidacion(campo, f"'{valor}' no es válido, use uno de: {opciones}")


# ============================================================
# 2. Esquemas: cómo se ve cada entidad "por fuera"
#
# Un Esquema reúne lo que la lectura y la escritura necesitan saber de
# una entidad. Así esas funciones se escriben UNA sola vez para las siete.
# ============================================================

@dataclass(frozen=True)
class Esquema(Generic[T]):
    nombre: str                                   # nombre del archivo, sin extensión
    columnas: tuple[str, ...]
    desde_registro: Callable[[Registro], T]       # registro crudo → entidad (valida)
    clave: Callable[[T], Hashable]                # para detectar duplicados

    def a_registro(self, entidad: T) -> dict[str, object]:
        """Entidad → registro con tipos que JSON entiende."""
        return {c: _exportable(getattr(entidad, c)) for c in self.columnas}


def _exportable(valor: object) -> object:
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Enum):
        return valor.name
    return valor


def _centro(r: Registro) -> CentroAcopio:
    return CentroAcopio(
        id=campo_texto(r, "id"),
        nombre=campo_texto(r, "nombre"),
        tipo=campo_enum(r, "tipo", TipoCentro),
        ciudad=campo_texto(r, "ciudad"),
        latitud=campo_real(r, "latitud"),
        longitud=campo_real(r, "longitud"),
        capacidad_m3=campo_real(r, "capacidad_m3"),
        tiene_frio=campo_booleano(r, "tiene_frio"),
    )


def _municipio(r: Registro) -> Municipio:
    return Municipio(
        id=campo_texto(r, "id"),
        nombre=campo_texto(r, "nombre"),
        departamento=campo_texto(r, "departamento"),
        latitud=campo_real(r, "latitud"),
        longitud=campo_real(r, "longitud"),
        poblacion_afectada=campo_entero(r, "poblacion_afectada"),
        urgencia=campo_enum(r, "urgencia", Urgencia),
    )


def _donante(r: Registro) -> Donante:
    return Donante(
        id=campo_texto(r, "id"),
        nombre=campo_texto(r, "nombre"),
        tipo=campo_enum(r, "tipo", TipoDonante),
        pais=campo_texto(r, "pais"),
    )


def _necesidad(r: Registro) -> Necesidad:
    return Necesidad(
        municipio_id=campo_texto(r, "municipio_id"),
        categoria=campo_enum(r, "categoria", Categoria),
        cantidad=campo_entero(r, "cantidad"),
    )


def _lote(r: Registro) -> Lote:
    return Lote(
        id=campo_texto(r, "id"),
        donante_id=campo_texto(r, "donante_id"),
        centro_id=campo_texto(r, "centro_id"),
        categoria=campo_enum(r, "categoria", Categoria),
        descripcion=campo_texto(r, "descripcion"),
        cantidad=campo_entero(r, "cantidad"),
        peso_kg=campo_real(r, "peso_kg"),
        volumen_m3=campo_real(r, "volumen_m3"),
        fecha_ingreso=campo_fecha(r, "fecha_ingreso"),
        fecha_caducidad=campo_fecha_opcional(r, "fecha_caducidad"),
        requiere_frio=campo_booleano(r, "requiere_frio"),
        estado=campo_enum(r, "estado", EstadoLote),
        municipio_destino_id=campo_texto_opcional(r, "municipio_destino_id"),
    )


def _aporte(r: Registro) -> AporteEconomico:
    return AporteEconomico(
        id=campo_texto(r, "id"),
        donante_id=campo_texto(r, "donante_id"),
        monto_cop=campo_entero(r, "monto_cop"),
        fecha=campo_fecha(r, "fecha"),
        municipio_destino_id=campo_texto_opcional(r, "municipio_destino_id"),
    )


def _via(r: Registro) -> Via:
    return Via(
        origen_id=campo_texto(r, "origen_id"),
        destino_id=campo_texto(r, "destino_id"),
        distancia_km=campo_real(r, "distancia_km"),
        tiempo_h=campo_real(r, "tiempo_h"),
        estado=campo_enum(r, "estado", EstadoVia),
    )


# En el ORDEN en que deben cargarse: primero lo que no depende de nada
CENTROS = Esquema[CentroAcopio](
    "centros", ("id", "nombre", "tipo", "ciudad", "latitud", "longitud", "capacidad_m3", "tiene_frio"),
    _centro, lambda e: e.id)
MUNICIPIOS = Esquema[Municipio](
    "municipios", ("id", "nombre", "departamento", "latitud", "longitud", "poblacion_afectada", "urgencia"),
    _municipio, lambda e: e.id)
DONANTES = Esquema[Donante](
    "donantes", ("id", "nombre", "tipo", "pais"),
    _donante, lambda e: e.id)
NECESIDADES = Esquema[Necesidad](
    "necesidades", ("municipio_id", "categoria", "cantidad"),
    _necesidad, lambda e: e.clave)
LOTES = Esquema[Lote](
    "lotes", ("id", "donante_id", "centro_id", "categoria", "descripcion", "cantidad", "peso_kg",
              "volumen_m3", "fecha_ingreso", "fecha_caducidad", "requiere_frio", "estado",
              "municipio_destino_id"),
    _lote, lambda e: e.id)
APORTES = Esquema[AporteEconomico](
    "aportes", ("id", "donante_id", "monto_cop", "fecha", "municipio_destino_id"),
    _aporte, lambda e: e.id)
VIAS = Esquema[Via](
    "vias", ("origen_id", "destino_id", "distancia_km", "tiempo_h", "estado"),
    _via, lambda e: e.clave)


@dataclass
class Datos:
    """Todo el conjunto de datos en memoria.

    En la Fase 1 son listas simples. En la Fase 3 se indexan en las
    estructuras de datos (tabla hash, árbol AVL, montículo, grafo).
    """
    centros: list[CentroAcopio] = field(default_factory=list)
    municipios: list[Municipio] = field(default_factory=list)
    donantes: list[Donante] = field(default_factory=list)
    necesidades: list[Necesidad] = field(default_factory=list)
    lotes: list[Lote] = field(default_factory=list)
    aportes: list[AporteEconomico] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)

    def colecciones(self) -> list[tuple[Esquema[Any], Sequence[Any]]]:
        """Cada esquema con su lista, en orden de carga."""
        return [
            (CENTROS, self.centros), (MUNICIPIOS, self.municipios), (DONANTES, self.donantes),
            (NECESIDADES, self.necesidades), (LOTES, self.lotes), (APORTES, self.aportes),
            (VIAS, self.vias),
        ]


@dataclass
class Carga:
    datos: Datos
    rechazos: list[Rechazo]


# ============================================================
# 3. Reglas entre entidades
#
# Un registro puede ser válido por sí solo (modelo.py lo aceptó) y aun
# así ser incoherente con el resto: un lote de un donante que no existe,
# un medicamento que vence antes del sismo, una vacuna guardada en un
# centro sin nevera. Estas reglas necesitan lo que ya se cargó.
# ============================================================

@dataclass
class Contexto:
    fecha_evento: date
    centros: dict[str, CentroAcopio] = field(default_factory=dict)
    municipios: set[str] = field(default_factory=set)
    donantes: set[str] = field(default_factory=set)


def _existe(campo: str, identificador: str, conjunto: set[str] | dict[str, CentroAcopio],
            que: str) -> None:
    if identificador not in conjunto:
        raise ErrorValidacion(campo, f"{que} {identificador} no existe")


def validar_necesidad(n: Necesidad, ctx: Contexto) -> None:
    _existe("municipio_id", n.municipio_id, ctx.municipios, "el municipio")


def validar_lote(lote: Lote, ctx: Contexto) -> None:
    _existe("donante_id", lote.donante_id, ctx.donantes, "el donante")
    _existe("centro_id", lote.centro_id, ctx.centros, "el centro de acopio")

    # Primero la caducidad: un producto vencido antes del sismo es el error
    # más grave, y si se revisara el ingreso primero este mensaje no saldría nunca.
    if lote.fecha_caducidad is not None and lote.fecha_caducidad <= ctx.fecha_evento:
        raise ErrorValidacion("fecha_caducidad",
                              f"{lote.fecha_caducidad} no es posterior al sismo ({ctx.fecha_evento})")
    if lote.fecha_ingreso < ctx.fecha_evento:
        raise ErrorValidacion("fecha_ingreso",
                              f"{lote.fecha_ingreso} es anterior al sismo ({ctx.fecha_evento})")

    if lote.municipio_destino_id is not None:
        _existe("municipio_destino_id", lote.municipio_destino_id, ctx.municipios, "el municipio")

    centro = ctx.centros[lote.centro_id]
    if lote.requiere_frio and not centro.tiene_frio:
        raise ErrorValidacion("centro_id",
                              f"el lote requiere frío y {centro.nombre} no tiene cadena de frío")


def validar_aporte(a: AporteEconomico, ctx: Contexto) -> None:
    _existe("donante_id", a.donante_id, ctx.donantes, "el donante")
    if a.fecha < ctx.fecha_evento:
        raise ErrorValidacion("fecha", f"{a.fecha} es anterior al sismo ({ctx.fecha_evento})")
    if a.municipio_destino_id is not None:
        _existe("municipio_destino_id", a.municipio_destino_id, ctx.municipios, "el municipio")


def validar_via(v: Via, ctx: Contexto) -> None:
    for campo, nodo in (("origen_id", v.origen_id), ("destino_id", v.destino_id)):
        if nodo not in ctx.centros and nodo not in ctx.municipios:
            raise ErrorValidacion(campo, f"el nodo {nodo} no existe")


# ============================================================
# 4. Lectura
#
# Dos pasos:
#   a. Leer: cada fila → entidad (conversión + reglas internas del modelo).
#   b. Integrar: reglas entre entidades, en orden de dependencias.
# ============================================================

@dataclass
class _Lectura(Generic[T]):
    """Resultado de leer un archivo: entidades válidas (con su línea) y rechazos."""
    archivo: str
    esquema: Esquema[T]
    filas: list[tuple[int, T]] = field(default_factory=list)
    rechazos: list[Rechazo] = field(default_factory=list)
    _claves: set[Hashable] = field(default_factory=set)

    def rechazar(self, linea: int, campo: str, mensaje: str) -> None:
        self.rechazos.append(Rechazo(self.archivo, linea, campo, mensaje))

    def agregar(self, linea: int, registro: Registro) -> None:
        try:
            entidad = self.esquema.desde_registro(registro)
        except ErrorValidacion as e:
            self.rechazar(linea, e.campo, e.mensaje)
            return
        clave = self.esquema.clave(entidad)
        if clave in self._claves:
            self.rechazar(linea, "clave", f"{clave} está repetido")
            return
        self._claves.add(clave)
        self.filas.append((linea, entidad))


def _leer_csv(ruta: Path, esquema: Esquema[T]) -> _Lectura[T]:
    lectura = _Lectura(ruta.name, esquema)
    try:
        # utf-8-sig: acepta el BOM que agrega Excel al guardar como CSV UTF-8
        with ruta.open(encoding="utf-8-sig", newline="") as f:
            lector = csv.DictReader(f)
            if lector.fieldnames is None:
                raise ErrorArchivo(f"{ruta.name} está vacío: no tiene ni encabezado")
            faltan = [c for c in esquema.columnas if c not in lector.fieldnames]
            if faltan:
                raise ErrorArchivo(f"{ruta.name}: faltan las columnas {', '.join(faltan)}")

            for fila in lector:
                linea = lector.line_num
                # DictReader guarda las columnas sobrantes bajo la llave None
                # y llena con None las que faltan
                if None in fila:
                    lectura.rechazar(linea, "fila", "tiene más valores que columnas el encabezado")
                elif any(v is None for v in fila.values()):
                    lectura.rechazar(linea, "fila", "tiene menos valores que columnas el encabezado")
                else:
                    lectura.agregar(linea, fila)
    except FileNotFoundError:
        raise ErrorArchivo(f"No existe el archivo {ruta}") from None
    except UnicodeDecodeError:
        raise ErrorArchivo(f"{ruta.name} no está guardado en UTF-8") from None
    except csv.Error as e:
        raise ErrorArchivo(f"{ruta.name} tiene un formato CSV inválido: {e}") from None
    except OSError as e:
        raise ErrorArchivo(f"No se pudo leer {ruta}: {e.strerror}") from None
    return lectura


def _leer_documento_json(ruta: Path) -> dict[str, object]:
    try:
        with ruta.open(encoding="utf-8") as f:
            documento = json.load(f)
    except FileNotFoundError:
        raise ErrorArchivo(f"No existe el archivo {ruta}") from None
    except UnicodeDecodeError:
        raise ErrorArchivo(f"{ruta.name} no está guardado en UTF-8") from None
    except json.JSONDecodeError as e:
        raise ErrorArchivo(f"{ruta.name} no es un JSON válido (línea {e.lineno}: {e.msg})") from None
    except OSError as e:
        raise ErrorArchivo(f"No se pudo leer {ruta}: {e.strerror}") from None

    if not isinstance(documento, dict) or documento.get("formato") != FORMATO_JSON:
        raise ErrorArchivo(f"{ruta.name} no es un archivo de este sistema (formato {FORMATO_JSON})")
    return documento


def _leer_coleccion_json(documento: dict[str, object], archivo: str,
                         esquema: Esquema[T]) -> _Lectura[T]:
    lectura = _Lectura(f"{archivo}:{esquema.nombre}", esquema)
    lista = documento.get(esquema.nombre)
    if not isinstance(lista, list):
        raise ErrorArchivo(f"{archivo}: '{esquema.nombre}' falta o no es una lista")
    for posicion, elemento in enumerate(lista, start=1):
        if isinstance(elemento, dict):
            lectura.agregar(posicion, elemento)
        else:
            lectura.rechazar(posicion, "registro", "no es un objeto JSON")
    return lectura


def _filtrar(lectura: _Lectura[T], regla: Callable[[T, Contexto], None] | None,
             ctx: Contexto, rechazos: list[Rechazo]) -> list[T]:
    rechazos.extend(lectura.rechazos)
    aceptadas: list[T] = []
    for linea, entidad in lectura.filas:
        if regla is not None:
            try:
                regla(entidad, ctx)
            except ErrorValidacion as e:
                rechazos.append(Rechazo(lectura.archivo, linea, e.campo, e.mensaje))
                continue
        aceptadas.append(entidad)
    return aceptadas


def _integrar(leer: Callable[[Esquema[Any]], _Lectura[Any]], fecha_evento: date) -> Carga:
    """Lee cada colección en orden de dependencias y aplica sus reglas.

    Como cada colección se valida contra lo YA aceptado, un rechazo se
    propaga: si un donante se rechaza, sus lotes también.
    """
    ctx = Contexto(fecha_evento)
    rechazos: list[Rechazo] = []
    d = Datos()

    d.centros = _filtrar(leer(CENTROS), None, ctx, rechazos)
    ctx.centros = {c.id: c for c in d.centros}
    d.municipios = _filtrar(leer(MUNICIPIOS), None, ctx, rechazos)
    ctx.municipios = {m.id for m in d.municipios}
    d.donantes = _filtrar(leer(DONANTES), None, ctx, rechazos)
    ctx.donantes = {x.id for x in d.donantes}

    d.necesidades = _filtrar(leer(NECESIDADES), validar_necesidad, ctx, rechazos)
    d.lotes = _filtrar(leer(LOTES), validar_lote, ctx, rechazos)
    d.aportes = _filtrar(leer(APORTES), validar_aporte, ctx, rechazos)
    d.vias = _filtrar(leer(VIAS), validar_via, ctx, rechazos)
    return Carga(d, rechazos)


def cargar_csv(carpeta: Path, fecha_evento: date = FECHA_EVENTO) -> Carga:
    """Carga los siete archivos CSV de una carpeta."""
    return _integrar(lambda e: _leer_csv(carpeta / f"{e.nombre}.csv", e), fecha_evento)


def cargar_json(ruta: Path, fecha_evento: date = FECHA_EVENTO) -> Carga:
    """Carga un archivo JSON con todas las colecciones."""
    documento = _leer_documento_json(ruta)
    return _integrar(lambda e: _leer_coleccion_json(documento, ruta.name, e), fecha_evento)


# ============================================================
# 5. Escritura
# ============================================================

def _celda(valor: object) -> str:
    """Valor exportable → texto de una celda CSV."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "SI" if valor else "NO"
    return str(valor)          # str(float) conserva todos los decimales


def _escribir_atomico(ruta: Path, escribir: Callable[[TextIO], None]) -> None:
    """Escribe en un temporal y lo renombra al final.

    Si algo falla a mitad de camino, el archivo original queda intacto.
    os.replace es atómico tanto en Linux como en Windows.
    """
    temporal = ruta.with_name(ruta.name + ".tmp")

    def limpiar() -> None:
        # Si la carpeta ni siquiera existe, borrar también falla: no importa
        try:
            temporal.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with temporal.open("w", encoding="utf-8", newline="") as f:
            escribir(f)
        os.replace(temporal, ruta)
    except OSError as e:
        limpiar()
        raise ErrorArchivo(f"No se pudo escribir {ruta}: {e.strerror}") from None
    except BaseException:
        limpiar()
        raise


def escribir_csv(ruta: Path, esquema: Esquema[T], entidades: Sequence[T]) -> None:
    def escribir(f: TextIO) -> None:
        escritor = csv.writer(f)
        escritor.writerow(esquema.columnas)
        for e in entidades:
            registro = esquema.a_registro(e)
            escritor.writerow([_celda(registro[c]) for c in esquema.columnas])
    _escribir_atomico(ruta, escribir)


def guardar_csv(carpeta: Path, datos: Datos) -> None:
    for esquema, entidades in datos.colecciones():
        escribir_csv(carpeta / f"{esquema.nombre}.csv", esquema, entidades)


def exportar_json(ruta: Path, datos: Datos, fecha_evento: date = FECHA_EVENTO) -> None:
    documento: dict[str, object] = {"formato": FORMATO_JSON, "fecha_evento": fecha_evento.isoformat()}
    for esquema, entidades in datos.colecciones():
        documento[esquema.nombre] = [esquema.a_registro(e) for e in entidades]

    def escribir(f: TextIO) -> None:
        json.dump(documento, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _escribir_atomico(ruta, escribir)


# ============================================================
# Línea de comandos: validar una carpeta de datos
# ============================================================

MAX_RECHAZOS_MOSTRADOS = 30


def imprimir_resumen(carga: Carga) -> None:
    print(f"{'Colección':<14}{'Registros':>10}")
    print("-" * 24)
    for esquema, entidades in carga.datos.colecciones():
        print(f"{esquema.nombre:<14}{len(entidades):>10}")
    if carga.rechazos:
        print(f"\n{len(carga.rechazos)} registros rechazados:")
        for r in carga.rechazos[:MAX_RECHAZOS_MOSTRADOS]:
            print(f"  {r}")
        if len(carga.rechazos) > MAX_RECHAZOS_MOSTRADOS:
            print(f"  ... y {len(carga.rechazos) - MAX_RECHAZOS_MOSTRADOS} más")
    else:
        print("\nTodos los registros son válidos.")


def main(argv: Sequence[str] | None = None) -> int:
    """Devuelve 0 si todo es válido, 1 si hubo rechazos, 2 si un archivo no sirve."""
    args = list(sys.argv[1:] if argv is None else argv)
    carpeta = Path(args[0]) if args else CARPETA_DATOS
    try:
        carga = cargar_csv(carpeta)
    except ErrorArchivo as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    imprimir_resumen(carga)
    return 1 if carga.rechazos else 0


if __name__ == "__main__":
    sys.exit(main())
