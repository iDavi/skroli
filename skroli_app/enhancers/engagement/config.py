"""Config schema for the engagement enhancer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngagementConfig:
    # Blend community engagement (Reddit upvotes, HN points) into the score.
    # final = (1 - weight)·recency + weight·engagement, engagement log-normalised
    # against ``cap`` votes. weight 0 = ignore engagement entirely.
    enabled: bool = True
    weight: float = 0.4
    cap: int = 2000
