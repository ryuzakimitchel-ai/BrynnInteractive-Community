@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive Desktop V0.48.0

set "EXE=%~dp0dist\BrynnInteractiveDesktop\BrynnInteractiveDesktop.exe"
set "RUNTIME=%LOCALAPPDATA%\BrynnInteractive\runtime\desktop"
set "VENV_PYW=%RUNTIME%\Scripts\pythonw.exe"
set "VENV_PY=%RUNTIME%\Scripts\python.exe"
set "APP=%~dp0desktop.py"

if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%APP%"
    exit /b 0
)
if exist "%VENV_PY%" (
    start "" "%VENV_PY%" "%APP%"
    exit /b 0
)

echo.
echo [ERROR] No se encontro BrynnInteractiveDesktop.exe ni el runtime de Brynn.
echo Ejecuta primero:
echo.
echo   .\instalar_desktop.bat
echo.
echo Runtime esperado:
echo   %RUNTIME%
pause
exit /b 1
