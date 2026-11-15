"""
interfaz.py — Fase 4: la ventana del sistema, en Tkinter.

Ejecutar desde la carpeta del proyecto:

    python -m donaciones.interfaz               fecha de operación: hoy
    python -m donaciones.interfaz 2026-11-10    otra fecha de operación

Este módulo solo dibuja y reacciona a clics; la lógica está en
controlador.py. Toda operación sobre los datos corre en segundo plano (ver
Ejecutor), así que la ventana no se congela mientras trabaja.

Cinco paneles, uno por pregunta del operador:
  Resumen               ¿cómo vamos?
  Inventario            ¿qué hay y dónde?
  Registrar ingreso     llegó una donación
  Alertas y despacho    ¿qué falta y qué sale hoy?
  Red de distribución   ¿por dónde llega la ayuda?
"""
from __future__ import annotations

import functools
import math
import sys
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Any, Literal, TypeVar

from .controlador import (
    NOMBRE_CATEGORIA, NOMBRE_ESTADO, NOMBRE_URGENCIA, UNIDAD_PLURAL, Controlador, ErrorFormulario,
    Fila, FiltrosInventario, Indicador, Mapa, NodoMapa, Opcion, Resumen, ResultadoDespacho, Tabla,
    cantidad, escala_flujo, fecha_corta, numero,
)
from .estructuras import Criterio, Ruta
from .modelo import Categoria, ErrorValidacion, EstadoLote, EstadoVia, Lote, Urgencia
from .operaciones import Alerta, ErrorOperacion
from .persistencia import CARPETA_DATOS, ErrorArchivo

T = TypeVar("T")
Ancla = Literal["w", "e", "center"]

# ============================================================
# Diseño: colores y tipografía
# ============================================================

C = {
    "fondo": "#EEF1F4", "panel": "#FFFFFF", "tinta": "#1F2A33", "tenue": "#5F6B76",
    "borde": "#D5DBE1", "linea": "#E7EBEF", "cabecera": "#F5F7F9", "seleccion": "#DCE8F5",
    "barra": "#1F2A33", "barra_texto": "#C9D2DA", "barra_tenue": "#7E8B96",
    "barra_activa": "#2F3E4A", "barra_hover": "#27353F",
    "acento": "#2563A6", "acento_hover": "#2B6FB8", "acento_presion": "#1D4F86", "ruta": "#0B3D6E",
    "critico": "#B42318", "critico_suave": "#FDECEA",
    "alerta": "#B54708", "alerta_suave": "#FEF3E2",
    "ok": "#1E7B4F", "ok_suave": "#E7F5EE",
}
COLOR_CATEGORIA = {
    Categoria.MEDICO: "#7A4EA3", Categoria.VIVERES: "#A8741A", Categoria.AGUA: "#1F6FB2",
    Categoria.REFUGIO: "#23807A", Categoria.RESCATE: "#5B6672",
}
COLOR_URGENCIA = {
    Urgencia.CRITICA: C["critico"], Urgencia.ALTA: C["alerta"],
    Urgencia.MEDIA: "#C9A227", Urgencia.BAJA: "#6B8E5A",
}
COLOR_VIA = {EstadoVia.TRANSITABLE: "#8C99A6", EstadoVia.RESTRINGIDA: "#D68A3C",
             EstadoVia.CERRADA: C["critico"]}
COLOR_TONO = {"neutro": C["tinta"], "critico": C["critico"], "alerta": C["alerta"], "ok": C["ok"]}


class Fuentes:
    """Segoe UI en Windows; en otros sistemas, la primera parecida que exista."""

    def __init__(self, raiz: tk.Misc) -> None:
        disponibles = set(tkfont.families(raiz))
        f = next((x for x in ("Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial", "Helvetica") if x in disponibles),
                 "TkDefaultFont")
        self.normal = (f, 10)
        self.negrita = (f, 10, "bold")
        self.pequena = (f, 9)
        self.etiqueta = (f, 9, "bold")
        self.subtitulo = (f, 12, "bold")
        self.titulo = (f, 18, "bold")
        self.cifra = (f, 24, "bold")
        self.marca = (f, 14, "bold")
        for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(nombre, raiz).configure(family=f, size=10)


def configurar_estilos(raiz: tk.Tk, f: Fuentes, px: Callable[[float], int]) -> None:
    e = ttk.Style(raiz)
    e.theme_use("clam")
    plano = {"bordercolor": C["borde"], "lightcolor": C["panel"], "darkcolor": C["panel"]}
    e.configure(".", background=C["panel"], foreground=C["tinta"], font=f.normal,
                troughcolor=C["fondo"], focuscolor=C["acento"], **plano)

    e.configure("TButton", padding=(px(14), px(7)), relief="solid", borderwidth=1, font=f.normal, **plano)
    e.map("TButton", background=[("disabled", C["fondo"]), ("pressed", "#E3E8ED"), ("active", "#F3F5F7")],
          foreground=[("disabled", C["barra_tenue"])])
    acento = {"background": C["acento"], "bordercolor": C["acento"], "lightcolor": C["acento"],
              "darkcolor": C["acento"]}
    e.configure("Acento.TButton", foreground="white", font=f.negrita, **acento)
    estados = [("disabled", "#9DB7D3"), ("pressed", C["acento_presion"]), ("active", C["acento_hover"])]
    e.map("Acento.TButton", foreground=[("disabled", "white")], background=estados,
          bordercolor=estados, lightcolor=estados, darkcolor=estados)

    for tipo in ("TEntry", "TCombobox"):
        e.configure(tipo, padding=(px(8), px(5)), fieldbackground=C["panel"], insertcolor=C["tinta"],
                    arrowcolor=C["tenue"], **plano)
        e.map(tipo, bordercolor=[("focus", C["acento"])], lightcolor=[("focus", C["acento"])],
              fieldbackground=[("disabled", C["fondo"]), ("readonly", C["panel"])],
              foreground=[("disabled", C["barra_tenue"])],
              selectbackground=[("readonly", C["panel"])], selectforeground=[("readonly", C["tinta"])])
        e.configure(f"Error.{tipo}", bordercolor=C["critico"], lightcolor=C["critico"])
        e.map(f"Error.{tipo}", bordercolor=[("focus", C["critico"])], lightcolor=[("focus", C["critico"])])
    raiz.option_add("*TCombobox*Listbox.font", f.normal)
    raiz.option_add("*TCombobox*Listbox.selectBackground", C["acento"])

    for tipo in ("TCheckbutton", "TRadiobutton"):
        e.configure(tipo, background=C["panel"], indicatorbackground=C["panel"],
                    indicatormargin=(0, 0, px(6), 0), padding=(0, px(3)))
        e.map(tipo, background=[("active", C["panel"])],
              indicatorbackground=[("selected", C["acento"]), ("pressed", C["seleccion"])],
              indicatorforeground=[("selected", "white")])

    e.configure("Segmento.Toolbutton", padding=(px(14), px(5)), background=C["panel"], anchor="center",
                relief="solid", borderwidth=1, **plano)
    e.map("Segmento.Toolbutton", background=[("selected", C["acento"]), ("active", "#F3F5F7")],
          foreground=[("selected", "white")], bordercolor=[("selected", C["acento"])])

    e.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], rowheight=px(28),
                borderwidth=0, font=f.normal)
    e.map("Treeview", background=[("selected", C["seleccion"])], foreground=[("selected", C["tinta"])])
    e.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    e.configure("Treeview.Heading", background=C["cabecera"], foreground=C["tenue"], font=f.etiqueta,
                relief="flat", padding=(px(8), px(6)), bordercolor=C["linea"],
                lightcolor=C["cabecera"], darkcolor=C["linea"])
    e.map("Treeview.Heading", background=[("active", "#EBEFF3")])

    for orientacion in ("Vertical", "Horizontal"):
        e.configure(f"{orientacion}.TScrollbar", background="#D9DFE5", troughcolor=C["panel"],
                    bordercolor=C["panel"], lightcolor="#D9DFE5", darkcolor="#D9DFE5",
                    arrowcolor=C["tenue"], gripcount=0, arrowsize=px(12))
        e.map(f"{orientacion}.TScrollbar", background=[("active", "#C3CCD4")])
    e.configure("Horizontal.TProgressbar", background=C["acento"], troughcolor="#DDE3E9",
                bordercolor="#DDE3E9", lightcolor=C["acento"], darkcolor=C["acento"], thickness=px(5))


# ============================================================
# Piezas reutilizables
# ============================================================

class Tarjeta(tk.Frame):
    """Caja blanca con borde fino: título, descripción, acciones a la derecha y cuerpo."""

    def __init__(self, padre: tk.Misc, app: Aplicacion, titulo: str = "", descripcion: str = "") -> None:
        super().__init__(padre, bg=C["panel"], highlightthickness=1, highlightbackground=C["borde"],
                         highlightcolor=C["borde"])
        px = app.px
        self.encabezado = tk.Frame(self, bg=C["panel"])
        self.acciones = tk.Frame(self.encabezado, bg=C["panel"])
        if titulo:
            self.encabezado.pack(fill="x", padx=px(18), pady=(px(14), 0))
            textos = tk.Frame(self.encabezado, bg=C["panel"])
            textos.pack(side="left", fill="x", expand=True)
            tk.Label(textos, text=titulo, font=app.f.subtitulo, bg=C["panel"], fg=C["tinta"],
                     anchor="w").pack(fill="x")
            if descripcion:
                self.descripcion = tk.Label(textos, text=descripcion, font=app.f.pequena, bg=C["panel"],
                                            fg=C["tenue"], anchor="w", justify="left")
                self.descripcion.pack(fill="x")
            self.acciones.pack(side="right")
        self.cuerpo = tk.Frame(self, bg=C["panel"])
        self.cuerpo.pack(fill="both", expand=True, padx=px(18), pady=(px(10), px(16)))


