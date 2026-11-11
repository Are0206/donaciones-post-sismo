@echo off
REM Corre todas las verificaciones: tipos (mypy) y pruebas (pytest).
cd /d "%~dp0"
echo == Verificacion de tipos (mypy --strict) ==
python -m mypy || exit /b 1
echo.
echo == Pruebas automatizadas (pytest) ==
python -m pytest %*
