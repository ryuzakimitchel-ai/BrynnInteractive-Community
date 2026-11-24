@echo off
title Brynn - Diagnostico Streamlabs V30
echo.
echo === STREAMLABS V30 ===
powershell -NoProfile -Command "try { $s=(Invoke-RestMethod http://127.0.0.1:8765/api/integrations).streamlabs; $s | Select-Object enabled,tokenPresent,tokenMasked,tokenLength,storageScope,storageFile,storageWritable,state,connected,activeBridges,lastError | ConvertTo-Json -Depth 5 } catch { Write-Host $_.Exception.Message -ForegroundColor Red }"
echo.
echo El token completo NO se muestra.
echo.
pause
