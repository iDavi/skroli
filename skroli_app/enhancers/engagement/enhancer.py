"""Built-in engagement enhancer (SPECS §3.2).

Folds community engagement (Reddit upvotes, Hacker News points) into the score:

    score = (1 - weight)·recency + weight·engagement_norm
    engagement_norm = log1p(votes) / log1p(cap)   (clamped to 1.0)

Items without a vote signal (plain RSS, Letterboxd) are treated as *average*
engagement (a neutral 0.5 baseline) rather than zero — so they're neither
penalised for lacking votes nor able to permanently outrank highly-voted posts.
A heavily-upvoted item rises above the baseline; a barely-voted one sinks below
it. Runs after the recency ``score`` enhancer, which it reads from and rewrites.
"""

from __future__ import annotations

import math

from .config import EngagementConfig
from ...models import Item

_NEUTRAL = 0.5  # assumed engagement for items that carry no vote signal


class EngagementEnhancer:
    name = "engagement"

    def __init__(self, config: EngagementConfig):
        self._config = config

    def enhance(self, items: list[Item]) -> list[Item]:
        if not self._config.enabled:
            return items
        weight = max(0.0, min(self._config.weight, 1.0))
        if weight == 0.0:
            return items
        denom = math.log1p(max(self._config.cap, 1))
        for it in items:
            if "engagement" in it.meta:
                votes = max(float(it.meta.get("engagement", 0) or 0), 0.0)
                norm = min(math.log1p(votes) / denom, 1.0) if denom else 0.0
            else:
                norm = _NEUTRAL
            recency = float(it.meta.get("score", 0.0))
            it.meta["score"] = round((1.0 - weight) * recency + weight * norm, 4)
        items.sort(key=lambda i: i.score, reverse=True)
        return items
