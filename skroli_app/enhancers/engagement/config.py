"""Config schema for the engagement enhancer."""

from __future__ import annotations

from dataclasses import dataclass

from ...core.addons_base import Field, Section


@dataclass
class EngagementConfig:
    # Blend community engagement (Reddit upvotes, HN points) into the score.
    # final = (1 - weight)·recency + weight·engagement, engagement log-normalised
    # against ``cap`` votes. weight 0 = ignore engagement entirely.
    enabled: bool = True
    weight: float = 0.4
    cap: int = 2000


SECTION = Section(
    id="engagement", group="enhancer", title="Engagement", attr="engagement",
    desc="Blends community votes (Reddit upvotes, HN points) into the score: "
         "(1−weight)·recency + weight·votes. Items without votes (plain RSS, "
         "Letterboxd) keep their recency score.",
    fields=[
        Field("enabled", "toggle"),
        Field("weight", "float", label="How much votes matter", min=0, max=1, step=0.05),
        Field("cap", "int", label="Votes for a full score", min=1, step=100),
    ],
)
