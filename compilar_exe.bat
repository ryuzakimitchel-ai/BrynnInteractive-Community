@echo off
setlocal
cd /d "%~dp0"
title Brynn Interactive Desktop - Compilar EXE V0.48.0
call "%~dp0crear_app_escritorio.bat"
exit /b %errorlevel%
