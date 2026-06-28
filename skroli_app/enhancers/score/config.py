"""Config schema for the score enhancer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreConfig:
    # Half-life (hours) for recency decay and optional per-source weights.
    enabled: bool = True
    half_life_hours: float = 12.0
    weights: dict[str, float] = field(default_factory=dict)
