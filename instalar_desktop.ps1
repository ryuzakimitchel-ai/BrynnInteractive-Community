$ErrorActionPreference = "Stop"
$BrynnUpdateMode = ($env:BRYNN_UPDATE_MODE -eq "1")

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " BRYNN INTERACTIVE DESKTOP BETA - INSTALACION V0.59.0" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$RuntimeRoot = Join-Path $env:LOCALAPPDATA "BrynnInteractive\runtime"
$VenvDir = Join-Path $RuntimeRoot "desktop"
$LegacyVenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonW = Join-Path $VenvDir "Scripts\pythonw.exe"
$Requirements = Join-Path $Root "requirements_desktop.txt"
$DesktopPy = Join-Path $Root "desktop.py"
$BuildPy = Join-Path $Root "build_desktop.py"
$DesktopExe = Join-Path $Root "dist\BrynnInteractiveDesktop\BrynnInteractiveDesktop.exe"
$ShortcutHelper = Join-Path $Root "crear_acceso_directo.ps1"

function Test-NativeWindowsPython([string]$Exe) {
    if (-not $Exe) { return $false }
    if (-not (Test-Path -LiteralPath $Exe)) { return $false }

    try {
        $result = & $Exe -c "import sys,sysconfig; print(sys.platform); print(sysconfig.get_platform()); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }

        $lines = @($result)
        if ($lines.Count -lt 3) { return $false }

        $platform = "$($lines[0])".Trim()
        $buildPlatform = "$($lines[1])".Trim().ToLower()
        $resolvedExe = "$($lines[2])".Trim().ToLower()

        if ($platform -ne "win32") { return $false }
        if (-not $buildPlatform.StartsWith("win")) { return $false }

        # Rechazar explícitamente entornos POSIX de Windows.
        if ($resolvedExe -match "\\msys64\\" -or
            $resolvedExe -match "\\cygwin" -or
            $resolvedExe -match "\\mingw") {
            return $false
        }

        return $true
    }
    catch {
        return $false
    }
}

function Get-PythonFromLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { return $null }

    foreach ($selector in @("-3.13", "-3.12", "-3.11", "-3")) {
        try {
            $exe = & $py.Source $selector -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                $candidate = "$exe".Trim()
                if (Test-NativeWindowsPython $candidate) {
                    return $candidate
                }
            }
        }
        catch {}
    }

    return $null
}

function Get-ExplicitPythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    $bases = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:ProgramFiles "Python313"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python311"),
        (Join-Path ${env:ProgramFiles(x86)} "Python313"),
        (Join-Path ${env:ProgramFiles(x86)} "Python312"),
        (Join-Path ${env:ProgramFiles(x86)} "Python311")
    )

    $localPythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPythonRoot) {
        Get-ChildItem -LiteralPath $localPythonRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $candidates.Add((Join-Path $_.FullName "python.exe"))
            }
    }

    foreach ($base in $bases) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }

        if ($base.EndsWith("\Python")) {
            continue
        }

        $candidates.Add((Join-Path $base "python.exe"))
    }

    $cmdPython = Get-Command python -ErrorAction SilentlyContinue
    if ($cmdPython) {
        $candidates.Add($cmdPython.Source)
    }

    return $candidates | Select-Object -Unique
}

function Find-NativeWindowsPython {
    $fromLauncher = Get-PythonFromLauncher
    if ($fromLauncher) {
        return $fromLauncher
    }

    foreach ($candidate in Get-ExplicitPythonCandidates) {
        if (Test-NativeWindowsPython $candidate) {
            return $candidate
        }
    }

    return $null
}

