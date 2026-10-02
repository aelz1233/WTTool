"""HUD group model: compact labels, built-in layouts and validation of imported profiles."""

import re
import uuid

from wtflight.core.metrics import ENGINE_FIELDS, METRICS, engine_metric_parts, metric_label, number

HUD_GREEN = "#64be98"


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
        if not isinstance(metrics, list) or not 1 <= len(metrics) <= 60:
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
