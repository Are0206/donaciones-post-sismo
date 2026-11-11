"""
generador.py — Datos sintéticos realistas del escenario.

Escenario: sismo el 3 de noviembre de 2026 con epicentro cerca de Los
Santos (Santander), una zona de sismicidad real (el "nido de
Bucaramanga"). Las coordenadas y distancias son aproximadas.

La geografía (centros, municipios, vías) es fija y está escrita a mano.
Donantes, lotes, aportes y necesidades se generan al azar con semilla
fija, así cada ejecución produce exactamente los mismos datos.

Todas las entidades se construyen con las clases de modelo.py, así que
el generador NO puede producir un registro inválido: si lo intentara,
fallaría al crearlo.

Uso:  python -m donaciones.generador [carpeta]
"""
from __future__ import annotations

import random
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from .modelo import (
    FECHA_EVENTO, AporteEconomico, Categoria, CentroAcopio, Donante, EstadoVia, Lote, Municipio,
    Necesidad, TipoCentro, TipoDonante, Urgencia, Via,
)
from .persistencia import CARPETA_DATOS, Carga, Datos, ErrorArchivo, guardar_csv, imprimir_resumen

# Misma semilla = mismos datos en cada ejecución
SEMILLA = 42

# ============================================================
# Geografía fija
# ============================================================

CENTROS = [
    CentroAcopio("CA-01", "Aeropuerto Palonegro", TipoCentro.AEROPUERTO, "Lebrija", 7.1265, -73.1848, 4000.0, True),
    CentroAcopio("CA-02", "Aeropuerto El Dorado", TipoCentro.AEROPUERTO, "Bogotá", 4.7016, -74.1469, 12000.0, True),
    CentroAcopio("CA-03", "Puerto fluvial de Barrancabermeja", TipoCentro.PUERTO, "Barrancabermeja", 7.0653, -73.8547, 6000.0, False),
    CentroAcopio("CA-04", "Acopio regional Bucaramanga", TipoCentro.ACOPIO_REGIONAL, "Bucaramanga", 7.1193, -73.1227, 5000.0, True),
    CentroAcopio("CA-05", "Acopio intermedio San Gil", TipoCentro.ACOPIO_INTERMEDIO, "San Gil", 6.5551, -73.1337, 1800.0, True),
    CentroAcopio("CA-06", "Acopio intermedio Socorro", TipoCentro.ACOPIO_INTERMEDIO, "Socorro", 6.4682, -73.2604, 1200.0, False),
    CentroAcopio("CA-07", "Acopio intermedio Piedecuesta", TipoCentro.ACOPIO_INTERMEDIO, "Piedecuesta", 6.9879, -73.0499, 1500.0, False),
]

_S = "Santander"
MUNICIPIOS = [
    Municipio("MUN-001", "Los Santos", _S, 6.7553, -73.1022, 11500, Urgencia.CRITICA),
    Municipio("MUN-002", "Zapatoca", _S, 6.8150, -73.2683, 9800, Urgencia.CRITICA),
    Municipio("MUN-003", "Jordán", _S, 6.7325, -73.0961, 1300, Urgencia.CRITICA),
    Municipio("MUN-004", "Villanueva", _S, 6.6717, -73.1747, 7600, Urgencia.ALTA),
    Municipio("MUN-005", "Barichara", _S, 6.6347, -73.2236, 7200, Urgencia.ALTA),
    Municipio("MUN-006", "Aratoca", _S, 6.6947, -73.0181, 8400, Urgencia.ALTA),
    Municipio("MUN-007", "Curití", _S, 6.6056, -73.0686, 11900, Urgencia.ALTA),
    Municipio("MUN-008", "Cepitá", _S, 6.7536, -72.9744, 1900, Urgencia.CRITICA),
    Municipio("MUN-009", "Betulia", _S, 6.8997, -73.2836, 5600, Urgencia.MEDIA),
    Municipio("MUN-010", "Piedecuesta", _S, 6.9879, -73.0499, 24000, Urgencia.MEDIA),
    Municipio("MUN-011", "Girón", _S, 7.0682, -73.1698, 18000, Urgencia.BAJA),
    Municipio("MUN-012", "Floridablanca", _S, 7.0622, -73.0864, 15000, Urgencia.BAJA),
    Municipio("MUN-013", "San Gil", _S, 6.5551, -73.1337, 12000, Urgencia.MEDIA),
    Municipio("MUN-014", "Socorro", _S, 6.4682, -73.2604, 6000, Urgencia.BAJA),
    Municipio("MUN-015", "Lebrija", _S, 7.1131, -73.2178, 4000, Urgencia.BAJA),
    Municipio("MUN-016", "Bucaramanga", _S, 7.1193, -73.1227, 30000, Urgencia.BAJA),
]

