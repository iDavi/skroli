"""Config schema for the score enhancer."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.addons_base import Field, Section


@dataclass
class ScoreConfig:
    # Half-life (hours) for recency decay and optional per-source weights.
    enabled: bool = True
    half_life_hours: float = 12.0
    weights: dict[str, float] = field(default_factory=dict)


SECTION = Section(
    id="score", group="enhancer", title="Score", attr="score",
    desc="Ranks the feed by recency. Each item scores 0.5 ^ (age / half-life) "
         "times its source weight.",
    fields=[
        Field("enabled", "toggle"),
        Field("half_life_hours", "float", label="Half-life (hours)", min=0.1, step=0.5),
        Field("weights", "weights", label="Source weights"),
    ],
)
