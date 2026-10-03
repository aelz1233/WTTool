"""Layout history, fuel estimation, portable profiles and alert calculations."""
import copy
import math
import re
import uuid
from collections import deque

from wtflight.core.metrics import METRICS, engine_metric_parts, number


class LayoutHistory:
    def __init__(self):
        self.states = {}
        self.future = {}

    def record(self, profiles):
        for key, groups in profiles.items():
            past = self.states.setdefault(key, [])
            if not past or past[-1] != groups:
                past.append(copy.deepcopy(groups))
                del past[:-100]
                self.future[key] = []

    def undo(self, key):
        past = self.states.get(key, [])
        if len(past) < 2:
            return None
        self.future.setdefault(key, []).append(past.pop())
        return copy.deepcopy(past[-1])

    def redo(self, key):
        future = self.future.get(key, [])
        if not future:
            return None
        groups = future.pop()
        self.states[key].append(copy.deepcopy(groups))
        return copy.deepcopy(groups)


class FuelEstimator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = deque()
        self.rate = None
        self.aircraft = None

    def update(self, aircraft, fuel, now):
        fuel = number(fuel)
        if fuel is None or fuel < 0 or aircraft != self.aircraft:
            self.reset()
            self.aircraft = aircraft
        if fuel is None or fuel < 0:
            return {}
        if self.samples:
            dt = now - self.samples[-1][0]
            drop = self.samples[-1][1] - fuel
            # Restart on refuelling, stale data, a new sortie or implausible jettison spikes.
            if dt <= 0 or dt > 3 or drop < -.5 or drop > max(15, dt * 100):
                self.samples.clear()
                self.rate = None
        self.samples.append((now, fuel))
        while len(self.samples) > 1 and now - self.samples[0][0] > 8:
            self.samples.popleft()
        elapsed = now - self.samples[0][0]
        if elapsed < 3:
            return {}
        raw = max(0, (self.samples[0][1] - fuel) / elapsed)
        dt = now - self.samples[-2][0] if len(self.samples) > 1 else 0
        alpha = 1 - math.exp(-dt / 4)
        self.rate = raw if self.rate is None else self.rate + alpha * (raw - self.rate)
        # An unchanged quantity for the complete observation window means no estimate.
        if raw < .0001:
            self.rate = 0
        result = {"fuel_flow": self.rate * 60}
        if self.rate > .005:
            result["fuel_seconds"] = fuel / self.rate
        return result


def add_margins(state, limits):
    for metric, current, threshold in (("ias_margin", "IAS, km/h", "ias_kmh"),
                                        ("mach_margin", "M", "mach"),
                                        ("g_margin_pos", "Ny", "positive_g")):
        value, maximum = number(state.get(current)), number(limits.get(threshold))
        if value is not None and maximum is not None:
            state[metric] = maximum - value
    load, minimum = number(state.get("Ny")), number(limits.get("negative_g"))
    if load is not None and minimum is not None:
        state["g_margin_neg"] = load - minimum


def metric_risk(metric, state, limits, fuel_minutes=3):
    pairs = {"ias": ("IAS, km/h", "ias_kmh"), "ias_margin": ("IAS, km/h", "ias_kmh"),
             "mach": ("M", "mach"), "mach_margin": ("M", "mach")}
    if metric in pairs:
        key, limit_key = pairs[metric]
        value, limit = number(state.get(key)), number(limits.get(limit_key))
        return value / limit if value is not None and limit and limit > 0 else None
    if metric in ("g", "g_margin_pos", "g_margin_neg"):
        value = number(state.get("Ny"))
        limit_key = {"g_margin_pos": "positive_g", "g_margin_neg": "negative_g"}.get(metric)
        if limit_key is None:
            limit_key = "positive_g" if value is not None and value >= 0 else "negative_g"
        limit = number(limits.get(limit_key))
        return max(0, value / limit) if value is not None and limit else None
    if metric in ("fuel", "fuel_percent", "fuel_time", "fuel_flow"):
        seconds = number(state.get("fuel_seconds"))
        return max(0, 1 - (seconds - 60) / max(1, fuel_minutes * 60 - 60) * .15) if seconds is not None else None
    if metric == "aoa":
        value, limit = abs(number(state.get("AoA, deg")) or 0), number(state.get("_aoa_limit"))
        return value / limit if limit and limit > 0 else None
    return None


