"""Top-level configuration (SPECS §9).

Each addon owns its own config schema (e.g. ``ingestors/rss/config.py``); this
module just aggregates them into one ``Config`` and reads/writes the TOML file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .enhancers.engagement.config import EngagementConfig
from .enhancers.score.config import ScoreConfig
from .ingestors.hackernews.config import HnConfig
from .ingestors.rss.config import RssConfig

DEFAULT_CONFIG_NAME = "skroli.config.toml"


@dataclass
class RuntimeConfig:
    poll_interval_minutes: int = 15
    retention_hours: int = 48
    port: int = 4242
    open_window: bool = False  # use pywebview if available


@dataclass
class Config:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    rss: RssConfig = field(default_factory=RssConfig)
    hn: HnConfig = field(default_factory=HnConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    engagement: EngagementConfig = field(default_factory=EngagementConfig)
    data_dir: Path = field(default_factory=lambda: Path.home() / ".skroli")
    source_path: Path | None = None


def _default_rss() -> RssConfig:
    """A sensible starter so a fresh install shows something immediately."""
    return RssConfig(
        feeds=["https://www.theverge.com/rss/index.xml"],
        subreddits=["programming", "selfhosted"],
        letterboxd=[],
    )


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_array(items: list[str]) -> str:
    return "[" + ", ".join(f'"{_toml_escape(i)}"' for i in items) + "]"


def _toml_num(value: float) -> str:
    # Keep whole numbers tidy (12.0 -> "12.0", 1.2 -> "1.2") without float noise.
    return f"{value:g}" if value != int(value) else f"{value:.1f}"


def save_config(config: Config) -> Path:
    """Write ``config`` back to disk as TOML. Used by the in-UI editor.

    Targets ``config.source_path`` if known, else ``./skroli.config.toml``. The
    file is regenerated from the live config, so hand-written comments are lost.
    """
    target = config.source_path or (Path.cwd() / DEFAULT_CONFIG_NAME)
    rt = config.runtime
    lines = [
        "# skroli configuration — written by skroli (the in-app editor rewrites this file).",
        "",
        "[runtime]",
        f"poll_interval_minutes = {rt.poll_interval_minutes}",
        f"retention_hours = {rt.retention_hours}",
        f"port = {rt.port}",
        f"open_window = {'true' if rt.open_window else 'false'}",
        "",
        "[ingestors.rss]",
        f"enabled = {'true' if config.rss.enabled else 'false'}",
        f"feeds = {_toml_array(config.rss.feeds)}",
        f"subreddits = {_toml_array(config.rss.subreddits)}",
        f"letterboxd = {_toml_array(config.rss.letterboxd)}",
        "",
        "[ingestors.hackernews]",
        f"enabled = {'true' if config.hn.enabled else 'false'}",
        f"count = {config.hn.count}",
        "",
        "[enhancers.score]",
        f"enabled = {'true' if config.score.enabled else 'false'}",
        f"half_life_hours = {_toml_num(config.score.half_life_hours)}",
    ]
    if config.score.weights:
        lines += ["", "[enhancers.score.weights]"]
        lines += [f'"{_toml_escape(k)}" = {_toml_num(v)}' for k, v in config.score.weights.items()]
    lines += [
        "",
        "[enhancers.engagement]",
        f"enabled = {'true' if config.engagement.enabled else 'false'}",
        f"weight = {_toml_num(config.engagement.weight)}",
        f"cap = {config.engagement.cap}",
    ]
    target.write_text("\n".join(lines) + "\n")
    config.source_path = target
    return target


def load_config(path: str | Path | None = None) -> Config:
    """Load config from ``path`` (or the default location), applying defaults.

    Missing file is not an error: you get a working starter config.
    """
    cfg = Config()

    candidate = Path(path) if path else Path.cwd() / DEFAULT_CONFIG_NAME
    if candidate.exists():
        raw = tomllib.loads(candidate.read_text())
        cfg.source_path = candidate

        rt = raw.get("runtime", {})
        cfg.runtime = RuntimeConfig(
            poll_interval_minutes=int(rt.get("poll_interval_minutes", 15)),
            retention_hours=int(rt.get("retention_hours", 48)),
            port=int(rt.get("port", 4242)),
            open_window=bool(rt.get("open_window", False)),
        )

        ingestors = raw.get("ingestors", {})
        rss = ingestors.get("rss", {})
        cfg.rss = RssConfig(
            enabled=bool(rss.get("enabled", True)),
            feeds=list(rss.get("feeds", [])),
            subreddits=list(rss.get("subreddits", [])),
            letterboxd=list(rss.get("letterboxd", [])),
        )
        hn = ingestors.get("hackernews", {})
        cfg.hn = HnConfig(enabled=bool(hn.get("enabled", True)), count=int(hn.get("count", 30)))

        enhancers = raw.get("enhancers", {})
        sc = enhancers.get("score", {})
        cfg.score = ScoreConfig(
            enabled=bool(sc.get("enabled", True)),
            half_life_hours=float(sc.get("half_life_hours", 12.0)),
            weights={str(k): float(v) for k, v in sc.get("weights", {}).items()},
        )
        eng = enhancers.get("engagement", {})
        cfg.engagement = EngagementConfig(
            enabled=bool(eng.get("enabled", True)),
            weight=float(eng.get("weight", 0.4)),
            cap=int(eng.get("cap", 2000)),
        )

        if "data_dir" in raw:
            cfg.data_dir = Path(raw["data_dir"]).expanduser()
    else:
        # No config file: ship a starter so `skroli run` works out of the box.
        cfg.rss = _default_rss()

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
