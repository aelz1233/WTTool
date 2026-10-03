"""Persistent application settings and profile migration.

The settings object is deliberately independent from Qt.  UI code can pass a
different path in tests or for portable installs without changing globals.
"""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wtflight.core._features import validate_profile
from wtflight.core.metrics import number
from wtflight.paths import CONFIG_PATH


class Settings:
    """Load, migrate and save the user's WT Flight configuration."""

    def __init__(self, path: str | Path | None = None,
                 group_factory: Callable[..., dict[str, Any]] | None = None,
                 default_factory: Callable[[], list[dict[str, Any]]] | None = None):
        self.path = Path(path) if path is not None else CONFIG_PATH
        if group_factory is None or default_factory is None:
            # Kept lazy so core.settings never imports the Qt window at module load.
            from wtflight.ui.main_window import default_profile, new_group
            group_factory = group_factory or new_group
            default_factory = default_factory or default_profile
        self._new_group = group_factory
        self._default_profile = default_factory
        self.data: dict[str, Any] = {
            "version": 4,
            "profiles": {"default": self._default_profile()},
            "limits": {},
            "sound": True,
            "menu_hotkey": "Ins",
        }
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError:
            return
        except ValueError:
            self._backup_invalid()
            return
        if not isinstance(saved, dict):
            self._backup_invalid()
            return
        if isinstance(saved.get("profiles"), dict):
            self.data.update(saved)
        elif isinstance(saved.get("groups"), list) and saved["groups"]:
            groups: list[dict[str, Any]] = []
            for index, old in enumerate(saved["groups"]):
                if not isinstance(old, dict) or not old.get("metrics"):
                    continue
                group = self._new_group(old["metrics"][0])
                group.update(
                    id=old.get("id", group["id"]), title=old.get("title", "БЛОК"),
                    metrics=old["metrics"], x=0.04 if index % 2 == 0 else 0.53,
                    y=0.14 + (index // 2) * 0.3, style=old.get("style", "text"),
                    size=old.get("font_size", 20), labels=old.get("show_labels", True),
                    title_visible=old.get("show_title", False), color=old.get("color", "#eaf2ff"),
                    accent=old.get("accent", "#57e0c3"),
                )
                groups.append(group)
            if groups:
                self.data["profiles"]["default"] = groups
            self.data["limits"]["default"] = saved.get("limits", {})
            self.data["sound"] = bool(saved.get("sound", True))
        for groups in self.data.get("profiles", {}).values():
            if isinstance(groups, list):
                for group in groups:
                    if isinstance(group, dict):
                        group.pop("opacity", None)
        if (number(saved.get("version")) or 0) < 4:
            for groups in self.data.get("profiles", {}).values():
                if isinstance(groups, list):
                    for group in groups:
                        if isinstance(group, dict):
                            group.update(font_family="Consolas", bold=True, shadow=True,
                                         compact_labels=True, spacing=1)
        self.data["version"] = 4
        self._validate()

    def _backup_invalid(self):
        # Keep the exact original before the UI writes recovered settings.
        if self.path.is_file():
            shutil.copy2(self.path, self.path.with_name(f"settings.recovery-{uuid.uuid4().hex[:8]}.json"))

    def _validate(self):
        original = copy.deepcopy(self.data)
        for section in ("profiles", "saved_layouts", "limits", "flight", "hotkeys", "preview"):
            if not isinstance(self.data.get(section, {}), dict):
                self.data[section] = {}
        for section in ("profiles", "saved_layouts"):
            for name, groups in list(self.data.get(section, {}).items()):
                try:
                    clean = validate_profile({"format": "wt-flight-profile", "version": 1, "groups": groups})
                except (ValueError, TypeError, AttributeError):
                    del self.data[section][name]
                    continue
                used = set()
                for group, source in zip(clean, groups, strict=True):
                    identity = source.get("id")
                    if isinstance(identity, str) and identity and identity not in used:
                        group["id"] = identity
                    used.add(group["id"])
                self.data[section][name] = clean
        self.data["profiles"].setdefault("default", self._default_profile())
        self.data["limits"] = {name: {key: number(value) for key, value in limits.items()
                                      if number(value) is not None} | ({"_auto": limits["_auto"]}
                                      if isinstance(limits.get("_auto"), bool) else {})
                               for name, limits in self.data["limits"].items() if isinstance(limits, dict)}
        flight = self.data.setdefault("flight", {})
        for key in ("warning_categories", "sound_categories", "sound_files"):
            if not isinstance(flight.get(key, {}), dict):
                flight[key] = {}
        if "sound_files" in flight:
            flight["sound_files"] = {key: value for key, value in flight["sound_files"].items()
                                     if isinstance(value, str)}
        for key, default, low, high in (("telemetry_hz", 10, 5, 15), ("aoa_limit", 15, 5, 45),
                ("warning_ratio", 90, 75, 99), ("fuel_critical_seconds", 60, 15, 300),
                ("volume", 65, 0, 100), ("repeat_seconds", 8, 2, 60), ("fuel_minutes", 3, 1, 20)):
            if key in flight:
                value = number(flight[key])
                flight[key] = int(value) if value is not None and low <= value <= high else default
        if flight.get("telemetry_hz", 10) not in (5, 10, 15):
            flight["telemetry_hz"] = 10
        for key in ("preview_background", "screen_name", "menu_hotkey"):
            if key in self.data and not isinstance(self.data[key], str):
                self.data.pop(key)
        for key, value in list(self.data.get("hotkeys", {}).items()):
            if not isinstance(value, str):
                del self.data["hotkeys"][key]
        if "database_checked_at" in self.data:
            self.data["database_checked_at"] = number(self.data["database_checked_at"]) or 0
        if "theme" in self.data and self.data["theme"] not in ("graphite", "cockpit", "arctic", "dark", "pink"):
            self.data["theme"] = "graphite"
        preview = self.data.get("preview", {})
        if "dimming" in preview:
            preview["dimming"] = max(0, min(100, int(number(preview["dimming"]) or 0)))
        if "image" in preview and not isinstance(preview["image"], str):
            preview.pop("image")
        if self.data != original:
            self._backup_invalid()

    def groups(self, aircraft: str) -> list[dict[str, Any]]:
        profiles = self.data.setdefault("profiles", {})
        if aircraft not in profiles:
            profiles[aircraft] = copy.deepcopy(profiles.get("default", self._default_profile()))
            for group in profiles[aircraft]:
                group["id"] = uuid.uuid4().hex[:10]
            self.save()
        return profiles[aircraft]

    def limits(self, aircraft: str) -> dict[str, Any]:
        return self.data.setdefault("limits", {}).get(aircraft, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
        if getattr(self, "on_saved", None):
            self.on_saved(self.data.get("profiles", {}))
