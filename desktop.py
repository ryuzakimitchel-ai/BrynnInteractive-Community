from __future__ import annotations

import json
import math
import struct
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl, QUrlQuery, Signal, QObject, QRect, QRectF, QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QFont, QIntValidator, QPainter, QPen, QPixmap, QMovie, QIcon, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGraphicsOpacityEffect,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QAbstractSpinBox,
    QStackedWidget,
    QStackedLayout,
    QSystemTrayIcon,
    QStyle,
    QSizeGrip,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtNetwork import QLocalServer, QLocalSocket

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    QT_MULTIMEDIA_AVAILABLE = True
except Exception:
    QMediaPlayer = QAudioOutput = QVideoWidget = None
    QT_MULTIMEDIA_AVAILABLE = False

APP_NAME = "Brynn Interactive Desktop"
APP_VERSION = "0.60.12-beta"
APP_VERSION_LABEL = "V0.60.12 - BETA"
ASSET_VERSION = "611"
APP_ID = "brynn-interactive-desktop"
LOCAL_BASE = "http://127.0.0.1:8765"
WEBHOOK_LOCAL = "http://127.0.0.1:8766"


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parent
    return root / name


APPDATA_ROOT = Path(
    os.environ.get("BRYNN_APPDATA_ROOT")
    or (Path(os.environ.get("APPDATA")) / "BrynnInteractive" if os.environ.get("APPDATA") else (Path.home() / ".brynn_interactive" / "BrynnInteractive"))
)
DATA_DIR = APPDATA_ROOT / "data"
MEDIA_DIR = APPDATA_ROOT / "user_media"
BACKUPS_DIR = APPDATA_ROOT / "backups"
STREAMLABS_FILE = APPDATA_ROOT / "streamlabs.json"
DESKTOP_STATE_FILE = APPDATA_ROOT / "desktop_state.json"
UPDATES_DIR = APPDATA_ROOT / "updates"
STAGED_UPDATES_DIR = UPDATES_DIR / "staged"
APPEARANCE_FILE = APPDATA_ROOT / "desktop_appearance.json"
LOADER_MEDIA_DIR = APPDATA_ROOT / "loading_assets"
FLOATING_CHAT_LOCAL_FILE = DATA_DIR / "floating_chat_config.json"
TWITCH_CONTROL_LOCAL_FILE = APPDATA_ROOT / "twitch_control.json"
KICK_LOCAL_FILE = APPDATA_ROOT / "kick.json"
BRANDING_DIR = APPDATA_ROOT / "branding"
APP_ICON_FILE = BRANDING_DIR / "app_icon.ico"
PROFILE_FILE = DATA_DIR / "profile.json"
SETUP_STATE_FILE = APPDATA_ROOT / "setup_state.json"
NAV_STATE_FILE = APPDATA_ROOT / "navigation_state.json"
SINGLE_INSTANCE_NAME = "BrynnInteractiveDesktop.SingleInstance.v1"


def default_profile() -> dict:
    return {
        "setupComplete": False,
        "streamerName": "",
        "owners": {"twitch": "", "tiktok": "", "kick": ""},
        "developerMode": False,
        "createdAt": None,
        "updatedAt": None,
    }


def load_profile() -> dict:
    data = default_profile()
    raw = load_json_file(PROFILE_FILE, {}) if PROFILE_FILE.exists() else {}
    if isinstance(raw, dict):
        data.update(raw)
    owners = data.get("owners") if isinstance(data.get("owners"), dict) else {}
    data["owners"] = {
        "twitch": str(owners.get("twitch") or "").strip().lstrip("@"),
        "tiktok": str(owners.get("tiktok") or "").strip().lstrip("@"),
        "kick": str(owners.get("kick") or "").strip().lstrip("@"),
    }
    return data


def save_profile(profile: dict) -> dict:
    current = default_profile()
    current.update(profile or {})
    owners = current.get("owners") if isinstance(current.get("owners"), dict) else {}
    current["owners"] = {
        "twitch": str(owners.get("twitch") or "").strip().lstrip("@"),
        "tiktok": str(owners.get("tiktok") or "").strip().lstrip("@"),
        "kick": str(owners.get("kick") or "").strip().lstrip("@"),
    }
    now = datetime.now().isoformat()
    current["createdAt"] = current.get("createdAt") or now
    current["updatedAt"] = now
    save_json_file(PROFILE_FILE, current)
    return current


def _write_setup_state(complete: bool) -> None:
    try:
        save_json_file(SETUP_STATE_FILE, {
            "complete": bool(complete),
            "updatedAt": datetime.now().isoformat(),
        })
    except Exception:
        pass


def setup_is_complete(profile: dict | None = None) -> bool:
    """Devuelve True si esta instalación ya completó el asistente.

    V0.47.4 usa un marcador persistente fuera de la carpeta versionada y además
    repara instalaciones 0.47.x donde setupComplete pudo quedar en False aunque
    la identidad ya estaba guardada. Esto evita relanzar el onboarding tras una
    actualización normal.
    """
    current = profile if isinstance(profile, dict) else load_profile()
    if bool(current.get("setupComplete", False)):
        _write_setup_state(True)
        return True

    state = load_json_file(SETUP_STATE_FILE, {}) if SETUP_STATE_FILE.exists() else {}
    if isinstance(state, dict) and bool(state.get("complete", False)):
        current["setupComplete"] = True
        save_profile(current)
        return True

    owners = current.get("owners") if isinstance(current.get("owners"), dict) else {}
    has_identity = bool(
        str(current.get("streamerName") or "").strip()
        or str(owners.get("twitch") or "").strip()
        or str(owners.get("tiktok") or "").strip()
    )
    if has_identity:
        # Reparación automática para usuarios existentes: si ya hay identidad,
        # no tiene sentido tratarlos como una instalación nueva.
        current["setupComplete"] = True
        save_profile(current)
        _write_setup_state(True)
        return True
    return False


def default_appearance() -> dict:
    return {
        "theme": "neon",
        "accent": "",
        "accent2": "",
        "fontFamily": "Segoe UI",
        "density": "comfortable",
        "sidebarWidth": 250,
        "uiScale": 100,
        "webZoom": 95,
        "brand": "BRYNN\\nINTERACTIVE",
        "showFooter": True,
        "titlebarStyle": "gradient",
        "panelRadius": 14,
        "menuStyle": "soft",
        "showSidebarVersion": True,
        "showTitleVersion": True,
        "titlebarHeight": 46,
        "loadingType": "circle",
        "loadingImage": "",
        "loadingEmoteId": "",
        "loadingSize": 72,
        "loadingMinMs": 320,
        "loadingText": "Cargando módulo…",
        "loadingShowText": True,
        "loadingBackdrop": True,
        "loadingBackdropOpacity": 82,
        # Pantalla de inicio (Splash Studio). Se guarda en AppData para que
        # sobreviva a cualquier actualización del programa.
        "startupSplashEnabled": True,
        "startupSplashMinMs": 1200,
        "startupTitle": "BRYNN INTERACTIVE",
        "startupSubtitle": "Preparando tu centro de control…",
        "startupShowLogo": True,
        "startupMediaPath": "",
        "startupAudioPath": "",
        "startupAudioVolume": 55,
        "startupBackground": "#080b12",
        "startupPreset": "neon",
        "startupProgressStyle": "neon",
        "startupMediaItems": [],
        "windowFrameStyle": "soft",
        "compactSidebarWidth": 84,
        "updateStylePreset": "match",
        "updateProgressStyle": "neon",
        "updateShowTechnicalLog": False,
        "updateTitle": "Actualizando Brynn Interactive",
        "updateBackground": "",
        "updateMediaPath": "",
        "updateShowLogo": True,
        "startupLayout": {
            "logo": {"x": 0.40, "y": 0.16, "w": 0.20, "h": 0.34},
            "media": {"x": 0.06, "y": 0.12, "w": 0.26, "h": 0.46},
            "title": {"x": 0.18, "y": 0.56, "w": 0.64, "h": 0.10},
            "subtitle": {"x": 0.18, "y": 0.66, "w": 0.64, "h": 0.08},
            "progress": {"x": 0.16, "y": 0.80, "w": 0.68, "h": 0.055},
            "status": {"x": 0.16, "y": 0.86, "w": 0.68, "h": 0.07}
        },
        "appIconPath": "",
        "updatedAt": None,
    }


