"""Typed HUD models with a single serialization boundary."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from uuid import uuid4


@dataclass
class HudGroup:
    metric_id: str
    x: float = 0.08
    y: float = 0.16
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    title: str = "НОВЫЙ БЛОК"
    metrics: list[str] = field(default_factory=list)
    style: str = "text"
    size: int = 18
    labels: bool = True
    title_visible: bool = False
    font_family: str = "Lucida Console"
    bold: bool = True
    shadow: bool = False
    compact_labels: bool = True
    spacing: int = 1
    color: str = "#66d6a0"
    accent: str = "#66d6a0"
    hud_style: str = "wtrti"
    outline: bool = True
    outline_color: str = "#07140f"
    outline_width: float = 1.4

    def __post_init__(self):
        if not self.metrics:
            self.metrics = [self.metric_id]

    def to_dict(self) -> dict:
        return {item.name: getattr(self, item.name) for item in fields(self) if item.name != "metric_id"}

    @classmethod
    def from_dict(cls, source: dict):
        metrics = list(source.get("metrics") or [])
        if not metrics:
            raise ValueError("HUD group must contain at least one metric")
        allowed = {item.name for item in fields(cls)} - {"metric_id"}
        values = {key: value for key, value in source.items() if key in allowed}
        values.update(metric_id=metrics[0], metrics=metrics)
        return cls(**values)

