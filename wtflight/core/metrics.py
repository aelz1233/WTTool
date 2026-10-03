"""Telemetry fields, warnings and persistent overlay settings."""

from __future__ import annotations

import math
import re

from wtflight.paths import CONFIG_PATH as CONFIG_PATH

# id: (section, label, source, API key, format)
METRICS = {
    "ias": ("Полёт", "IAS", "state", "IAS, km/h", "{:.0f} км/ч"),
    "tas": ("Полёт", "TAS", "state", "TAS, km/h", "{:.0f} км/ч"),
    "mach": ("Полёт", "Число Маха", "state", "M", "{:.2f} M"),
    "altitude": ("Полёт", "Высота", "state", "H, m", "{:.0f} м"),
    "g": ("Полёт", "Перегрузка", "state", "Ny", "{:+.1f} G"),
    "climb": ("Полёт", "Вертикальная скорость", "state", "Vy, m/s", "{:+.1f} м/с"),
    "aoa": ("Полёт", "Угол атаки", "state", "AoA, deg", "{:+.1f}°"),
    "aos": ("Полёт", "Угол скольжения", "state", "AoS, deg", "{:+.1f}°"),
    "fuel": ("Топливо и двигатель", "Топливо", "state", "Mfuel, kg", "{:.0f} кг"),
    "fuel_percent": ("Топливо и двигатель", "Топливо от старта", "derived", "fuel_percent", "{:.0f} %"),
    "fuel_time": ("Топливо и двигатель", "Топливо: время (оценка)", "state", "fuel_seconds", "{}"),
    "fuel_flow": ("Топливо и двигатель", "Расход топлива (оценка)", "state", "fuel_flow", "{:.1f} кг/мин"),
    "ias_margin": ("Запас до предела", "Запас IAS", "state", "ias_margin", "{:+.0f} км/ч"),
    "mach_margin": ("Запас до предела", "Запас Mach", "state", "mach_margin", "{:+.2f} M"),
    "g_margin_pos": ("Запас до предела", "Запас +G (оценка)", "state", "g_margin_pos", "{:+.1f} G"),
    "g_margin_neg": ("Запас до предела", "Запас −G (оценка)", "state", "g_margin_neg", "{:+.1f} G"),
    "throttle": ("Топливо и двигатель", "Газ, все двигатели", "state", "throttle 1, %", "{:.0f} %"),
    "rpm": ("Топливо и двигатель", "Обороты, все двигатели", "state", "RPM 1", "{:.0f} об/мин"),
    "oil_temp": ("Топливо и двигатель", "Масло, все двигатели", "state", "oil temp 1, C", "{:.0f} °C"),
    "water_temp": ("Топливо и двигатель", "Охлаждающая жидкость, все двигатели", "state", "water temp 1, C", "{:.0f} °C"),
    "power": ("Топливо и двигатель", "Мощность, все двигатели", "state", "power 1, hp", "{:.0f} л.с."),
    "thrust": ("Топливо и двигатель", "Тяга, все двигатели", "state", "thrust 1, kgs", "{:.0f} кгс"),
    "manifold": ("Топливо и двигатель", "Давление во впуске, все двигатели", "state", "manifold pressure 1, atm", "{:.2f} атм"),
    "mixture": ("Топливо и двигатель", "Смесь, все двигатели", "state", "mixture 1, %", "{:.0f} %"),
    "radiator": ("Топливо и двигатель", "Радиатор, все двигатели", "state", "radiator 1, %", "{:.0f} %"),
    "pitch": ("Топливо и двигатель", "Шаг винта, все двигатели", "state", "pitch 1, deg", "{:.1f}°"),
    "efficiency": ("Топливо и двигатель", "КПД винта, все двигатели", "state", "efficiency 1, %", "{:.0f} %"),
    "flaps": ("Конфигурация", "Закрылки", "state", "flaps, %", "{:.0f} %"),
    "gear": ("Конфигурация", "Шасси", "state", "gear, %", "{:.0f} %"),
    "airbrake": ("Конфигурация", "Воздушный тормоз", "state", "airbrake, %", "{:.0f} %"),
    "heading": ("Навигация", "Курс", "indicators", "compass", "{:.0f}°"),
    "limit_ias": ("Пределы самолёта", "Предельная IAS", "limits", "ias_kmh", "{:.0f} км/ч"),
    "limit_mach": ("Пределы самолёта", "Предельное число Маха", "limits", "mach", "{:.2f} M"),
    "limit_pos_g": ("Пределы самолёта", "Предел +G (оценка)", "limits", "positive_g", "{:+.1f} G"),
    "limit_neg_g": ("Пределы самолёта", "Предел −G (оценка)", "limits", "negative_g", "{:+.1f} G"),
    "limit_gear": ("Пределы самолёта", "Предельная скорость шасси", "limits", "gear_kmh", "{:.0f} км/ч"),
    "limit_flaps": ("Пределы самолёта", "Предел посадочных закрылков", "limits", "flaps_landing_kmh", "{:.0f} км/ч"),
    "warning": ("Система", "Предупреждения", "special", "warning", "{}"),
}

