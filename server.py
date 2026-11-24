from __future__ import annotations

import json
import math
import shutil
import threading
import time
import re
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
import secrets
import mimetypes
import tempfile
from collections import deque
from datetime import datetime, timedelta
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent

VENDOR_DIR = ROOT / "_vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import websocket
except Exception:
    websocket = None

from obs_controller import ObsController, ObsError
from automation_engine import AutomationEngine
from kick_connector import KickConnector, KickError, EVENTS as KICK_EVENT_TYPES
from follower_sync import FollowerCounters

DATA_DIR = Path(
    os.environ.get("BRYNN_DATA_DIR")
    or (ROOT / "data")
).resolve()
WEEKS_DIR = DATA_DIR / "semanas"

CURRENT_FILE = DATA_DIR / "ranking_actual.json"
BACKUP_FILE = DATA_DIR / "backup.json"

ECONOMY_FILE = DATA_DIR / "economia.json"
ECONOMY_BACKUP_FILE = DATA_DIR / "economia_backup.json"

COMMANDS_FILE = DATA_DIR / "commands.json"
COMMANDS_BACKUP_FILE = DATA_DIR / "commands_backup.json"

EMOTES_FILE = DATA_DIR / "emotes.json"
EMOTES_BACKUP_FILE = DATA_DIR / "emotes_backup.json"

ALERTS_FILE = DATA_DIR / "alerts.json"
ALERTS_BACKUP_FILE = DATA_DIR / "alerts_backup.json"
CHAT_DESIGN_FILE = DATA_DIR / "chat_design.json"
CHAT_DESIGN_BACKUP_FILE = DATA_DIR / "chat_design_backup.json"
DEBUG_EVENTS_FILE = DATA_DIR / "eventos_ssn.jsonl"
INTEGRATIONS_FILE = DATA_DIR / "integrations.json"
INTEGRATIONS_BACKUP_FILE = DATA_DIR / "integrations_backup.json"
SOCIAL_STREAM_FILE = DATA_DIR / "social_stream.json"
SOCIAL_STREAM_BACKUP_FILE = DATA_DIR / "social_stream_backup.json"

WEEKLY_REWARDS_CONFIG_FILE = DATA_DIR / "weekly_rewards_config.json"
WEEKLY_REWARDS_CONFIG_BACKUP_FILE = DATA_DIR / "weekly_rewards_config_backup.json"
WEEKLY_REWARDS_STATE_FILE = DATA_DIR / "weekly_rewards_state.json"
WEEKLY_REWARDS_STATE_BACKUP_FILE = DATA_DIR / "weekly_rewards_state_backup.json"
HALL_OF_FAME_FILE = DATA_DIR / "hall_of_fame.json"
HALL_OF_FAME_BACKUP_FILE = DATA_DIR / "hall_of_fame_backup.json"
LAYOUT_STUDIO_FILE = DATA_DIR / "layout_studio.json"
LAYOUT_STUDIO_BACKUP_FILE = DATA_DIR / "layout_studio_backup.json"

# V0.47: base comercial limpia + perfiles por instalación.
GOALS_FILE = DATA_DIR / "goals.json"
GOALS_BACKUP_FILE = DATA_DIR / "goals_backup.json"
GOALS_STATE_FILE = DATA_DIR / "goals_state.json"
GOALS_STATE_BACKUP_FILE = DATA_DIR / "goals_state_backup.json"
FLOATING_CHAT_CONFIG_FILE = DATA_DIR / "floating_chat_config.json"
FLOATING_CHAT_CONFIG_BACKUP_FILE = DATA_DIR / "floating_chat_config_backup.json"
PROFILE_FILE = DATA_DIR / "profile.json"

# V30: Streamlabs ya no guarda el token dentro de data/.
# Así no se pierde al cambiar de versión ni queda expuesto por el servidor web.
APPDATA_ROOT = Path(
    os.environ.get("BRYNN_APPDATA_ROOT")
    or (Path(os.environ.get("APPDATA")) / "BrynnInteractive" if os.environ.get("APPDATA") else (Path.home() / ".brynn_interactive" / "BrynnInteractive"))
)
BRYNN_GLOBAL_DIR = APPDATA_ROOT
STREAMLABS_GLOBAL_FILE = BRYNN_GLOBAL_DIR / "streamlabs.json"
STREAMLABS_GLOBAL_BACKUP_FILE = BRYNN_GLOBAL_DIR / "streamlabs_backup.json"
TWITCH_CONTROL_FILE = BRYNN_GLOBAL_DIR / "twitch_control.json"
TWITCH_CONTROL_BACKUP_FILE = BRYNN_GLOBAL_DIR / "twitch_control_backup.json"
KICK = KickConnector(BRYNN_GLOBAL_DIR / "kick.json")
FOLLOWERS = FollowerCounters(DATA_DIR, BRYNN_GLOBAL_DIR, lambda: load_twitch_control_private())
OBS_CONFIG_FILE = BRYNN_GLOBAL_DIR / "obs_config.json"
AUTOMATIONS_FILE = DATA_DIR / "automations.json"


USER_MEDIA_DIR = Path(
    os.environ.get("BRYNN_MEDIA_DIR")
    or (ROOT / "user_media")
).resolve()

LEGACY_FILE = ROOT / "ranking.json"

HOST = "127.0.0.1"
PORT = int(os.environ.get("BRYNN_PORT", "8765"))

# Puerto separado para exponer SOLO los webhooks de TikFinity Web.
# Nunca expongas el puerto 8765 completo a Internet.
WEBHOOK_HOST = "127.0.0.1"
WEBHOOK_PORT = int(os.environ.get("BRYNN_WEBHOOK_PORT", "8766"))

LOCK = threading.Lock()
GOALS_LOCK = threading.RLock()  # goal updates shared across webhook/poller threads

# Eventos efímeros que consume events_overlay.html.
EVENT_LOCK = threading.Lock()
EVENT_COUNTER = 0
EVENTS = deque(maxlen=120)

# Cambia cada vez que server.py arranca. Los overlays usan este ID para
# detectar reinicios del servidor sin tener que reiniciar OBS.
SERVER_SESSION_ID = secrets.token_hex(8)

DEBUG_EVENTS_LOCK = threading.Lock()
DEBUG_EVENTS = deque(maxlen=200)
DEBUG_EVENT_COUNTER = 0

# Historial unificado consumido por la ventana de chat flotante.
CHAT_EVENT_LOCK = threading.Lock()
CHAT_EVENT_COUNTER = 0
CHAT_EVENTS = deque(maxlen=2500)
CHAT_DEDUPE_LOCK = threading.Lock()
CHAT_DEDUPE = {}
COMMAND_DEDUPE_LOCK = threading.Lock()
COMMAND_DEDUPE = {}  # protect rewards/commands from duplicate SSN transport deliveries
VIEWER_LOCK = threading.Lock()
VIEWER_COUNTS = {"twitch": None, "tiktok": None, "kick": None}
VIEWER_UPDATED = {"twitch": None, "tiktok": None, "kick": None}
TWITCH_VIEWER_CACHE = {"value": None, "time": 0.0, "error": ""}

INTEGRATION_STATUS_LOCK = threading.Lock()
INTEGRATION_CONFIG_LOCK = threading.Lock()
STREAMLABS_SETTINGS_LOCK = threading.Lock()
INTEGRATION_DEDUPE_LOCK = threading.Lock()
INTEGRATION_DEDUPE = {}

OBS = ObsController(OBS_CONFIG_FILE)
AUTOMATION_ENGINE = None
AUTOMATION_DISPATCH_GUARD = threading.local()

STREAMLABS_BRIDGES_LOCK = threading.Lock()
STREAMLABS_BRIDGES = {}

INTEGRATION_STATUS = {
    "streamlabs": {
        "state": "disabled",
        "connected": False,
        "lastEvent": None,
        "lastError": "",
        "lastConnectedAt": None,
        "activeBridges": 0,
    },
    "kick": {
        "state": "disabled",
        "connected": False,
        "lastEvent": None,
        "lastError": "",
        "lastConnectedAt": None,
    },
    "tikfinity": {
        "state": "disabled",
        "connected": False,
        "lastEvent": None,
        "lastError": "",
        "lastConnectedAt": None,
    },
}

# Economía persistente.
ECONOMY_CONFIG_FILE = DATA_DIR / "economy_config.json"
ECONOMY_BRANDING_FILE = DATA_DIR / "economy_branding.json"
ECONOMY_BRANDING_BACKUP_FILE = DATA_DIR / "economy_branding_backup.json"

DEFAULT_ECONOMY_RATES = {
    "message": 2,
    "messageCooldownSeconds": 30,
    "likesPerGumpita": 5,
    "follow": 50,
    "join": 5,
    "joinCooldownSeconds": 1800,
    "share": 5,
    "subscription": 250,
    "giftBase": 25,
    "giftCoin": 2,
    "donationUsd": 60,
    "dailyBonus": 35,
    "dailyActivityBonus": 20,
    "activityMilestoneEvery": 10,
    "activityMilestoneBonus": 10,
}

ECONOMY_RATES = dict(DEFAULT_ECONOMY_RATES)



def load_economy_rates() -> dict:
    global ECONOMY_RATES
    ensure_storage()

    raw = {}

    if ECONOMY_CONFIG_FILE.exists():
        try:
            loaded = json.loads(
                ECONOMY_CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = {}

    merged = dict(DEFAULT_ECONOMY_RATES)

    for key, default in DEFAULT_ECONOMY_RATES.items():
        try:
            value = int(raw.get(key, default))
        except Exception:
            value = default

        if "CooldownSeconds" in key:
            value = max(0, min(value, 86400))
        elif key in {"likesPerGumpita", "activityMilestoneEvery"}:
            value = max(1, min(value, 100000))
        else:
            value = max(0, min(value, 1000000))

        merged[key] = value

    ECONOMY_RATES.clear()
    ECONOMY_RATES.update(merged)

    atomic_write_json(
        ECONOMY_CONFIG_FILE,
        ECONOMY_RATES
    )

    return dict(ECONOMY_RATES)


def save_economy_rates(payload: dict) -> dict:
    current = load_economy_rates()

    for key in DEFAULT_ECONOMY_RATES:
        if key not in payload:
            continue

        try:
            value = int(payload[key])
        except Exception:
            continue

        if "CooldownSeconds" in key:
            value = max(0, min(value, 86400))
        elif key in {"likesPerGumpita", "activityMilestoneEvery"}:
            value = max(1, min(value, 100000))
        else:
            value = max(0, min(value, 1000000))

        current[key] = value

    atomic_write_json(
        ECONOMY_CONFIG_FILE,
        current
    )

    return load_economy_rates()


def default_economy_branding() -> dict:
    return {
        "singular": "Gumpita",
        "plural": "Gumpitas",
        "symbol": "💀",
        "imageUrl": "",
        "balanceCommand": "gumpitas",
        "redeemPresentation": {
            "enabled": True,
            "hideDefaultCard": True,
            "durationMs": 4600,
            "position": "center",
            "offsetX": 0,
            "offsetY": 0,
            "scale": 100,
            "html": (
                "<div class='redeem-shell'>"
                "<div class='coin-wrap'>{currencyVisual}</div>"
                "<div class='redeem-kicker'>{platform} · CANJE</div>"
                "<h1>{user}</h1>"
                "<p>canjeó <b>{reward}</b></p>"
                "<div class='redeem-cost'>-{cost} {currencyName}</div>"
                "</div>"
            ),
            "css": (
                ":root{--accent:#ff6a00}*{box-sizing:border-box}"
                "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}"
                "body{display:grid;place-items:center;font-family:Arial,sans-serif;color:white}"
                ".redeem-shell{min-width:360px;max-width:72vw;padding:24px 30px;text-align:center;"
                "background:rgba(13,10,19,.94);border:1px solid color-mix(in srgb,var(--accent) 68%,transparent);"
                "border-radius:22px;box-shadow:0 20px 80px rgba(0,0,0,.48);animation:redeemIn .48s cubic-bezier(.2,.9,.2,1) both}"
                ".coin-wrap{display:flex;justify-content:center;margin-bottom:10px}.currency-image{width:72px;height:72px;object-fit:contain;filter:drop-shadow(0 8px 18px rgba(0,0,0,.4))}"
                ".currency-symbol{font-size:58px;line-height:1}.redeem-kicker{font-size:11px;letter-spacing:.18em;color:#b8c2d8}"
                "h1{margin:7px 0 2px;font-size:30px}p{margin:0;color:#d9deea;font-size:17px}.redeem-cost{margin-top:14px;font-size:22px;font-weight:900;color:#ffd34e}"
                "@keyframes redeemIn{from{opacity:0;transform:translateY(28px) scale(.82)}to{opacity:1;transform:none}}"
            ),
            "js": "",
        },
    }


def normalize_economy_branding(payload: dict | None) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    defaults = default_economy_branding()
    redeem_raw = raw.get("redeemPresentation") if isinstance(raw.get("redeemPresentation"), dict) else {}
    redeem = dict(defaults["redeemPresentation"])
    redeem.update(redeem_raw)
    command = re.sub(r"[^a-z0-9_-]", "", str(raw.get("balanceCommand") or defaults["balanceCommand"]).strip().lower().lstrip("!"))[:32] or "gumpitas"
    return {
        "singular": str(raw.get("singular") or defaults["singular"]).strip()[:40] or defaults["singular"],
        "plural": str(raw.get("plural") or defaults["plural"]).strip()[:40] or defaults["plural"],
        "symbol": str(raw.get("symbol") or defaults["symbol"]).strip()[:16] or defaults["symbol"],
        "imageUrl": str(raw.get("imageUrl") or "").strip()[:500],
        "balanceCommand": command,
        "redeemPresentation": {
            "enabled": bool(redeem.get("enabled", True)),
            "hideDefaultCard": bool(redeem.get("hideDefaultCard", True)),
            "durationMs": max(800, min(int(redeem.get("durationMs") or 4600), 30000)),
            "position": str(redeem.get("position") or "center") if str(redeem.get("position") or "center") in {"top-left","top-center","top-right","center-left","center","center-right","bottom-left","bottom-center","bottom-right"} else "center",
            "offsetX": max(-1920, min(int(float(redeem.get("offsetX") or 0)), 1920)),
            "offsetY": max(-1080, min(int(float(redeem.get("offsetY") or 0)), 1080)),
            "scale": max(25, min(int(float(redeem.get("scale") or 100)), 250)),
            "html": str(redeem.get("html") or defaults["redeemPresentation"]["html"])[:60000],
            "css": str(redeem.get("css") or defaults["redeemPresentation"]["css"])[:100000],
            "js": str(redeem.get("js") or "")[:100000],
        },
    }


def load_economy_branding() -> dict:
    ensure_storage()
    if not ECONOMY_BRANDING_FILE.exists():
        cfg = default_economy_branding()
        atomic_write_json(ECONOMY_BRANDING_FILE, cfg)
        return cfg
    try:
        raw = json.loads(ECONOMY_BRANDING_FILE.read_text(encoding="utf-8"))
        cfg = normalize_economy_branding(raw)
    except Exception:
        cfg = default_economy_branding()
    atomic_write_json(ECONOMY_BRANDING_FILE, cfg)
    return cfg


def save_economy_branding(payload: dict | None) -> dict:
    ensure_storage()
    if ECONOMY_BRANDING_FILE.exists():
        try:
            atomic_write_json(ECONOMY_BRANDING_BACKUP_FILE, json.loads(ECONOMY_BRANDING_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    cfg = normalize_economy_branding(payload)
    atomic_write_json(ECONOMY_BRANDING_FILE, cfg)
    return cfg


def currency_public() -> dict:
    cfg = load_economy_branding()
    return {
        "singular": cfg["singular"],
        "plural": cfg["plural"],
        "symbol": cfg["symbol"],
        "imageUrl": cfg["imageUrl"],
        "balanceCommand": cfg["balanceCommand"],
    }


def currency_name(amount) -> str:
    cfg = load_economy_branding()
    try:
        one = float(amount) == 1
    except Exception:
        one = False
    return cfg["singular"] if one else cfg["plural"]


# Cuentas propietarias configuradas por cada instalación.
# Tienen Gumpitas infinitas, pueden probar canjes y no compiten en rankings.
def load_owner_test_users() -> dict:
    try:
        raw = json.loads(PROFILE_FILE.read_text(encoding="utf-8")) if PROFILE_FILE.exists() else {}
    except Exception:
        raw = {}
    owners = raw.get("owners") if isinstance(raw, dict) else {}
    owners = owners if isinstance(owners, dict) else {}
    result = {}
    for platform in ("twitch", "tiktok", "kick"):
        username = str(owners.get(platform) or "").strip().lstrip("@")
        if not username:
            continue
        key = f"{platform}:{username.lower()}"
        result[key] = {"key": key, "username": username, "platform": platform}
    return result


TEST_USERS = load_owner_test_users()


def is_test_user_key(key: str) -> bool:
    # V0.53.2: leer el perfil en cada comprobación evita que un cambio de
    # propietario requiera reiniciar el backend para obtener el bypass.
    return str(key or "").strip().lower() in load_owner_test_users()


DEFAULT_COMMANDS = [{'id': 'glitch', 'name': 'Glitch de pantalla', 'cost': 60, 'icon': '⚡', 'description': 'Provoca un glitch rápido en toda la escena.', 'effect': 'glitch', 'aliases': ['glitch'], 'enabled': True, 'durationMs': 1800, 'animation': 'glitch', 'position': 'fullscreen', 'size': 100, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '', 'audioVolume': 0.8}, {'id': 'niebla', 'name': 'Niebla embrujada', 'cost': 80, 'icon': '🌫️', 'description': 'Invoca niebla spooky sobre el stream.', 'effect': 'fog', 'aliases': ['niebla', 'fog'], 'enabled': True, 'durationMs': 5200, 'animation': 'float', 'position': 'fullscreen', 'size': 100, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '', 'audioVolume': 0.8}, {'id': 'murcielagos', 'name': 'Ataque de murciélagos', 'cost': 100, 'icon': '🦇', 'description': 'Una bandada atraviesa la pantalla con aleteos.', 'effect': 'bats', 'aliases': ['murcielagos', 'murciélagos', 'bats'], 'enabled': True, 'durationMs': 4600, 'animation': 'fly', 'position': 'fullscreen', 'size': 62, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '/assets/audio/bat_wings.wav', 'audioVolume': 0.78}, {'id': 'calabazas', 'name': 'Lluvia de calabazas', 'cost': 120, 'icon': '🎃', 'description': 'Calabazas caen por la pantalla.', 'effect': 'pumpkins', 'aliases': ['calabazas', 'calabaza', 'pumpkins'], 'enabled': True, 'durationMs': 4700, 'animation': 'fall', 'position': 'fullscreen', 'size': 100, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '', 'audioVolume': 0.8}, {'id': 'bonk', 'name': 'BONK!', 'cost': 140, 'icon': '🔨', 'description': 'Golpe gigante estilo meme sobre el stream.', 'effect': 'bonk', 'aliases': ['bonk', 'golpe'], 'enabled': True, 'durationMs': 1300, 'animation': 'bounce', 'position': 'center', 'size': 62, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '', 'audioVolume': 0.8}, {'id': 'susto', 'name': 'Susto terrorífico', 'cost': 220, 'icon': '☠️', 'description': 'Cara terrorífica con golpe visual y grito sintético.', 'effect': 'scare', 'aliases': ['susto', 'jumpscare', 'scare'], 'enabled': True, 'durationMs': 2450, 'animation': 'zoom', 'position': 'fullscreen', 'size': 62, 'showCard': True, 'visualUrl': '', 'visualType': '', 'badgeUrl': '', 'audioUrl': '/assets/audio/scare_scream_synth.wav', 'audioVolume': 0.95}]



# ============================================================
# Común
# ============================================================

def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def current_period_key() -> str:
    now = datetime.now().astimezone()
    monday = (now - timedelta(days=now.weekday())).date()
    return monday.isoformat()


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEEKS_DIR.mkdir(parents=True, exist_ok=True)
    USER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, payload: dict) -> None:
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


# ============================================================
# Social Stream Ninja - configuración persistente
# ============================================================

def default_social_stream_config() -> dict:
    return {
        "sessionId": "",
        "password": "false",
    }


def load_social_stream_config() -> dict:
    ensure_storage()
    base = default_social_stream_config()

    if SOCIAL_STREAM_FILE.exists():
        try:
            raw = json.loads(
                SOCIAL_STREAM_FILE.read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(raw, dict):
                base.update(raw)
        except Exception:
            try:
                raw = json.loads(
                    SOCIAL_STREAM_BACKUP_FILE.read_text(
                        encoding="utf-8"
                    )
                )
                if isinstance(raw, dict):
                    base.update(raw)
            except Exception:
                pass

    base["sessionId"] = str(
        base.get("sessionId", "") or ""
    ).strip()
    base["password"] = str(
        base.get("password", "false") or "false"
    ).strip() or "false"
    return base


def save_social_stream_config(payload: dict) -> dict:
    ensure_storage()
    current = load_social_stream_config()

    if "sessionId" in payload:
        current["sessionId"] = str(
            payload.get("sessionId") or ""
        ).strip()

    if "password" in payload:
        current["password"] = str(
            payload.get("password") or "false"
        ).strip() or "false"

    if SOCIAL_STREAM_FILE.exists():
        try:
            previous = json.loads(
                SOCIAL_STREAM_FILE.read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(previous, dict):
                atomic_write_json(
                    SOCIAL_STREAM_BACKUP_FILE,
                    previous
                )
        except Exception:
            pass

    atomic_write_json(
        SOCIAL_STREAM_FILE,
        current
    )
    return current


# ============================================================
# Ranking semanal
# ============================================================

def empty_state(period: str | None = None) -> dict:
    return {
        "period": period or current_period_key(),
        "users": {},
        "updatedAt": now_iso(),
    }


def make_backup_of_current() -> None:
    if not CURRENT_FILE.exists():
        return

    try:
        payload = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
        atomic_write_json(BACKUP_FILE, payload)
    except Exception:
        pass


def save_current(state: dict, make_backup: bool = True) -> None:
    ensure_storage()
    state = dict(state)
    state["updatedAt"] = now_iso()

    if make_backup:
        make_backup_of_current()

    atomic_write_json(CURRENT_FILE, state)


def migrate_legacy_if_needed() -> None:
    ensure_storage()

    if CURRENT_FILE.exists():
        return

    if LEGACY_FILE.exists():
        try:
            payload = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))

            if isinstance(payload, dict):
                payload.setdefault("period", current_period_key())
                payload.setdefault("users", {})
                payload.pop("history", None)

                save_current(payload, make_backup=False)
                atomic_write_json(BACKUP_FILE, payload)

                migrated = ROOT / "ranking_migrado_v6.json"

                try:
                    shutil.copy2(LEGACY_FILE, migrated)
                except Exception:
                    pass

                print("Se migró ranking.json -> data/ranking_actual.json")
                return
        except Exception:
            pass

    state = empty_state()
    save_current(state, make_backup=False)
    atomic_write_json(BACKUP_FILE, state)


def load_current() -> dict:
    migrate_legacy_if_needed()

    try:
        data = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise ValueError("ranking_actual.json no contiene un objeto")

        data.setdefault("period", current_period_key())
        data.setdefault("users", {})

        return data

    except Exception:
        print("ranking_actual.json está dañado; intentando backup.json...")

        try:
            backup = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))

            if not isinstance(backup, dict):
                raise ValueError("backup inválido")

            backup.setdefault("period", current_period_key())
            backup.setdefault("users", {})

            save_current(backup, make_backup=False)
            return backup

        except Exception:
            state = empty_state()
            save_current(state, make_backup=False)
            atomic_write_json(BACKUP_FILE, state)
            return state


def sorted_users(state: dict) -> list[dict]:
    values = list(state.get("users", {}).values())

    values.sort(
        key=lambda u: (
            float(u.get("score", 0)),
            int(u.get("counters", {}).get("gifts", 0)),
            int(u.get("counters", {}).get("messages", 0)),
        ),
        reverse=True,
    )

    result = []

    for index, user in enumerate(values, start=1):
        row = dict(user)
        row["rank"] = index
        result.append(row)

    return result


def weekly_filename(period: str) -> Path:
    safe = period.replace("/", "-").replace("\\", "-")
    return WEEKS_DIR / f"semana_{safe}.json"


def archive_week(state: dict, manual: bool = False) -> Path:
    period = str(state.get("period") or current_period_key())

    archived = {
        "period": period,
        "closedAt": now_iso(),
        "manualReset": bool(manual),
        "top": sorted_users(state)[:10],
        "users": state.get("users", {}),
    }

    if manual:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        path = WEEKS_DIR / f"semana_{period}_manual_{stamp}.json"
    else:
        path = weekly_filename(period)

    atomic_write_json(path, archived)
    try:
        update_hall_of_fame(archived, path.name)
    except Exception as exc:
        print(f"Hall of Fame: no se pudo actualizar: {exc}")
    return path


def archive_and_reset_if_needed(state: dict) -> dict:
    wanted = current_period_key()

    if state.get("period") == wanted:
        return state

    if state.get("users"):
        archived_path = archive_week(state, manual=False)
        print(f"Semana archivada: {archived_path.name}")
        try:
            archived_payload = json.loads(archived_path.read_text(encoding="utf-8"))
            apply_weekly_rewards_from_archive(archived_payload, grant_bonuses=True, force=False)
            print("Recompensas semanales activadas para la nueva semana")
        except Exception as exc:
            print(f"Recompensas semanales: no se pudieron activar: {exc}")

    new_state = empty_state(wanted)
    save_current(new_state, make_backup=True)
    return new_state


