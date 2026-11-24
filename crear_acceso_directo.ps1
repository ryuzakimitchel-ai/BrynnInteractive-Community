param(
    [Parameter(Mandatory=$true)][string]$TargetPath,
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $TargetPath)) {
    throw "No existe el ejecutable: $TargetPath"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($Desktop)) {
    $Desktop = Join-Path $env:USERPROFILE "Desktop"
}

$ShortcutPath = Join-Path $Desktop "Brynn Interactive.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$Shortcut.Description = "Brynn Interactive Desktop"
$Shortcut.WindowStyle = 1

if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
    $Shortcut.IconLocation = "$IconPath,0"
} else {
    $Shortcut.IconLocation = "$TargetPath,0"
}

$Shortcut.Save()

# Actualiza el shell para que Windows refresque el icono del acceso directo.
try {
    Add-Type -Namespace Win32 -Name NativeShell -MemberDefinition @"
[DllImport("shell32.dll")]
public static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
"@
    [Win32.NativeShell]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
} catch {}

Write-Output "Acceso directo creado/actualizado: $ShortcutPath"
exit 0
