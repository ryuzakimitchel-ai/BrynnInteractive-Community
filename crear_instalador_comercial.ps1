$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$RuntimePython = Join-Path $env:LOCALAPPDATA "BrynnInteractive\runtime\desktop\Scripts\python.exe"
$BuildScript = Join-Path $Root "build_desktop.py"
$DistExe = Join-Path $Root "dist\BrynnInteractiveDesktop\BrynnInteractiveDesktop.exe"
$IssFile = Join-Path $Root "BrynnInteractiveSetup.iss"
$OutputExe = Join-Path $Root "installer_output\BrynnInteractive-Setup-0.59.0.exe"

function Find-Iscc {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " BRYNN INTERACTIVE - INSTALADOR COMERCIAL V0.59.0" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Este proceso genera UN SOLO archivo .exe para distribuir." -ForegroundColor Gray
Write-Host "El cliente podra elegir la carpeta de instalacion." -ForegroundColor Gray
Write-Host ""

$ProductIcon = Join-Path $Root "brynn_default.ico"
if (-not (Test-Path -LiteralPath $ProductIcon)) {
    throw "No se encontro el icono oficial de Brynn Interactive: $ProductIcon"
}
Write-Host "Icono del producto:" -ForegroundColor Cyan
Write-Host "  $ProductIcon" -ForegroundColor White
Write-Host "Este icono se incrustara en el EXE de la app, el Setup, los accesos directos y el desinstalador." -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Path -LiteralPath $RuntimePython)) {
    Write-Host "No existe el runtime de Brynn. Ejecutando instalador de desarrollo..." -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "instalar_desktop.ps1")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $RuntimePython)) {
        throw "No se pudo preparar el runtime de Python para compilar Brynn Interactive."
    }
}

Write-Host "[1/4] Preparando PyInstaller..." -ForegroundColor Cyan
& $RuntimePython -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller." }

Write-Host "[2/4] Compilando aplicacion comercial..." -ForegroundColor Cyan
& $RuntimePython $BuildScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $DistExe)) {
    throw "No se genero el ejecutable comercial: $DistExe"
}

Write-Host "[3/4] Buscando Inno Setup..." -ForegroundColor Cyan
$Iscc = Find-Iscc
if (-not $Iscc) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Inno Setup no esta instalado y winget no esta disponible. Instala Inno Setup 6 y vuelve a ejecutar este archivo."
    }

    Write-Host "Inno Setup no esta instalado. Instalando automaticamente..." -ForegroundColor Yellow
    & $winget.Source install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget no pudo instalar Inno Setup." }
    Start-Sleep -Seconds 2
    $Iscc = Find-Iscc
}

if (-not $Iscc) { throw "No pude localizar ISCC.exe despues de instalar Inno Setup." }
Write-Host "  $Iscc" -ForegroundColor DarkGray

Write-Host "[4/4] Generando instalador unico..." -ForegroundColor Cyan
& $Iscc $IssFile
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputExe)) {
    throw "Inno Setup no pudo generar el instalador comercial."
}


# Verificacion basica: Windows debe poder extraer un icono asociado del Setup generado.
try {
    Add-Type -AssemblyName System.Drawing -ErrorAction Stop
    $EmbeddedIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($OutputExe)
    if ($null -eq $EmbeddedIcon) {
        throw "Windows no pudo extraer un icono del instalador generado."
    }
    $EmbeddedIcon.Dispose()
    Write-Host "Icono del instalador verificado: OK" -ForegroundColor Green
} catch {
    throw "El instalador fue creado, pero no pude verificar el icono embebido: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " INSTALADOR COMERCIAL LISTO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Archivo para entregar a clientes:" -ForegroundColor Green
Write-Host "  $OutputExe" -ForegroundColor White
Write-Host ""
Write-Host "El cliente solo necesita ejecutar ese EXE." -ForegroundColor Gray
Write-Host "No necesita Python, el ZIP del proyecto ni Inno Setup." -ForegroundColor Gray

Start-Process explorer.exe -ArgumentList "/select,`"$OutputExe`""