def list_week_files() -> list[dict]:
    ensure_storage()
    rows = []

    for path in sorted(WEEKS_DIR.glob("semana_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))

            rows.append(
                {
                    "file": path.name,
                    "period": payload.get("period"),
                    "closedAt": payload.get("closedAt"),
                    "manualReset": payload.get("manualReset", False),
                    "top": payload.get("top", [])[:3],
                }
            )
        except Exception:
            continue

    return rows


def public_state(state: dict) -> dict:
    rows = sorted_users(state)

    return {
        "period": state.get("period"),
        "updatedAt": state.get("updatedAt"),
        "top": rows[:3],
        "ranking": rows,
        "archives": list_week_files(),
    }



# ============================================================
# Recompensas semanales / Hall of Fame
# ============================================================

WEEKLY_TIER_ORDER = ("top1", "top2", "top3", "top10")


def default_weekly_tier(
    tier_id: str,
    label: str,
    min_rank: int,
    max_rank: int,
    title: str,
    badge: str,
    accent: str,
) -> dict:
    return {
        "id": tier_id,
        "label": label,
        "minRank": min_rank,
        "maxRank": max_rank,
        "enabled": True,
        "title": title,
        "badgeLabel": badge,
        "badgeIcon": "✦",
        "badgeHtml": "<span class='weekly-badge-symbol'>✦</span>",
        "badgeCss": (
            ".weekly-badge-symbol{display:inline-grid;place-items:center;width:22px;height:22px;"
            "border:1px solid var(--accent);border-radius:7px;color:var(--accent);font-weight:900;"
            "box-shadow:0 0 12px color-mix(in srgb,var(--accent) 28%,transparent);}"
        ),
        "accent": accent,
        "commandIds": [],
        "emoteIds": [],
        "gumpitasBonus": 0,
        "discountPct": 0,
        "entryEnabled": True,
        "entryCooldownHours": 12,
        "entryDurationMs": 5200,
        "entryHtml": (
            "<div class='weekly-entry'>"
            "<div class='weekly-symbol'>{badgeHtml}</div>"
            "<div class='weekly-badge'>{badge}</div>"
            "<div class='weekly-kicker'>RANK #{rank} · {platform}</div>"
            "<h1>{title}</h1>"
            "<h2>{user}</h2>"
            "<p>{score} puntos la semana pasada</p>"
            "</div>"
        ),
        "entryCss": (
            ":root{--accent:" + accent + ";}"
            "*{box-sizing:border-box}"
            "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;}"
            "body{display:grid;place-items:center;font-family:Arial,sans-serif;}"
            ".weekly-entry{min-width:520px;max-width:76vw;padding:28px 34px;text-align:center;"
            "color:#fff;background:linear-gradient(145deg,rgba(10,12,20,.96),rgba(28,20,42,.94));"
            "border:2px solid var(--accent);border-radius:24px;box-shadow:0 0 42px color-mix(in srgb,var(--accent) 35%,transparent);"
            "animation:weeklyIn .55s cubic-bezier(.2,.9,.2,1) both;}"
            ".weekly-symbol{display:flex;justify-content:center;align-items:center;margin-bottom:9px;}"
            ".weekly-badge{display:inline-block;padding:7px 14px;border:1px solid var(--accent);"
            "border-radius:999px;color:var(--accent);font-weight:800;letter-spacing:.12em;}"
            ".weekly-kicker{margin-top:14px;color:#aeb7ca;font-size:13px;letter-spacing:.14em;}"
            "h1{margin:10px 0 4px;color:var(--accent);font-size:30px;}"
            "h2{margin:0;font-size:38px;}p{margin:10px 0 0;color:#c8ccda;}"
            "@keyframes weeklyIn{from{opacity:0;transform:scale(.72) translateY(30px)}to{opacity:1;transform:none}}"
        ),
        "entryJs": "",
    }


def default_weekly_rewards_config() -> dict:
    return {
        "enabled": True,
        "inheritLowerTiers": True,
        "awardOnManualReset": False,
        "ownerBypassEnabled": True,
        "ownerTestTier": "none",
        "resourceAccessVersion": 2,
        "reservedCommandIds": [],
        "reservedEmoteIds": [],
        "updatedAt": now_iso(),
        "tiers": {
            "top1": default_weekly_tier(
                "top1", "Top 1", 1, 1,
                "MVP DE LA SEMANA", "MVP", "#FFD34E",
            ),
            "top2": default_weekly_tier(
                "top2", "Top 2", 2, 2,
                "GUMPITA ÉLITE", "TOP 2", "#B9C7FF",
            ),
            "top3": default_weekly_tier(
                "top3", "Top 3", 3, 3,
                "GUMPITA DESTACADA", "TOP 3", "#FF9E66",
            ),
            "top10": default_weekly_tier(
                "top10", "Top 10", 4, 10,
                "TOP 10 SEMANAL", "TOP 10", "#53E6FF",
            ),
        },
    }


def normalize_weekly_rewards_config(payload: dict | None) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    defaults = default_weekly_rewards_config()
    result = {
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "inheritLowerTiers": bool(raw.get("inheritLowerTiers", True)),
        "awardOnManualReset": bool(raw.get("awardOnManualReset", False)),
        "ownerBypassEnabled": bool(raw.get("ownerBypassEnabled", True)),
        "ownerTestTier": str(raw.get("ownerTestTier") or "none").lower() if str(raw.get("ownerTestTier") or "none").lower() in {"none", *WEEKLY_TIER_ORDER} else "none",
        "resourceAccessVersion": max(1, min(int(raw.get("resourceAccessVersion") or 1), 2)),
        "reservedCommandIds": [str(x).strip().lower()[:40] for x in (raw.get("reservedCommandIds") or []) if str(x).strip()][:200],
        "reservedEmoteIds": [str(x).strip().lower()[:40] for x in (raw.get("reservedEmoteIds") or []) if str(x).strip()][:200],
        "updatedAt": str(raw.get("updatedAt") or now_iso()),
        "tiers": {},
    }

    raw_tiers = raw.get("tiers") if isinstance(raw.get("tiers"), dict) else {}
    for tier_id in WEEKLY_TIER_ORDER:
        base = dict(defaults["tiers"][tier_id])
        candidate = raw_tiers.get(tier_id) if isinstance(raw_tiers.get(tier_id), dict) else {}
        base.update(candidate)
        base["id"] = tier_id
        base["minRank"] = int(defaults["tiers"][tier_id]["minRank"])
        base["maxRank"] = int(defaults["tiers"][tier_id]["maxRank"])
        base["enabled"] = bool(base.get("enabled", True))
        base["title"] = str(base.get("title") or defaults["tiers"][tier_id]["title"])[:100]
        base["badgeLabel"] = str(base.get("badgeLabel") or defaults["tiers"][tier_id]["badgeLabel"])[:40]
        base["badgeIcon"] = str(base.get("badgeIcon") or "✦")[:12]
        base["badgeHtml"] = str(base.get("badgeHtml") or defaults["tiers"][tier_id]["badgeHtml"])[:20000]
        base["badgeCss"] = str(base.get("badgeCss") or defaults["tiers"][tier_id]["badgeCss"])[:40000]
        base["accent"] = str(base.get("accent") or defaults["tiers"][tier_id]["accent"])[:32]
        base["commandIds"] = [
            str(x).strip().lower()[:40]
            for x in (base.get("commandIds") or [])
            if str(x).strip()
        ][:100]
        base["emoteIds"] = [
            str(x).strip().lower()[:40]
            for x in (base.get("emoteIds") or [])
            if str(x).strip()
        ][:100]
        base["gumpitasBonus"] = max(0, min(int(base.get("gumpitasBonus") or 0), 1000000))
        base["discountPct"] = max(0, min(int(base.get("discountPct") or 0), 100))
        base["entryEnabled"] = bool(base.get("entryEnabled", True))
        base["entryCooldownHours"] = max(0, min(float(base.get("entryCooldownHours") or 0), 168))
        base["entryDurationMs"] = max(800, min(int(base.get("entryDurationMs") or 5200), 30000))
        base["entryHtml"] = str(base.get("entryHtml") or defaults["tiers"][tier_id]["entryHtml"])
        base["entryCss"] = str(base.get("entryCss") or defaults["tiers"][tier_id]["entryCss"])
        base["entryJs"] = str(base.get("entryJs") or "")
        result["tiers"][tier_id] = base

    return result


def _weekly_reserved_field(kind: str) -> str:
    return "reservedCommandIds" if str(kind).lower() == "command" else "reservedEmoteIds"


def migrate_weekly_resource_access_v2(config: dict) -> tuple[dict, bool]:
    """Migra la exclusividad antigua hacia Recompensas Semanales.

    Desde V0.53.3 la fuente de verdad para acceso exclusivo es
    weekly_rewards_config.json. Los accessMode=exclusive heredados que todavía
    no pertenecían a ningún tier se conservan como recursos reservados sin
    acceso, para no volverlos públicos accidentalmente.
    """
    cfg = dict(config or {})
    if int(cfg.get("resourceAccessVersion") or 1) >= 2:
        return cfg, False

    assigned_emotes = set()
    for tier_id in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(tier_id, {})
        assigned_emotes.update(str(x).strip().lower() for x in (tier.get("emoteIds") or []) if str(x).strip())

    reserved_emotes = {str(x).strip().lower() for x in (cfg.get("reservedEmoteIds") or []) if str(x).strip()}
    try:
        for item in load_emotes():
            item_id = str(item.get("id") or "").strip().lower()
            if item_id and str(item.get("accessMode") or "general").lower() == "exclusive" and item_id not in assigned_emotes:
                reserved_emotes.add(item_id)
    except Exception:
        pass

    cfg["reservedEmoteIds"] = sorted(reserved_emotes)[:200]
    cfg["reservedCommandIds"] = sorted({str(x).strip().lower() for x in (cfg.get("reservedCommandIds") or []) if str(x).strip()})[:200]
    cfg["resourceAccessVersion"] = 2
    return normalize_weekly_rewards_config(cfg), True


def weekly_reserved_ids(kind: str, config: dict | None = None) -> list[str]:
    cfg = config or load_weekly_rewards_config()
    return [str(x).strip().lower() for x in (cfg.get(_weekly_reserved_field(kind)) or []) if str(x).strip()]


def replace_weekly_resource_id(kind: str, old_id: str, new_id: str) -> dict:
    """Renombra referencias semanales sin cambiar quién tiene acceso."""
    cfg = load_weekly_rewards_config()
    field = "commandIds" if str(kind).lower() == "command" else "emoteIds"
    reserved_field = _weekly_reserved_field(kind)
    old_id = str(old_id or "").strip().lower()
    new_id = str(new_id or "").strip().lower()
    if not old_id or not new_id or old_id == new_id:
        return cfg
    for tier_id in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(tier_id, {})
        values = [str(x).strip().lower() for x in (tier.get(field) or []) if str(x).strip()]
        tier[field] = list(dict.fromkeys(new_id if x == old_id else x for x in values))[:100]
    reserved = [str(x).strip().lower() for x in (cfg.get(reserved_field) or []) if str(x).strip()]
    cfg[reserved_field] = list(dict.fromkeys(new_id if x == old_id else x for x in reserved))[:200]
    return save_weekly_rewards_config(cfg, make_backup=True)


def remove_weekly_resource_id(kind: str, item_id: str) -> dict:
    cfg = load_weekly_rewards_config()
    field = "commandIds" if str(kind).lower() == "command" else "emoteIds"
    reserved_field = _weekly_reserved_field(kind)
    wanted = str(item_id or "").strip().lower()
    for tier_id in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(tier_id, {})
        tier[field] = [str(x).strip().lower() for x in (tier.get(field) or []) if str(x).strip() and str(x).strip().lower() != wanted]
    cfg[reserved_field] = [str(x).strip().lower() for x in (cfg.get(reserved_field) or []) if str(x).strip() and str(x).strip().lower() != wanted]
    return save_weekly_rewards_config(cfg, make_backup=True)


def save_weekly_rewards_config(payload: dict, make_backup: bool = True) -> dict:
    ensure_storage()
    config = normalize_weekly_rewards_config(payload)
    config["updatedAt"] = now_iso()
    if make_backup and WEEKLY_REWARDS_CONFIG_FILE.exists():
        try:
            atomic_write_json(
                WEEKLY_REWARDS_CONFIG_BACKUP_FILE,
                json.loads(WEEKLY_REWARDS_CONFIG_FILE.read_text(encoding="utf-8")),
            )
        except Exception:
            pass
    atomic_write_json(WEEKLY_REWARDS_CONFIG_FILE, config)
    return config


def load_weekly_rewards_config() -> dict:
    ensure_storage()
    if not WEEKLY_REWARDS_CONFIG_FILE.exists():
        config = default_weekly_rewards_config()
        save_weekly_rewards_config(config, make_backup=False)
        atomic_write_json(WEEKLY_REWARDS_CONFIG_BACKUP_FILE, config)
        return config
    try:
        raw = json.loads(WEEKLY_REWARDS_CONFIG_FILE.read_text(encoding="utf-8"))
        config = normalize_weekly_rewards_config(raw)
        config, migrated = migrate_weekly_resource_access_v2(config)
        if migrated:
            save_weekly_rewards_config(config, make_backup=True)
        return config
    except Exception:
        try:
            raw = json.loads(WEEKLY_REWARDS_CONFIG_BACKUP_FILE.read_text(encoding="utf-8"))
            config = normalize_weekly_rewards_config(raw)
            config, _ = migrate_weekly_resource_access_v2(config)
            save_weekly_rewards_config(config, make_backup=False)
            return config
        except Exception:
            config = default_weekly_rewards_config()
            save_weekly_rewards_config(config, make_backup=False)
            return config


def empty_weekly_rewards_state() -> dict:
    return {
        "period": current_period_key(),
        "sourcePeriod": None,
        "activatedAt": None,
        "expiresAt": None,
        "winners": [],
        "lastEntrances": {},
        "updatedAt": now_iso(),
    }


def save_weekly_rewards_state(state: dict, make_backup: bool = True) -> dict:
    ensure_storage()
    clean = dict(state or {})
    clean.setdefault("period", current_period_key())
    clean.setdefault("sourcePeriod", None)
    clean.setdefault("activatedAt", None)
    clean.setdefault("expiresAt", None)
    clean.setdefault("winners", [])
    clean.setdefault("lastEntrances", {})
    clean["updatedAt"] = now_iso()
    if make_backup and WEEKLY_REWARDS_STATE_FILE.exists():
        try:
            atomic_write_json(
                WEEKLY_REWARDS_STATE_BACKUP_FILE,
                json.loads(WEEKLY_REWARDS_STATE_FILE.read_text(encoding="utf-8")),
            )
        except Exception:
            pass
    atomic_write_json(WEEKLY_REWARDS_STATE_FILE, clean)
    return clean


def load_weekly_rewards_state() -> dict:
    ensure_storage()
    if not WEEKLY_REWARDS_STATE_FILE.exists():
        state = empty_weekly_rewards_state()
        save_weekly_rewards_state(state, make_backup=False)
        return state
    try:
        state = json.loads(WEEKLY_REWARDS_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("weekly_rewards_state inválido")
        state.setdefault("winners", [])
        state.setdefault("lastEntrances", {})
        return state
    except Exception:
        try:
            state = json.loads(WEEKLY_REWARDS_STATE_BACKUP_FILE.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("backup inválido")
            save_weekly_rewards_state(state, make_backup=False)
            return state
        except Exception:
            return empty_weekly_rewards_state()


def load_hall_of_fame() -> dict:
    ensure_storage()
    if not HALL_OF_FAME_FILE.exists():
        payload = {"weeks": [], "updatedAt": now_iso()}
        atomic_write_json(HALL_OF_FAME_FILE, payload)
        atomic_write_json(HALL_OF_FAME_BACKUP_FILE, payload)
        return payload
    try:
        payload = json.loads(HALL_OF_FAME_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("hall_of_fame inválido")
        payload.setdefault("weeks", [])
        return payload
    except Exception:
        try:
            payload = json.loads(HALL_OF_FAME_BACKUP_FILE.read_text(encoding="utf-8"))
            payload.setdefault("weeks", [])
            return payload
        except Exception:
            return {"weeks": [], "updatedAt": now_iso()}


def save_hall_of_fame(payload: dict) -> dict:
    ensure_storage()
    if HALL_OF_FAME_FILE.exists():
        try:
            atomic_write_json(
                HALL_OF_FAME_BACKUP_FILE,
                json.loads(HALL_OF_FAME_FILE.read_text(encoding="utf-8")),
            )
        except Exception:
            pass
    clean = dict(payload or {})
    clean.setdefault("weeks", [])
    clean["weeks"] = list(clean.get("weeks") or [])[-104:]
    clean["updatedAt"] = now_iso()
    atomic_write_json(HALL_OF_FAME_FILE, clean)
    return clean


def weekly_category_winners(rows: list[dict]) -> dict:
    def best(field: str, nested: bool = True):
        if not rows:
            return None
        if nested:
            return max(rows, key=lambda r: float((r.get("counters") or {}).get(field, 0) or 0))
        return max(rows, key=lambda r: float(r.get(field, 0) or 0))

    supporter = None
    if rows:
        supporter = max(
            rows,
            key=lambda r: (
                float((r.get("counters") or {}).get("giftCoins", 0) or 0)
                + float((r.get("counters") or {}).get("donationUsd", 0) or 0) * 100
                + float((r.get("counters") or {}).get("gifts", 0) or 0) * 10
            ),
        )

    return {
        "mostMessages": best("messages"),
        "mostLikes": best("likes"),
        "supporter": supporter,
    }


def hall_user_summary() -> list[dict]:
    hall = load_hall_of_fame()
    users: dict[str, dict] = {}
    for week in hall.get("weeks", []):
        for row in week.get("top", [])[:10]:
            key = str(row.get("key") or "")
            if not key:
                continue
            entry = users.setdefault(
                key,
                {
                    "key": key,
                    "username": row.get("username", "Usuario"),
                    "platform": row.get("platform", ""),
                    "crowns": 0,
                    "top3": 0,
                    "top10": 0,
                    "bestScore": 0,
                },
            )
            rank = int(row.get("rank") or 999)
            entry["username"] = row.get("username", entry["username"])
            entry["platform"] = row.get("platform", entry["platform"])
            entry["top10"] += 1
            if rank <= 3:
                entry["top3"] += 1
            if rank == 1:
                entry["crowns"] += 1
            entry["bestScore"] = max(float(entry.get("bestScore", 0)), float(row.get("score", 0) or 0))
    return sorted(users.values(), key=lambda x: (x["crowns"], x["top3"], x["top10"], x["bestScore"]), reverse=True)


def update_hall_of_fame(archived: dict, source_file: str = "") -> dict:
    if not isinstance(archived, dict):
        return load_hall_of_fame()
    hall = load_hall_of_fame()
    all_rows = sorted_users({"users": archived.get("users", {})})
    rows = list(archived.get("top") or all_rows[:10])
    entry = {
        "id": f"{archived.get('period')}::{archived.get('closedAt')}::{bool(archived.get('manualReset'))}",
        "period": archived.get("period"),
        "closedAt": archived.get("closedAt"),
        "manualReset": bool(archived.get("manualReset", False)),
        "sourceFile": source_file,
        "top": rows[:10],
        "categories": weekly_category_winners(all_rows or rows),
    }
    weeks = [w for w in hall.get("weeks", []) if w.get("id") != entry["id"]]
    weeks.append(entry)
    weeks.sort(key=lambda w: str(w.get("closedAt") or ""))
    hall["weeks"] = weeks[-104:]
    return save_hall_of_fame(hall)


def weekly_primary_tier_for_rank(rank: int) -> str | None:
    rank = int(rank or 0)
    if rank == 1:
        return "top1"
    if rank == 2:
        return "top2"
    if rank == 3:
        return "top3"
    if 4 <= rank <= 10:
        return "top10"
    return None


def weekly_eligible_tiers(primary_tier: str | None, config: dict | None = None) -> list[str]:
    if primary_tier not in WEEKLY_TIER_ORDER:
        return []
    cfg = config or load_weekly_rewards_config()
    index = WEEKLY_TIER_ORDER.index(primary_tier)
    if cfg.get("inheritLowerTiers", True):
        return list(WEEKLY_TIER_ORDER[index:])
    return [primary_tier]


def weekly_state_is_active(state: dict | None = None) -> bool:
    state = state or load_weekly_rewards_state()
    if str(state.get("period") or "") != current_period_key():
        return False
    expires = str(state.get("expiresAt") or "")
    if expires:
        try:
            if datetime.fromisoformat(expires) <= datetime.now().astimezone():
                return False
        except Exception:
            pass
    return bool(state.get("winners"))


def weekly_winner_for_key(key: str, state: dict | None = None) -> dict | None:
    wanted = str(key or "").strip().lower()
    if not wanted:
        return None
    state = state or load_weekly_rewards_state()
    if not weekly_state_is_active(state):
        return None
    for winner in state.get("winners", []):
        if str(winner.get("key") or "").strip().lower() == wanted:
            return dict(winner)
    return None


def weekly_item_tiers(kind: str, item_id: str, config: dict | None = None) -> list[str]:
    cfg = config or load_weekly_rewards_config()
    field = "commandIds" if kind == "command" else "emoteIds"
    wanted = str(item_id or "").strip().lower()
    result = []
    for tier_id in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(tier_id, {})
        if tier.get("enabled", True) and wanted in [str(x).lower() for x in tier.get(field, [])]:
            result.append(tier_id)
    return result


def _weekly_item_marked_exclusive(kind: str, item_id: str) -> bool:
    """Compatibilidad: ahora significa reservado desde Recompensas Semanales."""
    wanted = str(item_id or "").strip().lower()
    return bool(wanted and wanted in weekly_reserved_ids(kind))


def weekly_access_for_item(user_key: str, kind: str, item_id: str) -> dict:
    assigned = weekly_item_tiers(kind, item_id)
    cfg = load_weekly_rewards_config()
    state = load_weekly_rewards_state()
    active = weekly_state_is_active(state)
    marked_exclusive = _weekly_item_marked_exclusive(kind, item_id)
    exclusive = bool(assigned) or marked_exclusive
    expires_at = state.get("expiresAt") if active else None

    if not exclusive:
        return {
            "allowed": True, "exclusive": False, "tiers": [], "winner": None,
            "ownerOverride": False, "active": active, "expiresAt": expires_at,
            "reason": "general",
        }

    # El propietario siempre puede probar/usar recompensas semanales si el
    # bypass está habilitado, incluso antes de asignarlas a un tier.
    if is_test_user_key(user_key) and cfg.get("ownerBypassEnabled", True):
        return {
            "allowed": True, "exclusive": True, "tiers": assigned, "winner": None,
            "ownerOverride": True, "active": active, "expiresAt": expires_at,
            "reason": "owner",
        }

    # Un recurso reservado desde Recompensas pero todavía sin tier queda
    # bloqueado para viewers, en vez de volverse público por accidente.
    if marked_exclusive and not assigned:
        return {
            "allowed": False, "exclusive": True, "tiers": [], "winner": None,
            "ownerOverride": False, "active": active, "expiresAt": expires_at,
            "reason": "unassigned",
        }

    winner = weekly_winner_for_key(user_key, state)
    if not winner:
        return {
            "allowed": False, "exclusive": True, "tiers": assigned, "winner": None,
            "ownerOverride": False, "active": active, "expiresAt": expires_at,
            "reason": "no_active_reward" if not active else "not_winner",
        }
    eligible = weekly_eligible_tiers(winner.get("tier"), cfg)
    allowed = any(tier in eligible for tier in assigned)
    return {
        "allowed": allowed, "exclusive": True, "tiers": assigned, "winner": winner,
        "ownerOverride": False, "active": active, "expiresAt": expires_at,
        "reason": "winner" if allowed else "wrong_tier",
    }


def weekly_item_access_summary(kind: str, item_id: str) -> dict:
    """Resumen administrativo: tiers, vigencia y usuarios con acceso actual."""
    cfg = load_weekly_rewards_config()
    assigned = weekly_item_tiers(kind, item_id, cfg)
    marked = _weekly_item_marked_exclusive(kind, item_id)
    active_payload = weekly_public_active()
    allowed_users = []
    for row in active_payload.get("winners", []):
        eligible = row.get("eligibleTiers") or weekly_eligible_tiers(row.get("tier"), cfg)
        if assigned and any(t in eligible for t in assigned):
            allowed_users.append({
                "key": row.get("key"), "username": row.get("username"),
                "platform": row.get("platform"), "tier": row.get("tier"),
                "ownerOverride": bool(row.get("ownerOverride")),
            })
    # El bypass del propietario es independiente de ownerTestTier: la persona
    # dueña de la instalación debe poder usar/probar todos los exclusivos.
    owners = []
    if cfg.get("ownerBypassEnabled", True):
        for row in load_owner_test_users().values():
            if not any(str(x.get("key")) == str(row.get("key")) for x in allowed_users):
                owners.append(dict(row))
    return {
        "ok": True, "kind": kind, "id": item_id,
        "exclusive": bool(assigned) or marked,
        "markedExclusive": marked, "tiers": assigned,
        "active": bool(active_payload.get("active")),
        "period": active_payload.get("period"),
        "expiresAt": active_payload.get("expiresAt"),
        "users": allowed_users, "owners": owners,
        "inheritLowerTiers": bool(cfg.get("inheritLowerTiers", True)),
    }


def update_weekly_item_assignments(kind: str, old_id: str, new_id: str, tiers: list[str] | None, reserved: bool = False) -> dict:
    """API interna de Recompensas: asigna un recurso a tiers o lo reserva."""
    cfg = load_weekly_rewards_config()
    field = "commandIds" if str(kind).lower() == "command" else "emoteIds"
    reserved_field = _weekly_reserved_field(kind)
    old_id = str(old_id or "").strip().lower()
    new_id = str(new_id or "").strip().lower()
    selected = {str(x).lower() for x in (tiers or []) if str(x).lower() in WEEKLY_TIER_ORDER}
    for tier_id in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(tier_id, {})
        values = [str(x).strip().lower() for x in (tier.get(field) or []) if str(x).strip()]
        values = [x for x in values if x not in {old_id, new_id}]
        if new_id and tier_id in selected:
            values.append(new_id)
        tier[field] = list(dict.fromkeys(values))[:100]
    reserved_values = [str(x).strip().lower() for x in (cfg.get(reserved_field) or []) if str(x).strip() and str(x).strip().lower() not in {old_id, new_id}]
    if new_id and reserved and not selected:
        reserved_values.append(new_id)
    cfg[reserved_field] = list(dict.fromkeys(reserved_values))[:200]
    return save_weekly_rewards_config(cfg, make_backup=True)


def replace_emote_id_in_commands(old_id: str, new_id: str) -> int:
    old_id = str(old_id or "").strip().lower()
    new_id = str(new_id or "").strip().lower()
    if not old_id or not new_id or old_id == new_id:
        return 0
    items = load_commands()
    changed = 0
    for command in items:
        dirty = False
        for cue in command.get("stickerTimeline") or []:
            if str(cue.get("emoteId") or "").lower() == old_id:
                cue["emoteId"] = new_id
                dirty = True
        if dirty:
            changed += 1
    if changed:
        save_commands_payload({"commands": items}, make_backup=True)
    return changed


def weekly_discount_for_user(user_key: str) -> int:
    cfg = load_weekly_rewards_config()
    if is_test_user_key(user_key) and cfg.get("ownerBypassEnabled", True):
        simulated = str(cfg.get("ownerTestTier") or "none").lower()
        if simulated in WEEKLY_TIER_ORDER:
            discounts = []
            for tier_id in weekly_eligible_tiers(simulated, cfg):
                tier = cfg.get("tiers", {}).get(tier_id, {})
                if tier.get("enabled", True):
                    discounts.append(int(tier.get("discountPct", 0) or 0))
            return max(discounts or [0])
        return 0
    winner = weekly_winner_for_key(user_key)
    if not winner:
        return 0
    discounts = []
    for tier_id in weekly_eligible_tiers(winner.get("tier"), cfg):
        tier = cfg.get("tiers", {}).get(tier_id, {})
        if tier.get("enabled", True):
            discounts.append(int(tier.get("discountPct", 0) or 0))
    return max(discounts or [0])


def weekly_discounted_cost(base_cost: int | float, discount_pct: int | float) -> int:
    """Aplica descuento con redondeo comercial (0.5 hacia arriba).

    Un canje que originalmente cuesta al menos 1 nunca puede quedar en 0:
    cualquier resultado menor de 1 conserva un coste mínimo de 1.
    """
    try:
        base = max(0.0, float(base_cost or 0))
        discount = max(0.0, min(100.0, float(discount_pct or 0)))
    except Exception:
        return 0
    if base <= 0:
        return 0
    raw = base * (100.0 - discount) / 100.0
    rounded = math.floor(raw + 0.5 + 1e-9)
    return max(1, int(rounded))


def weekly_public_active() -> dict:
    cfg = load_weekly_rewards_config()
    state = load_weekly_rewards_state()
    active = weekly_state_is_active(state)
    winners = []
    for winner in state.get("winners", []) if active else []:
        tier = cfg.get("tiers", {}).get(winner.get("tier"), {})
        row = dict(winner)
        row["title"] = tier.get("title", row.get("title", ""))
        row["badgeLabel"] = tier.get("badgeLabel", row.get("badgeLabel", ""))
        row["badgeIcon"] = tier.get("badgeIcon", row.get("badgeIcon", "✦"))
        row["badgeHtml"] = tier.get("badgeHtml", row.get("badgeHtml", ""))
        row["badgeCss"] = tier.get("badgeCss", row.get("badgeCss", ""))
        row["accent"] = tier.get("accent", row.get("accent", "#53E6FF"))
        row["eligibleTiers"] = weekly_eligible_tiers(row.get("tier"), cfg)
        winners.append(row)

    # V0.48: el propietario puede simular un rango para probar insignias,
    # descuentos, comandos y emotes sin contaminar el ranking real.
    simulated = str(cfg.get("ownerTestTier") or "none").lower()
    if cfg.get("ownerBypassEnabled", True) and simulated in WEEKLY_TIER_ORDER:
        tier = cfg.get("tiers", {}).get(simulated, {})
        for profile in load_owner_test_users().values():
            row = {
                "key": profile.get("key"),
                "username": profile.get("username"),
                "platform": profile.get("platform"),
                "avatar": "",
                "rank": int(tier.get("minRank", 1) or 1),
                "score": 99999,
                "tier": simulated,
                "title": tier.get("title", ""),
                "badgeLabel": tier.get("badgeLabel", ""),
                "badgeIcon": tier.get("badgeIcon", "✦"),
                "badgeHtml": tier.get("badgeHtml", ""),
                "badgeCss": tier.get("badgeCss", ""),
                "accent": tier.get("accent", "#53E6FF"),
                "eligibleTiers": weekly_eligible_tiers(simulated, cfg),
                "ownerOverride": True,
            }
            winners = [w for w in winners if str(w.get("key") or "") != str(row.get("key") or "")]
            winners.append(row)
    effective_active = active or any(bool(w.get("ownerOverride")) for w in winners)
    return {
        "ok": True,
        "active": effective_active,
        "period": state.get("period") or current_period_key(),
        "sourcePeriod": state.get("sourcePeriod"),
        "activatedAt": state.get("activatedAt"),
        "expiresAt": state.get("expiresAt"),
        "winners": winners,
        "winnersByKey": {str(w.get("key")): w for w in winners if w.get("key")},
    }


def _next_monday_iso() -> str:
    now = datetime.now().astimezone()
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (monday + timedelta(days=7)).isoformat()


def grant_weekly_bonus(winner: dict, tier: dict) -> int:
    amount = max(0, int(tier.get("gumpitasBonus", 0) or 0))
    if amount <= 0:
        return 0
    try:
        economy = load_economy()
        wallet = ensure_wallet(
            economy,
            {
                "key": winner.get("key"),
                "username": winner.get("username"),
                "platform": winner.get("platform"),
                "avatar": winner.get("avatar", ""),
            },
        )
        if is_test_user_key(wallet.get("key", "")):
            return 0
        wallet["balance"] = int(wallet.get("balance", 0)) + amount
        wallet["earned"] = int(wallet.get("earned", 0)) + amount
        add_transaction(economy, wallet, amount, f"weekly_reward_{winner.get('tier')}_{winner.get('sourcePeriod')}")
        save_economy(economy, make_backup=True)
        return amount
    except Exception:
        return 0


def apply_weekly_rewards_from_rows(
    rows: list[dict],
    source_period: str,
    *,
    grant_bonuses: bool = True,
    force: bool = False,
) -> dict:
    cfg = load_weekly_rewards_config()
    if not cfg.get("enabled", True) and not force:
        return load_weekly_rewards_state()
    existing = load_weekly_rewards_state()
    if (
        not force
        and existing.get("sourcePeriod") == source_period
        and existing.get("period") == current_period_key()
        and existing.get("winners")
    ):
        return existing

    winners = []
    for row in rows[:10]:
        rank = int(row.get("rank") or 0)
        tier_id = weekly_primary_tier_for_rank(rank)
        if not tier_id:
            continue
        tier = cfg.get("tiers", {}).get(tier_id, {})
        if not tier.get("enabled", True):
            continue
        winner = {
            "key": row.get("key"),
            "username": row.get("username", "Usuario"),
            "platform": row.get("platform", ""),
            "avatar": row.get("avatar", ""),
            "rank": rank,
            "score": row.get("score", 0),
            "tier": tier_id,
            "sourcePeriod": source_period,
            "title": tier.get("title", ""),
            "badgeLabel": tier.get("badgeLabel", ""),
            "badgeIcon": tier.get("badgeIcon", "✦"),
            "badgeHtml": tier.get("badgeHtml", ""),
            "badgeCss": tier.get("badgeCss", ""),
            "accent": tier.get("accent", "#53E6FF"),
            "bonusGranted": 0,
        }
        winners.append(winner)

    state = {
        "period": current_period_key(),
        "sourcePeriod": source_period,
        "activatedAt": now_iso(),
        "expiresAt": _next_monday_iso(),
        "winners": winners,
        "lastEntrances": {},
        "updatedAt": now_iso(),
    }
    state = save_weekly_rewards_state(state, make_backup=True)

    if grant_bonuses:
        changed = False
        for winner in state.get("winners", []):
            tier = cfg.get("tiers", {}).get(winner.get("tier"), {})
            amount = grant_weekly_bonus(winner, tier)
            if amount:
                winner["bonusGranted"] = amount
                changed = True
        if changed:
            state = save_weekly_rewards_state(state, make_backup=True)

    return state


def apply_weekly_rewards_from_archive(
    archived: dict,
    *,
    grant_bonuses: bool = True,
    force: bool = False,
) -> dict:
    rows = list(archived.get("top") or [])
    if not rows:
        rows = sorted_users({"users": archived.get("users", {})})[:10]
    return apply_weekly_rewards_from_rows(
        rows,
        str(archived.get("period") or ""),
        grant_bonuses=grant_bonuses,
        force=force,
    )


def weekly_admin_payload() -> dict:
    cfg = load_weekly_rewards_config()
    commands = load_commands()
    emotes = load_emotes()
    return {
        "ok": True,
        "config": cfg,
        "active": weekly_public_active(),
        "hall": load_hall_of_fame(),
        "hallUsers": hall_user_summary(),
        "commands": commands,
        "emotes": emotes,
        "resourceCatalog": {
            "commands": [{**item, "weeklyTiers": weekly_item_tiers("command", item.get("id", ""), cfg), "reserved": item.get("id", "") in weekly_reserved_ids("command", cfg)} for item in commands],
            "emotes": [{**item, "weeklyTiers": weekly_item_tiers("emote", item.get("id", ""), cfg), "reserved": item.get("id", "") in weekly_reserved_ids("emote", cfg)} for item in emotes],
        },
    }

# ============================================================
# Economía / Gumpitas
# ============================================================

def empty_economy() -> dict:
    return {
        "users": {},
        "transactions": [],
        "updatedAt": now_iso(),
    }


def make_economy_backup() -> None:
    if not ECONOMY_FILE.exists():
        return

    try:
        payload = json.loads(ECONOMY_FILE.read_text(encoding="utf-8"))
        atomic_write_json(ECONOMY_BACKUP_FILE, payload)
    except Exception:
        pass


def save_economy(state: dict, make_backup: bool = True) -> None:
    ensure_storage()
    state = dict(state)
    state["updatedAt"] = now_iso()

    if make_backup:
        make_economy_backup()

    atomic_write_json(ECONOMY_FILE, state)


def load_economy() -> dict:
    ensure_storage()

    if not ECONOMY_FILE.exists():
        state = empty_economy()
        ensure_test_wallets(state)
        save_economy(state, make_backup=False)
        atomic_write_json(ECONOMY_BACKUP_FILE, state)
        return state

    try:
        data = json.loads(ECONOMY_FILE.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise ValueError("economia.json inválido")

        data.setdefault("users", {})
        data.setdefault("transactions", [])

        ensure_test_wallets(data)

        return data

    except Exception:
        print("economia.json está dañado; intentando economia_backup.json...")

        try:
            backup = json.loads(
                ECONOMY_BACKUP_FILE.read_text(encoding="utf-8")
            )

            if not isinstance(backup, dict):
                raise ValueError("backup economía inválido")

            backup.setdefault("users", {})
            backup.setdefault("transactions", [])
            ensure_test_wallets(backup)

            save_economy(backup, make_backup=False)
            return backup

        except Exception:
            state = empty_economy()
            ensure_test_wallets(state)
            save_economy(state, make_backup=False)
            atomic_write_json(ECONOMY_BACKUP_FILE, state)
            return state


def ensure_wallet(state: dict, user: dict) -> dict:
    key = str(user.get("key") or "").strip()
    username = str(user.get("username") or "").strip()
    platform = str(user.get("platform") or "").strip().lower()

    if not key or not username or not platform:
        raise ValueError("Faltan key, username o platform")

    users = state.setdefault("users", {})

    entry = users.setdefault(
        key,
        {
            "key": key,
            "username": username,
            "platform": platform,
            "avatar": "",
            "balance": 0,
            "earned": 0,
            "spent": 0,
            "counters": {
                "messagesRewarded": 0,
                "likesRewarded": 0,
                "follows": 0,
                "joins": 0,
                "shares": 0,
                "subscriptions": 0,
                "gifts": 0,
                "dailyBonuses": 0,
                "activityBonuses": 0,
            },
            "likeRemainder": 0,
            "lastMessageRewardTs": 0.0,
            "lastJoinRewardTs": 0.0,
            "lastDailyClaimDate": "",
            "lastDailyActivityDate": "",
            "activityRewardCounter": 0,
            "lastInteraction": None,
        },
    )

    entry["username"] = username
    entry["platform"] = platform
    entry["isTestUser"] = is_test_user_key(key)

    if user.get("avatar"):
        entry["avatar"] = str(user.get("avatar"))

    return entry


def add_transaction(state: dict, entry: dict, amount: int, reason: str) -> None:
    transactions = state.setdefault("transactions", [])

    transactions.insert(
        0,
        {
            "time": now_iso(),
            "key": entry.get("key"),
            "username": entry.get("username"),
            "platform": entry.get("platform"),
            "amount": int(amount),
            "reason": reason,
            "balanceAfter": int(entry.get("balance", 0)),
        },
    )

    del transactions[200:]


def ensure_test_wallets(state: dict) -> None:
    """
    Hace que las cuentas de prueba aparezcan siempre en economia.html,
    incluso antes de escribir !gumpitas.
    """
    for profile in load_owner_test_users().values():
        entry = ensure_wallet(state, profile)
        entry["isTestUser"] = True


def sorted_wallets(
    state: dict,
    include_test: bool = True,
) -> list[dict]:
    rows = []

    for user in state.get("users", {}).values():
        row = dict(user)

        row.pop("lastMessageRewardTs", None)
        row.pop("lastJoinRewardTs", None)
        row.pop("likeRemainder", None)
        row.pop("lastDailyClaimDate", None)
        row.pop("lastDailyActivityDate", None)
        row.pop("activityRewardCounter", None)

        row["isTestUser"] = bool(
            row.get("isTestUser")
            or is_test_user_key(row.get("key", ""))
        )

        if not include_test and row["isTestUser"]:
            continue

        rows.append(row)

    rows.sort(
        key=lambda u: (
            1 if u.get("isTestUser") else 0,
            int(u.get("balance", 0)),
            int(u.get("earned", 0)),
        ),
        reverse=True,
    )

    regular_rank = 0

    for row in rows:
        if row.get("isTestUser"):
            row["rank"] = "TEST"
            row["infinite"] = True
            row["displayBalance"] = "∞"
        else:
            regular_rank += 1
            row["rank"] = regular_rank
            row["infinite"] = False
            row["displayBalance"] = str(
                int(row.get("balance", 0))
            )

    return rows


def public_economy(state: dict) -> dict:
    load_economy_rates()
    ensure_test_wallets(state)

    wallets = sorted_wallets(
        state,
        include_test=True,
    )

    real_ranking = sorted_wallets(
        state,
        include_test=False,
    )

    return {
        "updatedAt": state.get("updatedAt"),
        "top": real_ranking[:10],
        "wallets": wallets,
        "transactions": state.get("transactions", [])[:30],
        "rates": ECONOMY_RATES,
        "testUsers": list(load_owner_test_users().keys()),
        "currency": currency_public(),
    }


def award_gumpitas(
    state: dict,
    user: dict,
    kind: str,
    quantity: int = 1,
    gift_coins: int = 0,
    donation_usd: float = 0.0,
) -> tuple[int, dict]:
    entry = ensure_wallet(state, user)
    now_ts = time.time()

    amount = 0
    reason = kind
    counters = entry.setdefault("counters", {})

    quantity = max(0, int(quantity or 0))
    gift_coins = max(0, int(gift_coins or 0))
    donation_usd = max(0.0, float(donation_usd or 0.0))

    if kind == "message":
        cooldown = int(ECONOMY_RATES["messageCooldownSeconds"])
        last = float(entry.get("lastMessageRewardTs", 0.0))

        if now_ts - last >= cooldown:
            amount = int(ECONOMY_RATES["message"])
            entry["lastMessageRewardTs"] = now_ts
            counters["messagesRewarded"] = int(
                counters.get("messagesRewarded", 0)
            ) + 1
        else:
            reason = "message_cooldown"

    elif kind == "like":
        per = max(1, int(ECONOMY_RATES["likesPerGumpita"]))
        total = int(entry.get("likeRemainder", 0)) + quantity
        amount = total // per
        entry["likeRemainder"] = total % per

        if amount:
            counters["likesRewarded"] = int(
                counters.get("likesRewarded", 0)
            ) + quantity

    elif kind == "follow":
        amount = int(ECONOMY_RATES["follow"])
        counters["follows"] = int(counters.get("follows", 0)) + 1

    elif kind == "join":
        cooldown = int(ECONOMY_RATES["joinCooldownSeconds"])
        last = float(entry.get("lastJoinRewardTs", 0.0))

        if now_ts - last >= cooldown:
            amount = int(ECONOMY_RATES["join"])
            entry["lastJoinRewardTs"] = now_ts
            counters["joins"] = int(counters.get("joins", 0)) + 1
        else:
            reason = "join_cooldown"

    elif kind == "share":
        amount = int(
            ECONOMY_RATES.get(
                "share",
                5
            )
        )
        counters["shares"] = int(
            counters.get("shares", 0)
        ) + 1

    elif kind == "subscription":
        amount = int(ECONOMY_RATES["subscription"])
        counters["subscriptions"] = int(
            counters.get("subscriptions", 0)
        ) + 1

    elif kind == "gift":
        counters["gifts"] = int(counters.get("gifts", 0)) + 1

        if donation_usd > 0:
            amount = max(
                int(ECONOMY_RATES["giftBase"]),
                round(donation_usd * int(ECONOMY_RATES["donationUsd"])),
            )
            reason = f"gift_usd_{donation_usd:g}"

        elif gift_coins > 0:
            amount = max(
                int(ECONOMY_RATES["giftBase"]),
                gift_coins * int(ECONOMY_RATES["giftCoin"]),
            )
            reason = f"gift_coins_{gift_coins}"

        else:
            amount = int(ECONOMY_RATES["giftBase"])

    amount = max(0, int(amount))

    if amount > 0 and not is_test_user_key(entry.get("key", "")):
        today = datetime.now().astimezone().date().isoformat()

        if entry.get("lastDailyActivityDate") != today:
            bonus = int(
                ECONOMY_RATES.get(
                    "dailyActivityBonus",
                    0
                )
            )

            if bonus > 0:
                amount += bonus
                reason = f"{reason}+daily_activity"
                entry["lastDailyActivityDate"] = today
                counters["dailyBonuses"] = int(
                    counters.get("dailyBonuses", 0)
                ) + 1

        if kind == "message":
            count = int(
                entry.get(
                    "activityRewardCounter",
                    0
                )
            ) + 1

            entry["activityRewardCounter"] = count

            every = max(
                1,
                int(
                    ECONOMY_RATES.get(
                        "activityMilestoneEvery",
                        10
                    )
                )
            )

            if count % every == 0:
                milestone = int(
                    ECONOMY_RATES.get(
                        "activityMilestoneBonus",
                        0
                    )
                )

                if milestone > 0:
                    amount += milestone
                    reason = f"{reason}+activity_milestone"
                    counters["activityBonuses"] = int(
                        counters.get("activityBonuses", 0)
                    ) + 1

    if amount > 0:
        entry["balance"] = int(entry.get("balance", 0)) + amount
        entry["earned"] = int(entry.get("earned", 0)) + amount
        add_transaction(state, entry, amount, reason)

    entry["lastInteraction"] = now_iso()

    return amount, entry


# ============================================================
# Eventos para OBS
# ============================================================

def emit_event(event_type: str, payload: dict) -> dict:
    global EVENT_COUNTER

    with EVENT_LOCK:
        EVENT_COUNTER += 1

        event = {
            "id": EVENT_COUNTER,
            "time": now_iso(),
            "type": event_type,
            **payload,
        }

        EVENTS.append(event)

    if (not payload.get("automation")) and (not payload.get("testEvent")) and event_type in {
        "redeem", "emote_redeem", "goal_reached", "weekly_entrance", "daily_bonus"
    }:
        auto_event = {"event": event_type, **payload}
        if event_type == "redeem" and isinstance(payload.get("item"), dict):
            auto_event["command"] = str(payload.get("item", {}).get("id") or "")
        automation_dispatch("brynn_event", auto_event)

    return event



def _automation_user(event: dict) -> dict:
    user = event.get("user") if isinstance(event.get("user"), dict) else {}
    username = str(user.get("username") or event.get("username") or "Automation").strip()
    platform = str(user.get("platform") or event.get("platform") or "brynn").strip().lower()
    key = str(user.get("key") or "").strip()
    if not key:
        if username and platform in {"twitch", "tiktok", "kick"}:
            key = f"{platform}:{username.lower()}"
        else:
            key = "automation:demo"
    return {
        "key": key,
        "username": username,
        "platform": platform,
        "avatar": str(user.get("avatar") or event.get("avatar") or ""),
    }


def execute_automation_action(action: dict, event: dict):
    """Execute one action from AutomationEngine.

    Actions intentionally call the same public event format used by the OBS
    overlay so existing command/emote rendering remains compatible.
    """
    kind = str(action.get("type") or "").strip().lower()
    if kind == "obs_scene":
        return OBS.change_scene(str(action.get("scene") or ""))
    if kind == "obs_source":
        scene = str(action.get("scene") or "")
        if not scene:
            scene = str(OBS.request("GetCurrentProgramScene").get("currentProgramSceneName") or "")
        return OBS.set_source_visible(scene, str(action.get("source") or ""), bool(action.get("enabled", True)))
    if kind == "obs_filter":
        return OBS.set_filter_enabled(str(action.get("source") or ""), str(action.get("filter") or ""), bool(action.get("enabled", True)))
    if kind == "obs_mute":
        return OBS.set_mute(str(action.get("input") or ""), bool(action.get("muted", True)))
    if kind == "obs_volume":
        return OBS.set_volume(str(action.get("input") or ""), float(action.get("volume", 1.0) or 0))
    if kind == "obs_media_restart":
        return OBS.restart_media(str(action.get("input") or ""))
    if kind == "obs_media":
        return OBS.media_action(str(action.get("input") or ""), str(action.get("action") or "restart"))
    if kind == "obs_transition":
        duration = action.get("durationMs")
        return OBS.set_transition(str(action.get("transition") or ""), int(duration) if duration not in (None, "") else None)
    if kind == "obs_stream":
        return OBS.set_streaming(bool(action.get("active", True)))
    if kind == "obs_record":
        return OBS.set_recording(bool(action.get("active", True)))
    if kind == "obs_replay":
        return OBS.replay_buffer(str(action.get("action") or "save"))
    if kind == "economy_adjust":
        user = _automation_user(event)
        try:
            delta = max(-100000, min(100000, int(action.get("delta", 0) or 0)))
        except Exception:
            delta = 0
        if delta == 0:
            return {"delta": 0, "skipped": True}
        with LOCK:
            state = load_economy()
            entry = ensure_wallet(state, user)
            if is_test_user_key(entry.get("key", "")):
                return {"testUser": True, "balance": "∞", "delta": delta}
            current = int(entry.get("balance", 0))
            new_balance = max(0, current + delta)
            real_delta = new_balance - current
            entry["balance"] = new_balance
            if real_delta > 0:
                entry["earned"] = int(entry.get("earned", 0)) + real_delta
            elif real_delta < 0:
                entry["spent"] = int(entry.get("spent", 0)) + abs(real_delta)
            add_transaction(state, entry, real_delta, str(action.get("reason") or "automation"))
            save_economy(state, make_backup=True)
            return {"key": entry.get("key"), "delta": real_delta, "balance": new_balance}
    if kind == "command":
        item = find_store_item(str(action.get("id") or action.get("command") or ""))
        if not item:
            raise ValueError("Comando no encontrado")
        user = _automation_user(event)
        return emit_event("redeem", {
            "user": user,
            "item": command_event_item(item, test_cost=True),
            "balance": "∞",
            "testUser": True,
            "automation": True,
        })
    if kind == "emote":
        item = find_emote(str(action.get("id") or action.get("emote") or ""))
        if not item:
            raise ValueError("Emote no encontrado")
        return emit_event("emote_redeem", {
            "user": _automation_user(event),
            "emote": {**item, "cost": 0},
            "balance": "∞",
            "testUser": True,
            "automation": True,
        })
    if kind == "overlay_message":
        return emit_event("automation_notice", {
            "user": _automation_user(event),
            "title": str(action.get("title") or "Automatización"),
            "message": str(action.get("message") or ""),
            "accent": str(action.get("accent") or "#8CFF3A"),
            "durationMs": max(800, min(30000, int(action.get("durationMs", 4200) or 4200))),
            "automation": True,
        })
    if kind == "audio":
        return emit_event("automation_audio", {
            "audioUrl": str(action.get("url") or action.get("audioUrl") or ""),
            "volume": max(0.0, min(1.0, float(action.get("volume", 0.8) or 0.8))),
            "durationMs": max(0, min(300000, int(action.get("durationMs", 0) or 0))),
            "fadeOutMs": max(0, min(10000, int(action.get("fadeOutMs", 600) or 600))),
            "automation": True,
        })
    raise ValueError(f"Acción de automatización desconocida: {kind or '(vacía)'}")


def automation_dispatch(trigger_type: str, event: dict, force_id: str | None = None) -> list[str]:
    engine = AUTOMATION_ENGINE
    if engine is None:
        return []
    try:
        return engine.dispatch(str(trigger_type), event if isinstance(event, dict) else {}, force_id=force_id)
    except Exception as exc:
        print(f"[Automation] dispatch error: {exc}")
        return []


def events_after(after_id: int) -> list[dict]:
    with EVENT_LOCK:
        return [
            event
            for event in EVENTS
            if int(event.get("id", 0)) > after_id
        ]


def latest_event_id() -> int:
    with EVENT_LOCK:
        if not EVENTS:
            return int(EVENT_COUNTER)

        try:
            return max(
                int(event.get("id", 0))
                for event in EVENTS
            )
        except Exception:
            return int(EVENT_COUNTER)



def normalize_sticker_timeline(value) -> list[dict]:
    """Normaliza una secuencia de emotes/stickers sincronizada con el audio."""
    if not isinstance(value, list):
        return []

    allowed_patterns = {"scatter", "burst", "fountain", "rain", "orbit", "edges", "wave", "center"}
    rows = []
    for raw in value[:192]:
        if not isinstance(raw, dict):
            continue
        emote_id = re.sub(r"[^a-z0-9_-]", "", str(raw.get("emoteId") or "").strip().lower())[:40]
        if not emote_id:
            continue
        pattern = str(raw.get("pattern") or "scatter").strip().lower()
        if pattern not in allowed_patterns:
            pattern = "scatter"
        rows.append({
            "atMs": max(0, min(int(float(raw.get("atMs") or 0)), 180000)),
            "emoteId": emote_id,
            "quantity": max(1, min(int(raw.get("quantity") or 1), 60)),
            "durationMs": max(250, min(int(float(raw.get("durationMs") or 1800)), 30000)),
            "animation": str(raw.get("animation") or "float").strip().lower()[:40],
            "enterAnimation": str(raw.get("enterAnimation") or "pop").strip().lower()[:40],
            "exitAnimation": str(raw.get("exitAnimation") or "fade").strip().lower()[:40],
            "size": max(6, min(int(raw.get("size") or 24), 100)),
            "pattern": pattern,
            "staggerMs": max(0, min(int(raw.get("staggerMs") or 90), 3000)),
            "lane": max(0, min(int(raw.get("lane") or 0), 5)),
        })
    rows.sort(key=lambda row: row["atMs"])
    return rows


def command_playback_duration_ms(item: dict) -> int:
    visual_duration = int(item.get("durationMs") or 3000)
    if bool(item.get("cutAudioAtDuration", True)):
        base = visual_duration
    else:
        base = max(visual_duration, int(item.get("audioDurationMs") or 0))
    for cue in item.get("stickerTimeline") or []:
        end = int(cue.get("atMs") or 0) + int(cue.get("durationMs") or 0) + max(0, int(cue.get("quantity") or 1) - 1) * int(cue.get("staggerMs") or 0)
        base = max(base, end)
    return max(300, min(base, 180000))

def normalize_command_item(item: dict) -> dict:
    item = dict(item or {})
    command_id = re.sub(r"[^a-z0-9_-]", "", str(item.get("id") or "").lower())[:40]
    if not command_id:
        raise ValueError("El comando necesita un ID válido")

    aliases = item.get("aliases") or [command_id]
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split(",") if a.strip()]
    aliases = [str(a).strip().lower().lstrip("!") for a in aliases if str(a).strip()]
    if command_id not in aliases:
        aliases.insert(0, command_id)

    visual_url = str(item.get("visualUrl") or "")
    visual_type = str(item.get("visualType") or "").lower()
    badge_url = str(item.get("badgeUrl") or "")
    audio_url = str(item.get("audioUrl") or "")
    audio_source_duration_ms = max(0, min(int(float(item.get("audioSourceDurationMs") or item.get("audioDurationMs") or 0)), 180000))
    audio_trim_start_ms = max(0, min(int(float(item.get("audioTrimStartMs") or 0)), audio_source_duration_ms or 180000))
    raw_trim_end = item.get("audioTrimEndMs")
    audio_trim_end_ms = max(0, min(int(float(raw_trim_end if raw_trim_end not in (None, "", 0) else audio_source_duration_ms or 0)), audio_source_duration_ms or 180000))
    if audio_source_duration_ms > 0:
        audio_trim_start_ms = min(audio_trim_start_ms, max(0, audio_source_duration_ms - 50))
        audio_trim_end_ms = max(audio_trim_start_ms + 50, min(audio_trim_end_ms or audio_source_duration_ms, audio_source_duration_ms))
        audio_active_duration_ms = max(50, audio_trim_end_ms - audio_trim_start_ms)
    else:
        audio_trim_start_ms = 0
        audio_trim_end_ms = 0
        audio_active_duration_ms = 0

    return {
        "id": command_id,
        "name": str(item.get("name") or command_id)[:80],
        "cost": max(0, min(int(item.get("cost") or 0), 1000000)),
        "icon": str(item.get("icon") or "✦")[:12],
        "description": str(item.get("description") or "")[:300],
        "effect": str(item.get("effect") or "media").lower(),
        "aliases": aliases[:20],
        "enabled": bool(item.get("enabled", True)),
        "durationMs": max(300, min(int(item.get("durationMs") or 3000), 180000)),
        # animation = movimiento mientras permanece visible (compatibilidad V14)
        "animation": str(item.get("animation") or "none").lower(),
        "enterAnimation": str(
            item.get("enterAnimation")
            or item.get("animation")
            or "pop"
        ).lower(),
        "exitAnimation": str(
            item.get("exitAnimation")
            or "fade"
        ).lower(),
        "position": str(item.get("position") or "center").lower(),
        "size": max(10, min(int(item.get("size") or 62), 100)),
        "showCard": bool(item.get("showCard", True)),
        "visualUrl": visual_url,
        "visualType": visual_type,
        "badgeUrl": badge_url,
        "audioUrl": audio_url,
        "audioVolume": max(0.0, min(float(item.get("audioVolume", 0.8)), 1.0)),
        "audioDurationMs": audio_active_duration_ms,
        "audioSourceDurationMs": audio_source_duration_ms,
        "audioTrimStartMs": audio_trim_start_ms,
        "audioTrimEndMs": audio_trim_end_ms,
        "cutAudioAtDuration": bool(item.get("cutAudioAtDuration", True)),
        "audioFadeOutMs": max(0, min(int(float(item.get("audioFadeOutMs") if item.get("audioFadeOutMs") is not None else 600)), 5000)),
        "stickerTimelineEnabled": bool(item.get("stickerTimelineEnabled", False)),
        "timelineAutoDuration": bool(item.get("timelineAutoDuration", True)),
        "stickerTimeline": normalize_sticker_timeline(item.get("stickerTimeline") or []),
    }


def save_commands_payload(payload: dict, make_backup: bool = True) -> None:
    ensure_storage()
    if make_backup and COMMANDS_FILE.exists():
        try:
            current = json.loads(COMMANDS_FILE.read_text(encoding="utf-8"))
            atomic_write_json(COMMANDS_BACKUP_FILE, current)
        except Exception:
            pass
    atomic_write_json(COMMANDS_FILE, payload)


def load_commands() -> list[dict]:
    ensure_storage()
    if not COMMANDS_FILE.exists():
        payload = {"commands": [normalize_command_item(x) for x in DEFAULT_COMMANDS]}
        save_commands_payload(payload, make_backup=False)
        atomic_write_json(COMMANDS_BACKUP_FILE, payload)
        return payload["commands"]

    try:
        payload = json.loads(COMMANDS_FILE.read_text(encoding="utf-8"))
        items = payload.get("commands", []) if isinstance(payload, dict) else []
        return [normalize_command_item(x) for x in items]
    except Exception:
        try:
            payload = json.loads(COMMANDS_BACKUP_FILE.read_text(encoding="utf-8"))
            items = payload.get("commands", [])
            restored = [normalize_command_item(x) for x in items]
            save_commands_payload({"commands": restored}, make_backup=False)
            return restored
        except Exception:
            restored = [normalize_command_item(x) for x in DEFAULT_COMMANDS]
            save_commands_payload({"commands": restored}, make_backup=False)
            return restored


def command_map() -> dict[str, dict]:
    return {item["id"]: item for item in load_commands()}


def store_public() -> list[dict]:
    return [dict(item) for item in load_commands() if item.get("enabled", True)]


def find_store_item(raw: str) -> dict | None:
    wanted = str(raw or "").strip().lower().lstrip("!").replace("_", " ")
    if not wanted:
        return None
    for item in load_commands():
        if not item.get("enabled", True):
            continue
        names = [item["id"].lower(), item["name"].lower()]
        names.extend(str(a).lower() for a in item.get("aliases", []))
        if wanted in names:
            return item
    return None


def store_public_for_user(user_key: str) -> list[dict]:
    result = []
    discount = weekly_discount_for_user(user_key)
    for item in store_public():
        access = weekly_access_for_item(user_key, "command", item.get("id", ""))
        if access.get("exclusive") and not access.get("allowed"):
            continue
        row = dict(item)
        row["baseCost"] = int(row.get("cost", 0))
        row["weeklyDiscountPct"] = discount
        row["cost"] = weekly_discounted_cost(row["baseCost"], discount)
        row["weeklyExclusiveTiers"] = access.get("tiers", [])
        result.append(row)
    return result


def command_event_item(item: dict, test_cost: bool = False) -> dict:
    clean = normalize_command_item(item)
    # Resolver los emotes en el momento del canje evita duplicar URLs dentro
    # del archivo de comandos y permite cambiar un emote sin rehacer la secuencia.
    by_id = {str(e.get("id") or ""): e for e in load_emotes()}
    resolved = []
    for cue in clean.get("stickerTimeline") or []:
        row = dict(cue)
        emote = by_id.get(str(row.get("emoteId") or ""))
        if emote and emote.get("enabled", True) and emote.get("visualUrl"):
            row["emote"] = emote
            resolved.append(row)
    clean["stickerTimeline"] = resolved
    clean["playbackDurationMs"] = command_playback_duration_ms(clean)
    if test_cost:
        clean["cost"] = 0
    return clean



# ============================================================
# Emotes en pantalla
# ============================================================

DEFAULT_EMOTES = []


def normalize_emote_item(item: dict) -> dict:
    item = dict(item or {})
    emote_id = re.sub(
        r"[^a-z0-9_-]",
        "",
        str(item.get("id") or "").lower()
    )[:40]

    if not emote_id:
        raise ValueError("El emote necesita un ID válido")

    aliases = item.get("aliases") or [emote_id]
    if isinstance(aliases, str):
        aliases = [
            x.strip().lower().lstrip("!")
            for x in aliases.split(",")
            if x.strip()
        ]

    aliases = [
        str(x).strip().lower().lstrip("!")
        for x in aliases
        if str(x).strip()
    ]

    if emote_id not in aliases:
        aliases.insert(0, emote_id)

    return {
        "id": emote_id,
        "name": str(item.get("name") or emote_id)[:80],
        "description": str(item.get("description") or "")[:300],
        "accessMode": "exclusive" if str(item.get("accessMode") or "general").lower() == "exclusive" else "general",
        "cost": max(0, min(int(item.get("cost") or 0), 1000000)),
        "enabled": bool(item.get("enabled", True)),
        "aliases": aliases[:20],
        "visualUrl": str(item.get("visualUrl") or ""),
        "visualType": str(item.get("visualType") or "image").lower(),
        "audioUrl": str(item.get("audioUrl") or ""),
        "audioVolume": max(
            0.0,
            min(float(item.get("audioVolume", 0.8)), 1.0)
        ),
        "durationMs": max(
            300,
            min(int(item.get("durationMs") or 3000), 120000)
        ),
        "enterAnimation": str(
            item.get("enterAnimation") or "pop"
        ).lower(),
        "exitAnimation": str(
            item.get("exitAnimation") or "fade"
        ).lower(),
        "animation": str(
            item.get("animation") or "float"
        ).lower(),
        "position": str(
            item.get("position") or "center"
        ).lower(),
        "size": max(
            10,
            min(int(item.get("size") or 45), 100)
        ),
        "showCard": bool(item.get("showCard", False)),
    }


def save_emotes_payload(
    payload: dict,
    make_backup: bool = True
) -> None:
    ensure_storage()

    if make_backup and EMOTES_FILE.exists():
        try:
            current = json.loads(
                EMOTES_FILE.read_text(encoding="utf-8")
            )
            atomic_write_json(
                EMOTES_BACKUP_FILE,
                current
            )
        except Exception:
            pass

    atomic_write_json(
        EMOTES_FILE,
        payload
    )


def load_emotes() -> list[dict]:
    ensure_storage()

    if not EMOTES_FILE.exists():
        payload = {
            "emotes": [
                normalize_emote_item(x)
                for x in DEFAULT_EMOTES
            ]
        }
        save_emotes_payload(
            payload,
            make_backup=False
        )
        atomic_write_json(
            EMOTES_BACKUP_FILE,
            payload
        )
        return payload["emotes"]

    try:
        payload = json.loads(
            EMOTES_FILE.read_text(encoding="utf-8")
        )
        items = (
            payload.get("emotes", [])
            if isinstance(payload, dict)
            else []
        )
        return [
            normalize_emote_item(x)
            for x in items
        ]

    except Exception:
        try:
            backup = json.loads(
                EMOTES_BACKUP_FILE.read_text(
                    encoding="utf-8"
                )
            )
            items = backup.get("emotes", [])
            restored = [
                normalize_emote_item(x)
                for x in items
            ]
            save_emotes_payload(
                {"emotes": restored},
                make_backup=False
            )
            return restored

        except Exception:
            return []


def find_emote(raw: str) -> dict | None:
    wanted = (
        str(raw or "")
        .strip()
        .lower()
        .lstrip("!")
        .replace("_", " ")
    )

    if not wanted:
        return None

    for item in load_emotes():
        if not item.get("enabled", True):
            continue

        names = [
            str(item.get("id") or "").lower(),
            str(item.get("name") or "").lower(),
        ]
        names.extend(
            str(x).lower()
            for x in item.get("aliases", [])
        )

        if wanted in names:
            return item

    return None


# ============================================================
# Alertas Twitch / TikTok
# ============================================================

ALERT_TYPES_BY_PLATFORM = {
    "twitch": (
        "follow",
        "subscription",
        "bits",
        "raid",
        "donation",
    ),
    "kick": (
        "follow", "subscription", "gift", "reward",
    ),
    "tiktok": (
        "follow",
        "subscription",
        "gift",
        "like",
        "share",
        "join",
    ),
}


def _default_alert_item(
    platform: str,
    alert_type: str,
    title: str,
    message: str = "",
    duration_ms: int = 5000,
    animation: str = "float",
) -> dict:
    return {
        "id": f"{platform}:{alert_type}",
        "platform": platform,
        "type": alert_type,
        "enabled": True,
        "titleTemplate": title,
        "messageTemplate": message,
        "visualUrl": "",
        "visualType": "",
        "audioUrl": "",
        "audioVolume": 0.8,
        "durationMs": duration_ms,
        "enterAnimation": "pop",
        "exitAnimation": "fade",
        "animation": animation,
        "position": "top-center",
        "size": 45,
        "advancedEnabled": False,
        "autoVisualInAdvanced": True,
        "customHtml": "",
        "customCss": "",
        "customJs": "",
        "emoteBurst": {
            "enabled": False,
            "source": "selected",
            "emoteIds": [],
            "mode": "burst",
            "count": 18,
            "size": 72,
            "durationMs": 2200,
            "spread": 420,
            "delayMs": 250,
        },
    }


def default_alert_config() -> dict:
    configs = {}

    twitch = {
        "follow": ("{user} ahora sigue a Brynn", "", 5000, "float"),
        "subscription": ("{user} se suscribió", "{amount}", 6000, "pulse"),
        "bits": ("{user} envió Bits", "{amount}", 6000, "pulse"),
        "raid": ("¡Raid de {user}!", "{amount}", 7000, "pulse"),
        "donation": ("{user} hizo una donación", "{amount}", 6500, "pulse"),
    }

    tiktok = {
        "follow": ("{user} ahora sigue a Brynn", "", 5000, "float"),
        "subscription": ("{user} se suscribió", "{amount}", 6000, "pulse"),
        "gift": ("{user} envió un regalo", "{amount}", 6500, "pulse"),
        "like": ("{user} dejó likes", "{amount}", 4200, "float"),
        "share": ("{user} compartió el LIVE", "¡Gracias por compartir!", 4800, "float"),
        "join": ("{user} entró al LIVE", "¡Bienvenido/a!", 3800, "float"),
    }

    kick = {
        "follow": ("{user} ahora te sigue en Kick", "", 5000, "float"),
        "subscription": ("{user} se suscribió en Kick", "{amount}", 6000, "pulse"),
        "gift": ("{user} regaló en Kick", "{amount}", 6500, "pulse"),
        "reward": ("¡Recompensa de Kick canjeada!", "{user} · {amount}", 6500, "pulse"),
    }

    for platform, definitions in (("twitch", twitch), ("tiktok", tiktok), ("kick", kick)):
        for alert_type, values in definitions.items():
            title, message, duration, animation = values
            configs[f"{platform}:{alert_type}"] = _default_alert_item(
                platform,
                alert_type,
                title,
                message,
                duration,
                animation,
            )

    return {"alerts": configs}


def normalize_alert_emote_burst(value: dict | None) -> dict:
    value = dict(value or {})

    raw_ids = value.get("emoteIds") or []
    if isinstance(raw_ids, str):
        raw_ids = [
            part.strip()
            for part in raw_ids.split(",")
            if part.strip()
        ]

    emote_ids = []
    for raw in raw_ids:
        emote_id = re.sub(
            r"[^a-z0-9_-]",
            "",
            str(raw or "").lower()
        )[:40]
        if emote_id and emote_id not in emote_ids:
            emote_ids.append(emote_id)

    source = str(value.get("source") or "selected").lower()
    if source not in {"selected", "all"}:
        source = "selected"

    mode = str(value.get("mode") or "burst").lower()
    if mode not in {"burst", "fountain", "spray"}:
        mode = "burst"

    return {
        "enabled": bool(value.get("enabled", False)),
        "source": source,
        "emoteIds": emote_ids[:40],
        "mode": mode,
        "count": max(1, min(int(value.get("count") or 18), 80)),
        "size": max(18, min(int(value.get("size") or 72), 180)),
        "durationMs": max(500, min(int(value.get("durationMs") or 2200), 8000)),
        "spread": max(80, min(int(value.get("spread") or 420), 1000)),
        "delayMs": max(0, min(int(value.get("delayMs") or 250), 3000)),
    }


def normalize_alert_item(item: dict) -> dict:
    item = dict(item or {})

    platform = str(item.get("platform") or "twitch").lower()
    alert_type = str(item.get("type") or "follow").lower()

    if platform not in ALERT_TYPES_BY_PLATFORM:
        raise ValueError("Plataforma de alerta inválida")

    if alert_type not in ALERT_TYPES_BY_PLATFORM[platform]:
        raise ValueError(
            f"Tipo de alerta inválido para {platform}: {alert_type}"
        )

    return {
        "id": f"{platform}:{alert_type}",
        "platform": platform,
        "type": alert_type,
        "enabled": bool(item.get("enabled", True)),
        "titleTemplate": str(item.get("titleTemplate") or "{user}")[:160],
        "messageTemplate": str(item.get("messageTemplate") or "")[:300],
        "visualUrl": str(item.get("visualUrl") or ""),
        "visualType": str(item.get("visualType") or "").lower(),
        "audioUrl": str(item.get("audioUrl") or ""),
        "audioVolume": max(0.0, min(float(item.get("audioVolume", 0.8)), 1.0)),
        "durationMs": max(500, min(int(item.get("durationMs") or 5000), 120000)),
        "enterAnimation": str(item.get("enterAnimation") or "pop").lower(),
        "exitAnimation": str(item.get("exitAnimation") or "fade").lower(),
        "animation": str(item.get("animation") or "none").lower(),
        "position": str(item.get("position") or "top-center").lower(),
        "size": max(10, min(int(item.get("size") or 45), 100)),
        "advancedEnabled": bool(item.get("advancedEnabled", False)),
        "autoVisualInAdvanced": bool(item.get("autoVisualInAdvanced", True)),
        "customHtml": str(item.get("customHtml") or ""),
        "customCss": str(item.get("customCss") or ""),
        "customJs": str(item.get("customJs") or ""),
        "emoteBurst": normalize_alert_emote_burst(
            item.get("emoteBurst")
        ),
    }


def save_alerts_payload(
    payload: dict,
    make_backup: bool = True
) -> None:
    ensure_storage()

    if make_backup and ALERTS_FILE.exists():
        try:
            current = json.loads(
                ALERTS_FILE.read_text(encoding="utf-8")
            )
            atomic_write_json(
                ALERTS_BACKUP_FILE,
                current
            )
        except Exception:
            pass

    atomic_write_json(
        ALERTS_FILE,
        payload
    )


def load_alerts() -> dict:
    ensure_storage()

    if not ALERTS_FILE.exists():
        payload = default_alert_config()
        save_alerts_payload(
            payload,
            make_backup=False
        )
        atomic_write_json(
            ALERTS_BACKUP_FILE,
            payload
        )

    try:
        payload = json.loads(
            ALERTS_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        try:
            payload = json.loads(
                ALERTS_BACKUP_FILE.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            payload = default_alert_config()

    raw = (
        payload.get("alerts", {})
        if isinstance(payload, dict)
        else {}
    )

    # Migración V25 -> V26: el antiguo Twitch "gift" era una plantilla
    # genérica para donaciones/Bits/raids. Conservamos su diseño en
    # Donación y Bits la primera vez que se abre V26.
    if isinstance(raw, dict) and "twitch:gift" in raw:
        legacy = dict(raw.get("twitch:gift") or {})

        for migrated_type in ("donation", "bits"):
            migrated_key = f"twitch:{migrated_type}"

            if migrated_key not in raw:
                clone = dict(legacy)
                clone["id"] = migrated_key
                clone["platform"] = "twitch"
                clone["type"] = migrated_type
                raw[migrated_key] = clone

    normalized = {}

    for key, item in raw.items():
        try:
            clean = normalize_alert_item(item)
            normalized[clean["id"]] = clean
        except Exception:
            continue

    defaults = default_alert_config()["alerts"]

    for key, item in defaults.items():
        if key not in normalized:
            normalized[key] = normalize_alert_item(item)

    return normalized


def save_one_alert(item: dict) -> dict:
    clean = normalize_alert_item(item)
    current = load_alerts()
    current[clean["id"]] = clean
    save_alerts_payload(
        {"alerts": current},
        make_backup=True
    )
    return clean


def default_chat_design() -> dict:
    return {
        "enabled": False,
        "replaceDefaultCss": False,
        "customHtml": "",
        "customCss": "",
        "customJs": "",
        "updatedAt": now_iso(),
    }


def normalize_chat_design(payload: dict) -> dict:
    payload = dict(payload or {})

    return {
        "enabled": bool(payload.get("enabled", False)),
        "replaceDefaultCss": bool(payload.get("replaceDefaultCss", False)),
        "customHtml": str(payload.get("customHtml") or ""),
        "customCss": str(payload.get("customCss") or ""),
        "customJs": str(payload.get("customJs") or ""),
        "updatedAt": now_iso(),
    }


def load_chat_design() -> dict:
    ensure_storage()

    if not CHAT_DESIGN_FILE.exists():
        payload = default_chat_design()
        atomic_write_json(CHAT_DESIGN_FILE, payload)
        atomic_write_json(CHAT_DESIGN_BACKUP_FILE, payload)
        return payload

    try:
        raw = json.loads(CHAT_DESIGN_FILE.read_text(encoding="utf-8"))
        return normalize_chat_design(raw)
    except Exception:
        try:
            raw = json.loads(CHAT_DESIGN_BACKUP_FILE.read_text(encoding="utf-8"))
            clean = normalize_chat_design(raw)
            atomic_write_json(CHAT_DESIGN_FILE, clean)
            return clean
        except Exception:
            payload = default_chat_design()
            atomic_write_json(CHAT_DESIGN_FILE, payload)
            return payload


def save_chat_design(payload: dict) -> dict:
    ensure_storage()
    clean = normalize_chat_design(payload)

    if CHAT_DESIGN_FILE.exists():
        try:
            current = json.loads(CHAT_DESIGN_FILE.read_text(encoding="utf-8"))
            atomic_write_json(CHAT_DESIGN_BACKUP_FILE, current)
        except Exception:
            pass

    atomic_write_json(CHAT_DESIGN_FILE, clean)
    return clean


def default_layout_studio() -> dict:
    return {
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
        "updatedAt": now_iso(),
    }


def normalize_layout_section(raw: dict, kind: str) -> dict:
    raw = dict(raw or {})
    defaults = default_layout_studio()[kind]

    def clamp(value, low, high, fallback):
        try:
            return max(low, min(high, int(float(value))))
        except Exception:
            return fallback

    positions = {
        "chat": {"bottom-left", "bottom-right", "top-left", "top-right"},
        "alerts": {
            "top-center", "center", "top-left", "top-right",
            "bottom-left", "bottom-center", "bottom-right",
        },
    }[kind]

    position = str(raw.get("position") or defaults["position"])
    if position not in positions:
        position = defaults["position"]

    accent = str(raw.get("accent") or defaults["accent"]).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        accent = defaults["accent"]

    return {
        "width": clamp(raw.get("width"), 220, 1600, defaults["width"]),
        "scale": clamp(raw.get("scale"), 50, 180, defaults["scale"]),
        "position": position,
        "accent": accent,
        "backgroundOpacity": clamp(raw.get("backgroundOpacity"), 0, 100, defaults["backgroundOpacity"]),
        "radius": clamp(raw.get("radius"), 0, 48, defaults["radius"]),
    }


def load_layout_studio() -> dict:
    ensure_storage()
    defaults = default_layout_studio()

    if not LAYOUT_STUDIO_FILE.exists():
        atomic_write_json(LAYOUT_STUDIO_FILE, defaults)
        atomic_write_json(LAYOUT_STUDIO_BACKUP_FILE, defaults)
        return defaults

    try:
        raw = json.loads(LAYOUT_STUDIO_FILE.read_text(encoding="utf-8"))
    except Exception:
        try:
            raw = json.loads(LAYOUT_STUDIO_BACKUP_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = defaults

    return {
        "chat": normalize_layout_section(raw.get("chat", {}), "chat"),
        "alerts": normalize_layout_section(raw.get("alerts", {}), "alerts"),
        "updatedAt": str(raw.get("updatedAt") or now_iso()),
    }


def save_layout_studio(payload: dict) -> dict:
    current = load_layout_studio()
    if LAYOUT_STUDIO_FILE.exists():
        try:
            atomic_write_json(
                LAYOUT_STUDIO_BACKUP_FILE,
                json.loads(LAYOUT_STUDIO_FILE.read_text(encoding="utf-8")),
            )
        except Exception:
            pass

    clean = {
        "chat": normalize_layout_section(payload.get("chat", current["chat"]), "chat"),
        "alerts": normalize_layout_section(payload.get("alerts", current["alerts"]), "alerts"),
        "updatedAt": now_iso(),
    }
    atomic_write_json(LAYOUT_STUDIO_FILE, clean)
    return clean


def diagnostic_snapshot() -> dict:
    ensure_storage()
    integration = integrations_public_state()
    files = {
        "dataDir": str(DATA_DIR),
        "mediaDir": str(USER_MEDIA_DIR),
        "ranking": str(CURRENT_FILE),
        "economy": str(ECONOMY_FILE),
        "alerts": str(ALERTS_FILE),
        "chatDesign": str(CHAT_DESIGN_FILE),
        "layoutStudio": str(LAYOUT_STUDIO_FILE),
        "weeklyRewardsConfig": str(WEEKLY_REWARDS_CONFIG_FILE),
        "weeklyRewardsState": str(WEEKLY_REWARDS_STATE_FILE),
        "hallOfFame": str(HALL_OF_FAME_FILE),
        "integrations": str(INTEGRATIONS_FILE),
        "streamlabsGlobal": str(STREAMLABS_GLOBAL_FILE),
    }
    file_status = {}
    for key, raw_path in files.items():
        path = Path(raw_path)
        parent = path if path.is_dir() else path.parent
        file_status[key] = {
            "path": str(path),
            "exists": path.exists(),
            "parentWritable": os.access(str(parent), os.W_OK) if parent.exists() else False,
        }

    return {
        "ok": True,
        "time": now_iso(),
        "serverSession": SERVER_SESSION_ID,
        "ports": {"local": PORT, "webhook": WEBHOOK_PORT},
        "websocketClient": bool(websocket is not None),
        "eventsBuffered": len(EVENTS),
        "debugEventsBuffered": len(DEBUG_EVENTS),
        "integrations": integration,
        "files": file_status,
    }


def fill_alert_template(
    template: str,
    user: str,
    platform: str,
    amount: str
) -> str:
    return (
        str(template or "")
        .replace("{user}", user)
        .replace("{platform}", platform.upper())
        .replace("{amount}", amount)
    )


def parse_command(command: str) -> tuple[str, list[str]]:
    text = str(command or "").strip()

    if not text.startswith("!"):
        return "", []

    parts = text[1:].strip().split()

    if not parts:
        return "", []

    return parts[0].lower(), parts[1:]



# ============================================================
# Streamlabs persistente global (V30)
# ============================================================

def default_streamlabs_global() -> dict:
    return {
        "enabled": False,
        "socketToken": "",
        "updatedAt": None,
    }


def save_streamlabs_global(
    token: str | None = None,
    enabled: bool | None = None,
) -> dict:
    """
    Guarda Streamlabs fuera de la carpeta de la versión.

    Windows:
    %APPDATA%\\BrynnInteractive\\streamlabs.json

    Esto evita que el token se pierda al pasar de una beta a otra.
    """
    BRYNN_GLOBAL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with STREAMLABS_SETTINGS_LOCK:
        current = default_streamlabs_global()

        if STREAMLABS_GLOBAL_FILE.exists():
            try:
                loaded = json.loads(
                    STREAMLABS_GLOBAL_FILE.read_text(
                        encoding="utf-8"
                    )
                )

                if isinstance(loaded, dict):
                    current.update(loaded)

            except Exception:
                try:
                    backup = json.loads(
                        STREAMLABS_GLOBAL_BACKUP_FILE.read_text(
                            encoding="utf-8"
                        )
                    )

                    if isinstance(backup, dict):
                        current.update(backup)

                except Exception:
                    pass

        if token is not None:
            current["socketToken"] = str(
                token
            ).strip()

        if enabled is not None:
            current["enabled"] = bool(
                enabled
            )

        current["updatedAt"] = now_iso()

        # Backup del estado anterior válido.
        if STREAMLABS_GLOBAL_FILE.exists():
            try:
                previous = json.loads(
                    STREAMLABS_GLOBAL_FILE.read_text(
                        encoding="utf-8"
                    )
                )

                if isinstance(previous, dict):
                    atomic_write_json(
                        STREAMLABS_GLOBAL_BACKUP_FILE,
                        previous
                    )
            except Exception:
                pass

        atomic_write_json(
            STREAMLABS_GLOBAL_FILE,
            current
        )

        # Verificación real desde disco.
        verify = json.loads(
            STREAMLABS_GLOBAL_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(verify, dict):
            raise RuntimeError(
                "El archivo persistente de Streamlabs no es válido."
            )

        return verify


def load_streamlabs_global() -> dict:
    BRYNN_GLOBAL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with STREAMLABS_SETTINGS_LOCK:
        if not STREAMLABS_GLOBAL_FILE.exists():
            return default_streamlabs_global()

        try:
            loaded = json.loads(
                STREAMLABS_GLOBAL_FILE.read_text(
                    encoding="utf-8"
                )
            )

            result = default_streamlabs_global()

            if isinstance(loaded, dict):
                result.update(loaded)

            result["enabled"] = bool(
                result.get(
                    "enabled",
                    False
                )
            )

            result["socketToken"] = str(
                result.get(
                    "socketToken",
                    ""
                )
                or ""
            ).strip()

            return result

        except Exception:
            try:
                backup = json.loads(
                    STREAMLABS_GLOBAL_BACKUP_FILE.read_text(
                        encoding="utf-8"
                    )
                )

                result = default_streamlabs_global()

                if isinstance(backup, dict):
                    result.update(backup)

                return result

            except Exception:
                return default_streamlabs_global()


def migrate_legacy_streamlabs_token(
    config: dict
) -> tuple[dict, bool]:
    """
    Si una versión anterior aún tiene socketToken en data/integrations.json,
    V30 lo mueve automáticamente a AppData.
    """
    changed = False

    streamlabs = config.setdefault(
        "streamlabs",
        {}
    )

    legacy_token = str(
        streamlabs.get(
            "socketToken",
            ""
        )
        or ""
    ).strip()

    global_cfg = load_streamlabs_global()
    global_token = str(
        global_cfg.get(
            "socketToken",
            ""
        )
        or ""
    ).strip()

    if legacy_token and not global_token:
        save_streamlabs_global(
            token=legacy_token,
            enabled=bool(
                streamlabs.get(
                    "enabled",
                    True
                )
            )
        )
        changed = True

    # El secreto deja de vivir en la carpeta del proyecto.
    if streamlabs.get(
        "socketToken",
        ""
    ):
        streamlabs["socketToken"] = ""
        changed = True

    # Si ya existe la configuración global, ésta manda.
    global_cfg = load_streamlabs_global()

    if str(
        global_cfg.get(
            "socketToken",
            ""
        )
        or ""
    ).strip():
        desired_enabled = bool(
            global_cfg.get(
                "enabled",
                False
            )
        )

        if streamlabs.get(
            "enabled"
        ) != desired_enabled:
            streamlabs["enabled"] = desired_enabled
            changed = True

    return config, changed


# ============================================================
# Integraciones directas: Streamlabs + TikFinity
# ============================================================

def default_integrations_config() -> dict:
    return {
        "streamlabs": {
            "enabled": False,
            "socketToken": "",
        },
        "tikfinity": {
            "enabled": True,
            # "webhook" usa TikFinity Web + Actions & Events.
            # "desktop" conserva compatibilidad con la Event API local.
            "mode": "webhook",
            "url": "ws://127.0.0.1:21213/",
            "webhookSecret": secrets.token_urlsafe(24),
            "publicBaseUrl": "",
        },
    }


def save_integrations_config(
    payload: dict,
    make_backup: bool = True
) -> dict:
    ensure_storage()

    clean = default_integrations_config()

    streamlabs = payload.get("streamlabs") or {}
    tikfinity = payload.get("tikfinity") or {}

    clean["streamlabs"]["enabled"] = bool(
        streamlabs.get("enabled", False)
    )

    # V30: nunca persistir secretos dentro de data/integrations.json.
    clean["streamlabs"]["socketToken"] = ""

    clean["tikfinity"]["enabled"] = bool(
        tikfinity.get("enabled", True)
    )

    mode = str(
        tikfinity.get("mode")
        or "webhook"
    ).strip().lower()

    if mode not in {"webhook", "desktop"}:
        mode = "webhook"

    clean["tikfinity"]["mode"] = mode

    url = str(
        tikfinity.get("url")
        or "ws://127.0.0.1:21213/"
    ).strip()

    if not (
        url.startswith("ws://127.0.0.1:")
        or url.startswith("ws://localhost:")
    ):
        url = "ws://127.0.0.1:21213/"

    clean["tikfinity"]["url"] = url

    secret = str(
        tikfinity.get("webhookSecret")
        or ""
    ).strip()

    if len(secret) < 20:
        secret = secrets.token_urlsafe(24)

    clean["tikfinity"]["webhookSecret"] = secret

    public_base = str(
        tikfinity.get("publicBaseUrl")
        or ""
    ).strip().rstrip("/")

    if public_base and not public_base.startswith("https://"):
        public_base = ""

    clean["tikfinity"]["publicBaseUrl"] = public_base

    if make_backup and INTEGRATIONS_FILE.exists():
        try:
            current = json.loads(
                INTEGRATIONS_FILE.read_text(
                    encoding="utf-8"
                )
            )
            atomic_write_json(
                INTEGRATIONS_BACKUP_FILE,
                current
            )
        except Exception:
            pass

    atomic_write_json(
        INTEGRATIONS_FILE,
        clean
    )

    return clean


def load_integrations_config() -> dict:
    ensure_storage()

    if not INTEGRATIONS_FILE.exists():
        config = default_integrations_config()

        global_streamlabs = load_streamlabs_global()

        if str(
            global_streamlabs.get(
                "socketToken",
                ""
            )
            or ""
        ).strip():
            config["streamlabs"]["enabled"] = bool(
                global_streamlabs.get(
                    "enabled",
                    False
                )
            )

        save_integrations_config(
            config,
            make_backup=False
        )

        atomic_write_json(
            INTEGRATIONS_BACKUP_FILE,
            config
        )

        return config

    try:
        raw = json.loads(
            INTEGRATIONS_FILE.read_text(
                encoding="utf-8"
            )
        )

        base = default_integrations_config()

        if isinstance(raw, dict):
            for section in (
                "streamlabs",
                "tikfinity"
            ):
                if isinstance(
                    raw.get(section),
                    dict
                ):
                    base[section].update(
                        raw[section]
                    )

        base, changed = (
            migrate_legacy_streamlabs_token(
                base
            )
        )

        # No reescribimos integrations.json en cada GET.
        # Solo cuando hay una migración/normalización real.
        if changed:
            save_integrations_config(
                base,
                make_backup=True
            )

        return base

    except Exception:
        try:
            backup = json.loads(
                INTEGRATIONS_BACKUP_FILE.read_text(
                    encoding="utf-8"
                )
            )

            base = default_integrations_config()

            if isinstance(backup, dict):
                for section in (
                    "streamlabs",
                    "tikfinity"
                ):
                    if isinstance(
                        backup.get(section),
                        dict
                    ):
                        base[section].update(
                            backup[section]
                        )

            base, _ = (
                migrate_legacy_streamlabs_token(
                    base
                )
            )

            return base

        except Exception:
            config = default_integrations_config()

            global_streamlabs = (
                load_streamlabs_global()
            )

            if str(
                global_streamlabs.get(
                    "socketToken",
                    ""
                )
                or ""
            ).strip():
                config["streamlabs"][
                    "enabled"
                ] = bool(
                    global_streamlabs.get(
                        "enabled",
                        False
                    )
                )

            return config


def streamlabs_bridge_status_update(
    bridge_id: str,
    state: str,
    connected: bool,
    error: str = "",
) -> None:
    bridge_id = str(
        bridge_id or "legacy"
    )[:120]

    now = time.time()

    with STREAMLABS_BRIDGES_LOCK:
        STREAMLABS_BRIDGES[bridge_id] = {
            "state": str(state or "unknown")[:40],
            "connected": bool(connected),
            "error": str(error or "")[:500],
            "lastSeen": now,
        }

    recompute_streamlabs_bridge_status()


def recompute_streamlabs_bridge_status() -> None:
    now = time.time()
    config = load_integrations_config()
    enabled = bool(
        config.get("streamlabs", {}).get(
            "enabled",
            False
        )
    )
    global_streamlabs = load_streamlabs_global()

    token_present = bool(
        str(
            global_streamlabs.get(
                "socketToken",
                ""
            )
            or ""
        ).strip()
    )

    # La preferencia global manda para Streamlabs.
    enabled = bool(
        global_streamlabs.get(
            "enabled",
            enabled
        )
    )

    if not enabled:
        update_integration_status(
            "streamlabs",
            state="disabled",
            connected=False,
            lastError="",
            activeBridges=0,
        )
        return

    if not token_present:
        update_integration_status(
            "streamlabs",
            state="missing_token",
            connected=False,
            lastError="Pega tu Socket API Token en Integraciones.",
            activeBridges=0,
        )
        return

    with STREAMLABS_BRIDGES_LOCK:
        stale = [
            key
            for key, info in STREAMLABS_BRIDGES.items()
            if now - float(info.get("lastSeen", 0)) > 18
        ]

        for key in stale:
            STREAMLABS_BRIDGES.pop(
                key,
                None
            )

        bridges = list(
            STREAMLABS_BRIDGES.values()
        )

    connected_bridges = [
        item
        for item in bridges
        if item.get("connected")
    ]

    if connected_bridges:
        update_integration_status(
            "streamlabs",
            state="connected",
            connected=True,
            lastError="",
            activeBridges=len(connected_bridges),
        )
        return

    if bridges:
        # Prefer a meaningful current bridge state over a stale global one.
        newest = max(
            bridges,
            key=lambda x: x.get(
                "lastSeen",
                0
            )
        )

        state = str(
            newest.get(
                "state",
                "connecting"
            )
        )

        error = str(
            newest.get(
                "error",
                ""
            )
        )

        update_integration_status(
            "streamlabs",
            state=state,
            connected=False,
            lastError=error,
            activeBridges=0,
        )
        return

    update_integration_status(
        "streamlabs",
        state="waiting_bridge",
        connected=False,
        lastError=(
            "No hay un Streamlabs Bridge activo. "
            "Añade streamlabs_bridge.html?v=47&obs=1 como fuente de navegador en OBS."
        ),
        activeBridges=0,
    )


def integrations_public_state() -> dict:
    recompute_streamlabs_bridge_status()
    config = load_integrations_config()

    with INTEGRATION_STATUS_LOCK:
        statuses = json.loads(
            json.dumps(INTEGRATION_STATUS)
        )

    global_streamlabs = load_streamlabs_global()

    token = str(
        global_streamlabs.get(
            "socketToken",
            ""
        )
        or ""
    ).strip()

    masked = ""

    if token:
        masked = (
            "••••••••"
            + token[-4:]
        )

    return {
        "streamlabs": {
            "enabled": bool(
                global_streamlabs.get(
                    "enabled",
                    config["streamlabs"].get(
                        "enabled",
                        False
                    )
                )
            ),
            "tokenPresent": bool(token),
            "tokenMasked": masked,
            "tokenLength": len(token),
            "storageFile": str(
                STREAMLABS_GLOBAL_FILE
            ),
            "storageScope": "global_appdata",
            "storageWritable": os.access(
                str(BRYNN_GLOBAL_DIR),
                os.W_OK
            ),
            **statuses["streamlabs"],
        },
        "tikfinity": {
            "enabled": bool(
                config["tikfinity"].get(
                    "enabled",
                    True
                )
            ),
            "mode": config["tikfinity"].get(
                "mode",
                "webhook"
            ),
            "url": config["tikfinity"].get(
                "url",
                "ws://127.0.0.1:21213/"
            ),
            "publicBaseUrl": config["tikfinity"].get(
                "publicBaseUrl",
                ""
            ),
            "webhookSecretMasked": (
                "••••••••"
                + str(
                    config["tikfinity"].get(
                        "webhookSecret",
                        ""
                    )
                )[-4:]
            ),
            "webhookLocalPort": WEBHOOK_PORT,
            **statuses["tikfinity"],
        },
        "websocketClientAvailable": websocket is not None,
    }


def update_integration_status(
    service: str,
    **changes
) -> None:
    with INTEGRATION_STATUS_LOCK:
        state = INTEGRATION_STATUS.setdefault(
            service,
            {}
        )
        state.update(changes)


def integration_fingerprint(
    service: str,
    event_type: str,
    username: str,
    amount: str,
    unique_id: str = ""
) -> str:
    if unique_id:
        return (
            f"{service}|id|"
            f"{unique_id}"
        )

    bucket = int(time.time() // 4)

    return (
        f"{service}|{event_type}|"
        f"{str(username).lower()}|"
        f"{amount}|{bucket}"
    )


def integration_is_duplicate(
    fingerprint: str
) -> bool:
    now = time.time()

    with INTEGRATION_DEDUPE_LOCK:
        stale = [
            key
            for key, ts in INTEGRATION_DEDUPE.items()
            if now - ts > 30
        ]

        for key in stale:
            INTEGRATION_DEDUPE.pop(
                key,
                None
            )

        if fingerprint in INTEGRATION_DEDUPE:
            return True

        INTEGRATION_DEDUPE[fingerprint] = now

    return False


def trigger_configured_alert(
    platform: str,
    alert_type: str,
    username: str,
    amount: str = "",
    avatar: str = "",
) -> dict | None:
    platform = str(platform).lower()
    alert_type = str(alert_type).lower()

    config = load_alerts().get(
        f"{platform}:{alert_type}"
    )

    if not config:
        return None

    if not config.get(
        "enabled",
        True
    ):
        return None

    rendered = dict(config)

    rendered["title"] = fill_alert_template(
        config.get(
            "titleTemplate",
            ""
        ),
        username,
        platform,
        amount
    )

    rendered["message"] = fill_alert_template(
        config.get(
            "messageTemplate",
            ""
        ),
        username,
        platform,
        amount
    )

    return emit_event(
        "stream_alert",
        {
            "user": {
                "username": username,
                "platform": platform,
                "avatar": avatar,
            },
            "alert": rendered,
            "amount": amount,
            "directIntegration": True,
        }
    )



# TikFinity puede entregar likes sin que exista una ventana de chat/OBS abierta.
# Por eso el backend los registra directamente en el MISMO ranking semanal que
# utiliza /api/interaction (chat de SSN). Nunca usar totalLikes del LIVE.
TIKTOK_LIKE_SCORE = 0.10  # Mismo valor que SCORE.like en script.js.
TIKTOK_LIKE_BATCH_MAX = 100000
RANKING_EXCLUDED_BOTS = frozenset({"streamelements", "nightbot", "moobot"})


def register_tiktok_like_ranking(username: str, quantity: int, avatar: str = "") -> bool:
    username = str(username or "").strip().lstrip("@")
    if not username or username.lower() in RANKING_EXCLUDED_BOTS:
        return False
    if username.casefold() in {"usuario tiktok", "pruebatiktok"}:
        return False

    try:
        quantity = int(quantity)
    except (TypeError, ValueError, OverflowError):
        return False
    if quantity < 1 or quantity > TIKTOK_LIKE_BATCH_MAX:
        return False

    key = f"tiktok:{username.lower()}"
    if is_test_user_key(key):
        return False

    with LOCK:
        state = archive_and_reset_if_needed(load_current())
        users = state.setdefault("users", {})
        entry = users.setdefault(key, {
            "key": key,
            "username": username,
            "platform": "tiktok",
            "score": 0.0,
            "counters": {
                "messages": 0, "likes": 0, "gifts": 0, "giftCoins": 0,
                "donationUsd": 0.0, "follows": 0, "joins": 0,
                "subscriptions": 0,
            },
            "lastInteraction": None,
        })
        entry["username"] = username
        entry["platform"] = "tiktok"
        if avatar:
            entry["avatar"] = str(avatar)
        entry["score"] = round(
            float(entry.get("score", 0)) + quantity * TIKTOK_LIKE_SCORE,
            2,
        )
        counters = entry.setdefault("counters", {})
        counters["likes"] = int(counters.get("likes", 0)) + quantity
        entry["lastInteraction"] = now_iso()
        save_current(state, make_backup=True)
    return True


def award_direct_gumpitas(
    platform: str,
    username: str,
    kind: str,
    avatar: str = "",
    quantity: int = 1,
    gift_coins: int = 0,
    donation_usd: float = 0.0,
) -> dict:
    normalized_username = (
        str(username)
        .strip()
        .lstrip("@")
    )

    key = (
        f"{platform}:"
        f"{normalized_username.lower()}"
    )

    user = {
        "key": key,
        "username": normalized_username,
        "platform": platform,
        "avatar": avatar,
    }

    with LOCK:
        economy = load_economy()

        awarded, wallet = award_gumpitas(
            economy,
            user,
            kind,
            quantity,
            gift_coins,
            donation_usd,
        )

        save_economy(
            economy,
            make_backup=True
        )

    return {
        "awarded": awarded,
        "balance": int(
            wallet.get(
                "balance",
                0
            )
        ),
    }


def handle_direct_platform_event(
    service: str,
    platform: str,
    event_type: str,
    username: str,
    amount_text: str = "",
    avatar: str = "",
    raw: dict | None = None,
    unique_id: str = "",
    gift_coins: int = 0,
    donation_usd: float = 0.0,
    quantity: int = 1,
    test_only: bool = False,
) -> None:
    username = str(
        username or "Usuario"
    ).strip()

    # Los likes de TikTok pueden llegar muchas veces con la misma cantidad
    # en 4 segundos. Sin ID real NO se deben eliminar como duplicados.
    # Con ID estable sí se deduplican, como antes.
    if event_type != "like" or unique_id:
        fingerprint = integration_fingerprint(
            service, event_type, username, amount_text, unique_id,
        )
        if integration_is_duplicate(fingerprint):
            return

    raw_payload = (
        raw
        if isinstance(raw, dict)
        else {}
    )

    record_debug_event(
        service,
        {
            "event": event_type,
            "chatname": username,
            "type": platform,
            "amount": amount_text,
            "raw": raw_payload,
        }
    )

    alert_type = None
    economy_kind = None

    if event_type == "follow":
        alert_type = "follow"
        economy_kind = "follow"

    elif event_type == "subscription":
        alert_type = "subscription"
        economy_kind = "subscription"

    elif platform == "twitch" and event_type == "donation":
        alert_type = "donation"
        economy_kind = "gift"

    elif platform == "twitch" and event_type == "bits":
        alert_type = "bits"
        economy_kind = "gift"

    elif platform == "twitch" and event_type in {"raid", "raids"}:
        alert_type = "raid"

    elif platform == "kick" and event_type == "gift":
        alert_type = "gift"
        economy_kind = "gift"

    elif platform == "kick" and event_type == "reward":
        alert_type = "reward"

    elif platform == "tiktok" and event_type == "gift":
        alert_type = "gift"
        economy_kind = "gift"

    elif platform == "tiktok" and event_type == "like":
        alert_type = "like"
        economy_kind = "like"

    elif platform == "tiktok" and event_type == "share":
        alert_type = "share"
        economy_kind = "share"

    elif platform == "tiktok" and event_type == "join":
        alert_type = "join"
        economy_kind = "join"

    if alert_type:
        trigger_configured_alert(
            platform,
            alert_type,
            username,
            amount_text,
            avatar,
        )

    # Ranking independiente del overlay; pruebas simuladas no lo modifican.
    if platform == "tiktok" and event_type == "like" and not test_only:
        register_tiktok_like_ranking(username, quantity, avatar)

    gumpitas_result = None

    if economy_kind and not test_only:
        gumpitas_result = award_direct_gumpitas(
            platform,
            username,
            economy_kind,
            avatar=avatar,
            quantity=quantity,
            gift_coins=gift_coins,
            donation_usd=donation_usd,
        )

    # V0.44: alimentar metas desde integraciones directas.
    if not test_only:
        signal_amount = max(1, int(quantity or 1))
        if event_type == "like":
            update_goals_signal(platform, "likes", signal_amount, username)
        elif event_type == "follow":
            register_follow_for_goals(platform, username, unique_id)
        elif event_type == "subscription":
            update_goals_signal(platform, "subscriptions", signal_amount, username)
        elif event_type == "gift":
            update_goals_signal(platform, "gifts", signal_amount, username)
            if gift_coins > 0: update_goals_signal(platform, "giftCoins", gift_coins, username)
        elif event_type == "donation":
            update_goals_signal(platform, "gifts", 1, username)
            if donation_usd > 0: update_goals_signal(platform, "donationsUsd", donation_usd, username)
        elif event_type == "bits":
            update_goals_signal(platform, "bits", max(1, gift_coins or signal_amount), username)
        elif event_type == "share":
            update_goals_signal(platform, "shares", signal_amount, username)
        elif event_type == "join":
            update_goals_signal(platform, "joins", signal_amount, username)
        elif event_type in {"raid", "raids"}:
            update_goals_signal(platform, "raids", signal_amount, username)

    gift_name = ""
    if event_type == "gift":
        try:
            gift_name = str(first_nonempty(
                nested_value(raw_payload, "giftName", "gift.name", "giftDetails.giftName", "extendedGiftInfo.name",
                             "data.giftName", "data.gift.name", "data.giftDetails.giftName", "data.extendedGiftInfo.name",
                             "params.gift"),
                ""
            ))
        except Exception:
            gift_name = ""

    automation_dispatch("platform_event", {
        "source": service,
        "platform": platform,
        "event": event_type,
        "username": username,
        "avatar": avatar,
        "amount": amount_text,
        "quantity": int(quantity or 1),
        "giftCoins": int(gift_coins or 0),
        "giftName": gift_name,
        "donationUsd": float(donation_usd or 0),
        "uniqueId": unique_id,
        "testOnly": bool(test_only),
        "user": {
            "key": f"{platform}:{username.lower()}",
            "username": username,
            "platform": platform,
            "avatar": avatar,
        },
        "raw": raw_payload,
    })

    summary = {
        "time": now_iso(),
        "type": event_type,
        "username": username,
        "amount": amount_text,
        "platform": platform,
    }

    if gumpitas_result:
        summary["gumpitas"] = (
            gumpitas_result.get(
                "awarded",
                0
            )
        )

    update_integration_status(
        service,
        lastEvent=summary,
        lastError="",
    )


def first_nonempty(
    *values
):
    for value in values:
        if value is None:
            continue

        if isinstance(value, str):
            if value.strip():
                return value
        elif value != "":
            return value

    return ""


def nested_value(
    data: dict,
    *paths
):
    for path in paths:
        value = data

        try:
            for part in path.split("."):
                if not isinstance(value, dict):
                    raise KeyError(part)
                value = value.get(part)

            if value not in (None, ""):
                return value
        except Exception:
            pass

    return ""


def tikfinity_user_info(
    data: dict
) -> tuple[str, str]:
    username = first_nonempty(
        nested_value(
            data,
            "uniqueId",
            "username",
            "nickname",
            "displayName",
            "user.uniqueId",
            "user.username",
            "user.nickname",
            "user.displayName",
            "user.name",
        ),
        "Usuario TikTok"
    )

    avatar = first_nonempty(
        nested_value(
            data,
            "profilePictureUrl",
            "avatarUrl",
            "thumbnailUrl",
            "user.profilePictureUrl",
            "user.avatarUrl",
            "user.thumbnailUrl",
        ),
        ""
    )

    return (
        str(username),
        str(avatar),
    )


def tikfinity_gift_coins(
    data: dict
) -> int:
    repeat_count = first_nonempty(
        nested_value(
            data,
            "repeatCount",
            "repeat_count",
            "gift.repeatCount",
        ),
        1
    )

    per_gift = first_nonempty(
        nested_value(
            data,
            "diamondCount",
            "diamond_count",
            "gift.diamondCount",
            "giftDetails.diamondCount",
            "extendedGiftInfo.diamondCount",
        ),
        0
    )

    explicit_coins = first_nonempty(
        nested_value(
            data,
            "coins",
            "coinValue",
            "coin_value",
        ),
        0
    )

    try:
        explicit_coins = int(
            float(explicit_coins)
        )
    except Exception:
        explicit_coins = 0

    if explicit_coins > 0:
        return explicit_coins

    try:
        repeat_count = max(
            1,
            int(float(repeat_count))
        )
    except Exception:
        repeat_count = 1

    try:
        per_gift = int(
            float(per_gift)
        )
    except Exception:
        per_gift = 0

    return max(
        0,
        per_gift * repeat_count
    )



def normalize_webhook_value(
    value,
    default=""
) -> str:
    if isinstance(value, list):
        value = value[0] if value else default

    if value is None:
        value = default

    return str(value).strip()


def process_tikfinity_webhook(
    params: dict
) -> dict:
    event_type = normalize_webhook_value(
        params.get("type"),
        ""
    ).lower()

    aliases = {
        "followed": "follow",
        "subscribe": "subscription",
        "sub": "subscription",
        "gifted": "gift",
        "likes": "like",
        "shared": "share",
        "enter": "join",
        "roomuser": "join",
    }

    event_type = aliases.get(
        event_type,
        event_type
    )

    username = normalize_webhook_value(
        params.get("username"),
        ""
    ).lstrip("@")

    nickname = normalize_webhook_value(
        params.get("nickname"),
        ""
    )

    avatar = normalize_webhook_value(
        params.get("avatar"),
        ""
    )

    user_id = normalize_webhook_value(
        params.get("userId"),
        ""
    )

    if not username and nickname:
        username = nickname
    # Evita crear un usuario ficticio que acumule todos los tap taps.
    if event_type == "like" and not username:
        raise ValueError("Like sin usuario de TikTok: revisa {username} en TikFinity")
    username = username or "Usuario TikTok"

    amount_text = ""
    gift_coins = 0
    quantity = 1

    if event_type == "gift":
        gift_name = normalize_webhook_value(
            params.get("gift"),
            "Regalo TikTok"
        )

        try:
            gift_coins = max(
                0,
                int(
                    float(
                        normalize_webhook_value(
                            params.get("coins"),
                            "0"
                        )
                    )
                )
            )
        except Exception:
            gift_coins = 0

        try:
            repeat = max(
                1,
                int(
                    float(
                        normalize_webhook_value(
                            params.get("repeat"),
                            "1"
                        )
                    )
                )
            )
        except Exception:
            repeat = 1

        parts = [gift_name]

        if repeat > 1:
            parts.append(
                f"x{repeat}"
            )
        quantity = repeat

        if gift_coins > 0:
            parts.append(
                f"· {gift_coins} monedas"
            )

        amount_text = " ".join(parts)

    elif event_type == "subscription":
        months = normalize_webhook_value(
            params.get("months"),
            ""
        )

        if months:
            amount_text = f"{months} meses"

    elif event_type == "like":
        # {likecount} = likes NUEVOS de este evento. {totallikecount}
        # = total del LIVE (no es un delta y nunca se debe sumar).
        count_raw = first_nonempty(
            params.get("likes"), params.get("likeCount"),
            params.get("like_count"), params.get("value1"),
        )
        try:
            quantity = int(float(normalize_webhook_value(count_raw, "0")))
        except (TypeError, ValueError, OverflowError):
            quantity = 0
        if not (1 <= quantity <= TIKTOK_LIKE_BATCH_MAX):
            raise ValueError("Like sin cantidad válida: usa {likecount}, no {totallikecount}")
        amount_text = f"{quantity} likes"

    elif event_type == "share":
        amount_text = "Compartió el LIVE"

    elif event_type == "join":
        amount_text = "Entró al LIVE"

    if event_type not in {
        "follow",
        "subscription",
        "gift",
        "like",
        "share",
        "join",
    }:
        raise ValueError(
            f"Evento TikFinity no soportado: {event_type}"
        )

    # Solo usamos un ID único si TikFinity nos entrega uno real.
    # V23 construía un fallback como "follow"; eso hacía que todos los
    # follows de prueba parecieran el mismo evento durante la ventana
    # de deduplicación.
    unique_id = normalize_webhook_value(
        params.get("eventId"),
        ""
    )

    handle_direct_platform_event(
        "tikfinity_web",
        "tiktok",
        event_type,
        username,
        amount_text=amount_text,
        avatar=avatar,
        raw={
            "webhook": True,
            "params": {
                key: normalize_webhook_value(value)
                for key, value in params.items()
            },
        },
        unique_id=unique_id,
        gift_coins=gift_coins,
        quantity=quantity,
    )

    update_integration_status(
        "tikfinity",
        state="webhook_ready",
        connected=True,
        lastConnectedAt=now_iso(),
        lastError="",
    )

    return {
        "ok": True,
        "type": event_type,
        "username": username,
    }


def process_kick_event(event_type: str, data: dict, message_id: str) -> dict:
    """Atomically claim a Kick delivery and release the claim if its processing fails."""
    cfg = KICK.load()
    broadcaster = data.get("broadcaster") if isinstance(data.get("broadcaster"), dict) else {}
    if str(broadcaster.get("user_id") or "") != str(cfg.get("userId") or ""):
        raise KickError("El broadcaster de Kick no coincide con la cuenta autorizada.")
    if not KICK.mark_processed(message_id):
        return {"ok": True, "duplicate": True}
    try:
        return _process_kick_event_claimed(event_type, data, message_id)
    except Exception:
        KICK.unmark_processed(message_id)
        raise


def _process_kick_event_claimed(event_type: str, data: dict, message_id: str) -> dict:
    """Route a claimed, verified Kick webhook payload through Brynn's native event engine."""

    who_field = {
        "channel.followed": "follower", "channel.subscription.new": "subscriber",
        "channel.subscription.renewal": "subscriber", "channel.subscription.gifts": "gifter",
        "kicks.gifted": "sender", "channel.reward.redemption.updated": "redeemer",
    }.get(event_type, "sender")
    who = data.get(who_field) if isinstance(data.get(who_field), dict) else {}
    username = str(who.get("username") or "Anónimo")
    avatar = str(who.get("profile_picture") or "")
    amount = ""
    quantity = 1
    coins = 0
    if event_type == "chat.message.sent":
        msg = str(data.get("content") or "")[:2000]
        if not msg:
            KICK.mark_processed(message_id)
            return {"ok": True, "ignored": "empty_chat"}
        badges = (who.get("identity") or {}).get("badges") or []
        flags = {str(x.get("type") or "").lower() for x in badges if isinstance(x, dict)}
        payload = {
            "type": "kick", "chatname": username, "chatmessage": msg, "chatimg": avatar,
            "mid": str(data.get("message_id") or message_id), "moderator": "moderator" in flags,
            "broadcaster": "broadcaster" in flags, "membership": "" if "subscriber" not in flags else None,
            "chatbadges": [str(x.get("text") or x.get("type") or "") for x in badges if isinstance(x, dict)],
        }
        KICK.register_chat_user(username, who.get("user_id"))
        ingest_chat_event(payload, "kick")
    elif event_type == "channel.followed":
        handle_direct_platform_event("kick", "kick", "follow", username, avatar=avatar, raw=data, unique_id=message_id)
    elif event_type in {"channel.subscription.new", "channel.subscription.renewal"}:
        amount = f"{int(data.get('duration') or 1)} mes(es)"
        handle_direct_platform_event("kick", "kick", "subscription", username, amount_text=amount, avatar=avatar, raw=data, unique_id=message_id)
    elif event_type in {"channel.subscription.gifts", "kicks.gifted"}:
        if event_type == "channel.subscription.gifts":
            giftees = data.get("giftees") or []
            quantity = max(1, len(giftees)) if isinstance(giftees, list) else 1
            amount = f"{quantity} subs regaladas"
        else:
            gift = data.get("gift") if isinstance(data.get("gift"), dict) else {}
            coins = max(0, int(gift.get("amount") or 0))
            amount = f"{gift.get('name') or 'KICKs'} · {coins} KICKs"
        handle_direct_platform_event("kick", "kick", "gift", username,
                                     amount_text=amount, quantity=quantity, gift_coins=coins,
                                     avatar=avatar, raw=data, unique_id=message_id)
    elif event_type == "channel.reward.redemption.updated":
        # No premiar con Gumpitas por gastar puntos oficiales de Kick.
        # Únicamente alertar el canje aceptado y activar las automatizaciones.
        if data.get("status") == "accepted":
            reward = data.get("reward") if isinstance(data.get("reward"), dict) else {}
            handle_direct_platform_event("kick", "kick", "reward", username,
                                         amount_text=str(reward.get("title") or "Recompensa"),
                                         avatar=avatar, raw=data, unique_id=message_id)
    elif event_type == "livestream.status.updated":
        update_integration_status("kick", state="live" if data.get("is_live") else "offline",
                                  connected=True, lastEvent={"type": event_type, "live": bool(data.get("is_live"))})
    else:
        KICK.mark_processed(message_id)
        return {"ok": True, "ignored": event_type}

    KICK.mark_processed(message_id)
    event_summary = {"type": event_type, "username": username, "time": now_iso(), "amount": amount}
    KICK.last_event = event_summary
    KICK.last_delivery = now_iso()
    update_integration_status("kick", state="webhook_verified", connected=True,
                              lastError="", lastEvent=event_summary, lastConnectedAt=now_iso())
    return {"ok": True, "event": event_type}


class TikFinityWebhookHandler(SimpleHTTPRequestHandler):
    server_version = "BrynnTikFinityWebhook/1.0"

    def log_message(self, format, *args):
        # El path /t/SECRET es una credencial: no imprimirla en logs.
        if "/health" in str(args[0] if args else ""):
            return
        redacted = tuple(
            re.sub(r"/t/[^?\s]+", "/t/[oculto]", str(arg))
            for arg in args
        )
        super().log_message(format, *redacted)

    def send_json(self, payload: dict, status: int = 200):
        raw = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(raw))
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.end_headers()
        self.wfile.write(raw)

    def _read_params(self) -> dict:
        parsed = urlparse(self.path)
        params = parse_qs(
            parsed.query,
            keep_blank_values=True
        )

        if self.command == "POST":
            try:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        "0"
                    )
                )
            except Exception:
                length = 0

            body = self.rfile.read(
                max(0, min(length, 256000))
            )

            content_type = str(
                self.headers.get(
                    "Content-Type",
                    ""
                )
            ).lower()

            if body:
                try:
                    if "application/json" in content_type:
                        decoded = json.loads(
                            body.decode(
                                "utf-8",
                                errors="replace"
                            )
                        )

                        if isinstance(decoded, dict):
                            for key, value in decoded.items():
                                params[key] = [value]
                    else:
                        form = parse_qs(
                            body.decode(
                                "utf-8",
                                errors="replace"
                            ),
                            keep_blank_values=True
                        )
                        params.update(form)
                except Exception:
                    pass

        return {
            key: (
                values[0]
                if isinstance(values, list) and values
                else values
            )
            for key, values in params.items()
        }

    def _handle(self):
        parsed = urlparse(self.path)

        if parsed.path == "/kick/webhook":
            if self.command != "POST":
                self.send_json({"ok": False, "error": "Method Not Allowed"}, 405)
                return
            if not KICK.public().get("connected"):
                self.send_json({"ok": False, "error": "Kick no configurado"}, 503)
                return
            try:
                size = int(self.headers.get("Content-Length") or "0")
                if size <= 0 or size > 256000:
                    self.send_json({"ok": False, "error": "Tamaño inválido"}, 413)
                    return
                raw_body = self.rfile.read(size)
                mid = KICK.verify_webhook(self.headers, raw_body)
                event_type = str(self.headers.get("Kick-Event-Type") or "")
                if event_type not in KICK_EVENT_TYPES:
                    self.send_json({"ok": True, "ignored": event_type})
                    return
                data = json.loads(raw_body)
                if not isinstance(data, dict):
                    raise ValueError("Payload inválido")
                self.send_json(process_kick_event(event_type, data, mid))
            except KickError as exc:
                KICK.last_error = str(exc)[:160]
                self.send_json({"ok": False, "error": str(exc)}, 403)
            except (ValueError, UnicodeError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                KICK.last_error = str(exc)[:160]
                self.send_json({"ok": False, "error": "Kick webhook error"}, 500)
            return

        if parsed.path == "/health":
            self.send_json(
                {
                    "ok": True,
                    "service": "tikfinity-webhook",
                    "port": WEBHOOK_PORT,
                }
            )
            return

        config = load_integrations_config()
        tik = config.get(
            "tikfinity",
            {}
        )

        secret = str(
            tik.get(
                "webhookSecret",
                ""
            )
        )

        expected_path = (
            "/t/"
            + urllib.parse.quote(
                secret,
                safe=""
            )
        )

        if (
            not tik.get("enabled", True)
            or tik.get("mode", "webhook") != "webhook"
        ):
            self.send_json(
                {
                    "ok": False,
                    "error": "TikFinity Webhook está deshabilitado"
                },
                503
            )
            return

        if parsed.path != expected_path:
            self.send_json(
                {
                    "ok": False,
                    "error": "Not found"
                },
                404
            )
            return

        params = self._read_params()

        # V23: deja evidencia de que TikFinity/Cloudflare realmente
        # alcanzaron nuestro receptor, incluso si después un parámetro falla.
        record_debug_event(
            "tikfinity_web_http",
            {
                "event": str(params.get("type") or "webhook_request"),
                "chatname": str(
                    params.get("username")
                    or params.get("nickname")
                    or "Sin usuario"
                ),
                "type": "tiktok",
                "raw": {
                    "method": self.command,
                    "path": "/t/[oculto]",
                    "params": params,
                },
            }
        )

        try:
            result = process_tikfinity_webhook(
                params
            )
            self.send_json(result)

        except ValueError as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc)
                },
                400
            )

        except Exception as exc:
            update_integration_status(
                "tikfinity",
                state="webhook_error",
                connected=False,
                lastError=str(exc)[:300],
            )
            self.send_json(
                {
                    "ok": False,
                    "error": "Webhook processing error"
                },
                500
            )

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()


def start_tikfinity_webhook_server() -> None:
    def run():
        try:
            httpd = ThreadingHTTPServer(
                (
                    WEBHOOK_HOST,
                    WEBHOOK_PORT
                ),
                TikFinityWebhookHandler
            )

            config = load_integrations_config()
            tik = config.get(
                "tikfinity",
                {}
            )

            if (
                tik.get("enabled", True)
                and tik.get("mode", "webhook") == "webhook"
            ):
                update_integration_status(
                    "tikfinity",
                    state="webhook_ready",
                    connected=True,
                    lastConnectedAt=now_iso(),
                    lastError="",
                )

            httpd.serve_forever()

        except Exception as exc:
            update_integration_status(
                "tikfinity",
                state="webhook_error",
                connected=False,
                lastError=(
                    f"No se pudo abrir el puerto "
                    f"{WEBHOOK_PORT}: {exc}"
                ),
            )

    threading.Thread(
        target=run,
        name="Brynn-TikFinityWebhook",
        daemon=True,
    ).start()


def process_tikfinity_packet(
    packet: dict
) -> None:
    event_name = str(
        packet.get(
            "event",
            ""
        )
    ).strip().lower()

    data = packet.get("data")

    if not isinstance(data, dict):
        data = packet

    username, avatar = (
        tikfinity_user_info(
            data
        )
    )

    unique_id = str(
        first_nonempty(
            nested_value(
                data,
                "msgId",
                "messageId",
                "id",
                "giftId",
            ),
            ""
        )
    )

    if event_name == "follow":
        handle_direct_platform_event(
            "tikfinity",
            "tiktok",
            "follow",
            username,
            avatar=avatar,
            raw=packet,
            unique_id=unique_id,
        )
        return

    if event_name == "subscribe":
        months = first_nonempty(
            nested_value(
                data,
                "subMonth",
                "months",
                "month",
            ),
            ""
        )

        amount = (
            f"{months} meses"
            if str(months).strip()
            else ""
        )

        handle_direct_platform_event(
            "tikfinity",
            "tiktok",
            "subscription",
            username,
            amount_text=amount,
            avatar=avatar,
            raw=packet,
            unique_id=unique_id,
        )
        return

    if event_name == "gift":
        coins = tikfinity_gift_coins(
            data
        )

        gift_name = str(
            first_nonempty(
                nested_value(
                    data,
                    "giftName",
                    "gift.name",
                    "giftDetails.giftName",
                    "extendedGiftInfo.name",
                ),
                "Regalo TikTok"
            )
        )

        repeat_count = first_nonempty(
            nested_value(
                data,
                "repeatCount",
                "repeat_count",
                "gift.repeatCount",
            ),
            1
        )

        try:
            repeat_count = max(
                1,
                int(float(repeat_count))
            )
        except Exception:
            repeat_count = 1

        amount_parts = [
            gift_name
        ]

        if repeat_count > 1:
            amount_parts.append(
                f"x{repeat_count}"
            )

        if coins > 0:
            amount_parts.append(
                f"· {coins} monedas"
            )

        handle_direct_platform_event(
            "tikfinity",
            "tiktok",
            "gift",
            username,
            amount_text=" ".join(
                amount_parts
            ),
            avatar=avatar,
            raw=packet,
            unique_id=unique_id,
            gift_coins=coins,
            quantity=repeat_count,
        )
        return

    if event_name == "like":
        # id puede representar al usuario y repetirse entre varios taps.
        # Para dedupe usar solo IDs inequívocos del evento.
        unique_id = str(first_nonempty(
            nested_value(data, "msgId", "messageId", "eventId"), ""
        ))
        like_count = first_nonempty(
            nested_value(
                data,
                "likeCount",
                "count",
                "likes",
            ),
            1
        )

        try:
            like_count = int(float(like_count))
        except (TypeError, ValueError, OverflowError):
            like_count = 0
        if not (1 <= like_count <= TIKTOK_LIKE_BATCH_MAX):
            return
        if not username or username.strip().lower() == "usuario tiktok":
            return

        handle_direct_platform_event(
            "tikfinity",
            "tiktok",
            "like",
            username,
            raw=packet,
            unique_id=unique_id,
            quantity=like_count,
        )
        return


def process_streamlabs_event(
    event_data: dict
) -> None:
    if not isinstance(event_data, dict):
        return

    event_type = str(
        event_data.get(
            "type",
            ""
        )
    ).lower()

    event_for = str(
        event_data.get(
            "for",
            ""
        )
    ).lower()

    messages = event_data.get(
        "message",
        []
    )

    if not isinstance(messages, list):
        messages = [messages]

    for message in messages:
        if not isinstance(message, dict):
            continue

        username = str(
            first_nonempty(
                message.get("name"),
                message.get("from"),
                "Usuario"
            )
        )

        unique_id = str(
            first_nonempty(
                event_data.get("event_id"),
                message.get("_id"),
                message.get("id"),
                ""
            )
        )

        if event_type == "donation":
            raw_amount = first_nonempty(
                message.get("amount"),
                0
            )

            try:
                usd = max(
                    0.0,
                    float(raw_amount)
                )
            except Exception:
                usd = 0.0

            formatted = str(
                first_nonempty(
                    message.get(
                        "formatted_amount"
                    ),
                    message.get(
                        "formattedAmount"
                    ),
                    (
                        f"${usd:.2f}"
                        if usd > 0
                        else "Donación"
                    )
                )
            )

            handle_direct_platform_event(
                "streamlabs",
                "twitch",
                "donation",
                username,
                amount_text=formatted,
                raw=event_data,
                unique_id=unique_id,
                donation_usd=usd,
            )
            continue

        if event_for != "twitch_account":
            continue

        if event_type == "follow":
            handle_direct_platform_event(
                "streamlabs",
                "twitch",
                "follow",
                username,
                raw=event_data,
                unique_id=unique_id,
            )
            continue

        if event_type == "subscription":
            months = first_nonempty(
                message.get("months"),
                ""
            )

            sub_type = str(
                first_nonempty(
                    message.get("sub_type"),
                    ""
                )
            )

            amount_parts = []

            if months not in ("", None):
                amount_parts.append(
                    f"{months} meses"
                )

            if sub_type:
                amount_parts.append(
                    sub_type
                )

            handle_direct_platform_event(
                "streamlabs",
                "twitch",
                "subscription",
                username,
                amount_text=" · ".join(
                    amount_parts
                ),
                raw=event_data,
                unique_id=unique_id,
            )
            continue

        if event_type == "bits":
            try:
                bits = max(
                    0,
                    int(
                        float(
                            message.get(
                                "amount",
                                0
                            )
                        )
                    )
                )
            except Exception:
                bits = 0

            handle_direct_platform_event(
                "streamlabs",
                "twitch",
                "bits",
                username,
                amount_text=(
                    f"{bits} Bits"
                    if bits
                    else "Bits"
                ),
                raw=event_data,
                unique_id=unique_id,
                # 100 Bits ~= $1 al creador; usamos la misma
                # regla configurable de apoyo por dólar.
                donation_usd=(
                    bits / 100.0
                    if bits > 0
                    else 0.0
                ),
            )
            continue

        if event_type in {
            "raid",
            "raids",
        }:
            raiders = first_nonempty(
                message.get("raiders"),
                message.get("viewers"),
                ""
            )

            handle_direct_platform_event(
                "streamlabs",
                "twitch",
                "raid",
                username,
                amount_text=(
                    f"{raiders} viewers"
                    if str(raiders).strip()
                    else "Raid"
                ),
                raw=event_data,
                unique_id=unique_id,
            )


def streamlabs_worker() -> None:
    while True:
        config = load_integrations_config()
        cfg = config.get(
            "streamlabs",
            {}
        )

        enabled = bool(
            cfg.get(
                "enabled",
                False
            )
        )

        global_streamlabs = (
            load_streamlabs_global()
        )

        enabled = bool(
            global_streamlabs.get(
                "enabled",
                enabled
            )
        )

        token = str(
            global_streamlabs.get(
                "socketToken",
                ""
            )
            or ""
        ).strip()

        if not enabled:
            update_integration_status(
                "streamlabs",
                state="disabled",
                connected=False,
                lastError="",
            )
            time.sleep(2)
            continue

        if not token:
            update_integration_status(
                "streamlabs",
                state="missing_token",
                connected=False,
                lastError="Pega tu Socket API Token en Integraciones.",
            )
            time.sleep(2)
            continue

        if websocket is None:
            update_integration_status(
                "streamlabs",
                state="dependency_error",
                connected=False,
                lastError="No se pudo cargar websocket-client.",
            )
            time.sleep(4)
            continue

        ws = None

        try:
            update_integration_status(
                "streamlabs",
                state="connecting",
                connected=False,
                lastError="",
            )

            encoded_token = urllib.parse.quote(
                token,
                safe=""
            )

            url = (
                "wss://sockets.streamlabs.com/"
                "socket.io/?"
                f"token={encoded_token}"
                "&EIO=3"
                "&transport=websocket"
            )

            ws = websocket.create_connection(
                url,
                timeout=8,
                origin="https://streamlabs.com",
            )

            ws.settimeout(4)

            namespace_sent = False
            connected = False

            while True:
                latest = (
                    load_streamlabs_global()
                )

                if not latest.get(
                    "enabled",
                    False
                ):
                    break

                if str(
                    latest.get(
                        "socketToken",
                        ""
                    )
                    or ""
                ).strip() != token:
                    break

                try:
                    message = ws.recv()
                except Exception as exc:
                    # Un timeout de lectura no significa desconexión.
                    if "timed out" in str(exc).lower():
                        continue
                    raise

                if isinstance(
                    message,
                    bytes
                ):
                    message = message.decode(
                        "utf-8",
                        errors="replace"
                    )

                message = str(message)

                if message.startswith("0"):
                    if not namespace_sent:
                        ws.send("40")
                        namespace_sent = True
                    continue

                if message.startswith("2"):
                    # Engine.IO v3 ping -> pong
                    ws.send(
                        "3" + message[1:]
                    )
                    continue

                if message.startswith("40"):
                    connected = True
                    update_integration_status(
                        "streamlabs",
                        state="connected",
                        connected=True,
                        lastConnectedAt=now_iso(),
                        lastError="",
                    )
                    continue

                if message.startswith("42"):
                    try:
                        packet = json.loads(
                            message[2:]
                        )
                    except Exception:
                        continue

                    if (
                        isinstance(packet, list)
                        and len(packet) >= 2
                        and packet[0] == "event"
                    ):
                        if not connected:
                            connected = True
                            update_integration_status(
                                "streamlabs",
                                state="connected",
                                connected=True,
                                lastConnectedAt=now_iso(),
                                lastError="",
                            )

                        process_streamlabs_event(
                            packet[1]
                        )

        except Exception as exc:
            update_integration_status(
                "streamlabs",
                state="error",
                connected=False,
                lastError=str(exc)[:300],
            )

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

            if load_integrations_config().get(
                "streamlabs",
                {}
            ).get("enabled", False):
                update_integration_status(
                    "streamlabs",
                    connected=False,
                )

        time.sleep(3)


def tikfinity_worker() -> None:
    while True:
        config = load_integrations_config()
        cfg = config.get(
            "tikfinity",
            {}
        )

        enabled = bool(
            cfg.get(
                "enabled",
                True
            )
        )

        mode = str(
            cfg.get(
                "mode",
                "webhook"
            )
        ).lower()

        if mode != "desktop":
            time.sleep(2)
            continue

        url = str(
            cfg.get(
                "url",
                "ws://127.0.0.1:21213/"
            )
        )

        if not enabled:
            update_integration_status(
                "tikfinity",
                state="disabled",
                connected=False,
                lastError="",
            )
            time.sleep(2)
            continue

        if websocket is None:
            update_integration_status(
                "tikfinity",
                state="dependency_error",
                connected=False,
                lastError="No se pudo cargar websocket-client.",
            )
            time.sleep(4)
            continue

        ws = None

        try:
            update_integration_status(
                "tikfinity",
                state="connecting",
                connected=False,
                lastError="",
            )

            ws = websocket.create_connection(
                url,
                timeout=4,
            )

            ws.settimeout(4)

            update_integration_status(
                "tikfinity",
                state="connected",
                connected=True,
                lastConnectedAt=now_iso(),
                lastError="",
            )

            while True:
                latest = load_integrations_config().get(
                    "tikfinity",
                    {}
                )

                if not latest.get(
                    "enabled",
                    True
                ):
                    break

                if str(
                    latest.get(
                        "url",
                        "ws://127.0.0.1:21213/"
                    )
                ) != url:
                    break

                try:
                    message = ws.recv()
                except Exception as exc:
                    if "timed out" in str(exc).lower():
                        continue
                    raise

                if isinstance(
                    message,
                    bytes
                ):
                    message = message.decode(
                        "utf-8",
                        errors="replace"
                    )

                try:
                    packet = json.loads(
                        str(message)
                    )
                except Exception:
                    continue

                if isinstance(
                    packet,
                    dict
                ):
                    process_tikfinity_packet(
                        packet
                    )

        except Exception as exc:
            update_integration_status(
                "tikfinity",
                state="error",
                connected=False,
                lastError=str(exc)[:300],
            )

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

            if load_integrations_config().get(
                "tikfinity",
                {}
            ).get("enabled", True):
                update_integration_status(
                    "tikfinity",
                    connected=False,
                )

        time.sleep(3)


def start_integration_workers() -> None:
    """
    V20:
    - TikFinity se mantiene directamente en Python.
    - Streamlabs usa streamlabs_bridge.html con el cliente Socket.IO 2.x,
      que es el método documentado por Streamlabs.
    """
    thread = threading.Thread(
        target=tikfinity_worker,
        name="Brynn-TikFinity",
        daemon=True,
    )
    thread.start()


# ============================================================
# Monitor de eventos crudos
# ============================================================

def record_debug_event(source: str, payload: dict) -> dict:
    global DEBUG_EVENT_COUNTER

    source = str(source or "unknown")[:40]
    if not isinstance(payload, dict):
        payload = {"value": str(payload)}

    with DEBUG_EVENTS_LOCK:
        DEBUG_EVENT_COUNTER += 1
        row = {
            "id": DEBUG_EVENT_COUNTER,
            "time": now_iso(),
            "source": source,
            "payload": payload,
        }
        DEBUG_EVENTS.append(row)

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with DEBUG_EVENTS_FILE.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    return row


def debug_events_after(after: int = 0) -> list[dict]:
    with DEBUG_EVENTS_LOCK:
        return [
            row for row in DEBUG_EVENTS
            if int(row.get("id", 0)) > after
        ]



# ============================================================
# V0.44 - Metas / Goal system
# ============================================================

def _copy_json_backup(source: Path, backup: Path) -> None:
    try:
        if source.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
    except Exception:
        pass


def goal_write_locked(func):
    """Serialize goal read-modify-write operations across live event threads."""
    from functools import wraps
    @wraps(func)
    def inner(*args, **kwargs):
        with GOALS_LOCK:
            return func(*args, **kwargs)
    return inner


def default_goal_visuals() -> dict:
    return {
        "html": (
            "<div class='goal-card'>"
            "<div class='goal-top'><span class='goal-title'>{title}</span>"
            "<span class='goal-count'>{current} / {target}</span></div>"
            "<div class='goal-track'><div class='goal-fill' style='width:{percent}%'></div></div>"
            "<div class='goal-foot'>{remaining} restantes · {percent}%</div>"
            "</div>"
        ),
        "css": (
            ":root{--goal-accent:#53E6FF;--goal-ink:#F2EAD8;--goal-dark:rgba(10,14,24,.92)}"
            ".goal-card{width:min(620px,92vw);padding:16px 18px;color:var(--goal-ink);"
            "background:var(--goal-dark);border:1px solid color-mix(in srgb,var(--goal-accent) 46%,transparent);"
            "border-radius:16px;font-family:'Segoe UI',sans-serif;box-shadow:0 14px 36px rgba(0,0,0,.35)}"
            ".goal-top{display:flex;gap:18px;justify-content:space-between;align-items:end}.goal-title{font-weight:900;font-size:22px}"
            ".goal-count{font-weight:800;color:var(--goal-accent)}.goal-track{height:13px;margin-top:12px;border-radius:999px;"
            "overflow:hidden;background:rgba(255,255,255,.08)}.goal-fill{height:100%;border-radius:inherit;background:var(--goal-accent);"
            "box-shadow:0 0 18px var(--goal-accent);transition:width .6s cubic-bezier(.2,.9,.2,1)}"
            ".goal-foot{margin-top:8px;opacity:.7;font-size:12px}"
        ),
        "js": "GOAL_ROOT.dataset.ready='1';",
        "celebrationHtml": (
            "<div class='goal-win'><div class='goal-win-kicker'>META ALCANZADA</div>"
            "<div class='goal-win-title'>{title}</div><div class='goal-win-value'>{target}</div>"
            "<div class='goal-win-user'>{lastUser}</div></div>"
        ),
        "celebrationCss": (
            ".goal-win{padding:28px 42px;text-align:center;color:#F2EAD8;background:rgba(10,14,24,.94);"
            "border:2px solid var(--goal-accent);border-radius:22px;box-shadow:0 0 60px color-mix(in srgb,var(--goal-accent) 55%,transparent);"
            "animation:goalWin .65s cubic-bezier(.2,1,.2,1) both}.goal-win-kicker{letter-spacing:.22em;font-size:12px;color:var(--goal-accent)}"
            ".goal-win-title{font-size:34px;font-weight:1000;margin-top:8px}.goal-win-value{font-size:54px;font-weight:1000;color:var(--goal-accent)}"
            ".goal-win-user{opacity:.8;margin-top:6px}@keyframes goalWin{0%{opacity:0;transform:scale(.55) rotate(-3deg)}70%{transform:scale(1.06)}100%{opacity:1;transform:scale(1)}}"
        ),
        "celebrationJs": (
            "for(let i=0;i<24;i++){const p=document.createElement('i');p.className='goal-particle';"
            "p.style.cssText=`position:fixed;left:50%;top:50%;width:7px;height:7px;border-radius:50%;background:var(--goal-accent);pointer-events:none`;"
            "GOAL_ROOT.appendChild(p);const a=Math.random()*Math.PI*2,d=80+Math.random()*280;"
            "p.animate([{transform:'translate(-50%,-50%) scale(1)',opacity:1},{transform:`translate(calc(-50% + ${Math.cos(a)*d}px),calc(-50% + ${Math.sin(a)*d}px)) scale(.2)`,opacity:0}],{duration:900+Math.random()*900,easing:'cubic-bezier(.1,.7,.2,1)',fill:'forwards'});setTimeout(()=>p.remove(),1900)}"
        ),
    }


def default_goals_payload() -> dict:
    return {"goals": [], "updatedAt": now_iso()}


def normalize_goal_item(raw: dict) -> dict:
    raw = dict(raw or {})
    visuals = default_goal_visuals()
    goal_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or ""))[:48]
    if not goal_id:
        goal_id = "goal_" + secrets.token_hex(4)
    allowed_types = {
        "followers", "followersTotal", "subscriptions", "likes", "gifts", "giftCoins",
        "donationsUsd", "raids", "messages", "viewers", "shares", "joins", "bits", "custom"
    }
    kind = str(raw.get("type") or "followers")
    if kind not in allowed_types:
        kind = "custom"
    platform = str(raw.get("platform") or "all").lower()
    if platform not in {"all", "twitch", "tiktok", "kick", "tiktok_kick"}:
        platform = "all"
    try: target = max(1.0, float(raw.get("target", 100) or 100))
    except Exception: target = 100.0
    try: start = max(0.0, float(raw.get("start", 0) or 0))
    except Exception: start = 0.0
    try: duration = max(500, min(30000, int(raw.get("celebrationDurationMs", 6500) or 6500)))
    except Exception: duration = 6500
    accent = str(raw.get("accent") or "#53E6FF")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent): accent = "#53E6FF"
    return {
        "id": goal_id,
        "title": str(raw.get("title") or "Nueva meta")[:100],
        "type": kind,
        "platform": platform,
        "target": target,
        "start": start,
        "enabled": bool(raw.get("enabled", True)),
        "accent": accent,
        "html": str(raw.get("html") if raw.get("html") is not None else visuals["html"]),
        "css": str(raw.get("css") if raw.get("css") is not None else visuals["css"]),
        "js": str(raw.get("js") if raw.get("js") is not None else visuals["js"]),
        "celebrationHtml": str(raw.get("celebrationHtml") if raw.get("celebrationHtml") is not None else visuals["celebrationHtml"]),
        "celebrationCss": str(raw.get("celebrationCss") if raw.get("celebrationCss") is not None else visuals["celebrationCss"]),
        "celebrationJs": str(raw.get("celebrationJs") if raw.get("celebrationJs") is not None else visuals["celebrationJs"]),
        "celebrationDurationMs": duration,
        "updatedAt": now_iso(),
    }


def load_goals() -> dict:
    ensure_storage()
    if not GOALS_FILE.exists():
        payload = default_goals_payload()
        GOALS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    try:
        raw = json.loads(GOALS_FILE.read_text(encoding="utf-8"))
        goals = [normalize_goal_item(x) for x in (raw.get("goals") or []) if isinstance(x, dict)]
        return {"goals": goals, "updatedAt": raw.get("updatedAt") or now_iso()}
    except Exception:
        return default_goals_payload()


def current_followers_for_goal(goal: dict) -> int | None:
    if goal.get("type") != "followersTotal":
        return None
    rows = FOLLOWERS.public()["platforms"]
    platform = goal.get("platform", "all")
    if platform in ("all", "tiktok_kick"):
        names = ("tiktok", "kick", "twitch") if platform == "all" else ("tiktok", "kick")
        if not all(rows[p].get("count") is not None for p in names):
            return None
        return sum(int(rows[p]["count"]) for p in names)
    count = rows.get(platform, {}).get("count")
    return int(count) if count is not None else None


@goal_write_locked
def save_goals(payload: dict, make_backup: bool = True) -> dict:
    ensure_storage()
    if make_backup: _copy_json_backup(GOALS_FILE, GOALS_BACKUP_FILE)
    rows = payload.get("goals") if isinstance(payload, dict) else []
    clean_rows = [normalize_goal_item(x) for x in (rows or []) if isinstance(x, dict)]
    stamp = now_iso()
    for item in clean_rows: item["updatedAt"] = stamp
    clean = {"goals": clean_rows, "updatedAt": stamp}
    GOALS_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    # ensure state entries exist without destroying progress
    state = load_goals_state()
    changed = False
    valid = {g["id"] for g in clean["goals"]}
    for goal in clean["goals"]:
        if goal["id"] not in state["values"]:
            state["values"][goal["id"]] = {"current": float(goal.get("start",0)), "completed": False, "completedAt": None, "lastUser": "", "lastAmount": 0, "updatedAt": now_iso()}
            changed = True
        # Metas absolutas reflejan el total conocido también al crearlas/editar el tipo.
        known = current_followers_for_goal(goal)
        if known is not None:
            sr = state["values"][goal["id"]]
            if sr.get("current") != known:
                sr.update({"current": known, "completed": known >= goal["target"],
                           "completedAt": sr.get("completedAt") if known >= goal["target"] else None,
                           "updatedAt": now_iso()})
                changed = True
    for key in list(state["values"]):
        if key not in valid:
            del state["values"][key]; changed=True
    if changed: save_goals_state(state)
    return clean


def load_goals_state() -> dict:
    ensure_storage()
    if not GOALS_STATE_FILE.exists():
        state={"values":{},"updatedAt":now_iso()}
        GOALS_STATE_FILE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
        return state
    try:
        raw=json.loads(GOALS_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw,dict): raise ValueError()
        raw.setdefault("values",{}); return raw
    except Exception:
        return {"values":{},"updatedAt":now_iso()}


def save_goals_state(state: dict, make_backup: bool = True) -> dict:
    ensure_storage()
    if make_backup: _copy_json_backup(GOALS_STATE_FILE, GOALS_STATE_BACKUP_FILE)
    state=dict(state or {}); state.setdefault("values",{}); state["updatedAt"]=now_iso()
    GOALS_STATE_FILE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    return state


def goal_public_item(goal: dict, state_row: dict | None = None) -> dict:
    row=dict(goal); state_row=state_row or {}
    current=float(state_row.get("current", goal.get("start",0)) or 0)
    target=max(1.0,float(goal.get("target",1) or 1))
    percent=max(0.0,min(100.0,(current/target)*100.0))
    row.update({
        "current": round(current,2), "remaining": round(max(0.0,target-current),2),
        "percent": round(percent,2), "completed": bool(state_row.get("completed", current>=target)),
        "completedAt": state_row.get("completedAt"), "lastUser": state_row.get("lastUser", ""),
        "lastAmount": state_row.get("lastAmount",0), "stateUpdatedAt": state_row.get("updatedAt"),
    })
    if goal.get("type") == "followersTotal":
        rows = FOLLOWERS.public()["platforms"]
        chosen = (["tiktok", "kick", "twitch"] if goal.get("platform") == "all" else
                  ["tiktok", "kick"] if goal.get("platform") == "tiktok_kick" else
                  [goal.get("platform")])
        sources = [rows.get(platform, {}) for platform in chosen]
        row["syncFresh"] = bool(sources and all(x.get("fresh") for x in sources))
        row["syncStatus"] = ("VERIFICADO" if row["syncFresh"] else
                             "SIN BASE" if any(x.get("count") is None for x in sources) else "ESTIMADO")
        row["syncSource"] = ", ".join(str(x.get("source") or "none") for x in sources)
    else:
        row["syncFresh"] = False
        row["syncStatus"] = ""
        row["syncSource"] = ""
    return row


@goal_write_locked
def goals_public() -> dict:
    cfg=load_goals(); state=load_goals_state(); values=state.get("values",{})
    return {"ok":True,"goals":[goal_public_item(g,values.get(g["id"],{})) for g in cfg.get("goals",[])],"updatedAt":max(str(cfg.get("updatedAt") or ""),str(state.get("updatedAt") or ""))}


@goal_write_locked
def update_goals_signal(platform: str, kind: str, amount: float = 1, username: str = "", absolute: bool = False, test_only: bool = False) -> list[dict]:
    platform=str(platform or "").lower(); kind=str(kind or "")
    try: amount=float(amount)
    except Exception: amount=0.0
    if amount < 0: amount=0.0
    if test_only: return []
    cfg=load_goals(); state=load_goals_state(); values=state.setdefault("values",{}); reached=[]; dirty=False
    for goal in cfg.get("goals",[]):
        if not goal.get("enabled",True) or goal.get("type") != kind: continue
        accepted = {"all", platform}
        if platform in {"tiktok", "kick"}:
            accepted.add("tiktok_kick")
        if goal.get("platform") not in accepted: continue
        # Combined absolute goals are calculated by apply_follower_totals, not by a single source.
        if kind == "followersTotal" and goal.get("platform") in {"all", "tiktok_kick"} and platform != goal.get("platform"): continue
        sid=goal["id"]; sr=values.setdefault(sid,{"current":float(goal.get("start",0)),"completed":False,"completedAt":None,"lastUser":"","lastAmount":0,"updatedAt":now_iso()})
        before=float(sr.get("current",0) or 0)
        after=amount if absolute else before+amount
        sr["current"]=round(max(0.0,after),2); sr["lastUser"]=str(username or sr.get("lastUser") or ""); sr["lastAmount"]=round(amount,2); sr["updatedAt"]=now_iso(); dirty=True
        target=float(goal.get("target",1) or 1)
        was=bool(sr.get("completed",False))
        now=sr["current"]>=target
        if now and not was:
            sr["completed"]=True; sr["completedAt"]=now_iso()
            public=goal_public_item(goal,sr); reached.append(public)
            emit_event("goal_reached", {"goal":public,"render":{"html":goal.get("celebrationHtml",""),"css":goal.get("celebrationCss",""),"js":goal.get("celebrationJs",""),"durationMs":int(goal.get("celebrationDurationMs",6500) or 6500)}})
        elif not now and absolute:
            sr["completed"]=False; sr["completedAt"]=None
    if dirty: save_goals_state(state, make_backup=False)
    return reached



def apply_follower_totals(platform: str, count: int) -> None:
    """Reconcile absolute goals; only show a combined total if every source has a baseline."""
    update_goals_signal(platform, "followersTotal", count, absolute=True)
    rows = FOLLOWERS.public()["platforms"]
    if all(rows.get(p, {}).get("count") is not None for p in ("tiktok", "kick")):
        both = int(rows["tiktok"]["count"]) + int(rows["kick"]["count"])
        update_goals_signal("tiktok_kick", "followersTotal", both, absolute=True)
    if all(rows.get(p, {}).get("count") is not None for p in ("tiktok", "kick", "twitch")):
        grand_total = sum(int(rows[p]["count"]) for p in ("tiktok", "kick", "twitch"))
        update_goals_signal("all", "followersTotal", grand_total, absolute=True)


def register_follow_for_goals(platform: str, username: str, event_key: str = "") -> bool:
    if not FOLLOWERS.add_follow(platform, username, event_key):
        return False
    update_goals_signal(platform, "followers", 1, username)
    value = FOLLOWERS.public()["platforms"].get(platform, {}).get("count")
    if value is not None:
        apply_follower_totals(platform, int(value))
    return True


@goal_write_locked
def adjust_goal_value(goal_id: str, value: float, mode: str = "add", username: str = "Manual") -> tuple[dict | None, list[dict]]:
    cfg=load_goals(); goal=next((g for g in cfg.get("goals",[]) if g.get("id")==goal_id),None)
    if not goal: return None, []
    state=load_goals_state(); values=state.setdefault("values",{})
    sr=values.setdefault(goal_id,{"current":float(goal.get("start",0)),"completed":False,"completedAt":None,"lastUser":"","lastAmount":0,"updatedAt":now_iso()})
    before=float(sr.get("current",0) or 0)
    try: value=max(0.0,float(value))
    except Exception: value=0.0
    after=value if str(mode)=="set" else before+value
    sr["current"]=round(after,2); sr["lastUser"]=str(username or "Manual"); sr["lastAmount"]=round(value,2); sr["updatedAt"]=now_iso()
    target=float(goal.get("target",1) or 1); was=bool(sr.get("completed",False)); now=sr["current"]>=target; reached=[]
    if now and not was:
        sr["completed"]=True; sr["completedAt"]=now_iso(); public=goal_public_item(goal,sr); reached.append(public)
        emit_event("goal_reached", {"goal":public,"render":{"html":goal.get("celebrationHtml",""),"css":goal.get("celebrationCss",""),"js":goal.get("celebrationJs",""),"durationMs":int(goal.get("celebrationDurationMs",6500) or 6500)}})
    elif not now and str(mode)=="set":
        sr["completed"]=False; sr["completedAt"]=None
    save_goals_state(state,make_backup=False)
    return goal_public_item(goal,sr), reached


@goal_write_locked
def reset_goal(goal_id: str) -> dict | None:
    cfg=load_goals(); goal=next((g for g in cfg.get("goals",[]) if g.get("id")==goal_id),None)
    if not goal: return None
    baseline = current_followers_for_goal(goal)
    initial = float(baseline) if baseline is not None else float(goal.get("start",0))
    state=load_goals_state(); state.setdefault("values",{})[goal_id]={"current":initial,"completed":initial>=float(goal.get("target",1)),"completedAt":None,"lastUser":"","lastAmount":0,"updatedAt":now_iso()}; save_goals_state(state)
    return goal_public_item(goal,state["values"][goal_id])


# ============================================================
# V0.44 - Chat flotante / viewer metrics / SSN control
# ============================================================

def default_floating_chat_config() -> dict:
    return {
        "maxMessages": 600, "windowOpacity": 100, "zoom": 100,
        "width": 520, "height": 720, "alwaysOnTop": True,
        "startClickThrough": False, "showViewerCounts": True, "showComposer": True,
        "hotkeys": {"toggleClickThrough":"Ctrl+Alt+C","toggleVisible":"Ctrl+Alt+H","opacityUp":"Ctrl+Alt+Up","opacityDown":"Ctrl+Alt+Down","focusComposer":"Ctrl+Alt+Enter"},
        "updatedAt": now_iso(),
    }


def normalize_floating_chat_config(raw: dict | None) -> dict:
    out=default_floating_chat_config(); raw=raw if isinstance(raw,dict) else {}
    out.update({k:v for k,v in raw.items() if k in out and k!="hotkeys"})
    hk=dict(out["hotkeys"]); hk.update(raw.get("hotkeys") or {}); out["hotkeys"]={k:str(v or "")[:60] for k,v in hk.items()}
    for key,lo,hi in (("maxMessages",50,2500),("windowOpacity",15,100),("zoom",60,180),("width",280,1800),("height",260,1400)):
        try: out[key]=max(lo,min(hi,int(out[key])))
        except Exception: out[key]=default_floating_chat_config()[key]
    for key in ("alwaysOnTop","startClickThrough","showViewerCounts","showComposer"): out[key]=bool(out.get(key))
    out["updatedAt"]=str(raw.get("updatedAt") or out.get("updatedAt") or now_iso())
    return out


def load_floating_chat_config() -> dict:
    ensure_storage()
    if not FLOATING_CHAT_CONFIG_FILE.exists():
        cfg=default_floating_chat_config(); FLOATING_CHAT_CONFIG_FILE.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8"); return cfg
    try: return normalize_floating_chat_config(json.loads(FLOATING_CHAT_CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception: return default_floating_chat_config()


def save_floating_chat_config(raw: dict) -> dict:
    ensure_storage(); _copy_json_backup(FLOATING_CHAT_CONFIG_FILE,FLOATING_CHAT_CONFIG_BACKUP_FILE)
    cfg=normalize_floating_chat_config(raw); cfg["updatedAt"]=now_iso(); FLOATING_CHAT_CONFIG_FILE.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8"); return cfg


def load_twitch_control_private() -> dict:
    default={"enabled":False,"clientId":"","accessToken":"","broadcasterId":"","moderatorId":"","updatedAt":None}
    try:
        if TWITCH_CONTROL_FILE.exists(): default.update(json.loads(TWITCH_CONTROL_FILE.read_text(encoding="utf-8")))
    except Exception: pass
    return default


def save_twitch_control_private(raw: dict) -> dict:
    BRYNN_GLOBAL_DIR.mkdir(parents=True,exist_ok=True); _copy_json_backup(TWITCH_CONTROL_FILE,TWITCH_CONTROL_BACKUP_FILE)
    old=load_twitch_control_private(); clean={
        "enabled":bool(raw.get("enabled",old.get("enabled",False))),
        "clientId":str(raw.get("clientId") or old.get("clientId") or "").strip(),
        "accessToken":str(raw.get("accessToken") or old.get("accessToken") or "").strip().replace("oauth:",""),
        "broadcasterId":str(raw.get("broadcasterId") or old.get("broadcasterId") or "").strip(),
        "moderatorId":str(raw.get("moderatorId") or old.get("moderatorId") or "").strip(),
        "updatedAt":now_iso(),
    }; TWITCH_CONTROL_FILE.write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding="utf-8"); return clean


def twitch_control_public() -> dict:
    cfg=load_twitch_control_private(); return {"enabled":bool(cfg.get("enabled")),"clientId":cfg.get("clientId",""),"broadcasterId":cfg.get("broadcasterId",""),"moderatorId":cfg.get("moderatorId",""),"tokenPresent":bool(cfg.get("accessToken")),"updatedAt":cfg.get("updatedAt")}


def _ssn_request(action: str, target: str = "null", value: str = "") -> tuple[bool,str]:
    cfg=load_social_stream_config(); session=str(cfg.get("sessionId") or "").strip()
    if not session: return False,"Falta Session ID de Social Stream Ninja"
    path="https://io.socialstream.ninja/"+urllib.parse.quote(session,safe="")+"/"+urllib.parse.quote(action,safe="")
    if target or value: path += "/"+urllib.parse.quote(str(target or "null"),safe="")
    if value != "": path += "/"+urllib.parse.quote(str(value),safe="")
    try:
        req=urllib.request.Request(path,headers={"User-Agent":"BrynnInteractive/0.60"});
        with urllib.request.urlopen(req,timeout=5) as resp: body=resp.read(4096).decode("utf-8","ignore")
        # HTTP 200 confirms transport delivery only, not publication on a platform.
        if body.strip().lower() in {"false", "error", "null", "unauthorized"}:
            return False, "SSN devolvió: " + body.strip()
        return True,body
    except Exception as exc: return False,str(exc)


def _ssn_send_chat(message: str) -> tuple[bool, str]:
    """Send to SSN channel 1 using the documented POST command format.

    An HTTP success is a relay acknowledgement, not a platform delivery receipt.
    """
    ssn_cfg = load_social_stream_config()
    session = str(ssn_cfg.get("sessionId") or "").strip()
    password = str(ssn_cfg.get("password") or "false").strip() or "false"
    if not session:
        return False, "Falta configurar Session ID de Social Stream Ninja"
    endpoint = "https://io.socialstream.ninja/" + urllib.parse.quote(session, safe="") + "?channel=1"
    command = {"action": "sendChat", "value": message, "apiid": session, "out": 1}
    if password and password.lower() != "false":
        command["password"] = password
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(command, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "BrynnInteractive/0.60.3"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(4096).decode("utf-8", "replace").strip()
        if body.lower() in ("false", "null", "error", "unauthorized"):
            return False, "SSN rechazó el comando: " + body
        try:
            obj = json.loads(body)
            if obj is False or (isinstance(obj, dict) and obj.get("ok") is False):
                return False, "SSN rechazó el comando: " + body[:200]
        except (ValueError, TypeError):
            pass
        return True, "Comando recibido por SSN (sin confirmación de publicación)"
    except urllib.error.HTTPError as exc:
        return False, "SSN HTTP " + str(exc.code)
    except Exception as exc:
        return False, "Sin conexión con SSN: " + str(exc)


def twitch_api_request(path: str, method: str="GET", body: dict | None=None) -> tuple[bool,dict|str]:
    cfg=load_twitch_control_private(); token=str(cfg.get("accessToken") or ""); client=str(cfg.get("clientId") or "")
    if not cfg.get("enabled") or not token or not client: return False,"Twitch Control no está configurado"
    url="https://api.twitch.tv/helix/"+path.lstrip("/"); data=None
    if body is not None: data=json.dumps(body).encode("utf-8")
    req=urllib.request.Request(url,data=data,method=method,headers={"Authorization":"Bearer "+token,"Client-Id":client,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=6) as resp:
            raw=resp.read().decode("utf-8","ignore"); return True,(json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        try: detail=exc.read().decode("utf-8","ignore")
        except Exception: detail=str(exc)
        return False,detail
    except Exception as exc: return False,str(exc)


def twitch_user_id(username: str) -> tuple[bool,str]:
    ok,data=twitch_api_request("users?login="+urllib.parse.quote(str(username).lstrip("@")))
    if not ok: return False,str(data)
    rows=data.get("data",[]) if isinstance(data,dict) else []
    return (True,str(rows[0].get("id"))) if rows else (False,"Usuario de Twitch no encontrado")


def twitch_moderate(username: str, action: str, duration: int=0, reason: str="") -> tuple[bool,str]:
    cfg=load_twitch_control_private(); ok,uid=twitch_user_id(username)
    if not ok: return False,uid
    broadcaster=str(cfg.get("broadcasterId") or ""); moderator=str(cfg.get("moderatorId") or broadcaster)
    if not broadcaster or not moderator: return False,"Faltan broadcasterId/moderatorId"
    qs="?broadcaster_id="+urllib.parse.quote(broadcaster)+"&moderator_id="+urllib.parse.quote(moderator)
    if action=="unban":
        ok,data=twitch_api_request("moderation/bans"+qs+"&user_id="+urllib.parse.quote(uid),method="DELETE"); return ok,("OK" if ok else str(data))
    payload={"data":{"user_id":uid}}
    if reason: payload["data"]["reason"]=reason[:500]
    if action=="timeout": payload["data"]["duration"]=max(1,min(1209600,int(duration or 600)))
    ok,data=twitch_api_request("moderation/bans"+qs,method="POST",body=payload); return ok,("OK" if ok else str(data))


def fetch_twitch_viewers() -> tuple[int|None,str]:
    now=time.time()
    if now-float(TWITCH_VIEWER_CACHE.get("time",0))<15: return TWITCH_VIEWER_CACHE.get("value"),str(TWITCH_VIEWER_CACHE.get("error") or "")
    cfg=load_twitch_control_private(); bid=str(cfg.get("broadcasterId") or "")
    if not bid: return None,""
    ok,data=twitch_api_request("streams?user_id="+urllib.parse.quote(bid))
    if ok:
        rows=data.get("data",[]) if isinstance(data,dict) else []; val=int(rows[0].get("viewer_count",0)) if rows else 0; err=""
        with VIEWER_LOCK: VIEWER_COUNTS["twitch"]=val; VIEWER_UPDATED["twitch"]=now_iso()
    else: val=None; err=str(data)
    TWITCH_VIEWER_CACHE.update({"value":val,"time":now,"error":err}); return val,err


def _chat_fingerprint(data: dict) -> str:
    mid=str(data.get("mid") or data.get("messageId") or data.get("id") or "")
    if mid: return "mid:"+str(data.get("type") or data.get("platform") or "").lower()+":"+mid
    return "|".join([str(data.get("type") or ""),str(data.get("chatname") or ""),str(data.get("chatmessage") or data.get("membership") or data.get("hasDonation") or ""),str(data.get("event") or ""),str(data.get("contentimg") or "")])


def extract_viewer_count(data: dict) -> int | None:
    candidates=[]
    for obj in (data, data.get("meta") if isinstance(data.get("meta"),dict) else {}):
        for key in ("viewerCount","viewer_count","viewers","currentViewers","current_viewers","liveViewers"):
            if key in obj: candidates.append(obj.get(key))
    for value in candidates:
        try:
            n=int(float(str(value).replace(",",""))); return max(0,n)
        except Exception: pass
    return None


def ingest_chat_event(data: dict, source: str="ssn") -> dict | None:
    global CHAT_EVENT_COUNTER
    if not isinstance(data,dict): return None
    platform=str(data.get("type") or data.get("platform") or "").lower()
    if "twitch" in platform: platform="twitch"
    elif "tiktok" in platform: platform="tiktok"
    elif "kick" in platform: platform="kick"
    viewer=extract_viewer_count(data)
    if viewer is not None and platform in VIEWER_COUNTS:
        with VIEWER_LOCK: VIEWER_COUNTS[platform]=viewer; VIEWER_UPDATED[platform]=now_iso()
        update_goals_signal(platform,"viewers",viewer,absolute=True)
    if not (data.get("chatmessage") or data.get("hasDonation") or data.get("membership") or data.get("contentimg")): return None
    fp=_chat_fingerprint(data); now=time.time()
    with CHAT_DEDUPE_LOCK:
        for key,stamp in list(CHAT_DEDUPE.items()):
            if now-stamp>(15.0 if key.startswith("mid:") else 1.5): CHAT_DEDUPE.pop(key,None)
        if fp in CHAT_DEDUPE: return None
        CHAT_DEDUPE[fp]=now
    raw={k:data.get(k) for k in ("chatname","chatmessage","chatimg","type","chatbadges","membership","hasDonation","contentimg","event","textonly","moderator","broadcaster","admin","bot","donoValue","mid","id") if k in data}
    with CHAT_EVENT_LOCK:
        CHAT_EVENT_COUNTER+=1; row={"id":CHAT_EVENT_COUNTER,"time":now_iso(),"source":source,"platform":platform,"username":str(data.get("chatname") or "Usuario"),"message":str(data.get("chatmessage") or data.get("membership") or data.get("hasDonation") or ""),"avatar":str(data.get("chatimg") or ""),"raw":raw}; CHAT_EVENTS.append(row)
    automation_dispatch("chat_message", {
        "source": source, "platform": platform, "event": "message",
        "username": row.get("username"), "message": row.get("message"),
        "raw": raw,
    })
    return row


def chat_events_after(after: int) -> list[dict]:
    with CHAT_EVENT_LOCK: return [x for x in CHAT_EVENTS if int(x.get("id",0))>after]


def viewers_public() -> dict:
    tw,err=fetch_twitch_viewers()
    kv = KICK.get_viewers()
    with VIEWER_LOCK:
        # Never publish an old viewer count after Kick reports offline or its API fails.
        VIEWER_COUNTS["kick"] = kv
        VIEWER_UPDATED["kick"] = now_iso()
    if kv is not None:
        update_goals_signal("kick", "viewers", kv, absolute=True)
    with VIEWER_LOCK:
        return {"ok": True, "twitch": VIEWER_COUNTS.get("twitch") if tw is None else tw,
                "tiktok": VIEWER_COUNTS.get("tiktok"), "kick": VIEWER_COUNTS.get("kick"),
                "updated": dict(VIEWER_UPDATED), "twitchError": err, "kickError": KICK.last_error}


# ============================================================
# HTTP
# ============================================================

class AppHandler(SimpleHTTPRequestHandler):
    server_version = "BrynnInteractiveChat/22.0"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Same-origin desktop + OBS overlays. Never advertise an open CORS API.
        super().end_headers()

    def _allowed_request_origin(self):
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return True  # Native desktop helpers and server-side requests
        try:
            parsed = urllib.parse.urlsplit(origin)
            host = (parsed.hostname or "").lower()
            return parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "[::1]", "::1"} and parsed.port == PORT
        except (ValueError, AttributeError):
            return False

    def send_json(self, payload: dict, status: int = 200):
        body = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(
            self.headers.get(
                "Content-Length",
                "0"
            )
        )

        if length <= 0 or length > 1024 * 1024:
            return {}

        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/user_media/"):
            filename = urllib.parse.unquote(
                path[len("/user_media/"):]
            )

            if (
                not filename
                or filename != Path(filename).name
                or "/" in filename
                or "\\" in filename
            ):
                self.send_error(404)
                return

            target = USER_MEDIA_DIR / filename

            if not target.is_file():
                self.send_error(404)
                return

            content_type = (
                mimetypes.guess_type(str(target))[0]
                or "application/octet-stream"
            )

            try:
                size = target.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.end_headers()

                with target.open("rb") as handle:
                    shutil.copyfileobj(
                        handle,
                        self.wfile
                    )
            except Exception:
                self.send_error(500)
            return

        if path == "/api/social-stream-config":
            cfg = load_social_stream_config()
            self.send_json({
                "ok": True,
                "sessionId": cfg.get("sessionId", ""),
                "password": cfg.get("password", "false"),
            })
            return

        if path == "/api/ranking":
            with LOCK:
                state = archive_and_reset_if_needed(
                    load_current()
                )
                self.send_json(public_state(state))
            return

        if path == "/api/archives":
            with LOCK:
                self.send_json(
                    {
                        "archives": list_week_files()
                    }
                )
            return

        if path == "/api/economy":
            with LOCK:
                self.send_json(
                    public_economy(
                        load_economy()
                    )
                )
            return

        if path == "/api/profile":
            try:
                profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8")) if PROFILE_FILE.exists() else {}
            except Exception:
                profile = {}
            self.send_json({
                "ok": True,
                "profile": {
                    "streamerName": str(profile.get("streamerName") or ""),
                    "owners": dict(profile.get("owners") or {}),
                    "developerMode": bool(profile.get("developerMode", False)),
                },
            })
            return

        if path == "/api/economy-config":
            self.send_json(
                {
                    "ok": True,
                    "rates": load_economy_rates(),
                    "branding": load_economy_branding(),
                }
            )
            return

        if path == "/api/store":
            self.send_json({"items": store_public(), "currency": currency_public()})
            return

        if path == "/api/commands":
            self.send_json({"commands": load_commands()})
            return

        if path == "/api/emotes":
            self.send_json({"emotes": load_emotes()})
            return

        if path == "/api/weekly-rewards":
            self.send_json(weekly_admin_payload())
            return

        if path == "/api/weekly-rewards/active":
            self.send_json(weekly_public_active())
            return

        if path == "/api/weekly-access":
            kind = str((query.get("kind") or [""])[0]).strip().lower()
            item_id = str((query.get("id") or [""])[0]).strip().lower()
            if kind not in {"emote", "command"} or not item_id:
                self.send_json({"ok": False, "error": "kind/id inválidos"}, 400)
                return
            self.send_json(weekly_item_access_summary(kind, item_id))
            return

        if path == "/api/hall-of-fame":
            self.send_json({
                "ok": True,
                "hall": load_hall_of_fame(),
                "users": hall_user_summary(),
            })
            return

        if path == "/api/alerts-config":
            self.send_json(
                {"alerts": list(load_alerts().values())}
            )
            return

        if path == "/api/chat-design":
            self.send_json(
                {"ok": True, "design": load_chat_design()}
            )
            return

        if path == "/api/layout-studio":
            self.send_json({"ok": True, "layout": load_layout_studio()})
            return

        if path == "/api/obs":
            self.send_json(OBS.status(refresh=True))
            return

        if path == "/api/obs/inventory":
            try:
                self.send_json({"ok": True, **OBS.inventory()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 502)
            return

        if path == "/api/automations":
            data = AUTOMATION_ENGINE.load() if AUTOMATION_ENGINE else {"automations": []}
            self.send_json({"ok": True, **data, "runtime": AUTOMATION_ENGINE.runtime_state() if AUTOMATION_ENGINE else {}})
            return

        if path == "/api/diagnostics":
            self.send_json(diagnostic_snapshot())
            return

        if path == "/api/integrations":
            self.send_json(
                {
                    "ok": True,
                    **integrations_public_state()
                }
            )
            return

        if path == "/api/integrations/tikfinity-webhook-config":
            config = load_integrations_config()
            tik = config.get("tikfinity", {})
            secret = str(
                tik.get(
                    "webhookSecret",
                    ""
                )
            )

            self.send_json(
                {
                    "ok": True,
                    "enabled": bool(
                        tik.get(
                            "enabled",
                            True
                        )
                    ),
                    "mode": tik.get(
                        "mode",
                        "webhook"
                    ),
                    "publicBaseUrl": tik.get(
                        "publicBaseUrl",
                        ""
                    ),
                    "webhookSecret": secret,
                    "localBaseUrl": (
                        f"http://{WEBHOOK_HOST}:"
                        f"{WEBHOOK_PORT}"
                    ),
                }
            )
            return

        if path == "/api/integrations/streamlabs-token":
            cfg = load_streamlabs_global()

            enabled = bool(
                cfg.get(
                    "enabled",
                    False
                )
            )

            token = str(
                cfg.get(
                    "socketToken",
                    ""
                )
                or ""
            ).strip()

            self.send_json(
                {
                    "ok": True,
                    "enabled": enabled,
                    "socketToken": (
                        token
                        if enabled
                        else ""
                    ),
                    "storageScope": "global_appdata",
                }
            )
            return

        if path == "/api/debug-events":
            try:
                after = int(query.get("after", ["0"])[0])
            except Exception:
                after = 0

            self.send_json({"events": debug_events_after(after)})
            return

        if path == "/api/events":
            try:
                after = int(
                    query.get(
                        "after",
                        ["0"]
                    )[0]
                )
            except Exception:
                after = 0

            self.send_json(
                {
                    "sessionId": SERVER_SESSION_ID,
                    "latestId": latest_event_id(),
                    "events": events_after(after)
                }
            )
            return

        if path == "/api/goals":
            self.send_json(goals_public())
            return

        if path == "/api/followers":
            self.send_json(FOLLOWERS.public())
            return

        if path == "/api/floating-chat-config":
            self.send_json({"ok": True, "config": load_floating_chat_config()})
            return

        if path == "/api/chat/messages":
            try: after = int(query.get("after", ["0"])[0])
            except Exception: after = 0
            self.send_json({"ok": True, "latestId": CHAT_EVENT_COUNTER, "messages": chat_events_after(after)})
            return

        if path == "/api/chat/viewers":
            self.send_json(viewers_public())
            return

        if path == "/api/kick":
            self.send_json({"ok": True, **KICK.public()})
            return

        if path == "/api/kick/oauth/callback":
            try:
                error = str(query.get("error", [""])[0])
                if error:
                    raise KickError("Kick rechazó la autorización: " + error[:100])
                KICK.finish_oauth(query.get("code", [""])[0], query.get("state", [""])[0])
                body = "<html><meta charset='utf-8'><title>Kick conectado</title><body style='font:20px sans-serif;background:#10151b;color:#f5f5f5;padding:3rem'><h2>✅ Kick autorizado en Brynn</h2><p>Vuelve a Integraciones y pulsa 'Suscribir eventos'.</p></body></html>"
            except KickError as exc:
                from html import escape as html_escape
                body = "<html><meta charset='utf-8'><body><h2>Error de conexión Kick</h2><p>" + html_escape(str(exc)) + "</p></body></html>"
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if path == "/api/twitch-control":
            self.send_json({"ok": True, **twitch_control_public()})
            return

        if path == "/api/health":
            self.send_json(
                {
                    "ok": True,
                    "sessionId": SERVER_SESSION_ID,
                    "period": current_period_key(),
                    "time": now_iso(),
                    "ranking": str(CURRENT_FILE),
                    "economy": str(ECONOMY_FILE),
                    "economyBranding": str(ECONOMY_BRANDING_FILE),
                    "commands": str(COMMANDS_FILE),
                    "emotes": str(EMOTES_FILE),
                    "alerts": str(ALERTS_FILE),
                    "chatDesign": str(CHAT_DESIGN_FILE),
                    "weeklyRewards": str(WEEKLY_REWARDS_CONFIG_FILE),
                    "hallOfFame": str(HALL_OF_FAME_FILE),
                    "goals": str(GOALS_FILE),
                    "floatingChat": str(FLOATING_CHAT_CONFIG_FILE),
                    "obsConfig": str(OBS_CONFIG_FILE),
                    "automations": str(AUTOMATIONS_FILE),
                    "dataDir": str(DATA_DIR),
                    "mediaDir": str(USER_MEDIA_DIR),
                }
            )
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._allowed_request_origin():
            self.send_json({"ok": False, "error": "Origen externo no autorizado"}, 403)
            return
        if path.startswith("/api/") and path != "/api/upload" and not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self.send_json({"ok": False, "error": "Se requiere Content-Type: application/json"}, 415)
            return

        if path == "/api/upload":
            self.handle_upload(parsed)
            return

        try:
            payload = self.read_json()
        except Exception as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc)
                },
                400
            )
            return

        if path == "/api/followers/settings":
            try:
                self.send_json(FOLLOWERS.configure(payload))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/followers/manual":
            try:
                platform = str(payload.get("platform") or "")
                row = FOLLOWERS.set_manual(platform, payload.get("count"))
                apply_follower_totals(platform, row["count"])
                self.send_json({"ok": True, "counter": row})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/followers/sync":
            platform = str(payload.get("platform") or "")
            if platform not in ("tiktok", "kick", "twitch"):
                self.send_json({"ok": False, "error": "Plataforma no válida"}, 400)
            else:
                result = FOLLOWERS.sync_one(platform, apply_follower_totals)
                self.send_json(result, 200 if result["ok"] else 422)
            return

        if path == "/api/kick/credentials":
            try:
                self.send_json({"ok": True, **KICK.save_credentials(payload.get("clientId"), payload.get("clientSecret"), payload.get("enabled", True))})
            except KickError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/kick/oauth/start":
            try:
                self.send_json({"ok": True, "url": KICK.begin_oauth()})
            except KickError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/kick/subscriptions":
            try:
                self.send_json(KICK.subscribe())
            except KickError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 502)
            return

        if path == "/api/kick/disconnect":
            self.send_json({"ok": True, **KICK.disconnect()})
            return

        if path == "/api/social-stream-config":
            saved = save_social_stream_config(
                payload
            )
            self.send_json({
                "ok": True,
                "sessionId": saved.get("sessionId", ""),
                "password": saved.get("password", "false"),
            })
            return

        if path == "/api/obs/config":
            try:
                cfg = OBS.save_config(payload)
                result = OBS.status(refresh=bool(cfg.enabled))
                result["configured"] = cfg.public()
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/obs/test":
            try:
                OBS.connect(force=True)
                self.send_json(OBS.status(refresh=True))
            except Exception as exc:
                self.send_json({"ok": False, "connected": False, "error": str(exc)}, 502)
            return

        if path == "/api/obs/action":
            try:
                result = execute_automation_action(payload.get("action") or payload, {"username": "Manual", "platform": "brynn"})
                self.send_json({"ok": True, "result": result, "status": OBS.status(refresh=True)})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 502)
            return

        if path == "/api/automations/save":
            try:
                data = AUTOMATION_ENGINE.save(payload) if AUTOMATION_ENGINE else {"automations": []}
                self.send_json({"ok": True, **data})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/automations/delete":
            try:
                aid = str(payload.get("id") or "").strip()
                data = AUTOMATION_ENGINE.delete(aid) if AUTOMATION_ENGINE else {"automations": []}
                self.send_json({"ok": True, **data})
            except KeyError as exc:
                self.send_json({"ok": False, "error": str(exc).strip("\'\"")}, 404)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if path == "/api/automations/test":
            aid = str(payload.get("id") or "")
            if not aid:
                self.send_json({"ok": False, "error": "Falta id"}, 400)
                return
            sample = payload.get("event") if isinstance(payload.get("event"), dict) else {
                "source": "manual", "platform": "twitch", "event": "test",
                "username": "DemoViewer", "message": "Prueba de automatización",
                "quantity": 1, "giftCoins": 1,
            }
            started = automation_dispatch("manual", sample, force_id=aid)
            self.send_json({"ok": bool(started), "started": started, "error": "No se pudo iniciar" if not started else ""}, 200 if started else 404)
            return

        if path == "/api/interaction":
            self.handle_interaction(payload)
            return

        if path == "/api/reset":
            self.handle_reset()
            return

        if path == "/api/economy/earn":
            self.handle_economy_earn(payload)
            return

        if path == "/api/economy/adjust":
            self.handle_economy_adjust(payload)
            return

        if path == "/api/economy-config":
            self.handle_economy_config(payload)
            return

        if path == "/api/economy/redeem-test":
            self.handle_redeem_test(payload)
            return

        if path == "/api/command":
            self.handle_command(payload)
            return

        if path == "/api/test-effect":
            self.handle_test_effect(payload)
            return

        if path == "/api/commands/save":
            self.handle_command_save(payload)
            return

        if path == "/api/commands/delete":
            self.handle_command_delete(payload)
            return

        if path == "/api/commands/test":
            self.handle_command_test(payload)
            return

        if path == "/api/emotes/save":
            self.handle_emote_save(payload)
            return

        if path == "/api/emotes/delete":
            self.handle_emote_delete(payload)
            return

        if path == "/api/emotes/test":
            self.handle_emote_test(payload)
            return

        if path == "/api/weekly-rewards/save":
            saved = save_weekly_rewards_config(payload.get("config") or payload, make_backup=True)
            self.send_json({"ok": True, "config": saved, "active": weekly_public_active()})
            return

        if path == "/api/weekly-rewards/resource-reserve":
            kind = "command" if str(payload.get("kind") or "").lower() == "command" else "emote"
            item_id = re.sub(r"[^a-z0-9_-]", "", str(payload.get("id") or "").lower())
            reserved = bool(payload.get("reserved", False))
            cfg = load_weekly_rewards_config()
            tiers = weekly_item_tiers(kind, item_id, cfg)
            update_weekly_item_assignments(kind, item_id, item_id, tiers, reserved=reserved)
            self.send_json({"ok": True, "config": load_weekly_rewards_config(), "access": weekly_item_access_summary(kind, item_id)})
            return

        if path == "/api/weekly-rewards/apply-current":
            with LOCK:
                ranking_state = archive_and_reset_if_needed(load_current())
                rows = sorted_users(ranking_state)[:10]
                state = apply_weekly_rewards_from_rows(
                    rows,
                    str(ranking_state.get("period") or current_period_key()),
                    grant_bonuses=bool(payload.get("grantBonuses", False)),
                    force=True,
                )
            self.send_json({"ok": True, "state": state, "active": weekly_public_active()})
            return

        if path == "/api/weekly-rewards/clear":
            state = empty_weekly_rewards_state()
            state["winners"] = []
            state["activatedAt"] = now_iso()
            save_weekly_rewards_state(state, make_backup=True)
            self.send_json({"ok": True, "active": weekly_public_active()})
            return

        if path == "/api/weekly-rewards/entrance":
            self.handle_weekly_entrance(payload)
            return

        if path == "/api/goals/save":
            self.send_json({"ok": True, **save_goals(payload)})
            return

        if path == "/api/goals/reset":
            row = reset_goal(str(payload.get("id") or ""))
            self.send_json({"ok": bool(row), "goal": row, "error": "Meta no encontrada" if not row else ""}, 200 if row else 404)
            return

        if path == "/api/goals/adjust":
            gid=str(payload.get("id") or ""); mode=str(payload.get("mode") or "add")
            try: value=float(payload.get("value",0) or 0)
            except Exception: value=0
            goal_row,reached=adjust_goal_value(gid,value,mode,str(payload.get("username") or "Manual"))
            if not goal_row:
                self.send_json({"ok":False,"error":"Meta no encontrada"},404); return
            self.send_json({"ok":True,"goal":goal_row,"reached":reached,"data":goals_public()}); return

        if path == "/api/goals/test":
            gid=str(payload.get("id") or ""); public=goals_public(); goal=next((g for g in public.get("goals",[]) if g.get("id")==gid),None)
            if not goal: self.send_json({"ok":False,"error":"Meta no encontrada"},404); return
            sample=dict(goal); sample["current"]=sample["target"]; sample["remaining"]=0; sample["percent"]=100; sample["lastUser"]="ViewerDemo"
            event=emit_event("goal_reached",{"goal":sample,"render":{"html":goal.get("celebrationHtml",""),"css":goal.get("celebrationCss",""),"js":goal.get("celebrationJs",""),"durationMs":int(goal.get("celebrationDurationMs",6500) or 6500)},"testEvent":True})
            self.send_json({"ok":True,"event":event}); return

        if path == "/api/floating-chat-config/save":
            self.send_json({"ok":True,"config":save_floating_chat_config(payload.get("config") or payload)}); return

        if path == "/api/chat/ingest":
            row=ingest_chat_event(payload.get("data") or payload,str(payload.get("source") or "ssn")); self.send_json({"ok":True,"message":row}); return

        if path == "/api/chat/send":
            message=str(payload.get("message") or "").strip()[:500]
            if not message:
                self.send_json({"ok":False,"error":"Escribe un mensaje"},400); return
            target=str(payload.get("platform") or "ssn").lower()
            if target not in {"kick", "ssn"}:
                self.send_json({"ok": False, "error": "Selecciona destino SSN o Kick"}, 400)
                return
            if target == "kick":
                try:
                    result = KICK.send_chat(message)
                    self.send_json({"ok": True, "sentVia": "kick_official_api", "published": True,
                                    "status": "accepted_by_kick", "detail": "Kick API aceptó el mensaje", "kickResponse": result})
                except KickError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 502)
                return
            ok,detail=_ssn_send_chat(message)
            error="" if ok else detail
            diagnostic = {
                "sessionConfigured": bool(str(load_social_stream_config().get("sessionId") or "").strip()),
                "passwordConfigured": str(load_social_stream_config().get("password") or "false").strip().lower() != "false",
                "remoteApiHint": "Global settings > Mechanics > Enable remote API control of extension",
                "deliveryConfirmed": False,
            }
            if not ok and "session" not in error.lower():
                error=(error+" | Revisa en Social Stream Ninja > Global settings > Mechanics que esté activado 'Enable remote API control of extension'.").strip(" |")
            self.send_json({"ok":ok,"detail":detail,"sentVia":"ssn_post_channel_1","published":False,"status":"accepted_by_ssn" if ok else "transport_error","error":error,"diagnostic":diagnostic},200 if ok else 502); return

        if path == "/api/chat/block":
            username=str(payload.get("username") or "").strip().lstrip("@"); platform=str(payload.get("platform") or "").lower()
            if not username or platform not in {"twitch","tiktok"}: self.send_json({"ok":False,"error":"Usuario/plataforma inválidos"},400); return
            obj=json.dumps({"chatname":username,"type":platform},ensure_ascii=False,separators=(",",":")); ok,detail=_ssn_request("blockUser","null",obj)
            self.send_json({"ok":ok,"detail":detail,"error":"" if ok else detail},200 if ok else 502); return

        if path == "/api/chat/moderate":
            username=str(payload.get("username") or "").strip().lstrip("@"); platform=str(payload.get("platform") or "").lower(); action=str(payload.get("action") or "block")
            try: duration=int(payload.get("duration",600) or 600)
            except Exception: duration=600
            if platform == "kick":
                try:
                    response = KICK.moderate(username,action,duration,str(payload.get("reason") or ""))
                    self.send_json({"ok":True,"detail":"Kick API aceptó la moderación","result":response})
                except KickError as exc:
                    self.send_json({"ok":False,"error":str(exc)},502)
                return
            if platform != "twitch":
                self.send_json({"ok":False,"error":"El ban/timeout nativo está disponible para Twitch y Kick. Para TikTok usa Bloquear en SSN/Brynn."},400); return
            ok,detail=twitch_moderate(username,action,duration,str(payload.get("reason") or "")); self.send_json({"ok":ok,"detail":detail,"error":"" if ok else detail},200 if ok else 502); return

        if path == "/api/twitch-control/save":
            cfg=save_twitch_control_private(payload.get("config") or payload); self.send_json({"ok":True,**twitch_control_public()}); return

        if path == "/api/alert":
            self.handle_stream_alert(payload)
            return

        if path == "/api/alerts/save":
            self.handle_alert_save(payload)
            return

        if path == "/api/alerts/test":
            self.handle_alert_test(payload)
            return

        if path == "/api/chat-design/save":
            self.handle_chat_design_save(payload)
            return

        if path == "/api/layout-studio/save":
            self.send_json({"ok": True, "layout": save_layout_studio(payload.get("layout") or payload)})
            return

        if path == "/api/debug-event":
            self.handle_debug_event(payload)
            return

        if path == "/api/integrations/save":
            self.handle_integrations_save(payload)
            return

        if path == "/api/integrations/streamlabs-token/save":
            self.handle_streamlabs_token_save(payload)
            return

        if path == "/api/integrations/streamlabs-token/clear":
            self.handle_streamlabs_token_clear(payload)
            return

        if path == "/api/integrations/test":
            self.handle_integrations_test(payload)
            return

        if path == "/api/integrations/streamlabs-event":
            self.handle_streamlabs_bridge_event(payload)
            return

        if path == "/api/integrations/streamlabs-status":
            self.handle_streamlabs_bridge_status(payload)
            return

        self.send_json(
            {
                "ok": False,
                "error": "Ruta no encontrada"
            },
            404
        )

    # ---------------- Ranking ----------------

    def handle_interaction(self, payload: dict):
        user = payload.get("user") or {}
        key = str(user.get("key") or "").strip()
        username = str(user.get("username") or "").strip()
        platform = str(user.get("platform") or "").strip().lower()

        try:
            delta = float(payload.get("delta", 0))
        except Exception:
            delta = 0.0

        counters = payload.get("counters") or {}

        if not key or not username or not platform:
            self.send_json(
                {
                    "ok": False,
                    "error": "Faltan key, username o platform"
                },
                400
            )
            return

        if is_test_user_key(key):
            self.send_json({"ok": True, "ignored": True, "reason": "owner"})
            return

        delta = max(0.0, min(delta, 100000.0))

        with LOCK:
            state = archive_and_reset_if_needed(
                load_current()
            )

            users = state.setdefault("users", {})

            entry = users.setdefault(
                key,
                {
                    "key": key,
                    "username": username,
                    "platform": platform,
                    "score": 0.0,
                    "counters": {
                        "messages": 0,
                        "likes": 0,
                        "gifts": 0,
                        "giftCoins": 0,
                        "donationUsd": 0.0,
                        "follows": 0,
                        "joins": 0,
                        "subscriptions": 0,
                    },
                    "lastInteraction": None,
                }
            )

            entry["username"] = username
            entry["platform"] = platform

            if user.get("avatar"):
                entry["avatar"] = str(
                    user.get("avatar")
                )

            entry["score"] = round(
                float(
                    entry.get("score", 0)
                ) + delta,
                2
            )

            saved = entry.setdefault(
                "counters",
                {}
            )

            integer_fields = [
                "messages",
                "likes",
                "gifts",
                "giftCoins",
                "follows",
                "joins",
                "subscriptions",
            ]

            for field in integer_fields:
                try:
                    value = int(
                        counters.get(field, 0)
                    )
                except Exception:
                    value = 0

                saved[field] = (
                    int(
                        saved.get(field, 0)
                    )
                    + max(0, value)
                )

            try:
                usd = float(
                    counters.get(
                        "donationUsd",
                        0
                    )
                )
            except Exception:
                usd = 0.0

            saved["donationUsd"] = round(
                float(
                    saved.get(
                        "donationUsd",
                        0
                    )
                )
                + max(0.0, usd),
                2
            )

            entry["lastInteraction"] = now_iso()

            save_current(
                state,
                make_backup=True
            )

            response = public_state(state)

        response["ok"] = True

        # Mensajes se cuentan como meta desde el ranking; los demás eventos
        # entran por Alertas/TikFinity para evitar duplicados.
        try:
            message_count = max(0, int(counters.get("messages", 0) or 0))
            if message_count:
                update_goals_signal(platform, "messages", message_count, username)
        except Exception:
            pass

        self.send_json(response)

    def handle_reset(self):
        with LOCK:
            state = archive_and_reset_if_needed(
                load_current()
            )

            if state.get("users"):
                archived_path = archive_week(
                    state,
                    manual=True
                )

                print(
                    "Reinicio manual archivado: "
                    f"{archived_path.name}"
                )

                try:
                    reward_cfg = load_weekly_rewards_config()
                    if reward_cfg.get("awardOnManualReset", False):
                        archived_payload = json.loads(archived_path.read_text(encoding="utf-8"))
                        apply_weekly_rewards_from_archive(
                            archived_payload,
                            grant_bonuses=True,
                            force=True,
                        )
                except Exception as exc:
                    print(f"Recompensas por reinicio manual: {exc}")

            new_state = empty_state(
                current_period_key()
            )

            save_current(
                new_state,
                make_backup=True
            )

            response = public_state(
                new_state
            )

            response["ok"] = True

        self.send_json(response)

    # ---------------- Recompensas semanales ----------------

    def handle_weekly_entrance(self, payload: dict):
        user = payload.get("user") or {}
        key = str(user.get("key") or "").strip()
        if not key:
            self.send_json({"ok": False, "error": "Falta user.key"}, 400)
            return

        cfg = load_weekly_rewards_config()
        state = load_weekly_rewards_state()
        test_tier = str(payload.get("testTier") or "").lower()
        winner = weekly_winner_for_key(key, state)
        if is_test_user_key(key) and cfg.get("ownerBypassEnabled", True) and test_tier in WEEKLY_TIER_ORDER:
            profile = load_owner_test_users().get(key, {"key": key, "username": user.get("username") or "Owner", "platform": user.get("platform") or "twitch"})
            tier_defaults = cfg.get("tiers", {}).get(test_tier, {})
            winner = {
                "key": key, "username": profile.get("username"), "platform": profile.get("platform"), "avatar": user.get("avatar", ""),
                "rank": int(tier_defaults.get("minRank", 1) or 1), "score": 99999, "tier": test_tier, "sourcePeriod": "PRUEBA OWNER",
            }
        if not winner:
            self.send_json({"ok": True, "eligible": False})
            return

        tier = cfg.get("tiers", {}).get(winner.get("tier"), {})
        if not tier.get("entryEnabled", True):
            self.send_json({"ok": True, "eligible": True, "shown": False, "reason": "disabled"})
            return

        cooldown_hours = max(0.0, float(tier.get("entryCooldownHours", 12) or 0))
        last_map = state.setdefault("lastEntrances", {})
        last_value = str(last_map.get(key) or "")
        if last_value and cooldown_hours > 0:
            try:
                last_dt = datetime.fromisoformat(last_value)
                if datetime.now().astimezone() - last_dt < timedelta(hours=cooldown_hours):
                    self.send_json({"ok": True, "eligible": True, "shown": False, "reason": "cooldown"})
                    return
            except Exception:
                pass

        if not test_tier:
            last_map[key] = now_iso()
            save_weekly_rewards_state(state, make_backup=True)

        public_user = {
            "key": winner.get("key"),
            "username": winner.get("username"),
            "platform": winner.get("platform"),
            "avatar": winner.get("avatar", ""),
        }
        reward = dict(winner)
        reward["title"] = tier.get("title", winner.get("title", ""))
        reward["badgeLabel"] = tier.get("badgeLabel", winner.get("badgeLabel", ""))
        reward["badgeIcon"] = tier.get("badgeIcon", winner.get("badgeIcon", "✦"))
        reward["badgeHtml"] = tier.get("badgeHtml", winner.get("badgeHtml", ""))
        reward["badgeCss"] = tier.get("badgeCss", winner.get("badgeCss", ""))
        reward["accent"] = tier.get("accent", winner.get("accent", "#53E6FF"))

        event = emit_event(
            "weekly_entrance",
            {
                "user": public_user,
                "reward": reward,
                "render": {
                    "html": tier.get("entryHtml", ""),
                    "css": tier.get("entryCss", ""),
                    "js": tier.get("entryJs", ""),
                    "durationMs": int(tier.get("entryDurationMs", 5200) or 5200),
                },
            },
        )
        self.send_json({"ok": True, "eligible": True, "shown": True, "event": event})

    # ---------------- Economía ----------------

    def handle_economy_earn(self, payload: dict):
        user = payload.get("user") or {}
        kind = str(payload.get("kind") or "").strip().lower()

        try:
            quantity = int(payload.get("quantity", 1))
        except Exception:
            quantity = 1

        try:
            gift_coins = int(payload.get("giftCoins", 0))
        except Exception:
            gift_coins = 0

        try:
            donation_usd = float(payload.get("donationUsd", 0))
        except Exception:
            donation_usd = 0.0

        if kind not in {
            "message",
            "like",
            "follow",
            "join",
            "subscription",
            "gift",
        }:
            self.send_json(
                {
                    "ok": False,
                    "error": "Tipo de interacción desconocido"
                },
                400
            )
            return

        with LOCK:
            state = load_economy()

            try:
                amount, entry = award_gumpitas(
                    state,
                    user,
                    kind,
                    quantity,
                    gift_coins,
                    donation_usd,
                )
            except ValueError as exc:
                self.send_json(
                    {
                        "ok": False,
                        "error": str(exc)
                    },
                    400
                )
                return

            save_economy(
                state,
                make_backup=True
            )

            response = {
                "ok": True,
                "awarded": amount,
                "wallet": {
                    "key": entry.get("key"),
                    "username": entry.get("username"),
                    "platform": entry.get("platform"),
                    "balance": entry.get("balance", 0),
                    "earned": entry.get("earned", 0),
                    "spent": entry.get("spent", 0),
                },
            }

        self.send_json(response)

    def handle_economy_adjust(self, payload: dict):
        key = str(payload.get("key") or "").strip()

        try:
            delta = int(payload.get("delta", 0))
        except Exception:
            delta = 0

        delta = max(-100000, min(100000, delta))

        if not key or delta == 0:
            self.send_json(
                {
                    "ok": False,
                    "error": "Faltan key o delta"
                },
                400
            )
            return

        with LOCK:
            state = load_economy()
            entry = state.get("users", {}).get(key)

            if not entry:
                self.send_json(
                    {
                        "ok": False,
                        "error": "Usuario no encontrado"
                    },
                    404
                )
                return

            if is_test_user_key(key):
                response = public_economy(state)
                response["ok"] = True
                response["note"] = (
                    "Cuenta de pruebas: saldo infinito; "
                    "no necesita ajustes."
                )
                self.send_json(response)
                return

            current = int(entry.get("balance", 0))
            new_balance = max(0, current + delta)
            real_delta = new_balance - current

            entry["balance"] = new_balance

            if real_delta > 0:
                entry["earned"] = int(
                    entry.get("earned", 0)
                ) + real_delta
            elif real_delta < 0:
                entry["spent"] = int(
                    entry.get("spent", 0)
                ) + abs(real_delta)

            add_transaction(
                state,
                entry,
                real_delta,
                "ajuste_manual"
            )

            save_economy(
                state,
                make_backup=True
            )

            response = public_economy(state)
            response["ok"] = True

        self.send_json(response)

    def handle_economy_config(self, payload: dict):
        rates = save_economy_rates(payload.get("rates") or payload)
        branding = save_economy_branding(payload.get("branding") or load_economy_branding())
        self.send_json({"ok": True, "rates": rates, "branding": branding})

    def handle_redeem_test(self, payload: dict):
        branding = load_economy_branding()
        currency = currency_public()
        cost = max(1, int(payload.get("cost") or 75))
        before = int(payload.get("balanceBefore") or 500)
        event = emit_event(
            "redeem_preview",
            {
                "user": {"key": "test:viewer", "username": str(payload.get("username") or "ViewerDemo"), "platform": str(payload.get("platform") or "twitch"), "avatar": ""},
                "item": {"id": "demo", "name": str(payload.get("reward") or "Canje de prueba"), "cost": cost, "baseCost": cost, "showCard": False},
                "balanceBefore": before,
                "balance": max(0, before-cost),
                "currency": currency,
                "presentation": branding.get("redeemPresentation", {}),
                "testUser": True,
                "ownerOverride": True,
            },
        )
        self.send_json({"ok": True, "event": event})

    # ---------------- Pruebas / editor de comandos ----------------

    def handle_upload(self, parsed):
        query = parse_qs(parsed.query)
        kind = str(query.get("kind", ["visual"])[0]).lower()
        original = str(query.get("filename", ["archivo.bin"])[0])
        ext = Path(original).suffix.lower()

        allowed = {
            "visual": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"},
            "badge": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
            "audio": {".mp3", ".wav", ".ogg", ".m4a", ".aac"},
        }
        if kind not in allowed or ext not in allowed[kind]:
            self.send_json({"ok": False, "error": "Formato no permitido"}, 400)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0
        if length <= 0 or length > 100 * 1024 * 1024:
            self.send_json({"ok": False, "error": "Archivo vacío o mayor a 100 MB"}, 400)
            return

        ensure_storage()
        stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(original).stem)[:36] or "media"
        filename = f"{stem}_{int(time.time()*1000)}_{secrets.token_hex(4)}{ext}"
        target = USER_MEDIA_DIR / filename
        temp_path = USER_MEDIA_DIR / f".{filename}.upload"
        try:
            remaining = length
            with temp_path.open("wb") as output:
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("El archivo llegó incompleto")
                    output.write(block)
                    remaining -= len(block)
            os.replace(temp_path, target)
        except (OSError, ValueError) as exc:
            temp_path.unlink(missing_ok=True)
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return
        visual_type = ""
        if kind in {"visual", "badge"}:
            visual_type = "video" if ext in {".mp4", ".webm"} else ("gif" if ext == ".gif" else "image")
        self.send_json({
            "ok": True,
            "url": f"/user_media/{filename}",
            "filename": filename,
            "kind": kind,
            "visualType": visual_type,
        })

    def handle_command_save(self, payload: dict):
        raw_item = payload.get("command") or payload
        original_id = re.sub(r"[^a-z0-9_-]", "", str(payload.get("originalId") or "").lower())
        try:
            item = normalize_command_item(raw_item)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        with LOCK:
            items = load_commands()
            # Si se cambia el ID mientras se edita, actualizar el recurso actual
            # en vez de crear una copia.
            if original_id and original_id != item["id"] and any(x.get("id") == item["id"] for x in items):
                self.send_json({"ok": False, "error": f"Ya existe !{item['id']}. Elige otro ID."}, 409)
                return
            target_id = original_id or item["id"]
            replaced = False
            for index, current in enumerate(items):
                if current.get("id") == target_id:
                    items[index] = item
                    replaced = True
                    break
            if not replaced:
                items.append(item)
            save_commands_payload({"commands": items}, make_backup=True)
            if target_id != item["id"]:
                replace_weekly_resource_id("command", target_id, item["id"])
        self.send_json({
            "ok": True, "command": item, "commands": load_commands(),
            "weeklyAccess": weekly_item_access_summary("command", item["id"]),
        })

    def handle_command_delete(self, payload: dict):
        command_id = re.sub(r"[^a-z0-9_-]", "", str(payload.get("id") or "").lower())
        if not command_id:
            self.send_json({"ok": False, "error": "ID inválido"}, 400)
            return
        with LOCK:
            items = [x for x in load_commands() if x.get("id") != command_id]
            save_commands_payload({"commands": items}, make_backup=True)
            remove_weekly_resource_id("command", command_id)
        self.send_json({"ok": True, "commands": items})

    def handle_command_test(self, payload: dict):
        item = find_store_item(str(payload.get("id") or ""))
        if not item:
            self.send_json({"ok": False, "error": "Comando no encontrado"}, 404)
            return
        user_public = {
            "key": "twitch:demo_viewer",
            "username": "DemoViewer",
            "platform": "twitch",
            "avatar": "",
        }
        event = emit_event("redeem", {
            "user": user_public,
            "item": command_event_item(item, test_cost=True),
            "balance": "∞",
            "testUser": True,
            "testEvent": True,
        })
        self.send_json({"ok": True, "event": event})

    def handle_test_effect(self, payload: dict):
        requested = str(payload.get("effect") or "").strip().lower()
        item = find_store_item(requested)
        if not item:
            # Buscar también por el nombre interno de efecto.
            for candidate in load_commands():
                if str(candidate.get("effect") or "").lower() == requested:
                    item = candidate
                    break
        if not item:
            self.send_json({"ok": False, "error": "Efecto de prueba desconocido"}, 400)
            return
        user_public = {
            "key": "twitch:demo_viewer",
            "username": "DemoViewer",
            "platform": "twitch",
            "avatar": "",
        }
        event = emit_event("redeem", {
            "user": user_public,
            "item": command_event_item(item, test_cost=True),
            "balance": "∞",
            "testUser": True,
            "testEvent": True,
        })
        self.send_json({"ok": True, "event": event})

    # ---------------- Emotes ----------------

    def handle_emote_save(self, payload: dict):
        original_id = re.sub(r"[^a-z0-9_-]", "", str(payload.get("originalId") or "").lower())
        try:
            item = normalize_emote_item(payload.get("emote") or payload)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        if not item.get("visualUrl"):
            self.send_json({"ok": False, "error": "Sube una imagen o GIF para el emote"}, 400)
            return

        with LOCK:
            items = load_emotes()
            if original_id and original_id != item["id"] and any(x.get("id") == item["id"] for x in items):
                self.send_json({"ok": False, "error": f"Ya existe el emote '{item['id']}'. Elige otro ID."}, 409)
                return
            target_id = original_id or item["id"]
            replaced = False
            for index, current in enumerate(items):
                if current.get("id") == target_id:
                    items[index] = item
                    replaced = True
                    break
            if not replaced:
                items.append(item)
            save_emotes_payload({"emotes": items}, make_backup=True)

            # Mantener secuencias y recompensas apuntando al mismo emote aunque
            # cambie su ID visible.
            if target_id != item["id"]:
                replace_emote_id_in_commands(target_id, item["id"])
                replace_weekly_resource_id("emote", target_id, item["id"])

        self.send_json({
            "ok": True, "emote": item, "emotes": load_emotes(),
            "weeklyAccess": weekly_item_access_summary("emote", item["id"]),
        })

    def handle_emote_delete(self, payload: dict):
        emote_id = re.sub(
            r"[^a-z0-9_-]",
            "",
            str(payload.get("id") or "").lower()
        )

        if not emote_id:
            self.send_json(
                {"ok": False, "error": "ID inválido"},
                400
            )
            return

        with LOCK:
            items = [
                x
                for x in load_emotes()
                if x.get("id") != emote_id
            ]
            save_emotes_payload(
                {"emotes": items},
                make_backup=True
            )
            remove_weekly_resource_id("emote", emote_id)

        self.send_json(
            {
                "ok": True,
                "emotes": items
            }
        )

    def handle_emote_test(self, payload: dict):
        item = find_emote(
            str(payload.get("id") or "")
        )

        if not item:
            self.send_json(
                {
                    "ok": False,
                    "error": "Emote no encontrado"
                },
                404
            )
            return

        event = emit_event(
            "emote_redeem",
            {
                "user": {
                    "key": "twitch:demo_viewer",
                    "username": "DemoViewer",
                    "platform": "twitch",
                    "avatar": "",
                },
                "emote": {
                    **item,
                    "cost": 0,
                },
                "balance": "∞",
                "testUser": True,
                "testEvent": True,
            }
        )

        self.send_json(
            {"ok": True, "event": event}
        )

    # ---------------- Alertas de stream ----------------

    def handle_stream_alert(self, payload: dict):
        platform = str(
            payload.get("platform") or ""
        ).lower()

        alert_type = str(
            payload.get("type") or ""
        ).lower()

        username = str(
            payload.get("username") or "Usuario"
        )

        avatar = str(
            payload.get("avatar") or ""
        )

        amount = str(
            payload.get("amount") or ""
        )

        # Cuenta follows de SSN aun si se desactiva la alerta visual.
        if alert_type == "follow" and not payload.get("testEvent") and not payload.get("testOnly"):
            register_follow_for_goals(platform, username, str(payload.get("eventId") or ""))

        key = f"{platform}:{alert_type}"
        config = load_alerts().get(key)

        if not config or not config.get("enabled", True):
            self.send_json(
                {
                    "ok": True,
                    "ignored": True
                }
            )
            return

        rendered = dict(config)
        rendered["title"] = fill_alert_template(
            config.get("titleTemplate", ""),
            username,
            platform,
            amount
        )
        rendered["message"] = fill_alert_template(
            config.get("messageTemplate", ""),
            username,
            platform,
            amount
        )

        event = emit_event(
            "stream_alert",
            {
                "user": {
                    "username": username,
                    "platform": platform,
                    "avatar": avatar,
                },
                "alert": rendered,
                "amount": amount,
            }
        )

        # V0.44: las alertas SSN alimentan las metas cuando no existe
        # una integración directa propietaria del evento.
        try:
            number_match = re.search(r"[-+]?\d+(?:[.,]\d+)?", amount.replace(",", ""))
            numeric = float(number_match.group(0)) if number_match else 1.0
            mapping = {"follow":"followers","subscription":"subscriptions","like":"likes","gift":"gifts","raid":"raids","donation":"donationsUsd","share":"shares","join":"joins","bits":"bits"}
            goal_kind = mapping.get(alert_type)
            if goal_kind and goal_kind != "followers":
                update_goals_signal(platform, goal_kind, numeric if goal_kind in {"likes","raids","donationsUsd"} else 1, username)
        except Exception:
            pass

        self.send_json(
            {"ok": True, "event": event}
        )

    def handle_alert_save(self, payload: dict):
        try:
            item = save_one_alert(
                payload.get("alert") or payload
            )
        except Exception as exc:
            self.send_json(
                {"ok": False, "error": str(exc)},
                400
            )
            return

        self.send_json(
            {
                "ok": True,
                "alert": item,
                "alerts": list(
                    load_alerts().values()
                ),
            }
        )

    def handle_alert_test(self, payload: dict):
        platform = str(
            payload.get("platform") or "twitch"
        ).lower()

        alert_type = str(
            payload.get("type") or "follow"
        ).lower()

        key = f"{platform}:{alert_type}"
        config = load_alerts().get(key)

        if not config:
            self.send_json(
                {
                    "ok": False,
                    "error": "Alerta no encontrada"
                },
                404
            )
            return

        sample_amounts = {
            "gift": "Rose x5 · 5 monedas",
            "like": "100 likes",
            "share": "Compartió el LIVE",
            "join": "Entró al LIVE",
            "bits": "100 Bits",
            "raid": "25 viewers",
            "donation": "$5.00",
            "subscription": "1 mes",
        }

        amount = sample_amounts.get(alert_type, "")

        username = (
            "UsuarioDePrueba"
        )

        rendered = dict(config)
        rendered["title"] = fill_alert_template(
            config.get("titleTemplate", ""),
            username,
            platform,
            amount
        )
        rendered["message"] = fill_alert_template(
            config.get("messageTemplate", ""),
            username,
            platform,
            amount
        )

        event = emit_event(
            "stream_alert",
            {
                "user": {
                    "username": username,
                    "platform": platform,
                    "avatar": "",
                },
                "alert": rendered,
                "amount": amount,
                "testEvent": True,
            }
        )

        self.send_json(
            {"ok": True, "event": event}
        )

    # ---------------- Diseño del chat ----------------

    def handle_chat_design_save(self, payload: dict):
        design = save_chat_design(
            payload.get("design") or payload
        )

        self.send_json(
            {"ok": True, "design": design}
        )

    # ---------------- Integraciones ----------------

    def handle_integrations_save(self, payload: dict):
        with INTEGRATION_CONFIG_LOCK:
            current = load_integrations_config()

            streamlabs = current.get(
                "streamlabs",
                {}
            )

            tikfinity = current.get(
                "tikfinity",
                {}
            )

            token = ""

            if "streamlabsEnabled" in payload:
                requested_enabled = bool(
                    payload.get(
                        "streamlabsEnabled"
                    )
                )

                streamlabs["enabled"] = (
                    requested_enabled
                )

                save_streamlabs_global(
                    enabled=requested_enabled
                )

            # Compatibilidad con clientes viejos:
            # si mandan un token por la ruta genérica, migrarlo al almacén global.
            legacy_token = str(
                payload.get(
                    "streamlabsSocketToken",
                    ""
                )
                or ""
            ).strip()

            if legacy_token:
                token = legacy_token
                save_streamlabs_global(
                    token=legacy_token,
                    enabled=bool(
                        streamlabs.get(
                            "enabled",
                            True
                        )
                    )
                )

            if payload.get(
                "clearStreamlabsToken"
            ):
                save_streamlabs_global(
                    token="",
                    enabled=False
                )
                streamlabs["enabled"] = False

            if "tikfinityEnabled" in payload:
                tikfinity["enabled"] = bool(
                    payload.get(
                        "tikfinityEnabled"
                    )
                )

            if "tikfinityMode" in payload:
                mode = str(
                    payload.get(
                        "tikfinityMode"
                    )
                ).lower()

                if mode in {
                    "webhook",
                    "desktop",
                }:
                    tikfinity["mode"] = mode

            if "tikfinityPublicBaseUrl" in payload:
                tikfinity["publicBaseUrl"] = str(
                    payload.get(
                        "tikfinityPublicBaseUrl"
                    )
                    or ""
                ).strip().rstrip("/")

            if payload.get(
                "regenerateTikfinitySecret"
            ):
                tikfinity["webhookSecret"] = (
                    secrets.token_urlsafe(24)
                )

            config = save_integrations_config(
                {
                    "streamlabs": streamlabs,
                    "tikfinity": tikfinity,
                },
                make_backup=True
            )

        if (
            not config.get("streamlabs", {}).get("enabled", False)
            or payload.get("clearStreamlabsToken")
            or token
        ):
            with STREAMLABS_BRIDGES_LOCK:
                STREAMLABS_BRIDGES.clear()

        recompute_streamlabs_bridge_status()

        self.send_json(
            {
                "ok": True,
                **integrations_public_state()
            }
        )

    def handle_streamlabs_token_save(self, payload: dict):
        token = str(
            payload.get("socketToken")
            or ""
        ).strip()

        if not token:
            self.send_json(
                {
                    "ok": False,
                    "error": "El Socket API Token está vacío."
                },
                400
            )
            return

        enabled = bool(
            payload.get(
                "enabled",
                True
            )
        )

        try:
            saved = save_streamlabs_global(
                token=token,
                enabled=enabled
            )

            saved_token = str(
                saved.get(
                    "socketToken",
                    ""
                )
                or ""
            ).strip()

            saved_enabled = bool(
                saved.get(
                    "enabled",
                    False
                )
            )

            if saved_token != token:
                raise RuntimeError(
                    "La verificación del token persistente no coincide."
                )

            # Mantener enabled reflejado en integrations.json para compatibilidad,
            # pero sin guardar el token ahí.
            with INTEGRATION_CONFIG_LOCK:
                current = load_integrations_config()

                current.setdefault(
                    "streamlabs",
                    {}
                )

                current["streamlabs"][
                    "enabled"
                ] = saved_enabled

                current["streamlabs"][
                    "socketToken"
                ] = ""

                save_integrations_config(
                    current,
                    make_backup=True
                )

            with STREAMLABS_BRIDGES_LOCK:
                STREAMLABS_BRIDGES.clear()

            recompute_streamlabs_bridge_status()

            self.send_json(
                {
                    "ok": True,
                    "saved": True,
                    "enabled": saved_enabled,
                    "tokenPresent": True,
                    "tokenMasked": (
                        "••••••••"
                        + saved_token[-4:]
                    ),
                    "tokenLength": len(
                        saved_token
                    ),
                    "storageFile": str(
                        STREAMLABS_GLOBAL_FILE
                    ),
                    "storageScope": (
                        "global_appdata"
                    ),
                    **integrations_public_state()
                }
            )

        except Exception as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": (
                        "No se pudo guardar el token persistente: "
                        + str(exc)
                    )
                },
                500
            )

    def handle_streamlabs_token_clear(self, payload: dict):
        try:
            save_streamlabs_global(
                token="",
                enabled=False
            )

            with INTEGRATION_CONFIG_LOCK:
                current = load_integrations_config()

                current.setdefault(
                    "streamlabs",
                    {}
                )

                current["streamlabs"][
                    "enabled"
                ] = False

                current["streamlabs"][
                    "socketToken"
                ] = ""

                save_integrations_config(
                    current,
                    make_backup=True
                )

            with STREAMLABS_BRIDGES_LOCK:
                STREAMLABS_BRIDGES.clear()

            recompute_streamlabs_bridge_status()

            self.send_json(
                {
                    "ok": True,
                    "saved": True,
                    **integrations_public_state()
                }
            )

        except Exception as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": (
                        "No se pudo borrar el token persistente: "
                        + str(exc)
                    )
                },
                500
            )

    def handle_integrations_test(self, payload: dict):
        service = str(
            payload.get(
                "service",
                ""
            )
        ).lower()

        event_type = str(
            payload.get(
                "type",
                ""
            )
        ).lower()

        if service not in {
            "streamlabs",
            "tikfinity",
            "kick",
        }:
            self.send_json(
                {
                    "ok": False,
                    "error": "Servicio inválido"
                },
                400
            )
            return

        if service == "streamlabs":
            platform = "twitch"
            username = "PruebaStreamlabs"

            if event_type == "follow":
                amount = ""
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "subscription":
                amount = "1 mes"
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "donation":
                amount = "$5.00"
                gift_coins = 0
                donation_usd = 5.0
            elif event_type == "bits":
                amount = "100 Bits"
                gift_coins = 0
                donation_usd = 1.0
            elif event_type == "raid":
                amount = "25 viewers"
                gift_coins = 0
                donation_usd = 0.0
            else:
                self.send_json(
                    {
                        "ok": False,
                        "error": "Tipo de prueba inválido"
                    },
                    400
                )
                return

        elif service == "kick":
            platform = "kick"
            username = "PruebaKick"
            gift_coins = 0
            donation_usd = 0.0
            if event_type == "follow": amount = ""
            elif event_type == "subscription": amount = "1 mes"
            elif event_type == "gift":
                amount = "KICKs · 100 KICKs"
                gift_coins = 100
            elif event_type == "reward": amount = "Recompensa de prueba"
            else:
                self.send_json({"ok": False, "error": "Tipo de prueba Kick inválido"}, 400)
                return

        else:
            platform = "tiktok"
            username = "PruebaTikTok"

            if event_type == "follow":
                amount = ""
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "subscription":
                amount = "1 mes"
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "gift":
                amount = "Rose x5 · 5 monedas"
                gift_coins = 5
                donation_usd = 0.0
            elif event_type == "like":
                amount = "100 likes"
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "share":
                amount = "Compartió el LIVE"
                gift_coins = 0
                donation_usd = 0.0
            elif event_type == "join":
                amount = "Entró al LIVE"
                gift_coins = 0
                donation_usd = 0.0
            else:
                self.send_json(
                    {
                        "ok": False,
                        "error": "Tipo de prueba inválido"
                    },
                    400
                )
                return

        handle_direct_platform_event(
            service,
            platform,
            event_type,
            username,
            amount_text=amount,
            raw={
                "test": True,
                "service": service,
                "type": event_type,
            },
            unique_id=(
                f"test-{service}-"
                f"{event_type}-"
                f"{time.time_ns()}"
            ),
            gift_coins=gift_coins,
            donation_usd=donation_usd,
            test_only=True,
        )

        self.send_json(
            {
                "ok": True,
                "message": "Evento de prueba enviado"
            }
        )

    def handle_streamlabs_bridge_status(self, payload: dict):
        bridge_id = str(
            payload.get("bridgeId") or "legacy"
        )

        state = str(
            payload.get("state") or "unknown"
        )[:40]

        connected = bool(
            payload.get("connected", False)
        )

        error = str(
            payload.get("error") or ""
        )[:500]

        streamlabs_bridge_status_update(
            bridge_id,
            state,
            connected,
            error,
        )

        if connected:
            update_integration_status(
                "streamlabs",
                lastConnectedAt=now_iso(),
            )

        self.send_json(
            {"ok": True}
        )

    def handle_streamlabs_bridge_event(self, payload: dict):
        event_data = payload.get("event")

        if not isinstance(event_data, dict):
            self.send_json(
                {
                    "ok": False,
                    "error": "Falta event"
                },
                400
            )
            return

        record_debug_event(
            "streamlabs",
            event_data
        )

        process_streamlabs_event(
            event_data
        )

        self.send_json(
            {"ok": True}
        )

    # ---------------- Monitor de eventos ----------------

    def handle_debug_event(self, payload: dict):
        source = str(payload.get("source") or "unknown")
        raw = payload.get("payload")

        if not isinstance(raw, dict):
            self.send_json({"ok": False, "error": "payload debe ser un objeto"}, 400)
            return

        row = record_debug_event(source, raw)
        self.send_json({"ok": True, "event": row})

    # ---------------- Comandos ----------------

    def handle_command(self, payload: dict):
        user = payload.get("user") or {}
        command_text = str(payload.get("command") or "").strip()
        # Fast duplicate requests happen when SSN P2P and channel 4 deliver
        # the same chat message. Only block a repeated identical user/command.
        user_key = str(user.get("key") or (str(user.get("platform", "")) + ":" + str(user.get("username", "")))).lower()
        command_fingerprint = (user_key, command_text.casefold())
        moment = time.monotonic()
        with COMMAND_DEDUPE_LOCK:
            for old_key, timestamp in list(COMMAND_DEDUPE.items()):
                if moment - timestamp > 1.5:
                    COMMAND_DEDUPE.pop(old_key, None)
            if command_fingerprint in COMMAND_DEDUPE:
                self.send_json({"ok": True, "duplicate": True, "message": "Comando duplicado ignorado"})
                return
            COMMAND_DEDUPE[command_fingerprint] = moment

        name, args = parse_command(command_text)

        if not name:
            self.send_json(
                {
                    "ok": False,
                    "error": "Comando inválido"
                },
                400
            )
            return

        with LOCK:
            economy = load_economy()

            try:
                wallet = ensure_wallet(
                    economy,
                    user
                )
            except ValueError as exc:
                self.send_json(
                    {
                        "ok": False,
                        "error": str(exc)
                    },
                    400
                )
                return

            save_economy(
                economy,
                make_backup=True
            )

            user_public = {
                "key": wallet.get("key"),
                "username": wallet.get("username"),
                "platform": wallet.get("platform"),
                "avatar": wallet.get("avatar", ""),
            }

            # Recompensa de emote:
            # !emote nombre
            if name == "emote":
                requested = " ".join(args).strip()

                if not requested:
                    available = [
                        x.get("id")
                        for x in load_emotes()
                        if x.get("enabled", True)
                        and weekly_access_for_item(wallet.get("key", ""), "emote", x.get("id", "")).get("allowed")
                    ]

                    message = (
                        "Usa !emote <nombre>. "
                        + (
                            "Disponibles: "
                            + ", ".join(available[:12])
                            if available
                            else "Aún no hay emotes configurados."
                        )
                    )

                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message": message,
                        }
                    )

                    self.send_json(
                        {"ok": True, "event": event}
                    )
                    return

                emote = find_emote(requested)

                if not emote:
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message":
                                f"No encontré el emote '{requested}'."
                        }
                    )
                    self.send_json(
                        {"ok": True, "event": event}
                    )
                    return

                is_test = is_test_user_key(
                    wallet.get("key", "")
                )

                access = weekly_access_for_item(
                    wallet.get("key", ""),
                    "emote",
                    emote.get("id", ""),
                )
                if not access.get("allowed"):
                    tiers = ", ".join(str(x).upper() for x in access.get("tiers", [])) or "sin rango asignado"
                    reason = access.get("reason")
                    if reason == "unassigned":
                        message = f"{emote['name']} es exclusivo semanal, pero todavía no tiene un rango asignado."
                    elif reason == "no_active_reward":
                        message = f"{emote['name']} es exclusivo semanal y no hay una recompensa vigente para tu cuenta."
                    else:
                        message = f"{emote['name']} es un emote semanal exclusivo ({tiers})."
                    event = emit_event("error", {"user": user_public, "message": message})
                    self.send_json({"ok": True, "event": event})
                    return

                balance = int(
                    wallet.get("balance", 0)
                )

                base_cost = int(emote.get("cost", 0))
                weekly_discount = weekly_discount_for_user(wallet.get("key", ""))
                cost = weekly_discounted_cost(base_cost, weekly_discount)

                if (not is_test) and balance < cost:
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message":
                                f"Te faltan {cost - balance} {currency_name(cost - balance)} para usar {emote['name']}.",
                            "balance": balance,
                        }
                    )
                    self.send_json(
                        {"ok": True, "event": event}
                    )
                    return

                if not is_test:
                    wallet["balance"] = balance - cost
                    wallet["spent"] = int(
                        wallet.get("spent", 0)
                    ) + cost
                    wallet["lastInteraction"] = now_iso()

                    add_transaction(
                        economy,
                        wallet,
                        -cost,
                        f"emote_{emote['id']}"
                    )

                    save_economy(
                        economy,
                        make_backup=True
                    )

                branding = load_economy_branding()
                event = emit_event(
                    "emote_redeem",
                    {
                        "user": user_public,
                        "emote": {**emote, "cost": cost, "baseCost": base_cost, "weeklyDiscountPct": weekly_discount},
                        "balanceBefore": ("∞" if is_test else balance),
                        "balance": (
                            "∞"
                            if is_test
                            else int(
                                wallet.get("balance", 0)
                            )
                        ),
                        "testUser": is_test,
                        "ownerOverride": bool(is_test),
                        "currency": currency_public(),
                        "presentation": branding.get("redeemPresentation", {}),
                    }
                )

                self.send_json(
                    {"ok": True, "event": event}
                )
                return

            # Permite comandos directos de tienda:
            # !glitch, !niebla, !murcielagos, !calabazas, !bonk, !susto
            # Internamente se convierten al mismo flujo de canje.
            direct_item = find_store_item(name)

            if direct_item and not args:
                name = "canjear"
                args = [direct_item["id"]]

            if name in {
                "diario",
                "daily",
                "bonodiario",
            }:
                is_test = is_test_user_key(
                    wallet.get("key", "")
                )

                if is_test:
                    event = emit_event(
                        "daily_bonus",
                        {
                            "user": user_public,
                            "amount": "∞",
                            "balance": "∞",
                            "testUser": True,
                            "currency": currency_public(),
                        }
                    )

                    self.send_json(
                        {"ok": True, "event": event}
                    )
                    return

                today = datetime.now().astimezone().date().isoformat()

                if wallet.get("lastDailyClaimDate") == today:
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message":
                                "Ya reclamaste tu bono diario de hoy. Vuelve mañana."
                        }
                    )

                    self.send_json(
                        {"ok": True, "event": event}
                    )
                    return

                amount = int(
                    ECONOMY_RATES.get(
                        "dailyBonus",
                        35
                    )
                )

                wallet["lastDailyClaimDate"] = today
                wallet["balance"] = int(
                    wallet.get("balance", 0)
                ) + amount
                wallet["earned"] = int(
                    wallet.get("earned", 0)
                ) + amount

                counters = wallet.setdefault(
                    "counters",
                    {}
                )

                counters["dailyBonuses"] = int(
                    counters.get("dailyBonuses", 0)
                ) + 1

                add_transaction(
                    economy,
                    wallet,
                    amount,
                    "daily_claim"
                )

                save_economy(
                    economy,
                    make_backup=True
                )

                event = emit_event(
                    "daily_bonus",
                    {
                        "user": user_public,
                        "amount": amount,
                        "balance": int(
                            wallet.get("balance", 0)
                        ),
                        "currency": currency_public(),
                    }
                )

                self.send_json(
                    {"ok": True, "event": event}
                )
                return

            balance_aliases = {"gumpitas", "puntos", "saldo", "coins", str(load_economy_branding().get("balanceCommand") or "gumpitas").lower()}
            if name in balance_aliases:
                is_test = is_test_user_key(
                    wallet.get("key", "")
                )

                event = emit_event(
                    "balance",
                    {
                        "user": user_public,
                        "balance": (
                            "∞"
                            if is_test
                            else int(
                                wallet.get("balance", 0)
                            )
                        ),
                        "testUser": is_test,
                        "currency": currency_public(),
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            if name in {
                "tienda",
                "shop",
            }:
                is_test = is_test_user_key(
                    wallet.get("key", "")
                )

                event = emit_event(
                    "store",
                    {
                        "user": user_public,
                        "balance": (
                            "∞"
                            if is_test
                            else int(
                                wallet.get("balance", 0)
                            )
                        ),
                        "testUser": is_test,
                        "items": store_public_for_user(wallet.get("key", "")),
                        "currency": currency_public(),
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            if name in {
                "topgumpitas",
                "topcoins",
            }:
                rows = sorted_wallets(
                    economy,
                    include_test=False
                )[:3]

                event = emit_event(
                    "top_wallets",
                    {
                        "user": user_public,
                        "top": rows,
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            if name in {
                "ayuda",
                "comandos",
                "help",
            }:
                event = emit_event(
                    "help",
                    {
                        "user": user_public,
                        "commands": (["!" + str(load_economy_branding().get("balanceCommand") or "gumpitas"), "!diario", "!tienda"] + ["!" + x["id"] for x in store_public_for_user(wallet.get("key", ""))] + ["!topgumpitas", "!ranking"]),
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            if name == "ranking":
                ranking = public_state(
                    archive_and_reset_if_needed(
                        load_current()
                    )
                )

                event = emit_event(
                    "weekly_ranking",
                    {
                        "user": user_public,
                        "top": ranking.get(
                            "top",
                            []
                        )[:3],
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            if name in {
                "canjear",
                "redeem",
            }:
                raw_item = " ".join(args)

                if not raw_item:
                    event = emit_event(
                        "store",
                        {
                            "user": user_public,
                            "balance": (
                                "∞"
                                if is_test_user_key(
                                    wallet.get("key", "")
                                )
                                else int(
                                    wallet.get(
                                        "balance",
                                        0
                                    )
                                )
                            ),
                            "testUser": is_test_user_key(
                                wallet.get("key", "")
                            ),
                            "items": store_public_for_user(wallet.get("key", "")),
                            "currency": currency_public(),
                            "message":
                                "Usa directamente !glitch, !niebla, !bonk, etc."
                        }
                    )

                    self.send_json(
                        {
                            "ok": True,
                            "event": event
                        }
                    )
                    return

                item = find_store_item(
                    raw_item
                )

                if not item:
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message":
                                f"No encontré '{raw_item}' en la tienda."
                        }
                    )

                    self.send_json(
                        {
                            "ok": True,
                            "event": event
                        }
                    )
                    return

                access = weekly_access_for_item(
                    wallet.get("key", ""),
                    "command",
                    item.get("id", ""),
                )
                if not access.get("allowed"):
                    tiers = ", ".join(str(x).upper() for x in access.get("tiers", []))
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message": f"!{item['id']} es un comando semanal exclusivo ({tiers}).",
                        },
                    )
                    self.send_json({"ok": True, "event": event})
                    return

                balance = int(
                    wallet.get(
                        "balance",
                        0
                    )
                )

                base_cost = int(item["cost"])
                weekly_discount = weekly_discount_for_user(wallet.get("key", ""))
                cost = weekly_discounted_cost(base_cost, weekly_discount)

                is_test = is_test_user_key(
                    wallet.get("key", "")
                )

                if (not is_test) and balance < cost:
                    event = emit_event(
                        "error",
                        {
                            "user": user_public,
                            "message":
                                f"Te faltan {cost - balance} {currency_name(cost - balance)} para {item['name']}.",
                            "balance": balance,
                        }
                    )

                    self.send_json(
                        {
                            "ok": True,
                            "event": event
                        }
                    )
                    return

                if not is_test:
                    wallet["balance"] = balance - cost
                    wallet["spent"] = int(
                        wallet.get(
                            "spent",
                            0
                        )
                    ) + cost
                    wallet["lastInteraction"] = now_iso()

                    add_transaction(
                        economy,
                        wallet,
                        -cost,
                        f"canje_{item['id']}"
                    )

                    save_economy(
                        economy,
                        make_backup=True
                    )

                branding = load_economy_branding()
                event = emit_event(
                    "redeem",
                    {
                        "user": user_public,
                        "item": {**command_event_item(item), "cost": cost, "baseCost": base_cost, "weeklyDiscountPct": weekly_discount},
                        "balanceBefore": ("∞" if is_test else balance),
                        "balance": (
                            "∞"
                            if is_test
                            else int(
                                wallet.get(
                                    "balance",
                                    0
                                )
                            )
                        ),
                        "testUser": is_test,
                        "ownerOverride": bool(is_test),
                        "currency": currency_public(),
                        "presentation": branding.get("redeemPresentation", {}),
                    }
                )

                self.send_json(
                    {
                        "ok": True,
                        "event": event
                    }
                )
                return

            event = emit_event(
                "error",
                {
                    "user": user_public,
                    "message":
                        f"Comando desconocido: !{name}. Usa !ayuda."
                }
            )

            self.send_json(
                {
                    "ok": True,
                    "event": event
                }
            )

    def log_message(self, fmt, *args):
        print(
            "[%s] %s"
            % (
                self.log_date_time_string(),
                fmt % args
            )
        )


_MAIN_HTTP_SERVER = None
_RUNTIME_INITIALIZED = False


def initialize_runtime() -> None:
    global _RUNTIME_INITIALIZED

    if _RUNTIME_INITIALIZED:
        return

    ensure_storage()
    global AUTOMATION_ENGINE
    if AUTOMATION_ENGINE is None:
        AUTOMATION_ENGINE = AutomationEngine(AUTOMATIONS_FILE, execute_automation_action)
    migrate_legacy_if_needed()
    load_economy_rates()
    load_economy_branding()
    load_social_stream_config()

    with LOCK:
        archive_and_reset_if_needed(
            load_current()
        )
        load_economy()
        load_commands()

    load_integrations_config()
    global_streamlabs = load_streamlabs_global()

    if global_streamlabs.get("enabled", False):
        update_integration_status(
            "streamlabs",
            state="waiting_bridge",
            connected=False,
            lastError=(
                "Añade streamlabs_bridge.html?v=47&obs=1 "
                "como fuente persistente en OBS."
            ),
        )

    start_integration_workers()
    start_tikfinity_webhook_server()
    threading.Thread(target=FOLLOWERS.run_loop, args=(apply_follower_totals,),
                     name="Brynn-Followers-Sync", daemon=True).start()
    _RUNTIME_INITIALIZED = True


def run_server_forever() -> None:
    global _MAIN_HTTP_SERVER

    initialize_runtime()

    handler = partial(
        AppHandler,
        directory=str(ROOT)
    )

    _MAIN_HTTP_SERVER = ThreadingHTTPServer(
        (HOST, PORT),
        handler
    )

    print()
    print("============================================================")
    print(" BRYNN INTERACTIVE DESKTOP - Backend V0.60.12 · ESTABILIDAD Y SEGURIDAD")
    print("============================================================")
    print(f" Panel       : http://{HOST}:{PORT}/integraciones.html")
    print(f" Chat OBS    : http://{HOST}:{PORT}/index.html?v=47")
    print(f" Alertas OBS : http://{HOST}:{PORT}/alerts_overlay.html?v=47")
    print(f" Eventos OBS : http://{HOST}:{PORT}/events_overlay.html?v=51")
    print(f" Top semanal : http://{HOST}:{PORT}/top3_overlay.html?v=47")
    print(f" Metas OBS   : http://{HOST}:{PORT}/goals_overlay.html?v=47&id=GOAL_ID")
    print(f" TikFinity   : http://{WEBHOOK_HOST}:{WEBHOOK_PORT}/health")
    print(f" Datos       : {DATA_DIR}")
    print(f" Media       : {USER_MEDIA_DIR}")
    print("============================================================")
    print()

    try:
        _MAIN_HTTP_SERVER.serve_forever()
    finally:
        try:
            _MAIN_HTTP_SERVER.server_close()
        except Exception:
            pass
        _MAIN_HTTP_SERVER = None


def shutdown_server() -> None:
    server = _MAIN_HTTP_SERVER
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        run_server_forever()
    except KeyboardInterrupt:
        shutdown_server()