# Short in-app explanations shown when a HUD row is hovered.
METRIC_HELP = {
    "ias": "Приборная скорость относительно набегающего потока. Помогает следить за сваливанием и ограничением скорости самолёта.",
    "tas": "Истинная скорость относительно воздуха. Полезна для оценки перемещения и сохранения энергии.",
    "mach": "Отношение скорости самолёта к скорости звука. На больших значениях растут эффекты сжимаемости и нагрузка на конструкцию.",
    "altitude": "Высота над уровнем моря по данным игры. Нужна для выбора высоты боя и контроля набора или снижения.",
    "g": "Текущая перегрузка. Помогает контролировать нагрузку на самолёт и риск потери сознания пилотом.",
    "climb": "Вертикальная скорость: набор высоты или снижение в метрах в секунду.",
    "aoa": "Угол между продольной осью самолёта и набегающим потоком. Большой угол может привести к сваливанию.",
    "aos": "Угол бокового скольжения. Показывает, насколько самолёт летит боком относительно потока.",
    "fuel": "Оставшаяся масса топлива. Помогает оценить, сколько времени можно продолжать бой.",
    "fuel_percent": "Оценка оставшегося топлива в процентах от начального запаса.",
    "fuel_time": "Оценка времени до выработки топлива по текущему расходу.",
    "fuel_flow": "Оценочный расход топлива в килограммах в минуту.",
    "ias_margin": "Разница между текущей IAS и расчётным пределом скорости. Отрицательный запас означает превышение.",
    "mach_margin": "Разница между текущим числом Маха и расчётным пределом.",
    "g_margin_pos": "Оценка запаса до положительного предела перегрузки.",
    "g_margin_neg": "Оценка запаса до отрицательного предела перегрузки.",
    "throttle": "Положение управления тягой каждого доступного двигателя в процентах.",
    "rpm": "Обороты каждого доступного двигателя. Помогают заметить изменение режима работы двигателя.",
    "oil_temp": "Температура масла каждого доступного двигателя. Следите за ней, чтобы не допустить перегрева.",
    "water_temp": "Температура охлаждающей жидкости каждого двигателя, если она есть у самолёта.",
    "power": "Расчётная мощность каждого двигателя в лошадиных силах, если игра передаёт это значение.",
    "thrust": "Текущая тяга каждого двигателя в килограммах силы. Особенно полезна для реактивных самолётов.",
    "manifold": "Давление во впускном коллекторе поршневых двигателей.",
    "mixture": "Положение регулятора топливной смеси поршневого двигателя.",
    "radiator": "Степень открытия радиатора. Открытый радиатор улучшает охлаждение, но увеличивает сопротивление.",
    "pitch": "Угол установки лопастей винта каждого двигателя.",
    "efficiency": "Эффективность воздушного винта каждого двигателя.",
    "flaps": "Положение закрылков. Закрылки меняют подъёмную силу и сопротивление; на высокой скорости могут быть повреждены.",
    "gear": "Положение шасси. Выпуск на высокой скорости может повредить шасси.",
    "airbrake": "Положение воздушного тормоза. Увеличивает сопротивление и помогает быстро снизить скорость.",
    "heading": "Курс самолёта в градусах относительно севера.",
    "limit_ias": "Оценочный предельный порог приборной скорости для текущего самолёта.",
    "limit_mach": "Оценочный предел числа Маха для текущего самолёта.",
    "limit_pos_g": "Оценочный предел положительной перегрузки. Значение может зависеть от состояния самолёта.",
    "limit_neg_g": "Оценочный предел отрицательной перегрузки. Значение может зависеть от состояния самолёта.",
    "limit_gear": "Оценка скорости, выше которой выпуск шасси может быть небезопасен.",
    "limit_flaps": "Оценка предельной скорости для посадочных закрылков.",
    "warning": "Предупреждение о приближении к доступным пределам скорости, перегрузки или запаса топлива.",
}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


