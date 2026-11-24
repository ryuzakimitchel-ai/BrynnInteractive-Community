@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive Desktop - Diagnostico V0.48.0
set "RUNTIME=%LOCALAPPDATA%\BrynnInteractive\runtime\desktop"
set "VENV_PY=%RUNTIME%\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [ERROR] No se encontro el runtime de Brynn:
  echo %VENV_PY%
  echo Ejecuta primero .\instalar_desktop.bat
  pause
  exit /b 1
)
"%VENV_PY%" "%~dp0desktop.py"
echo.
echo La aplicacion termino con codigo %ERRORLEVEL%.
pause