class TarjetaIndicador(tk.Frame):
    def __init__(self, padre: tk.Misc, app: Aplicacion) -> None:
        super().__init__(padre, bg=C["panel"], highlightthickness=1, highlightbackground=C["borde"])
        px = app.px
        self.franja = tk.Frame(self, bg=C["borde"], height=px(4))
        self.franja.pack(fill="x")
        interior = tk.Frame(self, bg=C["panel"])
        interior.pack(fill="both", expand=True, padx=px(18), pady=(px(12), px(14)))
        self.titulo = tk.Label(interior, font=app.f.etiqueta, bg=C["panel"], fg=C["tenue"], anchor="w")
        self.valor = tk.Label(interior, text="…", font=app.f.cifra, bg=C["panel"], fg=C["tinta"], anchor="w")
        self.detalle = tk.Label(interior, font=app.f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w")
        for w in (self.titulo, self.valor, self.detalle):
            w.pack(fill="x")

    def mostrar(self, indicador: Indicador) -> None:
        color = COLOR_TONO[indicador.tono]
        self.franja.configure(bg=C["borde"] if indicador.tono == "neutro" else color)
        self.titulo.configure(text=indicador.titulo.upper())
        self.valor.configure(text=indicador.valor, fg=color)
        self.detalle.configure(text=indicador.detalle)


@dataclass(frozen=True)
class Columna:
    titulo: str
    ancho: int
    alineacion: Ancla = "w"
    estirar: bool = False


class TablaVista(tk.Frame):
    """Treeview con barra de desplazamiento, filas coloreadas por tono,
    orden al hacer clic en el encabezado y un mensaje cuando está vacía."""

    def __init__(self, padre: tk.Misc, app: Aplicacion, columnas: Sequence[Columna], alto: int = 10,
                 seleccion: str = "browse") -> None:
        super().__init__(padre, bg=C["panel"], highlightthickness=1, highlightbackground=C["linea"])
        self.app = app
        self.arbol = ttk.Treeview(self, show="headings", height=alto, selectmode=seleccion)  # type: ignore[arg-type]
        barra = ttk.Scrollbar(self, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=barra.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.arbol.tag_configure("par", background="#F9FAFB")
        self.arbol.tag_configure("alerta", background=C["alerta_suave"])
        self.arbol.tag_configure("critico", background=C["critico_suave"], foreground=C["critico"])
        self.vacio = tk.Label(self, bg=C["panel"], fg=C["tenue"], font=app.f.normal)
        self._filas: list[Fila] = []
        self._orden: tuple[int, bool] | None = None
        self.definir_columnas(columnas)

    def definir_columnas(self, columnas: Sequence[Columna]) -> None:
        self._columnas = list(columnas)
        ids = [f"c{i}" for i in range(len(columnas))]
        self.arbol.configure(columns=ids, displaycolumns=ids)
        for i, (cid, col) in enumerate(zip(ids, columnas)):
            self.arbol.heading(cid, text=col.titulo, anchor=col.alineacion,
                               command=functools.partial(self.ordenar, i))
            self.arbol.column(cid, width=self.app.px(col.ancho), minwidth=self.app.px(48),
                              anchor=col.alineacion, stretch=col.estirar)
        self._orden = None

    def cargar(self, filas: Sequence[Fila], vacio: str = "Sin resultados") -> None:
        seleccion = set(self.arbol.selection())
        self._filas = list(filas)
        if self._orden is not None:
            self._filas.sort(key=lambda f: f.clave(self._orden[0]) if self._orden else 0,
                             reverse=self._orden[1])
        self.arbol.delete(*self.arbol.get_children())
        for i, fila in enumerate(self._filas):
            tags = (fila.tono,) if fila.tono else (("par",) if i % 2 else ())
            self.arbol.insert("", "end", iid=fila.id, values=fila.valores, tags=tags)
        conservar = [i for i in seleccion if self.arbol.exists(i)]
        if conservar:
            self.arbol.selection_set(conservar)
        if self._filas:
            self.vacio.place_forget()
        else:
            self.vacio.configure(text=vacio)
            self.vacio.place(relx=0.5, rely=0.55, anchor="center")
        self._marcar_encabezados()

    def ordenar(self, columna: int) -> None:
        descendente = self._orden == (columna, False)
        self._orden = (columna, descendente)
        self.cargar(self._filas)

    def _marcar_encabezados(self) -> None:
        for i, col in enumerate(self._columnas):
            flecha = ""
            if self._orden is not None and self._orden[0] == i:
                flecha = "  ▼" if self._orden[1] else "  ▲"
            self.arbol.heading(f"c{i}", text=col.titulo + flecha)

    def seleccionados(self) -> list[str]:
        return list(self.arbol.selection())

    def ids(self) -> list[str]:
        return list(self.arbol.get_children())


class Campo(tk.Frame):
    """Etiqueta, control y mensaje de error debajo (con su espacio reservado,
    para que el formulario no salte al aparecer un error)."""

    def __init__(self, padre: tk.Misc, app: Aplicacion, etiqueta: str) -> None:
        super().__init__(padre, bg=C["panel"])
        tk.Label(self, text=etiqueta, font=app.f.etiqueta, bg=C["panel"], fg=C["tenue"],
                 anchor="w").pack(fill="x")
        self.fila = tk.Frame(self, bg=C["panel"])
        self.fila.pack(fill="x", pady=(app.px(3), 0))
        self.error = tk.Label(self, text=" ", font=app.f.pequena, bg=C["panel"], fg=C["critico"],
                              anchor="w", justify="left")
        self.error.pack(fill="x")
        self.control: ttk.Entry | ttk.Combobox | None = None

    def poner(self, control: ttk.Entry | ttk.Combobox) -> None:
        self.control = control
        control.pack(in_=self.fila, side="left", fill="x", expand=True)

    def marcar(self, mensaje: str | None) -> None:
        self.error.configure(text=mensaje or " ")
        if self.control is not None:
            base = "TCombobox" if isinstance(self.control, ttk.Combobox) else "TEntry"
            self.control.configure(style=f"Error.{base}" if mensaje else base)


# ============================================================
# Ventana principal
# ============================================================

class Aplicacion:
    PANELES = (("resumen", "Resumen"), ("inventario", "Inventario"), ("registro", "Registrar ingreso"),
               ("alertas", "Alertas y despacho"), ("red", "Red de distribución"))

    def __init__(self, raiz: tk.Tk, controlador: Controlador, rechazos: int = 0) -> None:
        self.raiz = raiz
        self.controlador = controlador
        self._escala = max(1.0, raiz.winfo_fpixels("1i") / 96)
        self.f = Fuentes(raiz)
        configurar_estilos(raiz, self.f, self.px)

        raiz.title("Sistema de donaciones post-sismo")
        raiz.configure(bg=C["fondo"])
        raiz.geometry(f"{self.px(1320)}x{self.px(840)}")
        raiz.minsize(self.px(1120), self.px(720))
        raiz.columnconfigure(1, weight=1)
        raiz.rowconfigure(0, weight=1)

        self._construir_barra_lateral()
        principal = tk.Frame(raiz, bg=C["fondo"])
        principal.grid(row=0, column=1, sticky="nsew")
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(1, weight=1)
        self._construir_encabezado(principal)
        contenido = tk.Frame(principal, bg=C["fondo"])
        contenido.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(18)))
        contenido.columnconfigure(0, weight=1)
        contenido.rowconfigure(0, weight=1)
        self._construir_barra_estado(principal)

        self.paneles: dict[str, Panel] = {
            "resumen": PanelResumen(contenido, self), "inventario": PanelInventario(contenido, self),
            "registro": PanelRegistro(contenido, self), "alertas": PanelAlertas(contenido, self),
            "red": PanelRed(contenido, self),
        }
        for panel in self.paneles.values():
            panel.grid(row=0, column=0, sticky="nsew")
        self.actual = ""

        for i, (clave, _) in enumerate(self.PANELES, start=1):
            raiz.bind_all(f"<Control-Key-{i}>", functools.partial(self._atajo, clave))
        raiz.bind_all("<Control-s>", lambda _e: self.guardar())
        raiz.protocol("WM_DELETE_WINDOW", self.cerrar)

        datos = controlador.sistema.datos
        mensaje = (f"Datos cargados: {numero(len(datos.lotes))} lotes, {len(datos.necesidades)} "
                   f"necesidades, {len(datos.centros)} centros.")
        if rechazos:
            mensaje += (f" {rechazos} registro(s) rechazado(s) al cargar: revíselos con "
                        "python -m donaciones.persistencia")
        self.estado(mensaje)
        self.mostrar("resumen")
        self._revisar_pendientes()

    def px(self, n: float) -> int:
        """Pixeles escalados a la densidad de la pantalla."""
        return round(n * self._escala)

    # ---------- Estructura ----------

    def _construir_barra_lateral(self) -> None:
        px = self.px
        barra = tk.Frame(self.raiz, bg=C["barra"], width=px(232))
        barra.grid(row=0, column=0, sticky="ns")
        barra.pack_propagate(False)

        marca = tk.Frame(barra, bg=C["barra"])
        marca.pack(fill="x", padx=px(22), pady=(px(26), px(28)))
        logo = tk.Canvas(marca, width=px(30), height=px(30), bg=C["barra"], highlightthickness=0)
        logo.create_oval(px(2), px(2), px(28), px(28), fill=C["acento"], outline="")
        logo.create_line(px(15), px(8), px(15), px(22), fill="white", width=px(3))
        logo.create_line(px(8), px(15), px(22), px(15), fill="white", width=px(3))
        logo.pack(side="left", padx=(0, px(10)))
        textos = tk.Frame(marca, bg=C["barra"])
        textos.pack(side="left")
        tk.Label(textos, text="Donaciones", font=self.f.marca, bg=C["barra"], fg="white",
                 anchor="w").pack(fill="x")
        tk.Label(textos, text="Respuesta al sismo", font=self.f.pequena, bg=C["barra"],
                 fg=C["barra_tenue"], anchor="w").pack(fill="x")

        tk.Label(barra, text="PANELES", font=self.f.etiqueta, bg=C["barra"], fg=C["barra_tenue"],
                 anchor="w").pack(fill="x", padx=px(24), pady=(0, px(6)))
        self._navegacion: dict[str, tuple[tk.Frame, tk.Frame, list[tk.Label]]] = {}
        for i, (clave, nombre) in enumerate(self.PANELES, start=1):
            item = tk.Frame(barra, bg=C["barra"], cursor="hand2")
            item.pack(fill="x", padx=px(10), pady=px(1))
            indicador = tk.Frame(item, bg=C["barra"], width=px(3))
            indicador.pack(side="left", fill="y")
            texto = tk.Label(item, text=nombre, font=self.f.normal, bg=C["barra"], fg=C["barra_texto"],
                             anchor="w", padx=px(12), pady=px(9))
            texto.pack(side="left", fill="x", expand=True)
            atajo = tk.Label(item, text=f"Ctrl+{i}", font=self.f.pequena, bg=C["barra"],
                             fg=C["barra_tenue"], padx=px(10))
            atajo.pack(side="right")
            for w in (item, texto, atajo):
                w.bind("<Button-1>", functools.partial(self._atajo, clave))
                w.bind("<Enter>", functools.partial(self._resaltar_nav, clave, True))
                w.bind("<Leave>", functools.partial(self._resaltar_nav, clave, False))
            self._navegacion[clave] = (item, indicador, [texto, atajo])

        pie = tk.Frame(barra, bg=C["barra"])
        pie.pack(side="bottom", fill="x", padx=px(24), pady=px(20))
        tk.Label(pie, text="Santander, Colombia", font=self.f.pequena, bg=C["barra"],
                 fg=C["barra_texto"], anchor="w").pack(fill="x")
        tk.Label(pie, text="Sismo del 3 nov 2026", font=self.f.pequena, bg=C["barra"],
                 fg=C["barra_tenue"], anchor="w").pack(fill="x")

    def _construir_encabezado(self, padre: tk.Frame) -> None:
        px = self.px
        encabezado = tk.Frame(padre, bg=C["fondo"])
        encabezado.grid(row=0, column=0, sticky="ew", padx=px(28), pady=(px(22), px(16)))
        textos = tk.Frame(encabezado, bg=C["fondo"])
        textos.pack(side="left", fill="x", expand=True)
        self._titulo = tk.Label(textos, font=self.f.titulo, bg=C["fondo"], fg=C["tinta"], anchor="w")
        self._titulo.pack(fill="x")
        self._subtitulo = tk.Label(textos, font=self.f.normal, bg=C["fondo"], fg=C["tenue"], anchor="w")
        self._subtitulo.pack(fill="x")

        derecha = tk.Frame(encabezado, bg=C["fondo"])
        derecha.pack(side="right")
        self.boton_guardar = ttk.Button(derecha, text="Guardar cambios", style="Acento.TButton",
                                        command=self.guardar)
        self.boton_guardar.pack(side="right")
        self._chip = tk.Label(derecha, font=self.f.etiqueta, padx=px(10), pady=px(4))
        self._chip.pack(side="right", padx=(0, px(12)))
        fecha = tk.Frame(derecha, bg=C["fondo"])
        fecha.pack(side="right", padx=(0, px(18)))
        tk.Label(fecha, text="FECHA DE OPERACIÓN", font=self.f.etiqueta, bg=C["fondo"], fg=C["tenue"],
                 anchor="e").pack(fill="x")
        tk.Label(fecha, text=fecha_corta(self.controlador.hoy), font=self.f.negrita, bg=C["fondo"],
                 fg=C["tinta"], anchor="e").pack(fill="x")
        self._actualizar_chip()

    def _construir_barra_estado(self, padre: tk.Frame) -> None:
        px = self.px
        barra = tk.Frame(padre, bg=C["panel"], highlightthickness=1, highlightbackground=C["borde"])
        barra.grid(row=2, column=0, sticky="ew")
        self._estado = tk.Label(barra, font=self.f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w",
                                padx=px(28), pady=px(7))
        self._estado.pack(side="left", fill="x", expand=True)
        self._progreso = ttk.Progressbar(barra, mode="indeterminate", length=px(140))
        self._trabajando = False

    # ---------- Navegación ----------

    def _atajo(self, clave: str, _evento: object = None) -> None:
        self.mostrar(clave)

    def _resaltar_nav(self, clave: str, dentro: bool, _evento: object = None) -> None:
        if clave == self.actual:
            return
        item, _, etiquetas = self._navegacion[clave]
        color = C["barra_hover"] if dentro else C["barra"]
        widgets: list[tk.Frame | tk.Label] = [item, *etiquetas]
        for w in widgets:
            w.configure(bg=color)

    def mostrar(self, clave: str) -> None:
        self.actual = clave
        for k, (item, indicador, (texto, atajo)) in self._navegacion.items():
            activo = k == clave
            fondo = C["barra_activa"] if activo else C["barra"]
            item.configure(bg=fondo)
            indicador.configure(bg="#6FA8DC" if activo else fondo)
            texto.configure(bg=fondo, fg="white" if activo else C["barra_texto"],
                            font=self.f.negrita if activo else self.f.normal)
            atajo.configure(bg=fondo)
        panel = self.paneles[clave]
        self._titulo.configure(text=panel.titulo)
        self._subtitulo.configure(text=panel.subtitulo)
        panel.tkraise()
        panel.al_mostrar()

    # ---------- Trabajo en segundo plano ----------

    def correr(self, tarea: Callable[[], T], al_terminar: Callable[[T], None],
               al_fallar: Callable[[Exception], None] | None = None, accion: str | None = None,
               mensaje: str = "") -> bool:
        """Ejecuta la tarea en segundo plano. Devuelve False si la acción ya estaba en curso."""
        def terminar(resultado: T) -> None:
            self._actualizar_chip()
            if mensaje and self._estado.cget("text") == mensaje:
                self.estado("Listo.")
            al_terminar(resultado)

        def fallar(error: Exception) -> None:
            self._actualizar_chip()
            (al_fallar or self.mostrar_error)(error)

        aceptada = self.controlador.ejecutor.ejecutar(tarea, terminar, fallar, accion)
        if aceptada and mensaje:
            self.estado(mensaje)
        return aceptada

    def _revisar_pendientes(self) -> None:
        self.controlador.ejecutor.procesar_pendientes()
        ocupado = self.controlador.ejecutor.ocupado
        if ocupado != self._trabajando:
            self._trabajando = ocupado
            if ocupado:
                self._progreso.pack(side="right", padx=self.px(20))
                self._progreso.start(12)
            else:
                self._progreso.stop()
                self._progreso.pack_forget()
        self.raiz.config(cursor="watch" if ocupado else "")
        self._tarea_revision = self.raiz.after(40, self._revisar_pendientes)

    def datos_cambiaron(self) -> None:
        """Una operación cambió los datos: cada panel se recarga la próxima vez que se vea."""
        for panel in self.paneles.values():
            panel.vigente = False
        self.paneles[self.actual].al_mostrar()

    # ---------- Mensajes ----------

    def estado(self, texto: str) -> None:
        self._estado.configure(text=texto)

    def avisar(self, titulo: str, texto: str, error: bool = False) -> None:
        (messagebox.showerror if error else messagebox.showinfo)(titulo, texto, parent=self.raiz)

    def confirmar(self, titulo: str, texto: str) -> bool:
        return bool(messagebox.askyesno(titulo, texto, parent=self.raiz))

    def mostrar_error(self, error: Exception) -> None:
        if isinstance(error, (ErrorOperacion, ErrorValidacion)):
            self.estado(f"No se pudo completar: {error}")
            self.avisar("No se pudo completar", str(error))
        else:
            self.estado(f"Error inesperado: {error}")
            self.avisar("Error inesperado", f"{type(error).__name__}: {error}", error=True)

    # ---------- Guardar y cerrar ----------

    def _actualizar_chip(self) -> None:
        if self.controlador.cambios_sin_guardar:
            self._chip.configure(text="●  Cambios sin guardar", bg=C["alerta_suave"], fg=C["alerta"])
            self.boton_guardar.state(["!disabled"])
        else:
            self._chip.configure(text="●  Todo guardado", bg=C["ok_suave"], fg=C["ok"])
            self.boton_guardar.state(["disabled"])

    def guardar(self) -> None:
        if not self.controlador.cambios_sin_guardar:
            return
        self.correr(self.controlador.guardar,
                    lambda _r: self.estado(f"Cambios guardados en {self.controlador.carpeta}."),
                    accion="guardar", mensaje="Guardando…")

    def cerrar(self) -> None:
        if self.controlador.cambios_sin_guardar:
            respuesta = messagebox.askyesnocancel(
                "Cambios sin guardar", "Hay cambios sin guardar. ¿Guardarlos antes de salir?",
                parent=self.raiz)
            if respuesta is None:
                return
            if respuesta:
                try:
                    self.controlador.guardar()
                except OSError as e:
                    self.avisar("No se pudo guardar", str(e), error=True)
                    return
        self.destruir()

    def destruir(self) -> None:
        self.raiz.after_cancel(self._tarea_revision)
        self.controlador.ejecutor.cerrar()
        self.raiz.destroy()


