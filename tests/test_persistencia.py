"""Fase 1 — Conversión, lectura y escritura: archivos malformados, nulos,
integridad referencial, coherencia temporal, ida y vuelta, datos generados."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from donaciones import generador, persistencia
from donaciones.generador import generar
from donaciones.modelo import FECHA_EVENTO as EVENTO
from donaciones.modelo import Categoria, ErrorValidacion, EstadoVia, Urgencia
from donaciones.persistencia import (
    DONANTES, Carga, Datos, ErrorArchivo, Rechazo, campo_booleano, campo_entero, campo_enum,
    campo_fecha, campo_fecha_opcional, campo_real, campo_texto, campo_texto_opcional,
    cargar_csv, cargar_json, escribir_csv, exportar_json, guardar_csv,
)


# ============================================================
# Utilidades para editar CSV dentro de las pruebas
# ============================================================

def leer_filas(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def escribir_filas(ruta: Path, filas: list[dict[str, str]]) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def cambiar_celda(ruta: Path, indice: int, columna: str, valor: str) -> int:
    """Cambia una celda de la fila `indice` (0 = primera fila de datos).

    Devuelve el número de línea de esa fila en el archivo (encabezado = 1).
    """
    filas = leer_filas(ruta)
    filas[indice][columna] = valor
    escribir_filas(ruta, filas)
    return indice + 2


# ============================================================
# Conversión de valores crudos (CSV o JSON) a tipos de Python
# ============================================================

def _r(valor: object) -> dict[str, object]:
    return {"x": valor}


# ---------- Enteros ----------

@pytest.mark.parametrize(("crudo", "esperado"), [
    ("12", 12), (" 12 ", 12), ("-3", -3), ("+4", 4), ("007", 7), (12, 12),
])
def test_entero_valido(crudo: object, esperado: int) -> None:
    assert campo_entero(_r(crudo), "x") == esperado


@pytest.mark.parametrize("crudo", ["", "  ", None, "3.5", "diez", "1e3", "1 000", True, 2.0, [1]])
def test_entero_invalido(crudo: object) -> None:
    with pytest.raises(ErrorValidacion) as error:
        campo_entero(_r(crudo), "x")
    assert error.value.campo == "x"


# ---------- Reales ----------

@pytest.mark.parametrize(("crudo", "esperado"), [
    ("1.5", 1.5), ("-73.1848", -73.1848), (".5", 0.5), ("3", 3.0), (2, 2.0), (2.25, 2.25),
])
def test_real_valido(crudo: object, esperado: float) -> None:
    assert campo_real(_r(crudo), "x") == esperado


@pytest.mark.parametrize("crudo", ["nan", "inf", "-inf", "1,5", "abc", "", False, float("nan")])
def test_real_invalido(crudo: object) -> None:
    with pytest.raises(ErrorValidacion):
        campo_real(_r(crudo), "x")


# ---------- Fechas ----------

def test_fecha_valida() -> None:
    assert campo_fecha(_r("2026-11-03"), "x") == date(2026, 11, 3)
    assert campo_fecha(_r("2028-02-29"), "x") == date(2028, 2, 29)     # año bisiesto


@pytest.mark.parametrize("crudo", [
    "2026-13-01",     # mes 13
    "2026-02-30",     # día que no existe
    "2027-02-29",     # 2027 no es bisiesto
    "03/11/2026",     # formato ambiguo
    "2026-1-3",       # sin ceros a la izquierda
    "20261103",
    "",
    None,
    20261103,
])
def test_fecha_invalida(crudo: object) -> None:
    with pytest.raises(ErrorValidacion):
        campo_fecha(_r(crudo), "x")


def test_fecha_opcional() -> None:
    assert campo_fecha_opcional(_r(""), "x") is None
    assert campo_fecha_opcional(_r(None), "x") is None
    assert campo_fecha_opcional(_r("2026-12-01"), "x") == date(2026, 12, 1)


# ---------- Booleanos ----------

@pytest.mark.parametrize(("crudo", "esperado"), [
    ("SI", True), ("si", True), ("Sí", True), ("NO", False), ("no", False), (True, True), (False, False),
])
def test_booleano_valido(crudo: object, esperado: bool) -> None:
    assert campo_booleano(_r(crudo), "x") is esperado


@pytest.mark.parametrize("crudo", ["S", "1", "verdadero", "", 1, None])
def test_booleano_invalido(crudo: object) -> None:
    with pytest.raises(ErrorValidacion):
        campo_booleano(_r(crudo), "x")


# ---------- Enumeraciones y texto ----------

def test_enumeracion_no_distingue_mayusculas() -> None:
    assert campo_enum(_r("agua"), "x", Categoria) is Categoria.AGUA
    assert campo_enum(_r("CRITICA"), "x", Urgencia) is Urgencia.CRITICA


def test_enumeracion_invalida_lista_las_opciones() -> None:
    with pytest.raises(ErrorValidacion) as error:
        campo_enum(_r("COMIDA"), "x", Categoria)
    assert "MEDICO" in error.value.mensaje and "AGUA" in error.value.mensaje


def test_urgencia_se_lee_por_nombre_no_por_numero() -> None:
    with pytest.raises(ErrorValidacion):
        campo_enum(_r("1"), "x", Urgencia)


def test_texto_quita_espacios_y_exige_valor() -> None:
    assert campo_texto(_r("  Zapatoca "), "x") == "Zapatoca"
    with pytest.raises(ErrorValidacion):
        campo_texto(_r("   "), "x")
    with pytest.raises(ErrorValidacion):
        campo_texto(_r(25), "x")


def test_texto_opcional() -> None:
    assert campo_texto_opcional(_r(""), "x") is None
    assert campo_texto_opcional(_r("MUN-001"), "x") == "MUN-001"


def test_campo_ausente() -> None:
    with pytest.raises(ErrorValidacion) as error:
        campo_entero({}, "cantidad")
    assert error.value.campo == "cantidad"
    assert "falta" in error.value.mensaje

# ============================================================
# Carga de archivos
# ============================================================


def _cargar(carpeta: Path) -> Carga:
    return cargar_csv(carpeta, EVENTO)


def _unico_rechazo(carga: Carga) -> Rechazo:
    assert len(carga.rechazos) == 1, [str(r) for r in carga.rechazos]
    return carga.rechazos[0]


# ============================================================
# Datos válidos e ida y vuelta
# ============================================================

def test_carga_sin_rechazos(carpeta: Path, datos_pequenos: Datos) -> None:
    carga = _cargar(carpeta)
    assert carga.rechazos == []
    assert carga.datos == datos_pequenos


def test_ida_y_vuelta_csv(tmp_path: Path, datos_pequenos: Datos) -> None:
    guardar_csv(tmp_path, datos_pequenos)
    assert _cargar(tmp_path).datos == datos_pequenos


def test_ida_y_vuelta_json(tmp_path: Path, datos_pequenos: Datos) -> None:
    ruta = tmp_path / "todo.json"
    exportar_json(ruta, datos_pequenos, EVENTO)
    carga = cargar_json(ruta, EVENTO)
    assert carga.rechazos == []
    assert carga.datos == datos_pequenos


def test_csv_a_json_a_csv_produce_archivos_identicos(carpeta: Path, tmp_path: Path) -> None:
    json_intermedio = tmp_path / "intermedio.json"
    exportar_json(json_intermedio, _cargar(carpeta).datos, EVENTO)
    otra = tmp_path / "otra"
    guardar_csv(otra, cargar_json(json_intermedio, EVENTO).datos)
    for archivo in carpeta.glob("*.csv"):
        assert (otra / archivo.name).read_bytes() == archivo.read_bytes()


def test_columnas_en_otro_orden_se_leen_igual(carpeta: Path, datos_pequenos: Datos) -> None:
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    invertidas = [dict(reversed(list(fila.items()))) for fila in filas]
    escribir_filas(ruta, invertidas)
    assert _cargar(carpeta).datos.lotes == datos_pequenos.lotes


def test_acepta_el_bom_que_agrega_excel(carpeta: Path) -> None:
    ruta = carpeta / "donantes.csv"
    ruta.write_bytes(b"\xef\xbb\xbf" + ruta.read_bytes())
    assert _cargar(carpeta).rechazos == []


def test_ignora_lineas_en_blanco(carpeta: Path, datos_pequenos: Datos) -> None:
    ruta = carpeta / "donantes.csv"
    ruta.write_text(ruta.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert len(_cargar(carpeta).datos.donantes) == len(datos_pequenos.donantes)


# ============================================================
# Archivos que no se pueden usar → ErrorArchivo
# ============================================================

def test_archivo_inexistente(carpeta: Path) -> None:
    (carpeta / "vias.csv").unlink()
    with pytest.raises(ErrorArchivo, match="No existe"):
        _cargar(carpeta)


def test_archivo_vacio(carpeta: Path) -> None:
    (carpeta / "municipios.csv").write_text("", encoding="utf-8")
    with pytest.raises(ErrorArchivo, match="vacío"):
        _cargar(carpeta)


def test_falta_una_columna(carpeta: Path) -> None:
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    for fila in filas:
        del fila["fecha_caducidad"]
    escribir_filas(ruta, filas)
    with pytest.raises(ErrorArchivo, match="fecha_caducidad"):
        _cargar(carpeta)


def test_archivo_que_no_esta_en_utf8(carpeta: Path) -> None:
    ruta = carpeta / "centros.csv"
    ruta.write_bytes(ruta.read_text(encoding="utf-8").encode("latin-1"))   # "Bogotá" en latin-1
    with pytest.raises(ErrorArchivo, match="UTF-8"):
        _cargar(carpeta)


def test_json_malformado(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.json"
    ruta.write_text('{"formato": "donaciones-v1", "lotes": [', encoding="utf-8")
    with pytest.raises(ErrorArchivo, match="no es un JSON válido"):
        cargar_json(ruta, EVENTO)


def test_json_de_otro_sistema(tmp_path: Path) -> None:
    ruta = tmp_path / "otro.json"
    ruta.write_text('{"usuarios": []}', encoding="utf-8")
    with pytest.raises(ErrorArchivo, match="formato"):
        cargar_json(ruta, EVENTO)


def test_json_con_coleccion_que_no_es_lista(tmp_path: Path, datos_pequenos: Datos) -> None:
    ruta = tmp_path / "todo.json"
    exportar_json(ruta, datos_pequenos, EVENTO)
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    documento["vias"] = {"origen_id": "CA-01"}
    ruta.write_text(json.dumps(documento), encoding="utf-8")
    with pytest.raises(ErrorArchivo, match="vias"):
        cargar_json(ruta, EVENTO)


# ============================================================
# Registros malos → se rechaza la fila y se cargan las demás
# ============================================================

@pytest.mark.parametrize(("columna", "valor", "fragmento"), [
    ("cantidad", "", "obligatorio"),                  # nulo
    ("cantidad", "diez", "entero"),                   # tipo equivocado
    ("cantidad", "-5", "mayor o igual"),              # negativo
    ("cantidad", "0", "mayor o igual"),
    ("peso_kg", "1,5", "punto decimal"),              # coma decimal
    ("fecha_ingreso", "2026-02-30", "no es una fecha que exista"),
    ("fecha_ingreso", "05/11/2026", "AAAA-MM-DD"),
    ("categoria", "COMIDA", "use uno de"),
    ("requiere_frio", "quizás", "SI o NO"),
    ("id", "LOTE-1", "formato"),
])
def test_fila_de_lote_invalida(carpeta: Path, datos_pequenos: Datos,
                               columna: str, valor: str, fragmento: str) -> None:
    linea = cambiar_celda(carpeta / "lotes.csv", 3, columna, valor)
    carga = _cargar(carpeta)
    rechazo = _unico_rechazo(carga)
    assert (rechazo.archivo, rechazo.linea, rechazo.campo) == ("lotes.csv", linea, columna)
    assert fragmento in rechazo.mensaje
    assert len(carga.datos.lotes) == len(datos_pequenos.lotes) - 1   # las demás sí cargan


def test_fila_con_columnas_de_mas_o_de_menos(carpeta: Path) -> None:
    ruta = carpeta / "donantes.csv"
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    lineas[1] += ",sobra"
    lineas[2] = lineas[2].rsplit(",", 1)[0]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    carga = _cargar(carpeta)
    donantes = [r for r in carga.rechazos if r.archivo == "donantes.csv"]
    assert [(r.linea, "más" in r.mensaje) for r in donantes] == [(2, True), (3, False)]


def test_id_repetido_conserva_el_primero(carpeta: Path) -> None:
    ruta = carpeta / "aportes.csv"
    filas = leer_filas(ruta)
    filas.append(dict(filas[0]))
    escribir_filas(ruta, filas)
    rechazo = _unico_rechazo(_cargar(carpeta))
    assert rechazo.linea == len(filas) + 1 and "repetido" in rechazo.mensaje


def test_necesidad_repetida_por_llave_compuesta(carpeta: Path) -> None:
    ruta = carpeta / "necesidades.csv"
    filas = leer_filas(ruta)
    copia = dict(filas[0])
    copia["cantidad"] = "999"            # otra cantidad, misma llave (municipio, categoría)
    filas.append(copia)
    escribir_filas(ruta, filas)
    assert "repetido" in _unico_rechazo(_cargar(carpeta)).mensaje


def test_via_repetida_en_sentido_contrario(carpeta: Path) -> None:
    ruta = carpeta / "vias.csv"
    filas = leer_filas(ruta)
    inversa = dict(filas[0])
    inversa["origen_id"], inversa["destino_id"] = filas[0]["destino_id"], filas[0]["origen_id"]
    filas.append(inversa)
    escribir_filas(ruta, filas)
    assert "repetido" in _unico_rechazo(_cargar(carpeta)).mensaje


# ============================================================
# Integridad referencial y coherencia temporal
# ============================================================

def test_lote_de_donante_inexistente(carpeta: Path) -> None:
    cambiar_celda(carpeta / "lotes.csv", 0, "donante_id", "DON-9999")
    rechazo = _unico_rechazo(_cargar(carpeta))
    assert rechazo.campo == "donante_id" and "no existe" in rechazo.mensaje


def test_rechazar_un_donante_rechaza_sus_lotes(carpeta: Path) -> None:
    donante = leer_filas(carpeta / "donantes.csv")[0]["id"]
    cambiar_celda(carpeta / "lotes.csv", 0, "donante_id", donante)
    cambiar_celda(carpeta / "donantes.csv", 0, "tipo", "EXTRATERRESTRE")
    carga = _cargar(carpeta)
    archivos = {r.archivo for r in carga.rechazos}
    assert {"donantes.csv", "lotes.csv"} <= archivos
    assert all(l.donante_id != donante for l in carga.datos.lotes)


def test_caducidad_anterior_al_sismo(carpeta: Path) -> None:
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    filas[0].update(categoria="VIVERES", fecha_ingreso="2026-10-01", fecha_caducidad="2026-10-20")
    escribir_filas(ruta, filas)
    rechazo = _unico_rechazo(_cargar(carpeta))
    assert rechazo.campo == "fecha_caducidad" and "sismo" in rechazo.mensaje


def test_caducidad_el_mismo_dia_del_sismo_no_es_posterior(carpeta: Path) -> None:
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    filas[0].update(categoria="VIVERES", fecha_ingreso="2026-11-01", fecha_caducidad=EVENTO.isoformat())
    escribir_filas(ruta, filas)
    assert _unico_rechazo(_cargar(carpeta)).campo == "fecha_caducidad"


def test_ingreso_anterior_al_sismo(carpeta: Path) -> None:
    cambiar_celda(carpeta / "lotes.csv", 0, "fecha_ingreso", "2026-11-02")
    assert _unico_rechazo(_cargar(carpeta)).campo == "fecha_ingreso"


def test_ingreso_el_mismo_dia_del_sismo_es_valido(carpeta: Path) -> None:
    cambiar_celda(carpeta / "lotes.csv", 0, "fecha_ingreso", EVENTO.isoformat())
    assert _cargar(carpeta).rechazos == []


def test_lote_con_frio_en_centro_sin_frio(carpeta: Path) -> None:
    sin_frio = next(c["id"] for c in leer_filas(carpeta / "centros.csv") if c["tiene_frio"] == "NO")
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    filas[0].update(categoria="MEDICO", fecha_caducidad="2027-01-15",
                    requiere_frio="SI", centro_id=sin_frio)
    escribir_filas(ruta, filas)
    rechazo = _unico_rechazo(_cargar(carpeta))
    assert rechazo.campo == "centro_id" and "frío" in rechazo.mensaje


def test_aporte_antes_del_sismo_y_destino_inexistente(carpeta: Path) -> None:
    cambiar_celda(carpeta / "aportes.csv", 0, "fecha", "2026-10-30")
    cambiar_celda(carpeta / "aportes.csv", 1, "municipio_destino_id", "MUN-999")
    campos = sorted(r.campo for r in _cargar(carpeta).rechazos)
    assert campos == ["fecha", "municipio_destino_id"]


def test_lote_asignado_a_un_municipio_inexistente(carpeta: Path) -> None:
    ruta = carpeta / "lotes.csv"
    filas = leer_filas(ruta)
    filas[0].update(estado="ASIGNADO", municipio_destino_id="MUN-999")
    escribir_filas(ruta, filas)
    rechazo = _unico_rechazo(_cargar(carpeta))
    assert rechazo.campo == "municipio_destino_id" and "no existe" in rechazo.mensaje


def test_via_hacia_un_nodo_inexistente(carpeta: Path) -> None:
    cambiar_celda(carpeta / "vias.csv", 0, "destino_id", "MUN-777")
    assert "no existe" in _unico_rechazo(_cargar(carpeta)).mensaje


# ============================================================
# JSON con tipos equivocados
# ============================================================

def test_json_con_registros_de_tipo_incorrecto(tmp_path: Path, datos_pequenos: Datos) -> None:
    ruta = tmp_path / "todo.json"
    exportar_json(ruta, datos_pequenos, EVENTO)
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    documento["lotes"][0]["cantidad"] = "diez"
    documento["lotes"][1]["cantidad"] = 2.5
    documento["lotes"][2]["requiere_frio"] = None
    documento["lotes"][3] = "no soy un objeto"
    ruta.write_text(json.dumps(documento), encoding="utf-8")
    carga = cargar_json(ruta, EVENTO)
    assert [(r.linea, r.campo) for r in carga.rechazos] == [
        (1, "cantidad"), (2, "cantidad"), (3, "requiere_frio"), (4, "registro")]
    assert len(carga.datos.lotes) == len(datos_pequenos.lotes) - 4


# ============================================================
# Escritura segura
# ============================================================

def test_una_escritura_fallida_no_dana_el_archivo_original(carpeta: Path, datos_pequenos: Datos) -> None:
    ruta = carpeta / "donantes.csv"
    original = ruta.read_bytes()
    # Un objeto que no es donante al final: la escritura falla a mitad de camino
    entidades: list[Any] = [*datos_pequenos.donantes, "esto no es un donante"]
    with pytest.raises(AttributeError):
        escribir_csv(ruta, DONANTES, entidades)
    assert ruta.read_bytes() == original
    assert not list(carpeta.glob("*.tmp"))


def test_escribir_en_una_ruta_imposible(tmp_path: Path, datos_pequenos: Datos) -> None:
    bloqueo = tmp_path / "soy_un_archivo"
    bloqueo.write_text("x", encoding="utf-8")
    with pytest.raises(ErrorArchivo, match="No se pudo escribir"):
        guardar_csv(bloqueo / "datos", datos_pequenos)


# ============================================================
# Datos generados
# ============================================================

def test_misma_semilla_mismos_datos() -> None:
    assert generar(42, EVENTO) == generar(42, EVENTO)


def test_otra_semilla_otros_datos() -> None:
    assert generar(1, EVENTO).lotes != generar(2, EVENTO).lotes


def test_los_datos_generados_pasan_todas_las_reglas(tmp_path: Path) -> None:
    guardar_csv(tmp_path, generar(42, EVENTO))
    assert cargar_csv(tmp_path, EVENTO).rechazos == []


def test_la_red_vial_conecta_todo_aun_sin_las_vias_cerradas() -> None:
    datos = generar(42, EVENTO)
    vecinos: dict[str, set[str]] = defaultdict(set)
    for v in datos.vias:
        if v.estado is not EstadoVia.CERRADA:
            vecinos[v.origen_id].add(v.destino_id)
            vecinos[v.destino_id].add(v.origen_id)
    visitados, pendientes = {"CA-01"}, ["CA-01"]
    while pendientes:
        for w in vecinos[pendientes.pop()] - visitados:
            visitados.add(w)
            pendientes.append(w)
    nodos = {c.id for c in datos.centros} | {m.id for m in datos.municipios}
    assert visitados == nodos


def test_hay_lotes_proximos_a_vencer_para_probar_las_alertas() -> None:
    proximos = [l for l in generar(42, EVENTO).lotes
                if l.fecha_caducidad is not None and (l.fecha_caducidad - EVENTO).days <= 30]
    assert len(proximos) >= 20


# ============================================================
# Línea de comandos
# ============================================================

def test_comandos_generar_y_validar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert generador.main([str(tmp_path)]) == 0
    assert persistencia.main([str(tmp_path)]) == 0
    assert "Todos los registros son válidos" in capsys.readouterr().out


def test_validar_reporta_la_linea_del_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    generador.main([str(tmp_path)])
    linea = cambiar_celda(tmp_path / "lotes.csv", 9, "cantidad", "-3")
    assert persistencia.main([str(tmp_path)]) == 1
    assert f"lotes.csv, línea {linea}: cantidad" in capsys.readouterr().out


def test_validar_una_carpeta_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert persistencia.main([str(tmp_path / "no_existe")]) == 2
    assert "No existe" in capsys.readouterr().err
