from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
import threading
import tempfile
import struct
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


def _load_websocket_client():
    """Load websocket-client from the runtime or Brynn's bundled _vendor copy.

    PyInstaller does not automatically treat folders added as data as importable
    packages.  V0.54 first prefers the installed websocket-client package and
    then adds the bundled _vendor directory explicitly as a resilient fallback.
    """
    errors = []

    def attempt():
        try:
            module = importlib.import_module("websocket")
            if not hasattr(module, "create_connection"):
                raise ImportError(
                    "Se encontró un paquete llamado 'websocket', pero no es websocket-client."
                )
            return module
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            sys.modules.pop("websocket", None)
            return None

    module = attempt()
    if module is not None:
        return module, ""

    here = Path(__file__).resolve().parent
    candidates = [here / "_vendor"]

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "_vendor")

    # PyInstaller onedir commonly places data below _internal.
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "_vendor", exe_dir / "_internal" / "_vendor"])
    except Exception:
        pass

    seen = set()
    for vendor_dir in candidates:
        try:
            key = str(vendor_dir.resolve())
        except Exception:
            key = str(vendor_dir)
        if key in seen or not vendor_dir.exists():
            continue
        seen.add(key)
        if key not in sys.path:
            sys.path.insert(0, key)
        importlib.invalidate_caches()
        module = attempt()
        if module is not None:
            return module, ""

    return None, " | ".join(errors[-4:])


websocket, WEBSOCKET_IMPORT_ERROR = _load_websocket_client()


class ObsError(RuntimeError):
    pass


class ObsRequestError(ObsError):
    """OBS understood the request but rejected it; the socket can stay open."""
    pass


@dataclass
class ObsConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    timeout: float = 2.5

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ObsConfig":
        raw = raw or {}
        try:
            port = int(raw.get("port", 4455))
        except Exception:
            port = 4455
        try:
            timeout = float(raw.get("timeout", 2.5))
        except Exception:
            timeout = 2.5
        return cls(
            enabled=bool(raw.get("enabled", False)),
            host=str(raw.get("host") or "127.0.0.1").strip(),
            port=max(1, min(65535, port)),
            password=str(raw.get("password") or ""),
            timeout=max(0.5, min(10.0, timeout)),
        )

    def public(self) -> dict:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "timeout": self.timeout,
            "passwordConfigured": bool(self.password),
        }


