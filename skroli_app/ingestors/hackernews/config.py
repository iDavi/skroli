"""Config schema for the Hacker News ingestor."""

from __future__ import annotations

from dataclasses import dataclass

from ...core.addons_base import Field, Section


@dataclass
class HnConfig:
    # Hacker News via the official Algolia API (real points + comment counts).
    enabled: bool = True
    count: int = 30  # how many front-page stories to pull


SECTION = Section(
    id="hackernews", group="ingestor", title="Hacker News", attr="hn",
    desc="Pulls the live front page from the official HN API, with points and "
         "comment counts the engagement enhancer can rank by.",
    fields=[
        Field("enabled", "toggle"),
        Field("count", "int", label="Stories to fetch (0 = off)", min=0, step=5),
    ],
)
