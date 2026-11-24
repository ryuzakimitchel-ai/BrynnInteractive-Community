from __future__ import annotations

import json
import random
import threading
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Any


class AutomationEngine:
    def __init__(self, data_file: Path, action_executor: Callable[[dict, dict], Any]):
        self.data_file = Path(data_file)
        self.action_executor = action_executor
        self._lock = threading.RLock()
        self._running = set()
        self._cooldowns = {}
        self._history = []

    def _default(self) -> dict:
        return {"version": 1, "automations": []}

    def load(self) -> dict:
        with self._lock:
            try:
                raw = json.loads(self.data_file.read_text(encoding="utf-8")) if self.data_file.exists() else self._default()
            except Exception:
                raw = self._default()
            if not isinstance(raw, dict):
                raw = self._default()
            if not isinstance(raw.get("automations"), list):
                raw["automations"] = []
            return raw

    def save(self, payload: dict) -> dict:
        rows = payload.get("automations") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("automations debe ser una lista")
        normalized = [self.normalize(x) for x in rows if isinstance(x, dict)]
        data = {"version": 1, "automations": normalized}
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.data_file.parent,
                                             prefix=f".{self.data_file.name}.", suffix=".tmp", delete=False) as handle:
                tmp = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
            tmp.replace(self.data_file)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return data

    def delete(self, automation_id: str) -> dict:
        """Delete one automation atomically and persist immediately."""
        aid = str(automation_id or "").strip()
        if not aid:
            raise ValueError("Falta id de automatización")
        current = self.load()
        before = current.get("automations", [])
        rows = [x for x in before if str(x.get("id") or "") != aid]
        if len(rows) == len(before):
            raise KeyError("Automatización no encontrada")
        return self.save({"automations": rows})

    def normalize(self, item: dict) -> dict:
        aid = str(item.get("id") or uuid.uuid4().hex[:12]).strip().lower().replace(" ", "-")
        trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else {"type": "manual"}
        conditions = item.get("conditions") if isinstance(item.get("conditions"), list) else []
        actions = item.get("actions") if isinstance(item.get("actions"), list) else []
        try:
            cooldown = max(0, min(86400, float(item.get("cooldownSeconds", 0) or 0)))
        except Exception:
            cooldown = 0
        return {
            "id": aid or uuid.uuid4().hex[:12],
            "name": str(item.get("name") or "Nueva automatización")[:80],
            "enabled": bool(item.get("enabled", True)),
            "trigger": trigger,
            "conditions": conditions[:16],
            "actions": actions[:64],
            "cooldownSeconds": cooldown,
            "stopOnError": bool(item.get("stopOnError", True)),
        }

    @staticmethod
    def _get_path(data: dict, path: str):
        value: Any = data
        for part in str(path or "").split("."):
            if not part:
                continue
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    @staticmethod
    def _num(value):
        try:
            return float(value)
        except Exception:
            return None

    def _condition_ok(self, condition: dict, event: dict) -> bool:
        field = str(condition.get("field") or "")
        op = str(condition.get("op") or "equals").lower()
        expected = condition.get("value")
        actual = self._get_path(event, field)
        if op in {"equals", "eq"}:
            return str(actual).lower() == str(expected).lower()
        if op in {"not_equals", "neq"}:
            return str(actual).lower() != str(expected).lower()
        if op == "contains":
            return str(expected).lower() in str(actual or "").lower()
        if op == "not_contains":
            return str(expected).lower() not in str(actual or "").lower()
        if op in {"gte", "gt", "lte", "lt"}:
            a, b = self._num(actual), self._num(expected)
            if a is None or b is None:
                return False
            return {"gte": a >= b, "gt": a > b, "lte": a <= b, "lt": a < b}[op]
        if op == "exists":
            return actual not in (None, "", False)
        return False

    def _trigger_ok(self, trigger: dict, trigger_type: str, event: dict) -> bool:
        if str(trigger.get("type") or "manual") != str(trigger_type):
            return False
        for key in ("platform", "event", "command", "source"):
            expected = trigger.get(key)
            if expected in (None, "", "any", "*"):
                continue
            actual = event.get(key)
            if str(actual).lower() != str(expected).lower():
                return False
        return True

    def _record(self, row: dict):
        with self._lock:
            self._history.append(row)
            self._history = self._history[-100:]

    def history(self) -> list[dict]:
        with self._lock:
            return list(reversed(self._history[-50:]))

    def dispatch(self, trigger_type: str, event: dict, force_id: str | None = None) -> list[str]:
        now = time.time()
        started = []
        for raw in self.load().get("automations", []):
            item = self.normalize(raw)
            if force_id and item["id"] != force_id:
                continue
            if not item["enabled"] and not force_id:
                continue
            if not force_id and not self._trigger_ok(item["trigger"], trigger_type, event):
                continue
            if any(not self._condition_ok(c, event) for c in item["conditions"] if isinstance(c, dict)):
                continue
            last = float(self._cooldowns.get(item["id"], 0) or 0)
            if not force_id and item["cooldownSeconds"] > 0 and (now - last) < item["cooldownSeconds"]:
                continue
            with self._lock:
                if item["id"] in self._running:
                    continue
                self._running.add(item["id"])
                self._cooldowns[item["id"]] = now
            started.append(item["id"])
            try:
                threading.Thread(target=self._run, args=(item, dict(event), trigger_type), daemon=True, name=f"BrynnAuto-{item['id']}").start()
            except Exception:
                with self._lock:
                    self._running.discard(item["id"])
                    self._cooldowns.pop(item["id"], None)
                raise
        return started

    def _run(self, item: dict, event: dict, trigger_type: str):
        started_at = time.time()
        errors = []
        executed = 0
        try:
            for action in item.get("actions", []):
                if not isinstance(action, dict) or action.get("_disabled", False) is True:
                    continue
                kind = str(action.get("type") or "").strip()
                if kind == "chance":
                    try:
                        percent = max(0.0, min(100.0, float(action.get("percent", 50) or 0)))
                    except Exception:
                        percent = 50.0
                    executed += 1
                    if random.random() * 100.0 > percent:
                        break
                    continue
                if kind == "stop":
                    executed += 1
                    break
                if kind == "wait":
                    try:
                        ms = max(0, min(300000, int(action.get("ms", 0) or 0)))
                    except Exception:
                        ms = 0
                    time.sleep(ms / 1000.0)
                    executed += 1
                    continue
                try:
                    self.action_executor(action, event)
                    executed += 1
                except Exception as exc:
                    errors.append(f"{kind}: {exc}")
                    if item.get("stopOnError", True):
                        break
        finally:
            with self._lock:
                self._running.discard(item["id"])
            self._record({
                "id": uuid.uuid4().hex[:10],
                "automationId": item["id"],
                "name": item["name"],
                "trigger": trigger_type,
                "startedAt": started_at,
                "durationMs": int((time.time() - started_at) * 1000),
                "executed": executed,
                "ok": not errors,
                "errors": errors,
            })

    def runtime_state(self) -> dict:
        with self._lock:
            return {"running": sorted(self._running), "history": self.history()}
