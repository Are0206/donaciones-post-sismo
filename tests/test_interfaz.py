"""Fase 4 — Interfaz gráfica.

Dos grupos de pruebas:

1. El controlador y el ejecutor en segundo plano, sin abrir ventanas.
2. La ventana real (Tkinter), oculta. Si el equipo no tiene pantalla
   (por ejemplo, un servidor), estas pruebas se omiten.
"""
from __future__ import annotations

import functools
import threading
import time
import tkinter as tk
from tkinter import messagebox
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from donaciones.controlador import (
    Controlador, Ejecutor, ErrorFormulario, FiltrosInventario, Fila, numero,
)
from donaciones.estructuras import Criterio
from donaciones.modelo import FECHA_EVENTO, EstadoLote, EstadoVia, Lote
from donaciones.operaciones import SistemaDonaciones
from donaciones.persistencia import Datos, cargar_csv

HOY = FECHA_EVENTO + timedelta(days=4)


@pytest.fixture
def ctrl(datos_pequenos: Datos, tmp_path: Path) -> Iterator[Controlador]:
    c = Controlador(SistemaDonaciones(datos_pequenos), HOY, tmp_path)
    yield c
    c.ejecutor.cerrar()


def formulario(ctrl: Controlador, **cambios: object) -> dict[str, object]:
    """Un formulario válido (agua en un centro con frío), con los cambios pedidos."""
    centro = next(c for c in ctrl.sistema.datos.centros if c.tiene_frio)
    valores: dict[str, object] = {
        "donante_id": ctrl.sistema.datos.donantes[0].id, "centro_id": centro.id, "categoria": "AGUA",
        "descripcion": "Agua embotellada", "cantidad": "500", "peso_kg": "520.5", "volumen_m3": "0.8",
        "fecha_ingreso": HOY.isoformat(), "fecha_caducidad": (HOY + timedelta(days=200)).isoformat(),
        "requiere_frio": False,
    }
    valores.update(cambios)
    return valores


def buscar(ctrl: Controlador, lote_id: str) -> Lote:
    lote = ctrl.sistema.lote(lote_id)
    assert lote is not None
    return lote


# ============================================================
# 1. Controlador
# ============================================================

def test_numeros_con_punto_de_miles_y_coma_decimal() -> None:
    assert numero(1234567) == "1.234.567"
    assert numero(1494.04, 1) == "1.494,0"
    assert numero(0) == "0"


def test_formulario_valido_no_tiene_errores(ctrl: Controlador) -> None:
    validacion = ctrl.validar_ingreso(formulario(ctrl))
    assert validacion.valida
    assert validacion.datos is not None


def test_formulario_reune_todos_los_errores_a_la_vez(ctrl: Controlador) -> None:
    validacion = ctrl.validar_ingreso(formulario(
        ctrl, donante_id="", descripcion="  ", cantidad="cinco", peso_kg="1,5", fecha_ingreso="14/11/2026"))
    assert set(validacion.errores) == {"donante_id", "descripcion", "cantidad", "peso_kg", "fecha_ingreso"}
    assert validacion.datos is None
    assert not any(m[0].islower() for m in validacion.errores.values())   # empiezan en mayúscula


def test_formulario_aplica_las_reglas_de_integridad(ctrl: Controlador) -> None:
    sin_frio = next(c for c in ctrl.sistema.datos.centros if not c.tiene_frio)
    validacion = ctrl.validar_ingreso(formulario(ctrl, centro_id=sin_frio.id, requiere_frio=True))
    assert list(validacion.errores) == ["centro_id"]
    assert "frío" in validacion.errores["centro_id"]
    otro = ctrl.validar_ingreso(formulario(ctrl, donante_id="DON-9999"))
    assert list(otro.errores) == ["donante_id"]


