@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive Desktop - Instalador V0.59.0

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_desktop.ps1"

if errorlevel 1 (
    echo.
    echo [ERROR] La instalacion no se completo.
    pause
    exit /b 1
)

exit /b 0
