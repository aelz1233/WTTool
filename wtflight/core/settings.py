"""Persistent application settings and profile migration.

The settings object is deliberately independent from Qt.  UI code can pass a
different path in tests or for portable installs without changing globals.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Callable

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
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
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
        if saved.get("version", 0) < 4:
            for groups in self.data.get("profiles", {}).values():
                if isinstance(groups, list):
                    for group in groups:
                        if isinstance(group, dict):
                            group.update(font_family="Consolas", bold=True, shadow=True,
                                         compact_labels=True, spacing=1)
        self.data["version"] = 4

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