# ============================================================
# Paneles
# ============================================================

class Panel(tk.Frame):
    titulo = ""
    subtitulo = ""

    def __init__(self, padre: tk.Misc, app: Aplicacion) -> None:
        super().__init__(padre, bg=C["fondo"])
        self.app = app
        self.ctrl = app.controlador
        self.vigente = False
        self.construir()

    def construir(self) -> None:
        raise NotImplementedError

    def al_mostrar(self) -> None:
        if not self.vigente:
            self.vigente = True
            self.actualizar()

    def actualizar(self) -> None:
        raise NotImplementedError


# ---------- Resumen ----------

class PanelResumen(Panel):
    titulo = "Resumen"
    subtitulo = "Cómo va la atención: necesidades cubiertas, faltantes y lotes por vencer"

    def construir(self) -> None:
        px = self.app.px
        for i in range(4):
            self.columnconfigure(i, weight=1, uniform="kpi")
        self.rowconfigure(1, weight=1)
        self.indicadores = [TarjetaIndicador(self, self.app) for _ in range(4)]
        for i, t in enumerate(self.indicadores):
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(8), 0 if i == 3 else px(8)))

        cobertura = Tarjeta(self, self.app, "Cobertura por categoría",
                            "Parte de lo que piden los municipios que ya tiene ayuda asignada o despachada")
        cobertura.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(px(16), 0), padx=(0, px(8)))
        self.lienzo = tk.Canvas(cobertura.cuerpo, bg=C["panel"], highlightthickness=0, height=px(300))
        self.lienzo.pack(fill="both", expand=True)
        self.lienzo.bind("<Configure>", lambda _e: self._dibujar_coberturas())
        self._resumen: Resumen | None = None

        prioridad = Tarjeta(self, self.app, "Atender primero",
                            "Necesidades sin cubrir, de la más urgente a la menos urgente")
        prioridad.grid(row=1, column=2, columnspan=2, sticky="nsew", pady=(px(16), 0), padx=(px(8), 0))
        ttk.Button(prioridad.acciones, text="Ver todas",
                   command=lambda: self.app.mostrar("alertas")).pack()
        self.lista = tk.Frame(prioridad.cuerpo, bg=C["panel"])
        self.lista.pack(fill="both", expand=True)

    def actualizar(self) -> None:
        self.app.correr(self.ctrl.resumen, self._mostrar)

    def _mostrar(self, resumen: Resumen) -> None:
        self._resumen = resumen
        for tarjeta, indicador in zip(self.indicadores, resumen.indicadores):
            tarjeta.mostrar(indicador)
        self._dibujar_coberturas()
        self._mostrar_prioridades(resumen.atender_primero)

    def _dibujar_coberturas(self) -> None:
        lz, px, f = self.lienzo, self.app.px, self.app.f
        lz.delete("all")
        if self._resumen is None:
            return
        ancho = max(lz.winfo_width(), px(200))
        alto_fila = px(62)
        for i, c in enumerate(self._resumen.coberturas):
            y = i * alto_fila + px(6)
            color = COLOR_CATEGORIA[c.categoria]
            lz.create_oval(0, y + px(4), px(10), y + px(14), fill=color, outline="")
            lz.create_text(px(18), y + px(9), text=NOMBRE_CATEGORIA[c.categoria], anchor="w",
                           font=f.negrita, fill=C["tinta"])
            porcentaje = round(100 * c.fraccion)
            lz.create_text(ancho - px(2), y + px(9), text=f"{porcentaje} %", anchor="e", font=f.negrita,
                           fill=C["ok"] if porcentaje >= 100 else C["tinta"])
            grosor = px(10)
            yb = y + px(28)
            lz.create_line(grosor // 2, yb, ancho - grosor // 2, yb, fill=C["linea"], width=grosor,
                           capstyle="round")
            if c.fraccion > 0:
                fin = grosor // 2 + (ancho - grosor) * c.fraccion
                lz.create_line(grosor // 2, yb, max(fin, grosor // 2 + 1), yb, fill=color, width=grosor,
                               capstyle="round")
            detalle = (f"Cubierto {cantidad(c.cubierto, c.categoria)} de {numero(c.necesidad)}   ·   "
                       f"disponible en centros: {cantidad(c.disponible, c.categoria)}")
            lz.create_text(0, y + px(46), text=detalle, anchor="w", font=f.pequena, fill=C["tenue"])
        lz.configure(height=len(self._resumen.coberturas) * alto_fila + px(8))

    def _mostrar_prioridades(self, alertas: list[Alerta]) -> None:
        px, f = self.app.px, self.app.f
        for w in self.lista.winfo_children():
            w.destroy()
        if not alertas:
            tk.Label(self.lista, text="Todas las necesidades están cubiertas.", font=f.negrita,
                     bg=C["panel"], fg=C["ok"]).pack(pady=px(30))
            return
        for i, a in enumerate(alertas):
            fila = tk.Frame(self.lista, bg=C["panel"])
            fila.pack(fill="x")
            if i:
                tk.Frame(self.lista, bg=C["linea"], height=1).pack(fill="x", before=fila)
            interior = tk.Frame(fila, bg=C["panel"])
            interior.pack(fill="x", pady=px(8))
            tk.Label(interior, text=NOMBRE_URGENCIA[a.municipio.urgencia], font=f.etiqueta, fg="white",
                     bg=COLOR_URGENCIA[a.municipio.urgencia], width=7, pady=px(2)).pack(side="left")
            textos = tk.Frame(interior, bg=C["panel"])
            textos.pack(side="left", fill="x", expand=True, padx=px(12))
            tk.Label(textos, text=a.municipio.nombre, font=f.negrita, bg=C["panel"], fg=C["tinta"],
                     anchor="w").pack(fill="x")
            tk.Label(textos, text=f"{NOMBRE_CATEGORIA[a.categoria]} · {numero(a.municipio.poblacion_afectada)}"
                     " personas afectadas", font=f.pequena, bg=C["panel"], fg=C["tenue"],
                     anchor="w").pack(fill="x")
            derecha = tk.Frame(interior, bg=C["panel"])
            derecha.pack(side="right")
            tk.Label(derecha, text=f"Faltan {cantidad(a.faltante, a.categoria)}", font=f.negrita,
                     bg=C["panel"], fg=C["critico"] if a.critica else C["tinta"], anchor="e").pack(fill="x")
            tk.Label(derecha, text="sin stock en la red" if a.critica else "hay stock para asignar",
                     font=f.pequena, bg=C["panel"], fg=C["critico"] if a.critica else C["tenue"],
                     anchor="e").pack(fill="x")


