@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive - Crear instalador comercial
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_instalador_comercial.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] No se pudo crear el instalador comercial.
  pause
  exit /b 1
)
echo.
echo Presiona ENTER para cerrar.
pause >nul
exit /b 0
