"""Config schema for the Hacker News ingestor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HnConfig:
    # Hacker News via the official Algolia API (real points + comment counts).
    enabled: bool = True
    count: int = 30  # how many front-page stories to pull
