@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive - Generar EXE y acceso directo

set "RUNTIME=%LOCALAPPDATA%\BrynnInteractive\runtime\desktop"
set "VENV_PY=%RUNTIME%\Scripts\python.exe"
set "BUILD_EXE=%~dp0dist\BrynnInteractiveDesktop\BrynnInteractiveDesktop.exe"
set "ICON=%APPDATA%\BrynnInteractive\branding\app_icon.ico"

if not exist "%VENV_PY%" (
    echo [ERROR] Primero ejecuta instalar_desktop.bat
    echo Runtime esperado: %RUNTIME%
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  BRYNN INTERACTIVE - GENERANDO APLICACION DE ESCRITORIO
echo ============================================================
echo.
echo Instalando/actualizando PyInstaller...
"%VENV_PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

echo.
echo Compilando BrynnInteractiveDesktop.exe...
"%VENV_PY%" "%~dp0build_desktop.py"
if errorlevel 1 goto :error

if not exist "%BUILD_EXE%" (
    echo [ERROR] La compilacion termino pero no encuentro:
    echo %BUILD_EXE%
    goto :error
)

echo.
echo Creando acceso directo del escritorio...
if exist "%ICON%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso_directo.ps1" -TargetPath "%BUILD_EXE%" -IconPath "%ICON%"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso_directo.ps1" -TargetPath "%BUILD_EXE%"
)
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  LISTO
echo ============================================================
echo EXE:
echo %BUILD_EXE%
echo.
echo Ya puedes abrir Brynn Interactive desde el icono del escritorio.
pause
exit /b 0

:error
echo.
echo [ERROR] No se pudo generar la aplicacion de escritorio.
pause
exit /b 1
