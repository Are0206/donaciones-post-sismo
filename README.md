# Sistema de donaciones post-sismo

Práctica 3 de Estructuras de Datos y Algoritmos. Gestión y distribución
de ayuda humanitaria tras un sismo en Santander, Colombia.

## Estado

| Fase | Estado |
|---|---|
| 1. Modelado y fuentes de datos | Terminada |
| 2. Especificación funcional | Terminada |
| 3. Estructuras de datos | Terminada |
| 4. Interfaz gráfica | Terminada |

## Instalación (Windows)

1. Instale **Python 3.10 o superior** desde python.org. En el instalador marque
   **"Add python.exe to PATH"**.
2. Abra la carpeta `donaciones` en **VS Code** y abra una terminal
   (**Terminal → New Terminal**).
3. Solo la primera vez, cree el entorno e instale las herramientas de prueba:

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Si PowerShell no permite activar el entorno, ejecute una sola vez
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelva a activarlo.

Cada vez que abra una terminal nueva, active el entorno con
`.venv\Scripts\activate`. Se sabe que está activo porque la línea empieza
con `(.venv)`.

## Uso

```
python -m donaciones.interfaz       # abre la ventana del sistema
python -m donaciones.generador      # crea los datos en datos\
python -m donaciones.persistencia   # carga los CSV y reporta errores con su línea
python -m donaciones.benchmark      # compara cada estructura con su alternativa ingenua
.\test.bat                          # mypy estricto + todas las pruebas
```

La ventana usa la fecha de hoy para saber qué está vencido. Para trabajar con
otra fecha: `python -m donaciones.interfaz 2026-11-10`.

## La ventana

| Panel | Atajo | Para qué |
|---|---|---|
| Resumen | Ctrl+1 | Necesidades cubiertas, faltantes, lotes por vencer y cobertura por categoría |
| Inventario | Ctrl+2 | Buscar y filtrar lotes; ver el stock de cada centro |
| Registrar ingreso | Ctrl+3 | Registrar una donación que llegó, con cada error marcado en su campo |
| Alertas y despacho | Ctrl+4 | Asignación automática por triaje, descarte de vencidos y despacho de lotes |
| Red de distribución | Ctrl+5 | Mapa de vías con la ayuda en camino y ruta más corta entre dos puntos |

Los cambios quedan en memoria hasta pulsar **Guardar cambios** (o Ctrl+S). Al
cerrar con cambios pendientes, la ventana pregunta si guardarlos.

Los CSV se editan con VS Code, no con Excel: Excel cambia las fechas a
`10/11/2026` y el sistema solo acepta `2026-11-10`.

La lectura y escritura en JSON (`cargar_json`, `exportar_json`) están en
`persistencia.py` y se usan desde el código.

## Repositorio

El control de versiones se maneja con **GitHub Desktop**: un commit al
terminar cada fase.

## Datos (`datos/`)

| Archivo | Contenido |
|---|---|
| `centros.csv` | Aeropuertos, puertos y centros de acopio: ubicación, capacidad, cadena de frío |
| `municipios.csv` | Municipios afectados: ubicación, población afectada, nivel de urgencia |
| `necesidades.csv` | Cuánto necesita cada municipio de cada categoría (llave: municipio + categoría) |
| `donantes.csv` | Personas, empresas, ONG, gobiernos y cooperación internacional |
| `lotes.csv` | Ayuda en especie: categoría, cantidad, peso, volumen, caducidad, frío, estado y municipio destino |
| `aportes.csv` | Aportes en dinero (pesos, enteros) con destino opcional |
| `vias.csv` | Red vial: distancia, tiempo estimado y estado (transitable, restringida, cerrada) |

Escenario: sismo el 2026-11-03, epicentro cerca de Los Santos. Las
coordenadas y distancias son aproximadas.
