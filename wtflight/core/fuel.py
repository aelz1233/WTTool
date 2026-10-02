"""Fuel flow and endurance estimate from consecutive fuel-mass samples."""

import math
from collections import deque

from wtflight.core.metrics import number


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