def test_formulario_aplica_las_reglas_del_modelo(ctrl: Controlador) -> None:
    sin_caducidad = ctrl.validar_ingreso(formulario(ctrl, fecha_caducidad=""))
    assert list(sin_caducidad.errores) == ["fecha_caducidad"]
    negativa = ctrl.validar_ingreso(formulario(ctrl, cantidad="-3"))
    assert list(negativa.errores) == ["cantidad"]


def test_validar_no_registra_nada(ctrl: Controlador) -> None:
    antes = len(ctrl.sistema.datos.lotes)
    ctrl.validar_ingreso(formulario(ctrl))
    assert len(ctrl.sistema.datos.lotes) == antes
    assert not ctrl.cambios_sin_guardar


def test_registrar_ingreso_valido(ctrl: Controlador) -> None:
    antes = len(ctrl.sistema.datos.lotes)
    lote = ctrl.registrar_ingreso(formulario(ctrl))
    assert len(ctrl.sistema.datos.lotes) == antes + 1
    assert ctrl.cambios_sin_guardar
    assert ctrl.inventario(FiltrosInventario(texto=lote.id)).filas[0].id == lote.id


def test_registrar_ingreso_invalido_no_cambia_nada(ctrl: Controlador) -> None:
    antes = len(ctrl.sistema.datos.lotes)
    with pytest.raises(ErrorFormulario) as error:
        ctrl.registrar_ingreso(formulario(ctrl, cantidad="0", descripcion=""))
    assert "descripcion" in error.value.errores
    assert len(ctrl.sistema.datos.lotes) == antes
    assert not ctrl.cambios_sin_guardar
    assert ctrl.sistema.verificar_consistencia() == []


def test_inventario_filtra_por_texto_y_vencimiento(ctrl: Controlador) -> None:
    todos = ctrl.inventario(FiltrosInventario())
    assert len(todos.filas) == len(ctrl.sistema.datos.lotes)
    descripcion = ctrl.sistema.datos.lotes[0].descripcion
    por_texto = ctrl.inventario(FiltrosInventario(texto=descripcion.upper()))
    assert por_texto.filas and all(descripcion in f.valores[2] for f in por_texto.filas)
    pronto = ctrl.inventario(FiltrosInventario(vence_en_dias=7))
    limite = HOY + timedelta(days=7)
    for fila in pronto.filas:
        lote = buscar(ctrl, fila.id)
        assert lote.fecha_caducidad is not None and lote.fecha_caducidad <= limite


def test_inventario_limita_las_filas_y_lo_dice(ctrl: Controlador, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Controlador, "LIMITE_FILAS", 5)
    tabla = ctrl.inventario(FiltrosInventario())
    assert len(tabla.filas) == 5
    assert "primeros 5" in tabla.pie


def test_filas_se_ordenan_por_valor_y_no_por_texto(ctrl: Controlador) -> None:
    filas = ctrl.inventario(FiltrosInventario()).filas
    por_cantidad = sorted(filas, key=lambda f: f.clave(3))
    cantidades = [buscar(ctrl, f.id).cantidad for f in por_cantidad]
    assert cantidades == sorted(cantidades)
    assert Fila("x", ("B",)).clave(0) == "b"            # sin claves, ordena por el texto


def test_inventario_por_centro_suma_lo_disponible(ctrl: Controlador) -> None:
    tabla = ctrl.inventario_por_centro()
    assert len(tabla.filas) == len(ctrl.sistema.datos.centros)
    total = sum(sum(f.claves[1:6]) for f in tabla.filas)
    assert total == sum(l.cantidad for l in ctrl.sistema.datos.lotes if l.estado is EstadoLote.DISPONIBLE)


def test_resumen_cuadra_con_las_alertas(ctrl: Controlador) -> None:
    resumen = ctrl.resumen()
    alertas = ctrl.sistema.alertas_desabastecimiento()
    cubiertas = len(ctrl.sistema.datos.necesidades) - len(alertas)
    assert resumen.indicadores[0].valor == f"{cubiertas} de {len(ctrl.sistema.datos.necesidades)}"
    for c in resumen.coberturas:
        assert 0 <= c.cubierto <= c.necesidad
        assert 0.0 <= c.fraccion <= 1.0


