@echo off
title Brynn - TikFinity Web Tunnel
echo.
echo ============================================================
echo  BRYNN - TIKFINITY WEBHOOK TUNNEL
echo ============================================================
echo.
echo Este script expone SOLO el receptor de WebHooks del puerto 8766.
echo NO expone el panel privado del puerto 8765.
echo.
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro cloudflared en PATH.
  echo Descargalo desde la pagina oficial de Cloudflare Tunnel,
  echo colocalo en esta carpeta o agregalo al PATH.
  echo.
  pause
  exit /b 1
)
echo Iniciando Quick Tunnel...
echo Cuando aparezca una URL https://xxxxx.trycloudflare.com
echo copiala en:
echo http://127.0.0.1:8765/integraciones.html
echo.
cloudflared tunnel --url http://127.0.0.1:8766
pause
