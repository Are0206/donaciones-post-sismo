"""
modelo.py — Entidades del dominio y sus reglas internas.

Cada entidad es una dataclass congelada (frozen=True): una vez creada no
se puede modificar. Si un dato cambia (por ejemplo, el estado de un lote),
se crea una copia nueva con dataclasses.replace(). Así ningún módulo puede
alterar un registro "por debajo" de otro sin que quede rastro.

Las reglas que dependen SOLO del propio registro (cantidades positivas,
fechas en orden, coordenadas dentro de Colombia) se verifican al crearlo,
en __post_init__: un objeto inválido nunca llega a existir.

Las reglas que dependen de OTROS registros (que el donante exista, que la
caducidad sea posterior al sismo) se verifican al cargar, en persistencia.py.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, IntEnum


# Día del sismo. Toda la ayuda debe ingresar desde este día y ningún
# producto puede llegar ya vencido respecto a él.
FECHA_EVENTO = date(2026, 11, 3)


class ErrorValidacion(ValueError):
    """Un dato no cumple una regla. Dice qué campo falló y por qué."""

    def __init__(self, campo: str, mensaje: str) -> None:
        super().__init__(f"{campo}: {mensaje}")
        self.campo = campo
        self.mensaje = mensaje


# ============================================================
# Enumeraciones: los valores posibles quedan cerrados y con nombre
# ============================================================

class Categoria(Enum):
    MEDICO = "MEDICO"      # insumos médicos y material de triaje
    VIVERES = "VIVERES"    # alimentos no perecederos
    AGUA = "AGUA"          # agua potable
    REFUGIO = "REFUGIO"    # kits de refugio
    RESCATE = "RESCATE"    # herramientas de rescate

    @property
    def unidad(self) -> str:
        """Unidad en la que se mide la cantidad de esta categoría."""
        return UNIDADES[self]

    @property
    def perecedera(self) -> bool:
        """Si sus lotes deben tener fecha de caducidad."""
        return self in CATEGORIAS_PERECEDERAS


UNIDADES: dict[Categoria, str] = {
    Categoria.MEDICO: "unidad",
    Categoria.VIVERES: "kg",
    Categoria.AGUA: "litro",
    Categoria.REFUGIO: "kit",
    Categoria.RESCATE: "kit",
}

CATEGORIAS_PERECEDERAS = frozenset({Categoria.MEDICO, Categoria.VIVERES, Categoria.AGUA})


class TipoDonante(Enum):
    PERSONA = "PERSONA"
    EMPRESA = "EMPRESA"
    ONG = "ONG"
    GOBIERNO = "GOBIERNO"
    INTERNACIONAL = "INTERNACIONAL"


class TipoCentro(Enum):
    AEROPUERTO = "AEROPUERTO"                 # punto de entrada
    PUERTO = "PUERTO"                         # punto de entrada
    ACOPIO_REGIONAL = "ACOPIO_REGIONAL"
    ACOPIO_INTERMEDIO = "ACOPIO_INTERMEDIO"


class Urgencia(IntEnum):
    """Nivel de triaje del municipio.

    Menor número = más urgente. Así, una cola de prioridad de mínimos
    saca primero lo más crítico sin tener que invertir nada.
    """
    CRITICA = 1
    ALTA = 2
    MEDIA = 3
    BAJA = 4


class EstadoLote(Enum):
    DISPONIBLE = "DISPONIBLE"   # en un centro de acopio, sin destino
    ASIGNADO = "ASIGNADO"       # reservado para un municipio
    DESPACHADO = "DESPACHADO"   # ya salió hacia el municipio
    DESCARTADO = "DESCARTADO"   # vencido o dañado


# Ciclo de vida de un lote: a qué estados puede pasar desde cada uno.
# Solo se avanza: un lote asignado nunca vuelve a quedar disponible.
#
#   DISPONIBLE ──asignar──> ASIGNADO ──despachar──> DESPACHADO
#        │
#        └──descartar──> DESCARTADO
TRANSICIONES: dict[EstadoLote, frozenset[EstadoLote]] = {
    EstadoLote.DISPONIBLE: frozenset({EstadoLote.ASIGNADO, EstadoLote.DESCARTADO}),
    EstadoLote.ASIGNADO: frozenset({EstadoLote.DESPACHADO}),
    EstadoLote.DESPACHADO: frozenset(),
    EstadoLote.DESCARTADO: frozenset(),
}

# Estados en los que el lote ya tiene un municipio destino
ESTADOS_CON_DESTINO = frozenset({EstadoLote.ASIGNADO, EstadoLote.DESPACHADO})


class EstadoVia(Enum):
    TRANSITABLE = "TRANSITABLE"
    RESTRINGIDA = "RESTRINGIDA"   # pasa, pero lento (un carril, derrumbes parciales)
    CERRADA = "CERRADA"           # no pasa nada


# ============================================================
# Identificadores: un formato fijo por entidad evita confundir
# el código de un donante con el de un lote.
# ============================================================

PATRON_DONANTE = re.compile(r"DON-\d{4}")
PATRON_LOTE = re.compile(r"LOT-\d{6}")
PATRON_APORTE = re.compile(r"APO-\d{5}")
PATRON_CENTRO = re.compile(r"CA-\d{2}")
PATRON_MUNICIPIO = re.compile(r"MUN-\d{3}")

# Rectángulo aproximado que contiene a Colombia, incluido San Andrés.
LATITUD_MIN, LATITUD_MAX = -4.3, 13.5
LONGITUD_MIN, LONGITUD_MAX = -82.0, -66.8


# ============================================================
# Validadores reutilizables. Revisan el TIPO además del valor:
# Python no impide pasar "5" donde se espera 5, así que se exige aquí.
# ============================================================

def _texto(campo: str, valor: object, maximo: int = 80) -> None:
    if not isinstance(valor, str):
        raise ErrorValidacion(campo, f"debe ser texto, se recibió {type(valor).__name__}")
    if not valor.strip():
        raise ErrorValidacion(campo, "no puede estar vacío")
    if len(valor) > maximo:
        raise ErrorValidacion(campo, f"supera los {maximo} caracteres")


def _identificador(campo: str, valor: object, patron: re.Pattern[str], ejemplo: str) -> None:
    if not isinstance(valor, str) or not patron.fullmatch(valor):
        raise ErrorValidacion(campo, f"'{valor}' no tiene el formato esperado (ej. {ejemplo})")


def _entero(campo: str, valor: object, minimo: int) -> None:
    # bool es subclase de int en Python (True == 1): hay que excluirlo a mano
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorValidacion(campo, f"debe ser un entero, se recibió {type(valor).__name__}")
    if valor < minimo:
        raise ErrorValidacion(campo, f"debe ser mayor o igual a {minimo}, se recibió {valor}")


def _positivo(campo: str, valor: object) -> None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorValidacion(campo, f"debe ser un número, se recibió {type(valor).__name__}")
    if not math.isfinite(valor):
        raise ErrorValidacion(campo, "debe ser un número finito")
    if valor <= 0:
        raise ErrorValidacion(campo, f"debe ser mayor que 0, se recibió {valor}")


def _fecha(campo: str, valor: object) -> None:
    # datetime es subclase de date: se rechaza para no mezclar fechas con horas
    if not isinstance(valor, date) or isinstance(valor, datetime):
        raise ErrorValidacion(campo, f"debe ser una fecha, se recibió {type(valor).__name__}")


def _booleano(campo: str, valor: object) -> None:
    if not isinstance(valor, bool):
        raise ErrorValidacion(campo, f"debe ser verdadero o falso, se recibió {type(valor).__name__}")


def _enumeracion(campo: str, valor: object, tipo: type[Enum]) -> None:
    if not isinstance(valor, tipo):
        raise ErrorValidacion(campo, f"debe ser un {tipo.__name__}")


def _numero_finito(campo: str, valor: object) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ErrorValidacion(campo, "debe ser un número finito")
    return float(valor)


def _coordenadas(latitud: object, longitud: object) -> None:
    lat = _numero_finito("latitud", latitud)
    lon = _numero_finito("longitud", longitud)
    if not LATITUD_MIN <= lat <= LATITUD_MAX:
        raise ErrorValidacion("latitud", f"{lat} está fuera de Colombia")
    if not LONGITUD_MIN <= lon <= LONGITUD_MAX:
        raise ErrorValidacion("longitud", f"{lon} está fuera de Colombia")


def es_nodo_vial(identificador: str) -> bool:
    """Los extremos de una vía pueden ser centros de acopio o municipios."""
    return bool(PATRON_CENTRO.fullmatch(identificador) or PATRON_MUNICIPIO.fullmatch(identificador))


# ============================================================
# Entidades
# ============================================================

@dataclass(frozen=True, slots=True)
class Donante:
    id: str
    nombre: str
    tipo: TipoDonante
    pais: str

    def __post_init__(self) -> None:
        _identificador("id", self.id, PATRON_DONANTE, "DON-0001")
        _texto("nombre", self.nombre)
        _enumeracion("tipo", self.tipo, TipoDonante)
        _texto("pais", self.pais, 40)


@dataclass(frozen=True, slots=True)
class CentroAcopio:
    id: str
    nombre: str
    tipo: TipoCentro
    ciudad: str
    latitud: float
    longitud: float
    capacidad_m3: float
    tiene_frio: bool              # cuenta con cadena de frío

    def __post_init__(self) -> None:
        _identificador("id", self.id, PATRON_CENTRO, "CA-01")
        _texto("nombre", self.nombre)
        _enumeracion("tipo", self.tipo, TipoCentro)
        _texto("ciudad", self.ciudad, 40)
        _coordenadas(self.latitud, self.longitud)
        _positivo("capacidad_m3", self.capacidad_m3)
        _booleano("tiene_frio", self.tiene_frio)

    @property
    def es_punto_de_entrada(self) -> bool:
        return self.tipo in (TipoCentro.AEROPUERTO, TipoCentro.PUERTO)


@dataclass(frozen=True, slots=True)
class Municipio:
    id: str
    nombre: str
    departamento: str
    latitud: float
    longitud: float
    poblacion_afectada: int
    urgencia: Urgencia

    def __post_init__(self) -> None:
        _identificador("id", self.id, PATRON_MUNICIPIO, "MUN-001")
        _texto("nombre", self.nombre, 40)
        _texto("departamento", self.departamento, 40)
        _coordenadas(self.latitud, self.longitud)
        _entero("poblacion_afectada", self.poblacion_afectada, minimo=0)
        _enumeracion("urgencia", self.urgencia, Urgencia)


@dataclass(frozen=True, slots=True)
class Necesidad:
    """Cuánto requiere un municipio de una categoría.

    La llave es compuesta: (municipio_id, categoria). Un municipio tiene
    a lo sumo una necesidad por categoría.
    """
    municipio_id: str
    categoria: Categoria
    cantidad: int                 # en la unidad de la categoría

    def __post_init__(self) -> None:
        _identificador("municipio_id", self.municipio_id, PATRON_MUNICIPIO, "MUN-001")
        _enumeracion("categoria", self.categoria, Categoria)
        _entero("cantidad", self.cantidad, minimo=1)

    @property
    def clave(self) -> tuple[str, Categoria]:
        return (self.municipio_id, self.categoria)


@dataclass(frozen=True, slots=True)
class Lote:
    """Un lote de ayuda en especie, tal como ingresó a un centro de acopio."""
    id: str
    donante_id: str
    centro_id: str                # centro donde ingresó
    categoria: Categoria
    descripcion: str
    cantidad: int                 # en la unidad de la categoría
    peso_kg: float
    volumen_m3: float
    fecha_ingreso: date
    fecha_caducidad: date | None  # None solo en categorías no perecederas
    requiere_frio: bool
    estado: EstadoLote = EstadoLote.DISPONIBLE
    municipio_destino_id: str | None = None   # a dónde va, si ya se asignó

    def __post_init__(self) -> None:
        _identificador("id", self.id, PATRON_LOTE, "LOT-000001")
        _identificador("donante_id", self.donante_id, PATRON_DONANTE, "DON-0001")
        _identificador("centro_id", self.centro_id, PATRON_CENTRO, "CA-01")
        _enumeracion("categoria", self.categoria, Categoria)
        _texto("descripcion", self.descripcion, 120)
        _entero("cantidad", self.cantidad, minimo=1)
        _positivo("peso_kg", self.peso_kg)
        _positivo("volumen_m3", self.volumen_m3)
        _fecha("fecha_ingreso", self.fecha_ingreso)
        _booleano("requiere_frio", self.requiere_frio)
        _enumeracion("estado", self.estado, EstadoLote)

        if self.fecha_caducidad is None:
            if self.categoria.perecedera:
                raise ErrorValidacion("fecha_caducidad",
                                      f"es obligatoria en la categoría {self.categoria.value}")
            if self.requiere_frio:
                raise ErrorValidacion("fecha_caducidad",
                                      "un lote que requiere frío debe tener caducidad")
        else:
            _fecha("fecha_caducidad", self.fecha_caducidad)
            if self.fecha_caducidad <= self.fecha_ingreso:
                raise ErrorValidacion("fecha_caducidad",
                                      "debe ser posterior a la fecha de ingreso")

        # El destino y el estado deben ir de la mano
        if self.estado in ESTADOS_CON_DESTINO:
            if self.municipio_destino_id is None:
                raise ErrorValidacion("municipio_destino_id",
                                      f"un lote {self.estado.value} debe tener municipio destino")
            _identificador("municipio_destino_id", self.municipio_destino_id,
                           PATRON_MUNICIPIO, "MUN-001")
        elif self.municipio_destino_id is not None:
            raise ErrorValidacion("municipio_destino_id",
                                  f"un lote {self.estado.value} no puede tener municipio destino")

    @property
    def unidad(self) -> str:
        return self.categoria.unidad

    def vencido(self, hoy: date) -> bool:
        """Si ya no se puede entregar: vence hoy o antes."""
        return self.fecha_caducidad is not None and self.fecha_caducidad <= hoy

    def dias_para_vencer(self, hoy: date) -> int | None:
        """Días que faltan para la caducidad; None si no caduca."""
        if self.fecha_caducidad is None:
            return None
        return (self.fecha_caducidad - hoy).days


@dataclass(frozen=True, slots=True)
class AporteEconomico:
    """Dinero para compras inmediatas en zonas cercanas."""
    id: str
    donante_id: str
    monto_cop: int                # pesos colombianos, entero: el dinero no se guarda en float
    fecha: date
    municipio_destino_id: str | None  # None = libre destinación

    def __post_init__(self) -> None:
        _identificador("id", self.id, PATRON_APORTE, "APO-00001")
        _identificador("donante_id", self.donante_id, PATRON_DONANTE, "DON-0001")
        _entero("monto_cop", self.monto_cop, minimo=1)
        _fecha("fecha", self.fecha)
        if self.municipio_destino_id is not None:
            _identificador("municipio_destino_id", self.municipio_destino_id,
                           PATRON_MUNICIPIO, "MUN-001")


@dataclass(frozen=True, slots=True)
class Via:
    """Tramo de carretera entre dos nodos (centros o municipios).

    No tiene dirección: se puede recorrer en ambos sentidos.
    """
    origen_id: str
    destino_id: str
    distancia_km: float
    tiempo_h: float               # tiempo estimado en condiciones normales
    estado: EstadoVia

    def __post_init__(self) -> None:
        for campo, valor in (("origen_id", self.origen_id), ("destino_id", self.destino_id)):
            if not isinstance(valor, str) or not es_nodo_vial(valor):
                raise ErrorValidacion(campo, f"'{valor}' no es un centro (CA-01) ni un municipio (MUN-001)")
        if self.origen_id == self.destino_id:
            raise ErrorValidacion("destino_id", "una vía no puede unir un nodo consigo mismo")
        _positivo("distancia_km", self.distancia_km)
        _positivo("tiempo_h", self.tiempo_h)
        _enumeracion("estado", self.estado, EstadoVia)

    @property
    def clave(self) -> tuple[str, str]:
        """La misma para A→B y B→A: así se detectan vías duplicadas."""
        a, b = sorted((self.origen_id, self.destino_id))
        return (a, b)
