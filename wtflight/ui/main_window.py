"""Drag-and-drop editor and click-through HUD for War Thunder telemetry."""

from __future__ import annotations

import copy
from html import escape
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.request import urlopen, Request

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QSize, Qt, QThread, Signal, QSaveFile, QIODevice, QEvent, QTimer
from PySide6.QtGui import (QBrush, QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter,
                           QPainterPath, QPen, QPixmap, QKeySequence, QImageReader, QShortcut,
                           QFontDatabase)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QAbstractSpinBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QSystemTrayIcon,
                               QVBoxLayout, QWidget, QTabWidget, QFormLayout, QKeySequenceEdit,
                               QFileDialog, QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressDialog)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from wt_core import (CONFIG_PATH, METRICS, available_metrics, evaluate,
                     metric_help, metric_label, metric_value, number, ENGINE_FIELDS,
                     engine_metric_parts, expand_engine_metric)
from wt_hotkey import GlobalHotkey, HOTKEYS
from wt_aircraft import AircraftDatabase, download_database, normalized_id
from wt_themes import THEMES, HUD_STYLES, theme_style
from wt_canvas import FlightCanvas
from wt_features import metric_risk, add_margins
from wt_feature_ui import FeatureControls
from wt_controls import SteppedSpinBox


API = "http://127.0.0.1:8111"
MIME = "application/x-wt-metric"
INK = "#eaf2ff"
MUTED = "#8fa1b9"
TEAL = "#57e0c3"
ORANGE = "#ffbd5a"
RED = "#ff6879"
HUD_GREEN = "#64be98"
APP_VERSION = "1.0.8"
GITHUB_REPO = "aelz1233/WTTool"
GITHUB_RELEASES = f"https://github.com/{GITHUB_REPO}/releases"


def alert_level(tone, caution_ratio=.9):
    """Normalize row state for the warning animation."""
    if tone == "critical" or (isinstance(tone, (float, int)) and tone >= 1):
        return "critical"
    if tone == "caution" or (isinstance(tone, (float, int)) and tone >= caution_ratio):
        return "caution"
    return ""


def flashing_alert_color(level, normal, now=None):
    """Alternate an alerted HUD row between its normal colour and yellow/red."""
    if not level:
        return QColor(normal)
    now = time.monotonic() if now is None else now
    if int(now * 5) % 2:
        return QColor(RED if level == "critical" else ORANGE)
    return QColor(normal)


def installed_hud_fonts():
    """Prefer familiar HUD fonts, but only offer families installed on this PC."""
    preferred = ["Consolas", "Lucida Console", "Bahnschrift", "Courier New", "Segoe UI",
                 "Arial", "Tahoma", "Verdana", "Impact"]
    installed = set(QFontDatabase.families())
    result = [name for name in preferred if name in installed]
    return result or ["Consolas"]


def fill_hud_font_box(combo):
    for family in installed_hud_fonts():
        combo.addItem(family)
        combo.setItemData(combo.count() - 1, QFont(family), Qt.FontRole)
HUD_LABELS = {"ias": "IAS", "tas": "TAS", "mach": "MACH", "altitude": "ALT",
              "g": "LDF", "climb": "CLMB", "aoa": "AOA", "aos": "AOS",
              "fuel": "FUEL", "fuel_percent": "FUEL", "throttle": "THR1",
              "rpm": "RPM1", "oil_temp": "OIL1", "water_temp": "WATER1",
              "power": "PWR1", "flaps": "FLAPS", "gear": "GEAR",
              "airbrake": "BRK", "heading": "HDG"}
HUD_LABELS.update(limit_ias="IAS MAX", limit_mach="M MAX", limit_pos_g="+G MAX",
                  limit_neg_g="−G MAX", limit_gear="GEAR MAX", limit_flaps="FLAPS MAX")
HUD_LABELS.update(fuel_time="FUEL TIME", fuel_flow="FLOW", ias_margin="IAS LEFT", mach_margin="M LEFT",
                  g_margin_pos="+G LEFT", g_margin_neg="−G LEFT")


def hud_label(metric_id):
    """Compact game-like label, including a stable engine number where needed."""
    engine = engine_metric_parts(metric_id)
    if engine:
        kind, index = engine
        return f"{ENGINE_FIELDS[kind][1]}{index}"
    return HUD_LABELS.get(metric_id, metric_label(metric_id))


def new_group(metric_id, x=0.08, y=0.16):
    return {"id": uuid.uuid4().hex[:10], "title": "НОВЫЙ БЛОК",
            "metrics": [metric_id], "x": x, "y": y, "style": "text",
            "size": 18, "labels": True, "title_visible": False,
            "font_family": "Lucida Console", "bold": True, "shadow": False,
            "compact_labels": True, "spacing": 1, "color": "#66d6a0", "accent": "#66d6a0",
            "hud_style": "wtrti", "outline": True, "outline_color": "#07140f", "outline_width": 1.4}


def reference_profile(kind="combat"):
    """Compact WTRTI-like layouts based on the supplied in-game references."""
    if kind == "empty":
        return []

    def group(metrics, x, y, color=HUD_GREEN, accent=HUD_GREEN, **values):
        result = new_group(metrics[0], x, y)
        result.update(metrics=metrics, color=color, accent=accent, size=18,
                      font_family="Lucida Console", compact_labels=True, **values)
        return result

    if kind == "engine":
        return [group(["climb", "state:Wx, deg/s", "g", "power", "thrust", "rpm", "fuel", "fuel_flow"],
                      .012, .024, color="#e2e7e9", accent="#e2e7e9",
                      label_map={"state:Wx, deg/s": "TURN"})]

    if kind == "helicopter":
        return [
            group(["ias", "altitude", "climb", "g", "aoa"], .018, .025,
                  color="#e2e7e9", accent="#e2e7e9"),
            group(["heading"], .58, .045),
            group(["throttle", "rpm", "power", "oil_temp", "water_temp"], .018, .54,
                  color="#e2e7e9", accent="#e2e7e9", title="ДВИГАТЕЛЬ", title_visible=True),
            group(["fuel", "fuel_flow", "fuel_time"], .80, .72, color="#ffbd5a", accent="#ffbd5a"),
        ]

    return [
        group(["throttle", "ias", "mach", "altitude", "aoa"], .018, .025,
              color="#e2e7e9", accent="#e2e7e9"),
        group(["heading"], .59, .045),
        group(["g"], .40, .40),
        group(["ias"], .80, .40),
        group(["thrust", "fuel", "fuel_flow"], .018, .64, color="#e2e7e9", accent="#ef4545",
              title="Power", title_visible=True),
        group(["climb"], .40, .79),
        group(["fuel_time"], .80, .79, color="#ffbd5a", accent="#ffbd5a"),
    ]


def default_profile():
    return reference_profile("combat")


class Settings:
    def __init__(self):
        self.data = {"version": 4, "profiles": {"default": default_profile()},
                     "limits": {}, "sound": True, "menu_hotkey": "Ins"}
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
                             color=old.get("color", INK),
                             accent=old.get("accent", TEAL))
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
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(CONFIG_PATH)
        if getattr(self, "on_saved", None):
            self.on_saved(self.data["profiles"])


class Telemetry(QThread):
    sample = Signal(str, dict, dict)

    def __init__(self, interval=0.1):
        super().__init__()
        self.stop_event = threading.Event()
        self.interval = max(0.05, min(0.5, float(interval)))

    def set_interval(self, interval):
        self.interval = max(0.05, min(0.5, float(interval)))

    def run(self):
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                with urlopen(API + "/state", timeout=0.25) as response:
                    state = json.load(response)
                if not isinstance(state, dict) or not state.get("valid"):
                    self.sample.emit("waiting", {}, {})
                else:
                    try:
                        with urlopen(API + "/indicators", timeout=0.25) as response:
                            indicators = json.load(response)
                        if not isinstance(indicators, dict) or not indicators.get("valid"):
                            indicators = {}
                    except (OSError, ValueError):
                        indicators = {}
                    self.sample.emit("live", state, indicators)
            except (OSError, ValueError):
                self.sample.emit("offline", {}, {})
            self.stop_event.wait(max(0, self.interval - (time.monotonic() - start)))

    def stop(self):
        self.stop_event.set()
        self.wait(2500)


class DatabaseUpdater(QThread):
    completed = Signal(object, str)

    def __init__(self, cache_dir, version):
        super().__init__()
        self.cache_dir, self.version = cache_dir, version

    def run(self):
        try:
            self.completed.emit(download_database(self.cache_dir, self.version), "")
        except (OSError, ValueError) as error:
            self.completed.emit(None, str(error))


class UpdateChecker(QThread):
    """Check the public GitHub release feed without blocking the editor."""
    completed = Signal(object, str)

    def run(self):
        try:
            request = Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"User-Agent": "WT-Flight-Assistant", "Accept": "application/vnd.github+json"},
            )
            with urlopen(request, timeout=5) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("GitHub вернул неожиданный ответ")
            tag = str(payload.get("tag_name", "")).strip()
            version = tag.lstrip("vV")
            asset = next((item.get("browser_download_url") for item in payload.get("assets", [])
                          if str(item.get("name", "")).lower().endswith(".exe")), "")
            self.completed.emit({"tag": tag, "version": version, "url": payload.get("html_url", GITHUB_RELEASES),
                                 "asset": asset, "name": payload.get("name", tag)}, "")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.completed.emit(None, str(error))


class InstallerDownloader(QThread):
    progress = Signal(int)
    completed = Signal(str, str)

    def __init__(self, url, filename):
        super().__init__()
        self.url, self.filename = url, filename

    def run(self):
        try:
            target = Path(tempfile.gettempdir()) / self.filename
            request = Request(self.url, headers={"User-Agent": "WT-Flight-Assistant"})
            with urlopen(request, timeout=20) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                with target.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        output.write(chunk)
                        received += len(chunk)
                        if total:
                            self.progress.emit(min(100, int(received * 100 / total)))
            self.completed.emit(str(target), "")
        except (OSError, ValueError) as error:
            self.completed.emit("", str(error))


def warning_for(sample, limits):
    mode, state, _indicators = sample
    if mode not in ("live", "demo"):
        return "", ""
    categories = state.get("_warning_categories", {})
    enabled = lambda key: categories.get(key, True)
    caution_ratio = number(state.get("_warning_ratio")) or .9
    severity, message = evaluate(number(state.get("IAS, km/h")), number(state.get("Ny")),
                    number(limits.get("positive_g")) if enabled("g") else None,
                    number(limits.get("negative_g")) if enabled("g") else None,
                    number(limits.get("ias_kmh")) if enabled("speed") else None, caution_ratio)
    if severity in ("critical", "caution") and ((limits.get("_g_estimate") and "G" in message) or
                                                (limits.get("_sweep_conservative") and "IAS" in message)):
        message = "≈ " + message
    mach, max_mach = number(state.get("M")), number(limits.get("mach")) if enabled("speed") else None
    if mach is not None and max_mach and mach >= max_mach:
        message = (message + " · " if severity == "critical" else "") + "ПРЕДЕЛ MACH"
        severity = "critical"
    elif mach is not None and max_mach and mach >= max_mach * caution_ratio and severity not in ("critical", "caution"):
        severity, message = "caution", "Близко к пределу MACH"
    fuel_seconds = number(state.get("fuel_seconds"))
    if enabled("fuel") and fuel_seconds is not None and fuel_seconds <= state.get("_fuel_minutes", 3) * 60:
        fuel_severity = "critical" if fuel_seconds <= state.get("_fuel_critical_seconds", 60) else "caution"
        if severity not in ("critical", "caution"):
            severity, message = fuel_severity, "МАЛО ТОПЛИВА"
        else:
            severity, message = ("critical" if fuel_severity == "critical" else severity,
                                 message + " · МАЛО ТОПЛИВА")
    aoa, aoa_limit = number(state.get("AoA, deg")), number(state.get("_aoa_limit"))
    if enabled("stall") and aoa is not None and aoa_limit and aoa_limit > 0 and abs(aoa) >= aoa_limit * caution_ratio:
        aoa_severity = "critical" if abs(aoa) >= aoa_limit else "caution"
        aoa_message = "ВОЗМОЖНО СВАЛИВАНИЕ" if aoa_severity == "critical" else "ВЫСОКИЙ УГОЛ АТАКИ"
        if severity not in ("critical", "caution"):
            return aoa_severity, aoa_message
        return "critical" if aoa_severity == "critical" else severity, message + " · " + aoa_message
    return severity, message


