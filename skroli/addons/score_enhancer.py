"""Built-in scoring enhancer (SPECS §3.2).

Classifies each item with a score in 0..1 and sorts the feed by it. The score is
recency (exponential decay by half-life) times an optional per-source weight.
Deliberately simple — a real ranker is a swappable addon.
"""

from __future__ import annotations

from ..config import ScoreConfig
from ..models import Item, utcnow


class ScoreEnhancer:
    name = "score"

    def __init__(self, config: ScoreConfig):
        self._config = config

    def enhance(self, items: list[Item]) -> list[Item]:
        if not self._config.enabled:
            return items
        now = utcnow()
        half_life = max(self._config.half_life_hours, 0.1)
        for it in items:
            age_hours = max((now - it.published_at).total_seconds() / 3600.0, 0.0)
            recency = 0.5 ** (age_hours / half_life)
            weight = self._config.weights.get(it.source, 1.0)
            it.meta["score"] = round(min(recency * weight, 1.0), 4)
        items.sort(key=lambda i: i.score, reverse=True)
        return items
