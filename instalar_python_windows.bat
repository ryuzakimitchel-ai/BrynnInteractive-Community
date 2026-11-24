@echo off
setlocal
title Brynn Interactive - Instalar Python Windows

echo ============================================================
echo  INSTALAR PYTHON 3.13 NATIVO DE WINDOWS
echo ============================================================
echo.
echo El Python de MSYS2 no es compatible con el entorno Qt de esta app.
echo.
where winget >nul 2>nul
if errorlevel 1 (
    echo No se encontro winget.
    echo Instala Python desde:
    echo https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
)

winget install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Si termino correctamente, cierra esta ventana y ejecuta:
echo instalar_desktop.bat
echo.
pause
