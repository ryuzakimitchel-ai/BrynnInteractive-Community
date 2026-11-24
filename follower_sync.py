"""Follower counters for Brynn: persistent event estimates and optional official API reconciliation.

No scraping and no credentials in the served data/ directory.  The official Kick
API does not currently publish an authoritative follower total, so its counter is
explicitly marked as an estimate unless a manually configured external JSON
source reports one (which is NOT called official/verified).
"""
from __future__ import annotations

import json
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


PLATFORMS = ('tiktok', 'kick', 'twitch')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def nonnegative_int(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and not value.is_integer():
            return None
        if isinstance(value, str) and not value.strip().isdigit():
            return None
        n = int(value)
        if n < 0 or n > 2_000_000_000:
            return None
        return n
    except (ValueError, TypeError, OverflowError):
        return None


def read_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text('utf-8'))
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as handle:
            tmp = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class FollowerCounters:
    def __init__(self, data_dir: Path, private_dir: Path,
                 twitch_config: Callable[[], dict] | None = None):
        self.state_path = Path(data_dir) / 'followers_state.json'
        self.private_path = Path(private_dir) / 'followers_private.json'
        self.lock = threading.RLock()
        self.twitch_config = twitch_config or (lambda: {})
        self.dedupe = {}
        self.state = read_json(self.state_path, {})
        self.state.setdefault('platforms', {})
        for name in PLATFORMS:
            self.state['platforms'].setdefault(name, {'count': None, 'source': 'none',
                                                      'confirmed': False, 'updatedAt': None,
                                                      'checkedAt': None, 'lastError': ''})
        self.config = read_json(self.private_path, {})
        self.config.setdefault('intervalSeconds', 180)
        self.config.setdefault('tiktok', {})
        self.config.setdefault('kick', {})

    def _persist(self):
        write_json(self.state_path, self.state)

    def _save_private(self):
        write_json(self.private_path, self.config)
        # Restrict on POSIX; on Windows the data remains in the user's AppData profile.
        try:
            self.private_path.chmod(0o600)
        except OSError:
            pass

    def public(self) -> dict:
        with self.lock:
            rows = {p: dict(self.state['platforms'][p]) for p in PLATFORMS}
            now = time.time()
            interval = int(self.config.get('intervalSeconds', 180))
            for platform, row in rows.items():
                row['fresh'] = bool(row.get('confirmed') and row.get('confirmedAtEpoch') and
                                    now - float(row['confirmedAtEpoch']) < max(interval * 3, 600))
                row.pop('confirmedAtEpoch', None)
                row['estimated'] = row.get('count') is not None and not row['fresh']
            tc = self.config.get('tiktok', {})
            kc = self.config.get('kick', {})
            return {'ok': True, 'platforms': rows, 'intervalSeconds': interval,
                    'settings': {'tiktok': {'tokenPresent': bool(tc.get('accessToken')),
                                            'refreshPresent': bool(tc.get('refreshToken')),
                                            'clientKeyPresent': bool(tc.get('clientKey')),
                                            'clientSecretPresent': bool(tc.get('clientSecret'))},
                                 'kick': {'externalUrl': kc.get('externalUrl', '')}}}

    def configure(self, payload: dict):
        with self.lock:
            if 'intervalSeconds' in payload:
                try:
                    self.config['intervalSeconds'] = max(60, min(3600, int(payload['intervalSeconds'])))
                except (TypeError, ValueError):
                    raise ValueError('El intervalo debe ser un número de segundos')
            if isinstance(payload.get('tiktok'), dict):
                target = self.config.setdefault('tiktok', {})
                for key in ('accessToken', 'refreshToken', 'clientKey', 'clientSecret'):
                    value = str(payload['tiktok'].get(key) or '').strip()
                    if value:
                        target[key] = value[:4096]
                if payload['tiktok'].get('clearCredentials'):
                    for key in ('accessToken', 'refreshToken', 'clientKey', 'clientSecret'):
                        target.pop(key, None)
            if isinstance(payload.get('kick'), dict):
                target = self.config.setdefault('kick', {})
                if 'externalUrl' in payload['kick']:
                    url = str(payload['kick'].get('externalUrl') or '').strip()
                    if url:
                        parsed = urllib.parse.urlsplit(url)
                        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                            raise ValueError('La fuente externa de Kick requiere una URL HTTPS válida')
                    target['externalUrl'] = url[:2048]
            self._save_private()
            return self.public()

    def set_manual(self, platform: str, count: object) -> dict:
        if platform not in PLATFORMS:
            raise ValueError('Plataforma no permitida')
        value = nonnegative_int(count)
        if value is None:
            raise ValueError('El total debe ser un número entero no negativo')
        with self.lock:
            row = self.state['platforms'][platform]
            row.update({'count': value, 'source': 'manual', 'confirmed': False,
                        'confirmedAtEpoch': None, 'updatedAt': stamp(), 'checkedAt': None,
                        'lastError': ''})
            self._persist()
        return dict(row)

    def add_follow(self, platform: str, username: str, event_key: str = '') -> bool:
        """Returns True only for the first delivery of a follow across event transports."""
        if platform not in PLATFORMS:
            return False
        username = str(username or '').strip().lower().lstrip('@')
        event_key = str(event_key or '').strip()
        if not username or username in ('usuario', 'usuario tiktok', 'anónimo', 'anonimo') and not event_key:
            return False
        now = time.monotonic()
        with self.lock:
            if len(self.dedupe) > 1200:
                self.dedupe = {k:v for k,v in self.dedupe.items() if now-v < 120}
            user_key = f'{platform}:user:{username}'
            id_key = f'{platform}:event:{event_key}' if event_key else None
            if (user_key in self.dedupe and now-self.dedupe[user_key] < 90 or
                id_key and id_key in self.dedupe and now-self.dedupe[id_key] < 1800):
                return False
            self.dedupe[user_key] = now
            if id_key:
                self.dedupe[id_key] = now
            row = self.state['platforms'][platform]
            row['newFollows'] = int(row.get('newFollows', 0)) + 1
            if row.get('count') is not None:
                row['count'] = int(row['count']) + 1
                row['source'] = 'event_estimate'
                row['confirmed'] = False
                row['confirmedAtEpoch'] = None
            row['updatedAt'] = stamp()
            self._persist()
            return True

    def _fetch_json(self, url: str, headers: dict, post: dict | None = None) -> dict:
        body = urllib.parse.urlencode(post).encode('utf-8') if post else None
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method='POST' if post else 'GET')
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                raise ValueError(f'HTTP {resp.status}')
            raw = resp.read(65536)
        result = json.loads(raw.decode('utf-8'))
        if not isinstance(result, dict):
            raise ValueError('Respuesta de estadísticas no válida')
        return result

    def _tiktok_total(self) -> int:
        with self.lock:
            cfg = dict(self.config.get('tiktok', {}))
        token = cfg.get('accessToken', '')
        if not token:
            raise ValueError('Configura un token de TikTok autorizado para user.info.stats')
        def request(t):
            d = self._fetch_json('https://open.tiktokapis.com/v2/user/info/?fields=follower_count',
                                 {'Authorization': f'Bearer {t}', 'Accept':'application/json',
                                  'User-Agent':'BrynnInteractive-FollowerSync/1.0'})
            if d.get('error', {}).get('code') not in (None, '', 'ok'):
                raise ValueError(str(d['error'].get('message') or 'TikTok rechazó el token'))
            value = nonnegative_int((d.get('data', {}).get('user') or {}).get('follower_count'))
            if value is None:
                raise ValueError('TikTok no devolvió follower_count (comprueba user.info.stats)')
            return value
        try:
            return request(token)
        except urllib.error.HTTPError as exc:
            if exc.code != 401 or not all(cfg.get(k) for k in ('refreshToken','clientKey','clientSecret')):
                raise
            response = self._fetch_json('https://open.tiktokapis.com/v2/oauth/token/',
                {'Content-Type':'application/x-www-form-urlencoded', 'User-Agent':'BrynnInteractive-FollowerSync/1.0'},
                {'client_key':cfg['clientKey'], 'client_secret':cfg['clientSecret'],
                 'grant_type':'refresh_token','refresh_token':cfg['refreshToken']})
            new_token = response.get('access_token')
            if not new_token:
                raise ValueError('TikTok no renovó el access token')
            with self.lock:
                target = self.config.setdefault('tiktok', {})
                target['accessToken'] = str(new_token)
                if response.get('refresh_token'):
                    target['refreshToken'] = str(response['refresh_token'])
                self._save_private()
            return request(str(new_token))

    def _twitch_total(self) -> int:
        cfg = self.twitch_config()
        bid = str(cfg.get('broadcasterId') or '')
        token = str(cfg.get('accessToken') or '')
        client = str(cfg.get('clientId') or '')
        if not (cfg.get('enabled') and bid and token and client):
            raise ValueError('Configura Twitch Control con un token autorizado')
        result = self._fetch_json('https://api.twitch.tv/helix/channels/followers?broadcaster_id='+
                                  urllib.parse.quote(bid, safe='')+'&first=1',
                                  {'Authorization':'Bearer '+token,'Client-Id':client,
                                   'User-Agent':'BrynnInteractive-FollowerSync/1.0'})
        total = nonnegative_int(result.get('total'))
        if total is None:
            raise ValueError('Twitch no devolvió el total (requiere moderator:read:followers)')
        return total

    def _kick_total(self) -> int:
        with self.lock:
            url = str(self.config.get('kick', {}).get('externalUrl') or '').strip()
        if not url:
            raise ValueError('Kick no ofrece el total en la API pública. Usa un valor inicial o una fuente externa HTTPS.')
        # User-controlled opt-in: external source must return JSON {"followers_count":123}.
        result = self._fetch_json(url, {'Accept':'application/json',
                                        'User-Agent':'BrynnInteractive-FollowerSync/1.0'})
        total = nonnegative_int(result.get('followers_count'))
        if total is None:
            raise ValueError('La fuente externa de Kick debe devolver JSON con followers_count entero')
        return total

    def sync_one(self, platform: str, on_total: Callable[[str, int], None] | None = None) -> dict:
        if platform not in PLATFORMS:
            raise ValueError('Plataforma no permitida')
        # No blanking or overwriting a valid count when the provider is unavailable.
        try:
            getter = {'tiktok':self._tiktok_total, 'twitch':self._twitch_total, 'kick':self._kick_total}[platform]
            total = getter()
            with self.lock:
                row = self.state['platforms'][platform]
                row.update({'count':total,
                            'source':'official' if platform != 'kick' else 'external',
                            'confirmed':platform != 'kick', 'confirmedAtEpoch':time.time() if platform != 'kick' else None,
                            'checkedAt':stamp(), 'updatedAt':stamp(), 'lastError':''})
                self._persist()
            if on_total:
                on_total(platform, total)
            return {'ok': True, 'platform': platform, 'count': total,
                    'verified':platform != 'kick'}
        except Exception as exc:
            with self.lock:
                row = self.state['platforms'][platform]
                row['checkedAt'] = stamp()
                row['lastError'] = str(exc)[:240]
                self._persist()
            return {'ok': False, 'platform': platform, 'error': str(exc)[:240]}

    def run_loop(self, on_total: Callable[[str, int], None]):
        # First sync and then once per configured interval. No busy-loop on outages.
        while True:
            for platform in PLATFORMS:
                with self.lock:
                    cfg = dict(self.config)
                if platform == 'tiktok' and not cfg.get('tiktok', {}).get('accessToken'):
                    continue
                if platform == 'kick' and not cfg.get('kick', {}).get('externalUrl'):
                    continue
                if platform == 'twitch' and not self.twitch_config().get('enabled'):
                    continue
                self.sync_one(platform, on_total)
            with self.lock:
                interval = int(self.config.get('intervalSeconds', 180))
            time.sleep(max(60, interval))