def normalize_hex_color(value: str) -> str:
    value = str(value or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.lower()
    return ""


def render_media_pixmap(pix: QPixmap, size: QSize, fit: str = "contain", zoom: int = 100, pan_x: int = 0, pan_y: int = 0, rotation: int = 0, flip_h: bool = False, flip_v: bool = False) -> QPixmap:
    """Ajusta un QPixmap dentro de un marco con zoom, paneo, giro y volteo.

    Se usa tanto en el editor visual como en la reproducción del splash.
    pan_x / pan_y son porcentajes relativos al tamaño del marco.
    """
    if pix.isNull() or size.width() < 1 or size.height() < 1:
        return pix

    fit = str(fit or "contain")
    zoom = max(10, min(400, int(zoom or 100)))
    pan_x = max(-200, min(200, int(pan_x or 0)))
    pan_y = max(-200, min(200, int(pan_y or 0)))
    rotation = int(rotation or 0) % 360

    working = QPixmap(pix)
    if flip_h or flip_v or rotation:
        tr = QTransform()
        tr.scale(-1 if flip_h else 1, -1 if flip_v else 1)
        if rotation:
            tr.rotate(rotation)
        working = working.transformed(tr, Qt.TransformationMode.SmoothTransformation)

    canvas = QPixmap(size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    scale_size = QSize(max(1, int(size.width() * zoom / 100.0)), max(1, int(size.height() * zoom / 100.0)))
    mode = Qt.AspectRatioMode.IgnoreAspectRatio if fit == "stretch" else (Qt.AspectRatioMode.KeepAspectRatioByExpanding if fit == "cover" else Qt.AspectRatioMode.KeepAspectRatio)
    scaled = working.scaled(scale_size, mode, Qt.TransformationMode.SmoothTransformation)

    shift_x = int(size.width() * pan_x / 100.0)
    shift_y = int(size.height() * pan_y / 100.0)

    if fit == "cover" or scaled.width() > size.width() or scaled.height() > size.height():
        src_x = int((scaled.width() - size.width()) / 2 - shift_x)
        src_y = int((scaled.height() - size.height()) / 2 - shift_y)
        src_x = max(0, min(max(0, scaled.width() - size.width()), src_x))
        src_y = max(0, min(max(0, scaled.height() - size.height()), src_y))
        cropped = scaled.copy(src_x, src_y, min(size.width(), scaled.width()), min(size.height(), scaled.height()))
        dx = max(0, (size.width() - cropped.width()) // 2)
        dy = max(0, (size.height() - cropped.height()) // 2)
        painter.drawPixmap(dx, dy, cropped)
    else:
        dx = int((size.width() - scaled.width()) / 2 + shift_x)
        dy = int((size.height() - scaled.height()) / 2 + shift_y)
        dx = max(min(dx, size.width() - scaled.width()), -scaled.width() + 8) if scaled.width() else 0
        dy = max(min(dy, size.height() - scaled.height()), -scaled.height() + 8) if scaled.height() else 0
        painter.drawPixmap(dx, dy, scaled)

    painter.end()
    return canvas



def visual_style_profile(name: str, palette: dict | None = None) -> dict:
    """Presets compartidos por Splash Studio y el actualizador."""
    p = dict(palette or {})
    key = str(name or "neon").lower()
    if key == "match":
        return {
            "bg": p.get("window", "#080a10"), "panel": p.get("panel1", "#121826"),
            "text": p.get("title", "#fff4df"), "muted": p.get("muted", "#95a6c0"),
            "accent": p.get("accent", "#76ff6a"), "accent2": p.get("accent2", "#53e6ff"),
            "border": p.get("accent2", "#53e6ff"), "radius": 16,
        }
    profiles = {
        "neon": {"bg":"#070b13","panel":"#101827","text":"#f6f1e8","muted":"#95a6c0","accent":"#76ff6a","accent2":"#53e6ff","border":"#53e6ff","radius":16},
        "halloween": {"bg":"#0d0711","panel":"#1b1022","text":"#fff0dc","muted":"#b99cb7","accent":"#ff8a2a","accent2":"#b06cff","border":"#ff8a2a","radius":20},
        "cyber": {"bg":"#020d12","panel":"#061a21","text":"#ecfeff","muted":"#7eb0ba","accent":"#00f5d4","accent2":"#ff3bd4","border":"#00f5d4","radius":5},
        "sakura": {"bg":"#170d16","panel":"#281521","text":"#fff5f8","muted":"#d0a8b8","accent":"#ff8fbd","accent2":"#c6a2ff","border":"#ff8fbd","radius":22},
        "ocean": {"bg":"#04141b","panel":"#0a2731","text":"#eefcff","muted":"#8fb8c2","accent":"#42e8d0","accent2":"#69b8ff","border":"#42e8d0","radius":18},
        "arcade": {"bg":"#090413","panel":"#160c2a","text":"#fff8ff","muted":"#aaa1c6","accent":"#b7ff35","accent2":"#ff4fd8","border":"#ff4fd8","radius":4},
        "candy": {"bg":"#1a1020","panel":"#2d1835","text":"#fff8ff","muted":"#d5b7d8","accent":"#7ef5ff","accent2":"#ff91cf","border":"#ff91cf","radius":24},
        "sunset": {"bg":"#160a12","panel":"#29101b","text":"#fff4e8","muted":"#c6a39f","accent":"#ffb34f","accent2":"#ff5d8f","border":"#ff845f","radius":16},
        "retro": {"bg":"#071009","panel":"#0c1b10","text":"#e9ffe9","muted":"#83aa87","accent":"#79ff78","accent2":"#d4ff74","border":"#79ff78","radius":1},
        "minimal": {"bg":"#111318","panel":"#1a1d24","text":"#f3f5f8","muted":"#9ba3ad","accent":"#a9c9ff","accent2":"#d1d7e0","border":"#536070","radius":12},
    }
    return dict(profiles.get(key, profiles["neon"]))


def progress_style_sheet(style: str, profile: dict) -> str:
    key = str(style or "neon").lower()
    bg = profile.get("panel", "#121826")
    a = profile.get("accent", "#76ff6a")
    b = profile.get("accent2", "#53e6ff")
    text = profile.get("text", "#ffffff")
    radius = int(profile.get("radius", 12))
    if key == "minimal":
        return f"QProgressBar{{background:{bg};border:0;border-radius:3px;text-align:center;color:{text};min-height:8px;}}QProgressBar::chunk{{background:{a};border-radius:3px;}}"
    if key == "arcade":
        return f"QProgressBar{{background:#050507;border:2px solid {b};border-radius:2px;text-align:center;color:{text};font-weight:800;min-height:18px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {a},stop:.5 {b},stop:1 {a});margin:2px;}}"
    if key == "halloween":
        return f"QProgressBar{{background:#110915;border:1px solid #6d3c83;border-radius:10px;text-align:center;color:{text};min-height:16px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff7b1c,stop:.55 #ffb52f,stop:1 #9c54ff);border-radius:9px;}}"
    if key == "candy":
        return f"QProgressBar{{background:#24162a;border:1px solid #7ef5ff66;border-radius:14px;text-align:center;color:{text};min-height:18px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7ef5ff,stop:.5 #ff91cf,stop:1 #c6a2ff);border-radius:13px;}}"
    if key == "segmented":
        return f"QProgressBar{{background:{bg};border:1px solid {b}66;border-radius:5px;text-align:center;color:{text};min-height:15px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {a},stop:.15 {a},stop:.16 {bg},stop:.18 {bg},stop:.19 {b},stop:.34 {b},stop:.35 {bg},stop:.37 {bg},stop:.38 {a},stop:.53 {a},stop:.54 {bg},stop:.56 {bg},stop:.57 {b},stop:.72 {b},stop:.73 {bg},stop:.75 {bg},stop:.76 {a},stop:1 {a});border-radius:4px;}}"
    if key == "rainbow":
        return f"QProgressBar{{background:{bg};border:1px solid {b}55;border-radius:10px;text-align:center;color:{text};min-height:16px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #53e6ff,stop:.25 #76ff6a,stop:.5 #ffd45c,stop:.75 #ff7aa8,stop:1 #b06cff);border-radius:9px;}}"
    return f"QProgressBar{{background:{bg};border:1px solid {b}66;border-radius:9px;text-align:center;color:{text};min-height:16px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {b},stop:1 {a});border-radius:8px;}}"

def load_appearance() -> dict:
    data = default_appearance()
    saved = load_json_file(APPEARANCE_FILE, {}) if APPEARANCE_FILE.exists() else {}
    if isinstance(saved, dict):
        data.update(saved)
    data["accent"] = normalize_hex_color(data.get("accent"))
    data["accent2"] = normalize_hex_color(data.get("accent2"))
    return data


def save_appearance(data: dict) -> dict:
    clean = default_appearance()
    clean.update(data or {})
    clean["accent"] = normalize_hex_color(clean.get("accent"))
    clean["accent2"] = normalize_hex_color(clean.get("accent2"))
    clean["updatedAt"] = datetime.now().isoformat()
    save_json_file(APPEARANCE_FILE, clean)
    return clean


def copy_missing_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


def load_json_file(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def default_navigation_state() -> dict:
    return {
        "favorites": [],
        "recent": [],
        "expanded": {
            "stream": True,
            "interaction": True,
            "community": True,
            "design": False,
            "integrations": False,
            "system": False,
            "developer": False,
        },
        "compact": False,
        "updatedAt": None,
    }


def load_navigation_state() -> dict:
    state = default_navigation_state()
    saved = load_json_file(NAV_STATE_FILE, {}) if NAV_STATE_FILE.exists() else {}
    if isinstance(saved, dict):
        state.update(saved)
    if not isinstance(state.get("favorites"), list):
        state["favorites"] = []
    if not isinstance(state.get("recent"), list):
        state["recent"] = []
    expanded = default_navigation_state()["expanded"]
    if isinstance(state.get("expanded"), dict):
        expanded.update({str(k): bool(v) for k, v in state["expanded"].items()})
    state["expanded"] = expanded
    state["compact"] = bool(state.get("compact", False))
    return state


def save_navigation_state(state: dict) -> dict:
    clean = default_navigation_state()
    clean.update(state or {})
    clean["favorites"] = list(dict.fromkeys(str(x) for x in clean.get("favorites", []) if x))[:12]
    clean["recent"] = list(dict.fromkeys(str(x) for x in clean.get("recent", []) if x))[:6]
    clean["updatedAt"] = datetime.now().isoformat()
    save_json_file(NAV_STATE_FILE, clean)
    return clean


def save_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cada escritura recibe un archivo único; .tmp fijo falla si dos
    # solicitudes simultáneas guardan el mismo JSON.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def create_data_backup(prefix: str = "backup") -> Path | None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = BACKUPS_DIR / f"{prefix}_{stamp}.zip"

    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
            for folder, archive_prefix in (
                (DATA_DIR, "data"),
                (MEDIA_DIR, "user_media"),
                (LOADER_MEDIA_DIR, "loading_assets"),
                (BRANDING_DIR, "branding"),
            ):
                if folder.exists():
                    for file in folder.rglob("*"):
                        if file.is_file():
                            z.write(
                                file,
                                f"{archive_prefix}/{file.relative_to(folder)}",
                            )

            if STREAMLABS_FILE.exists():
                z.write(STREAMLABS_FILE, "private/streamlabs.json")

            if TWITCH_CONTROL_LOCAL_FILE.exists():
                z.write(TWITCH_CONTROL_LOCAL_FILE, "private/twitch_control.json")

            if KICK_LOCAL_FILE.exists():
                z.write(KICK_LOCAL_FILE, "private/kick.json")

            if DESKTOP_STATE_FILE.exists():
                z.write(DESKTOP_STATE_FILE, "private/desktop_state.json")

            if APPEARANCE_FILE.exists():
                z.write(APPEARANCE_FILE, "private/desktop_appearance.json")

            if SETUP_STATE_FILE.exists():
                z.write(SETUP_STATE_FILE, "private/setup_state.json")

            if NAV_STATE_FILE.exists():
                z.write(NAV_STATE_FILE, "private/navigation_state.json")

            metadata = {
                "appId": APP_ID,
                "appVersion": APP_VERSION,
                "createdAt": datetime.now().isoformat(),
                "kind": prefix,
            }
            z.writestr(
                "meta/backup.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )

        return output
    except Exception:
        return None


def run_migrations(state: dict) -> list[str]:
    """Migraciones idempotentes para mantener datos entre betas."""
    completed = set(state.get("completedMigrations") or [])
    applied = []

    def apply(migration_id: str, fn):
        if migration_id in completed:
            return
        fn()
        completed.add(migration_id)
        applied.append(migration_id)

    apply(
        "0.33-persistent-appdata-v1",
        lambda: (
            DATA_DIR.mkdir(parents=True, exist_ok=True),
            MEDIA_DIR.mkdir(parents=True, exist_ok=True),
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True),
            LOADER_MEDIA_DIR.mkdir(parents=True, exist_ok=True),
            BRANDING_DIR.mkdir(parents=True, exist_ok=True),
        ),
    )

    apply(
        "0.34-update-manager-v1",
        lambda: (
            UPDATES_DIR.mkdir(parents=True, exist_ok=True),
            STAGED_UPDATES_DIR.mkdir(parents=True, exist_ok=True),
        ),
    )

    def init_layout_studio():
        layout_file = DATA_DIR / "layout_studio.json"
        if not layout_file.exists():
            save_json_file(
                layout_file,
                {
                    "chat": {
                        "width": 450,
                        "scale": 100,
                        "position": "bottom-left",
                        "accent": "#76ff6a",
                        "backgroundOpacity": 92,
                        "radius": 14,
                    },
                    "alerts": {
                        "width": 720,
                        "scale": 100,
                        "position": "top-center",
                        "accent": "#76ff6a",
                        "backgroundOpacity": 94,
                        "radius": 16,
                    },
                    "updatedAt": datetime.now().isoformat(),
                },
            )

    apply("0.34-layout-studio-v1", init_layout_studio)

    def init_desktop_appearance():
        if not APPEARANCE_FILE.exists():
            save_appearance(default_appearance())

    apply("0.35-desktop-appearance-v1", init_desktop_appearance)

    apply(
        "0.40-loader-assets-v1",
        lambda: LOADER_MEDIA_DIR.mkdir(parents=True, exist_ok=True),
    )

    def migrate_036_appearance():
        current = load_appearance()
        defaults = default_appearance()
        changed = False
        for key in ("menuStyle", "showSidebarVersion", "showTitleVersion", "titlebarHeight"):
            if key not in current:
                current[key] = defaults[key]
                changed = True
        # V0.36 suaviza un poco el radio predeterminado sin tocar elecciones previas.
        if changed:
            save_appearance(current)

    apply("0.36-natural-desktop-ui-v1", migrate_036_appearance)

    apply(
        "0.37-comfort-navigation-v1",
        lambda: None,
    )

    apply(
        "0.42-weekly-rewards-v1",
        lambda: None,
    )

    apply(
        "0.44-goals-floating-chat-v1",
        lambda: None,
    )

    apply(
        "0.45-floating-chat-input-context-resize-v1",
        lambda: None,
    )

    def init_commercial_profile():
        if not PROFILE_FILE.exists():
            save_json_file(PROFILE_FILE, default_profile())

    apply("0.47-commercial-foundation-v1", init_commercial_profile)
    apply("0.48-owner-currency-redeem-v1", lambda: None)

    state["completedMigrations"] = sorted(completed)
    return applied


def ensure_persistent_storage() -> None:
    APPDATA_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    STAGED_UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    LOADER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if not APPEARANCE_FILE.exists():
        save_appearance(default_appearance())
    if not PROFILE_FILE.exists():
        save_json_file(PROFILE_FILE, default_profile())

    # Importa únicamente archivos faltantes. Nunca reemplaza datos del usuario.
    copy_missing_tree(resource_path("data"), DATA_DIR)
    copy_missing_tree(resource_path("user_media"), MEDIA_DIR)

    state = load_json_file(
        DESKTOP_STATE_FILE,
        {
            "appName": APP_NAME,
            "appId": APP_ID,
            "currentVersion": None,
            "previousVersion": None,
            "lastUpdateAt": None,
            "installPath": None,
            "dataDir": str(DATA_DIR),
            "mediaDir": str(MEDIA_DIR),
            "streamlabsFile": str(STREAMLABS_FILE),
            "autoBackups": [],
            "versionHistory": [],
            "completedMigrations": [],
            "migrationHistory": [],
        },
    )

    state.setdefault("versionHistory", [])
    state.setdefault("completedMigrations", [])
    state.setdefault("migrationHistory", [])
    state.setdefault("autoBackups", [])

    previous_version = state.get("currentVersion")

    if previous_version != APP_VERSION:
        backup = create_data_backup(
            f"auto_update_{(previous_version or 'first-run').replace('/', '-')}_to_{APP_VERSION}"
        )

        state["previousVersion"] = previous_version
        state["currentVersion"] = APP_VERSION
        state["lastUpdateAt"] = datetime.now().isoformat()
        state["versionHistory"].append(
            {
                "from": previous_version,
                "to": APP_VERSION,
                "at": state["lastUpdateAt"],
                "backup": backup.name if backup else None,
            }
        )
        state["versionHistory"] = state["versionHistory"][-30:]

        if backup:
            state["autoBackups"].append(
                {
                    "version": APP_VERSION,
                    "file": backup.name,
                    "createdAt": datetime.now().isoformat(),
                }
            )
            state["autoBackups"] = state["autoBackups"][-10:]

    applied = run_migrations(state)
    if applied:
        state["migrationHistory"].append(
            {
                "version": APP_VERSION,
                "at": datetime.now().isoformat(),
                "migrations": applied,
            }
        )
        state["migrationHistory"] = state["migrationHistory"][-30:]

    state["appName"] = APP_NAME
    state["appId"] = APP_ID
    state["installPath"] = str(resource_path("."))
    state["dataDir"] = str(DATA_DIR)
    state["mediaDir"] = str(MEDIA_DIR)
    state["streamlabsFile"] = str(STREAMLABS_FILE)
    save_json_file(DESKTOP_STATE_FILE, state)

    os.environ["BRYNN_DATA_DIR"] = str(DATA_DIR)
    os.environ["BRYNN_MEDIA_DIR"] = str(MEDIA_DIR)

def http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 1.0):
    data = None
    headers = {"Cache-Control": "no-cache"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def server_is_alive() -> bool:
    try:
        return bool(http_json(f"{LOCAL_BASE}/api/health", timeout=0.35).get("ok"))
    except Exception:
        return False


class BackendState(QObject):
    failed = Signal(str)


class BackendController:
    def __init__(self):
        self.state = BackendState()
        self.thread: threading.Thread | None = None
        self.owned = False
        self.module = None
        self.last_error = ""

    def start(self) -> None:
        if server_is_alive():
            self.owned = False
            return

        self.owned = True
        self.thread = threading.Thread(
            target=self._run,
            name="BrynnBackend",
            daemon=True,
        )
        self.thread.start()

    def _run(self) -> None:
        try:
            import server
            self.module = server
            server.run_server_forever()
        except Exception as exc:
            self.last_error = str(exc)
            try:
                logs = APPDATA_ROOT / "logs"
                logs.mkdir(parents=True, exist_ok=True)
                (logs / "desktop_backend_error.log").write_text(
                    f"{datetime.now().isoformat()}\n{exc!r}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            self.state.failed.emit(str(exc))

    def stop(self) -> None:
        if not self.owned or self.module is None:
            return
        try:
            self.module.shutdown_server()
        except Exception:
            pass


class TitleBar(QFrame):
    def __init__(self, host: "BrynnDesktop"):
        super().__init__(host)
        self.host = host
        self.setObjectName("titleBar")
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(8)

        mark = QLabel("◈")
        mark.setObjectName("titleMark")
        layout.addWidget(mark)

        self.title_label = QLabel("BRYNN INTERACTIVE")
        self.title_label.setObjectName("titleText")
        layout.addWidget(self.title_label)

        self.version_label = QLabel(APP_VERSION_LABEL)
        self.version_label.setObjectName("titleVersion")
        layout.addWidget(self.version_label)
        layout.addStretch(1)

        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("windowMin")
        self.min_btn.setToolTip("Minimizar")
        self.min_btn.clicked.connect(host.showMinimized)

        self.max_btn = QPushButton("□")
        self.max_btn.setObjectName("windowMax")
        self.max_btn.setToolTip("Maximizar / restaurar")
        self.max_btn.clicked.connect(self.toggle_maximize)

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("windowClose")
        self.close_btn.setToolTip("Cerrar / minimizar a bandeja")
        self.close_btn.clicked.connect(host.close)

        for button in (self.min_btn, self.max_btn, self.close_btn):
            button.setFixedSize(42, 30)
            layout.addWidget(button)

    def toggle_maximize(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()
        self.sync_state()

    def sync_state(self):
        self.max_btn.setText("❐" if self.host.isMaximized() else "□")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.host.windowHandle()
            if handle is not None:
                try:
                    handle.startSystemMove()
                    event.accept()
                    return
                except Exception:
                    pass
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class StatusCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        self.title = QLabel(title)
        self.title.setObjectName("statusTitle")
        self.value = QLabel("Comprobando...")
        self.value.setObjectName("statusValue")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("statusDetail")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_state(self, text: str, detail: str = "", good: bool | None = None):
        self.value.setText(text)
        self.detail.setText(detail)
        if good is True:
            self.value.setStyleSheet("color:#8cff3a;font-weight:700;")
        elif good is False:
            self.value.setStyleSheet("color:#ff637d;font-weight:700;")
        else:
            self.value.setStyleSheet("color:#ffd34e;font-weight:700;")



class LoaderSpinner(QWidget):
    """Loader nativo para evitar el destello blanco de Qt WebEngine."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "circle"
        self.phase = 0
        self.primary = QColor("#76ff6a")
        self.secondary = QColor("#53e6ff")
        self.visual_size = 72
        self.setFixedSize(self.visual_size, self.visual_size)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(55)

    def configure(self, mode: str, size: int, primary: str, secondary: str):
        self.mode = str(mode or "circle")
        self.visual_size = max(32, min(180, int(size or 72)))
        self.primary = QColor(primary or "#76ff6a")
        self.secondary = QColor(secondary or "#53e6ff")
        self.setFixedSize(self.visual_size, self.visual_size)
        self.update()

    def start(self):
        if not self.timer.isActive():
            self.timer.start()
        self.show()

    def stop(self):
        self.timer.stop()

    def _tick(self):
        self.phase = (self.phase + 1) % 120
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        if self.mode == "dots":
            radius = max(3.0, min(w, h) * 0.065)
            gap = radius * 3.1
            for i in range(3):
                pulse = (self.phase / 5.0 - i) % 3
                alpha = int(90 + 165 * max(0.0, 1.0 - abs(pulse - 1.0)))
                color = QColor(self.primary if i != 1 else self.secondary)
                color.setAlpha(alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QRectF(cx + (i - 1) * gap - radius, cy - radius, radius * 2, radius * 2))
            return

        if self.mode == "bar":
            bar_w = w * 0.86
            bar_h = max(7.0, h * 0.11)
            x = (w - bar_w) / 2
            y = (h - bar_h) / 2
            track = QColor(self.secondary)
            track.setAlpha(45)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_h / 2, bar_h / 2)
            chunk = bar_w * 0.34
            travel = bar_w - chunk
            pos = (math.sin(self.phase / 120 * math.tau - math.pi / 2) + 1) / 2
            grad = QColor(self.primary)
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(x + travel * pos, y, chunk, bar_h), bar_h / 2, bar_h / 2)
            return

        if self.mode == "glitch":
            base_y = cy - h * 0.18
            heights = [h * 0.08, h * 0.065, h * 0.045]
            widths = [w * 0.72, w * 0.58, w * 0.42]
            for i in range(3):
                offset = math.sin((self.phase + i * 13) * 0.23) * w * 0.09
                color = QColor(self.primary if i != 1 else self.secondary)
                color.setAlpha(230 - i * 45)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRect(QRectF(cx - widths[i] / 2 + offset, base_y + i * h * 0.16, widths[i], heights[i]))
            return

        # Círculo por defecto.
        radius = min(w, h) * 0.34
        thickness = max(3.0, min(w, h) * 0.075)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        segments = 12
        for i in range(segments):
            alpha = int(40 + (215 * (i + 1) / segments))
            color = QColor(self.primary if i < 8 else self.secondary)
            color.setAlpha(alpha)
            pen = QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            start = int((self.phase * 9 - i * (360 / segments)) * 16)
            span = int(-18 * 16)
            painter.drawArc(rect, start, span)


class LoadingOverlay(QFrame):
    """Tarjeta de carga personalizable que cubre sólo el área de contenido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("loadingOverlay")
        self.setCursor(Qt.CursorShape.WaitCursor)
        self.movie = None
        self.config = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addStretch(1)

        center = QHBoxLayout()
        center.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("loadingCard")
        self.card.setMinimumWidth(245)
        self.card.setMaximumWidth(360)
        box = QVBoxLayout(self.card)
        box.setContentsMargins(28, 24, 28, 22)
        box.setSpacing(12)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spinner = LoaderSpinner()
        box.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)

        self.media = QLabel()
        self.media.setObjectName("loadingMedia")
        self.media.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media.setScaledContents(False)
        self.media.hide()
        box.addWidget(self.media, 0, Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel("Cargando módulo…")
        self.title.setObjectName("loadingTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        box.addWidget(self.title)

        self.module = QLabel("")
        self.module.setObjectName("loadingModule")
        self.module.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.module.setWordWrap(True)
        box.addWidget(self.module)

        center.addWidget(self.card)
        center.addStretch(1)
        root.addLayout(center)
        root.addStretch(1)
        self.hide()

    def _stop_movie(self):
        if self.movie is not None:
            try:
                self.movie.stop()
            except Exception:
                pass
        self.movie = None
        self.media.clear()

    def configure(self, config: dict, palette: dict, media_path: Path | None = None):
        self.config = dict(config or {})
        mode = str(self.config.get("loadingType") or "circle")
        size = max(32, min(180, int(self.config.get("loadingSize") or 72)))
        primary = str(palette.get("accent") or "#76ff6a")
        secondary = str(palette.get("accent2") or "#53e6ff")
        opacity = max(0, min(100, int(self.config.get("loadingBackdropOpacity") or 82)))
        backdrop = bool(self.config.get("loadingBackdrop", True))
        alpha = int(255 * opacity / 100) if backdrop else 0
        window = QColor(str(palette.get("window") or "#080a10"))
        panel = str(palette.get("panel1") or "#121826")
        text = str(palette.get("text") or "#eef3ff")
        muted = str(palette.get("muted") or "#93a2bd")
        accent = primary

        self.setStyleSheet(f"""
            QFrame#loadingOverlay {{
                background: rgba({window.red()},{window.green()},{window.blue()},{alpha});
            }}
            QFrame#loadingCard {{
                background: {panel};
                border: 1px solid {accent}55;
                border-radius: 18px;
            }}
            QLabel#loadingTitle {{
                color: {text};
                font-size: 15px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#loadingModule {{
                color: {muted};
                font-size: 11px;
                background: transparent;
            }}
            QLabel#loadingMedia {{ background: transparent; border: 0; }}
        """)

        self.spinner.configure(mode, size, primary, secondary)
        self._stop_movie()

        is_media = mode in ("image", "emote") and media_path and media_path.exists()
        if is_media:
            self.spinner.stop()
            self.spinner.hide()
            self.media.setFixedSize(size, size)
            suffix = media_path.suffix.lower()
            if suffix == ".gif":
                movie = QMovie(str(media_path))
                movie.setScaledSize(self.media.size())
                self.movie = movie
                self.media.setMovie(movie)
                movie.start()
            else:
                pix = QPixmap(str(media_path))
                if not pix.isNull():
                    pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.media.setPixmap(pix)
            self.media.show()
        else:
            self.media.hide()
            self.spinner.show()

        show_text = bool(self.config.get("loadingShowText", True))
        self.title.setVisible(show_text)
        self.title.setText(str(self.config.get("loadingText") or "Cargando módulo…"))

    def show_loader(self, module_name: str = ""):
        self.module.setText(str(module_name or ""))
        if self.spinner.isVisible():
            self.spinner.start()
        if self.movie is not None:
            self.movie.start()
        self.show()
        self.raise_()

    def hide_loader(self):
        self.spinner.stop()
        if self.movie is not None:
            self.movie.stop()
        self.hide()


class SplashEditorItem(QFrame):
    """Objeto movible/redimensionable del editor visual del splash."""
    geometryChanged = Signal(str, dict)
    previewTransformChanged = Signal(str, dict)
    selected = Signal(str)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.label_text = str(label or key)
        self._drag_mode = ""
        self._press_pos = None
        self._press_global_pos = None
        self._start_geo = None
        self._preview_path = ""
        self._original_pixmap = QPixmap()
        self._fallback_text = self.label_text
        self._selected = False
        self._fit = "contain"
        self._zoom = 100
        self._pan_x = 0
        self._pan_y = 0
        self._rotation = 0
        self._flip_h = False
        self._flip_v = False
        self._start_transform = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(34, 26)
        self.setObjectName("splashEditorItem")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.preview = QLabel()
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview.setMinimumSize(16, 16)
        self.caption = QLabel(self.label_text)
        self.caption.setObjectName("caption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.caption, 0)
        self._refresh_style()

    def _refresh_style(self):
        border = "#76ff6a" if self._selected else "rgba(83,230,255,180)"
        bg = "rgba(12,18,28,215)" if self._selected else "rgba(10,15,24,185)"
        caption_bg = "rgba(118,255,106,30)" if self._selected else "rgba(83,230,255,24)"
        self.setStyleSheet(
            f"QFrame#splashEditorItem{{background:{bg};border:1px solid {border};border-radius:8px;}}"
            "QLabel#preview{background:transparent;border:0;padding:2px;color:#eaf6ff;font-size:11px;font-weight:800;}"
            f"QLabel#caption{{color:#eaf6ff;background:{caption_bg};border:0;border-top:1px solid rgba(255,255,255,0.08);font-size:10px;font-weight:800;padding:4px 6px;border-bottom-left-radius:6px;border-bottom-right-radius:6px;}}"
        )

    def set_selected(self, value: bool):
        self._selected = bool(value)
        self._refresh_style()

    def _apply_preview(self, fallback: str = ""):
        fallback = str(fallback or self._fallback_text or self.key.upper())
        self._fallback_text = fallback
        self.caption.setText(self.label_text or fallback)
        self.preview.setPixmap(QPixmap())
        self.preview.setText("")
        path = Path(self._preview_path) if self._preview_path else None
        if path and path.exists():
            ext = path.suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                # Reutiliza la imagen decodificada mientras se mueve/escala.
                pix = self._original_pixmap
                if not pix.isNull():
                    target = QSize(max(20, self.width() - 12), max(20, self.height() - 36))
                    self.preview.setPixmap(render_media_pixmap(
                        pix, target, self._fit, self._zoom, self._pan_x, self._pan_y, self._rotation, self._flip_h, self._flip_v
                    ))
                    return
            elif ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}:
                self.preview.setText("🎞\nVÍDEO")
                return
        self.preview.setText(fallback)

    def set_preview(self, path: str = "", fallback: str = "", fit: str = "contain", transform: dict | None = None):
        new_path = str(path or "")
        if new_path != self._preview_path:
            self._preview_path = new_path
            self._original_pixmap = QPixmap()
            if Path(new_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"} and Path(new_path).is_file():
                self._original_pixmap = QPixmap(new_path)
        self._fallback_text = str(fallback or self.label_text or self.key.upper())
        self._fit = str(fit or "contain")
        transform = dict(transform or {})
        self._zoom = int(transform.get("zoom", 100) or 100)
        self._pan_x = int(transform.get("panX", 0) or 0)
        self._pan_y = int(transform.get("panY", 0) or 0)
        self._rotation = int(transform.get("rotation", 0) or 0)
        self._flip_h = bool(transform.get("flipH", False))
        self._flip_v = bool(transform.get("flipV", False))
        self._apply_preview(self._fallback_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_preview(self._fallback_text)

    def _emit_preview_transform(self):
        self.previewTransformChanged.emit(self.key, {
            "zoom": int(self._zoom),
            "panX": int(self._pan_x),
            "panY": int(self._pan_y),
            "rotation": int(self._rotation),
            "flipH": bool(self._flip_h),
            "flipV": bool(self._flip_v),
        })

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.selected.emit(self.key)
            self.raise_()
            self._press_pos = event.position().toPoint()
            self._press_global_pos = event.globalPosition().toPoint()
            self._start_geo = self.geometry()
            self._start_transform = {"panX": self._pan_x, "panY": self._pan_y}
            edge = 16
            if event.button() == Qt.MouseButton.RightButton and self._preview_path:
                self._drag_mode = "pan"
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif self._press_pos.x() >= self.width() - edge and self._press_pos.y() >= self.height() - edge:
                self._drag_mode = "resize"
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self._drag_mode = "move"
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._drag_mode or self._press_pos is None or self._start_geo is None:
            return super().mouseMoveEvent(event)
        # event.position() cambia cuando el widget se mueve: provoca saltos.
        # La posición global permanece estable durante todo el arrastre.
        delta = event.globalPosition().toPoint() - self._press_global_pos
        parent = self.parentWidget()
        if not parent:
            return
        work = parent.work_rect() if hasattr(parent, "work_rect") else parent.rect()
        if self._drag_mode == "move":
            x = max(work.x(), min(work.right() - self.width() + 1, self._start_geo.x() + delta.x()))
            y = max(work.y(), min(work.bottom() - self.height() + 1, self._start_geo.y() + delta.y()))
            self.move(x, y)
        elif self._drag_mode == "resize":
            max_w = max(34, work.right() - self.x() + 1)
            max_h = max(26, work.bottom() - self.y() + 1)
            w = max(34, min(max_w, self._start_geo.width() + delta.x()))
            h = max(26, min(max_h, self._start_geo.height() + delta.y()))
            self.resize(w, h)
        elif self._drag_mode == "pan":
            self._pan_x = max(-200, min(200, int((self._start_transform.get("panX", 0)) + (delta.x() * 100 / max(1, self.width())))))
            self._pan_y = max(-200, min(200, int((self._start_transform.get("panY", 0)) + (delta.y() * 100 / max(1, self.height())))))
            self._apply_preview(self._fallback_text)
        event.accept()

    def wheelEvent(self, event):
        if self._preview_path and self._selected:
            delta = event.angleDelta().y()
            if delta:
                step = 5 if delta > 0 else -5
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._rotation = int((self._rotation + step) % 360)
                else:
                    self._zoom = max(10, min(400, int(self._zoom + step)))
                self._apply_preview(self._fallback_text)
                self._emit_preview_transform()
                event.accept()
                return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._preview_path:
            self._zoom = 100
            self._pan_x = 0
            self._pan_y = 0
            self._rotation = 0
            self._apply_preview(self._fallback_text)
            self._emit_preview_transform()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_mode:
            drag_mode = self._drag_mode
            self._drag_mode = ""
            self._press_global_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if drag_mode == "pan":
                self._emit_preview_transform()
                event.accept()
                return
            parent = self.parentWidget()
            if parent and parent.width() and parent.height():
                g = self.geometry()
                work = parent.work_rect() if hasattr(parent, "work_rect") else parent.rect()
                base_w = max(1, work.width())
                base_h = max(1, work.height())
                self.geometryChanged.emit(self.key, {
                    "x": round((g.x() - work.x()) / base_w, 4), "y": round((g.y() - work.y()) / base_h, 4),
                    "w": round(g.width() / base_w, 4), "h": round(g.height() / base_h, 4)
                })
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SplashEditorCanvas(QFrame):
    layoutChanged = Signal(dict)
    mediaItemsChanged = Signal(list)
    selectionChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("splashEditorCanvas")
        self.setMinimumHeight(500)
        self.setMinimumWidth(420)
        self._layout_data = {}
        self._media_items = []
        self.background_color = "#080b12"
        self.preset = "neon"
        self.items = {}
        self._selected_key = ""
        self._workspace_padding = 26
        labels={"logo":"LOGO","title":"TÍTULO","subtitle":"SUBTÍTULO","progress":"BARRA DE PROGRESO","status":"ESTADO"}
        for key,label in labels.items():
            self._create_item(key,label)
        self.setToolTip("Área de trabajo tipo Photoshop: el rectángulo central es el lienzo 16:9. Arrastra cualquier objeto. Esquina inferior derecha = cambiar tamaño. Rueda = zoom, Ctrl+rueda = rotar y clic derecho y arrastra = reencuadrar la imagen.")

    def _create_item(self,key,label):
        item=SplashEditorItem(key,label,self)
        item.geometryChanged.connect(self._item_changed)
        item.previewTransformChanged.connect(self._item_preview_changed)
        item.selected.connect(self._select_key)
        self.items[key]=item
        return item

    def _select_key(self,key):
        key=str(key or "")
        if self._selected_key == key:
            for k,item in self.items.items(): item.set_selected(k==key)
            if key in self.items:
                try: self.items[key].raise_()
                except Exception: pass
            return
        self._selected_key=key
        for k,item in self.items.items(): item.set_selected(k==self._selected_key)
        if key in self.items:
            try: self.items[key].raise_()
            except Exception: pass
        self.selectionChanged.emit(self._selected_key)

    def selected_key(self): return self._selected_key

    def work_rect(self) -> QRect:
        pad = self._workspace_padding
        available = self.rect().adjusted(pad, pad, -pad, -pad)
        if available.width() < 10 or available.height() < 10:
            return self.rect().adjusted(4, 4, -4, -4)
        target_ratio = 16 / 9
        aw = available.width()
        ah = available.height()
        if aw / max(1, ah) > target_ratio:
            h = ah
            w = int(h * target_ratio)
        else:
            w = aw
            h = int(w / target_ratio)
        x = available.x() + max(0, (aw - w) // 2)
        y = available.y() + max(0, (ah - h) // 2)
        return QRect(x, y, max(20, w), max(20, h))

    def set_config(self, config: dict):
        self._layout_data = json.loads(json.dumps(config.get("startupLayout") or default_appearance()["startupLayout"]))
        self.background_color = normalize_hex_color(config.get("startupBackground")) or "#080b12"
        self.preset = str(config.get("startupPreset") or "neon")
        # Migra el único MEDIA de V0.56 sin perderlo.
        media_items=config.get("startupMediaItems") if isinstance(config.get("startupMediaItems"),list) else []
        if not media_items and str(config.get("startupMediaPath") or "").strip():
            legacy_spec=(self._layout_data.get("media") or default_appearance()["startupLayout"]["media"]).copy()
            media_items=[{"id":"legacy","path":str(config.get("startupMediaPath")),"name":Path(str(config.get("startupMediaPath"))).name,"fit":"contain","opacity":100,"animation":"none","zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False,"z":1,**legacy_spec}]
        self._media_items=json.loads(json.dumps(media_items))
        # Elimina widgets dinámicos anteriores.
        for key in [k for k in self.items if k.startswith("asset:")]:
            w=self.items.pop(key); w.setParent(None); w.deleteLater()
        # Crea las capas dinámicas. Las capas creadas después de que el canvas
        # está visible deben recibir show() explícito (Qt las deja ocultas).
        new_media_widgets = []
        for idx,data in enumerate(self._media_items):
            ident=str(data.get("id") or f"asset{idx+1}")
            data["id"]=ident
            key=f"asset:{ident}"
            item=self._create_item(key,str(data.get("name") or Path(str(data.get("path") or "MEDIA")).name or "MEDIA"))
            item.set_preview(str(data.get("path") or ""),"VÍDEO" if Path(str(data.get("path") or "")).suffix.lower() in {".mp4",".webm",".mov",".m4v",".avi",".mkv"} else "MEDIA",str(data.get("fit") or "contain"), data)
            self._layout_data[key]={k:float(data.get(k, default)) for k,default in (("x",.08),("y",.12),("w",.28),("h",.44))}
            new_media_widgets.append(item)
            item.raise_()
        for fixed in ("logo","title","subtitle","progress","status"):
            if fixed in self.items: self.items[fixed].raise_()
        self.items["logo"].setVisible(bool(config.get("startupShowLogo", True)))
        self.items["logo"].set_preview(str(resource_path("brynn_default.png")),"LOGO","contain", {})
        self.items["title"].caption.setText(str(config.get("startupTitle") or "TÍTULO"))
        self.items["subtitle"].caption.setText(str(config.get("startupSubtitle") or "SUBTÍTULO"))
        self._apply_layout()
        for item in new_media_widgets:
            item.show()  # imprescindible en canvas ya mostrado
        # Preserva la selección al cambiar tamaño, añadir o actualizar capas.
        if self._selected_key in self.items:
            self._select_key(self._selected_key)
        else:
            self._selected_key = ""
        self.update()

    def layout_data(self):
        base={k:v for k,v in self._layout_data.items() if not str(k).startswith("asset:")}
        return json.loads(json.dumps(base))

    def media_items(self):
        rows=[]
        by_id={str(x.get("id")):dict(x) for x in self._media_items}
        for ident,row in by_id.items():
            spec=self._layout_data.get(f"asset:{ident}") or {}
            row.update({k:float(spec.get(k,row.get(k,default))) for k,default in (("x",.08),("y",.12),("w",.28),("h",.44))})
            rows.append(row)
        rows.sort(key=lambda x:int(x.get("z",0)))
        return json.loads(json.dumps(rows))

    def _item_changed(self, key, spec):
        self._layout_data[key]=dict(spec)
        if str(key).startswith("asset:"):
            self.mediaItemsChanged.emit(self.media_items())
        else:
            self.layoutChanged.emit(self.layout_data())

    def _item_preview_changed(self, key, spec):
        if not str(key).startswith("asset:"):
            return
        ident = str(key).split(":", 1)[1]
        for row in self._media_items:
            if str(row.get("id")) == ident:
                row.update(dict(spec or {}))
                break
        self.mediaItemsChanged.emit(self.media_items())

    def _apply_layout(self):
        defaults=default_appearance()["startupLayout"]
        work = self.work_rect()
        for key,item in self.items.items():
            spec=self._layout_data.get(key) or defaults.get(key) or {"x":.1,"y":.1,"w":.2,"h":.1}
            x=work.x()+int(float(spec.get("x",.1))*max(1,work.width()))
            y=work.y()+int(float(spec.get("y",.1))*max(1,work.height()))
            w=max(34,int(float(spec.get("w",.2))*max(1,work.width())))
            h=max(26,int(float(spec.get("h",.1))*max(1,work.height())))
            max_w=max(34,work.right()-x+1)
            max_h=max(26,work.bottom()-y+1)
            item.setGeometry(x,y,min(w,max_w),min(h,max_h))

    def resizeEvent(self, event):
        super().resizeEvent(event); self._apply_layout()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        profile=visual_style_profile(self.preset)
        workspace=QColor("#10151d")
        painter.fillRect(self.rect(), workspace)
        work = self.work_rect()
        artboard=QColor(self.background_color or profile["bg"])
        shadow = QColor(0,0,0,90)
        painter.fillRect(work.adjusted(6,6,6,6), shadow)
        painter.fillRect(work, artboard)
        # Checkerboard subtle like design apps
        tile_a = QColor(255,255,255,6)
        tile_b = QColor(0,0,0,8)
        tile = 18
        for yy in range(work.y(), work.bottom()+1, tile):
            for xx in range(work.x(), work.right()+1, tile):
                painter.fillRect(QRect(xx, yy, min(tile, work.right()-xx+1), min(tile, work.bottom()-yy+1)), tile_a if ((xx//tile)+(yy//tile)) % 2 == 0 else tile_b)
        painter.fillRect(work, artboard)
        grid=QColor(profile.get("accent2","#53e6ff")); grid.setAlpha(34); painter.setPen(QPen(grid,1))
        for i in range(1,16):
            x = work.x() + int(work.width()*i/16)
            painter.drawLine(x, work.y(), x, work.bottom())
        for i in range(1,9):
            y = work.y() + int(work.height()*i/9)
            painter.drawLine(work.x(), y, work.right(), y)
        safe = work.adjusted(int(work.width()*0.05), int(work.height()*0.05), -int(work.width()*0.05), -int(work.height()*0.05))
        safe_color = QColor(profile.get("primary","#76ff6a")); safe_color.setAlpha(70)
        painter.setPen(QPen(safe_color,1,Qt.PenStyle.DashLine))
        painter.drawRect(safe)
        edge=QColor(profile.get("border","#53e6ff")); edge.setAlpha(180); painter.setPen(QPen(edge,2)); painter.drawRect(work.adjusted(0,0,-1,-1))
        label_bg = QRect(work.x()+10, work.y()+10, 112, 24)
        painter.fillRect(label_bg, QColor(8,12,20,180))
        painter.setPen(QColor("#eaf6ff"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(label_bg.adjusted(8,0,0,0), Qt.AlignmentFlag.AlignVCenter, "LIENZO 16:9")


class StartupSplashWindow(QWidget):
    """Splash de inicio V2: múltiples capas, ajuste, animación y presets."""
    def __init__(self, config: dict):
        super().__init__(None)
        self.config=dict(config or {})
        self._started_at=time.monotonic()
        self.audio_player=None; self.audio_output=None
        self._media_layers=[]
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1040,585)
        self.setMinimumSize(760,428)
        self.profile=visual_style_profile(str(self.config.get("startupPreset") or "neon"))
        bg=normalize_hex_color(self.config.get("startupBackground")) or self.profile["bg"]
        self.setStyleSheet(f"QWidget{{background:{bg};color:{self.profile['text']};font-family:'Segoe UI';}}")

        self.logo=QLabel(self); self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter); self.logo.setStyleSheet("background:transparent;border:0;")
        self.title=QLabel(str(self.config.get("startupTitle") or "BRYNN INTERACTIVE"),self); self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(f"font-size:30px;font-weight:900;letter-spacing:2px;color:{self.profile['text']};background:transparent;")
        self.subtitle=QLabel(str(self.config.get("startupSubtitle") or "Preparando tu centro de control…"),self); self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter); self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet(f"font-size:12px;color:{self.profile['muted']};background:transparent;")
        self.progress=QProgressBar(self); self.progress.setRange(0,100); self.progress.setTextVisible(False)
        self.progress.setStyleSheet(progress_style_sheet(str(self.config.get("startupProgressStyle") or "neon"),self.profile))
        self.status=QLabel("Iniciando…",self); self.status.setAlignment(Qt.AlignmentFlag.AlignCenter); self.status.setStyleSheet(f"font-size:11px;color:{self.profile['muted']};background:transparent;")
        self._load_logo(); self._load_media_layers(); self._load_audio(); self._apply_layout()
        self.anim_timer=QTimer(self); self.anim_timer.setInterval(40); self.anim_timer.timeout.connect(self._tick_animations); self.anim_timer.start()
        screen=QApplication.primaryScreen()
        if screen:
            geo=screen.availableGeometry(); self.move(geo.center()-self.rect().center())

    def _load_logo(self):
        logo_path=resource_path("brynn_default.png")
        self.logo.setVisible(bool(self.config.get("startupShowLogo",True)))
        if logo_path.exists():
            pix=QPixmap(str(logo_path))
            if not pix.isNull(): self.logo.setProperty("originalPixmap",pix); self.logo.setPixmap(pix)

    def _normalized_media_items(self):
        rows=self.config.get("startupMediaItems") if isinstance(self.config.get("startupMediaItems"),list) else []
        if not rows and str(self.config.get("startupMediaPath") or "").strip():
            spec=(self.config.get("startupLayout") or {}).get("media") or default_appearance()["startupLayout"]["media"]
            rows=[{"id":"legacy","path":str(self.config.get("startupMediaPath")),"fit":"contain","opacity":100,"animation":"none","zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False,"z":1,**spec}]
        return sorted([dict(r) for r in rows if str(r.get("path") or "").strip()],key=lambda r:int(r.get("z",0)))

    def _load_media_layers(self):
        for row in self._normalized_media_items():
            path=Path(str(row.get("path") or ""))
            if not path.exists(): continue
            ext=path.suffix.lower(); layer={"cfg":row,"path":path,"movie":None,"player":None,"audio":None,"effect":None,"widget":None,"base":None}
            if ext in {".mp4",".webm",".mov",".mkv",".avi",".m4v"} and QT_MULTIMEDIA_AVAILABLE:
                widget=QVideoWidget(self); player=QMediaPlayer(self); out=QAudioOutput(self); out.setVolume(0.0); player.setAudioOutput(out); player.setVideoOutput(widget); player.setSource(QUrl.fromLocalFile(str(path))); player.setLoops(QMediaPlayer.Loops.Infinite); player.play(); layer.update({"widget":widget,"player":player,"audio":out})
            else:
                widget=QLabel(self); widget.setAlignment(Qt.AlignmentFlag.AlignCenter); widget.setStyleSheet("background:transparent;border:0;")
                if ext==".gif":
                    movie=QMovie(str(path)); widget.setMovie(movie); movie.start(); layer["movie"]=movie
                else:
                    pix=QPixmap(str(path)); widget.setProperty("originalPixmap",pix)
                layer["widget"]=widget
            effect=QGraphicsOpacityEffect(layer["widget"]); layer["widget"].setGraphicsEffect(effect); layer["effect"]=effect
            layer["widget"].show(); self._media_layers.append(layer)

    def _load_audio(self):
        audio_path=Path(str(self.config.get("startupAudioPath") or "")) if self.config.get("startupAudioPath") else None
        if audio_path and audio_path.exists() and QT_MULTIMEDIA_AVAILABLE:
            try:
                self.audio_player=QMediaPlayer(self); self.audio_output=QAudioOutput(self); self.audio_output.setVolume(max(0,min(100,int(self.config.get("startupAudioVolume") or 55)))/100.0); self.audio_player.setAudioOutput(self.audio_output); self.audio_player.setSource(QUrl.fromLocalFile(str(audio_path))); self.audio_player.play()
            except Exception: pass

    def _geom(self,key,default):
        data=self.config.get("startupLayout") if isinstance(self.config.get("startupLayout"),dict) else {}
        spec=data.get(key) if isinstance(data.get(key),dict) else default
        return QRectF(float(spec.get("x",default["x"]))*self.width(),float(spec.get("y",default["y"]))*self.height(),float(spec.get("w",default["w"]))*self.width(),float(spec.get("h",default["h"]))*self.height()).toRect()

    def _media_rect(self,row):
        return QRectF(float(row.get("x",.08))*self.width(),float(row.get("y",.12))*self.height(),float(row.get("w",.28))*self.width(),float(row.get("h",.44))*self.height()).toRect()

    def _fit_pixmap(self,pix:QPixmap,size:QSize,fit:str):
        if pix.isNull() or size.width()<1 or size.height()<1: return pix
        if fit=="stretch": return pix.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        if fit=="cover":
            scaled=pix.scaled(size,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation)
            x=max(0,(scaled.width()-size.width())//2); y=max(0,(scaled.height()-size.height())//2)
            return scaled.copy(x,y,size.width(),size.height())
        return pix.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)

    def _apply_layout(self):
        defaults=default_appearance()["startupLayout"]
        for key,widget in [("logo",self.logo),("title",self.title),("subtitle",self.subtitle),("progress",self.progress),("status",self.status)]: widget.setGeometry(self._geom(key,defaults[key]))
        pix=self.logo.property("originalPixmap")
        if isinstance(pix,QPixmap) and not pix.isNull(): self.logo.setPixmap(self._fit_pixmap(pix,self.logo.size(),"contain"))
        for layer in self._media_layers:
            rect=self._media_rect(layer["cfg"]); layer["base"]=rect; layer["widget"].setGeometry(rect)
            fit=str(layer["cfg"].get("fit") or "contain")
            if layer.get("movie") is not None: layer["movie"].setScaledSize(rect.size())
            else:
                pix=layer["widget"].property("originalPixmap") if isinstance(layer["widget"],QLabel) else None
                if isinstance(pix,QPixmap) and not pix.isNull():
                    layer["widget"].setPixmap(render_media_pixmap(
                        pix, rect.size(), fit, int(layer["cfg"].get("zoom", 100) or 100), int(layer["cfg"].get("panX", 0) or 0), int(layer["cfg"].get("panY", 0) or 0), int(layer["cfg"].get("rotation", 0) or 0), bool(layer["cfg"].get("flipH", False)), bool(layer["cfg"].get("flipV", False))
                    ))
            try: layer["widget"].raise_()
            except Exception: pass
        self.logo.raise_(); self.title.raise_(); self.subtitle.raise_(); self.progress.raise_(); self.status.raise_()

    def _tick_animations(self):
        t=time.monotonic()-self._started_at
        for layer in self._media_layers:
            base=layer.get("base") or self._media_rect(layer["cfg"]); anim=str(layer["cfg"].get("animation") or "none"); rect=QRectF(base)
            opacity=max(0,min(100,int(layer["cfg"].get("opacity",100))))/100.0
            if anim=="float": rect.translate(0,math.sin(t*2.2)*8)
            elif anim=="drift": rect.translate(math.sin(t*1.7)*10,0)
            elif anim=="breathe":
                f=1.0+0.025*math.sin(t*2.4); dx=rect.width()*(f-1)/2; dy=rect.height()*(f-1)/2; rect.adjust(-dx,-dy,dx,dy)
            elif anim=="pulse": opacity*=0.76+0.24*((math.sin(t*3.2)+1)/2)
            elif anim=="fade": opacity*=min(1.0,max(0.0,t/0.8))
            layer["widget"].setGeometry(rect.toRect()); layer["effect"].setOpacity(opacity)

    def resizeEvent(self,event): super().resizeEvent(event); self._apply_layout()

    def set_progress(self,value:int,status:str=""):
        self.progress.setValue(max(0,min(100,int(value))))
        if status: self.status.setText(str(status))
        QApplication.processEvents()

    def stop_media(self):
        try:
            if hasattr(self,"anim_timer"): self.anim_timer.stop()
            for layer in self._media_layers:
                if layer.get("movie"): layer["movie"].stop()
                if layer.get("player"): layer["player"].stop()
            if self.audio_player: self.audio_player.stop()
        except Exception: pass

    def closeEvent(self,event): self.stop_media(); super().closeEvent(event)


class DesktopWebPage(QWebEnginePage):
    """Intercepta enlaces internos para que los gestione el shell de escritorio.

    Evita que un <a href="/...html"> navegue directamente dentro del WebView
    visible, que era la causa del lienzo negro/desincronizado al usar los botones
    superiores de las páginas administrativas.
    """
    localRouteRequested = Signal(str)
    desktopCommandRequested = Signal(str)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        try:
            scheme = url.scheme().lower()
            if scheme == "brynn":
                command = (url.host() + url.path()).strip("/")
                if url.query(): command += "?" + url.query()
                self.desktopCommandRequested.emit(command)
                return False

            host = (url.host() or "").lower()
            port = url.port(80)
            path = url.path() or ""
            local_http = scheme in {"http", "https"} and host in {"127.0.0.1", "localhost"} and port == 8765

            # Toda navegación web externa del frame principal sale al navegador
            # del sistema. Así OAuth, documentación y cualquier enlace futuro no
            # pueden reemplazar el panel de Brynn ni dejar un WebView negro.
            if is_main_frame and scheme in {"http", "https"} and not local_http:
                QDesktopServices.openUrl(url)
                return False

            clicked = navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            if clicked and is_main_frame and local_http and path.lower().endswith(".html"):
                self.localRouteRequested.emit(path.lstrip("/"))
                return False
        except Exception:
            pass
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)



class FloatingChatWebView(QWebEngineView):
    """WebView sin el menú contextual nativo de Chromium.

    El DOM sigue recibiendo el evento `contextmenu`, por lo que floating_chat.js
    puede mostrar el menú de moderación de Brynn.
    """
    def contextMenuEvent(self, event):
        event.accept()


class FloatingDragBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.window_ref=window
        self._offset=None
        self.setFixedHeight(28)
        self.setStyleSheet("QFrame{background:rgba(7,12,20,185);border:1px solid rgba(83,230,255,70);border-radius:8px;} QLabel{background:transparent;color:#dfe8f5;font-size:10px;font-weight:700;letter-spacing:1px} QPushButton{background:rgba(255,255,255,18);color:#fff;border:0;border-radius:5px;padding:3px 8px}")
        lay=QHBoxLayout(self); lay.setContentsMargins(8,3,4,3); lay.setSpacing(5)
        lab=QLabel("BRYNN CHAT · ARRASTRA AQUÍ"); lay.addWidget(lab); lay.addStretch(1)
        click=QPushButton("Click-through"); click.clicked.connect(window.toggle_click_through); lay.addWidget(click)
        hide=QPushButton("Ocultar"); hide.clicked.connect(window.hide); lay.addWidget(hide)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self._offset=event.globalPosition().toPoint()-self.window_ref.frameGeometry().topLeft(); event.accept(); return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self._offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window_ref.move(event.globalPosition().toPoint()-self._offset); event.accept(); return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        self._offset=None; super().mouseReleaseEvent(event)


class FloatingChatWindow(QMainWindow):
    """Chat transparente, always-on-top y con modo click-through.

    V0.45: la geometría que el usuario ajusta con el ratón se conserva y los
    cambios de configuración ya no fuerzan el tamaño anterior. También se
    desactiva el menú contextual nativo de Chromium para dejar pasar el menú
    de moderación implementado por Brynn en HTML/JS.
    """
    def __init__(self, owner):
        super().__init__(None)
        self.owner = owner
        self.cfg = {}
        self.click_through = False
        self._hotkey_down = {}
        self._last_cfg_stamp = ""
        self._last_configured_size = None
        self._applying_config_geometry = True
        self.position_settings=QSettings("BrynnInteractive","BrynnInteractiveDesktop")
        self.setWindowTitle("Brynn Floating Chat")
        self.setWindowIcon(owner.windowIcon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        central=QWidget(self); central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay=QVBoxLayout(central); lay.setContentsMargins(3,3,3,3); lay.setSpacing(3)
        self.drag_bar=FloatingDragBar(self); lay.addWidget(self.drag_bar)
        self.web = FloatingChatWebView(self)
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.web.setStyleSheet("background: transparent;")
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web.page().setBackgroundColor(QColor(0,0,0,0))
        self.web.loadFinished.connect(lambda ok: self.set_click_through(self.click_through, announce=False) if ok else None)
        lay.addWidget(self.web,1)
        grip_row=QHBoxLayout(); grip_row.setContentsMargins(0,0,0,0); grip_row.addStretch(1); self.grip=QSizeGrip(central); self.grip.setFixedSize(14,14); grip_row.addWidget(self.grip); lay.addLayout(grip_row)
        self.setCentralWidget(central)
        self.resize(520,720)
        self._load_config(first=True)
        try:
            saved_pos=self.position_settings.value("floatingChatPos")
            if saved_pos is not None and hasattr(saved_pos,"x"): self.move(saved_pos)
        except Exception:
            pass
        self.web.setUrl(QUrl(f"{LOCAL_BASE}/floating_chat.html?v={ASSET_VERSION}"))
        self.cfg_timer=QTimer(self); self.cfg_timer.timeout.connect(self._load_config); self.cfg_timer.start(2500)
        self.key_timer=QTimer(self); self.key_timer.timeout.connect(self._poll_hotkeys); self.key_timer.start(90)

    def _fetch_cfg(self):
        try:
            payload=http_json(f"{LOCAL_BASE}/api/floating-chat-config",timeout=.6)
            return payload.get("config",{}) if isinstance(payload,dict) else {}
        except Exception: return {}

    def _saved_window_size(self):
        try:
            w=int(self.position_settings.value("floatingChatWidth",0) or 0)
            h=int(self.position_settings.value("floatingChatHeight",0) or 0)
            if w>=280 and h>=260: return (w,h)
        except Exception:
            pass
        return None

    def _apply_window_size(self, width, height, remember=True):
        width=max(280,min(1800,int(width))); height=max(260,min(1400,int(height)))
        self._applying_config_geometry=True
        try:
            self.resize(width,height)
            if remember:
                self.position_settings.setValue("floatingChatWidth",width)
                self.position_settings.setValue("floatingChatHeight",height)
        finally:
            self._applying_config_geometry=False

    def _load_config(self, first=False):
        cfg=self._fetch_cfg()
        if not cfg: return
        stamp=str(cfg.get("updatedAt") or "")
        if not first and stamp==self._last_cfg_stamp: return
        configured_size=(int(cfg.get("width",520)),int(cfg.get("height",720)))
        previous_configured_size=self._last_configured_size
        self._last_cfg_stamp=stamp; self._last_configured_size=configured_size; self.cfg=cfg
        if first:
            saved_size=self._saved_window_size()
            self._apply_window_size(*(saved_size or configured_size),remember=True)
            self.click_through=bool(cfg.get("startClickThrough",False))
        elif previous_configured_size is not None and configured_size != previous_configured_size:
            # Sólo un cambio explícito Ancho/Alto desde el panel debe volver a
            # dimensionar la ventana. Cambiar opacidad, zoom, etc. no pisa el
            # tamaño ajustado manualmente con QSizeGrip.
            self._apply_window_size(*configured_size,remember=True)
        self.setWindowOpacity(max(.15,min(1.0,float(cfg.get("windowOpacity",100))/100.0)))
        self.web.setZoomFactor(max(.6,min(1.8,float(cfg.get("zoom",100))/100.0)))
        self._set_always_on_top(bool(cfg.get("alwaysOnTop",True)))
        self.set_click_through(self.click_through, announce=False)

    def _set_always_on_top(self, enabled):
        geo=self.geometry(); visible=self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible: self.show(); self.setGeometry(geo)

    def set_click_through(self, enabled, announce=True):
        enabled=bool(enabled); geo=self.geometry(); visible=self.isVisible(); self.click_through=enabled
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if hasattr(self,"drag_bar"): self.drag_bar.setVisible(not enabled)
        if hasattr(self,"grip"): self.grip.setVisible(not enabled)
        if visible: self.show(); self.setGeometry(geo)
        try: self.web.page().runJavaScript(f"window.BRYNN_SET_CLICKTHROUGH && window.BRYNN_SET_CLICKTHROUGH({str(enabled).lower()});")
        except Exception: pass
        if announce and getattr(self.owner,'footer_message',None): self.owner.footer_message.setText("CHAT FLOTANTE · CLICK-THROUGH " + ("ON" if enabled else "OFF"))

    def toggle_click_through(self): self.set_click_through(not self.click_through)
    def toggle_visible(self):
        if self.isVisible(): self.hide()
        else: self.show(); self.raise_()
    def adjust_opacity(self, delta): self.setWindowOpacity(max(.15,min(1.0,self.windowOpacity()+delta)))
    def focus_composer(self):
        if self.click_through: self.set_click_through(False)
        self.show(); self.raise_(); self.activateWindow(); self.web.setFocus()
        self.web.page().runJavaScript("window.BRYNN_FOCUS_INPUT && window.BRYNN_FOCUS_INPUT();")

    @staticmethod
    def _vk(token):
        token=token.strip().upper(); aliases={'CTRL':0x11,'CONTROL':0x11,'ALT':0x12,'SHIFT':0x10,'WIN':0x5B,'ENTER':0x0D,'SPACE':0x20,'UP':0x26,'DOWN':0x28,'LEFT':0x25,'RIGHT':0x27,'ESC':0x1B,'ESCAPE':0x1B,'TAB':0x09}
        if token in aliases: return aliases[token]
        if re.fullmatch(r'F(?:[1-9]|1[0-2])',token): return 0x70+int(token[1:])-1
        if len(token)==1 and token.isalnum(): return ord(token)
        return None

    def _combo_pressed(self, spec):
        if os.name!='nt' or not spec: return False
        try:
            import ctypes
            keys=[self._vk(x) for x in str(spec).split('+')]; keys=[k for k in keys if k is not None]
            return bool(keys) and all(ctypes.windll.user32.GetAsyncKeyState(k)&0x8000 for k in keys)
        except Exception: return False

    def _poll_hotkeys(self):
        actions={'toggleClickThrough':self.toggle_click_through,'toggleVisible':self.toggle_visible,'opacityUp':lambda:self.adjust_opacity(.08),'opacityDown':lambda:self.adjust_opacity(-.08),'focusComposer':self.focus_composer}
        hot=(self.cfg or {}).get('hotkeys',{})
        for name,fn in actions.items():
            down=self._combo_pressed(hot.get(name,'')); was=self._hotkey_down.get(name,False)
            if down and not was:
                try: fn()
                except Exception: pass
            self._hotkey_down[name]=down

    def moveEvent(self,event):
        try:
            if hasattr(self,"position_settings"): self.position_settings.setValue("floatingChatPos",self.pos())
        except Exception:
            pass
        super().moveEvent(event)

    def resizeEvent(self,event):
        try:
            if hasattr(self,"position_settings") and not self._applying_config_geometry:
                self.position_settings.setValue("floatingChatWidth",self.width())
                self.position_settings.setValue("floatingChatHeight",self.height())
        except Exception:
            pass
        super().resizeEvent(event)

    def closeEvent(self,event):
        event.ignore(); self.hide()



class FirstRunWizard(QDialog):
    """Asistente limpio para instalaciones comerciales nuevas."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a Brynn Interactive")
        self.setModal(True)
        self.resize(780, 610)
        self.setMinimumSize(700, 560)
        self.setStyleSheet("""
            QDialog { background:#0b0e14; color:#f2ead8; font-family:'Segoe UI'; }
            QLabel#hero { font-size:28px; font-weight:900; color:#ffffff; }
            QLabel#sub { color:#9fb2c8; font-size:13px; }
            QFrame#card { background:#111827; border:1px solid #26364d; border-radius:14px; }
            QLabel#section { font-size:16px; font-weight:800; color:#67e8f9; }
            QLineEdit { background:#090d14; color:#fff; border:1px solid #334155; border-radius:9px; padding:9px 11px; min-height:24px; }
            QLineEdit:focus { border-color:#67e8f9; }
            QCheckBox { spacing:8px; }
            QPushButton { background:#162033; color:#fff; border:1px solid #334155; border-radius:9px; padding:9px 16px; font-weight:700; }
            QPushButton:hover { border-color:#67e8f9; }
            QPushButton#primary { background:#0e7490; border-color:#22d3ee; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(14)
        hero = QLabel("Configura tu espacio")
        hero.setObjectName("hero")
        root.addWidget(hero)
        sub = QLabel(
            "Esta instalación empieza limpia. Tus cuentas, tokens, ranking, emotes y configuraciones "
            "se guardarán únicamente en este equipo. Puedes omitir cualquier integración y configurarla después."
        )
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        card = QFrame(); card.setObjectName("card")
        box = QVBoxLayout(card); box.setContentsMargins(20,18,20,20); box.setSpacing(12)
        section = QLabel("1 · Identidad del canal"); section.setObjectName("section"); box.addWidget(section)
        self.streamer = QLineEdit(); self.streamer.setPlaceholderText("Nombre visible del canal / streamer")
        self.owner_twitch = QLineEdit(); self.owner_twitch.setPlaceholderText("Usuario de Twitch (opcional)")
        self.owner_tiktok = QLineEdit(); self.owner_tiktok.setPlaceholderText("Usuario de TikTok (opcional)")
        self.owner_kick = QLineEdit(); self.owner_kick.setPlaceholderText("Usuario de Kick (opcional)")
        box.addWidget(self.streamer); box.addWidget(self.owner_twitch); box.addWidget(self.owner_tiktok); box.addWidget(self.owner_kick)
        root.addWidget(card)

        social = QFrame(); social.setObjectName("card")
        sv = QVBoxLayout(social); sv.setContentsMargins(20,18,20,20); sv.setSpacing(12)
        section2 = QLabel("2 · Social Stream Ninja · chat Twitch + TikTok"); section2.setObjectName("section"); sv.addWidget(section2)
        info = QLabel("Esta edición conserva el transporte estable de Social Stream Ninja para Twitch + TikTok, comandos y envío desde el chat de Brynn. Puedes configurar la sesión ahora o después desde Chat flotante.")
        info.setObjectName("sub"); info.setWordWrap(True); sv.addWidget(info)
        self.session = QLineEdit(); self.session.setPlaceholderText("Session ID de Social Stream Ninja")
        self.password = QLineEdit(); self.password.setText("false"); self.password.setPlaceholderText("false")
        sv.addWidget(QLabel("Session ID")); sv.addWidget(self.session)
        sv.addWidget(QLabel("Room password (normalmente false)")); sv.addWidget(self.password)
        ssn_note = QLabel("Brynn conserva el puente de Social Stream Ninja de la V0.53.3: P2P/Channel 4 para recibir y sendChat para publicar. Para enviar desde Brynn activa Remote API control en Social Stream Ninja.")
        ssn_note.setObjectName("sub"); ssn_note.setWordWrap(True); sv.addWidget(ssn_note)
        root.addWidget(social)

        self.developer = QCheckBox("Activar modo Developer (muestra diagnóstico, monitor y herramientas de prueba)")
        self.developer.setChecked(False)
        root.addWidget(self.developer)
        root.addStretch(1)

        actions = QHBoxLayout(); actions.addStretch(1)
        cancel = QPushButton("Salir"); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        start = QPushButton("Comenzar"); start.setObjectName("primary"); start.clicked.connect(self._finish); actions.addWidget(start)
        root.addLayout(actions)

    def _finish(self):
        profile = default_profile()
        profile.update({
            "setupComplete": True,
            "streamerName": self.streamer.text().strip() or "Mi canal",
            "owners": {
                "twitch": self.owner_twitch.text().strip().lstrip("@"),
                "tiktok": self.owner_tiktok.text().strip().lstrip("@"),
                "kick": self.owner_kick.text().strip().lstrip("@"),
            },
            "developerMode": self.developer.isChecked(),
        })
        save_profile(profile)
        _write_setup_state(True)
        save_json_file(DATA_DIR / "social_stream.json", {
            "sessionId": self.session.text().strip(),
            "password": self.password.text().strip() or "false",
        })
        self.accept()


class UpdateInstallSignals(QObject):
    progress = Signal(int, str)
    log = Signal(str)
    finished = Signal(bool, str, str)


class IntegratedUpdateDialog(QDialog):
    """Actualizador integrado y personalizable; nunca abre una consola visible."""
    def __init__(self, parent=None, config: dict | None = None):
        super().__init__(parent)
        self.config=dict(config or {})
        palette={}
        try:
            if parent and hasattr(parent,"_native_palette"):
                palette=parent._native_palette(theme=str(self.config.get("theme") or parent.current_theme),accent=str(self.config.get("accent") or ""),accent2=str(self.config.get("accent2") or ""))
        except Exception: palette={}
        preset=str(self.config.get("updateStylePreset") or "match")
        self.profile=visual_style_profile(preset,palette)
        title_text=str(self.config.get("updateTitle") or "Actualizando Brynn Interactive")
        self.setWindowTitle(title_text)
        self.setModal(True); self.resize(760,460)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        root=QVBoxLayout(self); root.setContentsMargins(26,24,26,22); root.setSpacing(12)
        hero=QHBoxLayout(); hero.setSpacing(12)
        mark=QLabel(); mark.setAlignment(Qt.AlignmentFlag.AlignCenter); mark.setFixedSize(52,52); mark.setStyleSheet("background:transparent;border:0;")
        if bool(self.config.get("updateShowLogo",True)) and resource_path("brynn_default.png").exists():
            pix=QPixmap(str(resource_path("brynn_default.png"))); mark.setPixmap(pix.scaled(48,48,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:
            mark.setText("◇"); mark.setStyleSheet(f"color:{self.profile['accent']};font-size:26px;font-weight:900;background:transparent;")
        hero.addWidget(mark)
        htext=QVBoxLayout(); htext.setSpacing(2)
        title=QLabel(title_text); title.setObjectName("updateDialogTitle"); htext.addWidget(title)
        subtitle=QLabel("Tus datos de AppData se conservan y Brynn crea un backup antes de reemplazar archivos."); subtitle.setWordWrap(True); subtitle.setObjectName("updateDialogSubtitle"); htext.addWidget(subtitle)
        hero.addLayout(htext,1)
        media_path=Path(str(self.config.get("updateMediaPath") or "")) if self.config.get("updateMediaPath") else None
        self.update_media=QLabel(); self.update_media.setAlignment(Qt.AlignmentFlag.AlignCenter); self.update_media.setFixedSize(104,58); self.update_media.hide()
        self.update_movie=None
        if media_path and media_path.exists():
            if media_path.suffix.lower()==".gif":
                self.update_movie=QMovie(str(media_path)); self.update_movie.setScaledSize(QSize(100,54)); self.update_media.setMovie(self.update_movie); self.update_movie.start()
            else:
                pix=QPixmap(str(media_path));
                if not pix.isNull(): self.update_media.setPixmap(pix.scaled(100,54,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            self.update_media.show(); hero.addWidget(self.update_media)
        root.addLayout(hero)
        self.status=QLabel("Preparando actualización…"); self.status.setWordWrap(True); self.status.setObjectName("updateStatus"); root.addWidget(self.status)
        self.bar=QProgressBar(); self.bar.setRange(0,100); self.bar.setValue(2); self.bar.setTextVisible(True); root.addWidget(self.bar)
        self.detail_btn=QPushButton("Mostrar detalles técnicos"); self.detail_btn.setCheckable(True); self.detail_btn.toggled.connect(self._toggle_details); root.addWidget(self.detail_btn,0,Qt.AlignmentFlag.AlignLeft)
        self.log_box=QPlainTextEdit(); self.log_box.setReadOnly(True); self.log_box.setPlaceholderText("El progreso técnico aparecerá aquí sin abrir CMD o PowerShell visible."); root.addWidget(self.log_box,1)
        show_log=bool(self.config.get("updateShowTechnicalLog",False)); self.detail_btn.setChecked(show_log); self.log_box.setVisible(show_log)
        self.close_btn=QPushButton("Trabajando…"); self.close_btn.setEnabled(False); self.close_btn.clicked.connect(self.accept); root.addWidget(self.close_btn)
        self._apply_theme()

    def _apply_theme(self):
        p=self.profile; radius=int(p.get("radius",16))
        custom_bg=normalize_hex_color(self.config.get("updateBackground")) or p["bg"]
        self.setStyleSheet(f"""
            QDialog{{background:{custom_bg};color:{p['text']};}}
            QLabel#updateDialogTitle{{color:{p['text']};font-size:24px;font-weight:900;background:transparent;}}
            QLabel#updateDialogSubtitle{{color:{p['muted']};font-size:11px;background:transparent;}}
            QLabel#updateStatus{{color:{p['text']};font-size:13px;font-weight:650;background:{p['panel']};border:1px solid {p['border']}55;border-radius:{max(5,radius-7)}px;padding:10px 12px;}}
            QPlainTextEdit{{background:{p['panel']};color:{p['muted']};border:1px solid {p['border']}44;border-radius:{max(5,radius-7)}px;padding:8px;}}
            QPushButton{{background:{p['panel']};color:{p['text']};border:1px solid {p['border']}55;border-radius:{max(5,radius-8)}px;padding:9px 14px;font-weight:700;}}
            QPushButton:hover{{border-color:{p['accent']};}}
        """ + progress_style_sheet(str(self.config.get("updateProgressStyle") or "neon"),p))

    def _toggle_details(self,visible:bool):
        self.log_box.setVisible(bool(visible)); self.detail_btn.setText("Ocultar detalles técnicos" if visible else "Mostrar detalles técnicos")
        if not visible: self.resize(max(620,self.width()),310)

    def append_log(self,text):
        text=str(text or '').strip()
        if text: self.log_box.appendPlainText(text)

    def set_progress(self,value,text):
        self.bar.setValue(max(0,min(100,int(value)))); self.status.setText(str(text or "Actualizando…"))

    def complete(self,ok:bool,message:str):
        self.bar.setValue(100 if ok else self.bar.value()); self.status.setText(message); self.close_btn.setText("Continuar" if ok else "Cerrar"); self.close_btn.setEnabled(True)

    def closeEvent(self,event):
        try:
            if getattr(self,"update_movie",None): self.update_movie.stop()
        except Exception: pass
        super().closeEvent(event)


class BrynnDesktop(QMainWindow):
    def __init__(self, backend: BackendController):
        super().__init__()
        self.backend = backend
        self.settings = QSettings("BrynnInteractive", "BrynnInteractiveDesktop")
        self.profile = load_profile()
        self.appearance = load_appearance()
        self.current_theme = str(self.appearance.get("theme") or "neon")
        self.staged_update_dir = None
        self.staged_installer = None
        self.staged_update_kind = None
        self.force_exit = False
        self.web_view = QWebEngineView()
        self._attach_desktop_web_page(self.web_view)
        self.web_view.setZoomFactor(float(self.appearance.get("webZoom", 95)) / 100.0)
        self.web_view.page().setBackgroundColor(QColor("#0b0e14"))
        self.pending_web_view = None
        self._loading_started_at = 0.0
        self.floating_chat_window = None

        # Conserva la estética frameless, pero con hints estándar para que
        # Windows trate el botón de la barra de tareas como una ventana normal.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL}")
        self._apply_app_icon()
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)

        self._build_ui()
        self._build_tray()
        self._apply_appearance_runtime()
        self._load_settings_form()

        self.backend.state.failed.connect(self._backend_failed)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2500)
        QTimer.singleShot(800, self.refresh_status)
        self._blank_watchdog_count = 0
        self.web_watchdog_timer = QTimer(self)
        self.web_watchdog_timer.setInterval(5000)
        self.web_watchdog_timer.timeout.connect(self._web_watchdog_tick)
        self.web_watchdog_timer.start()

    def _navigation_catalog(self) -> list[dict]:
        return [
            {"label":"Inicio","route":"home","group":"home","short":"INI","icon":"home","keywords":"inicio dashboard centro control resumen estado actividad"},
            {"label":"Alertas","route":"alertas_admin.html?v=57","group":"stream","short":"ALE","icon":"alert","keywords":"alertas follow sub raid gift regalo notificaciones twitch tiktok kick"},
            {"label":"Metas","route":"goals_admin.html?v=57","group":"stream","short":"MET","icon":"target","keywords":"metas goals seguidores subs likes regalos objetivo obs"},
            {"label":"Chat flotante","route":"floating_chat_admin.html?v=57","group":"stream","short":"FLT","icon":"floating","keywords":"chat flotante overlay transparente click through viewers moderacion twitch tiktok kick nativo"},
            {"label":"Comandos","route":"comandos_admin.html?v=57","group":"interaction","short":"CMD","icon":"terminal","keywords":"comandos audio secuencias stickers timeline efectos canjes"},
            {"label":"Emotes","route":"emotes_admin.html?v=57","group":"interaction","short":"EMO","icon":"emote","keywords":"emotes stickers gif animaciones pantalla"},
            {"label":"Billeteras","route":"economia.html?v=57","group":"community","short":"BIL","icon":"wallet","keywords":"usuarios saldo puntos moneda billetera gumpitas wumpitas"},
            {"label":"Economía","route":"economia_config.html?v=57","group":"community","short":"ECO","icon":"coin","keywords":"economia moneda puntos tienda costes canjes html css js"},
            {"label":"Ranking","route":"ranking.html?v=57","group":"community","short":"RAN","icon":"ranking","keywords":"ranking semanal usuarios buscar top puntos"},
            {"label":"Recompensas","route":"weekly_rewards_admin.html?v=57","group":"community","short":"REC","icon":"trophy","keywords":"recompensas semanal top1 top2 top3 top10 insignias hall fame"},
            {"label":"Chat","route":"chat_admin.html?v=57","group":"design","short":"CHT","icon":"chat","keywords":"chat diseño html css javascript obs mensajes"},
            {"label":"Layout Studio","route":"layout_studio.html?v=57","group":"design","short":"LAY","icon":"layout","keywords":"layout studio obs overlays posiciones diseño"},
            {"label":"Personalización","route":"personalization","group":"design","short":"PER","icon":"sliders","keywords":"personalizacion apariencia tema colores interfaz loader icono"},
            {"label":"Integraciones","route":"integraciones.html?v=57","group":"integrations","short":"INT","icon":"nodes","keywords":"integraciones twitch tiktok kick streamlabs tikfinity oauth tailscale chat nativo"},
            {"label":"OBS Studio","route":"obs_admin.html?v=57","group":"integrations","short":"OBS","icon":"screen","keywords":"obs studio websocket escenas fuentes filtros audio stream grabacion control"},
            {"label":"Automatizaciones","route":"automations_admin.html?v=57","group":"integrations","short":"AUT","icon":"flow","keywords":"automatizaciones automation engine flujos acciones triggers obs twitch tiktok kick chat"},
            {"label":"Novedades","route":"updates.html?v=57","group":"system","short":"NUE","icon":"document","keywords":"novedades changelog cambios version"},
            {"label":"Actualizaciones","route":"updates-native","group":"system","short":"ACT","icon":"update","keywords":"actualizaciones update zip exe instalar versiones"},
            {"label":"Datos y privacidad","route":"privacy","group":"system","short":"DAT","icon":"shield","keywords":"datos privacidad backup exportar importar restablecer"},
            {"label":"Ajustes Desktop","route":"settings","group":"system","short":"AJU","icon":"settings","keywords":"ajustes desktop propietario chat nativo social stream ninja inicio windows developer"},
            {"label":"Monitor","route":"eventos_monitor.html?v=57","group":"developer","short":"MON","icon":"monitor","keywords":"monitor eventos debug social stream tikfinity twitch chat" ,"developer":True},
            {"label":"Pruebas","route":"pruebas_efectos.html?v=57","group":"developer","short":"PRU","icon":"flask","keywords":"pruebas efectos test overlay obs","developer":True},
            {"label":"Diagnóstico","route":"diagnostico_admin.html?v=57","group":"developer","short":"DIA","icon":"diagnostic","keywords":"diagnostico logs estado errores api","developer":True},
        ]

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("windowRoot")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("bodyRoot")
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 14, 12, 12)
        side.setSpacing(8)

        brand_text = str(self.appearance.get("brand") or "BRYNN\\nINTERACTIVE").replace("\\n", "\n")
        self.brand_label = QLabel(brand_text)
        self.brand_label.setObjectName("brand")
        side.addWidget(self.brand_label)

        self.version_label = QLabel(f"Desktop Beta · {APP_VERSION_LABEL}")
        self.version_label.setObjectName("version")
        side.addWidget(self.version_label)

        # V0.51: navegación + Automation Engine + control directo de OBS.
        self.nav_state = load_navigation_state()
        self._route_catalog = self._navigation_catalog()
        self._route_labels = {row["route"]: row["label"] for row in self._route_catalog}
        self._route_categories = {row["route"]: row["group"] for row in self._route_catalog}
        self._route_entries = {row["route"]: row for row in self._route_catalog}
        self._nav_buttons = {}
        self._nav_button_instances = {}
        self._special_nav_buttons = []
        self._nav_groups = {}
        self._nav_group_headers = {}
        self._nav_group_layouts = {}

        # Buscador siempre arriba. Los controles grandes del pie se sustituyen
        # por acciones compactas para que la navegación se sienta como una app
        # de escritorio profesional.
        nav_tools = QHBoxLayout()
        nav_tools.setContentsMargins(0, 0, 0, 0)
        nav_tools.setSpacing(6)
        self.nav_search = QLineEdit()
        self.nav_search.setObjectName("navSearch")
        self.nav_search.setPlaceholderText("Buscar en Brynn…  Ctrl+K")
        self.nav_search.setClearButtonEnabled(True)
        self.nav_search.textChanged.connect(self._apply_nav_filter)
        nav_tools.addWidget(self.nav_search, 1)
        self.nav_palette_button = QPushButton()
        self.nav_palette_button.setObjectName("navTopIconButton")
        self.nav_palette_button.setIcon(self._nav_icon("search"))
        self.nav_palette_button.setIconSize(QSize(18,18))
        self.nav_palette_button.setToolTip("Buscador global · Ctrl+K")
        self.nav_palette_button.clicked.connect(self._open_command_palette)
        nav_tools.addWidget(self.nav_palette_button)
        self.nav_compact_button = QPushButton()
        self.nav_compact_button.setObjectName("navTopIconButton")
        self.nav_compact_button.setIcon(self._nav_icon("collapse"))
        self.nav_compact_button.setIconSize(QSize(18,18))
        self.nav_compact_button.setToolTip("Compactar menú lateral")
        self.nav_compact_button.clicked.connect(self._toggle_sidebar_compact)
        nav_tools.addWidget(self.nav_compact_button)
        side.addLayout(nav_tools)

        self.nav_scroll = QScrollArea()
        self.nav_scroll.setObjectName("navScroll")
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.nav_container = QWidget()
        self.nav_container.setObjectName("navContainer")
        self.nav_layout = QVBoxLayout(self.nav_container)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(5)

        # Inicio permanece siempre accesible arriba.
        home_entry = self._route_entries["home"]
        home_button = self._create_nav_button(home_entry, primary=True)
        self.nav_layout.addWidget(home_button)

        self._create_nav_group("favorites", "FAVORITOS", [], special=True)
        self._create_nav_group("recent", "RECIENTES", [], special=True)

        groups = [
            ("stream", "STREAM"),
            ("interaction", "INTERACCIÓN"),
            ("community", "COMUNIDAD"),
            ("design", "DISEÑO"),
            ("integrations", "INTEGRACIONES"),
            ("system", "SISTEMA"),
            ("developer", "DEVELOPER"),
        ]
        for group_key, group_label in groups:
            rows = [r for r in self._route_catalog if r.get("group") == group_key]
            self._create_nav_group(group_key, group_label, rows)

        self.nav_layout.addStretch(1)
        self.nav_scroll.setWidget(self.nav_container)
        side.addWidget(self.nav_scroll, 1)

        self._refresh_special_nav_groups()
        self._apply_sidebar_mode()
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.home = self._make_home()
        self.desktop_settings = self._make_settings()
        self.update_manager = self._make_update_manager()
        self.personalization = self._make_personalization()
        self.privacy_page = self._make_privacy_page()

        # V0.40+: host con doble WebView para cambiar de módulo sin flash blanco.
        self.web_host = QWidget()
        self.web_host.setObjectName("webHost")
        self.web_host_layout = QStackedLayout(self.web_host)
        self.web_host_layout.setContentsMargins(0, 0, 0, 0)
        self.web_host_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.web_stack = QStackedWidget()
        self.web_stack.setObjectName("webStack")
        self.web_stack.addWidget(self.web_view)
        self.web_host_layout.addWidget(self.web_stack)
        self.loading_overlay = LoadingOverlay()
        self.web_host_layout.addWidget(self.loading_overlay)

        self.stack.addWidget(self.home)
        self.stack.addWidget(self.web_host)
        self.stack.addWidget(self.desktop_settings)
        self.stack.addWidget(self.update_manager)
        self.stack.addWidget(self.personalization)
        self.stack.addWidget(self.privacy_page)

        # Barra contextual: breadcrumb + acceso rápido al buscador global.
        self.content_shell = QWidget()
        self.content_shell.setObjectName("contentShell")
        content_layout = QVBoxLayout(self.content_shell)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.context_bar = QFrame()
        self.context_bar.setObjectName("contextBar")
        context_layout = QHBoxLayout(self.context_bar)
        context_layout.setContentsMargins(18, 7, 14, 7)
        context_layout.setSpacing(10)
        self.breadcrumb_label = QLabel("Inicio")
        self.breadcrumb_label.setObjectName("breadcrumb")
        context_layout.addWidget(self.breadcrumb_label)
        context_layout.addStretch(1)
        context_search = QPushButton("Buscar · Ctrl+K")
        context_search.setObjectName("contextSearchButton")
        context_search.clicked.connect(self._open_command_palette)
        context_layout.addWidget(context_search)
        content_layout.addWidget(self.context_bar)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(self.content_shell, 1)
        outer.addWidget(body, 1)

        self.footer = QFrame()
        self.footer.setObjectName("statusFooter")
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(14, 4, 8, 4)
        footer_layout.setSpacing(14)
        self.footer_server = QLabel("● SERVER · ...")
        self.footer_streamlabs = QLabel("● STREAMLABS · ...")
        self.footer_tiktok = QLabel("● TIKFINITY · ...")
        self.footer_tailscale = QLabel("● TAILSCALE · ...")
        for label in (self.footer_server, self.footer_streamlabs, self.footer_tiktok, self.footer_tailscale):
            label.setObjectName("footerItem")
            footer_layout.addWidget(label)
        footer_layout.addStretch(1)
        self.footer_message = QLabel(APP_VERSION_LABEL)
        self.footer_message.setObjectName("footerVersion")
        footer_layout.addWidget(self.footer_message)
        outer.addWidget(self.footer)

        self.setCentralWidget(central)
        self.corner_grip = QSizeGrip(self)
        self.corner_grip.setObjectName("cornerGrip")
        self.corner_grip.setFixedSize(18, 18)
        self.corner_grip.move(max(0, self.width() - 18), max(0, self.height() - 18))
        self.corner_grip.raise_()
        self.statusBar().hide()

        # Paleta global Ctrl+K.
        self.command_palette_action = QAction(self)
        self.command_palette_action.setShortcut("Ctrl+K")
        self.command_palette_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.command_palette_action.triggered.connect(self._open_command_palette)
        self.addAction(self.command_palette_action)

        self._active_route = None
        self._nav_serial = 0
        self._requested_web_path = None
        self._requested_web_key = None
        self._pending_web_retry = 0
        self.web_view.urlChanged.connect(self._sync_nav_from_web_url)

        self._apply_developer_mode_visibility()
        self._select_nav_key("home")
        self._activate_route("home", force=True)

    def _nav_icon(self, name: str) -> QIcon:
        """Iconos vectoriales dibujados por Qt: sin emojis ni fuentes externas."""
        size = 22
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            color = QColor(self._native_palette().get("accent2", "#53e6ff"))
        except Exception:
            color = QColor("#53e6ff")
        pen = QPen(color)
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        n = str(name or "dot")
        L = lambda x1,y1,x2,y2: painter.drawLine(int(x1),int(y1),int(x2),int(y2))
        R = lambda x,y,w,h,r=0: painter.drawRoundedRect(QRectF(x,y,w,h),r,r) if r else painter.drawRect(QRectF(x,y,w,h))
        E = lambda x,y,w,h: painter.drawEllipse(QRectF(x,y,w,h))
        if n == "home":
            L(3,10,11,3); L(11,3,19,10); R(5,9,12,9,2); R(9,13,4,5,1)
        elif n == "alert":
            painter.drawArc(QRectF(5,4,12,12), 20*16, 140*16); L(5,10,5,14); L(17,10,17,14); L(5,14,17,14); E(10,16,2,2)
        elif n == "target":
            E(3,3,16,16); E(7,7,8,8); E(10,10,2,2)
        elif n == "floating":
            R(3,4,16,12,3); L(7,16,5,19); L(7,16,10,16); L(6,8,16,8); L(6,11,13,11)
        elif n == "terminal":
            R(3,4,16,14,3); L(6,8,9,11); L(9,11,6,14); L(11,14,16,14)
        elif n == "emote":
            E(3,3,16,16); E(7,8,1.5,1.5); E(13.5,8,1.5,1.5); painter.drawArc(QRectF(7,9,8,6), 200*16, 140*16)
        elif n == "wallet":
            R(3,6,16,11,3); L(5,6,7,3); L(7,3,17,6); R(13,9,6,5,2); E(15.5,10.5,1,1)
        elif n == "coin":
            E(4,3,14,16); E(7,6,8,10); L(11,7,11,15); L(9,9,13,9); L(9,13,13,13)
        elif n == "ranking":
            R(4,12,3,6,1); R(9,8,3,10,1); R(14,4,3,14,1)
        elif n == "trophy":
            painter.drawArc(QRectF(6,4,10,9), 180*16, 180*16); L(6,5,3,5); L(3,5,3,9); L(3,9,7,11); L(16,5,19,5); L(19,5,19,9); L(19,9,15,11); L(11,13,11,17); L(7,18,15,18)
        elif n == "chat":
            R(3,4,16,12,4); L(7,16,5,19); L(7,16,10,16); L(6,9,16,9); L(6,12,13,12)
        elif n == "layout":
            R(3,3,7,7,1); R(12,3,7,7,1); R(3,12,7,7,1); R(12,12,7,7,1)
        elif n == "sliders":
            L(4,6,18,6); E(8,4,4,4); L(4,11,18,11); E(13,9,4,4); L(4,16,18,16); E(6,14,4,4)
        elif n == "nodes":
            E(3,9,4,4); E(15,4,4,4); E(15,14,4,4); L(7,11,15,6); L(7,11,15,16)
        elif n == "screen":
            R(3,4,16,12,2); L(8,19,14,19); L(11,16,11,19); L(9,8,14,11); L(14,11,9,14); L(9,14,9,8)
        elif n == "flow":
            E(3,3,5,5); E(14,8.5,5,5); E(3,14,5,5); L(8,5,12,5); L(12,5,12,11); L(12,11,14,11); L(8,16,12,16); L(12,16,12,12)
        elif n == "document":
            R(5,3,12,16,2); L(8,8,14,8); L(8,11,14,11); L(8,14,12,14)
        elif n == "update":
            painter.drawArc(QRectF(4,4,14,14), 30*16, 280*16); L(16,4,18,8); L(16,4,12,5)
        elif n == "shield":
            L(11,3,18,6); L(18,6,17,13); L(17,13,11,19); L(11,19,5,13); L(5,13,4,6); L(4,6,11,3); L(8,11,10,13); L(10,13,15,8)
        elif n == "settings":
            E(7,7,8,8); E(10,10,2,2); L(11,3,11,6); L(11,16,11,19); L(3,11,6,11); L(16,11,19,11); L(5,5,7,7); L(15,15,17,17); L(17,5,15,7); L(5,17,7,15)
        elif n == "monitor":
            R(3,4,16,12,2); L(5,11,8,11); L(8,11,10,7); L(10,7,12,14); L(12,14,14,10); L(14,10,17,10); L(8,19,14,19); L(11,16,11,19)
        elif n == "flask":
            L(8,3,14,3); L(10,3,10,9); L(10,9,5,17); L(5,17,17,17); L(17,17,12,9); L(12,9,12,3); L(8,13,14,13)
        elif n == "diagnostic":
            E(3,3,16,16); L(5,11,8,11); L(8,11,10,7); L(10,7,12,15); L(12,15,14,10); L(14,10,17,10)
        elif n == "search":
            E(4,4,11,11); L(13,13,19,19)
        elif n == "collapse":
            L(7,5,12,11); L(12,11,7,17); L(14,5,14,17)
        elif n == "expand":
            L(15,5,10,11); L(10,11,15,17); L(8,5,8,17)
        else:
            E(8,8,6,6)
        painter.end()
        return QIcon(pix)

    def _create_nav_button(self, entry: dict, primary: bool = False) -> QPushButton:
        route = str(entry.get("route") or "")
        label = str(entry.get("label") or route)
        button = QPushButton(label)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setAutoExclusive(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("routeKey", route)
        button.setProperty("fullLabel", label)
        button.setProperty("shortLabel", str(entry.get("short") or label[:3]).upper())
        button.setProperty("groupKey", str(entry.get("group") or ""))
        button.setToolTip(label)
        button.setIcon(self._nav_icon(str(entry.get("icon") or "dot")))
        button.setIconSize(QSize(18, 18))
        button.clicked.connect(lambda checked=False, key=route: self._activate_route(key, force=False))
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(lambda pos, key=route, b=button: self._show_nav_context_menu(key, b, pos))
        self._nav_button_instances.setdefault(route, []).append(button)
        if primary:
            self._nav_buttons[route] = button
        return button

    def _create_nav_group(self, key: str, label: str, entries: list[dict], special: bool = False):
        frame = QFrame()
        frame.setObjectName("navGroup")
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        header = QPushButton(label)
        header.setObjectName("navGroupHeader")
        header.setCheckable(True)
        expanded = bool(self.nav_state.get("expanded", {}).get(key, True))
        header.setChecked(expanded)
        header.toggled.connect(lambda on, group=key: self._set_nav_group_expanded(group, on))
        box.addWidget(header)
        body = QWidget()
        body.setObjectName("navGroupBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(5, 0, 0, 0)
        body_layout.setSpacing(3)
        for entry in entries:
            btn = self._create_nav_button(entry, primary=True)
            body_layout.addWidget(btn)
        box.addWidget(body)
        self.nav_layout.addWidget(frame)
        self._nav_groups[key] = frame
        self._nav_group_headers[key] = header
        self._nav_group_layouts[key] = body_layout
        body.setProperty("groupKey", key)
        body.setVisible(expanded)
        if special:
            frame.setVisible(False)

    def _set_nav_group_expanded(self, key: str, expanded: bool):
        state = self.nav_state.setdefault("expanded", {})
        state[key] = bool(expanded)
        self.nav_state = save_navigation_state(self.nav_state)
        frame = self._nav_groups.get(key)
        if frame:
            body = frame.findChild(QWidget, "navGroupBody")
            if body and not self.nav_state.get("compact", False):
                body.setVisible(bool(expanded))

    def _show_nav_context_menu(self, route: str, button: QPushButton, pos):
        if route == "home":
            return
        menu = QMenu(button)
        favorites = list(self.nav_state.get("favorites", []))
        if route in favorites:
            action = menu.addAction("Quitar de favoritos")
            action.triggered.connect(lambda: self._toggle_favorite(route, False))
        else:
            action = menu.addAction("Fijar en favoritos")
            action.triggered.connect(lambda: self._toggle_favorite(route, True))
        menu.addSeparator()
        open_action = menu.addAction("Abrir")
        open_action.triggered.connect(lambda: self._activate_route(route, force=True))
        menu.exec(button.mapToGlobal(pos))

    def _toggle_favorite(self, route: str, enabled: bool):
        favorites = [str(x) for x in self.nav_state.get("favorites", []) if x]
        favorites = [x for x in favorites if x != route]
        if enabled and route in self._route_entries:
            favorites.insert(0, route)
        self.nav_state["favorites"] = favorites[:12]
        self.nav_state = save_navigation_state(self.nav_state)
        self._refresh_special_nav_groups()
        self._set_nav_checked(getattr(self, "_active_route", None))
        self._apply_nav_filter(self.nav_search.text() if hasattr(self, "nav_search") else "")

    def _clear_special_buttons(self):
        for button in list(getattr(self, "_special_nav_buttons", [])):
            route = str(button.property("routeKey") or "")
            instances = self._nav_button_instances.get(route, [])
            self._nav_button_instances[route] = [b for b in instances if b is not button]
            button.setParent(None)
            button.deleteLater()
        self._special_nav_buttons = []
        for key in ("favorites", "recent"):
            layout = self._nav_group_layouts.get(key)
            if not layout:
                continue
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()

    def _refresh_special_nav_groups(self):
        if not hasattr(self, "_nav_group_layouts"):
            return
        self._clear_special_buttons()
        for group_key, routes in (
            ("favorites", list(self.nav_state.get("favorites", []))),
            ("recent", list(self.nav_state.get("recent", []))),
        ):
            layout = self._nav_group_layouts.get(group_key)
            frame = self._nav_groups.get(group_key)
            valid = []
            for route in routes:
                entry = self._route_entries.get(route)
                if not entry:
                    continue
                if entry.get("developer") and not bool(load_profile().get("developerMode", False)):
                    continue
                btn = self._create_nav_button(entry, primary=False)
                self._special_nav_buttons.append(btn)
                layout.addWidget(btn)
                valid.append(route)
            if frame:
                frame.setVisible(bool(valid) and not bool(self.nav_state.get("compact", False)))

    def _record_recent_route(self, route: str):
        if route == "home" or route not in self._route_entries:
            return
        recent = [str(x) for x in self.nav_state.get("recent", []) if x and x != route]
        recent.insert(0, route)
        self.nav_state["recent"] = recent[:6]
        self.nav_state = save_navigation_state(self.nav_state)
        self._refresh_special_nav_groups()
        self._set_nav_checked(route)

    def _apply_nav_filter(self, text: str = ""):
        query = " ".join(str(text or "").lower().strip().split())
        dev_enabled = bool(load_profile().get("developerMode", False))
        compact = bool(self.nav_state.get("compact", False))

        for group_key, frame in getattr(self, "_nav_groups", {}).items():
            if group_key in {"favorites", "recent"}:
                if compact:
                    frame.setVisible(False)
                    continue
                buttons = [self._nav_group_layouts[group_key].itemAt(i).widget() for i in range(self._nav_group_layouts[group_key].count())]
                any_visible = False
                for button in buttons:
                    if not isinstance(button, QPushButton):
                        continue
                    route = str(button.property("routeKey") or "")
                    entry = self._route_entries.get(route, {})
                    hay = f"{entry.get('label','')} {entry.get('keywords','')} {group_key}".lower()
                    visible = (not query or query in hay) and (not entry.get("developer") or dev_enabled)
                    button.setVisible(visible)
                    any_visible = any_visible or visible
                frame.setVisible(any_visible)
                body = frame.findChild(QWidget, "navGroupBody")
                if body:
                    body.setVisible(True if query else bool(self.nav_state.get("expanded", {}).get(group_key, True)))
                continue

            rows = [r for r in self._route_catalog if r.get("group") == group_key]
            if group_key == "developer" and not dev_enabled:
                frame.setVisible(False)
                continue
            any_visible = False
            for entry in rows:
                button = self._nav_buttons.get(entry["route"])
                if not button:
                    continue
                hay = f"{entry.get('label','')} {entry.get('keywords','')} {group_key}".lower()
                visible = (not query or query in hay) and (not entry.get("developer") or dev_enabled)
                button.setVisible(visible)
                any_visible = any_visible or visible
            frame.setVisible(any_visible)
            header = self._nav_group_headers.get(group_key)
            body = frame.findChild(QWidget, "navGroupBody")
            if header:
                header.setVisible(not compact)
            if body:
                body.setVisible(any_visible and (compact or bool(query) or bool(self.nav_state.get("expanded", {}).get(group_key, True))))

        home = self._nav_buttons.get("home")
        if home:
            entry = self._route_entries.get("home", {})
            hay = f"{entry.get('label','')} {entry.get('keywords','')}".lower()
            home.setVisible(not query or query in hay)

    def _toggle_sidebar_compact(self):
        self.nav_state["compact"] = not bool(self.nav_state.get("compact", False))
        self.nav_state = save_navigation_state(self.nav_state)
        self._apply_sidebar_mode()

    def _apply_sidebar_mode(self):
        if not hasattr(self, "sidebar"):
            return
        compact = bool(self.nav_state.get("compact", False))
        if compact:
            self.sidebar.setFixedWidth(max(76, min(100, int(self.appearance.get("compactSidebarWidth", 84)))))
            self.brand_label.setText("◇")
            self.brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.version_label.hide()
            self.nav_search.hide()
            self.nav_palette_button.show()
            self.nav_compact_button.setIcon(self._nav_icon("expand"))
            self.nav_compact_button.setToolTip("Expandir menú lateral")
        else:
            self.sidebar.setFixedWidth(int(self.appearance.get("sidebarWidth", 250)))
            self.brand_label.setText(str(self.appearance.get("brand") or r"BRYNN\nINTERACTIVE").replace(r"\n", "\n"))
            self.brand_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.version_label.setVisible(bool(self.appearance.get("showSidebarVersion", True)))
            self.nav_search.show()
            self.nav_palette_button.show()
            self.nav_compact_button.setIcon(self._nav_icon("collapse"))
            self.nav_compact_button.setToolTip("Compactar menú lateral")

        for route, buttons in self._nav_button_instances.items():
            entry = self._route_entries.get(route, {})
            for button in buttons:
                button.setText("" if compact else str(entry.get("label") or route))
                button.setToolTip(str(entry.get("label") or route))
                button.setIconSize(QSize(22,22) if compact else QSize(18,18))
                button.setProperty("compactNav", compact)
                try:
                    button.style().unpolish(button); button.style().polish(button)
                except Exception:
                    pass
        self._refresh_special_nav_groups()
        self._apply_nav_filter(self.nav_search.text() if hasattr(self, "nav_search") else "")

    def _palette_entries(self) -> list[dict]:
        rows = []
        for entry in self._route_catalog:
            if entry.get("developer") and not bool(load_profile().get("developerMode", False)):
                continue
            rows.append({
                "label": entry["label"],
                "detail": self._group_display_name(entry.get("group")),
                "route": entry["route"],
                "search": f"{entry.get('label','')} {entry.get('keywords','')} {entry.get('group','')}",
            })
        rows.extend([
            {"label":"Crear una meta","detail":"Acción rápida","route":"goals_admin.html?v=57","search":"crear nueva meta goals"},
            {"label":"Crear un comando","detail":"Acción rápida","route":"comandos_admin.html?v=57","search":"crear nuevo comando audio secuencia"},
            {"label":"Crear un emote","detail":"Acción rápida","route":"emotes_admin.html?v=57","search":"crear nuevo emote sticker"},
            {"label":"Abrir chat flotante","detail":"Acción rápida","action":"floating-chat","search":"abrir chat flotante overlay"},
            {"label":"Copiar URLs de OBS","detail":"Acción rápida","action":"copy-obs","search":"obs urls overlays copiar"},
            {"label":"Crear backup","detail":"Acción rápida","action":"backup","search":"backup respaldo datos"},
        ])
        # Indexa entidades existentes para encontrarlas por nombre desde Ctrl+K.
        for endpoint, key, route, singular in [
            ("/api/commands", "commands", "comandos_admin.html?v=57", "Comando"),
            ("/api/emotes", "emotes", "emotes_admin.html?v=57", "Emote"),
            ("/api/goals", "goals", "goals_admin.html?v=57", "Meta"),
        ]:
            try:
                payload = http_json(f"{LOCAL_BASE}{endpoint}", timeout=0.35)
                items = payload.get(key, []) if isinstance(payload, dict) else []
                if isinstance(items, dict):
                    items = list(items.values())
                for item in list(items or [])[:80]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("title") or item.get("command") or item.get("id") or "").strip()
                    if not name:
                        continue
                    rows.append({"label":f"{singular}: {name}","detail":"Abrir editor","route":route,"search":f"{singular} {name} {item.get('description','')}"})
            except Exception:
                pass
        return rows

    def _open_command_palette(self):
        dialog = QDialog(self)
        dialog.setObjectName("commandPalette")
        dialog.setWindowTitle("Buscar en Brynn Interactive")
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title = QLabel("Buscar en Brynn Interactive")
        title.setObjectName("paletteTitle")
        layout.addWidget(title)
        search = QLineEdit()
        search.setObjectName("paletteSearch")
        search.setPlaceholderText("Escribe: alertas, !comando, meta, economía, OBS…")
        layout.addWidget(search)
        results = QListWidget()
        results.setObjectName("paletteResults")
        layout.addWidget(results, 1)
        entries = self._palette_entries()

        def refill(value=""):
            needle = " ".join(str(value or "").lower().split())
            results.clear()
            for entry in entries:
                hay = f"{entry.get('label','')} {entry.get('detail','')} {entry.get('search','')}".lower()
                if needle and needle not in hay:
                    continue
                item = QListWidgetItem(f"{entry.get('label')}   —   {entry.get('detail','')}")
                item.setData(Qt.ItemDataRole.UserRole, entry)
                results.addItem(item)
            if results.count():
                results.setCurrentRow(0)

        def activate(item=None):
            item = item or results.currentItem()
            if item is None:
                return
            entry = item.data(Qt.ItemDataRole.UserRole) or {}
            dialog.accept()
            action = entry.get("action")
            if action == "floating-chat":
                self.show_floating_chat()
            elif action == "copy-obs":
                self.copy_obs_urls()
            elif action == "backup":
                self.create_backup()
            elif entry.get("route"):
                self._activate_route(str(entry["route"]), force=True)

        search.textChanged.connect(refill)
        search.returnPressed.connect(lambda: activate())
        results.itemActivated.connect(activate)
        refill()
        search.setFocus()
        dialog.exec()

    def _group_display_name(self, key: str | None) -> str:
        return {
            "home":"Inicio", "stream":"Stream", "interaction":"Interacción", "community":"Comunidad",
            "design":"Diseño", "integrations":"Integraciones", "system":"Sistema", "developer":"Developer",
        }.get(str(key or ""), "Brynn")

    def _update_breadcrumb(self, route: str):
        if not hasattr(self, "breadcrumb_label"):
            return
        entry = self._route_entries.get(route, {})
        label = str(entry.get("label") or route)
        group = str(entry.get("group") or "")
        if route == "home":
            self.breadcrumb_label.setText("Inicio")
        else:
            self.breadcrumb_label.setText(f"{self._group_display_name(group)}  /  {label}")

    def _make_home(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("homeContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 28)
        layout.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("homeHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(16)
        hero_copy = QVBoxLayout()
        title = QLabel("Centro de control")
        title.setObjectName("pageTitle")
        hero_copy.addWidget(title)
        subtitle = QLabel(
            "Estado del directo, actividad, metas, ranking y accesos rápidos desde una sola pantalla."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        hero_copy.addWidget(subtitle)
        hero_layout.addLayout(hero_copy, 1)
        self.home_live_badge = QLabel("LISTO")
        self.home_live_badge.setObjectName("homeLiveBadge")
        hero_layout.addWidget(self.home_live_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(hero)

        quick_title = QLabel("Acciones rápidas")
        quick_title.setObjectName("sectionTitle")
        layout.addWidget(quick_title)
        quick = QGridLayout()
        quick.setHorizontalSpacing(10)
        quick.setVerticalSpacing(10)
        actions = [
            ("Nueva meta", lambda: self._activate_route("goals_admin.html?v=57", force=True)),
            ("Nuevo comando", lambda: self._activate_route("comandos_admin.html?v=57", force=True)),
            ("Nuevo emote", lambda: self._activate_route("emotes_admin.html?v=57", force=True)),
            ("Configurar alertas", lambda: self._activate_route("alertas_admin.html?v=57", force=True)),
            ("Abrir chat flotante", self.show_floating_chat),
            ("Layout Studio", lambda: self._activate_route("layout_studio.html?v=57", force=True)),
            ("Copiar URLs OBS", self.copy_obs_urls),
            ("Crear backup", self.create_backup),
        ]
        for i, (label, fn) in enumerate(actions):
            btn = QPushButton(label)
            btn.setObjectName("quickAction")
            btn.clicked.connect(fn)
            quick.addWidget(btn, i // 4, i % 4)
        layout.addLayout(quick)

        status_title = QLabel("Conexiones")
        status_title.setObjectName("sectionTitle")
        layout.addWidget(status_title)
        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.card_server = StatusCard("Servidor local")
        self.card_streamlabs = StatusCard("Twitch / Streamlabs")
        self.card_tiktok = StatusCard("TikTok / TikFinity")
        self.card_kick = StatusCard("Kick / API oficial")
        self.card_tailscale = StatusCard("Tailscale Funnel")
        cards.addWidget(self.card_server, 0, 0)
        cards.addWidget(self.card_streamlabs, 0, 1)
        cards.addWidget(self.card_tiktok, 0, 2)
        cards.addWidget(self.card_tailscale, 0, 3)
        cards.addWidget(self.card_kick, 1, 0, 1, 2)
        layout.addLayout(cards)

        live_title = QLabel("Ahora mismo")
        live_title.setObjectName("sectionTitle")
        layout.addWidget(live_title)
        live_grid = QGridLayout()
        live_grid.setHorizontalSpacing(10)
        live_grid.setVerticalSpacing(10)

        self.card_viewers_twitch = StatusCard("Viewers Twitch")
        self.card_viewers_tiktok = StatusCard("Viewers TikTok")
        self.card_viewers_kick = StatusCard("Viewers Kick")
        live_grid.addWidget(self.card_viewers_twitch, 0, 0)
        live_grid.addWidget(self.card_viewers_tiktok, 0, 1)
        live_grid.addWidget(self.card_viewers_kick, 0, 2)

        goal_panel = QFrame()
        goal_panel.setObjectName("dashboardPanel")
        goal_layout = QVBoxLayout(goal_panel)
        goal_layout.setContentsMargins(16, 14, 16, 14)
        goal_layout.setSpacing(8)
        goal_head = QHBoxLayout()
        goal_title = QLabel("Meta activa")
        goal_title.setObjectName("dashboardPanelTitle")
        goal_head.addWidget(goal_title)
        goal_head.addStretch(1)
        self.home_goal_percent = QLabel("—")
        self.home_goal_percent.setObjectName("dashboardValueSmall")
        goal_head.addWidget(self.home_goal_percent)
        goal_layout.addLayout(goal_head)
        self.home_goal_name = QLabel("Sin metas activas")
        self.home_goal_name.setObjectName("dashboardBigText")
        self.home_goal_name.setWordWrap(True)
        goal_layout.addWidget(self.home_goal_name)
        self.home_goal_progress = QProgressBar()
        self.home_goal_progress.setObjectName("goalProgress")
        self.home_goal_progress.setRange(0, 1000)
        self.home_goal_progress.setValue(0)
        self.home_goal_progress.setTextVisible(False)
        goal_layout.addWidget(self.home_goal_progress)
        self.home_goal_detail = QLabel("Crea una meta para verla aquí.")
        self.home_goal_detail.setObjectName("dashboardMuted")
        goal_layout.addWidget(self.home_goal_detail)
        live_grid.addWidget(goal_panel, 1, 0, 1, 2)

        ranking_panel = QFrame()
        ranking_panel.setObjectName("dashboardPanel")
        rank_layout = QVBoxLayout(ranking_panel)
        rank_layout.setContentsMargins(16, 14, 16, 14)
        rank_layout.setSpacing(7)
        rank_title = QLabel("Ranking semanal")
        rank_title.setObjectName("dashboardPanelTitle")
        rank_layout.addWidget(rank_title)
        self.home_rank_rows = []
        for i in range(3):
            row = QLabel(f"{i+1}. —")
            row.setObjectName("rankingPreviewRow")
            rank_layout.addWidget(row)
            self.home_rank_rows.append(row)
        rank_btn = QPushButton("Abrir ranking")
        rank_btn.clicked.connect(lambda: self._activate_route("ranking.html?v=57", force=True))
        rank_layout.addWidget(rank_btn)
        live_grid.addWidget(ranking_panel, 0, 2, 2, 1)
        live_grid.setColumnStretch(0, 1)
        live_grid.setColumnStretch(1, 1)
        live_grid.setColumnStretch(2, 2)
        layout.addLayout(live_grid)

        activity_panel = QFrame()
        activity_panel.setObjectName("dashboardPanel")
        activity_layout = QVBoxLayout(activity_panel)
        activity_layout.setContentsMargins(16, 14, 16, 14)
        activity_layout.setSpacing(8)
        activity_head = QHBoxLayout()
        activity_title = QLabel("Actividad reciente")
        activity_title.setObjectName("dashboardPanelTitle")
        activity_head.addWidget(activity_title)
        activity_head.addStretch(1)
        monitor_btn = QPushButton("Monitor")
        monitor_btn.clicked.connect(lambda: self._activate_route("eventos_monitor.html?v=57", force=True))
        activity_head.addWidget(monitor_btn)
        activity_layout.addLayout(activity_head)
        self.home_activity = QListWidget()
        self.home_activity.setObjectName("homeActivity")
        self.home_activity.setMinimumHeight(150)
        self.home_activity.setMaximumHeight(210)
        activity_layout.addWidget(self.home_activity)
        layout.addWidget(activity_panel)

        utility = QHBoxLayout()
        for text, fn in [
            ("Abrir datos", lambda: self.open_folder(APPDATA_ROOT)),
            ("Actualizar estado", self.refresh_status),
            ("Ver novedades", self.open_updates),
            ("Activar Funnel :8766", self.start_tailscale),
            ("Apagar Funnel", self.stop_tailscale),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            utility.addWidget(btn)
        utility.addStretch(1)
        layout.addLayout(utility)

        obs_panel = QFrame()
        obs_panel.setObjectName("dashboardPanel")
        obs_layout = QVBoxLayout(obs_panel)
        obs_layout.setContentsMargins(16, 14, 16, 14)
        obs_title = QLabel("Fuentes OBS")
        obs_title.setObjectName("dashboardPanelTitle")
        obs_layout.addWidget(obs_title)
        self.obs_urls = QPlainTextEdit()
        self.obs_urls.setReadOnly(True)
        self.obs_urls.setMaximumHeight(190)
        self.obs_urls.setPlainText(self._obs_text())
        obs_layout.addWidget(self.obs_urls)
        layout.addWidget(obs_panel)

        tip = QLabel(
            "Consejo: usa Ctrl+K desde cualquier pantalla para encontrar módulos, comandos, emotes y metas por nombre. "
            "También puedes hacer clic derecho sobre una sección del menú para fijarla en Favoritos."
        )
        tip.setWordWrap(True)
        tip.setObjectName("tip")
        layout.addWidget(tip)
        layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self._home_event_after = 0
        return page

    def _format_home_event(self, event: dict) -> str:
        kind = str(event.get("type") or "evento").replace("_", " ")
        user = str(event.get("username") or event.get("user") or event.get("chatname") or "").strip()
        platform = str(event.get("platform") or event.get("source") or "").strip()
        detail = ""
        if isinstance(event.get("goal"), dict):
            detail = str(event["goal"].get("title") or "")
        elif event.get("command"):
            detail = str(event.get("command"))
        elif event.get("reward"):
            detail = str(event.get("reward"))
        parts = [kind.upper()]
        if user:
            parts.append(user)
        if detail:
            parts.append(detail)
        if platform:
            parts.append(platform.upper())
        return "  ·  ".join(parts)

    def _refresh_home_snapshot(self):
        if not hasattr(self, "card_viewers_twitch"):
            return
        try:
            viewers = http_json(f"{LOCAL_BASE}/api/chat/viewers", timeout=0.45)
            tw = viewers.get("twitch")
            tt = viewers.get("tiktok")
            kk = viewers.get("kick")
            self.card_viewers_kick.set_state(str(kk) if kk is not None else "N/D", "Viewers actuales", True if kk is not None else None)
            self.card_viewers_twitch.set_state(str(tw) if tw is not None else "N/D", "Viewers actuales", True if tw is not None else None)
            self.card_viewers_tiktok.set_state(str(tt) if tt is not None else "N/D", "Viewers actuales", True if tt is not None else None)
        except Exception:
            self.card_viewers_twitch.set_state("N/D", "Sin dato", None)
            self.card_viewers_tiktok.set_state("N/D", "Sin dato", None)
            self.card_viewers_kick.set_state("N/D", "Sin dato", None)

        try:
            ranking = http_json(f"{LOCAL_BASE}/api/ranking", timeout=0.45)
            top = list(ranking.get("top") or [])[:3]
            for i, label in enumerate(self.home_rank_rows):
                if i < len(top):
                    row = top[i]
                    username = str(row.get("username") or "Usuario")
                    score = row.get("score", 0)
                    label.setText(f"{i+1}. {username}   ·   {score:g} pts" if isinstance(score, (int, float)) else f"{i+1}. {username}   ·   {score} pts")
                else:
                    label.setText(f"{i+1}. —")
        except Exception:
            pass

        try:
            goals = http_json(f"{LOCAL_BASE}/api/goals", timeout=0.45)
            active = [g for g in list(goals.get("goals") or []) if g.get("enabled", True)]
            active.sort(key=lambda g: (bool(g.get("completed")), -float(g.get("percent", 0) or 0)))
            if active:
                goal = active[0]
                pct = max(0.0, min(100.0, float(goal.get("percent", 0) or 0)))
                self.home_goal_name.setText(str(goal.get("title") or "Meta"))
                self.home_goal_percent.setText(f"{pct:.1f}%")
                self.home_goal_progress.setValue(int(pct * 10))
                self.home_goal_detail.setText(f"{goal.get('current',0):g} / {goal.get('target',0):g} · faltan {goal.get('remaining',0):g}")
            else:
                self.home_goal_name.setText("Sin metas activas")
                self.home_goal_percent.setText("—")
                self.home_goal_progress.setValue(0)
                self.home_goal_detail.setText("Crea una meta para verla aquí.")
        except Exception:
            pass

        try:
            payload = http_json(f"{LOCAL_BASE}/api/events?after=0", timeout=0.45)
            events = list(payload.get("events") or [])[-8:]
            self.home_activity.clear()
            if not events:
                self.home_activity.addItem("Sin actividad reciente en esta sesión.")
            else:
                for event in reversed(events):
                    self.home_activity.addItem(self._format_home_event(event))
        except Exception:
            if self.home_activity.count() == 0:
                self.home_activity.addItem("Esperando actividad del stream…")

    def _make_settings(self) -> QWidget:
        """Panel de ajustes general.

        V0.47.3 evita QFormLayout aquí porque, con algunos temas/escala de
        Windows, Qt comprime la columna de etiquetas y los controles quedan
        montados unos sobre otros. Todos los campos usan etiquetas superiores
        y el panel completo es desplazable.
        """
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(12)

        title = QLabel("Ajustes de Brynn Interactive")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Configura la identidad del canal, Social Stream Ninja y el comportamiento de la aplicación. "
            "Los datos personales de cada instalación se guardan de forma independiente en AppData."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # La barra horizontal se habilita como fallback si alguna sección
        # de terceros/no adaptable requiere más anchura que la ventana.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 6, 10, 12)
        layout.setSpacing(15)

        def card(title_text: str, subtitle_text: str = ""):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            box = QVBoxLayout(frame)
            box.setContentsMargins(20, 18, 20, 20)
            box.setSpacing(13)
            heading = QLabel(title_text)
            heading.setObjectName("cardTitle")
            box.addWidget(heading)
            if subtitle_text:
                desc = QLabel(subtitle_text)
                desc.setObjectName("cardSubtitle")
                desc.setWordWrap(True)
                box.addWidget(desc)
            return frame, box

        def field(title_text: str, control: QWidget, hint_text: str = ""):
            wrap = QWidget()
            wrap.setObjectName("fieldWrap")
            v = QVBoxLayout(wrap)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(6)
            label = QLabel(title_text)
            label.setObjectName("settingLabel")
            v.addWidget(label)
            v.addWidget(control)
            if hint_text:
                hint = QLabel(hint_text)
                hint.setObjectName("settingHint")
                hint.setWordWrap(True)
                v.addWidget(hint)
            return wrap

        # Identidad ---------------------------------------------------
        profile_box, profile_layout = card(
            "Identidad del canal",
            "Estas cuentas (Twitch, TikTok y Kick) se usan como propietario dentro de Brynn. No se distribuyen en la build comercial limpia."
        )
        self.profile_streamer = QLineEdit()
        self.profile_streamer.setPlaceholderText("Ej. MiCanalVT")
        self.profile_twitch = QLineEdit()
        self.profile_twitch.setPlaceholderText("Usuario de Twitch sin @")
        self.profile_tiktok = QLineEdit()
        self.profile_tiktok.setPlaceholderText("Usuario de TikTok sin @")
        self.profile_kick = QLineEdit()
        self.profile_kick.setPlaceholderText("Usuario de Kick sin @")

        identity_grid = QGridLayout()
        identity_grid.setContentsMargins(0, 0, 0, 0)
        identity_grid.setHorizontalSpacing(14)
        identity_grid.setVerticalSpacing(12)
        identity_grid.setColumnStretch(0, 1)
        identity_grid.setColumnStretch(1, 1)
        identity_grid.addWidget(field("Nombre del canal", self.profile_streamer), 0, 0, 1, 2)
        identity_grid.addWidget(field("Propietario Twitch", self.profile_twitch), 1, 0)
        identity_grid.addWidget(field("Propietario TikTok", self.profile_tiktok), 1, 1)
        identity_grid.addWidget(field("Propietario Kick", self.profile_kick), 2, 0, 1, 2)
        profile_layout.addLayout(identity_grid)

        save_profile_btn = QPushButton("Guardar identidad")
        save_profile_btn.setObjectName("primaryAction")
        save_profile_btn.clicked.connect(self.save_profile_settings)
        profile_actions = QHBoxLayout()
        profile_actions.addWidget(save_profile_btn)
        profile_actions.addStretch(1)
        profile_layout.addLayout(profile_actions)
        layout.addWidget(profile_box)

        # Social Stream Ninja · transporte principal ----------------
        social_box, social_layout = card(
            "Social Stream Ninja · chat principal",
            "Brynn usa Channel 4 de Social Stream Ninja para recibir Twitch + TikTok y sendChat para publicar desde nuestro chat y responder comandos en las plataformas conectadas."
        )
        self.session_id = QLineEdit()
        self.session_id.setPlaceholderText("Session ID de Social Stream Ninja")
        self.session_password = QLineEdit()
        self.session_password.setPlaceholderText("false")

        social_grid = QGridLayout()
        social_grid.setContentsMargins(0, 0, 0, 0)
        social_grid.setHorizontalSpacing(14)
        social_grid.setVerticalSpacing(12)
        social_grid.setColumnStretch(0, 2)
        social_grid.setColumnStretch(1, 1)
        social_grid.addWidget(field("Session ID", self.session_id), 0, 0)
        social_grid.addWidget(field("Password / room password", self.session_password), 0, 1)
        social_layout.addLayout(social_grid)

        save_social = QPushButton("Guardar Social Stream Ninja")
        save_social.setObjectName("primaryAction")
        save_social.clicked.connect(self.save_social_settings)
        social_actions = QHBoxLayout()
        social_actions.addWidget(save_social)
        social_actions.addStretch(1)
        social_layout.addLayout(social_actions)
        layout.addWidget(social_box)

        # Comportamiento Desktop -------------------------------------
        desktop_box, desktop_layout = card(
            "Aplicación y escritorio",
            "Controla el comportamiento de la ventana y el acceso a herramientas técnicas."
        )
        options_panel = QFrame()
        options_panel.setObjectName("subtlePanel")
        options = QVBoxLayout(options_panel)
        options.setContentsMargins(14, 12, 14, 12)
        options.setSpacing(10)

        self.minimize_to_tray = QCheckBox("Cerrar ventana = minimizar a bandeja")
        self.minimize_to_tray.setChecked(self.settings.value("minimizeToTray", True, type=bool))
        self.minimize_to_tray.toggled.connect(lambda value: self.settings.setValue("minimizeToTray", value))

        self.start_windows = QCheckBox("Iniciar Brynn Interactive con Windows")
        self.start_windows.setChecked(self._startup_enabled())
        self.start_windows.toggled.connect(self._set_startup)

        self.developer_mode = QCheckBox("Modo Developer")
        self.developer_mode.setToolTip("Muestra Monitor, Pruebas y Diagnóstico en el menú lateral.")
        self.developer_mode.toggled.connect(self._set_developer_mode)

        options.addWidget(self.minimize_to_tray)
        options.addWidget(self.start_windows)
        options.addWidget(self.developer_mode)
        desktop_layout.addWidget(options_panel)

        appearance_btn = QPushButton("Abrir personalización avanzada")
        appearance_btn.clicked.connect(self.open_personalization)
        desktop_actions = QHBoxLayout()
        desktop_actions.addWidget(appearance_btn)
        desktop_actions.addStretch(1)
        desktop_layout.addLayout(desktop_actions)
        layout.addWidget(desktop_box)

        # Rutas de datos ----------------------------------------------
        paths_box, paths_layout = card(
            "Datos locales",
            "Estas carpetas pertenecen únicamente a esta instalación de Windows. Las actualizaciones no deberían borrarlas."
        )

        def path_row(label_text: str, value: Path):
            frame = QFrame()
            frame.setObjectName("subtlePanel")
            row = QHBoxLayout(frame)
            row.setContentsMargins(14, 10, 14, 10)
            row.setSpacing(12)
            left = QLabel(label_text)
            left.setObjectName("settingLabel")
            left.setMinimumWidth(190)
            value_label = QLabel(str(value))
            value_label.setObjectName("settingHint")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            row.addWidget(left, 0)
            row.addWidget(value_label, 1)
            return frame

        paths_layout.addWidget(path_row("Datos persistentes", DATA_DIR))
        paths_layout.addWidget(path_row("Multimedia persistente", MEDIA_DIR))
        paths_layout.addWidget(path_row("Streamlabs global", STREAMLABS_FILE))
        paths_layout.addWidget(path_row("Versiones / actualizaciones", DESKTOP_STATE_FILE))
        paths_layout.addWidget(path_row("Apariencia persistente", APPEARANCE_FILE))

        open_data = QPushButton("Abrir carpeta BrynnInteractive")
        open_data.clicked.connect(lambda: self.open_folder(APPDATA_ROOT))
        path_actions = QHBoxLayout()
        path_actions.addWidget(open_data)
        path_actions.addStretch(1)
        paths_layout.addLayout(path_actions)
        layout.addWidget(paths_box)

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.settings_status = QLabel("")
        self.settings_status.setObjectName("personalizationStatus")
        self.settings_status.setWordWrap(True)
        root.addWidget(self.settings_status)
        return page


    def _make_privacy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(16)
        title = QLabel("Datos y privacidad")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Brynn Interactive guarda tus configuraciones localmente en AppData. "
            "Las exportaciones normales no incluyen tokens privados de Twitch o Streamlabs."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        transfer = QFrame(); transfer.setObjectName("panel")
        tv = QVBoxLayout(transfer); tv.setContentsMargins(18,18,18,18); tv.setSpacing(10)
        tv.addWidget(QLabel("Migración y copias personales"))
        row = QHBoxLayout()
        export_btn = QPushButton("Exportar configuración")
        export_btn.clicked.connect(self.export_user_configuration)
        import_btn = QPushButton("Importar configuración")
        import_btn.clicked.connect(self.import_user_configuration)
        backup_btn = QPushButton("Crear backup local")
        backup_btn.clicked.connect(self.create_backup)
        row.addWidget(export_btn); row.addWidget(import_btn); row.addWidget(backup_btn); row.addStretch(1)
        tv.addLayout(row)
        layout.addWidget(transfer)

        reset = QFrame(); reset.setObjectName("panel")
        rv = QVBoxLayout(reset); rv.setContentsMargins(18,18,18,18); rv.setSpacing(10)
        rv.addWidget(QLabel("Restablecimiento"))
        warning = QLabel("Estas acciones crean un backup antes de borrar información. El restablecimiento total vuelve a mostrar el asistente inicial.")
        warning.setWordWrap(True); warning.setObjectName("tip"); rv.addWidget(warning)
        row2 = QHBoxLayout()
        community = QPushButton("Borrar ranking y economía")
        community.clicked.connect(self.reset_community_data)
        full = QPushButton("Restablecer todo")
        full.clicked.connect(self.factory_reset)
        row2.addWidget(community); row2.addWidget(full); row2.addStretch(1)
        rv.addLayout(row2)
        layout.addWidget(reset)

        self.privacy_status = QLabel("")
        self.privacy_status.setWordWrap(True)
        layout.addWidget(self.privacy_status)
        layout.addStretch(1)
        return page

    def _make_personalization(self) -> QWidget:
        page = QWidget()
        page.setObjectName("personalizationPage")
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(14)

        title = QLabel("Personalización")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Ajusta la apariencia de Brynn Interactive de forma visual. "
            "Los cambios se guardan fuera de la carpeta de la versión y se conservan al actualizar."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # La barra horizontal se habilita como fallback si alguna sección
        # de terceros/no adaptable requiere más anchura que la ventana.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 10, 10)
        layout.setSpacing(16)

        def card(title_text: str, subtitle_text: str = ""):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            box = QVBoxLayout(frame)
            box.setContentsMargins(20, 18, 20, 20)
            box.setSpacing(14)
            head = QLabel(title_text)
            head.setObjectName("cardTitle")
            box.addWidget(head)
            if subtitle_text:
                desc = QLabel(subtitle_text)
                desc.setWordWrap(True)
                desc.setObjectName("cardSubtitle")
                box.addWidget(desc)
            return frame, box

        def field(title_text: str, control: QWidget, hint_text: str = ""):
            wrap = QWidget()
            wrap.setObjectName("fieldWrap")
            v = QVBoxLayout(wrap)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(7)
            label = QLabel(title_text)
            label.setObjectName("settingLabel")
            v.addWidget(label)
            v.addWidget(control)
            if hint_text:
                hint = QLabel(hint_text)
                hint.setWordWrap(True)
                hint.setObjectName("settingHint")
                v.addWidget(hint)
            return wrap

        def color_control(target: QLineEdit):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addWidget(target, 1)
            btn = QPushButton("Elegir color")
            btn.setObjectName("quietButton")
            btn.clicked.connect(lambda: self._pick_color(target))
            h.addWidget(btn)
            return row

        # Tema ---------------------------------------------------------
        theme_card, theme_box = card(
            "Tema y color",
            "Elige una base visual y, si quieres, reemplaza sus acentos. Dejar un color vacío usa el valor del tema."
        )
        theme_grid = QGridLayout()
        theme_grid.setHorizontalSpacing(16)
        theme_grid.setVerticalSpacing(14)
        theme_grid.setColumnStretch(0, 2)
        theme_grid.setColumnStretch(1, 1)
        theme_grid.setColumnStretch(2, 1)

        self.ap_theme = QComboBox()
        for label, key in [
            ("Neon / Futurista", "neon"),
            ("Spooky / Halloween", "spooky"),
            ("Day / Claro", "day"),
            ("Cyber Cyan", "cyber"),
            ("Amber Signal", "amber"),
            ("Violet Proxy", "violet"),
            ("Terminal Mono", "mono"),
            ("Graphite / Minimal", "graphite"),
            ("Ocean Glass", "ocean"),
            ("Rose Circuit", "rose"),
            ("Crimson Core", "crimson"),
            ("Sakura Dream", "sakura"),
            ("Candy Pop", "candy"),
            ("Arcade Night", "arcade"),
            ("Matrix Terminal", "matrix"),
            ("Sunset Drive", "sunset"),
            ("Ice Crystal", "ice"),
            ("Coffee Studio", "coffee"),
        ]:
            self.ap_theme.addItem(label, key)
        theme_grid.addWidget(field("Tema base", self.ap_theme, "Cambia el ambiente general de toda la aplicación."), 0, 0)

        self.ap_accent = QLineEdit()
        self.ap_accent.setPlaceholderText("Automático")
        theme_grid.addWidget(field("Color principal", color_control(self.ap_accent)), 0, 1)

        self.ap_accent2 = QLineEdit()
        self.ap_accent2.setPlaceholderText("Automático")
        theme_grid.addWidget(field("Color secundario", color_control(self.ap_accent2)), 0, 2)
        theme_box.addLayout(theme_grid)
        layout.addWidget(theme_card)

        # Identidad ----------------------------------------------------
        identity_card, identity_box = card(
            "Identidad",
            "Controla el texto de marca, la tipografía y dónde quieres ver la versión."
        )
        identity_grid = QGridLayout()
        identity_grid.setHorizontalSpacing(16)
        identity_grid.setVerticalSpacing(14)
        identity_grid.setColumnStretch(0, 1)
        identity_grid.setColumnStretch(1, 1)

        self.ap_brand = QLineEdit()
        self.ap_brand.setPlaceholderText(r"BRYNN\nINTERACTIVE")
        identity_grid.addWidget(field("Marca del menú lateral", self.ap_brand, r"Usa \n para crear una segunda línea."), 0, 0)

        self.ap_font = QComboBox()
        self.ap_font.setEditable(True)
        for font in ("Segoe UI Variable", "Segoe UI", "Inter", "Arial", "Trebuchet MS", "Consolas", "Verdana"):
            self.ap_font.addItem(font)
        identity_grid.addWidget(field("Tipografía", self.ap_font, "Se aplica a la interfaz nativa y a los paneles web."), 0, 1)

        version_options = QFrame()
        version_options.setObjectName("subtlePanel")
        vv = QVBoxLayout(version_options)
        vv.setContentsMargins(14, 12, 14, 12)
        vv.setSpacing(9)
        self.ap_sidebar_version = QCheckBox("Mostrar versión debajo de la marca")
        self.ap_title_version = QCheckBox("Mostrar versión en la barra superior")
        vv.addWidget(self.ap_sidebar_version)
        vv.addWidget(self.ap_title_version)
        identity_grid.addWidget(field("Visibilidad de versión", version_options), 1, 0, 1, 2)
        identity_box.addLayout(identity_grid)
        layout.addWidget(identity_card)

        # Navegación y layout -----------------------------------------
        layout_card, layout_box = card(
            "Interfaz y navegación",
            "Ajusta espacio, tamaño y comportamiento visual. Los valores numéricos son campos de texto visibles para evitar problemas de renderizado con los controles nativos de Qt."
        )
        controls_grid = QGridLayout()
        controls_grid.setHorizontalSpacing(18)
        controls_grid.setVerticalSpacing(16)
        controls_grid.setColumnStretch(0, 1)
        controls_grid.setColumnStretch(1, 1)

        self.ap_density = QComboBox()
        self.ap_density.addItem("Compacta", "compact")
        self.ap_density.addItem("Cómoda", "comfortable")
        self.ap_density.addItem("Espaciosa", "spacious")
        controls_grid.addWidget(field("Densidad", self.ap_density, "Controla el espacio vertical entre elementos."), 0, 0)

        self.ap_menu_style = QComboBox()
        self.ap_menu_style.addItem("Suave", "soft")
        self.ap_menu_style.addItem("Minimal", "minimal")
        self.ap_menu_style.addItem("Píldora", "pill")
        self.ap_menu_style.addItem("Indicador lateral", "rail")
        controls_grid.addWidget(field("Estilo del menú", self.ap_menu_style, "Cambia cómo se marca la sección activa."), 0, 1)

        self.ap_window_style = QComboBox()
        for label,key in [
            ("Soft Studio","soft"),("Glass Panel","glass"),("Arcade Frame","arcade"),
            ("Halloween Card","halloween"),("Terminal / CRT","terminal"),("Candy Rounded","candy"),("Minimal Flat","minimal")
        ]:
            self.ap_window_style.addItem(label,key)
        controls_grid.addWidget(field("Estilo de ventana", self.ap_window_style, "Cambia bordes, profundidad y lenguaje visual de paneles nativos."), 1, 0)

        self.ap_titlebar = QComboBox()
        self.ap_titlebar.addItem("Gradiente suave", "gradient")
        self.ap_titlebar.addItem("Sólida", "solid")
        self.ap_titlebar.addItem("Línea de acento", "line")
        controls_grid.addWidget(field("Barra superior", self.ap_titlebar, "Estilo visual de la barra de la ventana."), 1, 1)

        def make_number_input(minimum: int, maximum: int, default: int, unit: str):
            wrapper = QFrame()
            wrapper.setObjectName("numberInputWrap")
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            edit = QLineEdit(str(default))
            edit.setObjectName("numberInput")
            edit.setValidator(QIntValidator(minimum, maximum, edit))
            edit.setProperty("minValue", minimum)
            edit.setProperty("maxValue", maximum)
            edit.setProperty("defaultValue", default)
            edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            unit_label = QLabel(unit)
            unit_label.setObjectName("numberUnit")
            unit_label.setMinimumWidth(28)
            row.addWidget(edit, 1)
            row.addWidget(unit_label)
            return edit, wrapper

        self.ap_sidebar, sidebar_control = make_number_input(210, 380, 250, "px")
        controls_grid.addWidget(field("Ancho del menú", sidebar_control, "210–380 px"), 2, 0)

        self.ap_scale, scale_control = make_number_input(85, 135, 100, "%")
        controls_grid.addWidget(field("Escala de interfaz", scale_control, "85–135 %"), 2, 1)

        self.ap_webzoom, webzoom_control = make_number_input(75, 130, 95, "%")
        controls_grid.addWidget(field("Zoom de paneles web", webzoom_control, "75–130 %"), 3, 0)

        self.ap_radius, radius_control = make_number_input(0, 28, 14, "px")
        controls_grid.addWidget(field("Redondeo de paneles", radius_control, "0–28 px"), 3, 1)

        self.ap_titlebar_height, titlebar_control = make_number_input(40, 64, 46, "px")
        controls_grid.addWidget(field("Altura de barra superior", titlebar_control, "40–64 px"), 4, 0)

        footer_panel = QFrame()
        footer_panel.setObjectName("subtlePanel")
        footer_layout = QVBoxLayout(footer_panel)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        self.ap_footer = QCheckBox("Mostrar barra inferior de estado")
        footer_layout.addWidget(self.ap_footer)
        controls_grid.addWidget(field("Estado global", footer_panel), 4, 1)

        layout_box.addLayout(controls_grid)
        layout.addWidget(layout_card)

        # Transiciones y carga -----------------------------------------
        loader_card, loader_box = card(
            "Transiciones y carga",
            "Elimina el destello blanco al cambiar de módulo. La vista anterior permanece visible mientras la siguiente carga en segundo plano."
        )
        loader_grid = QGridLayout()
        loader_grid.setHorizontalSpacing(16)
        loader_grid.setVerticalSpacing(14)
        loader_grid.setColumnStretch(0, 1)
        loader_grid.setColumnStretch(1, 1)

        self.ap_loading_type = QComboBox()
        for label, key in [
            ("Círculo", "circle"),
            ("Puntos", "dots"),
            ("Barra", "bar"),
            ("Glitch", "glitch"),
            ("Imagen / GIF", "image"),
            ("Emote registrado", "emote"),
        ]:
            self.ap_loading_type.addItem(label, key)
        loader_grid.addWidget(field("Indicador", self.ap_loading_type, "Elige la animación que aparece mientras carga una sección."), 0, 0)

        self.ap_loading_text = QLineEdit()
        self.ap_loading_text.setPlaceholderText("Cargando módulo…")
        loader_grid.addWidget(field("Texto de carga", self.ap_loading_text, "Puedes ocultarlo con la opción inferior."), 0, 1)

        self.ap_loading_size, loader_size_control = make_number_input(32, 180, 72, "px")
        loader_grid.addWidget(field("Tamaño del indicador", loader_size_control, "32–180 px"), 1, 0)

        self.ap_loading_min_ms, loader_time_control = make_number_input(0, 3000, 320, "ms")
        loader_grid.addWidget(field("Tiempo mínimo visible", loader_time_control, "0–3000 ms. Evita parpadeos cuando una página carga demasiado rápido."), 1, 1)

        self.ap_loading_image = QLineEdit()
        self.ap_loading_image.setReadOnly(True)
        self.ap_loading_image.setPlaceholderText("Sin imagen personalizada")
        image_row = QWidget()
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(8)
        image_layout.addWidget(self.ap_loading_image, 1)
        select_image_btn = QPushButton("Elegir")
        select_image_btn.clicked.connect(self.select_loading_image)
        clear_image_btn = QPushButton("Quitar")
        clear_image_btn.clicked.connect(lambda: self.ap_loading_image.setText(""))
        image_layout.addWidget(select_image_btn)
        image_layout.addWidget(clear_image_btn)
        self.ap_loading_image_field = field("Imagen o GIF personalizado", image_row, "Se copia a AppData para que no se pierda al actualizar.")
        loader_grid.addWidget(self.ap_loading_image_field, 2, 0)

        self.ap_loading_emote = QComboBox()
        self.ap_loading_emote.addItem("Ninguno", "")
        self.ap_loading_emote_field = field("Emote registrado", self.ap_loading_emote, "Usa la imagen o GIF del emote guardado en Brynn Interactive.")
        loader_grid.addWidget(self.ap_loading_emote_field, 2, 1)

        self.ap_loading_opacity, loader_opacity_control = make_number_input(0, 100, 82, "%")
        loader_grid.addWidget(field("Oscurecimiento del fondo", loader_opacity_control, "0–100 %. Sólo se usa si el fondo de carga está habilitado."), 3, 0)

        loader_options = QFrame()
        loader_options.setObjectName("subtlePanel")
        lo = QVBoxLayout(loader_options)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(8)
        self.ap_loading_show_text = QCheckBox("Mostrar texto de carga")
        self.ap_loading_backdrop = QCheckBox("Oscurecer contenido mientras carga")
        lo.addWidget(self.ap_loading_show_text)
        lo.addWidget(self.ap_loading_backdrop)
        loader_grid.addWidget(field("Comportamiento", loader_options), 3, 1)

        loader_box.addLayout(loader_grid)
        loader_actions = QHBoxLayout()
        test_loader_btn = QPushButton("Probar pantalla de carga")
        test_loader_btn.clicked.connect(self.test_loading_screen)
        loader_actions.addWidget(test_loader_btn)
        loader_actions.addStretch(1)
        loader_box.addLayout(loader_actions)
        layout.addWidget(loader_card)

        self.ap_loading_type.currentIndexChanged.connect(self._refresh_loader_controls)

        # Splash Studio 2.0 --------------------------------------------
        splash_card, splash_box = card(
            "Splash Studio 3.1 · editor de la ventana de carga",
            "Edita exactamente la ventana que aparece al abrir Brynn Interactive: logo, textos, barra e imágenes personalizadas, con un flujo tipo mini editor visual."
        )
        splash_controls_shell = QVBoxLayout(); splash_controls_shell.setSpacing(12)

        # Columnas compactas podían forzar el ancho mínimo más allá del área
        # visible de Personalización. En vertical se ve cada botón y entrada.
        splash_row1 = QVBoxLayout(); splash_row1.setSpacing(12)
        splash_row2 = QVBoxLayout(); splash_row2.setSpacing(12)

        splash_flags=QFrame(); splash_flags.setObjectName("subtlePanel")
        sf=QVBoxLayout(splash_flags); sf.setContentsMargins(14,12,14,12); sf.setSpacing(8)
        flags_title = QLabel("Comportamiento")
        flags_title.setObjectName("fieldLabel")
        flags_hint = QLabel("Activa o desactiva la ventana de carga y define si quieres usar el logo oficial de Brynn.")
        flags_hint.setObjectName("fieldHint"); flags_hint.setWordWrap(True)
        self.ap_startup_enabled=QCheckBox("Mostrar pantalla de inicio al abrir Brynn")
        self.ap_startup_logo=QCheckBox("Mostrar logo oficial de Brynn")
        sf.addWidget(flags_title); sf.addWidget(flags_hint); sf.addWidget(self.ap_startup_enabled); sf.addWidget(self.ap_startup_logo); sf.addStretch(1)
        splash_row1.addWidget(splash_flags, 1)

        theme_card=QFrame(); theme_card.setObjectName("subtlePanel")
        tc=QVBoxLayout(theme_card); tc.setContentsMargins(14,12,14,12); tc.setSpacing(8)
        theme_title = QLabel("Tema y progreso")
        theme_title.setObjectName("fieldLabel")
        theme_hint = QLabel("Elige la paleta del splash y el estilo de la barra de progreso. Luego puedes afinarlo en el lienzo y en los colores.")
        theme_hint.setObjectName("fieldHint"); theme_hint.setWordWrap(True)
        preset_wrap=QWidget(); pw=QHBoxLayout(preset_wrap); pw.setContentsMargins(0,0,0,0); pw.setSpacing(8)
        self.ap_startup_preset=QComboBox()
        for label,key in [("Neon Brynn","neon"),("Halloween","halloween"),("Cyberpunk","cyber"),("Sakura","sakura"),("Ocean","ocean"),("Arcade","arcade"),("Candy","candy"),("Sunset","sunset"),("Retro CRT","retro"),("Minimal","minimal")]: self.ap_startup_preset.addItem(label,key)
        self.ap_startup_progress_style=QComboBox()
        for label,key in [("Neon","neon"),("Segmentada","segmented"),("Arcade","arcade"),("Halloween","halloween"),("Candy","candy"),("Rainbow","rainbow"),("Minimal","minimal")]: self.ap_startup_progress_style.addItem(label,key)
        pw.addWidget(self.ap_startup_preset,1); pw.addWidget(self.ap_startup_progress_style,1)
        preset_apply=QPushButton("Aplicar preset"); preset_apply.clicked.connect(self.apply_startup_preset); pw.addWidget(preset_apply)
        self.ap_startup_bg=QLineEdit(); self.ap_startup_bg.setPlaceholderText("#080b12")
        theme_bottom = QHBoxLayout(); theme_bottom.setSpacing(10)
        theme_bottom.addWidget(field("Fondo", color_control(self.ap_startup_bg)), 1)
        self.ap_startup_min_ms, startup_time_control = make_number_input(300,10000,1200,"ms")
        theme_bottom.addWidget(field("Tiempo mínimo",startup_time_control,"Evita que la ventana desaparezca demasiado rápido."), 1)
        tc.addWidget(theme_title); tc.addWidget(theme_hint); tc.addWidget(preset_wrap); tc.addLayout(theme_bottom)
        splash_row1.addWidget(theme_card, 1)

        text_card=QFrame(); text_card.setObjectName("subtlePanel")
        txc=QVBoxLayout(text_card); txc.setContentsMargins(14,12,14,12); txc.setSpacing(8)
        text_title = QLabel("Textos del splash")
        text_title.setObjectName("fieldLabel")
        text_hint = QLabel("El título y subtítulo también aparecen como capas movibles en el lienzo, igual que en un editor visual.")
        text_hint.setObjectName("fieldHint"); text_hint.setWordWrap(True)
        self.ap_startup_title=QLineEdit(); self.ap_startup_title.setPlaceholderText("BRYNN INTERACTIVE")
        self.ap_startup_subtitle=QLineEdit(); self.ap_startup_subtitle.setPlaceholderText("Preparando tu centro de control…")
        txc.addWidget(text_title); txc.addWidget(text_hint)
        txc.addWidget(field("Título", self.ap_startup_title))
        txc.addWidget(field("Subtítulo", self.ap_startup_subtitle))
        splash_row2.addWidget(text_card, 1)

        audio_card=QFrame(); audio_card.setObjectName("subtlePanel")
        ac=QVBoxLayout(audio_card); ac.setContentsMargins(14,12,14,12); ac.setSpacing(8)
        audio_title = QLabel("Audio y recursos")
        audio_title.setObjectName("fieldLabel")
        audio_hint = QLabel("Puedes añadir audio para esta ventana. Las imágenes, GIF y vídeos se siguen agregando desde la biblioteca de capas de abajo.")
        audio_hint.setObjectName("fieldHint"); audio_hint.setWordWrap(True)
        self.ap_startup_audio=QLineEdit(); self.ap_startup_audio.setReadOnly(True); self.ap_startup_audio.setPlaceholderText("Sin audio")
        audio_row=QWidget(); ar=QHBoxLayout(audio_row); ar.setContentsMargins(0,0,0,0); ar.setSpacing(7); ar.addWidget(self.ap_startup_audio,1)
        audio_choose=QPushButton("Elegir audio"); audio_choose.clicked.connect(self.select_startup_audio); ar.addWidget(audio_choose)
        audio_clear=QPushButton("Quitar"); audio_clear.clicked.connect(self.clear_startup_audio); ar.addWidget(audio_clear)
        self.ap_startup_volume, startup_volume_control = make_number_input(0,100,55,"%")
        ac.addWidget(audio_title); ac.addWidget(audio_hint)
        ac.addWidget(field("Audio de inicio",audio_row,"MP3/WAV/OGG/M4A. Se detiene al terminar de abrir."))
        ac.addWidget(field("Volumen del audio",startup_volume_control))
        splash_row2.addWidget(audio_card, 1)

        # Campo legacy invisible para migrar V0.56 sin perder el media anterior.
        self.ap_startup_media=QLineEdit(); self.ap_startup_media.hide()

        splash_controls_shell.addLayout(splash_row1)
        splash_controls_shell.addLayout(splash_row2)
        splash_box.addLayout(splash_controls_shell)

        # Biblioteca / capas / editor visual.
        splash_editor_shell = QVBoxLayout(); splash_editor_shell.setSpacing(12)
        splash_workspace_row = QHBoxLayout(); splash_workspace_row.setSpacing(12)

        left_panel = QFrame(); left_panel.setObjectName("subtlePanel"); left_panel.setMinimumWidth(204); left_panel.setMaximumWidth(248)
        lp = QVBoxLayout(left_panel); lp.setContentsMargins(12,12,12,12); lp.setSpacing(8)
        layers_title = QLabel("Recursos y capas")
        layers_title.setObjectName("sectionTitle")
        lp.addWidget(layers_title)
        layer_hint = QLabel("Importa una imagen y selecciónala: aparecerá en el lienzo para arrastrarla y cambiar su tamaño.")
        layer_hint.setObjectName("fieldHint"); layer_hint.setWordWrap(True)
        lp.addWidget(layer_hint)
        library_box = QFrame(); library_box.setObjectName("subtlePanel")
        lb = QVBoxLayout(library_box); lb.setContentsMargins(10,10,10,10); lb.setSpacing(6)
        library_actions = QVBoxLayout(); library_actions.setSpacing(6)
        add_images=QPushButton("+ Imágenes / GIF"); add_images.clicked.connect(self.add_startup_images); library_actions.addWidget(add_images)
        add_video=QPushButton("+ Vídeo"); add_video.clicked.connect(self.add_startup_video); library_actions.addWidget(add_video)
        lb.addLayout(library_actions)
        stack_actions = QHBoxLayout(); stack_actions.setSpacing(6)
        duplicate_layer=QPushButton("Duplicar"); duplicate_layer.clicked.connect(self.duplicate_startup_layer); stack_actions.addWidget(duplicate_layer)
        remove_layer=QPushButton("Eliminar"); remove_layer.clicked.connect(self.remove_startup_layer); stack_actions.addWidget(remove_layer)
        lb.addLayout(stack_actions)
        order_actions = QHBoxLayout(); order_actions.setSpacing(6)
        layer_up=QPushButton("Subir"); layer_up.clicked.connect(lambda: self.move_startup_layer(1)); order_actions.addWidget(layer_up)
        layer_down=QPushButton("Bajar"); layer_down.clicked.connect(lambda: self.move_startup_layer(-1)); order_actions.addWidget(layer_down)
        order_actions.addStretch(1)
        lb.addLayout(order_actions)
        lp.addWidget(library_box)
        layers_label = QLabel("Capas")
        layers_label.setObjectName("fieldLabel")
        lp.addWidget(layers_label)
        self.ap_splash_layers=QListWidget(); self.ap_splash_layers.setMinimumHeight(360); self.ap_splash_layers.setIconSize(QSize(56,56)); self.ap_splash_layers.setSpacing(4); self.ap_splash_layers.currentItemChanged.connect(self._on_splash_layer_list_selected)
        lp.addWidget(self.ap_splash_layers,1)
        splash_workspace_row.addWidget(left_panel,0)

        center_panel = QFrame(); center_panel.setObjectName("subtlePanel")
        cp = QVBoxLayout(center_panel); cp.setContentsMargins(12,12,12,12); cp.setSpacing(8)
        canvas_toolbar = QHBoxLayout(); canvas_toolbar.setSpacing(6)
        editor_title = QLabel("Mesa de trabajo")
        editor_title.setObjectName("sectionTitle")
        canvas_toolbar.addWidget(editor_title)
        self.ap_splash_selected_info = QLabel("Sin capa seleccionada")
        self.ap_splash_selected_info.setObjectName("fieldHint")
        canvas_toolbar.addWidget(self.ap_splash_selected_info, 1)
        cp.addLayout(canvas_toolbar)
        canvas_actions = QHBoxLayout(); canvas_actions.setSpacing(6)
        splash_center_btn = QPushButton("Centrar")
        splash_center_btn.clicked.connect(self.center_selected_splash_layer)
        splash_fill_btn = QPushButton("Ajustar al lienzo")
        splash_fill_btn.clicked.connect(self.fill_selected_splash_layer)
        splash_reset_img_btn = QPushButton("Reset imagen")
        splash_reset_img_btn.clicked.connect(self.reset_selected_splash_layer_transform)
        for b in (splash_center_btn, splash_fill_btn, splash_reset_img_btn): canvas_actions.addWidget(b)
        canvas_actions.addStretch(1)
        cp.addLayout(canvas_actions)
        # Dividir acciones en dos filas mantiene usable el lienzo a 900-1100 px.
        quick_toolbar = QHBoxLayout(); quick_toolbar.setSpacing(6)
        nudge_left = QPushButton("←"); nudge_left.clicked.connect(lambda: self.nudge_selected_splash_layer(-1,0)); quick_toolbar.addWidget(nudge_left)
        nudge_up = QPushButton("↑"); nudge_up.clicked.connect(lambda: self.nudge_selected_splash_layer(0,-1)); quick_toolbar.addWidget(nudge_up)
        nudge_down = QPushButton("↓"); nudge_down.clicked.connect(lambda: self.nudge_selected_splash_layer(0,1)); quick_toolbar.addWidget(nudge_down)
        nudge_right = QPushButton("→"); nudge_right.clicked.connect(lambda: self.nudge_selected_splash_layer(1,0)); quick_toolbar.addWidget(nudge_right)
        quick_toolbar.addStretch(1)
        cp.addLayout(quick_toolbar)
        edit_toolbar = QHBoxLayout(); edit_toolbar.setSpacing(6)
        resize_minus = QPushButton("- Tamaño"); resize_minus.clicked.connect(lambda: self.resize_selected_splash_layer(-2,-2)); edit_toolbar.addWidget(resize_minus)
        resize_plus = QPushButton("+ Tamaño"); resize_plus.clicked.connect(lambda: self.resize_selected_splash_layer(2,2)); edit_toolbar.addWidget(resize_plus)
        flip_lr = QPushButton("Voltear H"); flip_lr.setToolTip("Invertir izquierda/derecha"); flip_lr.clicked.connect(lambda: self.toggle_selected_splash_layer_flip(True)); edit_toolbar.addWidget(flip_lr)
        flip_ud = QPushButton("Voltear V"); flip_ud.setToolTip("Invertir arriba/abajo"); flip_ud.clicked.connect(lambda: self.toggle_selected_splash_layer_flip(False)); edit_toolbar.addWidget(flip_ud)
        edit_toolbar.addStretch(1)
        cp.addLayout(edit_toolbar)
        studio_hint=QLabel("Este editor modifica la ventana de carga real de Brynn. El rectángulo central es el lienzo 16:9. Clic = seleccionar · arrastra = mover · esquina inferior derecha = tamaño · rueda = zoom · Ctrl + rueda = rotar · clic derecho y arrastra = reencuadrar. Usa Invertir izquierda/derecha para cambiar hacia dónde mira la imagen.")
        studio_hint.setObjectName("settingHint"); studio_hint.setWordWrap(True); cp.addWidget(studio_hint)
        self.ap_splash_canvas=SplashEditorCanvas(); cp.addWidget(self.ap_splash_canvas,1)
        self.ap_splash_canvas_status = QLabel("X: 0% · Y: 0% · W: 0% · H: 0%")
        self.ap_splash_canvas_status.setObjectName("fieldHint")
        cp.addWidget(self.ap_splash_canvas_status)
        splash_workspace_row.addWidget(center_panel,3)
        splash_editor_shell.addLayout(splash_workspace_row)

        right_panel = QFrame(); right_panel.setObjectName("subtlePanel")
        rp = QVBoxLayout(right_panel); rp.setContentsMargins(12,12,12,12); rp.setSpacing(8)
        inspector_title = QLabel("Propiedades")
        inspector_title.setObjectName("sectionTitle")
        rp.addWidget(inspector_title)
        inspector_hint = QLabel("Inspector organizado por transformación y contenido, más cercano a un editor de imagen. Todo se actualiza al instante.")
        inspector_hint.setObjectName("fieldHint"); inspector_hint.setWordWrap(True)
        rp.addWidget(inspector_hint)
        transform_label = QLabel("Transformación")
        transform_label.setObjectName("fieldLabel")
        rp.addWidget(transform_label)
        inspector=QFrame(); inspector.setObjectName("subtlePanel"); ig=QGridLayout(inspector); ig.setContentsMargins(10,10,10,10); ig.setHorizontalSpacing(8); ig.setVerticalSpacing(6)
        self.ap_layer_fit=QComboBox();
        for label,key in [("Contener","contain"),("Cubrir / recortar","cover"),("Estirar","stretch")]: self.ap_layer_fit.addItem(label,key)
        self.ap_layer_animation=QComboBox();
        for label,key in [("Sin animación","none"),("Flotar","float"),("Deriva lateral","drift"),("Respirar","breathe"),("Pulso","pulse"),("Fade de entrada","fade")]: self.ap_layer_animation.addItem(label,key)
        self.ap_layer_opacity, opacity_wrap = make_number_input(10,100,100,"%")
        self.ap_layer_zoom, zoom_wrap = make_number_input(10,400,100,"%")
        self.ap_layer_panx, panx_wrap = make_number_input(-200,200,0,"x")
        self.ap_layer_pany, pany_wrap = make_number_input(-200,200,0,"y")
        self.ap_layer_rotation, rotation_wrap = make_number_input(0,359,0,"°")
        self.ap_layer_posx, posx_wrap = make_number_input(0,100,8,"%")
        self.ap_layer_posy, posy_wrap = make_number_input(0,100,10,"%")
        self.ap_layer_width, width_wrap = make_number_input(1,100,28,"%")
        self.ap_layer_height, height_wrap = make_number_input(1,100,42,"%")
        self.ap_layer_flip_h = QCheckBox("Horizontal (izq./der.)")
        self.ap_layer_flip_v = QCheckBox("Vertical")
        flips_row = QWidget(); fr = QHBoxLayout(flips_row); fr.setContentsMargins(0,0,0,0); fr.setSpacing(10); fr.addWidget(self.ap_layer_flip_h); fr.addWidget(self.ap_layer_flip_v); fr.addStretch(1)
        ig.addWidget(field("Ajuste",self.ap_layer_fit),0,0); ig.addWidget(field("Animación",self.ap_layer_animation),0,1)
        ig.addWidget(field("Posición X",posx_wrap),1,0); ig.addWidget(field("Posición Y",posy_wrap),1,1)
        ig.addWidget(field("Ancho",width_wrap),2,0); ig.addWidget(field("Alto",height_wrap),2,1)
        ig.addWidget(field("Opacidad",opacity_wrap),3,0); ig.addWidget(field("Zoom",zoom_wrap),3,1)
        ig.addWidget(field("Paneo X",panx_wrap),4,0); ig.addWidget(field("Paneo Y",pany_wrap),4,1)
        ig.addWidget(field("Rotación",rotation_wrap),5,0); ig.addWidget(field("Orientación",flips_row),5,1)
        quick_actions = QWidget(); qa = QHBoxLayout(quick_actions); qa.setContentsMargins(0,0,0,0); qa.setSpacing(6)
        quick_duplicate = QPushButton("Duplicar capa")
        quick_duplicate.clicked.connect(self.duplicate_startup_layer)
        quick_delete = QPushButton("Quitar capa")
        quick_delete.clicked.connect(self.remove_startup_layer)
        for b in (quick_duplicate, quick_delete): qa.addWidget(b)
        qa.addStretch(1)
        ig.addWidget(field("Capas", quick_actions),6,0,1,2)
        rp.addWidget(inspector)
        content_label = QLabel("Contenido")
        content_label.setObjectName("fieldLabel")
        rp.addWidget(content_label)
        rp.addStretch(1)
        splash_editor_shell.addWidget(right_panel)
        splash_box.addLayout(splash_editor_shell)

        self._splash_layout_edit=default_appearance()["startupLayout"]
        self._splash_media_items_edit=[]
        self.ap_splash_canvas.layoutChanged.connect(self._on_splash_layout_changed)
        self.ap_splash_canvas.mediaItemsChanged.connect(self._on_splash_media_items_changed)
        self.ap_splash_canvas.selectionChanged.connect(self._on_splash_canvas_selection)
        self.ap_layer_fit.currentIndexChanged.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_animation.currentIndexChanged.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_posx.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_posy.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_width.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_height.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_opacity.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_zoom.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_panx.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_pany.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_rotation.editingFinished.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_flip_h.toggled.connect(self._update_selected_splash_layer_properties)
        self.ap_layer_flip_v.toggled.connect(self._update_selected_splash_layer_properties)

        splash_actions=QHBoxLayout()
        test_splash=QPushButton("Probar pantalla de inicio"); test_splash.clicked.connect(self.test_startup_splash); splash_actions.addWidget(test_splash)
        reset_splash=QPushButton("Restablecer escena"); reset_splash.clicked.connect(self.reset_splash_layout); splash_actions.addWidget(reset_splash)
        splash_actions.addStretch(1); splash_box.addLayout(splash_actions)
        layout.addWidget(splash_card)

        for control in (self.ap_startup_enabled,self.ap_startup_logo): control.toggled.connect(self._refresh_splash_presentation)
        for control in (self.ap_startup_title,self.ap_startup_subtitle,self.ap_startup_bg): control.textChanged.connect(self._refresh_splash_presentation)
        self.ap_startup_preset.currentIndexChanged.connect(self._refresh_splash_presentation)
        self.ap_startup_progress_style.currentIndexChanged.connect(self._refresh_splash_presentation)

        # Personalización del actualizador ---------------------------
        update_style_card, update_style_box = card(
            "Actualizaciones · apariencia",
            "La ventana de actualización ya no depende de una consola. También puede seguir el tema general o usar un estilo propio y una barra distinta."
        )
        ug=QGridLayout(); ug.setHorizontalSpacing(16); ug.setVerticalSpacing(12); ug.setColumnStretch(0,1); ug.setColumnStretch(1,1)
        self.ap_update_preset=QComboBox()
        for label,key in [("Seguir tema de Brynn","match"),("Neon","neon"),("Halloween","halloween"),("Cyberpunk","cyber"),("Sakura","sakura"),("Ocean","ocean"),("Arcade","arcade"),("Candy","candy"),("Sunset","sunset"),("Retro CRT","retro"),("Minimal","minimal")]: self.ap_update_preset.addItem(label,key)
        self.ap_update_progress=QComboBox()
        for label,key in [("Neon","neon"),("Segmentada","segmented"),("Arcade","arcade"),("Halloween","halloween"),("Candy","candy"),("Rainbow","rainbow"),("Minimal","minimal")]: self.ap_update_progress.addItem(label,key)
        self.ap_update_title=QLineEdit(); self.ap_update_title.setPlaceholderText("Actualizando Brynn Interactive")
        self.ap_update_log=QCheckBox("Mostrar registro técnico desde el inicio")
        self.ap_update_logo=QCheckBox("Mostrar logo de Brynn")
        self.ap_update_bg=QLineEdit(); self.ap_update_bg.setPlaceholderText("Automático por tema")
        self.ap_update_media=QLineEdit(); self.ap_update_media.setReadOnly(True); self.ap_update_media.setPlaceholderText("Sin imagen / GIF decorativo")
        upd_media_wrap=QWidget(); um=QHBoxLayout(upd_media_wrap); um.setContentsMargins(0,0,0,0); um.setSpacing(7); um.addWidget(self.ap_update_media,1)
        upd_choose=QPushButton("Elegir"); upd_choose.clicked.connect(self.select_update_media); um.addWidget(upd_choose)
        upd_clear=QPushButton("Quitar"); upd_clear.clicked.connect(lambda: self.ap_update_media.setText("")); um.addWidget(upd_clear)
        details_wrap=QFrame(); details_wrap.setObjectName("subtlePanel"); dw=QVBoxLayout(details_wrap); dw.setContentsMargins(10,8,10,8); dw.addWidget(self.ap_update_logo); dw.addWidget(self.ap_update_log)
        ug.addWidget(field("Tema",self.ap_update_preset),0,0); ug.addWidget(field("Barra de progreso",self.ap_update_progress),0,1); ug.addWidget(field("Título",self.ap_update_title),1,0); ug.addWidget(field("Comportamiento",details_wrap),1,1); ug.addWidget(field("Fondo personalizado",color_control(self.ap_update_bg),"Déjalo vacío para usar el tema."),2,0); ug.addWidget(field("Imagen / GIF decorativo",upd_media_wrap),2,1)
        update_style_box.addLayout(ug)
        preview_update=QPushButton("Probar ventana de actualización"); preview_update.clicked.connect(self.test_update_dialog); update_style_box.addWidget(preview_update,0,Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(update_style_card)

        # Aplicación, icono y escritorio -------------------------------
        app_card, app_box = card(
            "Aplicación, icono y escritorio",
            "Elige cómo se representa Brynn Interactive en la ventana, la bandeja, la barra de tareas y el acceso directo del escritorio."
        )
        app_grid = QGridLayout()
        app_grid.setHorizontalSpacing(16)
        app_grid.setVerticalSpacing(14)
        app_grid.setColumnStretch(1, 1)

        self.ap_icon_preview = QLabel()
        self.ap_icon_preview.setFixedSize(76, 76)
        self.ap_icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ap_icon_preview.setObjectName("appIconPreview")
        app_grid.addWidget(self.ap_icon_preview, 0, 0, 2, 1)

        self.ap_icon_path = QLineEdit()
        self.ap_icon_path.setReadOnly(True)
        self.ap_icon_path.setPlaceholderText("Icono predeterminado de Brynn Interactive")
        app_grid.addWidget(field("Icono de la aplicación", self.ap_icon_path, "Admite ICO, PNG, JPG, WEBP o BMP. Las imágenes se convierten a ICO automáticamente."), 0, 1)

        icon_actions = QWidget()
        icon_actions_l = QHBoxLayout(icon_actions)
        icon_actions_l.setContentsMargins(0, 0, 0, 0)
        icon_actions_l.setSpacing(8)
        choose_icon_btn = QPushButton("Seleccionar icono")
        choose_icon_btn.clicked.connect(self.select_app_icon)
        reset_icon_btn = QPushButton("Usar predeterminado")
        reset_icon_btn.clicked.connect(self.reset_app_icon)
        shortcut_btn = QPushButton("Crear / actualizar acceso directo")
        shortcut_btn.clicked.connect(self.create_or_refresh_desktop_shortcut)
        build_exe_btn = QPushButton("Generar EXE para escritorio")
        build_exe_btn.clicked.connect(self.build_desktop_executable)
        for b in (choose_icon_btn, reset_icon_btn, shortcut_btn, build_exe_btn):
            icon_actions_l.addWidget(b)
        icon_actions_l.addStretch(1)
        app_grid.addWidget(icon_actions, 1, 1)

        app_help = QLabel(
            "El EXE se genera con PyInstaller en dist\\BrynnInteractiveDesktop. "
            "En el escritorio se crea un acceso directo al EXE real; no apunta a un .bat ni a python.exe. "
            "Si cambias el icono después, el acceso directo y la app se actualizan inmediatamente; vuelve a generar el EXE para incrustarlo también dentro del archivo .exe."
        )
        app_help.setWordWrap(True)
        app_help.setObjectName("fieldHint")
        app_grid.addWidget(app_help, 2, 0, 1, 2)
        app_box.addLayout(app_grid)
        layout.addWidget(app_card)

        # Preview ------------------------------------------------------
        preview_card, preview_box = card(
            "Vista previa",
            "Esta miniatura cambia mientras editas para que puedas evaluar el resultado antes de guardar."
        )
        self.ap_preview = QFrame()
        self.ap_preview.setObjectName("appearancePreview")
        preview_layout = QHBoxLayout(self.ap_preview)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(14)

        preview_side = QFrame()
        preview_side.setObjectName("appearancePreviewSide")
        ps = QVBoxLayout(preview_side)
        ps.setContentsMargins(14, 14, 14, 14)
        ps.setSpacing(7)
        self.ap_preview_brand = QLabel("BRYNN\nINTERACTIVE")
        self.ap_preview_brand.setObjectName("previewBrand")
        ps.addWidget(self.ap_preview_brand)
        for name in ("Inicio", "Comandos", "Personalización"):
            item = QLabel(name)
            item.setObjectName("previewMenuItemSelected" if name == "Personalización" else "previewMenuItem")
            ps.addWidget(item)
        ps.addStretch(1)
        preview_layout.addWidget(preview_side, 0)
        self.ap_preview_side = preview_side

        preview_content = QFrame()
        preview_content.setObjectName("appearancePreviewContent")
        pc = QVBoxLayout(preview_content)
        pc.setContentsMargins(18, 16, 18, 16)
        pc.setSpacing(9)
        self.ap_preview_title = QLabel("Panel de ejemplo")
        self.ap_preview_title.setObjectName("previewTitle")
        self.ap_preview_text = QLabel("Tema listo para previsualizar.")
        self.ap_preview_text.setWordWrap(True)
        self.ap_preview_text.setObjectName("previewText")
        pc.addWidget(self.ap_preview_title)
        pc.addWidget(self.ap_preview_text)
        preview_button = QPushButton("Acción de ejemplo")
        preview_button.setObjectName("previewButton")
        preview_button.setEnabled(False)
        pc.addWidget(preview_button)
        pc.addStretch(1)
        preview_layout.addWidget(preview_content, 1)
        self.ap_preview_content = preview_content
        self.ap_preview_button = preview_button
        preview_box.addWidget(self.ap_preview)
        layout.addWidget(preview_card)

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Acciones fijas -----------------------------------------------
        action_bar = QFrame()
        action_bar.setObjectName("personalizationActions")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(14, 11, 14, 11)
        actions.setSpacing(8)
        save_btn = QPushButton("Guardar y aplicar")
        save_btn.setObjectName("primaryAction")
        save_btn.clicked.connect(self.save_personalization)
        reset_btn = QPushButton("Restablecer")
        reset_btn.clicked.connect(self.reset_personalization)
        export_btn = QPushButton("Exportar perfil")
        export_btn.clicked.connect(self.export_appearance_profile)
        import_btn = QPushButton("Importar perfil")
        import_btn.clicked.connect(self.import_appearance_profile)
        folder_btn = QPushButton("Abrir configuración")
        folder_btn.clicked.connect(lambda: self.open_folder(APPDATA_ROOT))
        for btn in (save_btn, reset_btn, export_btn, import_btn, folder_btn):
            actions.addWidget(btn)
        actions.addStretch(1)
        root.addWidget(action_bar)

        self.ap_status = QLabel("")
        self.ap_status.setObjectName("personalizationStatus")
        self.ap_status.setWordWrap(True)
        root.addWidget(self.ap_status)

        # Preview en vivo sin guardar.
        self.ap_theme.currentIndexChanged.connect(self._refresh_personalization_preview)
        self.ap_accent.textChanged.connect(self._refresh_personalization_preview)
        self.ap_accent2.textChanged.connect(self._refresh_personalization_preview)
        self.ap_brand.textChanged.connect(self._refresh_personalization_preview)
        self.ap_font.currentTextChanged.connect(self._refresh_personalization_preview)
        self.ap_density.currentIndexChanged.connect(self._refresh_personalization_preview)
        self.ap_menu_style.currentIndexChanged.connect(self._refresh_personalization_preview)
        self.ap_titlebar.currentIndexChanged.connect(self._refresh_personalization_preview)
        self.ap_window_style.currentIndexChanged.connect(self._refresh_personalization_preview)
        for edit in (self.ap_sidebar, self.ap_scale, self.ap_webzoom, self.ap_radius, self.ap_titlebar_height):
            edit.textChanged.connect(self._refresh_personalization_preview)

        self._load_personalization_form()
        QTimer.singleShot(0, self._refresh_personalization_preview)
        return page

    def _combo_select_data(self, combo: QComboBox, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_personalization_form(self):
        if not hasattr(self, "ap_theme"):
            return
        a = self.appearance
        self._combo_select_data(self.ap_theme, a.get("theme", "neon"))
        self.ap_accent.setText(str(a.get("accent") or ""))
        self.ap_accent2.setText(str(a.get("accent2") or ""))
        self.ap_brand.setText(str(a.get("brand") or r"BRYNN\nINTERACTIVE"))
        font = str(a.get("fontFamily") or "Segoe UI")
        idx = self.ap_font.findText(font)
        if idx >= 0:
            self.ap_font.setCurrentIndex(idx)
        else:
            self.ap_font.setEditText(font)
        self._combo_select_data(self.ap_density, a.get("density", "comfortable"))
        self._combo_select_data(self.ap_titlebar, a.get("titlebarStyle", "gradient"))
        self._combo_select_data(self.ap_menu_style, a.get("menuStyle", "soft"))
        if hasattr(self, "ap_window_style"):
            self._combo_select_data(self.ap_window_style, a.get("windowFrameStyle", "soft"))
        self.ap_sidebar.setText(str(int(a.get("sidebarWidth", 250))))
        self.ap_scale.setText(str(int(a.get("uiScale", 100))))
        self.ap_webzoom.setText(str(int(a.get("webZoom", 95))))
        self.ap_radius.setText(str(int(a.get("panelRadius", 14))))
        self.ap_titlebar_height.setText(str(int(a.get("titlebarHeight", 46))))
        self.ap_footer.setChecked(bool(a.get("showFooter", True)))
        self.ap_sidebar_version.setChecked(bool(a.get("showSidebarVersion", True)))
        self.ap_title_version.setChecked(bool(a.get("showTitleVersion", True)))
        if hasattr(self, "ap_icon_path"):
            custom_icon = str(a.get("appIconPath") or "")
            self.ap_icon_path.setText(custom_icon if custom_icon else "")
            self._refresh_app_icon_preview()

        if hasattr(self, "ap_loading_type"):
            self._combo_select_data(self.ap_loading_type, a.get("loadingType", "circle"))
            self.ap_loading_image.setText(str(a.get("loadingImage") or ""))
            self._refresh_loading_emotes()
            self._combo_select_data(self.ap_loading_emote, a.get("loadingEmoteId", ""))
            self.ap_loading_size.setText(str(int(a.get("loadingSize", 72))))
            self.ap_loading_min_ms.setText(str(int(a.get("loadingMinMs", 320))))
            self.ap_loading_text.setText(str(a.get("loadingText") or "Cargando módulo…"))
            self.ap_loading_show_text.setChecked(bool(a.get("loadingShowText", True)))
            self.ap_loading_backdrop.setChecked(bool(a.get("loadingBackdrop", True)))
            self.ap_loading_opacity.setText(str(int(a.get("loadingBackdropOpacity", 82))))
            self._refresh_loader_controls()

        if hasattr(self, "ap_startup_enabled"):
            self.ap_startup_enabled.setChecked(bool(a.get("startupSplashEnabled", True)))
            self.ap_startup_logo.setChecked(bool(a.get("startupShowLogo", True)))
            self.ap_startup_title.setText(str(a.get("startupTitle") or "BRYNN INTERACTIVE"))
            self.ap_startup_subtitle.setText(str(a.get("startupSubtitle") or "Preparando tu centro de control…"))
            self.ap_startup_media.setText(str(a.get("startupMediaPath") or ""))
            self.ap_startup_audio.setText(str(a.get("startupAudioPath") or ""))
            self.ap_startup_min_ms.setText(str(int(a.get("startupSplashMinMs", 1200))))
            self.ap_startup_volume.setText(str(int(a.get("startupAudioVolume", 55))))
            self.ap_startup_bg.setText(str(a.get("startupBackground") or "#080b12"))
            self._combo_select_data(self.ap_startup_preset, a.get("startupPreset", "neon"))
            self._combo_select_data(self.ap_startup_progress_style, a.get("startupProgressStyle", "neon"))
            self._splash_layout_edit=json.loads(json.dumps(a.get("startupLayout") or default_appearance()["startupLayout"]))
            self._splash_media_items_edit=json.loads(json.dumps(a.get("startupMediaItems") or []))
            if not self._splash_media_items_edit and str(a.get("startupMediaPath") or "").strip():
                spec=(a.get("startupLayout") or {}).get("media") or default_appearance()["startupLayout"]["media"]
                self._splash_media_items_edit=[{"id":"legacy","path":str(a.get("startupMediaPath")),"name":Path(str(a.get("startupMediaPath"))).name,"fit":"contain","animation":"none","opacity":100,"zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False,"z":1,**spec}]
            self._refresh_splash_editor()
        if hasattr(self, "ap_update_preset"):
            self._combo_select_data(self.ap_update_preset, a.get("updateStylePreset", "match"))
            self._combo_select_data(self.ap_update_progress, a.get("updateProgressStyle", "neon"))
            self.ap_update_title.setText(str(a.get("updateTitle") or "Actualizando Brynn Interactive"))
            self.ap_update_log.setChecked(bool(a.get("updateShowTechnicalLog", False)))
            self.ap_update_logo.setChecked(bool(a.get("updateShowLogo", True)))
            self.ap_update_bg.setText(str(a.get("updateBackground") or ""))
            self.ap_update_media.setText(str(a.get("updateMediaPath") or ""))

        if hasattr(self, "ap_preview_brand"):
            self.ap_preview_brand.setText(str(a.get("brand") or r"BRYNN\nINTERACTIVE").replace(r"\n", "\n"))

    def _refresh_loading_emotes(self):
        if not hasattr(self, "ap_loading_emote"):
            return
        selected = self.ap_loading_emote.currentData() if self.ap_loading_emote.count() else ""
        self.ap_loading_emote.blockSignals(True)
        self.ap_loading_emote.clear()
        self.ap_loading_emote.addItem("Ninguno", "")
        payload = load_json_file(DATA_DIR / "emotes.json", {"emotes": []})
        emotes = payload.get("emotes", []) if isinstance(payload, dict) else []
        for emote in emotes:
            emote_id = str(emote.get("id") or "").strip()
            if not emote_id:
                continue
            label = str(emote.get("name") or emote_id).strip()
            self.ap_loading_emote.addItem(f"{label}  (!emote {emote_id})", emote_id)
        idx = self.ap_loading_emote.findData(selected)
        if idx >= 0:
            self.ap_loading_emote.setCurrentIndex(idx)
        self.ap_loading_emote.blockSignals(False)

    def _refresh_loader_controls(self, *_):
        if not hasattr(self, "ap_loading_type"):
            return
        mode = str(self.ap_loading_type.currentData() or "circle")
        self.ap_loading_image_field.setEnabled(mode == "image")
        self.ap_loading_emote_field.setEnabled(mode == "emote")

    def select_loading_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Elegir imagen de carga",
            str(Path.home()),
            "Imágenes (*.png *.jpg *.jpeg *.webp *.gif);;Todos los archivos (*.*)",
        )
        if not filename:
            return
        source = Path(filename)
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            QMessageBox.warning(self, "Imagen no compatible", "Usa PNG, JPG, WEBP o GIF.")
            return
        LOADER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = LOADER_MEDIA_DIR / f"loader_{stamp}{source.suffix.lower()}"
        try:
            shutil.copy2(source, target)
            self.ap_loading_image.setText(str(target))
            self.ap_status.setText("Imagen de carga copiada a AppData.")
        except Exception as exc:
            QMessageBox.critical(self, "Imagen de carga", str(exc))

    def test_loading_screen(self):
        if not hasattr(self, "loading_overlay"):
            return
        preview = default_appearance()
        preview.update(self._appearance_from_form())
        old_appearance = self.appearance
        previous_widget = self.stack.currentWidget()
        self.appearance = preview
        self._configure_loading_overlay()
        self.stack.setCurrentWidget(self.web_host)
        self.loading_overlay.show_loader("Vista previa")
        duration = max(650, min(3500, int(preview.get("loadingMinMs") or 320) + 900))

        def finish_preview():
            self.loading_overlay.hide_loader()
            self.appearance = old_appearance
            self._configure_loading_overlay()
            if self._active_route == "personalization":
                self.stack.setCurrentWidget(self.personalization)
            elif previous_widget is not None:
                self.stack.setCurrentWidget(previous_widget)

        QTimer.singleShot(duration, finish_preview)

    def _on_splash_layout_changed(self, layout_data: dict):
        self._splash_layout_edit=json.loads(json.dumps(layout_data or {}))

    def _on_splash_media_items_changed(self, rows: list):
        previous = {str(r.get("id")): r for r in getattr(self, "_splash_media_items_edit", [])}
        self._splash_media_items_edit = json.loads(json.dumps(rows or []))
        if not hasattr(self, "ap_splash_layers"):
            return
        expected = [str(r.get("id")) for r in sorted(rows or [], key=lambda r: int(r.get("z", 0)), reverse=True)]
        actual = [str(self.ap_splash_layers.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.ap_splash_layers.count())]
        if actual != expected:
            self._refresh_splash_layer_list(keep_selection=True)
        else:
            # Solo vuelve a generar iconos cuando cambia su aspecto real.
            appearance_keys = ("path", "name", "animation", "fit", "zoom", "panX", "panY", "rotation", "flipH", "flipV")
            for i in range(self.ap_splash_layers.count()):
                item = self.ap_splash_layers.item(i)
                row = self._find_splash_layer(item.data(Qt.ItemDataRole.UserRole))
                before = previous.get(str(row.get("id")), {}) if row else {}
                if row and any(before.get(k) != row.get(k) for k in appearance_keys):
                    item.setIcon(self._make_splash_layer_icon(row))
                    item.setText(f"{row.get('name', 'MEDIA')}   ·   {row.get('animation', 'none')}")
        current = self.ap_splash_layers.currentItem()
        if current:
            self._on_splash_layer_list_selected(current)

    def _startup_form_config(self) -> dict:
        cfg=default_appearance()
        cfg.update({
            "startupSplashEnabled": self.ap_startup_enabled.isChecked() if hasattr(self,"ap_startup_enabled") else True,
            "startupShowLogo": self.ap_startup_logo.isChecked() if hasattr(self,"ap_startup_logo") else True,
            "startupTitle": self.ap_startup_title.text().strip() if hasattr(self,"ap_startup_title") else "BRYNN INTERACTIVE",
            "startupSubtitle": self.ap_startup_subtitle.text().strip() if hasattr(self,"ap_startup_subtitle") else "Preparando tu centro de control…",
            "startupMediaPath": self.ap_startup_media.text().strip() if hasattr(self,"ap_startup_media") else "",
            "startupMediaItems": json.loads(json.dumps(getattr(self,"_splash_media_items_edit",[]))),
            "startupAudioPath": self.ap_startup_audio.text().strip() if hasattr(self,"ap_startup_audio") else "",
            "startupSplashMinMs": self._number_from_input(self.ap_startup_min_ms) if hasattr(self,"ap_startup_min_ms") else 1200,
            "startupAudioVolume": self._number_from_input(self.ap_startup_volume) if hasattr(self,"ap_startup_volume") else 55,
            "startupBackground": normalize_hex_color(self.ap_startup_bg.text()) if hasattr(self,"ap_startup_bg") else "#080b12",
            "startupPreset": self.ap_startup_preset.currentData() if hasattr(self,"ap_startup_preset") else "neon",
            "startupProgressStyle": self.ap_startup_progress_style.currentData() if hasattr(self,"ap_startup_progress_style") else "neon",
            "startupLayout": json.loads(json.dumps(getattr(self,"_splash_layout_edit",default_appearance()["startupLayout"]))),
        })
        if not cfg["startupBackground"]: cfg["startupBackground"]=visual_style_profile(cfg.get("startupPreset"))["bg"]
        return cfg

    def _refresh_splash_editor(self, *_):
        if not hasattr(self,"ap_splash_canvas"): return
        selected = self._selected_splash_layer_id() if hasattr(self, "ap_splash_layers") else ""
        cfg=self._startup_form_config()
        self.ap_splash_canvas.set_config(cfg)
        self.ap_splash_canvas.setEnabled(bool(cfg.get("startupSplashEnabled",True)))
        self._splash_media_items_edit=self.ap_splash_canvas.media_items()
        self._refresh_splash_layer_list(keep_selection=True)
        if selected and self._find_splash_layer(selected):
            self._select_splash_layer_by_id(selected)

    def _refresh_splash_presentation(self, *_):
        """Actualiza textos/tema sin destruir y reconstruir todas las capas."""
        if not hasattr(self, "ap_splash_canvas"):
            return
        canvas = self.ap_splash_canvas
        canvas.setEnabled(self.ap_startup_enabled.isChecked())
        canvas.items["logo"].setVisible(self.ap_startup_logo.isChecked())
        canvas.items["title"].caption.setText(self.ap_startup_title.text() or "TÍTULO")
        canvas.items["subtitle"].caption.setText(self.ap_startup_subtitle.text() or "SUBTÍTULO")
        canvas.background_color = normalize_hex_color(self.ap_startup_bg.text()) or "#080b12"
        canvas.preset = str(self.ap_startup_preset.currentData() or "neon")
        canvas.update()

    def _copy_startup_asset(self, filename: str, prefix: str) -> str:
        source=Path(filename)
        LOADER_MEDIA_DIR.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target=LOADER_MEDIA_DIR / f"{prefix}_{stamp}{source.suffix.lower()}"
        shutil.copy2(source,target)
        return str(target)

    def _next_splash_layer_id(self) -> str:
        return "layer_"+datetime.now().strftime("%H%M%S_%f")

    def add_startup_images(self):
        files,_=QFileDialog.getOpenFileNames(self,"Añadir imágenes o GIF al splash",str(Path.home()),"Imágenes / GIF (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Todos (*.*)")
        if not files: return
        added=[]
        for idx,filename in enumerate(files):
            try:
                path=self._copy_startup_asset(filename,"splash_layer")
                ident=self._next_splash_layer_id()+str(idx)
                count=len(self._splash_media_items_edit)
                row={"id":ident,"path":path,"name":Path(filename).stem,"fit":"contain","animation":"none","opacity":100,"zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False,"z":count+1,"x":.08+min(.36,(count%4)*.05),"y":.10+min(.35,(count%5)*.04),"w":.28,"h":.42}
                self._splash_media_items_edit.append(row); added.append(row)
            except Exception as exc:
                QMessageBox.warning(self,"Splash Studio",f"No se pudo agregar {Path(filename).name}:\n{exc}")
        self._refresh_splash_editor()
        if added:
            self._select_splash_layer_by_id(str(added[-1]["id"]))
            self.ap_status.setText(f"{len(added)} elemento(s) añadidos al splash.")

    def add_startup_video(self):
        filename,_=QFileDialog.getOpenFileName(self,"Añadir vídeo al splash",str(Path.home()),"Vídeos (*.mp4 *.webm *.mov *.m4v *.avi *.mkv);;Todos (*.*)")
        if not filename: return
        try:
            path=self._copy_startup_asset(filename,"splash_video")
            ident=self._next_splash_layer_id(); count=len(self._splash_media_items_edit)
            self._splash_media_items_edit.append({"id":ident,"path":path,"name":Path(filename).stem,"fit":"cover","animation":"none","opacity":100,"zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False,"z":count+1,"x":.08,"y":.08,"w":.42,"h":.56})
            self._refresh_splash_editor(); self._select_splash_layer_by_id(ident); self.ap_status.setText("Vídeo añadido al splash.")
        except Exception as exc: QMessageBox.critical(self,"Splash Studio",str(exc))

    def _make_splash_layer_icon(self, row: dict) -> QIcon:
        canvas = QPixmap(56, 56)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#53e6ff"), 1))
        painter.setBrush(QColor(10, 16, 26, 230))
        painter.drawRoundedRect(2, 2, 52, 52, 8, 8)
        path = Path(str(row.get("path") or ""))
        ext = path.suffix.lower()
        drawn = False
        if path.exists() and ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            pix = QPixmap(str(path))
            if not pix.isNull():
                inner = render_media_pixmap(
                    pix,
                    QSize(46, 36),
                    str(row.get("fit") or "contain"),
                    int(row.get("zoom", 100) or 100),
                    int(row.get("panX", 0) or 0),
                    int(row.get("panY", 0) or 0),
                    int(row.get("rotation", 0) or 0),
                    bool(row.get("flipH", False)),
                    bool(row.get("flipV", False)),
                )
                painter.drawPixmap(5, 6, inner)
                drawn = True
        if not drawn:
            painter.setPen(QColor("#eaf6ff"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(5, 7, 46, 30), Qt.AlignmentFlag.AlignCenter, "VÍDEO" if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"} else "MEDIA")
        painter.setPen(QColor("#eaf6ff"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        label = str(row.get("name") or path.stem or "CAPA")[:12]
        painter.drawText(QRectF(4, 41, 48, 11), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return QIcon(canvas)

    def _refresh_splash_layer_list(self, keep_selection=False):
        if not hasattr(self,"ap_splash_layers"): return
        current=""
        if keep_selection and self.ap_splash_layers.currentItem(): current=str(self.ap_splash_layers.currentItem().data(Qt.ItemDataRole.UserRole) or "")
        self.ap_splash_layers.blockSignals(True); self.ap_splash_layers.clear()
        for row in sorted(getattr(self,"_splash_media_items_edit",[]),key=lambda x:int(x.get("z",0)),reverse=True):
            label=str(row.get("name") or Path(str(row.get("path") or "MEDIA")).stem or "MEDIA")
            item=QListWidgetItem(self._make_splash_layer_icon(row), f"{label}   ·   {str(row.get('animation') or 'none')}")
            item.setData(Qt.ItemDataRole.UserRole,str(row.get("id") or ""))
            item.setToolTip(str(row.get("path") or ""))
            self.ap_splash_layers.addItem(item)
            if current and current==item.data(Qt.ItemDataRole.UserRole): self.ap_splash_layers.setCurrentItem(item)
        self.ap_splash_layers.blockSignals(False)
        if self.ap_splash_layers.count() and self.ap_splash_layers.currentRow()<0: self.ap_splash_layers.setCurrentRow(0)

    def _find_splash_layer(self, ident: str):
        for row in getattr(self,"_splash_media_items_edit",[]):
            if str(row.get("id"))==str(ident): return row
        return None

    def _selected_splash_layer_id(self) -> str:
        if hasattr(self,"ap_splash_layers") and self.ap_splash_layers.currentItem():
            return str(self.ap_splash_layers.currentItem().data(Qt.ItemDataRole.UserRole) or "")
        if hasattr(self, "ap_splash_canvas"):
            key = str(self.ap_splash_canvas.selected_key() or "")
            if key.startswith("asset:"):
                return key.split(":", 1)[1]
        return ""

    def _select_splash_layer_by_id(self, ident: str):
        if not hasattr(self,"ap_splash_layers"): return
        for i in range(self.ap_splash_layers.count()):
            item=self.ap_splash_layers.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole) or "")==str(ident): self.ap_splash_layers.setCurrentItem(item); break
        if hasattr(self,"ap_splash_canvas"):
            key=f"asset:{ident}"
            if key in self.ap_splash_canvas.items: self.ap_splash_canvas._select_key(key)

    def _on_splash_layer_list_selected(self,current,previous=None):
        if not current:
            if hasattr(self, "ap_splash_selected_info"):
                self.ap_splash_selected_info.setText("Sin capa seleccionada")
            return
        ident=str(current.data(Qt.ItemDataRole.UserRole) or ""); row=self._find_splash_layer(ident)
        if not row: return
        for widget in (self.ap_layer_fit, self.ap_layer_animation): widget.blockSignals(True)
        for widget in (self.ap_layer_posx, self.ap_layer_posy, self.ap_layer_width, self.ap_layer_height, self.ap_layer_opacity, self.ap_layer_zoom, self.ap_layer_panx, self.ap_layer_pany, self.ap_layer_rotation): widget.blockSignals(True)
        self.ap_layer_flip_h.blockSignals(True); self.ap_layer_flip_v.blockSignals(True)
        self._combo_select_data(self.ap_layer_fit,row.get("fit","contain")); self._combo_select_data(self.ap_layer_animation,row.get("animation","none"))
        self.ap_layer_posx.setText(str(int(round(float(row.get("x",0.08))*100))))
        self.ap_layer_posy.setText(str(int(round(float(row.get("y",0.10))*100))))
        self.ap_layer_width.setText(str(int(round(float(row.get("w",0.28))*100))))
        self.ap_layer_height.setText(str(int(round(float(row.get("h",0.42))*100))))
        self.ap_layer_opacity.setText(str(int(row.get("opacity",100))))
        self.ap_layer_zoom.setText(str(int(row.get("zoom",100))))
        self.ap_layer_panx.setText(str(int(row.get("panX",0))))
        self.ap_layer_pany.setText(str(int(row.get("panY",0))))
        self.ap_layer_rotation.setText(str(int(row.get("rotation",0)) % 360))
        self.ap_layer_flip_h.setChecked(bool(row.get("flipH",False)))
        self.ap_layer_flip_v.setChecked(bool(row.get("flipV",False)))
        for widget in (self.ap_layer_fit, self.ap_layer_animation): widget.blockSignals(False)
        for widget in (self.ap_layer_posx, self.ap_layer_posy, self.ap_layer_width, self.ap_layer_height, self.ap_layer_opacity, self.ap_layer_zoom, self.ap_layer_panx, self.ap_layer_pany, self.ap_layer_rotation): widget.blockSignals(False)
        self.ap_layer_flip_h.blockSignals(False); self.ap_layer_flip_v.blockSignals(False)
        if hasattr(self, "ap_splash_selected_info"):
            layer_name = str(row.get("name") or Path(str(row.get("path") or "MEDIA")).stem or "MEDIA")
            self.ap_splash_selected_info.setText(f"Editando: {layer_name}")
        if hasattr(self, "ap_splash_canvas_status"):
            self.ap_splash_canvas_status.setText(f"X: {int(round(float(row.get('x',0))*100))}% · Y: {int(round(float(row.get('y',0))*100))}% · W: {int(round(float(row.get('w',0))*100))}% · H: {int(round(float(row.get('h',0))*100))}%")
        if hasattr(self,"ap_splash_canvas"):
            key=f"asset:{ident}"
            if key in self.ap_splash_canvas.items: self.ap_splash_canvas._select_key(key)

    def _on_splash_canvas_selection(self,key: str):
        key = str(key or "")
        if key.startswith("asset:"):
            self._select_splash_layer_by_id(key.split(":",1)[1])
            return
        if hasattr(self, "ap_splash_layers"):
            self.ap_splash_layers.blockSignals(True)
            self.ap_splash_layers.clearSelection()
            self.ap_splash_layers.setCurrentRow(-1)
            self.ap_splash_layers.blockSignals(False)
        if hasattr(self, "ap_splash_selected_info"):
            friendly = {
                "logo": "Logo oficial",
                "title": "Título",
                "subtitle": "Subtítulo",
                "progress": "Barra de progreso",
                "status": "Estado",
            }.get(key, key.upper())
            hint = f"Elemento fijo: {friendly}"
            if key == "logo":
                hint += " · usa 'Eliminar' para ocultarlo"
            self.ap_splash_selected_info.setText(hint)
        if hasattr(self, "ap_splash_canvas_status"):
            self.ap_splash_canvas_status.setText("Elemento fijo del splash")

    def _update_selected_splash_layer_properties(self,*_):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        row["fit"]=str(self.ap_layer_fit.currentData() or "contain")
        row["animation"]=str(self.ap_layer_animation.currentData() or "none")
        def _percent_value(edit, default, min_value=0, max_value=100):
            try:
                value = int(edit.text() or default)
            except Exception:
                value = default
            value = max(min_value, min(max_value, value))
            edit.setText(str(value))
            return value / 100.0
        row["x"]=_percent_value(self.ap_layer_posx, 8)
        row["y"]=_percent_value(self.ap_layer_posy, 10)
        row["w"]=_percent_value(self.ap_layer_width, 28, 1, 100)
        row["h"]=_percent_value(self.ap_layer_height, 42, 1, 100)
        try: row["opacity"]=max(10,min(100,int(self.ap_layer_opacity.text() or 100)))
        except Exception: row["opacity"]=100
        try: row["zoom"]=max(10,min(400,int(self.ap_layer_zoom.text() or 100)))
        except Exception: row["zoom"]=100
        try: row["panX"]=max(-200,min(200,int(self.ap_layer_panx.text() or 0)))
        except Exception: row["panX"]=0
        try: row["panY"]=max(-200,min(200,int(self.ap_layer_pany.text() or 0)))
        except Exception: row["panY"]=0
        try: row["rotation"]=max(0,min(359,int(self.ap_layer_rotation.text() or 0)))
        except Exception: row["rotation"]=0
        row["flipH"]=self.ap_layer_flip_h.isChecked()
        row["flipV"]=self.ap_layer_flip_v.isChecked()
        if hasattr(self, "ap_splash_canvas_status"):
            self.ap_splash_canvas_status.setText(f"X: {int(round(float(row.get('x',0))*100))}% · Y: {int(round(float(row.get('y',0))*100))}% · W: {int(round(float(row.get('w',0))*100))}% · H: {int(round(float(row.get('h',0))*100))}%")
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def duplicate_startup_layer(self):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        new=json.loads(json.dumps(row)); new["id"]=self._next_splash_layer_id(); new["name"]=str(row.get("name") or "MEDIA")+" copia"; new["x"]=min(.9,float(row.get("x",.1))+.03); new["y"]=min(.9,float(row.get("y",.1))+.03); new["z"]=max([int(x.get("z",0)) for x in self._splash_media_items_edit]+[0])+1
        self._splash_media_items_edit.append(new); self._refresh_splash_editor(); self._select_splash_layer_by_id(new["id"])

    def remove_startup_layer(self):
        ident=self._selected_splash_layer_id()
        if ident:
            self._splash_media_items_edit=[x for x in self._splash_media_items_edit if str(x.get("id"))!=ident]
            self._refresh_splash_editor()
            if hasattr(self, "ap_status"):
                self.ap_status.setText("Capa eliminada del splash.")
            return
        canvas_key = str(self.ap_splash_canvas.selected_key() if hasattr(self, "ap_splash_canvas") else "")
        if canvas_key == "logo" and hasattr(self, "ap_startup_logo"):
            self.ap_startup_logo.setChecked(False)
            self._refresh_splash_presentation()
            if hasattr(self, "ap_splash_selected_info"):
                self.ap_splash_selected_info.setText("Logo oculto del splash")
            if hasattr(self, "ap_splash_canvas_status"):
                self.ap_splash_canvas_status.setText("El logo oficial está oculto")
            if hasattr(self, "ap_status"):
                self.ap_status.setText("Logo oficial ocultado del splash.")

    def move_startup_layer(self,direction:int):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        ordered=sorted(self._splash_media_items_edit,key=lambda x:int(x.get("z",0)))
        try: i=ordered.index(row)
        except ValueError: return
        j=max(0,min(len(ordered)-1,i+(1 if direction>0 else -1)))
        if i==j:return
        ordered[i],ordered[j]=ordered[j],ordered[i]
        for z,item in enumerate(ordered,1): item["z"]=z
        self._splash_media_items_edit=ordered; self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def center_selected_splash_layer(self):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        row["x"] = round((1.0 - float(row.get("w", 0.28))) / 2, 4)
        row["y"] = round((1.0 - float(row.get("h", 0.42))) / 2, 4)
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def fill_selected_splash_layer(self):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        row.update({"x":0.0,"y":0.0,"w":1.0,"h":1.0})
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def reset_selected_splash_layer_transform(self):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        row.update({"zoom":100,"panX":0,"panY":0,"rotation":0,"flipH":False,"flipV":False})
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def nudge_selected_splash_layer(self, dx_percent: int, dy_percent: int):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        row["x"] = max(0.0, min(1.0 - float(row.get("w", 0.28)), float(row.get("x", 0.08)) + (dx_percent / 100.0)))
        row["y"] = max(0.0, min(1.0 - float(row.get("h", 0.42)), float(row.get("y", 0.10)) + (dy_percent / 100.0)))
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def resize_selected_splash_layer(self, dw_percent: int, dh_percent: int):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        new_w = max(0.05, min(1.0 - float(row.get("x", 0.08)), float(row.get("w", 0.28)) + (dw_percent / 100.0)))
        new_h = max(0.05, min(1.0 - float(row.get("y", 0.10)), float(row.get("h", 0.42)) + (dh_percent / 100.0)))
        row["w"] = new_w
        row["h"] = new_h
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def toggle_selected_splash_layer_flip(self, horizontal: bool = True):
        ident=self._selected_splash_layer_id(); row=self._find_splash_layer(ident)
        if not row: return
        if horizontal:
            row["flipH"] = not bool(row.get("flipH", False))
        else:
            row["flipV"] = not bool(row.get("flipV", False))
        self._refresh_splash_editor(); self._select_splash_layer_by_id(ident)

    def select_startup_media(self):
        # Compatibilidad con versiones anteriores: redirige al nuevo selector múltiple.
        self.add_startup_images()

    def clear_startup_media(self):
        self._splash_media_items_edit=[]
        if hasattr(self,"ap_startup_media"): self.ap_startup_media.setText("")
        self._refresh_splash_editor()

    def select_startup_audio(self):
        filename,_=QFileDialog.getOpenFileName(self,"Audio para pantalla de inicio",str(Path.home()),"Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;Todos (*.*)")
        if not filename: return
        try:
            self.ap_startup_audio.setText(self._copy_startup_asset(filename,"startup_audio")); self.ap_status.setText("Audio del splash copiado a AppData.")
        except Exception as exc: QMessageBox.critical(self,"Splash Studio",str(exc))

    def clear_startup_audio(self):
        if hasattr(self,"ap_startup_audio"): self.ap_startup_audio.setText("")

    def reset_splash_layout(self):
        self._splash_layout_edit=json.loads(json.dumps(default_appearance()["startupLayout"])); self._splash_media_items_edit=[]
        self._refresh_splash_editor()

    def test_startup_splash(self):
        cfg=self._startup_form_config(); cfg["startupSplashEnabled"]=True
        preview=StartupSplashWindow(cfg); self._startup_preview_window=preview; preview.show(); preview.set_progress(8,"Preparando vista previa…")
        steps=[(350,28,"Cargando configuración…"),(750,52,"Iniciando servicios…"),(1200,76,"Preparando interfaz…"),(1700,94,"Conectando módulos…"),(2200,100,"Listo")]
        for delay,value,text in steps: QTimer.singleShot(delay,lambda v=value,t=text,w=preview: w.set_progress(v,t) if w.isVisible() else None)
        QTimer.singleShot(3000,lambda w=preview: w.close() if w.isVisible() else None)

    def apply_startup_preset(self):
        if not hasattr(self,"ap_startup_preset"): return
        key=str(self.ap_startup_preset.currentData() or "neon")
        profile=visual_style_profile(key)
        self.ap_startup_bg.setText(str(profile.get("bg") or "#080b12"))
        progress_map={"halloween":"halloween","arcade":"arcade","candy":"candy","retro":"segmented","minimal":"minimal","sakura":"candy","sunset":"rainbow"}
        self._combo_select_data(self.ap_startup_progress_style,progress_map.get(key,"neon"))
        self._refresh_splash_editor()

    def select_update_media(self):
        filename,_=QFileDialog.getOpenFileName(self,"Imagen o GIF para actualizaciones",str(Path.home()),"Imagen / GIF (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Todos (*.*)")
        if not filename: return
        try:
            self.ap_update_media.setText(self._copy_startup_asset(filename,"update_media")); self.ap_status.setText("Media del actualizador copiado a AppData.")
        except Exception as exc: QMessageBox.critical(self,"Actualizaciones",str(exc))

    def test_update_dialog(self):
        cfg=default_appearance(); cfg.update(self._appearance_from_form())
        dialog=IntegratedUpdateDialog(self,cfg); dialog.setModal(False); dialog.show(); self._update_preview_dialog=dialog
        steps=[(250,12,"Preparando copia de seguridad…"),(650,35,"Comprobando componentes…"),(1050,58,"Instalando archivos…"),(1450,82,"Aplicando personalización…"),(1850,100,"Actualización preparada")]
        for delay,value,text in steps: QTimer.singleShot(delay,lambda v=value,t=text,d=dialog: d.set_progress(v,t) if d.isVisible() else None)
        QTimer.singleShot(2050,lambda d=dialog: d.complete(True,"Vista previa terminada.") if d.isVisible() else None)

    def _pick_color(self, target: QLineEdit):
        initial = QColor(target.text()) if normalize_hex_color(target.text()) else QColor("#76ff6a")
        color = QColorDialog.getColor(initial, self, "Elegir color")
        if color.isValid():
            target.setText(color.name())

    def _number_from_input(self, edit: QLineEdit) -> int:
        default = int(edit.property("defaultValue") or 0)
        minimum = int(edit.property("minValue") or -2147483648)
        maximum = int(edit.property("maxValue") or 2147483647)
        try:
            value = int(edit.text().strip())
        except Exception:
            value = default
        value = max(minimum, min(maximum, value))
        edit.setText(str(value))
        return value

    def _appearance_from_form(self) -> dict:
        return {
            "theme": self.ap_theme.currentData(),
            "accent": normalize_hex_color(self.ap_accent.text()),
            "accent2": normalize_hex_color(self.ap_accent2.text()),
            "fontFamily": self.ap_font.currentText().strip() or "Segoe UI",
            "density": self.ap_density.currentData(),
            "sidebarWidth": self._number_from_input(self.ap_sidebar),
            "uiScale": self._number_from_input(self.ap_scale),
            "webZoom": self._number_from_input(self.ap_webzoom),
            "brand": self.ap_brand.text().strip() or r"BRYNN\nINTERACTIVE",
            "showFooter": self.ap_footer.isChecked(),
            "showSidebarVersion": self.ap_sidebar_version.isChecked(),
            "showTitleVersion": self.ap_title_version.isChecked(),
            "titlebarStyle": self.ap_titlebar.currentData(),
            "titlebarHeight": self._number_from_input(self.ap_titlebar_height),
            "menuStyle": self.ap_menu_style.currentData(),
            "windowFrameStyle": self.ap_window_style.currentData() if hasattr(self, "ap_window_style") else "soft",
            "panelRadius": self._number_from_input(self.ap_radius),
            "loadingType": self.ap_loading_type.currentData() if hasattr(self, "ap_loading_type") else "circle",
            "loadingImage": self.ap_loading_image.text().strip() if hasattr(self, "ap_loading_image") else "",
            "loadingEmoteId": self.ap_loading_emote.currentData() if hasattr(self, "ap_loading_emote") else "",
            "loadingSize": self._number_from_input(self.ap_loading_size) if hasattr(self, "ap_loading_size") else 72,
            "loadingMinMs": self._number_from_input(self.ap_loading_min_ms) if hasattr(self, "ap_loading_min_ms") else 320,
            "loadingText": self.ap_loading_text.text().strip() if hasattr(self, "ap_loading_text") else "Cargando módulo…",
            "loadingShowText": self.ap_loading_show_text.isChecked() if hasattr(self, "ap_loading_show_text") else True,
            "loadingBackdrop": self.ap_loading_backdrop.isChecked() if hasattr(self, "ap_loading_backdrop") else True,
            "loadingBackdropOpacity": self._number_from_input(self.ap_loading_opacity) if hasattr(self, "ap_loading_opacity") else 82,
            "startupSplashEnabled": self.ap_startup_enabled.isChecked() if hasattr(self, "ap_startup_enabled") else True,
            "startupSplashMinMs": self._number_from_input(self.ap_startup_min_ms) if hasattr(self, "ap_startup_min_ms") else 1200,
            "startupTitle": self.ap_startup_title.text().strip() if hasattr(self, "ap_startup_title") else "BRYNN INTERACTIVE",
            "startupSubtitle": self.ap_startup_subtitle.text().strip() if hasattr(self, "ap_startup_subtitle") else "Preparando tu centro de control…",
            "startupShowLogo": self.ap_startup_logo.isChecked() if hasattr(self, "ap_startup_logo") else True,
            "startupMediaPath": self.ap_startup_media.text().strip() if hasattr(self, "ap_startup_media") else "",
            "startupAudioPath": self.ap_startup_audio.text().strip() if hasattr(self, "ap_startup_audio") else "",
            "startupAudioVolume": self._number_from_input(self.ap_startup_volume) if hasattr(self, "ap_startup_volume") else 55,
            "startupBackground": normalize_hex_color(self.ap_startup_bg.text()) if hasattr(self, "ap_startup_bg") else "#080b12",
            "startupPreset": self.ap_startup_preset.currentData() if hasattr(self, "ap_startup_preset") else "neon",
            "startupProgressStyle": self.ap_startup_progress_style.currentData() if hasattr(self, "ap_startup_progress_style") else "neon",
            "startupMediaItems": json.loads(json.dumps(getattr(self, "_splash_media_items_edit", []))),
            "startupLayout": json.loads(json.dumps(getattr(self, "_splash_layout_edit", default_appearance()["startupLayout"]))),
            "updateStylePreset": self.ap_update_preset.currentData() if hasattr(self, "ap_update_preset") else "match",
            "updateProgressStyle": self.ap_update_progress.currentData() if hasattr(self, "ap_update_progress") else "neon",
            "updateShowTechnicalLog": self.ap_update_log.isChecked() if hasattr(self, "ap_update_log") else False,
            "updateTitle": self.ap_update_title.text().strip() if hasattr(self, "ap_update_title") else "Actualizando Brynn Interactive",
            "updateShowLogo": self.ap_update_logo.isChecked() if hasattr(self, "ap_update_logo") else True,
            "updateBackground": normalize_hex_color(self.ap_update_bg.text()) if hasattr(self, "ap_update_bg") else "",
            "updateMediaPath": self.ap_update_media.text().strip() if hasattr(self, "ap_update_media") else "",
            "appIconPath": self.ap_icon_path.text().strip() if hasattr(self, "ap_icon_path") else str(self.appearance.get("appIconPath") or ""),
        }

    def _refresh_personalization_preview(self, *_):
        if not hasattr(self, "ap_preview"):
            return
        theme = self.ap_theme.currentData() or "neon"
        accent = normalize_hex_color(self.ap_accent.text())
        accent2 = normalize_hex_color(self.ap_accent2.text())
        p = self._native_palette(theme=theme, accent=accent, accent2=accent2)
        brand = self.ap_brand.text().strip() or r"BRYNN\nINTERACTIVE"
        self.ap_preview_brand.setText(brand.replace(r"\n", "\n"))
        self.ap_preview_title.setText(self.ap_theme.currentText() or "Vista previa")
        self.ap_preview_text.setText(
            f"{self.ap_font.currentText() or 'Segoe UI'} · "
            f"{self.ap_density.currentText()} · {self.ap_menu_style.currentText()}"
        )
        radius = max(8, min(24, self._number_from_input(self.ap_radius) if hasattr(self, 'ap_radius') else 14))
        self.ap_preview.setStyleSheet(
            f"QFrame#appearancePreview{{background:{p['window']};border:1px solid {p['muted']}30;border-radius:{radius}px;}}"
        )
        self.ap_preview_side.setStyleSheet(
            f"QFrame#appearancePreviewSide{{background:{p['sidebar1']};border:1px solid {p['muted']}28;border-radius:{max(7,radius-2)}px;}}"
        )
        self.ap_preview_content.setStyleSheet(
            f"QFrame#appearancePreviewContent{{background:{p['panel1']};border:1px solid {p['muted']}28;border-radius:{max(7,radius-2)}px;}}"
        )
        self.ap_preview_brand.setStyleSheet(f"color:{p['title']};font-weight:800;background:transparent;")
        self.ap_preview_title.setStyleSheet(f"color:{p['accent2']};font-weight:800;background:transparent;")
        self.ap_preview_text.setStyleSheet(f"color:{p['muted']};background:transparent;")

    def export_appearance_profile(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar apariencia",
            str(Path.home() / "BrynnAppearance.json"),
            "Perfil de apariencia (*.json)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".json"):
            filename += ".json"
        try:
            payload = default_appearance()
            payload.update(self._appearance_from_form())
            payload["profileFormat"] = 1
            payload["exportedAt"] = datetime.now().isoformat()
            Path(filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.ap_status.setText("Perfil de apariencia exportado correctamente.")
        except Exception as exc:
            QMessageBox.critical(self, "Exportar apariencia", str(exc))

    def import_appearance_profile(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar apariencia",
            str(Path.home()),
            "Perfil de apariencia (*.json)",
        )
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("El archivo no contiene un perfil válido.")
            clean = default_appearance()
            for key in clean:
                if key in payload:
                    clean[key] = payload[key]
            self.appearance = save_appearance(clean)
            self.current_theme = str(self.appearance.get("theme") or "neon")
            self._load_personalization_form()
            self._apply_appearance_runtime()
            self._refresh_personalization_preview()
            self.ap_status.setText("Perfil importado y aplicado correctamente.")
        except Exception as exc:
            QMessageBox.critical(self, "Importar apariencia", f"No se pudo importar el perfil:\n{exc}")

    def save_personalization(self):
        accent = normalize_hex_color(self.ap_accent.text())
        accent2 = normalize_hex_color(self.ap_accent2.text())
        if self.ap_accent.text().strip() and not accent:
            QMessageBox.warning(self, "Color inválido", "El color principal debe tener formato #RRGGBB.")
            return
        if self.ap_accent2.text().strip() and not accent2:
            QMessageBox.warning(self, "Color inválido", "El color secundario debe tener formato #RRGGBB.")
            return
        form_data = self._appearance_from_form()
        form_data["accent"] = accent
        form_data["accent2"] = accent2
        self.appearance = save_appearance(form_data)
        self.current_theme = self.appearance.get("theme", "neon")
        self._apply_appearance_runtime()
        if hasattr(self, "ap_preview_brand"):
            self.ap_preview_brand.setText(str(self.appearance.get("brand") or r"BRYNN\nINTERACTIVE").replace(r"\n", "\n"))
        self._refresh_personalization_preview()
        self.ap_status.setText("Cambios guardados y aplicados. La apariencia se conservará en futuras versiones.")

    def reset_personalization(self):
        if QMessageBox.question(self, "Restablecer apariencia", "¿Volver a la apariencia Neon predeterminada?") != QMessageBox.StandardButton.Yes:
            return
        self.appearance = save_appearance(default_appearance())
        self.current_theme = "neon"
        self._load_personalization_form()
        self._apply_appearance_runtime()
        self.create_or_refresh_desktop_shortcut(silent=True)
        self.ap_status.setText("Apariencia predeterminada restaurada.")

    def open_personalization(self):
        self._select_nav_key("personalization")
        self._activate_route("personalization", force=True)

    def _reload_web_theme(self):
        if self.stack.currentWidget() is not self.web_host:
            return
        key = getattr(self, "_active_route", None)
        if isinstance(key, str) and ".html" in key:
            self._activate_route(key, force=True)

    def _apply_appearance_runtime(self):
        self.current_theme = str(self.appearance.get("theme") or "neon")
        self.web_view.setZoomFactor(float(self.appearance.get("webZoom", 95)) / 100.0)
        if getattr(self, "pending_web_view", None) is not None:
            self.pending_web_view.setZoomFactor(float(self.appearance.get("webZoom", 95)) / 100.0)
        if hasattr(self, "loading_overlay"):
            self._configure_loading_overlay()
        if hasattr(self, "brand_label"):
            self.brand_label.setText(str(self.appearance.get("brand") or r"BRYNN\nINTERACTIVE").replace(r"\n", "\n"))
        if hasattr(self, "sidebar") and hasattr(self, "nav_state"):
            self._apply_sidebar_mode()
        elif hasattr(self, "sidebar"):
            self.sidebar.setFixedWidth(int(self.appearance.get("sidebarWidth", 250)))
        if hasattr(self, "version_label") and not bool(getattr(self, "nav_state", {}).get("compact", False)):
            self.version_label.setVisible(bool(self.appearance.get("showSidebarVersion", True)))
        if hasattr(self, "title_bar") and hasattr(self.title_bar, "version_label"):
            self.title_bar.version_label.setVisible(bool(self.appearance.get("showTitleVersion", True)))
        if hasattr(self, "footer"):
            self.footer.setVisible(bool(self.appearance.get("showFooter", True)))
        self._apply_app_icon()
        self._apply_style()
        self._reload_web_theme()

    def _native_palette(self, theme: str | None = None, accent: str | None = None, accent2: str | None = None):
        palettes = {
            "neon": {
                "window":"#080a10","sidebar1":"#0f1220","sidebar2":"#090b11","panel1":"#121826","panel2":"#0c101a","text":"#eef3ff","muted":"#95a6c0","accent":"#76ff6a","accent2":"#53e6ff","title":"#fff4df","input":"#090d15","danger":"#ff637d"
            },
            "spooky": {
                "window":"#0b0710","sidebar1":"#160d1d","sidebar2":"#0d0912","panel1":"#1a1021","panel2":"#100b16","text":"#f8eee2","muted":"#b09ab8","accent":"#ff8a2a","accent2":"#b06cff","title":"#fff1da","input":"#0c0810","danger":"#ff637d"
            },
            "day": {
                "window":"#eef3f8","sidebar1":"#f9fbfd","sidebar2":"#e6edf4","panel1":"#ffffff","panel2":"#f4f7fa","text":"#182130","muted":"#64748b","accent":"#187a5d","accent2":"#5b54c5","title":"#111827","input":"#ffffff","danger":"#b4233a"
            },
            "cyber": {
                "window":"#041015","sidebar1":"#071b22","sidebar2":"#051017","panel1":"#0b2028","panel2":"#07171e","text":"#e8fcff","muted":"#80aab3","accent":"#00f5d4","accent2":"#00bbf9","title":"#efffff","input":"#051319","danger":"#ff4d7d"
            },
            "amber": {
                "window":"#100c07","sidebar1":"#1b1309","sidebar2":"#0f0a06","panel1":"#21170c","panel2":"#150f08","text":"#fff3df","muted":"#baa68b","accent":"#ffb000","accent2":"#ff7a00","title":"#fff8e8","input":"#110c07","danger":"#ff4e4e"
            },
            "violet": {
                "window":"#0a0712","sidebar1":"#171025","sidebar2":"#0c0914","panel1":"#1b1330","panel2":"#100c1d","text":"#f3efff","muted":"#a99bc2","accent":"#b56cff","accent2":"#ff55d8","title":"#fff2ff","input":"#0c0915","danger":"#ff5d7d"
            },
            "mono": {
                "window":"#080b09","sidebar1":"#0d120f","sidebar2":"#070a08","panel1":"#121714","panel2":"#0a0e0c","text":"#dfffe7","muted":"#7fa88a","accent":"#70ff8f","accent2":"#b7ffc6","title":"#effff2","input":"#060907","danger":"#ff5d6c"
            },
            "graphite": {
                "window":"#111318","sidebar1":"#161920","sidebar2":"#101218","panel1":"#1b1f27","panel2":"#15181f","text":"#eef1f5","muted":"#9ba3ad","accent":"#9fc6ff","accent2":"#c1cad8","title":"#ffffff","input":"#12151b","danger":"#e9687a"
            },
            "ocean": {
                "window":"#071116","sidebar1":"#0b1b23","sidebar2":"#081219","panel1":"#102630","panel2":"#0a1a22","text":"#eafaff","muted":"#88adb9","accent":"#45d6c7","accent2":"#66b9ff","title":"#f1fdff","input":"#07151b","danger":"#ff6f87"
            },
            "rose": {
                "window":"#120b11","sidebar1":"#1c111a","sidebar2":"#10090f","panel1":"#251720","panel2":"#180f16","text":"#fff2f7","muted":"#c19eae","accent":"#ff7aa8","accent2":"#d99cff","title":"#fff7fb","input":"#130b11","danger":"#ff526e"
            },
            "crimson": {
                "window":"#10090b","sidebar1":"#1a0d11","sidebar2":"#0d0809","panel1":"#241218","panel2":"#160c10","text":"#fff0f1","muted":"#bc989d","accent":"#ff5f6d","accent2":"#ffae62","title":"#fff7f2","input":"#12090c","danger":"#ff435a"
            },
            "sakura": {
                "window":"#170d16","sidebar1":"#241321","sidebar2":"#120b13","panel1":"#2a1725","panel2":"#1d101a","text":"#fff5f8","muted":"#d0a8b8","accent":"#ff8fbd","accent2":"#c6a2ff","title":"#fff9fc","input":"#130b12","danger":"#ff5f79"
            },
            "candy": {
                "window":"#17101d","sidebar1":"#261630","sidebar2":"#130c18","panel1":"#2d1835","panel2":"#211328","text":"#fff8ff","muted":"#d5b7d8","accent":"#7ef5ff","accent2":"#ff91cf","title":"#ffffff","input":"#160d1b","danger":"#ff6b89"
            },
            "arcade": {
                "window":"#090413","sidebar1":"#130922","sidebar2":"#05020b","panel1":"#160c2a","panel2":"#0e071b","text":"#fff8ff","muted":"#aaa1c6","accent":"#b7ff35","accent2":"#ff4fd8","title":"#ffffff","input":"#080410","danger":"#ff405e"
            },
            "matrix": {
                "window":"#020805","sidebar1":"#06110a","sidebar2":"#010503","panel1":"#09160d","panel2":"#051008","text":"#d8ffe1","muted":"#74a87f","accent":"#6cff79","accent2":"#c4ff6b","title":"#effff2","input":"#030906","danger":"#ff5b68"
            },
            "sunset": {
                "window":"#150911","sidebar1":"#25101b","sidebar2":"#0f0710","panel1":"#2d1321","panel2":"#1e0d18","text":"#fff4e8","muted":"#c6a39f","accent":"#ffb34f","accent2":"#ff5d8f","title":"#fff8ee","input":"#130910","danger":"#ff4e6d"
            },
            "ice": {
                "window":"#071019","sidebar1":"#0c1924","sidebar2":"#050b11","panel1":"#102233","panel2":"#0a1722","text":"#effaff","muted":"#9fb6c5","accent":"#a6efff","accent2":"#79a9ff","title":"#ffffff","input":"#07121b","danger":"#ff738b"
            },
            "coffee": {
                "window":"#120d0a","sidebar1":"#1d1510","sidebar2":"#0d0907","panel1":"#271b14","panel2":"#19110d","text":"#f8eee4","muted":"#b9a494","accent":"#d6a66f","accent2":"#83c9b8","title":"#fff7ef","input":"#100b08","danger":"#e66b70"
            },
        }
        selected_theme = theme or self.current_theme
        p = dict(palettes.get(selected_theme, palettes["neon"]))
        selected_accent = normalize_hex_color(accent if accent is not None else self.appearance.get("accent"))
        selected_accent2 = normalize_hex_color(accent2 if accent2 is not None else self.appearance.get("accent2"))
        if selected_accent:
            p["accent"] = selected_accent
        if selected_accent2:
            p["accent2"] = selected_accent2
        return p

    def _make_update_manager(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)

        title = QLabel("Gestor de actualizaciones")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Importa un ZIP o un instalador EXE de una nueva versión. Brynn crea un backup antes de actualizar y conserva tus datos persistentes."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        info = QFrame()
        info.setObjectName("panel")
        form = QFormLayout(info)
        form.setContentsMargins(18, 18, 18, 18)
        self.update_current = QLabel(APP_VERSION_LABEL)
        self.update_previous = QLabel("—")
        self.update_last = QLabel("—")
        self.update_path = QLabel(str(UPDATES_DIR))
        self.update_path.setWordWrap(True)
        form.addRow("Versión actual", self.update_current)
        form.addRow("Versión anterior", self.update_previous)
        form.addRow("Última migración", self.update_last)
        form.addRow("Paquetes preparados", self.update_path)
        layout.addWidget(info)

        actions = QHBoxLayout()
        select_btn = QPushButton("Seleccionar actualización ZIP / EXE")
        select_btn.clicked.connect(self.select_update_package)
        self.install_update_btn = QPushButton("Instalar paquete preparado")
        self.install_update_btn.setEnabled(False)
        self.install_update_btn.clicked.connect(self.install_staged_update)
        open_btn = QPushButton("Abrir carpeta updates")
        open_btn.clicked.connect(lambda: self.open_folder(UPDATES_DIR))
        refresh_btn = QPushButton("Actualizar historial")
        refresh_btn.clicked.connect(self.refresh_update_manager)
        for btn in (select_btn, self.install_update_btn, open_btn, refresh_btn):
            actions.addWidget(btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.update_status = QLabel("Selecciona un paquete cuando quieras actualizar.")
        self.update_status.setObjectName("tip")
        self.update_status.setWordWrap(True)
        layout.addWidget(self.update_status)

        history_title = QLabel("Historial de versiones y migraciones")
        history_title.setObjectName("sectionTitle")
        layout.addWidget(history_title)

        self.update_history = QPlainTextEdit()
        self.update_history.setReadOnly(True)
        layout.addWidget(self.update_history, 1)

        QTimer.singleShot(250, self.refresh_update_manager)
        return page

    def refresh_update_manager(self):
        state = load_json_file(DESKTOP_STATE_FILE, {})
        self.update_current.setText(APP_VERSION_LABEL)
        self.update_previous.setText(str(state.get("previousVersion") or "Primera versión registrada"))
        self.update_last.setText(str(state.get("lastUpdateAt") or "—"))

        lines = []
        lines.append(f"VERSIÓN ACTUAL: {APP_VERSION_LABEL}")
        lines.append(f"DATOS: {DATA_DIR}")
        lines.append(f"MEDIA: {MEDIA_DIR}")
        lines.append(f"APARIENCIA: {APPEARANCE_FILE}")
        lines.append("")
        lines.append("HISTORIAL DE VERSIONES")
        lines.append("=" * 58)

        history = state.get("versionHistory") or []
        if not history:
            lines.append("Sin actualizaciones registradas todavía.")
        else:
            for row in reversed(history[-20:]):
                lines.append(
                    f"{row.get('at','')}  {row.get('from') or 'primera'} -> {row.get('to')}"
                )
                if row.get("backup"):
                    lines.append(f"  backup: {row.get('backup')}")

        lines.append("")
        lines.append("MIGRACIONES")
        lines.append("=" * 58)
        migrations = state.get("migrationHistory") or []
        if not migrations:
            lines.append("Sin migraciones registradas.")
        else:
            for row in reversed(migrations[-20:]):
                lines.append(f"{row.get('at','')}  {row.get('version','')}")
                for migration in row.get("migrations") or []:
                    lines.append(f"  ✓ {migration}")

        self.update_history.setPlainText("\n".join(lines))

    def _read_update_manifest(self, zip_path: Path) -> tuple[dict, str]:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            candidates = [n for n in names if n.endswith("update_manifest.json")]
            if not candidates:
                raise ValueError("El ZIP no contiene update_manifest.json")

            # Preferir manifiesto más cercano a la raíz.
            manifest_name = sorted(candidates, key=lambda n: (n.count("/"), len(n)))[0]
            manifest = json.loads(z.read(manifest_name).decode("utf-8"))

            if manifest.get("appId") != APP_ID:
                raise ValueError("El paquete no pertenece a Brynn Interactive Desktop.")

            version = str(manifest.get("version") or "").strip()
            if not version:
                raise ValueError("El manifiesto no contiene una versión válida.")

            root_prefix = manifest_name.rsplit("/", 1)[0] + "/" if "/" in manifest_name else ""
            return manifest, root_prefix

    def select_update_package(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar actualización de Brynn Interactive",
            str(Path.home()),
            "Actualizaciones Brynn (*.zip *.exe);;Paquetes ZIP (*.zip);;Instaladores EXE (*.exe)",
        )
        if not filename:
            return

        source_path = Path(filename)

        try:
            if source_path.suffix.lower() == ".exe":
                # Los instaladores comerciales generados por Brynn usan siempre
                # este nombre. El AppId estable de Inno Setup hace que el EXE
                # actualice la instalación existente en lugar de crear otra.
                match = re.match(
                    r"(?i)^BrynnInteractive-Setup-([0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?)\.exe$",
                    source_path.name,
                )
                if not match:
                    raise ValueError(
                        "El EXE no parece un instalador oficial de Brynn Interactive. "
                        "Debe llamarse BrynnInteractive-Setup-VERSION.exe."
                    )
                version = match.group(1)
                backup = create_data_backup(f"before_install_{version}")
                if backup is None:
                    raise RuntimeError("No se pudo crear el backup previo a la actualización.")

                target = STAGED_UPDATES_DIR / ("exe_" + re.sub(r"[^0-9A-Za-z._-]+", "_", version))
                active_runtime = Path(sys.executable).resolve()
                if target.exists():
                    try:
                        active_runtime.relative_to(target.resolve())
                        target = STAGED_UPDATES_DIR / (target.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
                    except ValueError:
                        try:
                            shutil.rmtree(target)
                        except PermissionError:
                            target = STAGED_UPDATES_DIR / (target.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
                target.mkdir(parents=True, exist_ok=True)
                installer = target / source_path.name
                shutil.copy2(source_path, installer)

                self.staged_update_dir = target
                self.staged_installer = installer
                self.staged_update_kind = "exe"
                self.install_update_btn.setEnabled(True)
                self.update_status.setText(
                    f"✅ Instalador EXE {version} preparado. Backup: {backup.name}. "
                    "Al instalar, si Brynn ya existe se actualizará en la misma carpeta y AppData se conservará."
                )
                return

            manifest, root_prefix = self._read_update_manifest(source_path)
            version = str(manifest["version"])

            backup = create_data_backup(f"before_install_{version}")
            if backup is None:
                raise RuntimeError("No se pudo crear el backup previo a la actualización.")

            target = STAGED_UPDATES_DIR / re.sub(r"[^0-9A-Za-z._-]+", "_", version)
            active_runtime = Path(sys.executable).resolve()
            if target.exists():
                try:
                    active_runtime.relative_to(target.resolve())
                    # Nunca borres la carpeta desde la que Brynn está ejecutándose.
                    target = STAGED_UPDATES_DIR / (target.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
                except ValueError:
                    try:
                        shutil.rmtree(target)
                    except PermissionError:
                        # Si Windows mantiene cualquier DLL bloqueado, usa un staging nuevo.
                        target = STAGED_UPDATES_DIR / (target.name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            target.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(source_path, "r") as z:
                for member in z.infolist():
                    name = member.filename
                    if root_prefix and not name.startswith(root_prefix):
                        continue
                    rel = name[len(root_prefix):] if root_prefix else name
                    if not rel:
                        continue
                    dest = (target / rel).resolve()
                    if target.resolve() not in dest.parents and dest != target.resolve():
                        raise ValueError("El ZIP contiene una ruta no segura.")
                    if member.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(member) as src, dest.open("wb") as out:
                            shutil.copyfileobj(src, out)

            installer = target / str(manifest.get("installer") or "instalar_desktop.bat")
            if not installer.exists():
                found = list(target.rglob("instalar_desktop.bat"))
                if found:
                    installer = found[0]
                else:
                    raise ValueError("No se encontró instalar_desktop.bat en el paquete.")

            self.staged_update_dir = target
            self.staged_installer = installer
            self.staged_update_kind = "zip"
            self.install_update_btn.setEnabled(True)
            self.update_status.setText(
                f"✅ {manifest.get('label') or version} preparado. Backup: {backup.name}. "
                "Pulsa 'Instalar paquete preparado' para actualizar dentro de Brynn sin abrir CMD."
            )
        except Exception as exc:
            self.staged_update_dir = None
            self.staged_installer = None
            self.staged_update_kind = None
            self.install_update_btn.setEnabled(False)
            QMessageBox.critical(self, "Actualización no válida", str(exc))

    def install_staged_update(self):
        if not self.staged_installer or not Path(self.staged_installer).exists():
            QMessageBox.warning(self, "Actualización", "No hay un paquete preparado.")
            return

        if QMessageBox.question(
            self,
            "Instalar actualización",
            "Brynn hará la actualización sin abrir CMD. Se conservarán AppData y el backup ya creado.\n\n¿Continuar?",
        ) != QMessageBox.StandardButton.Yes:
            return

        installer=Path(self.staged_installer)
        if os.name != "nt":
            try: subprocess.Popen([str(installer)],cwd=str(installer.parent)); self.exit_completely()
            except Exception as exc: QMessageBox.critical(self,"Actualización",str(exc))
            return

        # Instaladores EXE comerciales se ejecutan silenciosamente después de
        # cerrar Brynn, ya que Inno Setup necesita reemplazar el propio EXE.
        if installer.suffix.lower()==".exe":
            try:
                pid=os.getpid()
                args=[str(installer),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-"]
                # Un PowerShell oculto espera a que Brynn se cierre y después
                # ejecuta Inno Setup. No aparece CMD/PowerShell en pantalla.
                current_exe=str(Path(sys.executable)).replace("'","''")
                current_dir=str(Path(sys.executable).parent).replace("'","''")
                cmd=(f"Wait-Process -Id {pid}; Start-Process -FilePath '{str(installer).replace("'","''")}' "
                     "-ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-' -Wait; "
                     f"if (Test-Path '{current_exe}') {{ Start-Process -FilePath '{current_exe}' -WorkingDirectory '{current_dir}' }}")
                subprocess.Popen(["powershell.exe","-NoProfile","-WindowStyle","Hidden","-Command",cmd],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                self.update_status.setText("Actualización comercial preparada. Brynn se cerrará y el instalador continuará silenciosamente.")
                QTimer.singleShot(450,self.exit_completely)
            except Exception as exc: QMessageBox.critical(self,"Actualización",f"No se pudo iniciar la actualización silenciosa:\n{exc}")
            return

        ps1=installer.with_name("instalar_desktop.ps1")
        if not ps1.exists():
            QMessageBox.critical(self,"Actualización","El paquete no contiene instalar_desktop.ps1 para actualización integrada.")
            return

        dialog=IntegratedUpdateDialog(self,self.appearance)
        self._integrated_update_dialog=dialog
        signals=UpdateInstallSignals(); self._integrated_update_signals=signals
        signals.progress.connect(dialog.set_progress); signals.log.connect(dialog.append_log)

        result_holder={"restart":""}
        def done(ok,message,restart_path):
            result_holder["restart"]=restart_path or ""
            dialog.complete(ok,message)
            if ok:
                self.update_status.setText("✅ Actualización instalada. Pulsa Continuar para reiniciar Brynn.")
        signals.finished.connect(done)

        def worker():
            env=os.environ.copy(); env["BRYNN_UPDATE_MODE"]="1"
            args=["powershell.exe","-NoProfile","-WindowStyle","Hidden","-ExecutionPolicy","Bypass","-File",str(ps1)]
            flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
            progress=5
            mapping=[
                ("Python nativo detectado",12,"Python detectado"),
                ("Entorno virtual Windows: OK",24,"Runtime preparado"),
                ("Instalando PySide6",38,"Comprobando dependencias"),
                ("Comprobando Qt WebEngine",52,"Comprobando interfaz web"),
                ("Preparando ejecutable",66,"Compilando aplicación"),
                ("Build terminado",88,"Finalizando ejecutable"),
                ("EXE y acceso directo: OK",94,"Actualizando acceso directo"),
                ("INSTALACION COMPLETADA",100,"Actualización instalada"),
            ]
            try:
                signals.progress.emit(5,"Preparando actualización…")
                proc=subprocess.Popen(args,cwd=str(ps1.parent),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",env=env,creationflags=flags)
                for line in iter(proc.stdout.readline,'') if proc.stdout else []:
                    text=line.rstrip(); signals.log.emit(text)
                    for token,value,label in mapping:
                        if token.lower() in text.lower() and value>progress:
                            progress=value; signals.progress.emit(value,label); break
                code=proc.wait()
                candidate=ps1.parent / "dist" / "BrynnInteractiveDesktop" / "BrynnInteractiveDesktop.exe"
                if code==0 and candidate.exists(): signals.finished.emit(True,"Actualización terminada correctamente.",str(candidate))
                elif code==0: signals.finished.emit(False,"El instalador terminó pero no se encontró el nuevo ejecutable.","")
                else: signals.finished.emit(False,f"La actualización terminó con código {code}. Revisa el registro mostrado arriba.","")
            except Exception as exc:
                signals.finished.emit(False,f"No se pudo completar la actualización: {exc}","")
        threading.Thread(target=worker,name="BrynnIntegratedUpdate",daemon=True).start()
        dialog.exec()
        restart=result_holder.get("restart") or ""
        if restart and Path(restart).exists() and dialog.bar.value()>=100:
            self._restart_after_exit(Path(restart))

    def _restart_after_exit(self, exe_path: Path):
        if os.name!="nt":
            subprocess.Popen([str(exe_path)],cwd=str(exe_path.parent)); self.exit_completely(); return
        pid=os.getpid(); safe=str(exe_path).replace("'","''"); work=str(exe_path.parent).replace("'","''")
        cmd=f"Wait-Process -Id {pid}; Start-Process -FilePath '{safe}' -WorkingDirectory '{work}'"
        try:
            subprocess.Popen(["powershell.exe","-NoProfile","-WindowStyle","Hidden","-Command",cmd],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            self.exit_completely()
        except Exception as exc:
            QMessageBox.critical(self,"Reiniciar Brynn",str(exc))

    def _resolved_app_icon_path(self) -> Path | None:
        custom = str(self.appearance.get("appIconPath") or "").strip()
        if custom:
            try:
                path = Path(custom)
                if path.exists():
                    return path
            except Exception:
                pass
        default = resource_path("brynn_default.ico")
        return default if default.exists() else None

    def _current_app_icon(self) -> QIcon:
        path = self._resolved_app_icon_path()
        if path:
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
        try:
            return self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        except Exception:
            return QIcon()

    def _apply_app_icon(self):
        icon = self._current_app_icon()
        if icon.isNull():
            return
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        if hasattr(self, "tray"):
            self.tray.setIcon(icon)
        if getattr(self, "floating_chat_window", None) is not None:
            self.floating_chat_window.setWindowIcon(icon)
        if hasattr(self, "ap_icon_preview"):
            self.ap_icon_preview.setPixmap(icon.pixmap(64, 64))

    def _refresh_app_icon_preview(self):
        if not hasattr(self, "ap_icon_preview"):
            return
        candidate = self.ap_icon_path.text().strip() if hasattr(self, "ap_icon_path") else ""
        icon = QIcon(candidate) if candidate and Path(candidate).exists() else QIcon(str(resource_path("brynn_default.ico")))
        if icon.isNull():
            icon = self._current_app_icon()
        self.ap_icon_preview.setPixmap(icon.pixmap(64, 64))

    def _save_pixmap_as_ico(self, pixmap: QPixmap, target: Path):
        if pixmap.isNull():
            raise ValueError("No se pudo leer la imagen seleccionada.")
        size = 256
        scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        x = (size - scaled.width()) // 2
        y = (size - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not canvas.save(buffer, "PNG"):
            raise RuntimeError("Qt no pudo convertir la imagen a PNG para el icono.")
        buffer.close()
        png = bytes(data)
        header = struct.pack("<HHH", 0, 1, 1)
        entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(header + entry + png)

    def select_app_icon(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar icono de Brynn Interactive",
            str(Path.home()),
            "Iconos e imágenes (*.ico *.png *.jpg *.jpeg *.webp *.bmp);;Todos los archivos (*.*)",
        )
        if not filename:
            return
        try:
            BRANDING_DIR.mkdir(parents=True, exist_ok=True)
            source = Path(filename)
            if source.suffix.lower() == ".ico":
                shutil.copy2(source, APP_ICON_FILE)
            else:
                self._save_pixmap_as_ico(QPixmap(str(source)), APP_ICON_FILE)
            self.appearance["appIconPath"] = str(APP_ICON_FILE)
            self.appearance = save_appearance(self.appearance)
            if hasattr(self, "ap_icon_path"):
                self.ap_icon_path.setText(str(APP_ICON_FILE))
            self._apply_app_icon()
            self._refresh_app_icon_preview()
            self.create_or_refresh_desktop_shortcut(silent=True)
            if hasattr(self, "ap_status"):
                self.ap_status.setText("Icono aplicado a la ventana, bandeja y acceso directo. Regenera el EXE para incrustarlo también dentro del archivo ejecutable.")
        except Exception as exc:
            QMessageBox.critical(self, "Icono de Brynn Interactive", str(exc))

    def reset_app_icon(self):
        self.appearance["appIconPath"] = ""
        try:
            if APP_ICON_FILE.exists():
                APP_ICON_FILE.unlink()
        except Exception:
            pass
        self.appearance = save_appearance(self.appearance)
        if hasattr(self, "ap_icon_path"):
            self.ap_icon_path.clear()
        self._apply_app_icon()
        self._refresh_app_icon_preview()
        self.create_or_refresh_desktop_shortcut(silent=True)
        if hasattr(self, "ap_status"):
            self.ap_status.setText("Icono predeterminado restaurado.")

    def _compiled_executable_path(self) -> Path | None:
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        candidate = resource_path("dist") / "BrynnInteractiveDesktop" / "BrynnInteractiveDesktop.exe"
        return candidate if candidate.exists() else None

    def _run_shortcut_helper(self, exe_path: Path) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "La creación automática del acceso directo está disponible en Windows."
        helper = resource_path("crear_acceso_directo.ps1")
        if not helper.exists():
            return False, f"No existe el helper: {helper}"
        icon_path = self._resolved_app_icon_path()
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-TargetPath", str(exe_path)]
        if icon_path:
            args += ["-IconPath", str(icon_path)]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=20, **self._hidden_process_kwargs())
            msg = (result.stdout or result.stderr or "").strip()
            return result.returncode == 0, msg
        except Exception as exc:
            return False, str(exc)

    def create_or_refresh_desktop_shortcut(self, silent: bool = False):
        exe_path = self._compiled_executable_path()
        if exe_path is None:
            if silent:
                return False
            answer = QMessageBox.question(
                self,
                "EXE todavía no generado",
                "Aún no existe BrynnInteractiveDesktop.exe. ¿Quieres generarlo ahora y crear el acceso directo del escritorio?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.build_desktop_executable()
            return False
        ok, message = self._run_shortcut_helper(exe_path)
        if not silent:
            if ok:
                QMessageBox.information(self, "Acceso directo", message or "Acceso directo actualizado en el escritorio.")
            else:
                QMessageBox.warning(self, "Acceso directo", message or "No se pudo crear el acceso directo.")
        return ok

    def build_desktop_executable(self):
        if getattr(sys, "frozen", False):
            self.create_or_refresh_desktop_shortcut()
            return
        script = resource_path("crear_app_escritorio.bat")
        if not script.exists():
            QMessageBox.critical(self, "Generar EXE", f"No existe {script.name}.")
            return
        if QMessageBox.question(
            self,
            "Generar aplicación de escritorio",
            "Se abrirá una consola para compilar BrynnInteractiveDesktop.exe con PyInstaller. La primera vez puede tardar varios minutos.\n\nAl terminar se creará o actualizará el acceso directo del escritorio. ¿Continuar?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", str(script)], cwd=str(script.parent))
            if hasattr(self, "ap_status"):
                self.ap_status.setText("Compilación iniciada. La consola creará el EXE y el acceso directo del escritorio al terminar.")
        except Exception as exc:
            QMessageBox.critical(self, "Generar EXE", str(exc))

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.showMinimized()
            else:
                self.show_from_tray()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon())
        self.tray.setToolTip(APP_NAME)
        menu = self.tray.contextMenu()
        if menu is None:
            from PySide6.QtWidgets import QMenu
            menu = QMenu()
            self.tray.setContextMenu(menu)

        show_action = QAction("Abrir Brynn Interactive", self)
        show_action.triggered.connect(self.show_from_tray)
        menu.addAction(show_action)
        floating_action = QAction("Abrir chat flotante", self)
        floating_action.triggered.connect(self.show_floating_chat)
        menu.addAction(floating_action)
        menu.addSeparator()
        exit_action = QAction("Salir completamente", self)
        exit_action.triggered.connect(self.exit_completely)
        menu.addAction(exit_action)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _apply_style(self):
        p = self._native_palette()
        scale = max(0.8, min(1.35, float(self.appearance.get("uiScale", 100)) / 100.0))
        density = str(self.appearance.get("density", "comfortable"))
        density_factor = {"compact": 0.82, "comfortable": 1.0, "spacious": 1.18}.get(density, 1.0)
        radius = int(self.appearance.get("panelRadius", 16))
        font = str(self.appearance.get("fontFamily") or "Segoe UI").replace("'", "")
        nav_v = max(7, int(11 * density_factor * scale))
        button_v = max(7, int(9 * density_factor * scale))
        base_font = max(11, int(13 * scale))
        title_font = max(22, int(28 * scale))
        brand_font = max(18, int(22 * scale))
        titlebar_style = str(self.appearance.get("titlebarStyle", "gradient"))
        if titlebar_style == "solid":
            titlebar_bg = p["panel1"]
            titlebar_border = p["accent"] + "55"
        elif titlebar_style == "line":
            titlebar_bg = p["window"]
            titlebar_border = p["accent2"] + "88"
        else:
            titlebar_bg = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {p['sidebar1']}, stop:0.55 {p['panel1']}, stop:1 {p['sidebar2']})"
            titlebar_border = p["accent"] + "55"

        menu_style = str(self.appearance.get("menuStyle", "soft"))
        if menu_style == "minimal":
            nav_radius = 5
            nav_selected_bg = "transparent"
            nav_selected_border = p["accent"] + "00"
            nav_selected_extra = f"border-bottom:2px solid {p['accent']};"
        elif menu_style == "pill":
            nav_radius = 999
            nav_selected_bg = p["accent"] + "20"
            nav_selected_border = p["accent"] + "55"
            nav_selected_extra = ""
        elif menu_style == "rail":
            nav_radius = max(4, radius - 8)
            nav_selected_bg = p["panel1"]
            nav_selected_border = p["accent"] + "00"
            nav_selected_extra = f"border-left:3px solid {p['accent']};"
        else:
            nav_radius = max(6, radius - 5)
            nav_selected_bg = p["accent"] + "12"
            nav_selected_border = p["accent"] + "35"
            nav_selected_extra = ""

        frame_style = str(self.appearance.get("windowFrameStyle", "soft"))
        panel_bg = p["panel1"]
        panel_bg2 = p["panel2"]
        panel_border = p["muted"] + "22"
        sidebar_border = p["accent"] + "44"
        if frame_style == "glass":
            panel_bg = p["panel1"] + "e8"
            panel_bg2 = p["panel2"] + "d8"
            panel_border = p["accent2"] + "36"
            radius = max(radius, 18)
        elif frame_style == "arcade":
            panel_border = p["accent2"] + "88"
            sidebar_border = p["accent2"] + "aa"
            radius = min(radius, 5)
        elif frame_style == "halloween":
            panel_border = p["accent"] + "66"
            radius = max(radius, 18)
        elif frame_style == "terminal":
            panel_bg = p["window"]
            panel_bg2 = p["window"]
            panel_border = p["accent"] + "55"
            radius = min(radius, 3)
        elif frame_style == "candy":
            panel_border = p["accent2"] + "55"
            radius = max(radius, 22)
        elif frame_style == "minimal":
            panel_border = p["muted"] + "18"
            radius = min(radius, 9)

        if frame_style == "arcade":
            titlebar_bg = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {p['window']}, stop:.5 {p['panel1']}, stop:1 {p['window']})"
            titlebar_border = p["accent2"] + "cc"
        elif frame_style == "halloween":
            titlebar_bg = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {p['sidebar1']}, stop:.55 {p['panel1']}, stop:1 {p['accent']}22)"
            titlebar_border = p["accent"] + "aa"
        elif frame_style == "terminal":
            titlebar_bg = p["window"]
            titlebar_border = p["accent"] + "88"
        elif frame_style == "candy":
            titlebar_bg = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {p['accent2']}22, stop:.5 {p['panel1']}, stop:1 {p['accent']}22)"
            titlebar_border = p["accent2"] + "77"

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background:{p['window']}; color:{p['text']}; font-family:'{font}'; font-size:{base_font}px;
            }}
            QLabel, QCheckBox {{ background:transparent; }}
            #windowRoot, #bodyRoot {{ background:{p['window']}; }}
            #titleBar {{
                background:{titlebar_bg}; border-bottom:1px solid {titlebar_border};
            }}
            #titleMark {{ color:{p['accent']}; font-size:{max(18,int(21*scale))}px; font-weight:900; background:transparent; }}
            #titleText {{ color:{p['title']}; font-size:{max(12,int(14*scale))}px; font-weight:900; letter-spacing:2px; background:transparent; }}
            #titleVersion {{ color:{p['accent2']}; font-size:{max(10,int(11*scale))}px; font-weight:700; background:transparent; padding:3px 8px; border:1px solid {p['accent2']}44; border-radius:8px; }}
            #windowMin, #windowMax, #windowClose {{ background:transparent; border:0; border-radius:8px; padding:0; color:{p['text']}; font-size:16px; }}
            #windowMin:hover, #windowMax:hover {{ background:{p['accent2']}22; color:{p['accent2']}; }}
            #windowClose:hover {{ background:{p['danger']}; color:white; }}
            #sidebar {{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {p['sidebar1']}, stop:1 {p['sidebar2']});
                border-right:1px solid {sidebar_border};
            }}
            #brand {{ color:{p['title']}; font-size:{brand_font}px; font-weight:900; letter-spacing:2px; line-height:1.05; padding:8px 4px 2px 4px; }}
            #version {{ color:{p['muted']}; font-size:{max(10,int(11*scale))}px; margin-bottom:12px; }}
            #navScroll, #navContainer, #navGroup, #navGroupBody {{ background:transparent; border:0; }}
            QLineEdit#navSearch {{
                background:{p['input']}; border:1px solid {p['muted']}2f; border-radius:{max(7,radius-5)}px;
                padding:8px 10px; color:{p['text']}; min-height:28px;
            }}
            QLineEdit#navSearch:focus {{ border-color:{p['accent2']}88; }}
            QPushButton#navGroupHeader {{
                background:transparent; color:{p['muted']}; border:0; border-radius:6px;
                padding:7px 7px 5px 7px; text-align:left; font-size:{max(9,int(10*scale))}px;
                font-weight:800; letter-spacing:1px;
            }}
            QPushButton#navGroupHeader:hover {{ color:{p['text']}; background:{p['accent2']}0e; }}
            QPushButton#navGroupHeader:checked {{ color:{p['accent2']}; }}
            QPushButton#navUtilityButton {{
                background:{p['panel1']}; border:1px solid {p['muted']}25; color:{p['muted']};
                min-height:26px; padding:6px 8px; border-radius:{max(6,radius-7)}px; font-size:{max(9,int(10*scale))}px;
            }}
            QPushButton#navUtilityButton:hover {{ color:{p['text']}; border-color:{p['accent2']}66; }}
            QPushButton#navTopIconButton {{
                background:{p['panel1']}; border:1px solid {p['muted']}2b; border-radius:{max(7,radius-6)}px;
                min-width:28px; max-width:28px; min-height:30px; max-height:30px; padding:0;
            }}
            QPushButton#navTopIconButton:hover {{ border-color:{p['accent2']}77; background:{p['accent2']}14; }}
            QPushButton#navButton {{
                background:transparent;
                color:{p['text']};
                border:1px solid transparent;
                border-radius:{nav_radius}px;
                padding:{nav_v}px 14px;
                text-align:left;
                font-size:{base_font}px;
                font-weight:500;
            }}
            QPushButton#navButton[compactNav="true"] {{ padding:10px 0px; text-align:center; min-height:28px; }}
            QPushButton#navButton:hover {{
                background:{p['accent2']}16;
                border:1px solid {p['accent2']}38;
            }}
            QPushButton#navButton:checked {{
                background:{nav_selected_bg};
                color:{p['accent']};
                border:1px solid {nav_selected_border};
                {nav_selected_extra}
            }}
            #contentShell {{ background:{p['window']}; }}
            #contextBar {{ background:{p['panel2']}; border-bottom:1px solid {p['muted']}1b; }}
            #breadcrumb {{ color:{p['muted']}; font-size:{max(10,int(11*scale))}px; font-weight:650; }}
            QPushButton#contextSearchButton {{ background:transparent; border:1px solid {p['muted']}25; color:{p['muted']}; padding:5px 10px; min-height:20px; }}
            QPushButton#contextSearchButton:hover {{ color:{p['accent2']}; border-color:{p['accent2']}55; }}
            #homeScroll, #homeScroll > QWidget, #homeScroll QWidget#qt_scrollarea_viewport, #homeContent {{ background:transparent; border:0; }}
            #homeHero {{ background:{panel_bg}; border:1px solid {panel_border}; border-radius:{radius}px; }}
            #homeLiveBadge {{ color:{p['accent']}; background:{p['accent']}12; border:1px solid {p['accent']}44; border-radius:9px; padding:6px 10px; font-size:{max(9,int(10*scale))}px; font-weight:850; }}
            QPushButton#quickAction {{ min-height:34px; text-align:left; }}
            #dashboardPanel {{ background:{panel_bg}; border:1px solid {panel_border}; border-radius:{radius}px; }}
            #dashboardPanelTitle {{ color:{p['accent2']}; font-weight:800; font-size:{max(11,int(12*scale))}px; }}
            #dashboardBigText {{ color:{p['title']}; font-weight:900; font-size:{max(15,int(17*scale))}px; }}
            #dashboardValueSmall {{ color:{p['accent']}; font-weight:850; }}
            #dashboardMuted {{ color:{p['muted']}; font-size:{max(9,int(10*scale))}px; }}
            #rankingPreviewRow {{ color:{p['text']}; background:{p['panel2']}; border:1px solid {p['muted']}18; border-radius:7px; padding:8px 10px; }}
            QProgressBar#goalProgress {{ background:{p['panel2']}; border:1px solid {p['muted']}18; border-radius:6px; min-height:10px; max-height:10px; }}
            QProgressBar#goalProgress::chunk {{ background:{p['accent']}; border-radius:5px; }}
            QListWidget#homeActivity, QListWidget#paletteResults {{ background:{p['panel2']}; border:1px solid {p['muted']}20; border-radius:{max(7,radius-5)}px; padding:5px; }}
            QListWidget#homeActivity::item, QListWidget#paletteResults::item {{ padding:8px 9px; border-radius:6px; }}
            QListWidget#homeActivity::item:selected, QListWidget#paletteResults::item:selected {{ background:{p['accent']}20; color:{p['title']}; }}
            QDialog#commandPalette {{ background:{p['window']}; }}
            #paletteTitle {{ color:{p['title']}; font-size:{max(18,int(20*scale))}px; font-weight:900; }}
            #pageTitle {{ font-size:{title_font}px; font-weight:900; color:{p['title']}; }}
            #pageSubtitle {{ color:{p['muted']}; font-size:{max(11,int(13*scale))}px; }}
            #statusCard, #panel {{ background:{panel_bg}; border:1px solid {panel_border}; border-radius:{radius}px; }}
            #settingsScroll, #settingsScroll > QWidget, #settingsScroll QWidget#qt_scrollarea_viewport, #settingsContent {{ background:transparent; border:0; }}
            #settingsCard {{ background:{panel_bg}; border:1px solid {panel_border}; border-radius:{radius}px; }}
            #cardTitle {{ color:{p['title']}; font-size:{max(16,int(18*scale))}px; font-weight:800; background:transparent; }}
            #cardSubtitle {{ color:{p['muted']}; font-size:{max(10,int(11*scale))}px; background:transparent; }}
            #fieldWrap {{ background:transparent; }}
            #settingLabel {{ color:{p['text']}; font-weight:650; background:transparent; }}
            #settingHint {{ color:{p['muted']}; font-size:{max(9,int(10*scale))}px; background:transparent; }}
            #subtlePanel {{ background:{panel_bg2}; border:1px solid {panel_border}; border-radius:{max(4,radius-5)}px; }}
            #personalizationActions {{ background:{p['window']}; border-top:1px solid {p['muted']}20; }}
            #personalizationStatus {{ color:{p['muted']}; background:transparent; padding:2px 4px; }}
            #primaryAction {{ background:{p['accent']}24; border:1px solid {p['accent']}66; color:{p['title']}; }}
            #primaryAction:hover {{ background:{p['accent']}38; border-color:{p['accent']}; }}
            #quietButton {{ min-width:96px; }}
            #appearancePreview {{ background:{p['window']}; border:1px solid {p['muted']}24; border-radius:{radius}px; }}
            #appearancePreviewSide {{ background:{p['sidebar1']}; border:1px solid {p['muted']}22; border-radius:{max(8,radius-2)}px; min-width:210px; }}
            #appearancePreviewContent {{ background:{panel_bg2}; border:1px solid {panel_border}; border-radius:{max(6,radius-2)}px; }}
            #previewBrand {{ color:{p['title']}; font-weight:900; font-size:{max(15,int(17*scale))}px; letter-spacing:1px; background:transparent; }}
            #previewMenuItem {{ color:{p['muted']}; padding:7px 9px; background:transparent; }}
            #previewMenuItemSelected {{ color:{p['accent']}; padding:7px 9px; background:{p['accent']}14; border-radius:{max(5,radius-7)}px; }}
            #previewTitle {{ color:{p['accent2']}; font-weight:800; background:transparent; }}
            #previewText {{ color:{p['muted']}; background:transparent; }}
            #statusTitle {{ color:{p['accent2']}; font-size:{max(9,int(11*scale))}px; font-weight:700; }}
            #statusValue {{ font-size:{max(14,int(18*scale))}px; font-weight:900; color:{p['title']}; }}
            #statusDetail {{ color:{p['muted']}; font-size:{max(9,int(10*scale))}px; }}
            #sectionTitle {{ font-size:{max(14,int(16*scale))}px; font-weight:900; color:{p['accent2']}; }}
            #tip {{ background:{p['panel2']}; border:1px solid {p['accent']}38; border-left:4px solid {p['accent']}; border-radius:{max(6,radius-4)}px; padding:12px; color:{p['text']}; }}
            QPushButton {{ background:{p['panel1']}; border:1px solid {p['muted']}2d; min-height:24px; padding:{button_v}px 14px; border-radius:{max(6,radius-5)}px; color:{p['text']}; font-weight:650; }}
            QPushButton:hover {{ border-color:{p['accent']}; background:{p['accent']}16; }}
            QPushButton:disabled {{ color:{p['muted']}; border-color:{p['muted']}44; }}
            QLineEdit, QPlainTextEdit, QComboBox {{ background:{p['input']}; border:1px solid {p['muted']}32; min-height:30px; border-radius:{max(7,radius-5)}px; padding:{max(7,int(8*density_factor))}px 10px; color:{p['text']}; selection-background-color:{p['accent2']}; selection-color:{p['window']}; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color:{p['accent']}88; }}
            #numberInputWrap {{ background:{p['input']}; border:1px solid {p['muted']}32; border-radius:{max(7,radius-5)}px; }}
            #numberInput {{ background:transparent; border:0; min-height:30px; padding:{max(7,int(8*density_factor))}px 10px; color:{p['text']}; font-weight:650; }}
            #numberInput:focus {{ border:0; background:{p['accent']}0d; }}
            #numberUnit {{ color:{p['muted']}; background:transparent; padding-right:10px; font-weight:600; }}
            QComboBox {{ padding-right:28px; }}
            QComboBox::drop-down {{ border:0; width:26px; }}
            QComboBox QAbstractItemView {{ background:{p['panel1']}; color:{p['text']}; border:1px solid {p['muted']}30; selection-background-color:{p['accent']}33; padding:4px; }}
            QCheckBox {{ spacing:8px; color:{p['text']}; }}
            QScrollBar:vertical {{ background:{p['panel2']}; width:11px; margin:0; border-radius:6px; }}
            QScrollBar::handle:vertical {{ background:{p['accent2']}; min-height:30px; border-radius:6px; }}
            #statusFooter {{ background:{p['panel2']}; border-top:1px solid {p['accent']}33; }}
            #footerItem {{ color:{p['muted']}; font-size:{max(9,int(10*scale))}px; background:transparent; }}
            #footerVersion {{ color:{p['accent2']}; font-size:{max(9,int(10*scale))}px; font-weight:700; background:transparent; }}
        """)
        if hasattr(self, "title_bar"):
            self.title_bar.setFixedHeight(max(40, int(int(self.appearance.get("titlebarHeight", 46)) * scale)))
            self.title_bar.sync_state()

    def _set_nav_checked(self, key: str):
        for route, buttons in getattr(self, "_nav_button_instances", {}).items():
            for button in list(buttons):
                try:
                    button.blockSignals(True)
                    button.setChecked(route == key)
                    button.blockSignals(False)
                except RuntimeError:
                    pass
        self._update_breadcrumb(key)

    def _route_is_visible(self, key: str) -> bool:
        if key == "home":
            return self.stack.currentWidget() is self.home
        if key == "settings":
            return self.stack.currentWidget() is self.desktop_settings
        if key == "updates-native":
            return self.stack.currentWidget() is self.update_manager
        if key == "personalization":
            return self.stack.currentWidget() is self.personalization
        if key == "privacy":
            return self.stack.currentWidget() is self.privacy_page
        if self.stack.currentWidget() is not self.web_host:
            return False
        target_path = "/" + key.split("?", 1)[0].lstrip("/")
        return self.web_view.url().path() == target_path

    def _loader_media_path(self) -> Path | None:
        mode = str(self.appearance.get("loadingType") or "circle")
        if mode == "image":
            raw = str(self.appearance.get("loadingImage") or "").strip()
            if not raw:
                return None
            candidate = Path(raw)
            if candidate.exists():
                return candidate
            candidate = LOADER_MEDIA_DIR / Path(raw).name
            return candidate if candidate.exists() else None

        if mode == "emote":
            emote_id = str(self.appearance.get("loadingEmoteId") or "").strip()
            if not emote_id:
                return None
            payload = load_json_file(DATA_DIR / "emotes.json", {"emotes": []})
            for emote in payload.get("emotes", []) if isinstance(payload, dict) else []:
                if str(emote.get("id") or "") != emote_id:
                    continue
                visual = str(emote.get("visualUrl") or "").strip()
                if not visual:
                    return None
                parsed = urllib.parse.urlparse(visual)
                name = Path(urllib.parse.unquote(parsed.path)).name
                candidate = MEDIA_DIR / name
                if candidate.exists():
                    return candidate
                return None
        return None

    def _configure_loading_overlay(self):
        if not hasattr(self, "loading_overlay"):
            return
        palette = self._native_palette(
            theme=str(self.appearance.get("theme") or "neon"),
            accent=str(self.appearance.get("accent") or ""),
            accent2=str(self.appearance.get("accent2") or ""),
        )
        self.loading_overlay.configure(
            self.appearance,
            palette,
            self._loader_media_path(),
        )

    def _cancel_pending_web(self):
        view = getattr(self, "pending_web_view", None)
        if view is None:
            return
        try:
            view.stop()
            if hasattr(self, "web_stack"):
                self.web_stack.removeWidget(view)
            view.setParent(None)
            view.deleteLater()
        except Exception:
            pass
        self.pending_web_view = None

    def _attach_desktop_web_page(self, view: QWebEngineView):
        page = DesktopWebPage(view)
        page.localRouteRequested.connect(self._handle_internal_web_route)
        page.desktopCommandRequested.connect(self._handle_desktop_command)
        try:
            page.renderProcessTerminated.connect(
                lambda _status, _code, v=view: self._recover_web_view(v)
            )
        except Exception:
            pass
        view.setPage(page)

    def _recover_web_view(self, view: QWebEngineView):
        """Recupera Chromium si el renderer termina en lugar de dejar negro."""
        if view not in {getattr(self, "web_view", None), getattr(self, "pending_web_view", None)}:
            return
        key = str(getattr(self, "_active_route", "") or "")
        if ".html" not in key:
            return
        if hasattr(self, "footer_message"):
            self.footer_message.setText("RECUPERANDO PANEL…")
        QTimer.singleShot(180, lambda k=key: self._activate_route(k, force=True))

    def _web_watchdog_tick(self):
        """Detecta un renderer aparentemente vivo pero con documento vacío."""
        try:
            if not hasattr(self,"web_host") or self.stack.currentWidget() is not self.web_host:
                self._blank_watchdog_count=0; return
            if getattr(self,"pending_web_view",None) is not None:
                return
            view=getattr(self,"web_view",None)
            if view is None or view.url().path() in {"","/"}:
                return
            view.page().runJavaScript("(() => document.body ? (document.body.innerText || document.body.textContent || '').trim().length : 0)()", self._on_web_watchdog_result)
        except Exception:
            self._blank_watchdog_count=0

    def _on_web_watchdog_result(self,length):
        try: useful=int(length or 0)>=12
        except Exception: useful=False
        if useful:
            self._blank_watchdog_count=0; return
        self._blank_watchdog_count+=1
        if self._blank_watchdog_count>=2:
            self._blank_watchdog_count=0
            key=str(getattr(self,"_active_route","") or "")
            if ".html" in key:
                if hasattr(self,"footer_message"): self.footer_message.setText("RECUPERANDO PANEL VACÍO…")
                self._activate_route(key,force=True)

    def _route_key_for_path(self, path: str) -> str | None:
        clean = str(path or "").split("?", 1)[0].lstrip("/")
        for key in getattr(self, "_nav_buttons", {}):
            if not isinstance(key, str) or ".html" not in key:
                continue
            if key.split("?", 1)[0].lstrip("/") == clean:
                return key
        return None

    def _handle_internal_web_route(self, path: str):
        key = self._route_key_for_path(path)
        if key:
            self._activate_route(key, force=True)
            return
        # Si aparece una página local nueva en una beta futura, la seguimos
        # abriendo mediante el mismo pipeline seguro del shell.
        clean = str(path or "").split("?", 1)[0].lstrip("/")
        if clean.lower().endswith(".html"):
            self._activate_route(f"{clean}?v={ASSET_VERSION}", force=True)

    def _handle_desktop_command(self, command: str):
        raw = str(command or "")
        base, _, query_text = raw.partition("?")
        cmd = base.strip("/").lower()
        if cmd in {"floating-chat/open","chat/open"}:
            self.show_floating_chat()
        elif cmd in {"floating-chat/toggle-click","chat/toggle-click"}:
            self.show_floating_chat()
            self.floating_chat_window.toggle_click_through()
        elif cmd in {"floating-chat/hide","chat/hide"}:
            if self.floating_chat_window: self.floating_chat_window.hide()
        elif cmd in {"external/open", "open-external", "browser/open"}:
            try:
                params = urllib.parse.parse_qs(query_text)
                url = str((params.get("url") or [""])[0] or "").strip()
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme.lower() in {"http", "https"}:
                    QDesktopServices.openUrl(QUrl(url))
            except Exception:
                pass

    def show_floating_chat(self):
        if self.floating_chat_window is None:
            self.floating_chat_window=FloatingChatWindow(self)
        self.floating_chat_window.show()
        self.floating_chat_window.raise_()
        return self.floating_chat_window

    def _new_web_view(self) -> QWebEngineView:
        view = QWebEngineView()
        self._attach_desktop_web_page(view)
        view.setZoomFactor(float(self.appearance.get("webZoom", 95)) / 100.0)
        palette = self._native_palette(
            theme=str(self.appearance.get("theme") or "neon"),
            accent=str(self.appearance.get("accent") or ""),
            accent2=str(self.appearance.get("accent2") or ""),
        )
        view.page().setBackgroundColor(QColor(str(palette.get("window") or "#0b0e14")))
        view.urlChanged.connect(self._sync_nav_from_web_url)
        return view

    def _activate_route(self, key: str, force: bool = False):
        if not key:
            return
        if not force and str(getattr(self, "_active_route", "")) == str(key) and self._route_is_visible(key):
            return

        # Cualquier ruta nueva invalida cargas web anteriores.
        self._nav_serial += 1
        serial = self._nav_serial

        if key in ("home", "settings", "updates-native", "personalization", "privacy"):
            self._cancel_pending_web()
            if hasattr(self, "loading_overlay"):
                self.loading_overlay.hide_loader()

            self._active_route = key
            self._set_nav_checked(key)
            self._record_recent_route(key)

            if key == "home":
                self.stack.setCurrentWidget(self.home)
                self.refresh_status()
            elif key == "settings":
                self.stack.setCurrentWidget(self.desktop_settings)
                self._load_settings_form()
            elif key == "updates-native":
                self.stack.setCurrentWidget(self.update_manager)
                self.refresh_update_manager()
            elif key == "personalization":
                self.stack.setCurrentWidget(self.personalization)
                self._load_personalization_form()
                self._refresh_personalization_preview()
            elif key == "privacy":
                self.stack.setCurrentWidget(self.privacy_page)
            return

        target = self._make_web_url(key)
        self._active_route = key
        self._requested_web_key = key
        self._requested_web_path = target.path()
        self._pending_web_retry = 0
        self._set_nav_checked(key)
        self._record_recent_route(key)
        self._cancel_pending_web()

        pending = self._new_web_view()
        self.pending_web_view = pending
        self.web_stack.addWidget(pending)
        pending.loadFinished.connect(
            lambda ok, s=serial, v=pending, k=key, path=target.path():
            self._on_pending_web_load_finished(s, v, k, path, ok)
        )

        # La vista anterior se mantiene visible. Si venimos de una página
        # nativa, el overlay cubre el WebView vacío inicial.
        self.stack.setCurrentWidget(self.web_host)
        self._configure_loading_overlay()
        label = self._route_labels.get(key, key.split("?", 1)[0])
        self._loading_started_at = time.monotonic()
        self.loading_overlay.show_loader(label)
        if hasattr(self, "footer_message"):
            self.footer_message.setText(f"CARGANDO · {label.upper()}")

        pending.setUrl(target)

    def _on_pending_web_load_finished(
        self,
        serial: int,
        view: QWebEngineView,
        key: str,
        requested_path: str,
        ok: bool,
    ):
        if serial != self._nav_serial or view is not self.pending_web_view:
            try:
                view.stop()
                self.web_stack.removeWidget(view)
                view.deleteLater()
            except Exception:
                pass
            return

        current_path = view.url().path()
        if not ok or current_path != requested_path:
            self._retry_or_fail_pending_web(serial, view, key, requested_path)
            return

        # loadFinished puede ser True incluso si Chromium dejó un documento
        # vacío. Verificamos contenido real antes de sustituir el panel visible.
        try:
            view.page().runJavaScript(
                "(() => document.body ? (document.body.innerText || document.body.textContent || '').trim().length : 0)()",
                lambda length, s=serial, v=view, k=key, path=requested_path:
                    self._on_pending_web_content_verified(s, v, k, path, length),
            )
        except Exception:
            self._retry_or_fail_pending_web(serial, view, key, requested_path)

    def _retry_or_fail_pending_web(self, serial: int, view: QWebEngineView, key: str, requested_path: str):
        if serial != self._nav_serial or view is not self.pending_web_view:
            return
        if self._pending_web_retry < 2:
            self._pending_web_retry += 1
            retry_url = self._make_web_url(key)
            QTimer.singleShot(180 * self._pending_web_retry, lambda v=view, u=QUrl(retry_url): v.setUrl(u))
            return
        # Nunca sustituimos la vista anterior por una pantalla negra.
        self._cancel_pending_web()
        current_view=getattr(self, "web_view", None)
        current_path=current_view.url().path() if current_view is not None else ""
        if current_view is not None and current_path not in {"", "/"}:
            self.web_stack.setCurrentWidget(current_view)
        else:
            # Si todavía no existía ningún panel web válido, volvemos a Inicio;
            # jamás dejamos el host vacío/negro como estado final.
            self.stack.setCurrentWidget(self.home)
            self._set_nav_checked("home")
        self.loading_overlay.hide_loader()
        if hasattr(self, "footer_message"):
            self.footer_message.setText("PANEL NO DISPONIBLE · reintenta la sección")
        QMessageBox.warning(self, "Panel no disponible", "Brynn evitó mostrar una pantalla vacía. El panel anterior se conservó. Vuelve a intentarlo en unos segundos.")

    def _on_pending_web_content_verified(self, serial: int, view: QWebEngineView, key: str, requested_path: str, length):
        if serial != self._nav_serial or view is not self.pending_web_view:
            return
        try:
            useful = int(length or 0) >= 12
        except Exception:
            useful = False
        if not useful:
            self._retry_or_fail_pending_web(serial, view, key, requested_path)
            return

        old = self.web_view
        self.web_view = view
        self.pending_web_view = None
        self.web_stack.setCurrentWidget(view)
        self._requested_web_path = None
        self._requested_web_key = None
        self._pending_web_retry = 0
        self._set_nav_checked(key)

        if old is not view:
            try:
                self.web_stack.removeWidget(old)
                old.stop()
                old.setParent(None)
                old.deleteLater()
            except Exception:
                pass

        minimum_ms = max(0, min(3000, int(self.appearance.get("loadingMinMs") or 320)))
        elapsed_ms = int((time.monotonic() - self._loading_started_at) * 1000)
        wait_ms = max(0, minimum_ms - elapsed_ms)
        QTimer.singleShot(wait_ms, lambda s=serial: self._hide_loader_if_current(s))

        if hasattr(self, "footer_message"):
            self.footer_message.setText(APP_VERSION_LABEL)

    def _hide_loader_if_current(self, serial: int):
        if serial == self._nav_serial and hasattr(self, "loading_overlay"):
            self.loading_overlay.hide_loader()

    def _select_nav_key(self, key: str):
        self._set_nav_checked(key)

    def _sync_nav_from_web_url(self, url: QUrl):
        source = self.sender()
        if isinstance(source, QWebEngineView) and source is not self.web_view:
            return
        if not url.isValid():
            return
        path = url.path()
        if not path or path == "/":
            return

        requested = getattr(self, "_requested_web_path", None)
        if requested and path != requested:
            return

        clean_path = path.lstrip("/")
        for key in getattr(self, "_nav_buttons", {}):
            if not isinstance(key, str) or ".html" not in key:
                continue
            if key.split("?", 1)[0].lstrip("/") == clean_path:
                self._active_route = key
                self._set_nav_checked(key)
                break

    def _make_web_url(self, key: str) -> QUrl:
        url = QUrl(f"{LOCAL_BASE}/{key}")
        query = QUrlQuery(url)
        query.addQueryItem("theme", str(self.appearance.get("theme", "neon")))
        if self.appearance.get("accent"):
            query.addQueryItem("accent", str(self.appearance.get("accent")))
        if self.appearance.get("accent2"):
            query.addQueryItem("accent2", str(self.appearance.get("accent2")))
        query.addQueryItem("density", str(self.appearance.get("density", "comfortable")))
        query.addQueryItem("font", str(self.appearance.get("fontFamily", "Segoe UI")))
        query.addQueryItem("radius", str(self.appearance.get("panelRadius", 16)))
        url.setQuery(query)
        return url

    def open_updates(self):
        key = "updates.html?v=57"
        self._select_nav_key(key)
        self._activate_route(key, force=True)

    def _obs_text(self) -> str:
        return "\n".join([
            "Brynn_Chat",
            f"{LOCAL_BASE}/index.html?v=57",
            "",
            "Brynn_Alerts",
            f"{LOCAL_BASE}/alerts_overlay.html?v=57",
            "",
            "Brynn_Events",
            f"{LOCAL_BASE}/events_overlay.html?v=57",
            "",
            "Brynn_Top3",
            f"{LOCAL_BASE}/top3_overlay.html?v=57",
            "",
            "Brynn_Goals (usa el ID que muestra el panel Metas)",
            f"{LOCAL_BASE}/goals_overlay.html?v=57&id=GOAL_ID",
            "",
            "Brynn_StreamlabsBridge",
            f"{LOCAL_BASE}/streamlabs_bridge.html?v=57&obs=1",
        ])

    def copy_obs_urls(self):
        QApplication.clipboard().setText(self._obs_text())
        if hasattr(self, "footer_message"):
            self.footer_message.setText("URLs de OBS copiadas ✓")
            QTimer.singleShot(3000, lambda: self.footer_message.setText(APP_VERSION_LABEL))

    def open_folder(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def create_backup(self):
        output = create_data_backup("manual_backup")
        if output:
            QMessageBox.information(self, "Backup creado", f"Se guardó en:\n{output}")
        else:
            QMessageBox.critical(self, "Error", "No se pudo crear el backup.")

    def refresh_status(self):
        try:
            health = http_json(f"{LOCAL_BASE}/api/health", timeout=0.45)
            self.card_server.set_state(
                "● Activo",
                f"127.0.0.1:8765 · {health.get('sessionId','')[:6]}",
                True,
            )
            if hasattr(self, "footer_server"):
                self.footer_server.setText("● SERVER · ONLINE")
                self.footer_server.setStyleSheet("color:#76ff6a;background:transparent;")
        except Exception as exc:
            self.card_server.set_state("● Sin conexión", str(exc)[:80], False)
            if hasattr(self, "footer_server"):
                self.footer_server.setText("● SERVER · OFFLINE")
                self.footer_server.setStyleSheet("color:#ff637d;background:transparent;")
            if hasattr(self, "home_live_badge"):
                self.home_live_badge.setText("BACKEND OFFLINE")
            self.card_streamlabs.set_state("—", "Servidor no disponible", None)
            self.card_tiktok.set_state("—", "Servidor no disponible", None)
            self.card_kick.set_state("—", "Servidor no disponible", None)
            return

        try:
            data = http_json(f"{LOCAL_BASE}/api/integrations", timeout=0.55)
            sl = data.get("streamlabs", {})
            if sl.get("connected"):
                self.card_streamlabs.set_state(
                    "● Conectado",
                    f"Bridge: {sl.get('activeBridges',0)} · Token: {'sí' if sl.get('tokenPresent') else 'no'}",
                    True,
                )
                if hasattr(self, "footer_streamlabs"):
                    self.footer_streamlabs.setText("● STREAMLABS · ONLINE")
                    self.footer_streamlabs.setStyleSheet("color:#76ff6a;background:transparent;")
            elif sl.get("tokenPresent"):
                self.card_streamlabs.set_state(
                    "● Preparando",
                    sl.get("lastError") or sl.get("state", "Esperando bridge"),
                    None,
                )
            else:
                self.card_streamlabs.set_state("● Sin configurar", "Falta Socket API Token", False)
                if hasattr(self, "footer_streamlabs"):
                    self.footer_streamlabs.setText("● STREAMLABS · OFFLINE")
                    self.footer_streamlabs.setStyleSheet("color:#ff637d;background:transparent;")

            tk = data.get("tikfinity", {})
            mode = tk.get("mode", "webhook")
            if tk.get("enabled"):
                self.card_tiktok.set_state(
                    "● Habilitado",
                    f"Modo: {mode} · {tk.get('publicBaseUrl') or 'URL pública no configurada'}",
                    True if tk.get("publicBaseUrl") else None,
                )
                if hasattr(self, "footer_tiktok"):
                    self.footer_tiktok.setText("● TIKFINITY · READY")
                    self.footer_tiktok.setStyleSheet("color:#76ff6a;background:transparent;")
            else:
                self.card_tiktok.set_state("● Deshabilitado", "", None)
                if hasattr(self, "footer_tiktok"):
                    self.footer_tiktok.setText("● TIKFINITY · OFF")
                    self.footer_tiktok.setStyleSheet("color:#95a6c0;background:transparent;")
        except Exception as exc:
            self.card_streamlabs.set_state("● Error", str(exc)[:80], None)
            self.card_tiktok.set_state("● Error", str(exc)[:80], None)

        try:
            kick = http_json(f"{LOCAL_BASE}/api/kick", timeout=0.55)
            if kick.get("connected"):
                self.card_kick.set_state("● Autorizado", "Usuario: " + str(kick.get("username") or kick.get("userId") or ""), True)
            elif kick.get("clientConfigured"):
                self.card_kick.set_state("● Pendiente", "Falta autorización OAuth", None)
            else:
                self.card_kick.set_state("● Sin configurar", "Integraciones → Kick", False)
        except Exception as exc:
            self.card_kick.set_state("● Error", str(exc)[:60], None)

        # Tailscale se consulta con menor frecuencia para no bloquear el UI.
        if not hasattr(self, "_tailscale_counter"):
            self._tailscale_counter = 0
        self._tailscale_counter += 1
        if self._tailscale_counter % 4 == 1:
            self.refresh_tailscale()

        if hasattr(self, "home_live_badge"):
            self.home_live_badge.setText("SISTEMA ONLINE")
        if not hasattr(self, "_home_snapshot_counter"):
            self._home_snapshot_counter = 0
        self._home_snapshot_counter += 1
        if self._home_snapshot_counter % 2 == 1:
            self._refresh_home_snapshot()

    def _hidden_process_kwargs(self):
        if os.name != "nt":
            return {}
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

    def refresh_tailscale(self):
        exe = shutil.which("tailscale")
        if not exe:
            self.card_tailscale.set_state("● No encontrado", "Instala Tailscale o añádelo al PATH", False)
            return
        try:
            proc = subprocess.run(
                [exe, "funnel", "status"],
                capture_output=True,
                text=True,
                timeout=3,
                **self._hidden_process_kwargs(),
            )
            text = (proc.stdout + "\n" + proc.stderr).strip()
            match = re.search(r"https://[^\s]+", text)
            if match:
                self.card_tailscale.set_state("● Activo", match.group(0).rstrip("/"), True)
                if hasattr(self, "footer_tailscale"):
                    self.footer_tailscale.setText("● TAILSCALE · ONLINE")
                    self.footer_tailscale.setStyleSheet("color:#76ff6a;background:transparent;")
            else:
                self.card_tailscale.set_state("● Inactivo", text[:100] or "Sin Funnel", None)
                if hasattr(self, "footer_tailscale"):
                    self.footer_tailscale.setText("● TAILSCALE · OFF")
                    self.footer_tailscale.setStyleSheet("color:#95a6c0;background:transparent;")
        except Exception as exc:
            self.card_tailscale.set_state("● Error", str(exc)[:100], None)

    def start_tailscale(self):
        exe = shutil.which("tailscale")
        if not exe:
            QMessageBox.warning(self, "Tailscale", "No se encontró tailscale.exe en PATH.")
            return
        try:
            proc = subprocess.run(
                [exe, "funnel", "--bg", "8766"],
                capture_output=True,
                text=True,
                timeout=12,
                **self._hidden_process_kwargs(),
            )
            message = (proc.stdout + "\n" + proc.stderr).strip()
            QMessageBox.information(self, "Tailscale Funnel", message or "Comando ejecutado.")
            self.refresh_tailscale()
        except Exception as exc:
            QMessageBox.critical(self, "Tailscale", str(exc))

    def stop_tailscale(self):
        exe = shutil.which("tailscale")
        if not exe:
            return
        if QMessageBox.question(
            self,
            "Apagar Funnel",
            "¿Quieres apagar el Funnel público de TikFinity?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            subprocess.run(
                [exe, "funnel", "--https=443", "off"],
                capture_output=True,
                text=True,
                timeout=8,
                **self._hidden_process_kwargs(),
            )
            self.refresh_tailscale()
        except Exception as exc:
            QMessageBox.critical(self, "Tailscale", str(exc))


    def _apply_developer_mode_visibility(self):
        enabled = bool(load_profile().get("developerMode", False))
        for entry in getattr(self, "_route_catalog", []):
            if not entry.get("developer"):
                continue
            for button in getattr(self, "_nav_button_instances", {}).get(entry.get("route"), []):
                button.setVisible(enabled)
        if hasattr(self, "_nav_groups"):
            group = self._nav_groups.get("developer")
            if group:
                group.setVisible(enabled)
        if hasattr(self, "nav_search"):
            self._refresh_special_nav_groups()
            self._apply_nav_filter(self.nav_search.text())

    def _set_developer_mode(self, enabled: bool):
        profile = load_profile()
        profile["developerMode"] = bool(enabled)
        self.profile = save_profile(profile)
        self._apply_developer_mode_visibility()

    def save_profile_settings(self):
        profile = load_profile()
        profile["setupComplete"] = True
        profile["streamerName"] = self.profile_streamer.text().strip() or "Mi canal"
        profile["owners"] = {
            "twitch": self.profile_twitch.text().strip().lstrip("@"),
            "tiktok": self.profile_tiktok.text().strip().lstrip("@"),
            "kick": self.profile_kick.text().strip().lstrip("@"),
        }
        profile["developerMode"] = self.developer_mode.isChecked() if hasattr(self, "developer_mode") else False
        self.profile = save_profile(profile)
        _write_setup_state(True)
        self.settings_status.setText("✅ Identidad guardada. Reinicia Brynn si cambiaste las cuentas propietarias para aplicar privilegios de economía.")

    def export_user_configuration(self):
        suggested = f"BrynnInteractive-config-{datetime.now().strftime('%Y%m%d')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar configuración", str(Path.home()/suggested), "ZIP (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for folder, prefix in ((DATA_DIR,"data"),(MEDIA_DIR,"user_media"),(LOADER_MEDIA_DIR,"loading_assets"),(BRANDING_DIR,"branding")):
                    if folder.exists():
                        for file in folder.rglob("*"):
                            if not file.is_file():
                                continue
                            arc = f"{prefix}/{file.relative_to(folder)}"
                            if file == DATA_DIR / "integrations.json":
                                redacted = load_json_file(file, {})
                                if isinstance(redacted, dict):
                                    if isinstance(redacted.get("streamlabs"), dict): redacted["streamlabs"]["socketToken"] = ""
                                    if isinstance(redacted.get("tikfinity"), dict): redacted["tikfinity"]["webhookSecret"] = ""
                                z.writestr(arc, json.dumps(redacted, ensure_ascii=False, indent=2))
                            elif file == DATA_DIR / "social_stream.json":
                                redacted = load_json_file(file, {})
                                if isinstance(redacted, dict): redacted["password"] = "false"
                                z.writestr(arc, json.dumps(redacted, ensure_ascii=False, indent=2))
                            else:
                                z.write(file, arc)
                if APPEARANCE_FILE.exists():
                    z.write(APPEARANCE_FILE, "desktop_appearance.json")
                if NAV_STATE_FILE.exists():
                    z.write(NAV_STATE_FILE, "navigation_state.json")
                z.writestr("export_info.json", json.dumps({"appId":APP_ID,"version":APP_VERSION,"includesSecrets":False,"createdAt":datetime.now().isoformat()}, indent=2))
            self.privacy_status.setText(f"✅ Configuración exportada: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Exportar configuración", str(exc))

    def import_user_configuration(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar configuración", str(Path.home()), "ZIP (*.zip)")
        if not path:
            return
        backup = create_data_backup("before_import")
        try:
            allowed = {"data":DATA_DIR,"user_media":MEDIA_DIR,"loading_assets":LOADER_MEDIA_DIR,"branding":BRANDING_DIR}
            with zipfile.ZipFile(path, "r") as z:
                for member in z.infolist():
                    name = member.filename.replace("\\","/")
                    if name == "desktop_appearance.json":
                        APPEARANCE_FILE.write_bytes(z.read(member))
                        continue
                    if name == "navigation_state.json":
                        NAV_STATE_FILE.write_bytes(z.read(member))
                        continue
                    parts = [x for x in name.split("/") if x and x not in (".","..")]
                    if len(parts) < 2 or parts[0] not in allowed or member.is_dir():
                        continue
                    target = allowed[parts[0]].joinpath(*parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(member))
            QMessageBox.information(self, "Importación completa", "La configuración fue importada. Reinicia Brynn Interactive para cargar todos los cambios.")
            self.privacy_status.setText(f"✅ Importado. Backup previo: {backup.name if backup else 'no disponible'}")
        except Exception as exc:
            QMessageBox.critical(self, "Importar configuración", str(exc))

    def reset_community_data(self):
        if QMessageBox.question(self, "Borrar datos de comunidad", "Se borrarán ranking, economía, Hall of Fame y recompensas semanales. ¿Continuar?") != QMessageBox.StandardButton.Yes:
            return
        create_data_backup("before_community_reset")
        payloads = {
            "ranking_actual.json":{"period":"","users":{},"updatedAt":None},
            "backup.json":{"period":"","users":{},"updatedAt":None},
            "economia.json":{"users":{},"transactions":[],"updatedAt":None},
            "economia_backup.json":{"users":{},"transactions":[],"updatedAt":None},
            "weekly_rewards_state.json":{},
            "hall_of_fame.json":{"weeks":[],"users":{},"updatedAt":None},
        }
        for name, payload in payloads.items():
            save_json_file(DATA_DIR/name, payload)
        weeks = DATA_DIR/"semanas"
        if weeks.exists():
            for file in weeks.glob("*.json"):
                try:
                    file.unlink()
                except Exception:
                    pass
        self.privacy_status.setText("✅ Ranking, economía y recompensas históricas restablecidos.")

    def factory_reset(self):
        answer = QMessageBox.warning(
            self,
            "Restablecer Brynn Interactive",
            "Esto borrará configuraciones, multimedia, metas, alertas y datos locales de Brynn. Se creará un backup primero. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        create_data_backup("before_factory_reset")
        try:
            self.backend.stop()
        except Exception:
            pass
        for folder in (DATA_DIR, MEDIA_DIR, LOADER_MEDIA_DIR, BRANDING_DIR):
            try:
                if folder.exists():
                    shutil.rmtree(folder)
            except Exception:
                pass
        for file in (APPEARANCE_FILE, STREAMLABS_FILE, TWITCH_CONTROL_LOCAL_FILE, KICK_LOCAL_FILE, SETUP_STATE_FILE):
            try:
                if file.exists():
                    file.unlink()
            except Exception:
                pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        save_json_file(PROFILE_FILE, default_profile())
        QMessageBox.information(self, "Restablecimiento completo", "Brynn Interactive quedó restablecido. Ábrelo de nuevo para iniciar el asistente de configuración.")
        self.force_exit = True
        QApplication.instance().quit()

    def _load_settings_form(self):
        profile = load_profile()
        if hasattr(self, "profile_streamer"):
            self.profile_streamer.setText(str(profile.get("streamerName") or ""))
            owners = profile.get("owners") or {}
            self.profile_twitch.setText(str(owners.get("twitch") or ""))
            self.profile_tiktok.setText(str(owners.get("tiktok") or ""))
            self.profile_kick.setText(str(owners.get("kick") or ""))
            self.developer_mode.blockSignals(True)
            self.developer_mode.setChecked(bool(profile.get("developerMode", False)))
            self.developer_mode.blockSignals(False)
        try:
            data = http_json(f"{LOCAL_BASE}/api/social-stream-config", timeout=0.6)
            self.session_id.setText(str(data.get("sessionId", "")))
            self.session_password.setText(str(data.get("password", "false")))
        except Exception:
            pass

    def save_social_settings(self):
        try:
            data = http_json(
                f"{LOCAL_BASE}/api/social-stream-config",
                method="POST",
                payload={
                    "sessionId": self.session_id.text().strip(),
                    "password": self.session_password.text().strip() or "false",
                },
                timeout=1.2,
            )
            if data.get("ok"):
                self.settings_status.setText(
                    "Social Stream Ninja guardado. Brynn lo usará como transporte principal del chat al reconectar."
                )
        except Exception as exc:
            self.settings_status.setText(f"❌ No se pudo guardar: {exc}")

    def _startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        compiled = resource_path("dist") / "BrynnInteractiveDesktop" / "BrynnInteractiveDesktop.exe"
        if compiled.exists():
            return f'"{compiled}" --minimized'
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else Path(sys.executable)
        return f'"{executable}" "{Path(__file__).resolve()}" --minimized'

    def _startup_enabled(self) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "BrynnInteractiveDesktop")
                return bool(value)
        except Exception:
            return False

    def _set_startup(self, enabled: bool):
        if os.name != "nt":
            return
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key,
                        "BrynnInteractiveDesktop",
                        0,
                        winreg.REG_SZ,
                        self._startup_command(),
                    )
                else:
                    try:
                        winreg.DeleteValue(key, "BrynnInteractiveDesktop")
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            QMessageBox.warning(self, "Inicio con Windows", str(exc))
            self.start_windows.blockSignals(True)
            self.start_windows.setChecked(not enabled)
            self.start_windows.blockSignals(False)

    def _backend_failed(self, message: str):
        QMessageBox.critical(
            self,
            "Backend de Brynn Interactive",
            "No se pudo iniciar el servidor local:\n\n" + message,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "corner_grip"):
            self.corner_grip.move(max(0, self.width() - 18), max(0, self.height() - 18))
            self.corner_grip.setVisible(not self.isMaximized())
            self.corner_grip.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.sync_state()
        if hasattr(self, "corner_grip"):
            self.corner_grip.setVisible(not self.isMaximized())

    def show_from_tray(self):
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        else:
            self.show()
        if hasattr(self, "title_bar"):
            self.title_bar.sync_state()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent):
        if self.force_exit:
            event.accept()
            return

        if not self.minimize_to_tray.isChecked():
            self.force_exit = True
            self.backend.stop()
            self.tray.hide()
            event.accept()
            QTimer.singleShot(0, QApplication.instance().quit)
            return

        event.ignore()
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            "Brynn Interactive sigue funcionando en segundo plano.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def exit_completely(self):
        self.force_exit = True
        self.backend.stop()
        self.tray.hide()
        QApplication.instance().quit()


def _set_windows_app_user_model_id():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BrynnInteractive.Desktop")
    except Exception:
        pass


def main():
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("BrynnInteractive")
    app.setQuitOnLastWindowClosed(False)

    ensure_persistent_storage()

    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_NAME)
    if probe.waitForConnected(180):
        probe.write(b"show"); probe.flush(); probe.waitForBytesWritten(180); probe.disconnectFromServer(); return 0

    profile = load_profile()
    if not setup_is_complete(profile) and "--skip-setup" not in sys.argv:
        wizard = FirstRunWizard()
        if wizard.exec() != QDialog.DialogCode.Accepted: return 0

    appearance=load_appearance()
    splash=None
    show_splash=bool(appearance.get("startupSplashEnabled",True)) and "--minimized" not in sys.argv and "--no-splash" not in sys.argv
    if show_splash:
        splash=StartupSplashWindow(appearance); splash.show(); splash.set_progress(6,"Preparando almacenamiento…")

    QLocalServer.removeServer(SINGLE_INSTANCE_NAME)
    single_server = QLocalServer(app); single_server.listen(SINGLE_INSTANCE_NAME)
    if splash: splash.set_progress(18,"Cargando configuración…")

    backend = BackendController(); backend.start()
    if splash: splash.set_progress(34,"Iniciando servicios locales…")

    # Espera breve y visual al backend, sin congelar la pantalla de inicio.
    deadline=time.monotonic()+1.8
    while not server_is_alive() and time.monotonic()<deadline:
        if splash:
            elapsed=1.8-(deadline-time.monotonic()); splash.set_progress(34+int(max(0,min(1,elapsed/1.8))*20),"Conectando motor de Brynn…")
        app.processEvents(); time.sleep(.045)

    if splash: splash.set_progress(58,"Preparando interfaz…")
    window = BrynnDesktop(backend)
    if splash: splash.set_progress(82,"Cargando módulos y preferencias…")

    def accept_single_instance_request():
        while single_server.hasPendingConnections():
            client = single_server.nextPendingConnection()
            def on_ready(c=client):
                try:
                    data = bytes(c.readAll()).decode("utf-8", errors="ignore")
                    if "show" in data: window.show_from_tray()
                finally:
                    c.disconnectFromServer(); c.deleteLater()
            client.readyRead.connect(on_ready)
    single_server.newConnection.connect(accept_single_instance_request)
    app._brynn_single_instance_server = single_server

    if "--minimized" not in sys.argv: window.show()
    if splash:
        splash.set_progress(96,"Aplicando personalización…")
        elapsed_ms=int((time.monotonic()-splash._started_at)*1000)
        minimum=max(300,min(10000,int(appearance.get("startupSplashMinMs") or 1200)))
        delay=max(80,minimum-elapsed_ms)
        def finish_splash():
            if splash and splash.isVisible(): splash.set_progress(100,"Listo"); QTimer.singleShot(160,splash.close)
        QTimer.singleShot(delay,finish_splash)

    code = app.exec(); backend.stop(); return code


if __name__ == "__main__":
    raise SystemExit(main())
