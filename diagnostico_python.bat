@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive - Diagnostico Python V0.48.0
set "RUNTIME=%LOCALAPPDATA%\BrynnInteractive\runtime\desktop"
set "VENV_PY=%RUNTIME%\Scripts\python.exe"

echo ============================================================
echo  DIAGNOSTICO DE PYTHON
echo ============================================================
echo.
echo PATH python:
where python
echo.
echo PATH py:
where py
echo.
echo Python ejecutado por "python":
python -c "import sys,sysconfig; print('exe=',sys.executable); print('platform=',sys.platform); print('build=',sysconfig.get_platform())"
echo.
echo IMPORTANTE:
echo Si exe contiene C:\msys64\ y platform no es win32,
echo ese Python no sirve para PySide6 Desktop.
echo.
echo Runtime Brynn esperado:
echo %VENV_PY%
echo.
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; print(sys.executable); print(sys.version)"
) else (
    echo [NO EXISTE]
)
echo.
pause