def test_asignar_despachar_y_guardar(ctrl: Controlador) -> None:
    asignados = ctrl.asignar_automaticamente()
    assert asignados > 0 and ctrl.cambios_sin_guardar
    pendientes = ctrl.por_despachar().filas
    assert len(pendientes) == asignados
    ids = [f.id for f in pendientes[:3]]
    resultado = ctrl.despachar(ids + ["LOT-999999"])
    assert resultado.despachados == ids
    assert len(resultado.errores) == 1                   # un error no detiene a los demás
    assert all(buscar(ctrl, i).estado is EstadoLote.DESPACHADO for i in ids)

    ctrl.guardar()
    assert not ctrl.cambios_sin_guardar
    releidos = cargar_csv(ctrl.carpeta).datos
    assert sum(l.estado is EstadoLote.DESPACHADO for l in releidos.lotes) == 3


def test_mapa_reparte_el_flujo_por_vias_abiertas(ctrl: Controlador) -> None:
    ctrl.asignar_automaticamente()
    mapa = ctrl.mapa()
    assert len(mapa.nodos) == len(ctrl.sistema.datos.centros) + len(ctrl.sistema.datos.municipios)
    assert len(mapa.tramos) == len(ctrl.sistema.datos.vias)
    assert sum(t.toneladas for t in mapa.tramos) > 0
    assert all(t.toneladas == 0 for t in mapa.tramos if t.via.estado is EstadoVia.CERRADA)


def test_describir_ruta(ctrl: Controlador) -> None:
    centro = ctrl.sistema.datos.centros[0].id
    municipio = ctrl.sistema.datos.municipios[0].id
    ruta = ctrl.ruta(centro, municipio, Criterio.DISTANCIA)
    assert ruta is not None
    texto = ctrl.describir_ruta(ruta, Criterio.DISTANCIA)
    assert "km" in texto and " → " in texto
    assert "No hay ruta" in ctrl.describir_ruta(None, Criterio.TIEMPO)


# ============================================================
# 1b. Ejecutor en segundo plano
# ============================================================

def esperar_resultados(ejecutor: Ejecutor, cuantos: int, limite: float = 5.0) -> None:
    entregados, fin = 0, time.monotonic() + limite
    while entregados < cuantos:
        assert time.monotonic() < fin, "el ejecutor no terminó a tiempo"
        entregados += ejecutor.procesar_pendientes()
        time.sleep(0.005)


@pytest.fixture
def ejecutor() -> Iterator[Ejecutor]:
    e = Ejecutor()
    yield e
    e.cerrar()


def test_corre_en_otro_hilo_y_entrega_solo_al_procesar(ejecutor: Ejecutor) -> None:
    hilos: list[str] = []
    recibidos: list[int] = []
    def tarea() -> int:
        hilos.append(threading.current_thread().name)
        return 42
    ejecutor.ejecutar(tarea, recibidos.append, lambda e: None)
    time.sleep(0.1)
    assert recibidos == []                       # nada llega sin procesar_pendientes
    esperar_resultados(ejecutor, 1)
    assert recibidos == [42]
    assert hilos and hilos[0] != threading.current_thread().name
    assert not ejecutor.ocupado


def test_ejecutar_vuelve_de_inmediato_aunque_la_tarea_tarde(ejecutor: Ejecutor) -> None:
    liberar = threading.Event()
    inicio = time.monotonic()
    ejecutor.ejecutar(lambda: liberar.wait(5), lambda _r: None, lambda e: None)
    assert time.monotonic() - inicio < 0.05
    assert ejecutor.ocupado
    liberar.set()
    esperar_resultados(ejecutor, 1)
    assert not ejecutor.ocupado


