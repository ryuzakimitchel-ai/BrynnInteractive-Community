@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive Desktop - Reparar V0.44.0

echo.
echo Se eliminara SOLO:
echo   %~dp0.venv
echo.
echo Tus datos, Streamlabs, Gumpitas, alertas y user_media NO se borran.
echo.
pause

if exist "%~dp0.venv" (
    rmdir /s /q "%~dp0.venv"
)

call "%~dp0instalar_desktop.bat"
