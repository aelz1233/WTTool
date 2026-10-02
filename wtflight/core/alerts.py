"""Limit margins, risk ratios and the warning text shown on the HUD."""

from wtflight.core.metrics import number


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
            if seconds is not None and seconds <= fuel_minutes * 60:
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


def evaluate(ias, load, positive_limit, negative_limit, speed_limit, caution_ratio=.9):
    if ias is None and load is None:
        return "unset", "Нет данных IAS и перегрузки"
    critical, caution = [], []
    if load is not None and positive_limit is not None:
        if load >= positive_limit:
            critical.append("ПРЕДЕЛ +G")
        elif load >= positive_limit * caution_ratio:
            caution.append("Близко к пределу +G")
    if load is not None and negative_limit is not None:
        if load <= negative_limit:
            critical.append("ПРЕДЕЛ −G")
        elif load <= negative_limit * caution_ratio:
            caution.append("Близко к пределу −G")
    if ias is not None and speed_limit is not None:
        if ias >= speed_limit:
            critical.append("ПРЕДЕЛ IAS")
        elif ias >= speed_limit * caution_ratio:
            caution.append("Близко к пределу IAS")
    if critical:
        return "critical", " · ".join(critical)
    if caution:
        return "caution", " · ".join(caution)
    if all(v is None for v in (positive_limit, negative_limit, speed_limit)):
        return "unset", "Пределы не настроены"
    return "normal", "В пределах заданных значений"


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