def test_los_errores_llegan_a_al_fallar(ejecutor: Ejecutor) -> None:
    errores: list[Exception] = []

    def falla() -> None:
        raise ValueError("algo salió mal")
    ejecutor.ejecutar(falla, lambda _r: pytest.fail("no debía terminar bien"), errores.append)
    esperar_resultados(ejecutor, 1)
    assert len(errores) == 1 and str(errores[0]) == "algo salió mal"


def test_un_doble_clic_no_repite_la_accion(ejecutor: Ejecutor) -> None:
    liberar = threading.Event()
    corridas: list[int] = []

    def tarea() -> None:
        liberar.wait(5)
        corridas.append(1)
    assert ejecutor.ejecutar(tarea, lambda _r: None, lambda e: None, accion="asignar")
    assert not ejecutor.ejecutar(tarea, lambda _r: None, lambda e: None, accion="asignar")
    assert ejecutor.en_curso("asignar")
    liberar.set()
    esperar_resultados(ejecutor, 1)
    assert corridas == [1]
    assert not ejecutor.en_curso("asignar")
    assert ejecutor.ejecutar(tarea, lambda _r: None, lambda e: None, accion="asignar")   # ya se puede
    esperar_resultados(ejecutor, 1)


def test_muchas_tareas_se_entregan_en_orden(ejecutor: Ejecutor) -> None:
    recibidos: list[int] = []
    for i in range(500):
        ejecutor.ejecutar(functools.partial(int, i), recibidos.append, lambda e: None)
    esperar_resultados(ejecutor, 500)
    assert recibidos == list(range(500))


def test_operaciones_desde_la_interfaz_y_otros_hilos_no_rompen_el_inventario(ctrl: Controlador) -> None:
    """Mientras la ventana registra y asigna en segundo plano, otro hilo
    (por ejemplo, una carga masiva) también registra. El inventario debe
    quedar consistente."""
    def registrar_muchos() -> None:
        for _ in range(100):
            ctrl.registrar_ingreso(formulario(ctrl))

    otro = threading.Thread(target=registrar_muchos)
    otro.start()
    for _ in range(100):
        ctrl.ejecutor.ejecutar(lambda: ctrl.registrar_ingreso(formulario(ctrl)), lambda _r: None,
                               lambda e: pytest.fail(str(e)))
    ctrl.ejecutor.ejecutar(ctrl.asignar_automaticamente, lambda _r: None, lambda e: pytest.fail(str(e)))
    otro.join()
    esperar_resultados(ctrl.ejecutor, 101)
    assert ctrl.sistema.verificar_consistencia() == []
    ids = [l.id for l in ctrl.sistema.datos.lotes]
    assert len(ids) == len(set(ids)) == 40 + 200


# ============================================================
# 2. La ventana
# ============================================================