# Velocidad promedio en montaña según el estado de la vía (km/h)
_VELOCIDAD = {EstadoVia.TRANSITABLE: 45.0, EstadoVia.RESTRINGIDA: 20.0, EstadoVia.CERRADA: 45.0}

_T, _R, _C = EstadoVia.TRANSITABLE, EstadoVia.RESTRINGIDA, EstadoVia.CERRADA
_TRAMOS = [
    # Entradas a la red
    ("CA-01", "MUN-015", 9, _T),    ("CA-01", "MUN-016", 27, _T),
    ("CA-02", "MUN-014", 275, _T),  ("CA-03", "MUN-015", 98, _T),
    ("CA-03", "MUN-009", 90, _R),
    # Centros dentro de su ciudad
    ("CA-04", "MUN-016", 3, _T),    ("CA-05", "MUN-013", 2, _T),
    ("CA-06", "MUN-014", 2, _T),    ("CA-07", "MUN-010", 2, _T),
    # Área metropolitana
    ("MUN-016", "MUN-012", 9, _T),  ("MUN-016", "MUN-011", 10, _T),
    ("MUN-012", "MUN-010", 12, _T), ("MUN-011", "MUN-015", 18, _T),
    # Zona del epicentro (vías dañadas)
    ("MUN-010", "MUN-001", 38, _R), ("MUN-001", "MUN-003", 24, _C),
    ("MUN-010", "MUN-006", 58, _R), ("MUN-006", "MUN-008", 22, _R),
    ("MUN-006", "MUN-007", 17, _T), ("MUN-011", "MUN-002", 56, _C),
    ("MUN-011", "MUN-009", 38, _T), ("MUN-009", "MUN-002", 29, _R),
    ("MUN-005", "MUN-002", 45, _R),
    # Provincia de Guanentá
    ("MUN-007", "MUN-013", 11, _T), ("MUN-013", "MUN-005", 21, _T),
    ("MUN-013", "MUN-004", 19, _T), ("MUN-004", "MUN-005", 14, _R),
    ("MUN-004", "MUN-003", 20, _T), ("MUN-013", "MUN-014", 22, _T),
]

VIAS = [Via(a, b, float(km), round(km / _VELOCIDAD[estado], 2), estado)
        for a, b, km, estado in _TRAMOS]

# ============================================================
# Catálogos para generar al azar
# ============================================================

# descripción, requiere frío, (kg por unidad, m³ por unidad), (cantidad mín, máx)
_PRODUCTOS: dict[Categoria, list[tuple[str, bool]]] = {
    Categoria.MEDICO: [("Kit de trauma", False), ("Suero fisiológico 500 ml", False),
                       ("Antibióticos de amplio espectro", False), ("Material de sutura", False),
                       ("Kit de triaje", False), ("Insulina", True), ("Vacuna antitetánica", True)],
    Categoria.VIVERES: [("Arroz", False), ("Lenteja", False), ("Atún enlatado", False),
                        ("Leche en polvo", False), ("Panela", False), ("Aceite vegetal", False)],
    Categoria.AGUA: [("Agua potable en bolsa", False), ("Agua embotellada", False),
                     ("Agua en garrafa 20 L", False)],
    Categoria.REFUGIO: [("Carpa familiar", False), ("Kit de cobijas", False),
                        ("Kit de cocina", False), ("Kit de aseo personal", False)],
    Categoria.RESCATE: [("Kit de herramientas de rescate", False), ("Linterna y baterías", False),
                        ("Gato hidráulico", False), ("Motosierra", False)],
}