class ObsController:
    """Small OBS WebSocket 5.x client.

    OBS 28+ ships obs-websocket 5.x by default. The controller keeps a single
    connection and reconnects automatically when OBS is restarted.
    """

    def __init__(self, config_file: Path):
        self.config_file = Path(config_file)
        self._lock = threading.RLock()
        self._ws = None
        self._identified = False
        self._last_error = ""
        self._last_connected_at = None
        self._last_ok_at = None

    def load_config(self) -> ObsConfig:
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8")) if self.config_file.exists() else {}
        except Exception:
            raw = {}
        return ObsConfig.from_dict(raw)

    def save_config(self, payload: dict) -> ObsConfig:
        current = self.load_config()
        raw = {
            "enabled": bool(payload.get("enabled", current.enabled)),
            "host": str(payload.get("host", current.host) or current.host).strip(),
            "port": payload.get("port", current.port),
            "password": current.password,
            "timeout": payload.get("timeout", current.timeout),
        }
        # Empty password from the UI means "keep the current secret".
        if "password" in payload and str(payload.get("password") or ""):
            raw["password"] = str(payload.get("password") or "")
        if bool(payload.get("clearPassword", False)):
            raw["password"] = ""
        cfg = ObsConfig.from_dict(raw)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        payload_to_write = {
            "enabled": cfg.enabled,
            "host": cfg.host,
            "port": cfg.port,
            "password": cfg.password,
            "timeout": cfg.timeout,
        }
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_file.parent,
                                             prefix=f".{self.config_file.name}.", suffix=".tmp", delete=False) as handle:
                tmp = Path(handle.name)
                json.dump(payload_to_write, handle, ensure_ascii=False, indent=2)
            tmp.replace(self.config_file)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        self.disconnect()
        return cfg

    def disconnect(self):
        with self._lock:
            ws, self._ws = self._ws, None
            self._identified = False
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _auth_value(self, password: str, salt: str, challenge: str) -> str:
        secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
        return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")

    _OBS_CLOSE_CODES = {
        4000: "OBS cerró la conexión por una razón desconocida.",
        4002: "OBS no pudo decodificar un mensaje WebSocket.",
        4003: "Falta un campo de datos requerido por OBS WebSocket.",
        4004: "OBS recibió un campo con un tipo de dato inválido.",
        4005: "OBS recibió un valor inválido durante la identificación.",
        4006: "OBS recibió un código de operación WebSocket desconocido.",
        4007: "Brynn intentó enviar una solicitud antes de identificarse con OBS.",
        4008: "La conexión ya estaba identificada con OBS.",
        4009: "Autenticación rechazada por OBS. La contraseña guardada en Brynn no coincide con la contraseña de OBS.",
        4010: "La versión RPC solicitada no es compatible con esta versión de OBS WebSocket.",
        4011: "OBS invalidó la sesión WebSocket.",
        4012: "OBS no admite una función solicitada por Brynn.",
    }

    @classmethod
    def _decode_close_frame(cls, payload) -> tuple[int | None, str]:
        if payload is None:
            return None, ""
        if isinstance(payload, str):
            payload = payload.encode("utf-8", errors="replace")
        if not isinstance(payload, (bytes, bytearray)):
            return None, str(payload)
        if len(payload) < 2:
            return None, bytes(payload).decode("utf-8", errors="replace")
        code = struct.unpack("!H", bytes(payload[:2]))[0]
        reason = bytes(payload[2:]).decode("utf-8", errors="replace").strip()
        return code, reason

    def _recv_json(self, stage: str = "respuesta") -> dict:
        # websocket-client's recv() converts CLOSE frames to an empty string.
        # Using recv_data(control_frame=True) preserves the OBS close code/reason,
        # which is crucial for diagnosing bad passwords (close code 4009).
        try:
            opcode, raw = self._ws.recv_data(control_frame=True)
        except AttributeError:
            raw = self._ws.recv()
            opcode = None

        close_opcode = getattr(getattr(websocket, "ABNF", None), "OPCODE_CLOSE", 8) if websocket else 8
        if opcode == close_opcode:
            code, reason = self._decode_close_frame(raw)
            friendly = self._OBS_CLOSE_CODES.get(code, "OBS cerró la conexión WebSocket.")
            suffix = f" Motivo de OBS: {reason}" if reason else ""
            code_text = f" (código {code})" if code is not None else ""
            raise ObsError(f"{friendly}{code_text}{suffix}")

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if raw is None or not str(raw).strip():
            raise ObsError(
                f"OBS cerró la conexión durante {stage} sin enviar datos. "
                "Si la autenticación está habilitada, vuelve a escribir la contraseña exacta de OBS en Brynn y pulsa Guardar."
            )
        try:
            packet = json.loads(raw)
        except json.JSONDecodeError as exc:
            preview = str(raw)[:180].replace("\n", " ")
            raise ObsError(f"OBS devolvió una respuesta no válida durante {stage}: {preview!r}") from exc
        if not isinstance(packet, dict):
            raise ObsError(f"OBS devolvió un paquete inesperado durante {stage}.")
        return packet

    def connect(self, force: bool = False) -> dict:
        with self._lock:
            cfg = self.load_config()
            if websocket is None:
                detail = f" Detalle: {WEBSOCKET_IMPORT_ERROR}" if WEBSOCKET_IMPORT_ERROR else ""
                raise ObsError(
                    "No está disponible websocket-client en esta instalación. "
                    "Ejecuta el instalador V0.54 para reparar la dependencia." + detail
                )
            if not cfg.enabled and not force:
                raise ObsError("La integración con OBS está deshabilitada.")
            if self._ws is not None and self._identified:
                try:
                    return self.request("GetVersion")
                except Exception:
                    self.disconnect()

            url = f"ws://{cfg.host}:{cfg.port}"
            try:
                self._ws = websocket.create_connection(url, timeout=cfg.timeout, enable_multithread=True)
                hello = self._recv_json("el saludo inicial")
                if int(hello.get("op", -1)) != 0:
                    raise ObsError("OBS respondió con un saludo WebSocket no válido.")
                data = hello.get("d") or {}
                identify = {"rpcVersion": int(data.get("rpcVersion") or 1), "eventSubscriptions": 0}
                auth = data.get("authentication") or {}
                if auth:
                    if not cfg.password:
                        raise ObsError("OBS solicita contraseña y Brynn no tiene una configurada.")
                    identify["authentication"] = self._auth_value(
                        cfg.password,
                        str(auth.get("salt") or ""),
                        str(auth.get("challenge") or ""),
                    )
                self._ws.send(json.dumps({"op": 1, "d": identify}))
                identified = self._recv_json("la autenticación/identificación")
                if int(identified.get("op", -1)) != 2:
                    raise ObsError("OBS rechazó la identificación. Revisa host, puerto y contraseña.")
                self._identified = True
                self._last_connected_at = time.time()
                self._last_error = ""
                return data
            except Exception as exc:
                self.disconnect()
                self._last_error = str(exc)
                if isinstance(exc, ObsError):
                    raise
                raise ObsError(f"No se pudo conectar con OBS ({url}): {exc}") from exc

    def request(self, request_type: str, request_data: dict | None = None) -> dict:
        with self._lock:
            if self._ws is None or not self._identified:
                self.connect()
            rid = uuid.uuid4().hex
            packet = {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": rid,
                    "requestData": request_data or {},
                },
            }
            try:
                self._ws.send(json.dumps(packet))
                while True:
                    response = self._recv_json(f"la solicitud {request_type}")
                    if int(response.get("op", -1)) != 7:
                        continue
                    d = response.get("d") or {}
                    if str(d.get("requestId")) != rid:
                        continue
                    status = d.get("requestStatus") or {}
                    if not bool(status.get("result", False)):
                        comment = str(status.get("comment") or "Solicitud rechazada por OBS")
                        code = status.get("code")
                        raise ObsRequestError(f"{comment} (código {code})")
                    self._last_ok_at = time.time()
                    self._last_error = ""
                    return d.get("responseData") or {}
            except ObsRequestError as exc:
                # A normal OBS request rejection (for example asking media status
                # from a non-media input) does not invalidate the WebSocket session.
                self._last_error = str(exc)
                raise
            except Exception as exc:
                self._last_error = str(exc)
                self.disconnect()
                if isinstance(exc, ObsError):
                    raise
                raise ObsError(str(exc)) from exc

    def status(self, refresh: bool = True) -> dict:
        cfg = self.load_config()
        data = {
            "ok": True,
            "configured": cfg.public(),
            "connected": False,
            "lastError": self._last_error,
            "currentScene": "",
            "streaming": False,
            "recording": False,
            "streamDuration": "",
            "recordDuration": "",
            "obsVersion": "",
            "webSocketVersion": "",
            "profile": "",
            "sceneCollection": "",
            "connectedAt": self._last_connected_at,
            "lastOkAt": self._last_ok_at,
        }
        if not cfg.enabled:
            return data
        try:
            version = self.request("GetVersion") if refresh else {}
            current = self.request("GetCurrentProgramScene") if refresh else {}
            stream = self.request("GetStreamStatus") if refresh else {}
            record = self.request("GetRecordStatus") if refresh else {}
            profile = {}
            collection = {}
            if refresh:
                try:
                    profile = self.request("GetProfileList")
                except Exception:
                    profile = {}
                try:
                    collection = self.request("GetSceneCollectionList")
                except Exception:
                    collection = {}
            data.update({
                "connected": True,
                "currentScene": str(current.get("currentProgramSceneName") or ""),
                "streaming": bool(stream.get("outputActive", False)),
                "recording": bool(record.get("outputActive", False)),
                "streamDuration": str(stream.get("outputTimecode") or ""),
                "recordDuration": str(record.get("outputTimecode") or ""),
                "obsVersion": str(version.get("obsVersion") or ""),
                "webSocketVersion": str(version.get("obsWebSocketVersion") or ""),
                "profile": str(profile.get("currentProfileName") or ""),
                "sceneCollection": str(collection.get("currentSceneCollectionName") or ""),
                "connectedAt": self._last_connected_at,
                "lastOkAt": self._last_ok_at,
                "lastError": "",
            })
        except Exception as exc:
            data["lastError"] = str(exc)
        return data

    def inventory(self) -> dict:
        scenes_data = self.request("GetSceneList")
        scenes = [str(x.get("sceneName") or "") for x in scenes_data.get("scenes", []) if x.get("sceneName")]
        try:
            transition_data = self.request("GetSceneTransitionList")
            transitions = [str(x.get("transitionName") or "") for x in transition_data.get("transitions", []) if x.get("transitionName")]
            current_transition = str(transition_data.get("currentSceneTransitionName") or "")
        except Exception:
            transitions = []
            current_transition = ""
        inputs_data = self.request("GetInputList")
        input_rows = [x for x in inputs_data.get("inputs", []) if x.get("inputName")]
        inputs = [str(x.get("inputName") or "") for x in input_rows]
        input_details = []
        for row in input_rows:
            name = str(row.get("inputName") or "")
            detail = {
                "name": name,
                "kind": str(row.get("inputKind") or row.get("unversionedInputKind") or ""),
                "muted": False,
                "volume": 1.0,
                "volumeDb": 0.0,
                "audio": False,
                "mediaState": "",
            }
            try:
                mute = self.request("GetInputMute", {"inputName": name})
                volume = self.request("GetInputVolume", {"inputName": name})
                detail["muted"] = bool(mute.get("inputMuted", False))
                detail["volume"] = float(volume.get("inputVolumeMul", 1.0) or 0.0)
                detail["volumeDb"] = float(volume.get("inputVolumeDb", 0.0) or 0.0)
                detail["audio"] = True
            except Exception:
                pass
            try:
                media = self.request("GetMediaInputStatus", {"inputName": name})
                detail["mediaState"] = str(media.get("mediaState") or "")
            except Exception:
                pass
            input_details.append(detail)

        scene_items = {}
        filters = {}
        for scene in scenes:
            try:
                rows = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
                scene_items[scene] = [{
                    "id": int(x.get("sceneItemId")),
                    "name": str(x.get("sourceName") or ""),
                    "enabled": bool(x.get("sceneItemEnabled", True)),
                    "kind": str(x.get("inputKind") or x.get("sourceType") or ""),
                } for x in rows]
            except Exception:
                scene_items[scene] = []
        filter_sources = sorted(set(inputs + [item["name"] for rows in scene_items.values() for item in rows if item.get("name")]))
        for source in filter_sources:
            try:
                rows = self.request("GetSourceFilterList", {"sourceName": source}).get("filters", [])
                if rows:
                    filters[source] = [{"name": str(x.get("filterName") or ""), "enabled": bool(x.get("filterEnabled", True))} for x in rows]
            except Exception:
                pass
        return {
            "scenes": scenes,
            "transitions": transitions,
            "currentTransition": current_transition,
            "inputs": inputs,
            "inputDetails": input_details,
            "sceneItems": scene_items,
            "filters": filters,
        }

    def change_scene(self, scene: str):
        return self.request("SetCurrentProgramScene", {"sceneName": scene})

    def _scene_item_id(self, scene: str, source: str) -> int:
        rows = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        for row in rows:
            if str(row.get("sourceName") or "") == source:
                return int(row.get("sceneItemId"))
        raise ObsError(f"No encontré la fuente '{source}' en la escena '{scene}'.")

    def set_source_visible(self, scene: str, source: str, enabled: bool):
        item_id = self._scene_item_id(scene, source)
        return self.request("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id, "sceneItemEnabled": bool(enabled)})

    def set_filter_enabled(self, source: str, filter_name: str, enabled: bool):
        return self.request("SetSourceFilterEnabled", {"sourceName": source, "filterName": filter_name, "filterEnabled": bool(enabled)})

    def set_mute(self, input_name: str, muted: bool):
        return self.request("SetInputMute", {"inputName": input_name, "inputMuted": bool(muted)})

    def set_volume(self, input_name: str, multiplier: float):
        return self.request("SetInputVolume", {"inputName": input_name, "inputVolumeMul": max(0.0, min(20.0, float(multiplier)))})

    def media_action(self, input_name: str, action: str = "restart"):
        actions = {
            "restart": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
            "play": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY",
            "pause": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE",
            "stop": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP",
            "next": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NEXT",
            "previous": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PREVIOUS",
        }
        key = str(action or "restart").lower()
        if key not in actions:
            raise ObsError(f"Acción multimedia desconocida: {key}")
        return self.request("TriggerMediaInputAction", {"inputName": input_name, "mediaAction": actions[key]})

    def restart_media(self, input_name: str):
        return self.media_action(input_name, "restart")

    def set_transition(self, transition_name: str, duration_ms: int | None = None):
        if transition_name:
            self.request("SetCurrentSceneTransition", {"transitionName": transition_name})
        if duration_ms is not None:
            self.request("SetCurrentSceneTransitionDuration", {"transitionDuration": max(50, min(20000, int(duration_ms)))})
        return {"transitionName": transition_name, "durationMs": duration_ms}

    def replay_buffer(self, action: str):
        action = str(action or "save").lower()
        request_type = {"start": "StartReplayBuffer", "stop": "StopReplayBuffer", "save": "SaveReplayBuffer"}.get(action)
        if not request_type:
            raise ObsError(f"Acción de replay buffer desconocida: {action}")
        return self.request(request_type)

    def set_streaming(self, active: bool):
        return self.request("StartStream" if active else "StopStream")

    def set_recording(self, active: bool):
        return self.request("StartRecord" if active else "StopRecord")
