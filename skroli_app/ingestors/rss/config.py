"""Config schema for the RSS ingestor."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.addons_base import Field, Section


@dataclass
class RssConfig:
    enabled: bool = True
    feeds: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)
    letterboxd: list[str] = field(default_factory=list)  # usernames → film reviews


SECTION = Section(
    id="rss", group="ingestor", title="RSS", attr="rss",
    desc="Reads any RSS or Atom feed, subreddits (via Reddit's API, with upvotes), "
         "and Letterboxd profiles (film reviews).",
    fields=[
        Field("enabled", "toggle"),
        Field("feeds", "list", label="Feeds", placeholder="https://example.com/feed.xml"),
        Field("subreddits", "list", label="Subreddits", prefix="r/", placeholder="subreddit"),
        Field("letterboxd", "list", label="Letterboxd profiles", prefix="@",
              placeholder="username", action="import-following"),
    ],
)
