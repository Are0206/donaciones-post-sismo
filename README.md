# Sistema de donaciones post-sismo

Práctica 3 de Estructuras de Datos y Algoritmos. Gestión y distribución
de ayuda humanitaria tras un sismo en Santander, Colombia.

## Estado

| Fase | Estado |
|---|---|
| 1. Modelado y fuentes de datos | Terminada |
| 2. Especificación funcional | Pendiente |
| 3. Estructuras de datos | Pendiente |
| 4. Interfaz gráfica | Pendiente |

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
python -m donaciones.generador      # crea los datos en datos\
python -m donaciones.persistencia   # carga los CSV y reporta errores con su línea
.\test.bat                          # mypy estricto + todas las pruebas
```

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
| `lotes.csv` | Ayuda en especie: categoría, cantidad, peso, volumen, caducidad, frío, estado |
| `aportes.csv` | Aportes en dinero (pesos, enteros) con destino opcional |
| `vias.csv` | Red vial: distancia, tiempo estimado y estado (transitable, restringida, cerrada) |

Escenario: sismo el 2026-11-03, epicentro cerca de Los Santos. Las
coordenadas y distancias son aproximadas.

## Organización del código

```
donaciones/
  modelo.py          entidades (dataclasses inmutables), sus reglas internas y la fecha del sismo
  persistencia.py    conversión de valores, reglas entre entidades, lectura y escritura CSV/JSON
  generador.py       datos sintéticos con semilla fija
tests/
  test_modelo.py         reglas de cada entidad
  test_persistencia.py   conversión, archivos malformados, integridad, ida y vuelta, datos generados
```