# The local API numbers engine data from 1 upwards (for example ``RPM 2``).
# A regular metric in METRICS means "all engines"; ``engine:power:2`` pins an
# individual row when a pilot wants a dedicated location for one engine.
ENGINE_FIELDS = {
    "throttle": ("throttle {n}, %", "THR", "Положение газа"),
    "rpm": ("RPM {n}", "RPM", "Обороты"),
    "oil_temp": ("oil temp {n}, C", "OIL", "Температура масла"),
    "water_temp": ("water temp {n}, C", "WATER", "Температура охлаждающей жидкости"),
    "power": ("power {n}, hp", "PWR", "Мощность"),
    "thrust": ("thrust {n}, kgs", "TRST", "Тяга"),
    "manifold": ("manifold pressure {n}, atm", "MAP", "Давление во впуске"),
    "mixture": ("mixture {n}, %", "MIX", "Топливная смесь"),
    "radiator": ("radiator {n}, %", "RAD", "Радиатор"),
    "pitch": ("pitch {n}, deg", "PITCH", "Шаг винта"),
    "efficiency": ("efficiency {n}, %", "EFF", "КПД винта"),
}


def engine_metric_parts(metric_id):
    """Return (kind, number) for an individual engine field, otherwise None."""
    match = re.fullmatch(r"engine:([a-z_]+):([1-9][0-9]?)", metric_id)
    if not match or match.group(1) not in ENGINE_FIELDS:
        return None
    return match.group(1), int(match.group(2))


def engine_metric_ids(kind, state):
    """List numbered engine rows available in this state snapshot."""
    if kind not in ENGINE_FIELDS:
        return []
    template = ENGINE_FIELDS[kind][0]
    pattern = "^" + re.escape(template).replace(r"\{n\}", r"([1-9][0-9]?)") + "$"
    indices = sorted(int(match.group(1)) for key in state
                     if (match := re.fullmatch(pattern, key)) and number(state.get(key)) is not None)
    return [f"engine:{kind}:{index}" for index in indices]


def expand_engine_metric(metric_id, state):
    """Expand the all-engines metric to one HUD row per live engine."""
    return engine_metric_ids(metric_id, state) if metric_id in ENGINE_FIELDS else [metric_id]