_FISICO: dict[Categoria, tuple[float, float]] = {   # (kg, m³) por unidad
    Categoria.MEDICO: (0.5, 0.002), Categoria.VIVERES: (1.0, 0.0015),
    Categoria.AGUA: (1.05, 0.0011), Categoria.REFUGIO: (12.0, 0.06),
    Categoria.RESCATE: (18.0, 0.05),
}

_RANGO_CANTIDAD: dict[Categoria, tuple[int, int]] = {
    Categoria.MEDICO: (20, 400), Categoria.VIVERES: (100, 2000),
    Categoria.AGUA: (200, 3000), Categoria.REFUGIO: (10, 150),
    Categoria.RESCATE: (2, 30),
}

# Peso de cada categoría en el total de donaciones
_PESO_CATEGORIA = {Categoria.MEDICO: 20, Categoria.VIVERES: 30, Categoria.AGUA: 30,
                   Categoria.REFUGIO: 12, Categoria.RESCATE: 8}

# Vida útil (días) para las categorías perecederas
_VIDA_UTIL = {Categoria.MEDICO: (90, 720), Categoria.VIVERES: (60, 540), Categoria.AGUA: (180, 720)}

_NOMBRES = ["Ana", "Carlos", "Luisa", "Andrés", "María", "Jorge", "Camila", "Felipe",
            "Valentina", "Santiago", "Daniela", "Juan", "Paula", "Mateo", "Laura"]
_APELLIDOS = ["Gómez", "Rodríguez", "Martínez", "López", "García", "Pérez", "Ramírez",
              "Torres", "Díaz", "Vargas", "Rojas", "Moreno", "Castro", "Ortiz"]
_EMPRESAS = ["Distribuidora", "Comercializadora", "Industrias", "Alimentos", "Transportes",
             "Farmacéutica", "Constructora"]
_SUFIJOS = ["Andina", "del Oriente", "Santandereana", "del Valle", "Nacional", "La Montaña"]
_PAISES = ["Estados Unidos", "España", "Alemania", "Japón", "Canadá", "México", "Chile",
           "Corea del Sur", "Suiza", "Noruega"]
_CIUDADES = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cúcuta", "Pereira", "Manizales"]


def _donantes(azar: random.Random, n: int) -> list[Donante]:
    tipos = [TipoDonante.PERSONA] * 40 + [TipoDonante.EMPRESA] * 25 + [TipoDonante.ONG] * 15 \
        + [TipoDonante.GOBIERNO] * 8 + [TipoDonante.INTERNACIONAL] * 12
    donantes = []
    for i in range(1, n + 1):
        tipo = azar.choice(tipos)
        pais = "Colombia"
        if tipo is TipoDonante.PERSONA:
            nombre = f"{azar.choice(_NOMBRES)} {azar.choice(_APELLIDOS)}"
        elif tipo is TipoDonante.EMPRESA:
            nombre = f"{azar.choice(_EMPRESAS)} {azar.choice(_SUFIJOS)} S.A.S."
        elif tipo is TipoDonante.ONG:
            nombre = f"Fundación {azar.choice(_APELLIDOS)} {azar.choice(_SUFIJOS)}"
        elif tipo is TipoDonante.GOBIERNO:
            nombre = f"Alcaldía de {azar.choice(_CIUDADES)}"
        else:
            pais = azar.choice(_PAISES)
            nombre = f"Cooperación internacional de {pais}"
        donantes.append(Donante(f"DON-{i:04d}", nombre, tipo, pais))
    return donantes