@pytest.fixture
def app(ctrl: Controlador, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from donaciones.interfaz import Aplicacion
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("Este equipo no tiene pantalla para abrir ventanas")
    raiz.withdraw()
    aplicacion = Aplicacion(raiz, ctrl)
    monkeypatch.setattr(aplicacion, "avisar", lambda titulo, texto, error=False: None)
    monkeypatch.setattr(aplicacion, "confirmar", lambda titulo, texto: True)
    bombear(aplicacion)
    yield aplicacion
    try:
        aplicacion.destruir()
    except tk.TclError:
        pass                                         # la prueba ya cerró la ventana


def bombear(app: Any, hasta: Callable[[], bool] | None = None, limite: float = 10.0) -> None:
    """Deja correr la ventana hasta que el ejecutor termine (y la condición se cumpla)."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        app.raiz.update()
        app.controlador.ejecutor.procesar_pendientes()
        if not app.controlador.ejecutor.ocupado and (hasta is None or hasta()):
            app.raiz.update()
            return
        time.sleep(0.01)
    pytest.fail("la ventana no terminó a tiempo")


def test_se_puede_ir_a_cada_panel(app: Any) -> None:
    for clave, nombre in app.PANELES:
        app.mostrar(clave)
        bombear(app)
        assert app.actual == clave
        assert app._titulo.cget("text") == app.paneles[clave].titulo
        assert app.paneles[clave].vigente


def test_resumen_muestra_los_indicadores(app: Any) -> None:
    textos = [t.valor.cget("text") for t in app.paneles["resumen"].indicadores]
    assert "…" not in textos
    assert textos[3] == numero(len(app.controlador.sistema.datos.lotes))


def test_formulario_marca_cada_campo_con_error(app: Any) -> None:
    app.mostrar("registro")
    panel = app.paneles["registro"]
    panel.variables["descripcion"].set("")
    panel.variables["cantidad"].set("-5")
    panel.variables["peso_kg"].set("1,5")
    antes = len(app.controlador.sistema.datos.lotes)
    panel.registrar()
    bombear(app)
    assert panel.campos["peso_kg"].error.cget("text").startswith("'1,5'")
    assert panel.campos["descripcion"].error.cget("text").strip()
    assert panel.campos["donante_id"].error.cget("text").strip()
    assert len(app.controlador.sistema.datos.lotes) == antes
    panel.variables["peso_kg"].set("2")              # al corregir, el error se borra
    assert not panel.campos["peso_kg"].error.cget("text").strip()


def test_formulario_registra_un_lote(app: Any) -> None:
    app.mostrar("registro")
    panel = app.paneles["registro"]
    centro = next(o for o in panel._centros if app.controlador.centro_tiene_frio(o.id))
    for campo, valor in (("donante_id", panel._donantes[0].etiqueta), ("centro_id", centro.etiqueta),
                         ("categoria", "Médico"), ("descripcion", "Insulina"), ("cantidad", "40"),
                         ("peso_kg", "8"), ("volumen_m3", "0.05"),
                         ("fecha_caducidad", (HOY + timedelta(days=90)).isoformat())):
        panel.variables[campo].set(valor)
    panel.frio.set(True)
    assert panel.unidad.cget("text") == "unidades"
    antes = len(app.controlador.sistema.datos.lotes)
    panel.registrar()
    bombear(app)
    assert len(app.controlador.sistema.datos.lotes) == antes + 1
    nuevo = app.controlador.sistema.datos.lotes[-1]
    assert nuevo.requiere_frio and nuevo.descripcion == "Insulina"
    assert panel.ultimo_codigo.cget("text") == nuevo.id
    assert "sin guardar" in app._chip.cget("text")


def test_categoria_no_perecedera_desactiva_la_caducidad(app: Any) -> None:
    panel = app.paneles["registro"]
    panel.variables["fecha_caducidad"].set("2027-01-01")
    panel.variables["categoria"].set("Rescate")
    assert panel.variables["fecha_caducidad"].get() == ""
    assert panel.campos["fecha_caducidad"].control.instate(["disabled"])
    panel.variables["categoria"].set("Agua")
    assert not panel.campos["fecha_caducidad"].control.instate(["disabled"])


def test_filtrar_y_ordenar_el_inventario(app: Any) -> None:
    app.mostrar("inventario")
    bombear(app)
    panel = app.paneles["inventario"]
    assert len(panel.tabla.ids()) == len(app.controlador.sistema.datos.lotes)
    panel.categoria.set("Agua")
    panel.actualizar()
    bombear(app)
    ids = panel.tabla.ids()
    assert ids and all(app.controlador.sistema.lote(i).categoria.name == "AGUA" for i in ids)
    panel.tabla.ordenar(3)                          # columna Cantidad
    cantidades = [app.controlador.sistema.lote(i).cantidad for i in panel.tabla.ids()]
    assert cantidades == sorted(cantidades)
    panel.tabla.ordenar(3)                          # segundo clic: al revés
    cantidades = [app.controlador.sistema.lote(i).cantidad for i in panel.tabla.ids()]
    assert cantidades == sorted(cantidades, reverse=True)


def test_busqueda_espera_a_que_se_deje_de_escribir(app: Any) -> None:
    app.mostrar("inventario")
    bombear(app)
    panel = app.paneles["inventario"]
    codigo = app.controlador.sistema.datos.lotes[5].id
    for i in range(1, len(codigo) + 1):             # se "escribe" letra por letra
        panel.texto.set(codigo[:i])
    bombear(app, hasta=lambda: panel.tabla.ids() == [codigo])


def test_asignar_y_despachar_desde_la_ventana(app: Any) -> None:
    app.mostrar("alertas")
    bombear(app)
    panel = app.paneles["alertas"]
    assert panel.asignados.ids() == []
    panel.asignar()
    panel.asignar()                                 # doble clic: se ignora
    bombear(app)
    pendientes = panel.asignados.ids()
    assert len(pendientes) == len(app.controlador.sistema.buscar_lotes(estado=EstadoLote.ASIGNADO)) > 0
    elegidos = pendientes[:2]
    panel.asignados.arbol.selection_set(elegidos)
    panel.despachar()
    bombear(app)
    assert all(app.controlador.sistema.lote(i).estado is EstadoLote.DESPACHADO for i in elegidos)
    assert not set(elegidos) & set(panel.asignados.ids())
    assert app.controlador.sistema.verificar_consistencia() == []


def test_despachar_sin_seleccion_no_hace_nada(app: Any) -> None:
    app.mostrar("alertas")
    bombear(app)
    app.paneles["alertas"].despachar()
    bombear(app)
    assert "Seleccione" in app._estado.cget("text")


def test_el_mapa_dibuja_la_red_y_la_ruta(app: Any) -> None:
    app.mostrar("red")
    bombear(app)
    lienzo = app.paneles["red"].lienzo
    datos = app.controlador.sistema.datos
    assert len(lienzo.find_withtag("nodo")) == len(datos.centros) + len(datos.municipios)
    assert len(lienzo.find_withtag("via")) == len(datos.vias)
    panel = app.paneles["red"]
    panel._elegir_nodo(datos.centros[0].id)
    panel._elegir_nodo(datos.municipios[0].id)
    bombear(app)
    assert lienzo.ruta is not None
    assert "tramo" in panel.resultado.cget("text")


def test_guardar_desde_la_ventana(app: Any) -> None:
    assert app.boton_guardar.instate(["disabled"])
    app.paneles["alertas"].descartar()
    app.paneles["alertas"].asignar()
    bombear(app)
    assert not app.boton_guardar.instate(["disabled"])
    app.guardar()
    bombear(app)
    assert not app.controlador.cambios_sin_guardar
    assert (app.controlador.carpeta / "lotes.csv").exists()
    assert "guardado" in app._chip.cget("text")


def test_cerrar_con_cambios_pregunta(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app.paneles["alertas"].asignar()
    bombear(app)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: None)
    app.cerrar()                                    # cancelar: la ventana sigue abierta
    assert app.raiz.winfo_exists()
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: True)
    app.cerrar()                                    # sí: guarda y cierra
    assert not app.controlador.cambios_sin_guardar
    assert (app.controlador.carpeta / "lotes.csv").exists()
    with pytest.raises(tk.TclError):
        app.raiz.winfo_exists()


def test_fecha_de_operacion_por_linea_de_comandos(monkeypatch: pytest.MonkeyPatch) -> None:
    from donaciones import interfaz
    with pytest.raises(SystemExit):
        interfaz.main(["14/11/2026"])
    assert interfaz.nombre_corto("Aeropuerto Palonegro") == "Palonegro"
    assert date.fromisoformat("2026-11-14")          # el formato que sí se acepta
