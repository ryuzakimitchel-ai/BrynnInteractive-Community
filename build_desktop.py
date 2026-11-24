from pathlib import Path
import os
import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent

# En builds comerciales el ejecutable usa siempre el icono del producto.
# Un icono personal puede seguir aplicándose en runtime y al acceso directo.
appdata = os.environ.get("APPDATA")
custom_icon = Path(appdata) / "BrynnInteractive" / "branding" / "app_icon.ico" if appdata else None
default_icon = ROOT / "brynn_default.ico"
use_custom_build_icon = os.environ.get("BRYNN_USE_CUSTOM_BUILD_ICON", "0") == "1"
icon = custom_icon if use_custom_build_icon and custom_icon and custom_icon.exists() else default_icon

datas = []
for pattern in ("*.html", "*.js", "*.css", "*.txt", "*.json", "*.ico", "*.png", "*.ps1", "*.bat"):
    for file in ROOT.glob(pattern):
        if file.name.startswith("desktop"):
            continue
        datas.extend(["--add-data", f"{file};."])

for folder in ("data", "user_media", "_vendor"):
    path = ROOT / folder
    if path.exists():
        datas.extend(["--add-data", f"{path};{folder}"])

args = [
    str(ROOT / "desktop.py"),
    "--name", "BrynnInteractiveDesktop",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--hidden-import", "server",
    "--hidden-import", "kick_connector",
    "--hidden-import", "obs_controller",
    "--hidden-import", "automation_engine",
    "--hidden-import", "PySide6.QtMultimedia",
    "--hidden-import", "PySide6.QtMultimediaWidgets",
    "--collect-submodules", "websocket",
]

if icon.exists():
    args.extend(["--icon", str(icon)])

args.extend(datas)

PyInstaller.__main__.run(args)
print("\nBuild terminado en dist/BrynnInteractiveDesktop/")
print(f"Icono usado: {icon}")
