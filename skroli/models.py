"""Core data contract passed between every pipeline stage (SPECS §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Item:
    """A single piece of content in the feed."""

    id: str
    source: str
    url: str
    title: str
    published_at: datetime
    body: str = ""
    author: str = ""
    # Open bag for fields added by enhancers (e.g. the score). SPECS §4.
    meta: dict[str, Any] = field(default_factory=dict)
    # Populated from the federation in later versions; local-only stub for 0.0.1.
    saved: bool = False

    @property
    def score(self) -> float:
        """Convenience accessor for the enhancer-assigned score (0..1)."""
        return float(self.meta.get("score", 0.0))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
