"""Persistent user settings: per-aircraft HUD profiles, limits and preferences."""

import copy
import json
import uuid
from pathlib import Path

from wtflight import paths
from wtflight.core.profiles import default_profile, new_group

# Colours used by settings written before version 4.
_LEGACY_INK = "#eaf2ff"
_LEGACY_TEAL = "#57e0c3"


class Settings:
    """JSON settings file; ``path`` defaults to the per-user location."""

    def __init__(self, path=None):
        self.path = Path(path or paths.CONFIG_PATH)
        self.on_saved = None
        self.data = {"version": 4, "profiles": {"default": default_profile()},
                     "limits": {}, "sound": True, "menu_hotkey": "Ins"}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        if isinstance(saved.get("profiles"), dict):
            self.data.update(saved)
        elif isinstance(saved.get("groups"), list) and saved["groups"]:
            groups = []
            for index, old in enumerate(saved["groups"]):
                if not isinstance(old, dict) or not old.get("metrics"):
                    continue
                group = new_group(old["metrics"][0])
                group.update(id=old.get("id", group["id"]), title=old.get("title", "БЛОК"),
                             metrics=old["metrics"],
                             x=0.04 if index % 2 == 0 else 0.53,
                             y=0.14 + (index // 2) * 0.3,
                             style=old.get("style", "text"),
                             size=old.get("font_size", 20),
                             labels=old.get("show_labels", True),
                             title_visible=old.get("show_title", False),
                             color=old.get("color", _LEGACY_INK),
                             accent=old.get("accent", _LEGACY_TEAL))
                groups.append(group)
            if groups:
                self.data["profiles"]["default"] = groups
            self.data["limits"]["default"] = saved.get("limits", {})
            self.data["sound"] = bool(saved.get("sound", True))
        # Preserve layout and colors; migrate only the old typography to the new HUD style.
        for groups in self.data["profiles"].values():
            for group in groups:
                group.pop("opacity", None)
        if saved.get("version", 0) < 4:
            for groups in self.data["profiles"].values():
                for group in groups:
                    group.update(font_family="Consolas", bold=True, shadow=True,
                                 compact_labels=True, spacing=1)
        self.data["version"] = 4

    @property
    def directory(self):
        """Folder for files that live next to the settings (sounds, backgrounds, cache)."""
        return self.path.parent

    def groups(self, aircraft):
        profiles = self.data["profiles"]
        if aircraft not in profiles:
            profiles[aircraft] = copy.deepcopy(profiles.get("default", default_profile()))
            for group in profiles[aircraft]:
                group["id"] = uuid.uuid4().hex[:10]
            self.save()
        return profiles[aircraft]

    def limits(self, aircraft):
        return self.data.setdefault("limits", {}).get(aircraft, {})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
        if self.on_saved:
            self.on_saved(self.data["profiles"])