function Install-OfficialPython {
    $winget = Get-Command winget -ErrorAction SilentlyContinue

    if (-not $winget) {
        throw @"
No se encontro una instalacion nativa de Python para Windows.

El Python detectado pertenece a MSYS2:
C:\msys64\...

PySide6/Qt Desktop necesita Python nativo de Windows.

Instala Python 3.13 desde:
https://www.python.org/downloads/windows/

Durante la instalacion marca:
[+] Add python.exe to PATH

Despues vuelve a ejecutar instalar_desktop.bat.
"@
    }

    Write-Host ""
    Write-Host "No se encontro Python nativo de Windows." -ForegroundColor Yellow
    Write-Host "Se encontro Python de MSYS2, que no sirve para esta app Qt." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Instalando Python 3.13 oficial con winget..." -ForegroundColor Cyan

    & $winget.Source install `
        --id Python.Python.3.13 `
        -e `
        --scope user `
        --accept-package-agreements `
        --accept-source-agreements

    if ($LASTEXITCODE -ne 0) {
        throw "winget no pudo instalar Python 3.13. Codigo: $LASTEXITCODE"
    }

    Start-Sleep -Seconds 2
}

try {
    $PythonExe = Find-NativeWindowsPython

    if (-not $PythonExe) {
        Install-OfficialPython
        $PythonExe = Find-NativeWindowsPython
    }

    if (-not $PythonExe) {
        throw @"
Python 3 se instalo, pero no pude localizar python.exe automaticamente.

Prueba cerrar PowerShell, abrir uno nuevo y ejecutar nuevamente:
.\instalar_desktop.bat
"@
    }

    Write-Host "Python nativo detectado:" -ForegroundColor Green
    Write-Host "  $PythonExe" -ForegroundColor Green

    $pyInfo = & $PythonExe -c "import sys,sysconfig; print(sys.version); print(sysconfig.get_platform())"
    Write-Host "  $($pyInfo -join ' | ')" -ForegroundColor DarkGray
    Write-Host ""

    # Desde V0.48.0 el runtime se guarda fuera de la carpeta del proyecto.
    # Esto evita el limite historico de rutas largas de Windows/PySide6,
    # especialmente cuando el proyecto esta dentro de OneDrive o carpetas profundas.
    if (Test-Path $LegacyVenvDir) {
        Write-Host "Eliminando .venv local de una beta anterior (ya no se usa)..." -ForegroundColor Yellow
        try { Remove-Item -LiteralPath $LegacyVenvDir -Recurse -Force } catch {}
    }

    $PosixVenvPython = Join-Path $VenvDir "bin\python.exe"
    if (Test-Path $PosixVenvPython) {
        Write-Host "Se detecto un runtime creado por MSYS2. Eliminando..." -ForegroundColor Yellow
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
    elseif ((Test-Path $VenvDir) -and -not (Test-Path $VenvPython)) {
        Write-Host "Se detecto un runtime incompleto. Eliminando..." -ForegroundColor Yellow
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }

    if (-not (Test-Path $RuntimeRoot)) {
        New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creando runtime Windows en una ruta corta:" -ForegroundColor Cyan
        Write-Host "  $VenvDir" -ForegroundColor DarkGray
        & $PythonExe -m venv $VenvDir

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo crear el entorno virtual. Codigo: $LASTEXITCODE"
        }
    }

    if (-not (Test-Path $VenvPython)) {
        throw @"
Python ejecuto 'venv', pero no creo:
$VenvPython

Python usado:
$PythonExe

Esto indica que no se esta usando CPython nativo de Windows.
"@
    }

    Write-Host "Entorno virtual Windows: OK" -ForegroundColor Green
    Write-Host "  $VenvDir" -ForegroundColor DarkGray

    Write-Host "Preparando pip..." -ForegroundColor Cyan
    & $VenvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        throw "ensurepip fallo. Codigo: $LASTEXITCODE"
    }

    Write-Host "Actualizando pip / setuptools / wheel..." -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo actualizar pip. Codigo: $LASTEXITCODE"
    }

    if (-not (Test-Path $Requirements)) {
        throw "No existe requirements_desktop.txt en: $Root"
    }

    Write-Host ""
    Write-Host "Instalando PySide6 + Qt WebEngine..." -ForegroundColor Cyan
    Write-Host "La primera instalacion puede tardar varios minutos." -ForegroundColor DarkGray

    & $VenvPython -m pip install -r $Requirements

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron instalar las dependencias. Codigo: $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Comprobando Qt WebEngine..." -ForegroundColor Cyan

    & $VenvPython -c "import PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 OK:', PySide6.__version__)"

    if ($LASTEXITCODE -ne 0) {
        throw "PySide6 se instalo pero Qt WebEngine no pudo cargarse."
    }

    $ExeReady = $false
    try {
        Write-Host ""
        Write-Host "Preparando ejecutable de escritorio..." -ForegroundColor Cyan
        & $VenvPython -m pip install --upgrade pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller." }

        if (-not (Test-Path $BuildPy)) { throw "No existe build_desktop.py" }
        & $VenvPython $BuildPy
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller devolvio codigo $LASTEXITCODE" }

        if (-not (Test-Path $DesktopExe)) { throw "No se genero $DesktopExe" }

        $CustomIcon = Join-Path $env:APPDATA "BrynnInteractive\branding\app_icon.ico"
        if (Test-Path $ShortcutHelper) {
            if (Test-Path $CustomIcon) {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ShortcutHelper -TargetPath $DesktopExe -IconPath $CustomIcon
            } else {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ShortcutHelper -TargetPath $DesktopExe
            }
        }
        $ExeReady = $true
        Write-Host "EXE y acceso directo: OK" -ForegroundColor Green
    }
    catch {
        Write-Host ""
        Write-Host "[AVISO] La app quedo instalada, pero no pude generar el EXE/acceso directo." -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        Write-Host "Puedes crearlo despues desde Personalizacion o ejecutar crear_app_escritorio.bat." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " INSTALACION COMPLETADA" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""

    if (-not $BrynnUpdateMode) {
        Write-Host "Iniciando Brynn Interactive Desktop..." -ForegroundColor Cyan
        if ($ExeReady -and (Test-Path $DesktopExe)) {
            Start-Process -FilePath $DesktopExe -WorkingDirectory (Split-Path -Parent $DesktopExe)
        }
        elseif (Test-Path $VenvPythonW) {
            Start-Process `
                -FilePath $VenvPythonW `
                -ArgumentList @($DesktopPy) `
                -WorkingDirectory $Root
        }
        else {
            Start-Process `
                -FilePath $VenvPython `
                -ArgumentList @($DesktopPy) `
                -WorkingDirectory $Root
        }
    } else {
        Write-Host "Modo actualización integrada: el reinicio lo realizará Brynn Interactive." -ForegroundColor DarkGray
    }
}
catch {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host " ERROR DE INSTALACION" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Carpeta:" -ForegroundColor Yellow
    Write-Host "  $Root"
    Write-Host ""
    Write-Host "Python en PATH:" -ForegroundColor Yellow

    try {
        where.exe python
    }
    catch {}

    Write-Host ""
    Write-Host "Si aparece C:\msys64\..., ese Python NO debe usarse para Desktop." -ForegroundColor Yellow
    Write-Host "Runtime esperado:" -ForegroundColor Yellow
    Write-Host "  $VenvDir" -ForegroundColor Yellow
    Write-Host ""
    if (-not $BrynnUpdateMode) { Read-Host "Presiona ENTER para salir" }
    exit 1
}