def alert_levels(state, limits, fuel_minutes=3, aoa_limit=15, caution_ratio=.9,
                 fuel_critical_seconds=60, categories=None):
    result = {}
    categories = categories or {}
    for name, metrics in (("speed", ("ias", "mach")), ("g", ("g",)), ("fuel", ("fuel_time",))):
        if not categories.get(name, True):
            continue
        ratios = [metric_risk(m, state, limits, fuel_minutes) for m in metrics]
        ratio = max((v for v in ratios if v is not None), default=0)
        if name == "fuel":
            seconds = number(state.get("fuel_seconds"))
            if seconds is not None and seconds <= max(fuel_minutes * 60, fuel_critical_seconds):
                result[name] = "critical" if seconds <= fuel_critical_seconds else "caution"
            continue
        threshold = caution_ratio
        if ratio >= threshold:
            result[name] = "critical" if ratio >= 1 else "caution"
    aoa = abs(number(state.get("AoA, deg")) or 0)
    if categories.get("stall", True) and aoa_limit and aoa >= aoa_limit * caution_ratio:
        result["stall"] = "critical" if aoa >= aoa_limit else "caution"
    return result


class AlertCooldown:
    def __init__(self):
        self.last = {}

    def choose(self, levels, now, interval, enabled):
        priority = {"stall": 0, "speed": 1, "g": 2, "fuel": 3}
        for key in sorted(levels, key=lambda k: (levels[k] != "critical", priority.get(k, 99), k)):
            if not enabled.get(key, True):
                continue
            last_time, last_level = self.last.get(key, (-1e9, ""))
            if now - last_time >= interval or (levels[key] == "critical" and last_level != "critical"):
                self.last[key] = (now, levels[key])
                return key
        return None


def validate_profile(payload):
    if not isinstance(payload, dict) or payload.get("format") != "wt-flight-profile" or payload.get("version") != 1:
        raise ValueError("Это не профиль WT Flight версии 1")
    groups = payload.get("groups")
    if not isinstance(groups, list) or not 0 <= len(groups) <= 100:
        raise ValueError("В профиле может быть до 100 групп")
    clean = []
    for source in groups:
        if not isinstance(source, dict):
            raise ValueError("Неверный формат группы")
        metrics = source.get("metrics")
        if not isinstance(metrics, list) or not 0 <= len(metrics) <= 60:
            raise ValueError("Неверный список показателей")
        if any(not isinstance(m, str) or len(m) > 160 or
               (m not in METRICS and not engine_metric_parts(m) and not m.startswith(("state:", "indicators:"))) for m in metrics):
            raise ValueError("Неизвестный показатель в профиле")
        g = {"id": uuid.uuid4().hex[:10], "metrics": list(dict.fromkeys(metrics)),
             "title": str(source.get("title", "Группа"))[:60],
             "font_family": str(source.get("font_family", "Consolas"))[:80]}
        for key, fallback, low, high in (("x", .1, 0, 1), ("y", .1, 0, 1),
                                         ("size", 18, 10, 48), ("spacing", 1, 0, 16)):
            value = number(source.get(key, fallback))
            if value is None or not low <= value <= high:
                raise ValueError(f"Некорректное значение {key}")
            g[key] = int(value) if key in ("size", "spacing") else value
        for key, fallback in (("labels", True), ("title_visible", False), ("bold", True),
                               ("shadow", True), ("compact_labels", True), ("outline", True)):
            g[key] = bool(source.get(key, fallback))
        label_map = source.get("label_map", {})
        if not isinstance(label_map, dict) or len(label_map) > 60 or any(
        not isinstance(key, str) or len(key) > 160 or (key not in METRICS and not engine_metric_parts(key) and not key.startswith(("state:", "indicators:"))) or
                not isinstance(value, str) or len(value) > 16 for key, value in label_map.items()):
            raise ValueError("Неверные сокращённые подписи показателей")
        g["label_map"] = dict(label_map)
        for key, fallback in (("color", "#64be98"), ("accent", "#64be98"),
                              ("outline_color", "#07140f")):
            value = source.get(key, fallback)
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("Неверный цвет")
            g[key] = value
        outline_width = number(source.get("outline_width", 1.5))
        if outline_width is None or not .5 <= outline_width <= 4:
            raise ValueError("Неверная толщина обводки")
        g["outline_width"] = outline_width
        hud_style = source.get("hud_style", "custom")
        g["hud_style"] = hud_style if isinstance(hud_style, str) and len(hud_style) <= 24 else "custom"
        g["style"] = "panel" if source.get("style") == "panel" else "text"
        clean.append(g)
    return clean
