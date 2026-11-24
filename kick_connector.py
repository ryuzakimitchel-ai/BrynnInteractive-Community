"""Integración Kick oficial para Brynn Interactive.

OAuth 2.1 (PKCE), API REST y webhooks firmados RSA SHA-256.
Todos los secretos viven exclusivamente bajo AppData, no en ROOT/data.
Se mantiene separado de las integraciones existentes de Twitch y TikTok.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AUTH_URL = "https://id.kick.com/oauth/authorize"
TOKEN_URL = "https://id.kick.com/oauth/token"
API_ROOT = "https://api.kick.com/public/v1"
SCOPES = "user:read channel:read chat:write events:subscribe channel:rewards:read moderation:ban"
EVENTS = (
    "chat.message.sent",
    "channel.followed",
    "channel.subscription.new",
    "channel.subscription.renewal",
    "channel.subscription.gifts",
    "kicks.gifted",
    "channel.reward.redemption.updated",
    "livestream.status.updated",
)
REDIRECT_URL = "http://localhost:8765/api/kick/oauth/callback"


class KickError(Exception):
    pass


def http_json(url: str, token: str = "", method: str = "GET", payload=None, form=False):
    headers = {"Accept": "application/json", "User-Agent": "BrynnInteractive-Kick/0.1"}
    data = None
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(512000)
            if not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except (ValueError, UnicodeError):
                # Kick public key endpoint can return PEM rather than JSON.
                return raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise KickError(f"Kick HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise KickError(f"No se pudo conectar a Kick: {exc.reason}") from exc


def _first_row(value):
    if isinstance(value, dict):
        rows = value.get("data", value)
        if isinstance(rows, list):
            return rows[0] if rows else {}
        if isinstance(rows, dict):
            return rows
        return value
    return {}


def _identity_from_user(value):
    row = _first_row(value)
    if not isinstance(row, dict):
        row = {}
    return {"username": str(row.get("name") or row.get("username") or ""),
            "userId": str(row.get("user_id") or row.get("id") or "")}


def _safe_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class KickConnector:
    def __init__(self, private_file: Path):
        self.path = Path(private_file)
        self.lock = threading.RLock()
        self.pending = None
        self.key_cache = None
        self.key_until = 0.0
        self.last_event = None
        self.last_error = ""
        self.last_delivery = None
        self.recent_ids = {}
        # IDs aprendidos solamente de webhooks firmados, jamás de chat no autenticado.
        self.chat_users = {}
        self.viewers = None
        self.viewers_until = 0.0

    def load(self):
        try:
            cfg = json.loads(self.path.read_text(encoding="utf-8"))
            return cfg if isinstance(cfg, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_credentials(self, client_id: str, client_secret: str, enabled: bool = True):
        with self.lock:
            old = self.load()
            old["clientId"] = str(client_id or old.get("clientId") or "").strip()
            old["clientSecret"] = str(client_secret or old.get("clientSecret") or "").strip()
            old["enabled"] = bool(enabled)
            if not old["clientId"] or not old["clientSecret"]:
                raise KickError("Necesitas Client ID y Client Secret de Kick Developer.")
            _safe_write(self.path, old)
        return self.public()

    def disconnect(self):
        # La desconexión local no revoca el token ni elimina las suscripciones
        # del servidor de Kick: el usuario debe poder ver esto claramente.
        with self.lock:
            cfg = self.load()
            for key in ("accessToken", "refreshToken", "expiresAt", "userId", "username"):
                cfg.pop(key, None)
            _safe_write(self.path, cfg)
            self.pending = None
        return self.public()

    def public(self):
        cfg = self.load()
        return {"enabled": bool(cfg.get("enabled", False)),
                "clientConfigured": bool(cfg.get("clientId") and cfg.get("clientSecret")),
                "connected": bool(cfg.get("accessToken") and cfg.get("refreshToken")),
                "username": cfg.get("username") or "",
                "userId": cfg.get("userId") or "",
                "redirectUrl": REDIRECT_URL,
                "webhookPath": "/kick/webhook",
                "lastEvent": self.last_event,
                "lastError": self.last_error,
                "lastDeliveryAt": self.last_delivery,
                "viewers": self.viewers}

    def begin_oauth(self):
        cfg = self.load()
        if not cfg.get("clientId") or not cfg.get("clientSecret"):
            raise KickError("Configura primero las credenciales de Kick Developer.")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        with self.lock:
            self.pending = {"state": state, "verifier": verifier, "expires": time.time() + 600}
        params = {"response_type": "code", "client_id": cfg["clientId"],
                  "redirect_uri": REDIRECT_URL, "scope": SCOPES,
                  "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
        return AUTH_URL + "?" + urllib.parse.urlencode(params)

    def finish_oauth(self, code, state):
        with self.lock:
            pending = self.pending
            if not pending or time.time() > pending["expires"] or not secrets.compare_digest(str(state), pending["state"]):
                raise KickError("Estado OAuth inválido o caducado. Reinicia la conexión desde Brynn.")
            # Consumir sólo después de validar state: callbacks ajenos no pueden invalidar el flujo legítimo.
            self.pending = None
        cfg = self.load()
        token = http_json(TOKEN_URL, method="POST", form=True, payload={
            "grant_type": "authorization_code", "client_id": cfg["clientId"],
            "client_secret": cfg["clientSecret"], "redirect_uri": REDIRECT_URL,
            "code_verifier": pending["verifier"], "code": str(code),
        })
        if not isinstance(token, dict) or not token.get("access_token"):
            raise KickError("Kick no entregó un access_token válido.")
        account = _identity_from_user(http_json(API_ROOT + "/users", token=token["access_token"]))
        if not account["userId"]:
            raise KickError("Kick no entregó el user_id de la cuenta. No se guardaron los tokens.")
        with self.lock:
            cfg.update({"accessToken": token["access_token"],
                        "refreshToken": token.get("refresh_token") or "",
                        "expiresAt": time.time() + max(60, int(token.get("expires_in") or 3600)),
                        "userId": account["userId"], "username": account["username"], "enabled": True})
            _safe_write(self.path, cfg)
        return self.public()

    def token(self):
        with self.lock:
            cfg = self.load()
            if not cfg.get("enabled") or not cfg.get("accessToken"):
                raise KickError("Conecta primero tu cuenta de Kick.")
            if time.time() < float(cfg.get("expiresAt") or 0) - 90:
                return cfg["accessToken"]
            if not cfg.get("refreshToken"):
                raise KickError("Token Kick caducado y sin refresh_token. Reconecta la cuenta.")
            refreshed = http_json(TOKEN_URL, method="POST", form=True, payload={
                "grant_type": "refresh_token", "client_id": cfg["clientId"],
                "client_secret": cfg["clientSecret"], "refresh_token": cfg["refreshToken"]})
            if not isinstance(refreshed, dict) or not refreshed.get("access_token"):
                raise KickError("Kick no renovó el token: reconecta la cuenta.")
            cfg["accessToken"] = refreshed["access_token"]
            cfg["refreshToken"] = refreshed.get("refresh_token") or cfg["refreshToken"]
            cfg["expiresAt"] = time.time() + max(60, int(refreshed.get("expires_in") or 3600))
            _safe_write(self.path, cfg)
            return cfg["accessToken"]

    def api(self, path, payload=None, method="GET"):
        return http_json(API_ROOT + path, token=self.token(), method=method, payload=payload)

    def send_chat(self, message):
        message = str(message or "").strip()
        if not message or len(message) > 500:
            raise KickError("El mensaje debe tener de 1 a 500 caracteres.")
        cfg = self.load()
        if not str(cfg.get("userId") or "").isdigit():
            raise KickError("Kick no tiene broadcaster_user_id válido.")
        response = self.api("/chat", method="POST", payload={
            "type": "user", "content": message,
            "broadcaster_user_id": int(cfg["userId"]),
        })
        return {"acceptedByKick": True, "result": response}

    def register_chat_user(self, username, user_id):
        username = str(username or '').strip().lower()
        if username and str(user_id or '').isdigit():
            with self.lock:
                self.chat_users[username] = (int(user_id), time.time())
                if len(self.chat_users) > 5000:
                    self.chat_users = {u: v for u, v in self.chat_users.items() if time.time() - v[1] < 3600}

    def moderate(self, username, action, duration=600, reason=''):
        name = str(username or '').strip().lower().lstrip('@')
        if action not in {'ban', 'timeout'}:
            raise KickError('Acción de moderación Kick no admitida.')
        with self.lock:
            match = self.chat_users.get(name)
        if not match or time.time() - match[1] > 43200:
            raise KickError('No se encontró el ID de este usuario en el chat Kick reciente. Debe escribir un mensaje en el chat primero.')
        cfg = self.load()
        if not str(cfg.get('userId') or '').isdigit():
            raise KickError('Conecta primero Kick con una cuenta autorizada.')
        request = {'broadcaster_user_id': int(cfg['userId']), 'user_id': int(match[0]),
                   'reason': str(reason or 'Moderación desde Brynn')[:240]}
        if action == 'timeout':
            request['duration'] = max(1, min(604800, int(duration or 600)))
        return self.api('/moderation/bans', method='POST', payload=request)

    def subscriptions(self):
        return self.api("/events/subscriptions")

    def subscribe(self):
        cfg = self.load()
        if not str(cfg.get("userId") or "").isdigit():
            raise KickError("Primero autoriza Kick con OAuth.")
        known = self.subscriptions()
        rows = known.get("data", []) if isinstance(known, dict) else []
        if isinstance(rows, dict):
            rows = rows.get("subscriptions", [])
        existing = {(str(x.get("event") or x.get("name") or x.get("event_name")), int(x.get("version") or 1))
                    for x in rows if isinstance(x, dict)} if isinstance(rows, list) else set()
        missing = [name for name in EVENTS if (name, 1) not in existing]
        if not missing:
            return {"ok": True, "message": "Ya estaban suscritos los eventos", "events": list(EVENTS)}
        result = self.api("/events/subscriptions", method="POST", payload={
            "broadcaster_user_id": int(cfg["userId"]),
            "events": [{"name": name, "version": 1} for name in missing],
            "method": "webhook",
        })
        return {"ok": True, "requested": missing, "result": result}

    def get_viewers(self):
        if time.time() < self.viewers_until:
            return self.viewers
        cfg = self.load()
        if not cfg.get("accessToken") or not cfg.get("userId"):
            with self.lock:
                self.viewers = None
                self.viewers_until = time.time() + 15
            return None
        with self.lock:
            if time.time() < self.viewers_until:
                return self.viewers
            try:
                data = self.api("/users/livestreams?" + urllib.parse.urlencode({"broadcaster_user_id": cfg["userId"]}))
                rows = data.get("data", []) if isinstance(data, dict) else []
                if isinstance(rows, dict):
                    rows = rows.get("livestreams", [])
                item = next((x for x in rows if isinstance(x, dict) and str(x.get("broadcaster_user_id")) == str(cfg["userId"])), None) if isinstance(rows, list) else None
                if item is None and isinstance(rows, list) and len(rows) == 1:
                    item = rows[0]
                self.viewers = int(item["viewer_count"]) if item and item.get("viewer_count") is not None else None
                self.last_error = ""
            except (KickError, ValueError, KeyError) as exc:
                self.last_error = str(exc)[:200]
                self.viewers = None
            self.viewers_until = time.time() + 15
            return self.viewers

    def _public_key(self, force=False):
        with self.lock:
            if self.key_cache and self.key_until > time.time() and not force:
                return self.key_cache
            data = http_json(API_ROOT + "/public-key")
            if isinstance(data, dict):
                data = data.get("data", data)
                if isinstance(data, dict):
                    data = data.get("public_key") or data.get("publicKey") or data.get("key")
            if not isinstance(data, str) or "BEGIN PUBLIC KEY" not in data:
                raise KickError("Kick no entregó una clave pública PEM válida.")
            self.key_cache = data.encode("utf-8")
            self.key_until = time.time() + 3600
            return self.key_cache

    def verify_webhook(self, headers, raw: bytes):
        # Fail-closed: if the key cannot be downloaded or crypto missing,
        # NO webhook is accepted.
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.exceptions import InvalidSignature
        except ImportError as exc:
            raise KickError("Falta cryptography para validar las firmas de Kick.") from exc
        mid = str(headers.get("Kick-Event-Message-Id") or "")
        stamp = str(headers.get("Kick-Event-Message-Timestamp") or "")
        sig = str(headers.get("Kick-Event-Signature") or "")
        if not (mid and stamp and sig) or len(raw) > 256000:
            raise KickError("Faltan encabezados firmados de Kick.")
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is None or abs(datetime.now(timezone.utc).timestamp() - dt.timestamp()) > 600:
                raise ValueError("timestamp fuera de rango")
            signed = mid.encode("utf-8") + b"." + stamp.encode("utf-8") + b"." + raw
            signature = base64.b64decode(sig, validate=True)
        except (ValueError, UnicodeError) as exc:
            raise KickError("Fecha o firma Kick inválida/caducada.") from exc
        for retry in (False, True):
            try:
                key = serialization.load_pem_public_key(self._public_key(force=retry))
                key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
                break
            except InvalidSignature:
                if retry:
                    raise KickError("Firma Kick inválida.")
            except (ValueError, TypeError) as exc:
                raise KickError("Clave pública Kick inválida.") from exc
        return mid

    def is_processed(self, message_id):
        with self.lock:
            now = time.time()
            self.recent_ids = {k: v for k, v in self.recent_ids.items() if now - v < 1200}
            return message_id in self.recent_ids

    def mark_processed(self, message_id):
        with self.lock:
            now = time.time()
            self.recent_ids = {k: v for k, v in self.recent_ids.items() if now - v < 1200}
            if message_id in self.recent_ids:
                return False
            self.recent_ids[message_id] = now
            return True

    def unmark_processed(self, message_id):
        """Release a claimed webhook ID when processing failed before completion."""
        with self.lock:
            self.recent_ids.pop(message_id, None)