def metric_value(metric_id, state, indicators, limits=None):
    engine = engine_metric_parts(metric_id)
    if engine:
        kind, index = engine
        value = number(state.get(ENGINE_FIELDS[kind][0].format(n=index)))
        return METRICS[kind][4].format(value) if value is not None else "—"
    if metric_id.startswith("state:") or metric_id.startswith("indicators:"):
        source_name, key = metric_id.split(":", 1)
        source = state if source_name == "state" else indicators
        value = number(source.get(key))
        return f"{value:.1f}" if value is not None else "—"
    spec = METRICS[metric_id]
    if metric_id == "fuel_time":
        seconds = number(state.get("fuel_seconds"))
        if seconds is None:
            return "—"
        minutes, seconds = divmod(int(max(0, seconds)), 60)
        return f"≈{minutes:02d}:{seconds:02d}"
    if spec[2] == "special":
        return None
    if spec[2] == "derived":
        fuel, initial = number(state.get("Mfuel, kg")), number(state.get("Mfuel0, kg"))
        value = 100 * fuel / initial if fuel is not None and initial and initial > 0 else None
    elif spec[2] == "limits":
        value = number((limits or {}).get(spec[3]))
    else:
        source = state if spec[2] == "state" else indicators
        value = number(source.get(spec[3]))
    result = spec[4].format(value) if value is not None else "—"
    if value is not None and spec[2] == "limits" and limits:
        if (spec[3] in ("positive_g", "negative_g") and limits.get("_g_estimate")) or (
                spec[3] in ("ias_kmh", "mach") and limits.get("_sweep_conservative")):
            result = "≈" + result
    if value is not None and limits and ((metric_id.startswith("g_margin") and limits.get("_g_estimate")) or
                                         (metric_id in ("ias_margin", "mach_margin") and limits.get("_sweep_conservative"))):
        result = "≈" + result
    return result


def metric_label(metric_id):
    engine = engine_metric_parts(metric_id)
    if engine:
        kind, index = engine
        return f"{ENGINE_FIELDS[kind][2]}, двигатель {index}"
    if metric_id in METRICS:
        return METRICS[metric_id][1]
    if ":" in metric_id:
        return metric_id.split(":", 1)[1]
    return metric_id


def metric_help(metric_id):
    """Return a concise Russian explanation for a built-in or raw telemetry field."""
    engine = engine_metric_parts(metric_id)
    if engine:
        kind, index = engine
        return METRIC_HELP[kind] + f" Сейчас показан двигатель {index}."
    if metric_id in METRIC_HELP:
        return METRIC_HELP[metric_id]
    if ":" in metric_id:
        source, key = metric_id.split(":", 1)
        origin = "состояния самолёта" if source == "state" else "индикаторов игры"
        return f"Поле «{key}» из {origin}. Игра передаёт его напрямую; точный смысл зависит от самолёта и типа данных."
    return "Показатель телеметрии War Thunder. Его значение поступает из локального интерфейса игры."


def available_metrics(state, indicators, limits=None):
    """Show fields actually present in the current aircraft's local telemetry."""
    known_keys = {"state": set(), "indicators": set()}
    ids = []
    for metric_id, spec in METRICS.items():
        source, key = spec[2], spec[3]
        if source == "special":
            ids.append(metric_id)
        elif source == "derived":
            if number(state.get("Mfuel, kg")) is not None and number(state.get("Mfuel0, kg")):
                ids.append(metric_id)
        elif source == "limits":
            if number((limits or {}).get(key)) is not None:
                ids.append(metric_id)
        elif key in (state if source == "state" else indicators):
            ids.append(metric_id)
        if source in known_keys:
            known_keys[source].add(key)
    # Keep the all-engines entry and add individual rows for pilots that want
    # different placement or styling for a particular engine.
    for kind in ENGINE_FIELDS:
        engine_ids = engine_metric_ids(kind, state)
        ids.extend(engine_ids)
        known_keys["state"].update(ENGINE_FIELDS[kind][0].format(n=engine_id.rsplit(":", 1)[1])
                                   for engine_id in engine_ids)
    for source, data in (("state", state), ("indicators", indicators)):
        for key, value in sorted(data.items()):
            if key not in known_keys[source] and key not in ("valid", "type") and not key.startswith("_") and number(value) is not None:
                ids.append(f"{source}:{key}")
    return ids


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