class GroupView(QWidget):
    selected = Signal(str)
    moved = Signal()
    added = Signal(str, str)

    def __init__(self, group, editor, parent=None):
        super().__init__(parent)
        self.group = group
        self.editor = editor
        self.sample = ("offline", {}, {})
        self.limits = {}
        self.is_selected = False
        self.press = None
        self.hover_pos = QPoint()
        self.setMouseTracking(True)
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.setInterval(550)
        self.tooltip_timer.timeout.connect(self.show_metric_tooltip)
        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(100)
        self.flash_timer.timeout.connect(self.update)
        self.flash_timer.start()
        # A popup parented to an embedded GroupView is automatically embedded by
        # QGraphicsProxyWidget too. Keep it outside the scene, in screen coordinates.
        self.metric_tip = QLabel(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                                Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput |
                                Qt.BypassGraphicsProxyWidget)
        self.destroyed.connect(self.metric_tip.deleteLater)
        self.metric_tip.setObjectName("metricDescriptionTip")
        self.metric_tip.setWordWrap(True)
        self.metric_tip.setTextFormat(Qt.RichText)
        self.metric_tip.setFixedWidth(340)
        tip_font = QFont(QApplication.font())
        tip_font.setPixelSize(15)
        self.metric_tip.setFont(tip_font)
        self.metric_tip.setAttribute(Qt.WA_ShowWithoutActivating)
        self.metric_tip.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.metric_tip.setStyleSheet(
            "QLabel#metricDescriptionTip { color: #f1f5f9; background: #111a20; "
            "font-family: 'Segoe UI'; font-size: 15px; border: 1px solid #64808b; border-radius: 7px; "
            "padding: 10px 12px; }"
        )
        self.metric_tip.hide()
        self.setAttribute(Qt.WA_TranslucentBackground)
        if editor:
            self.setAcceptDrops(True)
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.adjustSize()

    def lines(self):
        mode, state, indicators = self.sample
        active = mode in ("live", "demo")
        available = set(available_metrics(state, indicators, self.limits)) if active else None
        lines = []
        if self.group.get("title_visible"):
            lines.append((self.group.get("title", "БЛОК"), "", "title", "__title__"))
        for configured_metric in self.group.get("metrics", []):
            metric_ids = expand_engine_metric(configured_metric, state) if active else [configured_metric]
            for metric_id in metric_ids:
                if active and metric_id not in available:
                    continue
                if metric_id == "warning":
                    severity, warning = warning_for(self.sample, self.limits)
                    value = warning if active else "ОЖИДАНИЕ БОЯ"
                    if not value or severity in ("normal", "unset"):
                        continue
                    lines.append(("", value, severity or "unset", "warning"))
                else:
                    value = metric_value(metric_id, state, indicators, self.limits) if active else "—"
                    label_map = self.group.get("label_map", {})
                    label = (label_map.get(metric_id, label_map.get(configured_metric, hud_label(metric_id)))
                             if self.group.get("compact_labels", True) else metric_label(metric_id))
                    label = label.upper() if self.group.get("labels", True) else ""
                    risk = metric_risk(metric_id, state, self.limits, state.get("_fuel_minutes", 3)) if active else None
                    lines.append((label, value, risk if risk is not None else "normal", metric_id))
        return lines

    def hud_font(self):
        font = QFont(self.group.get("font_family", "Consolas"))
        font.setPixelSize(int(self.group.get("size", 18)))
        font.setBold(self.group.get("bold", True))
        return font

    def sizeHint(self):
        fm = QFontMetrics(self.hud_font())
        rows = self.lines() or [("", "—", "normal", "__empty__")]
        gap = fm.horizontalAdvance(" ")
        label_width = max(fm.horizontalAdvance(a) for a, _, _, _ in rows)
        width = label_width + gap + max(fm.horizontalAdvance(b) for _, b, _, _ in rows)
        pad = 10 if self.group.get("style") == "panel" else 3
        spacing = int(self.group.get("spacing", 1))
        return QSize(max(40, width + pad * 2), max(20, len(rows) * (fm.height() + spacing) + pad * 2))

    def set_sample(self, sample, limits):
        self.sample = sample
        self.limits = limits
        self.adjustSize()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        g = self.group
        painter.setFont(self.hud_font())
        fm = painter.fontMetrics()
        panel = g.get("style") == "panel"
        if panel:
            painter.setBrush(QColor(14, 23, 39, 220))
            painter.setPen(QPen(QColor("#36506b"), 1))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)
        if self.editor and self.is_selected:
            pen = QPen(QColor(TEAL), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 10, 10)
        x = 10 if panel else 3
        y = x + fm.ascent()
        gap = fm.horizontalAdvance(" ")
        lines = self.lines() or [("", "—", "normal", "__empty__")]
        label_width = max((fm.horizontalAdvance(a) for a, _, _, _ in lines), default=0)
        for label, value, tone, _metric_id in lines:
            level = alert_level(tone, number(self.sample[1].get("_warning_ratio")) or .9)
            tone_color = RED if tone == "critical" else ORANGE if tone == "caution" else g.get("color", INK)
            critical_row, caution_row = level == "critical", level == "caution"
            if not level and isinstance(tone, (float, int)) and tone > .75:
                start = QColor(g.get("color", INK)) if tone < .9 else QColor(ORANGE)
                end = QColor(ORANGE if tone < .9 else RED)
                blend = min(1, max(0, (tone - .75) / .15 if tone < .9 else (tone - .9) / .1))
                tone_color = QColor(round(start.red() + (end.red() - start.red()) * blend),
                                    round(start.green() + (end.green() - start.green()) * blend),
                                    round(start.blue() + (end.blue() - start.blue()) * blend))
            if tone in ("title", "unset"):
                tone_color = g.get("accent", TEAL) if tone == "title" else MUTED
            label_color = RED if critical_row else ORANGE if caution_row else g.get("accent", TEAL)
            if level:
                tone_color = flashing_alert_color(level, g.get("color", INK))
                label_color = flashing_alert_color(level, g.get("accent", TEAL))
            if g.get("shadow", True):
                painter.setPen(QColor(4, 12, 25, 190))
                painter.drawText(x + 1, y + 1, label)
                painter.drawText(x + label_width + (gap if label and value else 0) + 1, y + 1, value)
            def draw_hud_text(text, left, fill):
                if not text:
                    return
                outline = g.get("outline", True)
                path = QPainterPath()
                path.addText(float(left), float(y), painter.font(), text)
                if outline:
                    pen = QPen(QColor(g.get("outline_color", "#07140f")),
                               float(g.get("outline_width", 1.4)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                    painter.strokePath(path, pen)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(fill))
                painter.drawPath(path)
                painter.setBrush(Qt.NoBrush)
            draw_hud_text(label, x, label_color)
            draw_hud_text(value, x + label_width + (gap if label and value else 0), tone_color)
            y += fm.height() + int(g.get("spacing", 1))
        painter.end()

    def mousePressEvent(self, event):
        if self.editor and event.button() == Qt.LeftButton:
            self.tooltip_timer.stop()
            self.metric_tip.hide()
            if hasattr(self, "canvas"):
                self.canvas.setFocus(Qt.MouseFocusReason)
                if event.modifiers() & Qt.ControlModifier:
                    selected = set(self.canvas.selected_ids)
                    if self.group["id"] in selected:
                        selected.remove(self.group["id"])
                    else:
                        selected.add(self.group["id"])
                    primary = self.group["id"] if self.group["id"] in selected else None
                    self.canvas.set_selection(selected, primary)
                elif self.group["id"] not in self.canvas.selected_ids:
                    self.canvas.set_selection({self.group["id"]}, self.group["id"])
            selected_id = (self.canvas.selected_id if hasattr(self, "canvas") and
                           event.modifiers() & Qt.ControlModifier else self.group["id"])
            self.selected.emit(selected_id or "")
            if hasattr(self, "canvas") and self.group["id"] not in self.canvas.selected_ids:
                self.press = None
                return
            self.press = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.editor and self.press is not None and event.buttons() & Qt.LeftButton:
            self.tooltip_timer.stop()
            self.metric_tip.hide()
            pos = self.pos() + event.position().toPoint() - self.press
            self.canvas.move_selected_by(self, pos.x(), pos.y())
        else:
            self.hover_pos = event.position().toPoint()
            if self.rect().contains(self.hover_pos):
                self.tooltip_timer.start()

    def show_metric_tooltip(self):
        if not self.isVisible() or (hasattr(self, "canvas") and not self.canvas.isVisible()):
            return
        if not self.rect().contains(self.hover_pos):
            return
        g = self.group
        pad = 10 if g.get("style") == "panel" else 3
        fm = QFontMetrics(self.hud_font())
        row_height = fm.height() + int(g.get("spacing", 1))
        row_index = (self.hover_pos.y() - pad) // max(1, row_height)
        lines = self.lines()
        if row_index < 0 or row_index >= len(lines):
            self.metric_tip.hide()
            return
        label, value, _tone, metric_id = lines[row_index]
        if metric_id == "__title__":
            self.metric_tip.hide()
            return
        title = metric_label(metric_id)
        if metric_id == "warning":
            title = "Предупреждения"
        detail = metric_help(metric_id)
        current = f"<br>Сейчас: {escape(value)}" if value and value != "—" else ""
        text = f"<b>{escape(title)}</b>{current}<br><br>{escape(detail)}"
        # A regular QToolTip disappears after a short platform timeout. Use a small,
        # non-interactive tool window and keep it visible for the entire hover instead.
        self.metric_tip.setText(text)
        self.metric_tip.setFixedHeight(self.metric_tip.heightForWidth(self.metric_tip.width()))
        row_y = pad + row_index * row_height + fm.height() // 2
        proxy = self.graphicsProxyWidget() if self.editor and hasattr(self, "canvas") else None
        if proxy is not None:
            scene_anchor = proxy.mapToScene(QPointF(self.width(), row_y))
            viewport_anchor = self.canvas.mapFromScene(scene_anchor)
            anchor = self.canvas.viewport().mapToGlobal(viewport_anchor)
            left_anchor = self.canvas.viewport().mapToGlobal(
                self.canvas.mapFromScene(proxy.mapToScene(QPointF(0, row_y))))
        else:
            anchor = self.mapToGlobal(QPoint(self.width(), row_y))
            left_anchor = self.mapToGlobal(QPoint(0, row_y))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x, y = anchor.x() + 12, anchor.y() - self.metric_tip.height() // 2
        if x + self.metric_tip.width() > bounds.right() + 1:
            x = left_anchor.x() - self.metric_tip.width() - 12
        x = max(bounds.left(), min(x, bounds.right() + 1 - self.metric_tip.width()))
        y = max(bounds.top(), min(y, bounds.bottom() + 1 - self.metric_tip.height()))
        self.metric_tip.move(max(bounds.left(), x), max(bounds.top(), y))
        self.metric_tip.show()

    def leaveEvent(self, event):
        self.tooltip_timer.stop()
        self.metric_tip.hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.tooltip_timer.stop()
        self.metric_tip.hide()
        super().hideEvent(event)

    def mouseReleaseEvent(self, _event):
        if self.editor and self.press is not None:
            self.press = None
            self.setCursor(Qt.OpenHandCursor)
            self.moved.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls() and hasattr(self.parentWidget(), "image_dropped"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls() and hasattr(self.parentWidget(), "image_dropped"):
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.parentWidget().image_dropped.emit(url.toLocalFile())
                    event.acceptProposedAction()
                    return
            return
        metric_id = bytes(event.mimeData().data(MIME)).decode("utf-8")
        self.added.emit(self.group["id"], metric_id)
        event.acceptProposedAction()


class MetricList(QTreeWidget):
    metric_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(1, 28)
        self.setObjectName("metricList")
        self.expanded_sections = {"Полёт"}
        self.populating = False
        self.itemExpanded.connect(self.remember_sections)
        self.itemCollapsed.connect(self.remember_sections)
        self.itemClicked.connect(self.click_item)
        self.itemDoubleClicked.connect(self.double_click_item)

    def remember_sections(self, item):
        if self.populating:
            return
        section = item.data(0, Qt.UserRole + 1)
        if item.isExpanded():
            self.expanded_sections.add(section)
        else:
            self.expanded_sections.discard(section)

    def populate(self, ids, query):
        self.populating = True
        self.clear()
        sections = {}
        theme = THEMES.get(QApplication.instance().property("theme"), THEMES["graphite"])
        english = QApplication.instance().property("language") == "en"
        section_en = {"Полёт": "Flight", "Двигатель": "Engine", "Механизация": "Configuration",
                      "Навигация": "Navigation", "Предупреждения": "Warnings", "Пределы самолёта": "Aircraft limits",
                      "Другие данные": "Other data"}
        label_en = {"ias": "IAS · Indicated", "tas": "TAS · True airspeed", "g": "LDF · G-load",
                    "mach": "MACH · Mach number", "altitude": "ALT · Altitude", "climb": "CLMB · Climb rate",
                    "aoa": "AOA · Angle of attack", "aos": "AOS · Sideslip", "fuel": "FUEL · Fuel",
                    "rpm": "RPM · All engines", "throttle": "THR · All engines", "power": "PWR · All engines",
                    "oil_temp": "OIL · All engines", "water_temp": "WTR · Cooling", "fuel_time": "FUEL · Remaining",
                    "fuel_flow": "FUEL · Flow", "ias_margin": "IAS · Margin", "mach_margin": "MACH · Margin",
                    "g_margin_pos": "G · Positive margin", "g_margin_neg": "G · Negative margin",
                    "limit_ias": "IAS · Limit", "limit_mach": "MACH · Limit", "limit_pos_g": "G · Positive limit",
                    "limit_neg_g": "G · Negative limit", "limit_gear": "GEAR · Limit", "limit_flaps": "FLAPS · Limit"}
        for metric_id in ids:
            label = metric_label(metric_id)
            code = hud_label(metric_id)
            if query and not any(query in text.casefold() for text in (label, metric_id, code)):
                continue
            section = (METRICS[metric_id][0] if metric_id in METRICS else
                       "Топливо и двигатель" if engine_metric_parts(metric_id) else "Другие данные")
            section = {"Топливо и двигатель": "Двигатель", "Конфигурация": "Механизация",
                       "Система": "Предупреждения"}.get(section, section)
            section_display = section_en.get(section, section) if english else section
            if section not in sections:
                parent = QTreeWidgetItem(self, [section_display])
                parent.setData(0, Qt.UserRole + 1, section)
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setFirstColumnSpanned(True)
                parent.setForeground(0, QColor(theme["muted"]))
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                sections[section] = parent
            display = {"ias": "IAS · Приборная", "tas": "TAS · Истинная", "g": "LDF · Перегрузка",
                       "mach": "MACH · Число Маха", "altitude": "ALT · Высота", "climb": "CLMB · Набор",
                       "aoa": "AOA · Угол атаки", "aos": "AOS · Скольжение", "fuel": "FUEL · Топливо",
                       "rpm": "RPM · Все двигатели", "throttle": "THR · Все двигатели", "power": "PWR · Все двигатели",
                       "oil_temp": "OIL · Масло", "water_temp": "WTR · Охлаждение",
                       "fuel_time": "FUEL · Остаток", "fuel_flow": "FUEL · Расход",
                       "ias_margin": "IAS · Запас", "mach_margin": "MACH · Запас",
                       "g_margin_pos": "G · Запас +", "g_margin_neg": "G · Запас −",
                       "limit_ias": "IAS · Предел", "limit_mach": "MACH · Предел",
                       "limit_pos_g": "G · Предел +", "limit_neg_g": "G · Предел −",
                       "limit_gear": "GEAR · Предел", "limit_flaps": "FLAPS · Предел"}.get(metric_id,
                                                                                                  f"{code} · {label}" if engine_metric_parts(metric_id) else label)
            if english:
                display = label_en.get(metric_id, display)
                label = label_en.get(metric_id, label)
            item = QTreeWidgetItem(sections[section], [display, "+"])
            item.setToolTip(0, label)
            item.setData(0, Qt.UserRole, metric_id)
            item.setTextAlignment(1, Qt.AlignCenter)
            item.setForeground(1, QColor(theme["accent"]))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            item.setToolTip(0, f"{label}\n\n{metric_help(metric_id)}\n\n" +
                             ("Drag to the layout or an existing group." if english else "Перетащите на макет или на существующую группу."))
            item.setToolTip(1, "Add metric" if english else "Добавить отдельный показатель")
        for section, parent in sections.items():
            parent.setText(0, f"{section}  ·  {parent.childCount()}")
            parent.setExpanded(bool(query) or section in self.expanded_sections)
        self.populating = False
        return sum(p.childCount() for p in sections.values())

    def click_item(self, item, column):
        metric_id = item.data(0, Qt.UserRole)
        if metric_id and column == 1:
            self.metric_requested.emit(metric_id)
        elif not metric_id:
            item.setExpanded(not item.isExpanded())

    def double_click_item(self, item, column):
        metric_id = item.data(0, Qt.UserRole)
        if metric_id and column == 0:
            self.metric_requested.emit(metric_id)

    def keyPressEvent(self, event):
        item = self.currentItem()
        if item and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            metric_id = item.data(0, Qt.UserRole)
            if metric_id:
                self.metric_requested.emit(metric_id)
                return
        super().keyPressEvent(event)

    def startDrag(self, _actions):
        item = self.currentItem()
        if not item:
            return
        metric_id = item.data(0, Qt.UserRole)
        if not metric_id:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, str(metric_id).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class ScreenCanvas(FlightCanvas):
    def __init__(self):
        super().__init__(GroupView, MIME)


class OverlayWindow(GroupView):
    def __init__(self, group, screen_provider=None):
        super().__init__(group, False)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.screen_provider = screen_provider or QApplication.primaryScreen

    def set_editing(self, editing):
        self.editor = editing
        self.is_selected = editing
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not editing)
        self.setWindowFlag(Qt.WindowTransparentForInput, not editing)
        self.setCursor(Qt.OpenHandCursor if editing else Qt.ArrowCursor)
        self.press = None

    def mousePressEvent(self, event):
        if self.editor and event.button() == Qt.LeftButton:
            self.press = event.globalPosition().toPoint() - self.pos()
            self.selected.emit(self.group["id"])
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.editor and self.press is not None and event.buttons() & Qt.LeftButton:
            screen = self.screen_provider().geometry()
            point = event.globalPosition().toPoint() - self.press
            x = max(screen.left(), min(screen.right() + 1 - self.width(), point.x()))
            y = max(screen.top(), min(screen.bottom() + 1 - self.height(), point.y()))
            self.move(x, y)
            self.group["x"] = (x - screen.left()) / screen.width()
            self.group["y"] = (y - screen.top()) / screen.height()

    def place(self):
        screen = self.screen_provider().geometry()
        self.adjustSize()
        if self.press is None:
            self.move(screen.left() + min(max(0, screen.width() - self.width()),
                                         int(self.group.get("x", 0) * screen.width())),
                      screen.top() + min(max(0, screen.height() - self.height()),
                                        int(self.group.get("y", 0) * screen.height())))


class HotkeyCapture(QKeySequenceEdit):
    """Capture one chord without the native editor clearing globally consumed keys."""

    def __init__(self):
        super().__init__()
        self.setMaximumSequenceLength(1)
        self.installEventFilter(self)
        for child in self.findChildren(QLineEdit):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ShortcutOverride:
            if event.key() not in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                event.accept()
                return True
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            key = event.key()
            if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                return super().eventFilter(watched, event)
            if event.type() == QEvent.KeyPress:
                if key == Qt.Key_Backspace:
                    self.clear()
                elif key not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
                    self.setKeySequence(QKeySequence(event.keyCombination()))
            event.accept()
            return True
        return super().eventFilter(watched, event)


class HotkeyPanel(QWidget):
    """Shared keyboard settings for the full editor and the Insert menu."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.edits = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for action, (label, default) in HOTKEYS.items():
            layout.addWidget(owner.text(label, "muted"))
            row = QHBoxLayout()
            row.setSpacing(5)
            edit = HotkeyCapture()
            edit.setMaximumSequenceLength(1)
            edit.setKeySequence(QKeySequence(owner.configured_hotkey(action)))
            self.edits[action] = edit
            row.addWidget(edit, 1)
            apply = QPushButton("✓")
            apply.setFixedWidth(32)
            apply.setToolTip("Применить сочетание")
            apply.clicked.connect(lambda _checked=False, key=action: self.apply(key))
            row.addWidget(apply)
            disable = QPushButton("×")
            disable.setFixedWidth(32)
            disable.setToolTip("Отключить это сочетание" if action != "menu" else "Для меню нужна клавиша")
            disable.setEnabled(action != "menu")
            disable.clicked.connect(lambda _checked=False, key=action: self.disable(key))
            row.addWidget(disable)
            layout.addLayout(row)
        self.feedback = owner.text("Нажмите новое сочетание, затем ✓. Работает и в игре.", "muted")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        layout.addStretch()

    def sync(self, action=None):
        for key, edit in self.edits.items():
            if action is None or action == key:
                edit.setKeySequence(QKeySequence(self.owner.configured_hotkey(key)))
        if hasattr(self.owner, "hotkey_errors"):
            errors = [HOTKEYS[k][0] + ": " + v for k, v in self.owner.hotkey_errors.items() if v]
            self.feedback.setText("\n".join(errors) if errors else
                                  "Нажмите новое сочетание, затем ✓. Работает и в игре.")

    def apply(self, action):
        sequence = self.edits[action].keySequence().toString(QKeySequence.PortableText)
        ok, error = self.owner.apply_hotkey(action, sequence)
        self.feedback.setText("Сохранено: " + (sequence or "отключено") if ok else error)

    def disable(self, action):
        self.edits[action].clear()
        self.apply(action)


class QuickSettings(QDialog):
    """Independent tool window; opening it never restores the main editor."""

    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.owner = owner
        self.syncing = False
        self.setWindowTitle("WT Flight · Быстрое меню")
        self.setFixedSize(380, 520)
        self.setModal(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        header = QHBoxLayout()
        header.addWidget(owner.text("WT FLIGHT", "headline"))
        header.addStretch()
        header.addWidget(owner.text("БЫСТРОЕ МЕНЮ", "eyebrow"))
        layout.addLayout(header)
        self.plane = owner.text("Общий профиль", "muted")
        self.plane.setWordWrap(True)
        layout.addWidget(self.plane)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        hud = QWidget()
        self.tabs.addTab(hud, "HUD")
        hud_layout = QVBoxLayout(hud)
        hud_layout.setContentsMargins(2, 16, 2, 6)
        hud_layout.setSpacing(14)
        self.visible_check = QCheckBox("Показывать HUD")
        self.visible_check.toggled.connect(self.change_visibility)
        hud_layout.addWidget(self.visible_check)
        self.move_check = QCheckBox("Перемещать текст мышью")
        self.move_check.toggled.connect(self.change_editing)
        hud_layout.addWidget(self.move_check)
        hint = owner.text("Включите перемещение и перетащите группу прямо на экране. Закройте меню, чтобы вернуться к игре.", "muted")
        hint.setWordWrap(True)
        hud_layout.addWidget(hint)
        self.action_hints = owner.text("", "muted")
        self.action_hints.setWordWrap(True)
        hud_layout.addWidget(self.action_hints)
        hud_layout.addStretch()
        self.theme_box = QComboBox()
        for key, theme in THEMES.items():
            self.theme_box.addItem(theme["name"] + " · " + theme["description"], key)
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        hud_layout.addWidget(owner.text("ОФОРМЛЕНИЕ ПРОГРАММЫ", "eyebrow"))
        hud_layout.addWidget(self.theme_box)

        look = QWidget()
        self.tabs.addTab(look, "Вид текста")
        look_layout = QVBoxLayout(look)
        look_layout.setContentsMargins(2, 12, 2, 6)
        self.group_box = QComboBox()
        self.group_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_box.currentIndexChanged.connect(self.select_group)
        look_layout.addWidget(self.group_box)
        self.style_box = QComboBox()
        self.style_box.addItem("Текст без фона", "text")
        self.style_box.addItem("Компактная панель", "panel")
        self.font_box = QComboBox()
        fill_hud_font_box(self.font_box)
        self.size_spin = SteppedSpinBox()
        self.size_spin.setRange(10, 48)
        self.size_spin.setSuffix(" px")
        form = QFormLayout()
        form.addRow("Вид", self.style_box)
        form.addRow("Шрифт", self.font_box)
        self.hud_style_box = QComboBox()
        for key, preset in HUD_STYLES.items():
            self.hud_style_box.addItem(preset["name"], key)
        form.addRow("Готовый стиль HUD", self.hud_style_box)
        form.addRow("Размер", self.size_spin)
        look_layout.addLayout(form)
        self.shadow = QCheckBox("Тень текста")
        self.compact = QCheckBox("Короткие подписи: IAS / LDF")
        look_layout.addWidget(self.shadow)
        look_layout.addWidget(self.compact)
        colors = QHBoxLayout()
        for key, label in (("color", "Цвет значений"), ("accent", "Цвет подписей")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, k=key: self.choose_color(k))
            colors.addWidget(button)
        look_layout.addLayout(colors)
        look_layout.addStretch()
        self.style_box.currentIndexChanged.connect(self.apply_group)
        self.font_box.currentTextChanged.connect(self.apply_group)
        self.size_spin.valueChanged.connect(self.apply_group)
        self.hud_style_box.currentIndexChanged.connect(self.apply_hud_style)
        self.shadow.toggled.connect(self.apply_group)
        self.compact.toggled.connect(self.apply_group)

        keys = QWidget()
        self.tabs.addTab(keys, "Клавиши")
        keys_layout = QVBoxLayout(keys)
        keys_layout.setContentsMargins(2, 12, 2, 0)
        self.key_panel = HotkeyPanel(owner)
        keys_layout.addWidget(self.key_panel)
        self.key_edit = self.key_panel.edits["menu"]
        self.feedback = self.key_panel.feedback
        self.history_shortcuts = []
        for keys, callback in (("Ctrl+Z", owner.undo_layout), ("Ctrl+Y", owner.redo_layout)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(callback)
            self.history_shortcuts.append(shortcut)
        actions = QHBoxLayout()
        editor = QPushButton("Открыть редактор")
        editor.clicked.connect(self.open_editor)
        actions.addWidget(editor)
        done = QPushButton("Готово · Esc")
        done.setObjectName("primary")
        done.clicked.connect(self.hide)
        actions.addWidget(done)
        layout.addLayout(actions)

    def change_theme(self):
        if not self.syncing:
            self.owner.set_theme(self.theme_box.currentData())

    def sync(self):
        self.syncing = True
        self.plane.setText(self.owner.database.display_name(self.owner.aircraft) if self.owner.aircraft != "default"
                           else "Общий профиль · ожидание самолёта")
        self.visible_check.setChecked(self.owner.hud_visible)
        self.move_check.setChecked(self.owner.overlay_editing)
        self.group_box.clear()
        for group in self.owner.groups():
            self.group_box.addItem(self.owner.group_caption(group), group["id"])
        self.group_box.setCurrentIndex(self.group_box.findData(self.owner.selected_id))
        self.key_panel.sync()
        self.action_hints.setText("\n".join(f"{self.owner.configured_hotkey(key) or 'Отключено'}  ·  {HOTKEYS[key][0]}"
                                          for key in ("hud", "move", "editor")))
        self.theme_box.setCurrentIndex(self.theme_box.findData(self.owner.settings.data.get("theme", "graphite")))
        self.syncing = False
        self.sync_group()

    def sync_group(self):
        self.syncing = True
        group = self.owner.selected_group()
        for widget in (self.style_box, self.font_box, self.size_spin, self.shadow, self.compact,
                       self.hud_style_box):
            widget.setEnabled(bool(group))
        if group:
            self.style_box.setCurrentIndex(0 if group.get("style") == "text" else 1)
            self.font_box.setCurrentText(group.get("font_family", "Consolas"))
            self.hud_style_box.setCurrentIndex(self.hud_style_box.findData(group.get("hud_style", "wtrti")))
            self.size_spin.setValue(group.get("size", 18))
            self.shadow.setChecked(group.get("shadow", True))
            self.compact.setChecked(group.get("compact_labels", True))
        self.syncing = False

    def select_group(self):
        if not self.syncing:
            self.owner.select_group(self.group_box.currentData())
            self.sync_group()

    def apply_group(self):
        group = self.owner.selected_group()
        if self.syncing or not group:
            return
        selected = [g for g in self.owner.groups() if g["id"] in self.owner.canvas.selected_ids]
        targets = selected if len(selected) > 1 else [group]
        values = dict(style=self.style_box.currentData(), font_family=self.font_box.currentText(),
                      size=self.size_spin.value(), shadow=self.shadow.isChecked(),
                      compact_labels=self.compact.isChecked())
        field = {self.style_box: "style", self.font_box: "font_family", self.size_spin: "size",
                 self.shadow: "shadow", self.compact: "compact_labels"}.get(self.sender())
        changes = {field: values[field]} if field else values
        for target in targets:
            target.update(changes)
            target["hud_style"] = "custom"
        self.owner.settings.save()
        self.owner.select_group(group["id"], preserve_selection=True)
        self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
        self.owner.update_overlays()

    def apply_hud_style(self):
        if self.syncing:
            return
        key = self.hud_style_box.currentData()
        if key not in HUD_STYLES:
            return
        selected = [g for g in self.owner.groups() if g["id"] in self.owner.canvas.selected_ids]
        group = self.owner.selected_group()
        for target in selected or ([group] if group else []):
            values = copy.deepcopy(HUD_STYLES[key])
            values.pop("name", None)
            target.update(values)
            target["hud_style"] = key
        if group:
            self.owner.settings.save()
            self.sync_group()
            self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
            self.owner.update_overlays()

    def choose_color(self, key):
        group = self.owner.selected_group()
        if not group:
            return
        color = QColorDialog.getColor(QColor(group.get(key, HUD_GREEN)), self, "Цвет HUD")
        if color.isValid():
            group[key] = color.name()
            self.owner.settings.save()
            self.owner.canvas.set_sample(self.owner.sample, self.owner.current_limits())
            self.owner.update_overlays()

    def change_visibility(self, visible):
        if not self.syncing:
            self.owner.hud_visible = visible
            if not visible:
                self.move_check.setChecked(False)
            self.owner.update_overlays()

    def change_editing(self, editing):
        if not self.syncing:
            self.owner.set_overlay_editing(editing)

    def apply_hotkey(self):
        self.key_panel.apply("menu")

    def open_editor(self):
        self.hide()
        self.owner.open_editor()

    def hideEvent(self, event):
        self.owner.set_overlay_editing(False)
        super().hideEvent(event)


class LimitsDialog(QDialog):
    def __init__(self, parent, aircraft, limits):
        super().__init__(parent)
        self.setWindowTitle("Пределы самолёта")
        self.setMinimumWidth(370)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Самолёт: {aircraft}"))
        info = QLabel("Пустое поле использует предел из базы. Число задаёт ваш порог для этого самолёта.\n"
                      "Оценка G учитывает массу топлива, но не массу подвесок и экипажа.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)
        self.auto_check = QCheckBox("Автоматические пределы из базы")
        self.auto_check.setChecked(limits.get("_auto", True))
        layout.addWidget(self.auto_check)
        automatic = parent.database.limits(aircraft, parent.sample[1])
        self.entries = {}
        for key, title in (("positive_g", "Предел +G"),
                           ("negative_g", "Предел −G"),
                           ("ias_kmh", "Предел IAS, км/ч")):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            edit = QLineEdit()
            value = limits.get(key)
            edit.setText(str(value) if value is not None else "")
            auto_value = automatic.get(key)
            edit.setPlaceholderText(f"Авто: {auto_value:.1f}" if auto_value is not None else "Нет данных")
            row.addWidget(edit)
            self.entries[key] = edit
            layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.values = None

    def validate(self):
        values = {}
        for key, edit in self.entries.items():
            raw = edit.text().strip().replace(",", ".")
            value = number(raw) if raw else None
            if raw and value is None:
                QMessageBox.warning(self, "Пределы", "Введите число или оставьте поле пустым.")
                return
            values[key] = value
        if ((values["positive_g"] is not None and values["positive_g"] <= 1) or
                (values["negative_g"] is not None and values["negative_g"] >= 0) or
                (values["ias_kmh"] is not None and values["ias_kmh"] <= 0)):
            QMessageBox.warning(self, "Пределы", "Нужно: +G > 1, −G < 0, IAS > 0.")
            return
        values["_auto"] = self.auto_check.isChecked()
        self.values = values
        self.accept()


STYLE = """
QWidget { background: #15181b; color: #e3e7e8; font-family: 'Segoe UI'; font-size: 12px; }
QLabel, QCheckBox { background: transparent; }
QLabel#eyebrow { color: #8fbca9; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#headline { color: #f3f5f5; font-size: 19px; font-weight: 600; }
QLabel#muted { color: #929b9f; font-size: 11px; }
QLabel#status { background: #21352e; border-radius: 5px; color: #91cdb4; padding: 5px 8px; font-size: 10px; }
QLabel#status[offline="true"] { background: #30302a; color: #c9bc94; }
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit { background: #202529; border: 1px solid #343c40; border-radius: 5px; padding: 6px; color: #e3e7e8; min-height: 16px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QKeySequenceEdit:focus { border-color: #87b9a4; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #242a2e; selection-background-color: #344b40; }
QListWidget { background: #191e21; border: 1px solid #2d3539; border-radius: 6px; padding: 3px; outline: none; }
QListWidget::item { border-radius: 4px; padding: 5px 3px; margin: 0; }
QListWidget::item:hover { background: #28332e; }
QListWidget::item:selected { background: #344b40; color: #d5eee1; }
QTreeWidget { background: #191e21; border: 1px solid #2d3539; border-radius: 6px; padding: 3px; outline: none; }
QTreeWidget::item { height: 27px; padding: 1px 2px; border: none; }
QTreeWidget::item:hover { background: #26372f; }
QTreeWidget::item:selected { background: #344b40; color: #e4f2eb; }
QPushButton { background: #262d31; border: 1px solid #394246; border-radius: 5px; padding: 7px 10px; font-weight: 500; }
QPushButton:hover { background: #35423b; border-color: #6a8d7b; }
QPushButton:checked { background: #344b40; border-color: #8fbca5; color: #d5eee1; }
QPushButton#primary { background: #8fbca5; border: 1px solid #8fbca5; color: #14241c; }
QPushButton#primary:hover { background: #abd2be; }
QPushButton#danger { color: #d8999d; }
QPushButton#stepButton { padding: 2px; min-width: 28px; max-width: 32px; min-height: 24px; font-size: 10px; }
QCheckBox { spacing: 7px; padding: 2px 0; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #53635c; border-radius: 3px; background: #202529; }
QCheckBox::indicator:checked { background: #8fbca5; border: 1px solid #aecfbe; }
QSlider::groove:horizontal { background: #34433c; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #8fbca5; width: 12px; margin: -5px 0; border-radius: 6px; }
QTabWidget::pane { border: none; border-top: 1px solid #30383c; }
QTabBar::tab { background: transparent; color: #939da0; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #cce2d6; border-bottom-color: #8fbca5; }
QTabBar::tab:hover { color: #e3e7e8; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #191e21; width: 6px; }
QScrollBar::handle:vertical { background: #46534c; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class MainWindow(FeatureControls, QMainWindow):
    def __init__(self, start_background_updates=True):
        super().__init__()
        self.settings = Settings()
        self.init_feature_state()
        self.database = AircraftDatabase.load(CONFIG_PATH.parent)
        self.db_updater = None
        self.update_checker = None
        self.installer_downloader = None
        self.update_progress = None
        self.database_status = "локальная копия"
        self.aircraft = "default"
        self.sample = ("offline", {}, {})
        self.available = None
        self.selected_id = None
        self.overlays = []
        self.hud_visible = False
        self.overlay_editing = False
        self.loading_inspector = False
        self.setWindowTitle("WT Flight · Редактор HUD")
        self.resize(720, 560)
        self.setMinimumSize(640, 520)
        self.build_ui()
        self.set_language(self.settings.data.get("language", "en"), save=False)
        self.set_theme(self.settings.data.get("theme", "graphite"))
        self.install_editor_shortcuts()
        QApplication.instance().installEventFilter(self)
        self.restore_background()
        self.build_tray()
        self.refresh_palette()
        if self.groups():
            self.selected_id = self.groups()[0]["id"]
        self.refresh_layout()
        self.hotkeys = {}
        self.hotkey_errors = {}
        for action in HOTKEYS:
            binding = GlobalHotkey(lambda key=action: self.dispatch_hotkey(key))
            self.hotkeys[action] = binding
            sequence = self.configured_hotkey(action)
            ok, error = binding.register(sequence) if sequence else (True, "")
            self.hotkey_errors[action] = error
        self.hotkey = self.hotkeys["menu"]
        self.hotkey_error = self.hotkey_errors["menu"]
        self.hotkey_hint.setText(f"{self.hotkey.sequence} • быстрое меню" if not self.hotkey_error else
                                "Клавиша занята • откройте меню")
        self.quick_settings = QuickSettings(self)
        # Quick menu is created after the main window; apply the selected language to it too.
        self.set_language(self.settings.data.get("language", "en"), save=False)
        self.main_key_panel.sync()
        self.settings.save()
        interval = 1 / self.settings.data.get("flight", {}).get("telemetry_hz", 10)
        self.telemetry = Telemetry(interval)
        self.telemetry.sample.connect(self.on_sample)
        self.telemetry.start()
        self.start_feature_timers()
        self.update_aircraft_panel()
        if start_background_updates and time.time() - self.settings.data.get("database_checked_at", 0) > 86400:
            self.check_database_update()
        if start_background_updates and not self.settings.data.get("updates_disabled"):
            self.check_for_updates(silent=True)

    def groups(self):
        return self.settings.groups(self.aircraft)

    def configured_hotkey(self, action):
        saved = self.settings.data.get("hotkeys", {})
        if action in saved:
            return saved[action]
        return self.settings.data.get("menu_hotkey", "Ins") if action == "menu" else HOTKEYS[action][1]

    def dispatch_hotkey(self, action):
        focus = QApplication.focusWidget() if QApplication.activeWindow() else None
        while focus:
            if isinstance(focus, QKeySequenceEdit):
                focus.setKeySequence(QKeySequence(self.hotkeys[action].sequence))
                return
            focus = focus.parentWidget()
        {"menu": self.toggle_quick_settings, "hud": self.toggle_hud,
         "move": self.toggle_move_hotkey, "editor": self.open_editor}[action]()

    def apply_hotkey(self, action, sequence):
        if not sequence:
            if action == "menu":
                return False, "Назначьте клавишу для меню."
            self.hotkeys[action].disable()
        else:
            try:
                sequence, _flags, _vk = GlobalHotkey.decode(sequence)
            except ValueError as error:
                return False, str(error)
            for key, binding in self.hotkeys.items():
                if key != action and binding.sequence == sequence:
                    return False, "Уже назначено: " + HOTKEYS[key][0]
            ok, error = self.hotkeys[action].register(sequence)
            if not ok:
                return False, error
        self.settings.data.setdefault("hotkeys", {})[action] = sequence
        self.hotkey_errors[action] = ""
        if action == "menu":
            self.settings.data["menu_hotkey"] = sequence
            self.hotkey_error = ""
            self.hotkey_hint.setText(f"{sequence} • быстрое меню")
        self.settings.save()
        self.main_key_panel.sync(action)
        self.quick_settings.key_panel.sync(action)
        return True, ""

    def close_hotkeys(self):
        for binding in self.hotkeys.values():
            binding.close()

    def toggle_move_hotkey(self):
        if not self.quick_settings.isVisible():
            self.toggle_quick_settings()
        self.set_overlay_editing(not self.overlay_editing)
        self.quick_settings.sync()
        self.quick_settings.tabs.setCurrentIndex(0)

    def set_theme(self, theme):
        theme = theme if theme in THEMES else "graphite"
        self.settings.data["theme"] = theme
        QApplication.instance().setProperty("theme", theme)
        QApplication.instance().setStyleSheet(theme_style(STYLE, theme))
        for key, button in self.theme_buttons.items():
            button.setChecked(key == theme)
        self.theme_description.setText(THEMES[theme]["description"])
        if hasattr(self, "quick_settings"):
            self.quick_settings.theme_box.blockSignals(True)
            self.quick_settings.theme_box.setCurrentIndex(self.quick_settings.theme_box.findData(theme))
            self.quick_settings.theme_box.blockSignals(False)
        self.refresh_palette()
        self.settings.save()

    def install_editor_shortcuts(self):
        self.editor_shortcuts = []
        def bind(keys, widget, callback, context=Qt.WidgetWithChildrenShortcut):
            shortcut = QShortcut(QKeySequence(keys), widget)
            shortcut.setContext(context)
            shortcut.activated.connect(callback)
            self.editor_shortcuts.append(shortcut)
        bind("Del", self.canvas, self.delete_group)
        bind("Del", self.group_metrics, self.remove_metric)
        bind("Ctrl+D", self.canvas, self.duplicate_group)
        bind("Ctrl+A", self.canvas, self.select_all_groups)
        bind("Ctrl+F", self, self.focus_search, Qt.WindowShortcut)
        bind("Ctrl+Z", self, self.undo_layout, Qt.WindowShortcut)
        bind("Ctrl+Y", self, self.redo_layout, Qt.WindowShortcut)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            for modifier, step in (("", 1), ("Shift+", 10)):
                bind(modifier + key, self.canvas, lambda x=dx * step, y=dy * step: self.nudge_group(x, y))

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)
        modifiers = event.modifiers() | QApplication.keyboardModifiers()

        # A wheel over controls must never silently change the selected font, size,
        # spacing, zoom or another setting. Use clicks and keyboard for those fields.
        if isinstance(watched, (QComboBox, QAbstractSpinBox, QSlider)):
            event.accept()
            return True

        if modifiers & Qt.ControlModifier:
            widget = watched if isinstance(watched, QWidget) else None
            if widget is None:
                widget = QApplication.widgetAt(event.globalPosition().toPoint())
            in_editor = False
            while widget:
                if isinstance(widget, GroupView) and widget.editor:
                    in_editor = True
                    break
                if widget is self.canvas.viewport() or widget is self.canvas:
                    in_editor = True
                    break
                widget = widget.parentWidget()
            if in_editor:
                group = self.selected_group()
                delta = event.angleDelta().y() or event.pixelDelta().y()
                if group and delta:
                    steps = max(1, round(abs(delta) / (120 if event.angleDelta().y() else 40)))
                    direction = 1 if delta > 0 else -1
                    for selected in self.groups():
                        if selected["id"] not in self.canvas.selected_ids:
                            continue
                        selected["size"] = max(10, min(48, int(selected.get("size", 18)) + direction * steps))
                    self.settings.save()
                    self.select_group(group["id"], preserve_selection=True)
                    self.canvas.set_sample(self.sample, self.current_limits())
                    self.canvas.position_views()
                    self.update_overlays()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def focus_search(self):
        self.tabs.setCurrentIndex(0)
        self.search.setFocus()
        self.search.selectAll()

    def duplicate_group(self):
        group = self.selected_group()
        if not group:
            return
        duplicate = copy.deepcopy(group)
        duplicate.update(id=uuid.uuid4().hex[:10], x=min(.9, group["x"] + .025), y=min(.9, group["y"] + .025))
        self.groups().append(duplicate)
        self.selected_id = duplicate["id"]
        self.layout_changed()

    def select_all_groups(self):
        self.canvas.set_selection({group["id"] for group in self.groups()})
        self.select_group(self.canvas.selected_id, preserve_selection=True)

    def nudge_group(self, dx, dy):
        group = self.selected_group()
        if group:
            view = next(v for v in self.canvas.views if v.group["id"] == group["id"])
            self.canvas.move_selected_by(view, view.x() + dx, view.y() + dy, snap=False)
            self.settings.save()
            self.canvas.position_views()
            self.update_overlays()

    def current_limits(self):
        overrides = self.settings.limits(self.aircraft)
        live_type = normalized_id(self.sample[2].get("type")) if self.sample[0] in ("live", "demo") else ""
        limits = (self.database.limits(live_type, self.sample[1], self.sample[2])
                  if live_type and overrides.get("_auto", True) else {})
        for key, value in overrides.items():
            if not key.startswith("_") and number(value) is not None:
                limits[key] = number(value)
        if number(overrides.get("positive_g")) is not None and number(overrides.get("negative_g")) is not None:
            limits.pop("_g_estimate", None)
        if number(overrides.get("ias_kmh")) is not None:
            limits.pop("_sweep_conservative", None)
        if limits:
            limits["_fuel_minutes"] = self.settings.data.get("flight", {}).get("fuel_minutes", 3)
        return limits

    def selected_group(self):
        return next((g for g in self.groups() if g["id"] == self.selected_id), None)

    def text(self, label, object_name=None):
        widget = QLabel(label)
        if object_name:
            widget.setObjectName(object_name)
        return widget

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(self.text("WT FLIGHT", "headline"))
        header.addStretch()
        self.demo_button = QPushButton("Тест")
        self.demo_button.setCheckable(True)
        self.demo_button.clicked.connect(self.set_demo_mode)
        header.addWidget(self.demo_button)
        self.update_button = QPushButton("Обновить")
        self.update_button.setToolTip("Проверить новую версию программы на GitHub")
        self.update_button.clicked.connect(self.check_for_updates)
        header.addWidget(self.update_button)
        self.status = self.text("ОЖИДАНИЕ ИГРЫ", "status")
        self.status.setProperty("offline", True)
        header.addWidget(self.status)
        outer.addLayout(header)
        self.plane_label = self.text("Подключение к игре автоматически", "muted")
        self.plane_label.setWordWrap(True)
        outer.addWidget(self.plane_label)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        layout_page = QWidget()
        self.tabs.addTab(layout_page, "Расположение")
        body = QHBoxLayout(layout_page)
        body.setContentsMargins(0, 12, 0, 0)
        body.setSpacing(12)
        left = QWidget()
        left.setFixedWidth(232)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        library_header = QHBoxLayout()
        library_header.addWidget(self.text("ПОКАЗАТЕЛИ", "eyebrow"))
        library_header.addStretch()
        self.metric_count = self.text("", "muted")
        library_header.addWidget(self.metric_count)
        ll.addLayout(library_header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск · IAS, топливо…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_palette)
        ll.addWidget(self.search)
        self.palette = MetricList()
        self.palette.metric_requested.connect(self.add_metric_from_catalog)
        ll.addWidget(self.palette, 1)
        self.palette_hint = self.text("Данные появятся в бою", "muted")
        self.palette_hint.setWordWrap(True)
        ll.addWidget(self.palette_hint)
        self.palette_hint.hide()
        body.addWidget(left)
        ml = QVBoxLayout()
        self.profile_label = self.text("ПРОФИЛЬ: ОБЩИЙ", "eyebrow")
        self.profile_label.setWordWrap(True)
        self.profile_label.setParent(layout_page)
        self.profile_label.hide()
        self.canvas_tools = QWidget()
        tools_layout = QVBoxLayout(self.canvas_tools)
        tools_layout.setContentsMargins(0, 4, 0, 4)
        tools_layout.addLayout(self.build_preview_toolbar())
        self.background_button = QPushButton("⋯")
        self.background_button.setFixedWidth(36)
        background_menu = QMenu(self.background_button)
        background_menu.addAction("Сохранить макет как…", self.save_preset)
        background_menu.addAction("Импорт макета…", self.import_profile)
        background_menu.addAction("Экспорт макета…", self.export_profile)
        background_menu.addSeparator()
        background_menu.addAction("Загрузить фон…", self.choose_background)
        self.remove_background_action = background_menu.addAction("Убрать фон", self.clear_background)
        background_menu.addSeparator()
        self.grid_action = background_menu.addAction("Показать сетку")
        self.grid_action.setCheckable(True)
        self.grid_action.toggled.connect(self.change_preview_grid)
        self.canvas_tools_action = background_menu.addAction("Инструменты макета")
        self.canvas_tools_action.setCheckable(True)
        self.canvas_tools_action.toggled.connect(self.canvas_tools.setVisible)
        background_menu.addSeparator()
        background_menu.addAction("Сбросить расположение", self.reset_layout)
        self.background_button.setMenu(background_menu)
        self.background_button.setToolTip("Макеты, фон, масштаб и выравнивание")
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.text("Макет", "muted"))
        self.main_preset_box = QComboBox()
        self.main_preset_box.setMinimumContentsLength(18)
        self.main_preset_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.main_preset_box.setToolTip("Готовые и сохранённые конфигурации оверлея")
        profile_row.addWidget(self.main_preset_box, 1)
        self.apply_main_preset_button = QPushButton("Применить")
        self.apply_main_preset_button.setToolTip("Применить макет к текущему профилю самолёта")
        self.apply_main_preset_button.clicked.connect(lambda: self.apply_preset(self.main_preset_box))
        profile_row.addWidget(self.apply_main_preset_button)
        self.overwrite_main_preset_button = QPushButton("Сохранить")
        self.overwrite_main_preset_button.setToolTip("Перезаписать выбранный сохранённый конфиг текущим макетом")
        self.overwrite_main_preset_button.clicked.connect(lambda: self.overwrite_preset(self.main_preset_box))
        profile_row.addWidget(self.overwrite_main_preset_button)
        self.delete_main_preset_button = QPushButton("Удалить")
        self.delete_main_preset_button.setObjectName("danger")
        self.delete_main_preset_button.setToolTip("Удалить выбранный сохранённый конфиг")
        self.delete_main_preset_button.clicked.connect(lambda: self.delete_preset(self.main_preset_box))
        profile_row.addWidget(self.delete_main_preset_button)
        profile_row.addWidget(self.background_button)
        ml.addLayout(profile_row)
        ml.addWidget(self.canvas_tools)
        self.canvas_tools.hide()
        self.canvas = ScreenCanvas()
        # The visible hint below the canvas explains selection and shortcuts. A widget
        # tooltip here masks the per-metric descriptions shown on the preview.
        self.canvas.image_dropped.connect(self.load_background)
        self.canvas.group_selected.connect(lambda group_id: self.select_group(group_id, preserve_selection=True))
        self.canvas.group_added.connect(self.add_to_group)
        self.canvas.group_created.connect(self.create_group)
        self.canvas.group_moved.connect(self.layout_changed)
        ml.addWidget(self.canvas, 1)
        background_controls = QHBoxLayout()
        background_controls.addWidget(self.text("Затемнение фона", "muted"))
        self.background_dim = QSlider(Qt.Horizontal)
        self.background_dim.setRange(0, 75)
        self.background_dim.setMaximumWidth(115)
        self.background_dim.setToolTip("Затемнить картинку для проверки читаемости текста")
        self.background_dim.valueChanged.connect(self.change_background_dimming)
        background_controls.addWidget(self.background_dim)
        background_controls.addStretch()
        tools_layout.addLayout(background_controls)
        hint = self.text("Перетащите показатель на макет · Рамка выделяет несколько", "muted")
        hint.setWordWrap(True)
        ml.addWidget(hint)
        edit_row = QHBoxLayout()
        create_group = QPushButton("＋ Группа")
        create_group.setToolTip("Создать пустую группу на макете; затем перетащите в неё нужные показатели")
        create_group.clicked.connect(self.create_empty_group)
        edit_row.addWidget(create_group)
        look = QPushButton("Оформление выбранного текста")
        look.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        edit_row.addWidget(look)
        ml.addLayout(edit_row)
        body.addLayout(ml, 1)

        appearance_scroll = QScrollArea()
        appearance_scroll.setWidgetResizable(True)
        appearance_scroll.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(appearance_scroll, "Вид текста")
        appearance = QWidget()
        appearance_scroll.setWidget(appearance)
        rl = QVBoxLayout(appearance)
        rl.setContentsMargins(2, 14, 6, 6)
        self.group_selector = QComboBox()
        self.group_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_selector.currentIndexChanged.connect(self.select_from_combo)
        rl.addWidget(self.group_selector)
        self.inspector_note = self.text("Выберите группу на макете", "muted")
        self.inspector_note.setWordWrap(True)
        rl.addWidget(self.inspector_note)
        form = QFormLayout()
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(9)
        self.text_details = QWidget()
        details_layout = QVBoxLayout(self.text_details)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_form = QFormLayout()
        details_form.setVerticalSpacing(9)
        details_layout.addLayout(details_form)
        self.title_edit = QLineEdit()
        self.title_edit.editingFinished.connect(self.apply_inspector)
        details_form.addRow("Название", self.title_edit)
        self.style_box = QComboBox()
        self.style_box.addItem("Текст без фона", "text")
        self.style_box.addItem("Компактная панель", "panel")
        self.style_box.currentIndexChanged.connect(self.apply_inspector)
        details_form.addRow("Отображение", self.style_box)
        self.font_box = QComboBox()
        fill_hud_font_box(self.font_box)
        self.font_box.currentTextChanged.connect(self.apply_inspector)
        form.addRow("Шрифт", self.font_box)
        self.hud_style_box = QComboBox()
        for key, preset in HUD_STYLES.items():
            self.hud_style_box.addItem(preset["name"], key)
        self.hud_style_box.currentIndexChanged.connect(self.apply_hud_style)
        form.addRow("Готовый стиль HUD", self.hud_style_box)
        self.size_slider = SteppedSpinBox()
        self.size_slider.setRange(10, 48)
        self.size_slider.setSuffix(" px")
        self.size_slider.valueChanged.connect(self.apply_inspector)
        form.addRow("Размер", self.size_slider)
        self.spacing_spin = SteppedSpinBox()
        self.spacing_spin.setRange(0, 16)
        self.spacing_spin.setSuffix(" px")
        self.spacing_spin.valueChanged.connect(self.apply_inspector)
        details_form.addRow("Между строками", self.spacing_spin)
        wheel_hint = self.text("На макете: Ctrl + колесо — размер", "muted")
        wheel_hint.setWordWrap(True)
        form.addRow(wheel_hint)
        rl.addLayout(form)
        self.text_details_button = QPushButton("Дополнительные настройки")
        self.text_details_button.setCheckable(True)
        self.text_details_button.toggled.connect(self.text_details.setVisible)
        rl.addWidget(self.text_details_button)
        rl.addWidget(self.text_details)
        self.text_details.hide()
        checks = QHBoxLayout()
        self.labels_check = QCheckBox("Подписи")
        self.title_check = QCheckBox("Название группы")
        self.compact_check = QCheckBox("IAS / LDF / CLMB")
        for check in (self.labels_check, self.title_check, self.compact_check):
            check.toggled.connect(self.apply_inspector)
            checks.addWidget(check)
        details_layout.addLayout(checks)
        effects = QHBoxLayout()
        self.bold_check = QCheckBox("Жирный")
        self.shadow_check = QCheckBox("Тень текста")
        self.outline_check = QCheckBox("Обводка")
        for check in (self.bold_check, self.shadow_check, self.outline_check):
            check.toggled.connect(self.apply_inspector)
            effects.addWidget(check)
        self.text_color = QPushButton("Цвет значений")
        self.text_color.clicked.connect(lambda: self.choose_color("color"))
        self.accent_color = QPushButton("Цвет подписей")
        self.accent_color.clicked.connect(lambda: self.choose_color("accent"))
        self.outline_color = QPushButton("Цвет обводки")
        self.outline_color.clicked.connect(lambda: self.choose_color("outline_color"))
        details_layout.addLayout(effects)
        colors = QHBoxLayout()
        colors.addWidget(self.text_color)
        colors.addWidget(self.accent_color)
        colors.addWidget(self.outline_color)
        details_layout.addLayout(colors)
        self.group_metrics = QListWidget()
        self.group_metrics.setFixedHeight(95)
        details_layout.addWidget(self.group_metrics)
        actions = QHBoxLayout()
        remove_metric = QPushButton("Убрать показатель")
        remove_metric.clicked.connect(self.remove_metric)
        actions.addWidget(remove_metric)
        delete = QPushButton("Удалить группу")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_group)
        actions.addWidget(delete)
        limits = QPushButton("Пределы самолёта")
        limits.clicked.connect(self.edit_limits)
        actions.addWidget(limits)
        details_layout.addLayout(actions)
        rl.addStretch()

        aircraft_page = QWidget()
        self.tabs.addTab(aircraft_page, "Самолёт")
        aircraft_layout = QVBoxLayout(aircraft_page)
        aircraft_layout.setContentsMargins(4, 14, 4, 4)
        self.aircraft_name = self.text("Самолёт определится в бою", "headline")
        self.aircraft_name.setWordWrap(True)
        aircraft_layout.addWidget(self.aircraft_name)
        self.aircraft_details = self.text("", "muted")
        self.aircraft_details.setWordWrap(True)
        aircraft_layout.addWidget(self.aircraft_details)
        limits_form = QFormLayout()
        limits_form.setVerticalSpacing(10)
        limits_form.setHorizontalSpacing(24)
        self.aircraft_values = {}
        for key, title in (("ias_kmh", "Предельная IAS"), ("mach", "Предельный Mach"),
                           ("positive_g", "Предел +G · оценка"), ("negative_g", "Предел −G · оценка"),
                           ("gear_kmh", "Скорость выпуска шасси"),
                           ("flaps_landing_kmh", "Посадочные закрылки")):
            value = self.text("—")
            self.aircraft_values[key] = value
            limits_form.addRow(title, value)
        aircraft_layout.addLayout(limits_form)
        self.limit_note = self.text("", "muted")
        self.limit_note.setWordWrap(True)
        aircraft_layout.addWidget(self.limit_note)
        aircraft_layout.addStretch()
        self.database_note = self.text("", "muted")
        self.database_note.setWordWrap(True)
        aircraft_layout.addWidget(self.database_note)
        db_actions = QHBoxLayout()
        self.database_update_button = QPushButton("Обновить базу")
        self.database_update_button.clicked.connect(self.check_database_update)
        db_actions.addWidget(self.database_update_button)
        custom_limits = QPushButton("Свои пороги")
        custom_limits.clicked.connect(self.edit_limits)
        db_actions.addWidget(custom_limits)
        aircraft_layout.addLayout(db_actions)

        self.build_helicopter_tab()

        preferences = QScrollArea()
        preferences.setWidgetResizable(True)
        preferences.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(preferences, "Настройки")
        preferences_body = QWidget()
        preferences.setWidget(preferences_body)
        prefs = QVBoxLayout(preferences_body)
        prefs.setContentsMargins(3, 14, 8, 6)
        prefs.addWidget(self.text("ОФОРМЛЕНИЕ ПРОГРАММЫ", "eyebrow"))
        themes_row = QHBoxLayout()
        self.theme_buttons = {}
        for key, theme in THEMES.items():
            button = QPushButton(theme["name"])
            button.setCheckable(True)
            button.setToolTip(theme["description"])
            button.clicked.connect(lambda _checked=False, name=key: self.set_theme(name))
            self.theme_buttons[key] = button
            themes_row.addWidget(button)
        prefs.addLayout(themes_row)
        self.theme_description = self.text("", "muted")
        prefs.addWidget(self.theme_description)
        prefs.addSpacing(8)
        prefs.addWidget(self.text("ГЛОБАЛЬНЫЕ КЛАВИШИ", "eyebrow"))
        self.main_key_panel = HotkeyPanel(self)
        prefs.addWidget(self.main_key_panel)
        local_help = self.text("В редакторе: Del — удалить выделенное; Ctrl+D — копия группы; "
                               "стрелки — сдвиг на 1 px, Shift+стрелки — на 10 px; Ctrl+F — поиск. "
                               "Удаление работает на макете и в списке показателей группы.", "muted")
        local_help.setWordWrap(True)
        prefs.addWidget(local_help)
        self.add_feature_ui(prefs)
        language_row = QHBoxLayout()
        language_row.addWidget(self.text("Язык интерфейса", "muted"))
        self.language_box = QComboBox()
        self.language_box.addItem("Русский", "ru")
        self.language_box.addItem("English", "en")
        self.language_box.currentIndexChanged.connect(lambda: self.set_language(self.language_box.currentData()))
        language_row.addWidget(self.language_box)
        language_row.addStretch()
        prefs.addLayout(language_row)
        updates_row = QHBoxLayout()
        self.update_check_button = QPushButton("Проверить обновления")
        self.update_check_button.clicked.connect(self.check_for_updates)
        updates_row.addWidget(self.update_check_button)
        self.update_status = self.text(f"Версия программы: {APP_VERSION}", "muted")
        updates_row.addWidget(self.update_status)
        updates_row.addStretch()
        prefs.addLayout(updates_row)
        self.main_preset_box.currentIndexChanged.connect(self.sync_main_preset)
        self.preset_box.currentIndexChanged.connect(self.sync_main_preset)
        self.refresh_presets()

        footer = QHBoxLayout()
        self.hotkey_hint = self.text("Ins • быстрое меню", "muted")
        footer.addWidget(self.hotkey_hint)
        footer.addStretch()
        quick = QPushButton("Быстрое меню")
        quick.clicked.connect(self.toggle_quick_settings)
        footer.addWidget(quick)
        start = QPushButton("Показать HUD")
        start.setObjectName("primary")
        start.clicked.connect(self.show_hud)
        footer.addWidget(start)
        outer.addLayout(footer)

    def set_language(self, language="ru", save=True):
        language = language if language in ("ru", "en") else "ru"
        self.settings.data["language"] = language
        QApplication.instance().setProperty("language", language)
        translations = {
            "ОЖИДАНИЕ ИГРЫ": "WAITING FOR GAME", "Тест": "Demo", "Обновить": "Update",
            "Скачать и установить": "Download and install",
            "Подключение к игре автоматически": "Connecting to the game automatically",
            "Самолёт определится в бою": "Aircraft will be detected in battle",
            "Модель ещё не получена из игры": "The game has not provided an aircraft model yet",
            "Данные появятся в бою": "Data appears in battle", "Сброс": "Reset",
            "Расположение": "Layout", "Вид текста": "Text style", "Самолёт": "Aircraft",
            "Вертолёт": "Helicopter", "Настройки": "Settings", "ПОКАЗАТЕЛИ": "METRICS",
            "Поиск · IAS, топливо…": "Search · IAS, fuel…", "Данные появятся в бою": "Data appears in battle",
            "ПРОФИЛЬ: ОБЩИЙ": "PROFILE: DEFAULT", "Макет": "Layout", "Применить": "Apply",
            "Сохранить": "Save", "Удалить": "Delete", "Быстрое меню": "Quick menu",
            "Показать HUD": "Show HUD", "Оформление выбранного текста": "Style selected text",
            "＋ Группа": "＋ Group", "ОФОРМЛЕНИЕ ПРОГРАММЫ": "APP APPEARANCE",
            "ГЛОБАЛЬНЫЕ КЛАВИШИ": "GLOBAL HOTKEYS", "Язык интерфейса": "Interface language",
            "Проверить обновления": "Check for updates", "ОБНОВЛЕНИЯ": "UPDATES",
            "Вписать": "Fit", "Выравнивание и привязка": "Alignment and snapping",
            "Инструменты макета": "Layout tools", "Показать сетку": "Show grid",
            "Сбросить расположение": "Reset layout", "Загрузить фон…": "Load background…",
            "Убрать фон": "Remove background", "Сохранить макет как…": "Save layout as…",
            "Импорт макета…": "Import layout…", "Экспорт макета…": "Export layout…",
            "Поведение HUD": "HUD behavior", "ПОВЕДЕНИЕ HUD": "HUD BEHAVIOR",
            "Скрывать HUD вне вылета": "Hide HUD outside a sortie",
            "Скрывать поверх других программ": "Hide when other apps are active",
            "Частота данных": "Data update rate", "Критический AoA": "Critical AoA",
            "ПРЕДУПРЕЖДЕНИЯ HUD": "HUD WARNINGS", "Скорость": "Speed", "Перегрузка": "G-load",
            "Топливо": "Fuel", "Сваливание": "Stall", "Раннее предупреждение": "Early warning",
            "Критическое топливо": "Critical fuel", "ЗВУКОВЫЕ ПРЕДУПРЕЖДЕНИЯ": "AUDIO WARNINGS",
            "Включить звук": "Enable sound", "Громкость": "Volume", "Пауза между сигналами": "Alert repeat delay",
            "Предупреждать о топливе за": "Warn about fuel with", "Прослушать": "Play",
            "Свой WAV…": "Custom WAV…", "Стандарт": "Default", "Стандартные сигналы": "Default sounds",
            "Профили": "Profiles", "ГОТОВЫЕ И СОХРАНЁННЫЕ МАКЕТЫ": "BUILT-IN AND SAVED LAYOUTS",
            "Сохранить как…": "Save as…", "Импорт…": "Import…", "Экспорт…": "Export…",
            "Сохранить изменения": "Save changes", "Удалить конфиг": "Delete config",
            "Восстановить выбранный стандартный макет": "Restore selected built-in layout",
            "ТЕСТ БЕЗ ЗАПУСКА ИГРЫ": "DEMO WITHOUT THE GAME", "Обычный полёт": "Normal flight",
            "Превышение скорости": "Overspeed", "Высокая перегрузка": "High G-load", "Мало топлива": "Low fuel",
            "Ракеты: направление угрозы недоступно в используемом локальном API.": "Missile direction is not available in the local API.",
            "Данные вертолёта появятся после входа в бой": "Helicopter data appears after entering battle",
            "Применить макет вертолёта": "Apply helicopter layout", "Добавить в группу": "Add to group",
            "ВЕРТОЛЁТ": "HELICOPTER", "Показать HUD": "Show HUD", "Перемещать текст мышью": "Move text with mouse",
            "Открыть редактор": "Open editor", "Готово · Esc": "Done · Esc", "Клавиши": "Hotkeys",
            "Оформление программы": "App appearance", "ОФОРМЛЕНИЕ ПРОГРАММЫ": "APP APPEARANCE",
            "Пределы самолёта": "Aircraft limits", "Автоматические пределы из базы": "Automatic limits from database",
            "Шрифт": "Font", "Размер": "Size", "Название": "Name", "Отображение": "Display",
            "Дополнительные настройки": "Additional settings", "Подписи": "Labels",
            "Название группы": "Group title", "Жирный": "Bold", "Тень текста": "Text shadow",
            "Обводка": "Outline", "Цвет значений": "Value color", "Цвет подписей": "Label color",
            "Цвет обводки": "Outline color", "Убрать показатель": "Remove metric",
            "Удалить группу": "Delete group", "Пределы самолёта": "Aircraft limits",
            "Принудительно обновить данные API": "Force refresh API data",
            "Версия программы: 1.0.8": "Application version: 1.0.8",
        }
        for widget in self.findChildren(QWidget):
            original = widget.property("wt_ru_text")
            if original is None:
                if isinstance(widget, (QLabel, QPushButton, QCheckBox)) and widget.text():
                    original = widget.text()
                    widget.setProperty("wt_ru_text", original)
                elif isinstance(widget, QLineEdit) and widget.placeholderText():
                    original = widget.placeholderText()
                    widget.setProperty("wt_ru_placeholder", original)
            if original is not None and isinstance(widget, (QLabel, QPushButton, QCheckBox)):
                widget.setText(original if language == "ru" else translations.get(original, original))
            placeholder = widget.property("wt_ru_placeholder")
            if placeholder is not None and isinstance(widget, QLineEdit):
                widget.setPlaceholderText(placeholder if language == "ru" else translations.get(placeholder, placeholder))
        tab_translations = {"Расположение": "Layout", "Вид текста": "Text style", "Самолёт": "Aircraft",
                            "Вертолёт": "Helicopter", "Настройки": "Settings"}
        for index in range(self.tabs.count()):
            ru = self.tabs.tabBar().tabData(index) or self.tabs.tabText(index)
            if self.tabs.tabBar().tabData(index) is None:
                self.tabs.tabBar().setTabData(index, ru)
            self.tabs.setTabText(index, ru if language == "ru" else tab_translations.get(ru, ru))
        if hasattr(self, "language_box"):
            self.language_box.blockSignals(True)
            self.language_box.setCurrentIndex(self.language_box.findData(language))
            self.language_box.blockSignals(False)
        if save:
            self.settings.save()
        if hasattr(self, "palette"):
            self.refresh_palette()

    def check_for_updates(self, silent=False):
        if self.update_checker and self.update_checker.isRunning():
            return
        if not silent:
            self.update_status.setText("Проверка GitHub…")
        self.update_button.setEnabled(False)
        if hasattr(self, "update_check_button"):
            self.update_check_button.setEnabled(False)
        self.update_checker = UpdateChecker()
        self.update_checker.completed.connect(lambda info, error, quiet=silent: self.on_update_checked(info, error, quiet))
        self.update_checker.start()

    @staticmethod
    def _version_tuple(value):
        try:
            return tuple(int(part) for part in str(value).lstrip("vV").split(".")[:3])
        except (TypeError, ValueError):
            return (0, 0, 0)

    def on_update_checked(self, info, error, silent=False):
        self.update_button.setEnabled(True)
        if hasattr(self, "update_check_button"):
            self.update_check_button.setEnabled(True)
        if error or not info:
            if not silent:
                self.update_status.setText("Не удалось проверить обновления")
                QMessageBox.warning(self, "Проверка обновлений", "GitHub недоступен. Проверьте интернет-соединение.")
            return
        latest = info.get("version", "")
        if self._version_tuple(latest) <= self._version_tuple(APP_VERSION):
            self.update_status.setText(f"Установлена последняя версия · {APP_VERSION}")
            if not silent:
                QMessageBox.information(self, "Обновления", f"У вас уже последняя версия {APP_VERSION}.")
            return
        self.update_status.setText(f"Доступна версия {latest}")
        if self.settings.data.get("updates_skip_version") == latest:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Доступно обновление")
        box.setText(f"Доступна новая версия WT Flight: {latest}\nТекущая версия: {APP_VERSION}")
        box.setInformativeText("Скачайте установщик из GitHub. Он обновит программу в папке D:\\WT Flight.")
        skip = QCheckBox("Больше не напоминать об этой версии", box)
        box.setCheckBox(skip)
        download = box.addButton("Скачать и установить", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.exec()
        if skip.isChecked():
            self.settings.data["updates_skip_version"] = latest
            self.settings.save()
        if box.clickedButton() is download:
            self.download_and_install(info)

    def download_and_install(self, info):
        asset = info.get("asset")
        if not asset:
            QDesktopServices.openUrl(QUrl(info.get("url") or GITHUB_RELEASES))
            return
        filename = f"WT-Flight-Setup-{info.get('version', 'latest')}.exe"
        self.update_progress = QProgressDialog("Скачивание установщика…", "Отмена", 0, 100, self)
        self.update_progress.setWindowTitle("Обновление WT Flight")
        self.update_progress.setAutoClose(False)
        self.update_progress.setMinimumDuration(0)
        self.update_progress.show()
        self.installer_downloader = InstallerDownloader(asset, filename)
        self.installer_downloader.progress.connect(self.update_progress.setValue)
        self.installer_downloader.completed.connect(self.on_installer_downloaded)
        self.update_progress.canceled.connect(self.installer_downloader.terminate)
        self.installer_downloader.start()

    def on_installer_downloaded(self, path, error):
        if self.update_progress:
            self.update_progress.close()
        if error or not path or not Path(path).is_file():
            QMessageBox.warning(self, "Обновление", "Не удалось скачать установщик: " + (error or "файл не найден"))
            return
        answer = QMessageBox.question(
            self, "Установить обновление", "Установщик скачан. Закрыть WT Flight и запустить установку сейчас?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        try:
            subprocess.Popen([path], cwd=str(Path(path).parent))
            QTimer.singleShot(250, QApplication.instance().quit)
        except OSError as error:
            QMessageBox.warning(self, "Обновление", "Не удалось запустить установщик: " + str(error))

    def select_from_combo(self):
        self.select_group(self.group_selector.currentData())

    def update_aircraft_panel(self):
        limits = self.current_limits()
        aircraft = self.aircraft
        known = self.database.resolve(aircraft)
        self.aircraft_name.setText(self.database.display_name(aircraft) if aircraft != "default"
                                   else "Самолёт определится в бою")
        self.aircraft_details.setText(
            ("Определён автоматически · " + aircraft) if known else
            "Модель ещё не получена из игры" if aircraft == "default" else
            "Этой модели нет в базе · " + aircraft)
        for key, label in self.aircraft_values.items():
            value = limits.get(key)
            text = "—"
            if value is not None:
                if key.endswith("g"):
                    text = ("≈ " if limits.get("_g_estimate") else "") + f"{value:+.1f} G"
                elif key == "mach":
                    text = f"{value:.2f} M"
                else:
                    text = f"{value:.0f} км/ч"
            label.setText(text)
        notes = []
        if limits.get("_g_estimate"):
            notes.append("G рассчитана по пустой массе и текущему топливу; подвески и экипаж не учтены.")
        if limits.get("_sweep_conservative"):
            notes.append("Стреловидность неизвестна: для IAS / Mach взят минимальный предел из таблицы крыла.")
        if not notes:
            notes.append("Пределы загружаются автоматически при получении модели самолёта из игры.")
        self.limit_note.setText(" ".join(notes))
        if not self.db_updater or not self.db_updater.isRunning():
            self.database_note.setText(f"База {self.database.version} · {len(self.database.models)} моделей · {self.database_status}")

    def check_database_update(self):
        if self.db_updater and self.db_updater.isRunning():
            return
        self.database_update_button.setEnabled(False)
        self.database_note.setText(f"База {self.database.version} · проверка обновления…")
        self.db_updater = DatabaseUpdater(CONFIG_PATH.parent, self.database.version)
        self.db_updater.completed.connect(self.on_database_update)
        self.db_updater.start()

    def on_database_update(self, database, error):
        self.database_update_button.setEnabled(True)
        if database:
            self.database = database
        self.database_status = ("нет связи, локальная копия" if error else "последняя доступная версия")
        self.settings.data["database_checked_at"] = time.time()
        self.settings.save()
        if self.demo_active:
            self.demo_pulse()
        else:
            self.present_sample(*self.last_real_sample)
        self.database_note.setText(f"База {self.database.version} · {self.database_status}")
        self.database_note.setToolTip(error or "https://github.com/SpaceCapo/warthunder-byo-fm")

    def restore_background(self):
        preview = self.settings.data.get("preview", {})
        self.background_dim.setValue(int(preview.get("dimming", 22)))
        self.grid_action.setChecked(bool(preview.get("grid", False)))
        path = preview.get("image")
        packaged_default = Path(__file__).parents[1] / "resources" / "default_hud_background.png"
        default = packaged_default if packaged_default.exists() else Path(__file__).parents[2] / "data" / "default_hud_background.png"
        if path is None and default.is_file():
            self.load_background(str(default))
            return
        if path:
            self.canvas.set_background(QPixmap(path))
        self.remove_background_action.setEnabled(not self.canvas.background.isNull())

    def choose_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Фон предпросмотра — выберите скриншот", "",
                                            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.load_background(path)

    def load_background(self, path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, "Не удалось открыть фон", "Выберите изображение PNG, JPEG, WebP или BMP.")
            return False
        if image.width() > 2560 or image.height() > 2560:
            image = image.scaled(2560, 2560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        target = CONFIG_PATH.parent / "preview_background.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(str(target))
        if not output.open(QIODevice.WriteOnly) or not image.save(output, "PNG") or not output.commit():
            QMessageBox.warning(self, "Не удалось сохранить фон", "Не удалось сохранить изображение в папке настроек.")
            return False
        self.settings.data.setdefault("preview", {})["image"] = str(target)
        self.settings.save()
        self.canvas.set_background(QPixmap.fromImage(image))
        self.remove_background_action.setEnabled(True)
        return True

    def clear_background(self):
        self.settings.data.setdefault("preview", {})["image"] = ""
        self.settings.save()
        self.canvas.set_background(QPixmap())
        self.remove_background_action.setEnabled(False)

    def change_background_dimming(self, value):
        self.canvas.dimming = value
        self.canvas.viewport().update()
        self.settings.data.setdefault("preview", {})["dimming"] = value
        self.settings.save()

    def change_preview_grid(self, enabled):
        self.canvas.show_grid = enabled
        self.canvas.viewport().update()
        self.settings.data.setdefault("preview", {})["grid"] = enabled
        self.settings.save()

    def sync_group_selector(self):
        self.group_selector.blockSignals(True)
        self.group_selector.clear()
        for group in self.groups():
            self.group_selector.addItem(self.group_caption(group), group["id"])
        self.group_selector.setCurrentIndex(self.group_selector.findData(self.selected_id))
        self.group_selector.blockSignals(False)

    @staticmethod
    def group_caption(group):
        return " / ".join(HUD_LABELS.get(m, metric_label(m)) for m in group["metrics"])

    def build_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#57e0c3"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor("#0b1725"))
        painter.setFont(QFont("Segoe UI", 25, QFont.Bold))
        painter.drawText(QRect(0, 0, 64, 64), Qt.AlignCenter, "W")
        painter.end()
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        menu.addAction("Быстрое меню настроек", self.toggle_quick_settings)
        menu.addAction("Открыть редактор", self.open_editor)
        menu.addAction("Показать / скрыть HUD", self.toggle_hud)
        menu.addSeparator()
        menu.addAction("Выход", self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_editor()
                            if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def refresh_palette(self):
        if not hasattr(self, "palette"):
            return
        query = self.search.text().casefold()
        ids = self.available if self.available is not None else list(METRICS)
        count = self.palette.populate(ids, query)
        self.metric_count.setText(str(count))
        self.palette_hint.setText("Ничего не найдено" if count == 0 else
                                 "Доступно на этом самолёте" if self.available is not None else
                                 "В бою список обновится автоматически")

    def refresh_layout(self):
        self.profile_label.setText("ПРОФИЛЬ: " + (self.aircraft if self.aircraft != "default" else "ОБЩИЙ"))
        self.canvas.set_groups(self.groups())
        self.canvas.set_sample(self.sample, self.current_limits())
        self.sync_group_selector()
        self.select_group(self.selected_id, preserve_selection=True)
        self.rebuild_overlays()
        if hasattr(self, "quick_settings") and self.quick_settings.isVisible():
            self.quick_settings.sync()

    def select_group(self, group_id, preserve_selection=False):
        group_id = group_id or None
        self.selected_id = group_id
        if not preserve_selection or group_id not in self.canvas.selected_ids:
            self.canvas.select(group_id)
        self.group_selector.blockSignals(True)
        self.group_selector.setCurrentIndex(self.group_selector.findData(group_id))
        self.group_selector.blockSignals(False)
        group = self.selected_group()
        self.loading_inspector = True
        self.group_metrics.clear()
        if group:
            self.inspector_note.setText("Изменения сразу применяются к HUD и сохраняются.")
            self.title_edit.setText(group.get("title", ""))
            self.style_box.setCurrentIndex(0 if group.get("style") == "text" else 1)
            self.labels_check.setChecked(bool(group.get("labels", True)))
            self.title_check.setChecked(bool(group.get("title_visible", False)))
            self.size_slider.setValue(int(group.get("size", 20)))
            self.font_box.setCurrentText(group.get("font_family", "Consolas"))
            self.spacing_spin.setValue(group.get("spacing", 1))
            self.compact_check.setChecked(group.get("compact_labels", True))
            self.bold_check.setChecked(group.get("bold", True))
            self.shadow_check.setChecked(group.get("shadow", True))
            self.outline_check.setChecked(group.get("outline", True))
            self.hud_style_box.blockSignals(True)
            self.hud_style_box.setCurrentIndex(self.hud_style_box.findData(group.get("hud_style", "wtrti")))
            self.hud_style_box.blockSignals(False)
            for metric_id in group.get("metrics", []):
                self.group_metrics.addItem(metric_label(metric_id))
        else:
            self.inspector_note.setText("Выберите блок на макете, чтобы изменить его вид.")
            self.title_edit.clear()
        self.loading_inspector = False

    def apply_inspector(self, *_args):
        if self.loading_inspector:
            return
        group = self.selected_group()
        if not group:
            return
        group.update(title=self.title_edit.text().strip() or "БЛОК",
                     style=self.style_box.currentData(), labels=self.labels_check.isChecked(),
                     title_visible=self.title_check.isChecked(), size=self.size_slider.value(),
                     font_family=self.font_box.currentText(),
                     spacing=self.spacing_spin.value(), compact_labels=self.compact_check.isChecked(),
                     bold=self.bold_check.isChecked(), shadow=self.shadow_check.isChecked(),
                     outline=self.outline_check.isChecked())
        if self.sender() in (self.font_box, self.bold_check, self.shadow_check, self.outline_check):
            group["hud_style"] = "custom"
            self.hud_style_box.blockSignals(True)
            self.hud_style_box.setCurrentIndex(-1)
            self.hud_style_box.blockSignals(False)
        field = {self.size_slider: "size", self.font_box: "font_family", self.style_box: "style",
                 self.spacing_spin: "spacing", self.labels_check: "labels", self.title_check: "title_visible",
                 self.compact_check: "compact_labels", self.bold_check: "bold",
                 self.shadow_check: "shadow", self.outline_check: "outline"}.get(self.sender())
        if field:
            for selected in self.groups():
                if selected["id"] in self.canvas.selected_ids:
                    selected[field] = group[field]
                    if field in ("font_family", "bold", "shadow", "outline"):
                        selected["hud_style"] = "custom"
        self.settings.save()
        self.canvas.set_sample(self.sample, self.current_limits())
        self.update_overlays()

    def choose_color(self, key):
        group = self.selected_group()
        if not group:
            return
        color = QColorDialog.getColor(QColor(group.get(key, INK)), self, "Цвет HUD")
        if color.isValid():
            group[key] = color.name()
            if key in ("color", "accent", "outline_color"):
                group["hud_style"] = "custom"
                self.hud_style_box.blockSignals(True)
                self.hud_style_box.setCurrentIndex(-1)
                self.hud_style_box.blockSignals(False)
            self.settings.save()
            self.canvas.set_sample(self.sample, self.current_limits())
            self.update_overlays()

    def apply_hud_style(self, *_):
        if self.loading_inspector:
            return
        group = self.selected_group()
        key = self.hud_style_box.currentData()
        if not group or key not in HUD_STYLES:
            return
        values = copy.deepcopy(HUD_STYLES[key])
        values.pop("name", None)
        values["hud_style"] = key
        for target in self.groups():
            if target["id"] in self.canvas.selected_ids or target is group:
                target.update(values)
        self.loading_inspector = True
        self.font_box.setCurrentText(group["font_family"])
        self.bold_check.setChecked(group["bold"])
        self.shadow_check.setChecked(group["shadow"])
        self.outline_check.setChecked(group["outline"])
        self.loading_inspector = False
        self.layout_changed()

    def create_group(self, metric_id, x, y):
        group = new_group(metric_id, max(0, min(0.85, x)), max(0, min(0.85, y)))
        group["title"] = metric_label(metric_id)
        self.groups().append(group)
        self.selected_id = group["id"]
        self.layout_changed()

    def create_empty_group(self):
        """Create a visible drop target without forcing an unrelated metric into it."""
        index = len(self.groups())
        group = new_group("ias", 0.08 + (index // 6 % 3) * 0.24, 0.10 + (index % 6) * 0.12)
        group.update(title="НОВАЯ ГРУППА", metrics=[], title_visible=True)
        self.groups().append(group)
        self.selected_id = group["id"]
        self.layout_changed()

    def add_to_group(self, group_id, metric_id):
        group = next((g for g in self.groups() if g["id"] == group_id), None)
        if group and metric_id not in group["metrics"]:
            group["metrics"].append(metric_id)
            self.selected_id = group_id
            self.layout_changed()

    def add_metric_from_catalog(self, metric_id):
        index = len(self.groups())
        self.create_group(metric_id, 0.08 + (index // 6 % 3) * 0.24, 0.10 + (index % 6) * 0.12)

    def remove_metric(self):
        group = self.selected_group()
        row = self.group_metrics.currentRow()
        if not group or row < 0:
            return
        group["metrics"].pop(row)
        if not group["metrics"]:
            self.groups().remove(group)
            self.selected_id = None
        self.layout_changed()

    def delete_group(self):
        ids = set(self.canvas.selected_ids)
        if not ids and self.selected_id:
            ids.add(self.selected_id)
        if ids:
            self.groups()[:] = [group for group in self.groups() if group["id"] not in ids]
            self.selected_id = None
            self.layout_changed()

    def layout_changed(self):
        self.settings.save()
        self.refresh_layout()

    def reset_layout(self):
        self.settings.data["profiles"][self.aircraft] = default_profile()
        self.selected_id = self.groups()[0]["id"]
        self.layout_changed()

    def edit_limits(self):
        dialog = LimitsDialog(self, self.aircraft, self.settings.limits(self.aircraft))
        if dialog.exec() == QDialog.Accepted:
            self.settings.data.setdefault("limits", {})[self.aircraft] = dialog.values
            self.settings.save()
            self.canvas.set_sample(self.sample, self.current_limits())
            self.update_overlays()
            self.update_aircraft_panel()

    def on_sample(self, mode, state, indicators):
        self.last_real_sample = (mode, state, indicators)
        if not self.demo_active:
            self.present_sample(mode, state, indicators)

    def present_sample(self, mode, state, indicators):
        state = dict(state)
        flight = self.settings.data.get("flight", {})
        state["_fuel_minutes"] = flight.get("fuel_minutes", 3)
        state["_aoa_limit"] = flight.get("aoa_limit", 15)
        state["_warning_ratio"] = flight.get("warning_ratio", 90) / 100
        state["_warning_categories"] = dict(flight.get("warning_categories", {}))
        state["_fuel_critical_seconds"] = flight.get("fuel_critical_seconds", 60)
        if mode == "live":
            state.update(self.fuel_estimator.update(str(indicators.get("type") or ""), state.get("Mfuel, kg"), time.monotonic()))
        elif mode != "demo":
            self.fuel_estimator.reset()
        self.sample = (mode, state, indicators)
        if mode in ("live", "demo"):
            aircraft = self.aircraft if mode == "demo" else normalized_id(indicators.get("type")) or "default"
            if aircraft != self.aircraft:
                self.aircraft = aircraft
                self.settings.groups(aircraft)
                self.selected_id = self.groups()[0]["id"] if self.groups() else None
                self.refresh_layout()
            add_margins(state, self.current_limits())
            available = available_metrics(state, indicators, self.current_limits())
            if available != self.available:
                self.available = available
                self.refresh_palette()
            self.status.setText("ТЕСТ · ПРИМЕР ДАННЫХ" if mode == "demo" else "В БОЮ  ·  LIVE")
            self.status.setProperty("offline", False)
            self.plane_label.setText(self.database.display_name(aircraft) if aircraft != "default" else "Самолёт не определён")
        else:
            if self.available is not None:
                self.available = None
                self.refresh_palette()
            self.status.setText("ОЖИДАНИЕ БОЯ" if mode == "waiting" else "ИГРА НЕ НАЙДЕНА")
            self.status.setProperty("offline", True)
            self.plane_label.setText("Подключение к 127.0.0.1:8111 автоматически")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.canvas.set_sample(self.sample, self.current_limits())
        self.update_overlays()
        self.update_aircraft_panel()
        self.update_helicopter_panel()
        self.process_audio()

    def rebuild_overlays(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = [OverlayWindow(group, self.target_screen) for group in self.groups()]
        for overlay in self.overlays:
            overlay.selected.connect(self.select_live_group)
            overlay.moved.connect(self.save_overlay_position)
            overlay.set_editing(self.overlay_editing)
        self.update_overlays()

    def select_live_group(self, group_id):
        self.select_group(group_id)
        if hasattr(self, "quick_settings"):
            self.quick_settings.sync()

    def save_overlay_position(self):
        self.settings.save()
        self.canvas.position_views()

    def set_overlay_editing(self, editing):
        if self.overlay_editing and not editing:
            self.settings.save()
        self.overlay_editing = editing
        if editing:
            self.hud_visible = True
        for overlay in self.overlays:
            overlay.set_editing(editing)
        self.update_overlays()
        if hasattr(self, "quick_settings"):
            self.quick_settings.visible_check.blockSignals(True)
            self.quick_settings.visible_check.setChecked(self.hud_visible)
            self.quick_settings.visible_check.blockSignals(False)

    def toggle_quick_settings(self):
        if self.quick_settings.isVisible():
            self.quick_settings.hide()
        else:
            self.quick_settings.sync()
            screen = QApplication.primaryScreen().availableGeometry()
            self.quick_settings.adjustSize()
            self.quick_settings.move(screen.center() - self.quick_settings.rect().center())
            self.quick_settings.show()
            self.quick_settings.raise_()
            self.quick_settings.activateWindow()
            self.quick_settings.visible_check.setFocus()

    def update_overlays(self):
        visible = self.should_show_hud()
        for overlay in self.overlays:
            overlay.set_sample(self.sample, self.current_limits())
            overlay.place()
            if visible and overlay.lines():
                overlay.show()
            else:
                overlay.hide()
        if hasattr(self, "demo_badge"):
            self.demo_badge.setVisible(visible and self.demo_active)

    def show_hud(self):
        self.hud_visible = True
        self.quick_settings.hide()
        self.hide()
        self.update_overlays()

    def toggle_hud(self):
        self.hud_visible = not self.hud_visible
        if not self.hud_visible:
            self.set_overlay_editing(False)
        self.update_overlays()
        if self.quick_settings.isVisible():
            self.quick_settings.sync()

    def open_editor(self):
        self.quick_settings.hide()
        self.hud_visible = False
        self.update_overlays()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.show_hud()

    def exit_app(self):
        self.close_hotkeys()
        self.telemetry.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def stop_workers(self):
        self.stop_feature_timers()
        self.telemetry.stop()
        if self.db_updater:
            self.db_updater.wait(20000)


def main():
    app = QApplication([])
    app.setApplicationName("WT Flight")
    app.setApplicationVersion("1.0.0")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "data" / "wt-flight.ico")))
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    app.aboutToQuit.connect(window.stop_workers)
    app.aboutToQuit.connect(window.close_hotkeys)
    app.exec()
