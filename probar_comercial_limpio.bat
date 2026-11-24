@echo off
setlocal
cd /d "%~dp0"
set "BRYNN_APPDATA_ROOT=%~dp0_commercial_test_profile"
set "RUNTIME=%LOCALAPPDATA%\BrynnInteractive\runtime\desktop"
set "PY=%RUNTIME%\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Primero ejecuta instalar_desktop.bat
  echo Runtime esperado: %RUNTIME%
  pause
  exit /b 1
)
echo Perfil de prueba aislado:
echo %BRYNN_APPDATA_ROOT%
echo.
"%PY%" "%~dp0desktop.py"
endlocal
