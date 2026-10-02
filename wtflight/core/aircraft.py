"""Versioned flight-model data, aircraft aliases and automatic limit estimates.

Data provenance and its license are in resources/flight_models/metadata.json and LICENSE.
The per-wing load convention is documented by SpaceCapo/warthunder-byoh, core_client.
"""

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from wtflight.core.metrics import number
from wtflight.paths import FLIGHT_MODELS as BUNDLED
UPSTREAM = "https://raw.githubusercontent.com/SpaceCapo/warthunder-byo-fm/main/"


def version_tuple(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("Неверная версия базы")
    return tuple(map(int, version.split(".")))


def normalized_id(value):
    value = str(value or "").strip().lower()
    for suffix in (".blkx", ".blk"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    return value


def numbers(value):
    parts = str(value or "").split(",")
    values = [number(part) for part in parts]
    return values if all(v is not None for v in values) else []


def speed_limit(value, sweep=None):
    """Scalar or (wing sweep ratio, limit) table. Missing sweep uses its minimum."""
    values = numbers(value)
    if len(values) == 1:
        return values[0] if values[0] > 0 else None, False
    if not values or len(values) % 2:
        return None, False
    pairs = sorted(zip(values[::2], values[1::2]))
    if any(x < 0 or x > 1 or y <= 0 for x, y in pairs):
        return None, False
    if sweep is None or not 0 <= sweep <= 1:
        return min(y for _, y in pairs), True
    if sweep <= pairs[0][0]:
        return pairs[0][1], False
    for (left, low), (right, high) in zip(pairs, pairs[1:]):
        if left < sweep <= right:
            return low + (high - low) * (sweep - left) / (right - left), False
    return pairs[-1][1], False


class AircraftDatabase:
    def __init__(self, models_text, names_text, version):
        version_tuple(version)
        self.version = version
        models = csv.DictReader(io.StringIO(models_text.lstrip("\ufeff")), delimiter=";")
        names = csv.DictReader(io.StringIO(names_text.lstrip("\ufeff")), delimiter=";")
        if not {"Name", "CritAirSpd", "CritWingOverload", "EmptyMass"}.issubset(models.fieldnames or []):
            raise ValueError("Неверные столбцы параметров самолётов")
        if not {"Name", "FmName", "English"}.issubset(names.fieldnames or []):
            raise ValueError("Неверные столбцы имён самолётов")
        self.models = {normalized_id(row["Name"]): row for row in models if row.get("Name")}
        self.names = {normalized_id(row["Name"]): row for row in names if row.get("Name")}
        if not self.models or not self.names:
            raise ValueError("База самолётов пуста")
        self.known_count = len(set(self.models) | {k for k, v in self.names.items()
                                                 if normalized_id(v.get("FmName")) in self.models})

    @classmethod
    def load(cls, cache_dir):
        bundled = cls((BUNDLED / "fm_data_db.csv").read_text(encoding="utf-8-sig"),
                      (BUNDLED / "fm_names_db.csv").read_text(encoding="utf-8-sig"),
                      (BUNDLED / "version").read_text().strip())
        try:
            cache = json.loads((Path(cache_dir) / "aircraft_database.json").read_text(encoding="utf-8"))
            if version_tuple(cache["version"]) > version_tuple(bundled.version):
                return cls(cache["models"], cache["names"], cache["version"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return bundled

    def resolve(self, aircraft):
        key = normalized_id(aircraft)
        alias = self.names.get(key)
        model = normalized_id(alias.get("FmName")) if alias else key
        return self.models.get(model)

    def display_name(self, aircraft):
        alias = self.names.get(normalized_id(aircraft), {})
        if alias.get("English"):
            return alias["English"]
        if not self.resolve(aircraft):
            return aircraft
        # Human-readable fallback for models not covered by the names table.
        return re.sub(r"^([A-Za-z]+)[ _](\d+[A-Za-z]*)", lambda m: m[1].upper() + "-" + m[2].upper(),
                      normalized_id(aircraft).replace("_", " ").title())

    def limits(self, aircraft, state, indicators=None):
        record = self.resolve(aircraft)
        if record is None:
            return {}
        result = {"_source": "database", "_version": self.version}
        sweep_pct = number(state.get("wing sweep, %"))
        sweep = sweep_pct / 100 if sweep_pct is not None else None
        for column, key in (("CritAirSpd", "ias_kmh"), ("CritAirSpdMach", "mach")):
            value, conservative = speed_limit(record.get(column), sweep)
            if value is not None:
                result[key] = value
            if conservative:
                result["_sweep_conservative"] = True
        gear = number(record.get("CritGearSpd"))
        if gear and gear > 0:
            result["gear_kmh"] = gear
        flaps = numbers(record.get("CritFlapsSpd"))
        if len(flaps) % 2 == 0:
            speeds = [speed for ratio, speed in zip(flaps[::2], flaps[1::2]) if ratio > 0 and speed > 0]
            if speeds:
                result["flaps_landing_kmh"] = min(speeds)
        empty_mass = number(record.get("EmptyMass"))
        fuel_mass = number(state.get("Mfuel, kg"))
        loads = numbers(record.get("CritWingOverload"))
        # A per-wing force is doubled. This estimate excludes unknown payload / crew mass.
        if empty_mass and empty_mass > 0 and fuel_mass is not None and fuel_mass >= 0 and len(loads) == 2:
            weight = (empty_mass + fuel_mass) * 9.81
            if loads[0] < 0:
                result["negative_g"] = 2 * loads[0] / weight
            if loads[1] > 0:
                result["positive_g"] = 2 * loads[1] / weight
            result["_g_estimate"] = True
        return result


def download_database(cache_dir, current_version):
    """Update both tables atomically. On failure the existing snapshot remains usable."""
    def read(relative, limit=4_000_000):
        request = Request(UPSTREAM + relative, headers={"User-Agent": "WTFlightAssistant/1.0"})
        with urlopen(request, timeout=5) as response:
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Файл базы слишком большой")
        return content.decode("utf-8-sig")

    version = read("latest/fm/version", 100).strip()
    if version_tuple(version) <= version_tuple(current_version):
        return None
    models = read(f"{version}/fm/fm_data_db.csv")
    names = read(f"{version}/fm/fm_names_db.csv")
    database = AircraftDatabase(models, names, version)
    payload = {"version": version, "models": models, "names": names,
               "source": UPSTREAM, "downloaded_at": datetime.now(timezone.utc).isoformat()}
    target = Path(cache_dir) / "aircraft_database.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return database
