"""Config schema for the RSS ingestor."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RssConfig:
    enabled: bool = True
    feeds: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)
    letterboxd: list[str] = field(default_factory=list)  # usernames → film reviews