# ---------- Inventario ----------

COLUMNAS_LOTES = [
    Columna("Código", 96), Columna("Categoría", 78), Columna("Descripción", 170, estirar=True),
    Columna("Cantidad", 108, "e"), Columna("Centro", 170, estirar=True), Columna("Caducidad", 96),
    Columna("Vence en", 74, "e"), Columna("Estado", 84), Columna("Destino", 104, estirar=True),
]
COLUMNAS_CENTROS = [
    Columna("Centro", 260, estirar=True), *(Columna(NOMBRE_CATEGORIA[c], 110, "e") for c in Categoria),
    Columna("Cadena de frío", 110, "center"),
]


class PanelInventario(Panel):
    titulo = "Inventario"
    subtitulo = "Lotes en especie: dónde están, cuándo vencen y a dónde van"
    TODOS = "Todos"
    VENCIMIENTOS = {"Cualquier fecha": None, "Vencidos": 0, "En 7 días": 7, "En 30 días": 30}

    def construir(self) -> None:
        px = self.app.px
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        filtros = Tarjeta(self, self.app)
        filtros.grid(row=0, column=0, sticky="ew", pady=(0, px(16)))
        cuerpo = filtros.cuerpo
        cuerpo.columnconfigure(0, weight=3)
        for i in range(1, 5):
            cuerpo.columnconfigure(i, weight=2)

        self.texto = tk.StringVar()
        self.categoria = tk.StringVar(value=self.TODOS)
        self.centro = tk.StringVar(value=self.TODOS)
        self.estado = tk.StringVar(value=self.TODOS)
        self.vencimiento = tk.StringVar(value="Cualquier fecha")
        self.modo = tk.StringVar(value="lotes")
        self._centros = self.ctrl.centros()

        def filtro(columna: int, etiqueta: str) -> tk.Frame:
            marco = tk.Frame(cuerpo, bg=C["panel"])
            marco.grid(row=0, column=columna, sticky="ew", padx=(0, px(12)))
            tk.Label(marco, text=etiqueta, font=self.app.f.etiqueta, bg=C["panel"], fg=C["tenue"],
                     anchor="w").pack(fill="x", pady=(0, px(3)))
            return marco

        self.buscar = ttk.Entry(filtro(0, "BUSCAR"), textvariable=self.texto)
        self.buscar.pack(fill="x")
        self.combos = [
            ttk.Combobox(filtro(1, "CATEGORÍA"), textvariable=self.categoria, state="readonly",
                         values=[self.TODOS, *NOMBRE_CATEGORIA.values()]),
            ttk.Combobox(filtro(2, "CENTRO"), textvariable=self.centro, state="readonly",
                         values=[self.TODOS, *(o.etiqueta for o in self._centros)]),
            ttk.Combobox(filtro(3, "ESTADO"), textvariable=self.estado, state="readonly",
                         values=[self.TODOS, *NOMBRE_ESTADO.values()]),
            ttk.Combobox(filtro(4, "VENCIMIENTO"), textvariable=self.vencimiento, state="readonly",
                         values=list(self.VENCIMIENTOS)),
        ]
        for combo in self.combos:
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda _e: self.actualizar())
        self._espera: str | None = None
        self.texto.trace_add("write", lambda *_: self._programar_busqueda())

        vista = tk.Frame(cuerpo, bg=C["panel"])
        vista.grid(row=0, column=5, sticky="se")
        tk.Label(vista, text="VER", font=self.app.f.etiqueta, bg=C["panel"], fg=C["tenue"],
                 anchor="w").pack(fill="x", pady=(0, px(3)))
        segmentos = tk.Frame(vista, bg=C["panel"])
        segmentos.pack()
        for valor, texto in (("lotes", "Lotes"), ("centros", "Por centro")):
            ttk.Radiobutton(segmentos, text=texto, value=valor, variable=self.modo,
                            style="Segmento.Toolbutton", command=self._cambiar_modo).pack(side="left")

        tabla = Tarjeta(self, self.app)
        tabla.grid(row=1, column=0, sticky="nsew")
        self.tabla = TablaVista(tabla.cuerpo, self.app, COLUMNAS_LOTES, alto=16)
        self.tabla.pack(fill="both", expand=True)
        leyenda = tk.Frame(tabla.cuerpo, bg=C["panel"])
        leyenda.pack(fill="x", pady=(px(10), 0))
        self.pie = tk.Label(leyenda, font=self.app.f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w")
        self.pie.pack(side="left")
        self.tonos = tk.Frame(leyenda, bg=C["panel"])
        self.tonos.pack(side="right")
        for texto, fondo, tinta in (("Vencido", C["critico_suave"], C["critico"]),
                                    (f"Vence en {self.ctrl.DIAS_POR_VENCER} días o menos",
                                     C["alerta_suave"], C["alerta"])):
            tk.Label(self.tonos, text=texto, font=self.app.f.pequena, bg=fondo, fg=tinta,
                     padx=px(8), pady=px(1)).pack(side="right", padx=(px(6), 0))

    def _programar_busqueda(self) -> None:
        """Espera a que el operador deje de escribir antes de buscar."""
        if self._espera is not None:
            self.after_cancel(self._espera)
        self._espera = self.after(300, self.actualizar)

    def _cambiar_modo(self) -> None:
        por_lotes = self.modo.get() == "lotes"
        self.tabla.definir_columnas(COLUMNAS_LOTES if por_lotes else COLUMNAS_CENTROS)
        if por_lotes:
            self.tonos.pack(side="right")
        else:
            self.tonos.pack_forget()
        estado = ["!disabled"] if por_lotes else ["disabled"]
        self.buscar.state(estado)
        for combo in self.combos:
            combo.state(estado + (["readonly"] if por_lotes else []))
        self.actualizar()

    def filtros(self) -> FiltrosInventario:
        def buscar(valor: str, opciones: dict[str, T]) -> T | None:
            return opciones.get(valor)

        categoria = buscar(self.categoria.get(), {v: k for k, v in NOMBRE_CATEGORIA.items()})
        estado = buscar(self.estado.get(), {v: k for k, v in NOMBRE_ESTADO.items()})
        centro = buscar(self.centro.get(), {o.etiqueta: o.id for o in self._centros})
        return FiltrosInventario(self.texto.get(), categoria, centro, estado,
                                 self.VENCIMIENTOS.get(self.vencimiento.get()))

    def actualizar(self) -> None:
        self._espera = None
        if self.modo.get() == "lotes":
            filtros = self.filtros()
            self.app.correr(lambda: self.ctrl.inventario(filtros), self._mostrar)
        else:
            self.app.correr(self.ctrl.inventario_por_centro, self._mostrar)

    def _mostrar(self, tabla: Tabla) -> None:
        self.tabla.cargar(tabla.filas, "Ningún lote coincide con los filtros.")
        self.pie.configure(text=tabla.pie)


# ---------- Registrar ingreso ----------

class PanelRegistro(Panel):
    titulo = "Registrar ingreso"
    subtitulo = "Una donación en especie que acaba de llegar a un centro de acopio"

    def construir(self) -> None:
        px, f = self.app.px, self.app.f
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        formulario = Tarjeta(self, self.app, "Datos del lote",
                             "Los campos se revisan con las mismas reglas que la carga de archivos")
        formulario.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        cuerpo = formulario.cuerpo
        cuerpo.columnconfigure((0, 1), weight=1, uniform="campos")

        self._donantes = self.ctrl.donantes()
        self._centros = self.ctrl.centros()
        self.campos: dict[str, Campo] = {}
        self.variables: dict[str, tk.StringVar] = {}

        def campo(nombre: str, etiqueta: str, fila: int, columna: int, ancho: int = 1,
                  opciones: list[str] | None = None) -> Campo:
            c = Campo(cuerpo, self.app, etiqueta)
            c.grid(row=fila, column=columna, columnspan=ancho, sticky="ew",
                   padx=(0 if columna == 0 and ancho == 1 else 0, px(14) if columna == 0 and ancho == 1 else 0),
                   pady=(0, px(4)))
            variable = tk.StringVar()
            control: ttk.Entry | ttk.Combobox
            if opciones is None:
                control = ttk.Entry(c, textvariable=variable)
            else:
                control = ttk.Combobox(c, textvariable=variable, values=opciones, state="readonly",
                                       height=14)
            c.poner(control)
            variable.trace_add("write", lambda *_: c.marcar(None))
            self.campos[nombre] = c
            self.variables[nombre] = variable
            return c

        campo("donante_id", "DONANTE", 0, 0, 2, [o.etiqueta for o in self._donantes])
        centro = campo("centro_id", "CENTRO DE ACOPIO", 1, 0, opciones=[o.etiqueta for o in self._centros])
        campo("categoria", "CATEGORÍA", 1, 1, opciones=list(NOMBRE_CATEGORIA.values()))
        campo("descripcion", "DESCRIPCIÓN", 2, 0, 2)
        cant = campo("cantidad", "CANTIDAD", 3, 0)
        campo("peso_kg", "PESO TOTAL (KG)", 3, 1)
        campo("volumen_m3", "VOLUMEN TOTAL (M³)", 4, 0)
        campo("fecha_ingreso", "FECHA DE INGRESO (AAAA-MM-DD)", 4, 1)
        campo("fecha_caducidad", "FECHA DE CADUCIDAD (AAAA-MM-DD)", 5, 0)

        self.unidad = tk.Label(cant.fila, text="", font=f.pequena, bg=C["panel"], fg=C["tenue"],
                               width=9, anchor="w")
        self.unidad.pack(side="left", padx=(px(8), 0))
        self.aviso_frio = tk.Label(centro.fila, text="", font=f.pequena, bg=C["panel"], fg=C["tenue"])
        self.aviso_frio.pack(side="left", padx=(px(8), 0))

        frio = Campo(cuerpo, self.app, "CONSERVACIÓN")
        frio.grid(row=5, column=1, sticky="ew", pady=(0, px(4)))
        self.frio = tk.BooleanVar()
        ttk.Checkbutton(frio.fila, text="Requiere cadena de frío", variable=self.frio,
                        command=lambda: frio.marcar(None)).pack(side="left")
        self.campos["requiere_frio"] = frio

        self.variables["categoria"].trace_add("write", lambda *_: self._categoria_cambio())
        self.variables["centro_id"].trace_add("write", lambda *_: self._centro_cambio())

        botones = tk.Frame(cuerpo, bg=C["panel"])
        botones.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        self.boton = ttk.Button(botones, text="Registrar ingreso", style="Acento.TButton",
                                command=self.registrar)
        self.boton.pack(side="left")
        ttk.Button(botones, text="Limpiar", command=self.limpiar).pack(side="left", padx=(px(10), 0))

        lateral = tk.Frame(self, bg=C["fondo"])
        lateral.grid(row=0, column=1, sticky="nsew")
        ultimo = Tarjeta(lateral, self.app, "Último ingreso registrado")
        ultimo.pack(fill="x")
        self.ultimo_codigo = tk.Label(ultimo.cuerpo, text="Ninguno todavía en esta sesión", font=f.negrita,
                                      bg=C["panel"], fg=C["tenue"], anchor="w")
        self.ultimo_codigo.pack(fill="x")
        self.ultimo_detalle = tk.Label(ultimo.cuerpo, text="", font=f.normal, bg=C["panel"],
                                       fg=C["tenue"], anchor="w", justify="left")
        self.ultimo_detalle.pack(fill="x")

        guia = Tarjeta(lateral, self.app, "Cómo llenar el formulario")
        guia.pack(fill="x", pady=(px(16), 0))
        for texto in (
            "Fechas como 2026-11-14 (año, mes y día).",
            "Decimales con punto: 12.5, no 12,5.",
            "Peso y volumen son del lote completo.",
            "Agua, víveres y médico vencen: la caducidad es obligatoria. Refugio y rescate no vencen.",
            "Si el lote requiere frío, el centro debe tener cadena de frío.",
            "Los cambios quedan en memoria hasta que pulse «Guardar cambios».",
        ):
            fila = tk.Frame(guia.cuerpo, bg=C["panel"])
            fila.pack(fill="x", pady=px(3))
            tk.Label(fila, text="•", font=f.negrita, bg=C["panel"], fg=C["acento"]).pack(side="left",
                                                                                        anchor="n")
            tk.Label(fila, text=texto, font=f.normal, bg=C["panel"], fg=C["tinta"], anchor="w",
                     justify="left", wraplength=px(330)).pack(side="left", fill="x", padx=(px(8), 0))
        self.limpiar()

    def al_mostrar(self) -> None:
        self.vigente = True                     # el formulario no depende de los datos

    def actualizar(self) -> None:
        pass

    def _categoria(self) -> Categoria | None:
        return {v: k for k, v in NOMBRE_CATEGORIA.items()}.get(self.variables["categoria"].get())

    def _categoria_cambio(self) -> None:
        categoria = self._categoria()
        self.unidad.configure(text="" if categoria is None else UNIDAD_PLURAL[categoria.unidad])
        caducidad = self.campos["fecha_caducidad"]
        assert caducidad.control is not None
        if categoria is not None and not categoria.perecedera:
            self.variables["fecha_caducidad"].set("")
            caducidad.control.state(["disabled"])
            caducidad.marcar(None)
        else:
            caducidad.control.state(["!disabled"])

    def _centro_cambio(self) -> None:
        opcion = self._opcion(self._centros, "centro_id")
        if opcion is None:
            self.aviso_frio.configure(text="")
        elif self.ctrl.centro_tiene_frio(opcion.id):
            self.aviso_frio.configure(text="con frío", fg=C["ok"])
        else:
            self.aviso_frio.configure(text="sin frío", fg=C["tenue"])

    def _opcion(self, opciones: list[Opcion], campo: str) -> Opcion | None:
        etiqueta = self.variables[campo].get()
        return next((o for o in opciones if o.etiqueta == etiqueta), None)

    def valores(self) -> dict[str, object]:
        donante = self._opcion(self._donantes, "donante_id")
        centro = self._opcion(self._centros, "centro_id")
        categoria = self._categoria()
        valores: dict[str, object] = {k: v.get().strip() for k, v in self.variables.items()}
        valores["donante_id"] = donante.id if donante else ""
        valores["centro_id"] = centro.id if centro else ""
        valores["categoria"] = categoria.value if categoria else ""
        valores["requiere_frio"] = self.frio.get()
        return valores

    def registrar(self) -> None:
        valores = self.valores()
        self.app.correr(lambda: self.ctrl.registrar_ingreso(valores), self._registrado, self._fallo,
                        accion="registrar", mensaje="Registrando ingreso…")

    def _registrado(self, lote: Lote) -> None:
        for c in self.campos.values():
            c.marcar(None)
        centro = next(o.etiqueta for o in self._centros if o.id == lote.centro_id)
        self.ultimo_codigo.configure(text=lote.id, fg=C["ok"], font=self.app.f.subtitulo)
        self.ultimo_detalle.configure(
            text=f"{lote.descripcion}\n{cantidad(lote.cantidad, lote.categoria)} de "
                 f"{NOMBRE_CATEGORIA[lote.categoria].lower()}\n{centro}\n"
                 f"Caducidad: {fecha_corta(lote.fecha_caducidad)}", fg=C["tinta"])
        for nombre in ("descripcion", "cantidad", "peso_kg", "volumen_m3", "fecha_caducidad"):
            self.variables[nombre].set("")
        self.app.estado(f"Ingreso registrado: {lote.id}. Quedan cambios sin guardar.")
        self.app.datos_cambiaron()

    def _fallo(self, error: Exception) -> None:
        if not isinstance(error, ErrorFormulario):
            self.app.mostrar_error(error)
            return
        for nombre, c in self.campos.items():
            c.marcar(error.errores.get(nombre))
        self.app.estado(f"El formulario tiene {len(error.errores)} error(es): corríjalos y vuelva a intentar.")

    def limpiar(self) -> None:
        for variable in self.variables.values():
            variable.set("")
        self.variables["fecha_ingreso"].set(self.ctrl.hoy.isoformat())
        self.frio.set(False)
        for c in self.campos.values():
            c.marcar(None)


# ---------- Alertas y despacho ----------

class PanelAlertas(Panel):
    titulo = "Alertas y despacho"
    subtitulo = "Necesidades sin cubrir, asignación por triaje y salida de lotes"

    def construir(self) -> None:
        px, f = self.app.px, self.app.f
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        acciones = Tarjeta(self, self.app)
        acciones.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(16)))
        self.boton_asignar = ttk.Button(acciones.cuerpo, text="Asignar automáticamente",
                                        style="Acento.TButton", command=self.asignar)
        self.boton_asignar.pack(side="right")
        ttk.Button(acciones.cuerpo, text="Descartar vencidos",
                   command=self.descartar).pack(side="right", padx=(0, px(10)))
        textos = tk.Frame(acciones.cuerpo, bg=C["panel"])
        textos.pack(side="left", fill="x", expand=True)
        tk.Label(textos, text="Asignación por triaje", font=f.subtitulo, bg=C["panel"], fg=C["tinta"],
                 anchor="w").pack(fill="x")
        tk.Label(textos, text="Primero se atiende la urgencia crítica, y sale primero lo que vence antes.",
                 font=f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w").pack(fill="x")

        alertas = Tarjeta(self, self.app, "Necesidades sin cubrir",
                          "Rojo: no hay stock en la red para cubrirlas")
        alertas.grid(row=1, column=0, sticky="nsew", padx=(0, px(8)), pady=(0, px(16)))
        self.alertas = TablaVista(alertas.cuerpo, self.app, [
            Columna("Situación", 90), Columna("Municipio", 120, estirar=True), Columna("Urgencia", 80),
            Columna("Categoría", 84), Columna("Faltante", 124, "e"), Columna("Cubierto", 76, "e"),
        ], alto=7)
        self.alertas.pack(fill="both", expand=True)
        self.pie_alertas = tk.Label(alertas.cuerpo, font=f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w")
        self.pie_alertas.pack(fill="x", pady=(px(8), 0))

        riesgo = Tarjeta(self, self.app, "En riesgo de quedar sin atender",
                         "Las de menor prioridad donde no alcanza el stock")
        riesgo.grid(row=1, column=1, sticky="nsew", padx=(px(8), 0), pady=(0, px(16)))
        self.riesgo = TablaVista(riesgo.cuerpo, self.app, [
            Columna("Municipio", 110, estirar=True), Columna("Categoría", 84), Columna("Faltante", 118, "e"),
        ], alto=7)
        self.riesgo.pack(fill="both", expand=True)
        self.pie_riesgo = tk.Label(riesgo.cuerpo, font=f.pequena, bg=C["panel"], fg=C["tenue"], anchor="w",
                                   justify="left", wraplength=px(380))
        self.pie_riesgo.pack(fill="x", pady=(px(8), 0))

        despacho = Tarjeta(self, self.app, "Asignados, esperando despacho",
                           "Seleccione varios con Ctrl o Mayús y despáchelos juntos")
        despacho.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.boton_despachar = ttk.Button(despacho.acciones, text="Despachar seleccionados",
                                          style="Acento.TButton", command=self.despachar)
        self.boton_despachar.pack(side="right")
        ttk.Button(despacho.acciones, text="Seleccionar todos",
                   command=self._seleccionar_todos).pack(side="right", padx=(0, px(10)))
        self.asignados = TablaVista(despacho.cuerpo, self.app, [
            Columna("Lote", 110), Columna("Categoría", 90), Columna("Cantidad", 130, "e"),
            Columna("Desde", 240, estirar=True), Columna("Hacia", 160),
        ], alto=6, seleccion="extended")
        self.asignados.pack(fill="both", expand=True)
        self.pie_asignados = tk.Label(despacho.cuerpo, font=f.pequena, bg=C["panel"], fg=C["tenue"],
                                      anchor="w")
        self.pie_asignados.pack(fill="x", pady=(px(8), 0))

    def actualizar(self) -> None:
        self.app.correr(lambda: (self.ctrl.alertas(), self.ctrl.en_riesgo(), self.ctrl.por_despachar()),
                        self._mostrar)

    def _mostrar(self, tablas: tuple[Tabla, Tabla, Tabla]) -> None:
        alertas, riesgo, asignados = tablas
        self.alertas.cargar(alertas.filas, "Todas las necesidades están cubiertas.")
        self.pie_alertas.configure(text=alertas.pie)
        self.riesgo.cargar(riesgo.filas, "Nada en riesgo.")
        self.pie_riesgo.configure(text=riesgo.pie)
        self.asignados.cargar(asignados.filas, "No hay lotes asignados pendientes de despacho.")
        self.pie_asignados.configure(text=asignados.pie)

    def asignar(self) -> None:
        def listo(cuantos: int) -> None:
            self.app.estado(f"Asignación terminada: {numero(cuantos)} lotes asignados." if cuantos
                            else "No había lotes que asignar: las necesidades están cubiertas o no hay stock.")
            self.app.datos_cambiaron()
        self.app.correr(self.ctrl.asignar_automaticamente, listo, accion="asignar",
                        mensaje="Asignando por triaje…")

    def descartar(self) -> None:
        def listo(cuantos: int) -> None:
            self.app.estado(f"Se descartaron {numero(cuantos)} lotes vencidos." if cuantos
                            else "No hay lotes vencidos.")
            self.app.datos_cambiaron()
        self.app.correr(self.ctrl.descartar_vencidos, listo, accion="descartar",
                        mensaje="Descartando lotes vencidos…")

    def _seleccionar_todos(self) -> None:
        self.asignados.arbol.selection_set(self.asignados.ids())

    def despachar(self) -> None:
        ids = self.asignados.seleccionados()
        if not ids:
            self.app.estado("Seleccione al menos un lote para despachar.")
            return
        if not self.app.confirmar("Despachar lotes", f"¿Despachar {len(ids)} lote(s)? "
                                  "Un lote despachado ya salió del centro y no se puede reasignar."):
            return

        def listo(resultado: ResultadoDespacho) -> None:
            self.app.estado(f"{len(resultado.despachados)} lote(s) despachado(s).")
            if resultado.errores:
                self.app.avisar("Algunos lotes no se despacharon", "\n".join(resultado.errores[:10]))
            self.app.datos_cambiaron()
        self.app.correr(lambda: self.ctrl.despachar(ids), listo, accion="despachar",
                        mensaje="Despachando…")


# ---------- Red de distribución ----------

class MapaVista(tk.Canvas):
    """Mapa esquemático: proyección simple de latitud y longitud, ajustada al
    tamaño del lienzo. Los nodos muy lejanos (Bogotá) se dibujan en el borde."""

    LEJANO_GRADOS = 1.5

    def __init__(self, padre: tk.Misc, app: Aplicacion, al_elegir: Callable[[str], None]) -> None:
        super().__init__(padre, bg=C["panel"], highlightthickness=0)
        self.app = app
        self.al_elegir = al_elegir
        self.mapa: Mapa | None = None
        self.ruta: Ruta | None = None
        self.posiciones: dict[str, tuple[float, float]] = {}
        self.bind("<Configure>", lambda _e: self.dibujar())
        self.tag_bind("nodo", "<Button-1>", self._clic)
        for etiqueta in ("nodo", "via"):
            self.tag_bind(etiqueta, "<Enter>", self._entrar)
            self.tag_bind(etiqueta, "<Leave>", lambda _e: self.delete("ayuda"))
        self._textos: dict[str, str] = {}
        self._medidas: dict[str, tkfont.Font] = {}
        self._adjuntos: set[str] = set()
        self._poblacion_max = 1
        self._km_por_px = 1.0

    def mostrar(self, mapa: Mapa, ruta: Ruta | None = None) -> None:
        self.mapa, self.ruta = mapa, ruta
        self.dibujar()

    def resaltar(self, ruta: Ruta | None) -> None:
        self.ruta = ruta
        self.dibujar()

    def _radio(self, n: NodoMapa) -> float:
        if n.es_centro:
            return float(self.app.px(7))
        return self.app.px(6) + self.app.px(9) * math.sqrt(n.poblacion / self._poblacion_max)

    def _proyectar(self, mapa: Mapa) -> dict[str, tuple[float, float, bool]]:
        municipios = [n for n in mapa.nodos if not n.es_centro]
        lat0 = sum(n.latitud for n in municipios) / len(municipios)
        lon0 = sum(n.longitud for n in municipios) / len(municipios)
        cercanos = [n for n in mapa.nodos if abs(n.latitud - lat0) <= self.LEJANO_GRADOS
                    and abs(n.longitud - lon0) <= self.LEJANO_GRADOS]
        k = math.cos(math.radians(lat0))
        xs = [n.longitud * k for n in cercanos]
        ys = [-n.latitud for n in cercanos]
        ancho, alto = max(self.winfo_width(), 200), max(self.winfo_height(), 200)
        margen = self.app.px(60)
        escala = min((ancho - 2 * margen) / (max(xs) - min(xs)), (alto - 2 * margen) / (max(ys) - min(ys)))
        dx = (ancho - escala * (max(xs) - min(xs))) / 2 - escala * min(xs)
        dy = (alto - escala * (max(ys) - min(ys))) / 2 - escala * min(ys)
        self._km_por_px = 111.0 / escala
        resultado: dict[str, tuple[float, float, bool]] = {}
        borde = self.app.px(22)
        for n in mapa.nodos:
            x, y = n.longitud * k * escala + dx, -n.latitud * escala + dy
            fuera = not (borde <= x <= ancho - borde and borde <= y <= alto - borde)
            resultado[n.id] = (min(max(x, borde), ancho - borde), min(max(y, borde), alto - borde), fuera)
        # Un centro en la misma ciudad que un municipio se dibuja pegado al
        # borde de su círculo, para que ambos se vean y se puedan pulsar.
        self._adjuntos = set()
        for n in mapa.nodos:
            if not n.es_centro:
                continue
            x, y, fuera = resultado[n.id]
            for m in mapa.nodos:
                mx, my, _ = resultado[m.id]
                if not m.es_centro and abs(mx - x) < 6 and abs(my - y) < 6:
                    r = self._radio(m) * 0.75
                    resultado[n.id] = (mx + r + self.app.px(2), my - r - self.app.px(2), fuera)
                    self._adjuntos.add(n.id)
        return resultado

    def dibujar(self) -> None:
        self.delete("all")
        if self.mapa is None:
            return
        px = self.app.px
        mapa = self.mapa
        self._poblacion_max = max((n.poblacion for n in mapa.nodos), default=1) or 1
        proy = self._proyectar(mapa)
        self.posiciones = {k: (x, y) for k, (x, y, _) in proy.items()}
        nombres = {n.id: n.nombre for n in mapa.nodos}
        self._textos = {}

        maximo = max((t.toneladas for t in mapa.tramos), default=0.0)
        for t in mapa.tramos:
            (x1, y1), (x2, y2) = self.posiciones[t.via.origen_id], self.posiciones[t.via.destino_id]
            cerrada = t.via.estado is EstadoVia.CERRADA
            grosor = px(2) if cerrada else px(2) + px(10) * escala_flujo(t.toneladas, maximo)
            etiqueta = f"via:{t.via.origen_id}:{t.via.destino_id}"
            self.create_line(x1, y1, x2, y2, fill=COLOR_VIA[t.via.estado], width=grosor, capstyle="round",
                             dash=(px(6), px(4)) if cerrada else (), tags=("via", etiqueta))
            flujo = f"\n{numero(t.toneladas, 1)} t de ayuda en camino" if t.toneladas else ""
            self._textos[etiqueta] = (f"{nombres[t.via.origen_id]} – {nombres[t.via.destino_id]}\n"
                                      f"{numero(t.via.distancia_km, 1)} km, {numero(t.via.tiempo_h, 1)} h, "
                                      f"{t.via.estado.name.lower()}{flujo}")

        if self.ruta is not None:
            puntos = [c for n in self.ruta.nodos for c in self.posiciones[n]]
            if len(puntos) >= 4:
                self.create_line(*puntos, fill="#BFD4EA", width=px(11), capstyle="round", joinstyle="round")
                self.create_line(*puntos, fill=C["ruta"], width=px(4), capstyle="round", joinstyle="round")

        # Primero todas las figuras, después los nombres: así ningún nombre
        # queda tapado y cada nombre puede esquivar las figuras ya dibujadas.
        for n in sorted(mapa.nodos, key=lambda n: n.es_centro):
            x, y, _ = proy[n.id]
            r = self._radio(n)
            etiqueta = f"nodo:{n.id}"
            borde = C["ruta"] if self.ruta is not None and n.id in self.ruta.nodos else "white"
            if n.es_centro:
                self.create_rectangle(x - r, y - r, x + r, y + r, fill=C["barra"], outline=borde,
                                      width=px(2), tags=("nodo", etiqueta))
                self._textos[etiqueta] = f"{n.nombre}\nCentro de acopio · clic para ver su inventario"
            else:
                assert n.urgencia is not None
                self.create_oval(x - r, y - r, x + r, y + r, fill=COLOR_URGENCIA[n.urgencia],
                                 outline=borde, width=px(2), tags=("nodo", etiqueta))
                self._textos[etiqueta] = (f"{n.nombre}\nUrgencia {NOMBRE_URGENCIA[n.urgencia].lower()}, "
                                          f"{numero(n.poblacion)} personas afectadas")

        for n in sorted(mapa.nodos, key=lambda n: (n.es_centro, -n.poblacion)):
            if n.id in self._adjuntos:
                continue                     # lo nombra el municipio en el que está
            x, y, fuera = proy[n.id]
            if n.es_centro:
                texto = nombre_corto(n.nombre) + (" (fuera de escala)" if fuera else "")
                self._rotular(texto, x, y, self._radio(n), self.app.f.etiqueta, C["tinta"])
            else:
                self._rotular(n.nombre, x, y, self._radio(n), self.app.f.pequena, C["tinta"])
        self._escala_grafica()

    def _rotular(self, texto: str, x: float, y: float, r: float, fuente: tuple[Any, ...], color: str) -> None:
        """Pone el nombre a la derecha del nodo; si ahí choca con otro nodo o
        nombre, prueba a la izquierda, arriba y abajo."""
        clave = str(fuente)
        if clave not in self._medidas:
            self._medidas[clave] = tkfont.Font(self, font=fuente)
        medida = self._medidas[clave]
        ancho, alto = medida.measure(texto), medida.metrics("linespace")
        sep = self.app.px(4)
        candidatos = [(x + r + sep, y - alto / 2), (x - r - sep - ancho, y - alto / 2),
                      (x - ancho / 2, y - r - sep - alto), (x - ancho / 2, y + r + sep)]
        limite_x, limite_y = self.winfo_width(), self.winfo_height()
        elegido = candidatos[0]
        for cx, cy in candidatos:
            if cx < 2 or cy < 2 or cx + ancho > limite_x - 2 or cy + alto > limite_y - 2:
                continue
            choques = [i for i in self.find_overlapping(cx, cy, cx + ancho, cy + alto)
                       if {"nodo", "rotulo"} & set(self.gettags(i))]
            if not choques:
                elegido = (cx, cy)
                break
        cx, cy = elegido
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):     # halo blanco: se lee sobre las vías
            self.create_text(cx + ox, cy + oy, text=texto, anchor="nw", font=fuente, fill="white",
                             tags="rotulo")
        self.create_text(cx, cy, text=texto, anchor="nw", font=fuente, fill=color, tags="rotulo")

    def _escala_grafica(self) -> None:
        px, f = self.app.px, self.app.f
        km = 10
        largo = km / self._km_por_px
        x1, y0 = self.winfo_width() - px(18), self.winfo_height() - px(18)
        x0 = x1 - largo
        self.create_line(x0, y0, x1, y0, fill=C["tenue"], width=px(2))
        for x in (x0, x1):
            self.create_line(x, y0 - px(4), x, y0 + px(1), fill=C["tenue"], width=px(2))
        self.create_text(x0 - px(6), y0, text=f"{km} km", anchor="e", font=f.pequena, fill=C["tenue"])

    def _id_actual(self, prefijo: str) -> str | None:
        for etiqueta in self.gettags("current"):
            if etiqueta.startswith(prefijo):
                return etiqueta
        return None

    def _clic(self, _evento: object) -> None:
        etiqueta = self._id_actual("nodo:")
        if etiqueta is not None:
            self.al_elegir(etiqueta.removeprefix("nodo:"))

    def _entrar(self, evento: tk.Event[Any]) -> None:
        etiqueta = self._id_actual("nodo:") or self._id_actual("via:")
        if etiqueta is None or etiqueta not in self._textos:
            return
        self.delete("ayuda")
        px = self.app.px
        x = min(evento.x + px(14), self.winfo_width() - px(240))
        y = evento.y + px(14)
        texto = self.create_text(x + px(10), y + px(8), text=self._textos[etiqueta], anchor="nw",
                                 font=self.app.f.pequena, fill="white", tags="ayuda")
        x1, y1, x2, y2 = self.bbox(texto)
        fondo = self.create_rectangle(x1 - px(10), y1 - px(7), x2 + px(10), y2 + px(7), fill=C["barra"],
                                      outline="", tags="ayuda")
        self.tag_lower(fondo, texto)


def nombre_corto(nombre: str) -> str:
    """'Aeropuerto Palonegro' → 'Palonegro', para rotular el mapa."""
    for prefijo in ("Aeropuerto ", "Puerto fluvial de ", "Acopio regional ", "Acopio intermedio "):
        if nombre.startswith(prefijo):
            return nombre.removeprefix(prefijo)
    return nombre


class PanelRed(Panel):
    titulo = "Red de distribución"
    subtitulo = "Vías, ayuda en camino y rutas más cortas (Dijkstra)"

    def construir(self) -> None:
        px, f = self.app.px, self.app.f
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        tarjeta_mapa = Tarjeta(self, self.app, "Mapa de la red",
                               "El grosor de cada vía es la ayuda asignada que pasa por ella")
        tarjeta_mapa.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        self.lienzo = MapaVista(tarjeta_mapa.cuerpo, self.app, self._elegir_nodo)
        self.lienzo.pack(fill="both", expand=True)

        lateral = tk.Frame(self, bg=C["fondo"], width=px(330))
        lateral.grid(row=0, column=1, sticky="ns")
        lateral.pack_propagate(False)

        ruta = Tarjeta(lateral, self.app, "Ruta más corta")
        ruta.pack(fill="x")
        self._nodos = self.ctrl.nodos()
        etiquetas = [o.etiqueta for o in self._nodos]
        self.origen = tk.StringVar()
        self.destino = tk.StringVar()
        self.criterio = tk.StringVar(value=Criterio.TIEMPO.name)
        for texto, variable in (("DESDE", self.origen), ("HASTA", self.destino)):
            tk.Label(ruta.cuerpo, text=texto, font=f.etiqueta, bg=C["panel"], fg=C["tenue"],
                     anchor="w").pack(fill="x")
            ttk.Combobox(ruta.cuerpo, textvariable=variable, values=etiquetas, state="readonly",
                         height=16).pack(fill="x", pady=(px(3), px(10)))
        criterios = tk.Frame(ruta.cuerpo, bg=C["panel"])
        criterios.pack(fill="x")
        for valor, texto in ((Criterio.TIEMPO.name, "Más rápida"), (Criterio.DISTANCIA.name, "Más corta")):
            ttk.Radiobutton(criterios, text=texto, value=valor, variable=self.criterio,
                            command=self.calcular).pack(side="left", padx=(0, px(16)))
        botones = tk.Frame(ruta.cuerpo, bg=C["panel"])
        botones.pack(fill="x", pady=(px(10), 0))
        ttk.Button(botones, text="Calcular ruta", style="Acento.TButton",
                   command=self.calcular).pack(side="left")
        ttk.Button(botones, text="Quitar", command=self._quitar_ruta).pack(side="left", padx=(px(8), 0))
        self.resultado = tk.Label(ruta.cuerpo, text="", font=f.normal, bg=C["panel"], fg=C["tinta"],
                                  anchor="w", justify="left", wraplength=px(280))
        self.resultado.pack(fill="x", pady=(px(10), 0))

        detalle = Tarjeta(lateral, self.app, "Detalle")
        detalle.pack(fill="x", pady=(px(14), 0))
        self.detalle = tk.Label(detalle.cuerpo, font=f.normal, bg=C["panel"], fg=C["tenue"], anchor="w",
                                justify="left", wraplength=px(280),
                                text="Clic en un centro (cuadro) lo pone como origen; "
                                     "clic en un municipio (círculo), como destino.")
        self.detalle.pack(fill="x")

        leyenda = Tarjeta(lateral, self.app, "Convenciones")
        leyenda.pack(fill="x", pady=(px(14), 0))
        self._dibujar_leyenda(leyenda.cuerpo)

    def _dibujar_leyenda(self, padre: tk.Frame) -> None:
        px, f = self.app.px, self.app.f
        lz = tk.Canvas(padre, bg=C["panel"], highlightthickness=0, height=px(136), width=px(290))
        lz.pack(fill="x")
        y = px(8)
        for texto, color, guiones in (("Transitable", COLOR_VIA[EstadoVia.TRANSITABLE], ()),
                                       ("Restringida", COLOR_VIA[EstadoVia.RESTRINGIDA], ()),
                                       ("Cerrada", COLOR_VIA[EstadoVia.CERRADA], (px(6), px(4))),
                                       ("Ruta calculada", C["ruta"], ())):
            lz.create_line(0, y, px(26), y, fill=color, width=px(3), dash=guiones)
            lz.create_text(px(34), y, text=texto, anchor="w", font=f.pequena, fill=C["tinta"])
            y += px(22)
        x, y = px(150), px(8)
        r = px(6)
        lz.create_rectangle(x, y - r, x + 2 * r, y + r, fill=C["barra"], outline="")
        lz.create_text(x + px(20), y, text="Centro de acopio", anchor="w", font=f.pequena, fill=C["tinta"])
        y += px(22)
        for urgencia in Urgencia:
            lz.create_oval(x, y - r, x + 2 * r, y + r, fill=COLOR_URGENCIA[urgencia], outline="")
            lz.create_text(x + px(20), y, text=f"Urgencia {NOMBRE_URGENCIA[urgencia].lower()}", anchor="w",
                           font=f.pequena, fill=C["tinta"])
            y += px(22)
        lz.create_text(0, px(126), text="Tamaño del círculo: población afectada.", anchor="w",
                       font=f.pequena, fill=C["tenue"])

    def actualizar(self) -> None:
        self.app.correr(self.ctrl.mapa, self.lienzo.mostrar, mensaje="Calculando flujos en la red…")

    def _elegir_nodo(self, nodo_id: str) -> None:
        opcion = next(o for o in self._nodos if o.id == nodo_id)
        es_centro = nodo_id.startswith("CA-")
        (self.origen if es_centro else self.destino).set(opcion.etiqueta)
        describir = self.ctrl.describir_centro if es_centro else self.ctrl.describir_municipio
        def mostrar(texto: str) -> None:
            self.detalle.configure(text=texto, fg=C["tinta"])
        self.app.correr(lambda: describir(nodo_id), mostrar)
        if self.origen.get() and self.destino.get():
            self.calcular()

    def calcular(self) -> None:
        origen = next((o.id for o in self._nodos if o.etiqueta == self.origen.get()), None)
        destino = next((o.id for o in self._nodos if o.etiqueta == self.destino.get()), None)
        if origen is None or destino is None:
            self.resultado.configure(text="Elija el origen y el destino.", fg=C["tenue"])
            return
        criterio = Criterio[self.criterio.get()]

        def calcular() -> tuple[Ruta | None, str]:
            r = self.ctrl.ruta(origen, destino, criterio)
            return r, self.ctrl.describir_ruta(r, criterio)

        def mostrar(resultado: tuple[Ruta | None, str]) -> None:
            r, texto = resultado
            self.resultado.configure(text=texto, fg=C["tinta"] if r else C["critico"])
            self.lienzo.resaltar(r)
        self.app.correr(calcular, mostrar)

    def _quitar_ruta(self) -> None:
        self.resultado.configure(text="")
        self.lienzo.resaltar(None)


# ============================================================
# Arranque
# ============================================================

def activar_dpi_windows() -> None:
    """En pantallas con escala de Windows (125 %, 150 %) evita que la ventana se vea borrosa."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> None:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    hoy = date.today()
    if argumentos:
        try:
            hoy = date.fromisoformat(argumentos[0])
        except ValueError:
            print("La fecha de operación va como AAAA-MM-DD, por ejemplo: "
                  "python -m donaciones.interfaz 2026-11-10")
            raise SystemExit(2)
    activar_dpi_windows()
    raiz = tk.Tk()
    raiz.withdraw()
    try:
        controlador, rechazos = Controlador.desde_carpeta(CARPETA_DATOS, hoy)
    except (ErrorArchivo, OSError) as error:
        messagebox.showerror("No se pudieron cargar los datos",
                             f"{error}\n\nSi aún no existen, créelos con:\npython -m donaciones.generador")
        raiz.destroy()
        return
    Aplicacion(raiz, controlador, rechazos)
    raiz.deiconify()
    raiz.mainloop()


if __name__ == "__main__":
    main()