def _lotes(azar: random.Random, n: int, donantes: list[Donante], evento: date) -> list[Lote]:
    # Las donaciones llegan sobre todo a los puntos de entrada y al acopio regional
    pesos_centro = {"CA-01": 25, "CA-02": 20, "CA-03": 15, "CA-04": 20, "CA-05": 8, "CA-06": 6, "CA-07": 6}
    con_frio = [c.id for c in CENTROS if c.tiene_frio]
    categorias = list(_PESO_CATEGORIA)
    lotes = []
    for i in range(1, n + 1):
        categoria = azar.choices(categorias, weights=[_PESO_CATEGORIA[c] for c in categorias])[0]
        descripcion, frio = azar.choice(_PRODUCTOS[categoria])
        if frio:
            centro = azar.choice(con_frio)
        else:
            centro = azar.choices(list(pesos_centro), weights=list(pesos_centro.values()))[0]

        cantidad = azar.randint(*_RANGO_CANTIDAD[categoria])
        kg, m3 = _FISICO[categoria]
        ingreso = evento + timedelta(days=azar.randint(0, 7))

        caducidad = None
        if categoria.perecedera:
            if frio:
                vida = azar.randint(20, 180)       # la cadena de frío vence pronto
            elif azar.random() < 0.08:
                vida = azar.randint(5, 20)         # algunos lotes ya próximos a vencer
            else:
                vida = azar.randint(*_VIDA_UTIL[categoria])
            caducidad = ingreso + timedelta(days=vida)

        lotes.append(Lote(
            id=f"LOT-{i:06d}",
            donante_id=azar.choice(donantes).id,
            centro_id=centro,
            categoria=categoria,
            descripcion=descripcion,
            cantidad=cantidad,
            peso_kg=round(cantidad * kg * azar.uniform(0.95, 1.05), 2),
            volumen_m3=round(cantidad * m3 * azar.uniform(0.95, 1.10), 3),
            fecha_ingreso=ingreso,
            fecha_caducidad=caducidad,
            requiere_frio=frio,
        ))
    return lotes


def _aportes(azar: random.Random, n: int, donantes: list[Donante], evento: date) -> list[AporteEconomico]:
    aportes = []
    for i in range(1, n + 1):
        # Distribución log-uniforme: muchos aportes pequeños, pocos muy grandes
        monto = int(round(10 ** azar.uniform(4.7, 8.7), -3))     # entre ~50 mil y ~500 millones
        destino = azar.choice(MUNICIPIOS).id if azar.random() < 0.4 else None
        aportes.append(AporteEconomico(
            f"APO-{i:05d}", azar.choice(donantes).id, monto,
            evento + timedelta(days=azar.randint(0, 7)), destino))
    return aportes


# Necesidad por persona afectada para una semana, en la unidad de cada categoría
_NECESIDAD_POR_PERSONA = {
    Categoria.AGUA: 15.0,       # litros
    Categoria.VIVERES: 5.0,     # kg
    Categoria.MEDICO: 1.0,      # unidades (medicamentos e insumos)
    Categoria.REFUGIO: 0.25,    # kits (uno por familia de cuatro)
}


def _necesidades(azar: random.Random) -> list[Necesidad]:
    necesidades = []
    for m in MUNICIPIOS:
        # Mientras más urgente, más fracción de la población necesita ayuda
        fraccion = {Urgencia.CRITICA: 1.0, Urgencia.ALTA: 0.7,
                    Urgencia.MEDIA: 0.4, Urgencia.BAJA: 0.15}[m.urgencia]
        for categoria, por_persona in _NECESIDAD_POR_PERSONA.items():
            cantidad = int(m.poblacion_afectada * fraccion * por_persona * azar.uniform(0.8, 1.2))
            if cantidad > 0:
                necesidades.append(Necesidad(m.id, categoria, cantidad))
        if m.urgencia <= Urgencia.ALTA:           # rescate solo donde hubo colapsos
            necesidades.append(Necesidad(m.id, Categoria.RESCATE, azar.randint(50, 250)))
    return necesidades


def generar(semilla: int, evento: date, n_donantes: int = 80,
            n_lotes: int = 1500, n_aportes: int = 150) -> Datos:
    azar = random.Random(semilla)    # generador propio: no altera el azar global
    donantes = _donantes(azar, n_donantes)
    return Datos(
        centros=list(CENTROS),
        municipios=list(MUNICIPIOS),
        donantes=donantes,
        necesidades=_necesidades(azar),
        lotes=_lotes(azar, n_lotes, donantes, evento),
        aportes=_aportes(azar, n_aportes, donantes, evento),
        vias=list(VIAS),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    carpeta = Path(args[0]) if args else CARPETA_DATOS
    datos = generar(SEMILLA, FECHA_EVENTO)
    try:
        guardar_csv(carpeta, datos)
    except ErrorArchivo as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(f"Datos generados en {carpeta}/")
    imprimir_resumen(Carga(datos, []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
