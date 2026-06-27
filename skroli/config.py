"""Configuration loading (SPECS §9).

Reads ``skroli.config.toml`` and fills in defaults. The format is intentionally
small for 0.0.1; it grows as more of the spec is implemented.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAME = "skroli.config.toml"


@dataclass
class RuntimeConfig:
    poll_interval_minutes: int = 15
    retention_hours: int = 48
    port: int = 4242
    open_window: bool = False  # use pywebview if available


@dataclass
class RssConfig:
    feeds: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)


@dataclass
class ScoreConfig:
    # Half-life (hours) for recency decay and optional per-source weights.
    half_life_hours: float = 12.0
    weights: dict[str, float] = field(default_factory=dict)


@dataclass
class Config:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    rss: RssConfig = field(default_factory=RssConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    data_dir: Path = field(default_factory=lambda: Path.home() / ".skroli")
    source_path: Path | None = None


def _default_rss() -> RssConfig:
    """A sensible starter so a fresh install shows something immediately."""
    return RssConfig(
        feeds=[
            "https://news.ycombinator.com/rss",
            "https://www.theverge.com/rss/index.xml",
        ],
        subreddits=["programming", "selfhosted"],
    )


def load_config(path: str | Path | None = None) -> Config:
    """Load config from ``path`` (or the default location), applying defaults.

    Missing file is not an error: you get a working starter config.
    """
    cfg = Config()

    candidate = Path(path) if path else Path.cwd() / DEFAULT_CONFIG_NAME
    if path is not None:
        # Remember an explicit config path even before the file exists so UI edits
        # are persisted to the path the user asked skroli to use.
        cfg.source_path = candidate
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

        rss = raw.get("ingestors", {}).get("rss", {})
        cfg.rss = RssConfig(
            feeds=list(rss.get("feeds", [])),
            subreddits=list(rss.get("subreddits", [])),
        )

        sc = raw.get("enhancers", {}).get("score", {})
        cfg.score = ScoreConfig(
            half_life_hours=float(sc.get("half_life_hours", 12.0)),
            weights={str(k): float(v) for k, v in sc.get("weights", {}).items()},
        )

        if "data_dir" in raw:
            cfg.data_dir = Path(raw["data_dir"]).expanduser()
    else:
        # No config file: ship a starter so `skroli run` works out of the box.
        cfg.rss = _default_rss()

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _toml_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _toml_array(values: list[str]) -> str:
    if not values:
        return '[]'
    lines = ["["]
    lines.extend(f"  {_toml_string(value)}," for value in values)
    lines.append("]")
    return "\n".join(lines)


def write_config(config: Config, path: str | Path | None = None) -> Path:
    """Persist the editable skroli settings to a TOML config file."""
    target = Path(path) if path else config.source_path or Path.cwd() / DEFAULT_CONFIG_NAME
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# skroli configuration"]
    if config.data_dir != Path.home() / ".skroli":
        lines.extend(["", f"data_dir = {_toml_string(str(config.data_dir))}"])
    lines.extend([
        "",
        "[runtime]",
        f"poll_interval_minutes = {int(config.runtime.poll_interval_minutes)}",
        f"retention_hours = {int(config.runtime.retention_hours)}",
        f"port = {int(config.runtime.port)}",
        f"open_window = {str(bool(config.runtime.open_window)).lower()}",
        "",
        "[ingestors.rss]",
        f"feeds = {_toml_array(config.rss.feeds)}",
        f"subreddits = {_toml_array(config.rss.subreddits)}",
        "",
        "[enhancers.score]",
        f"half_life_hours = {float(config.score.half_life_hours):g}",
    ])
    if config.score.weights:
        lines.extend(["", "[enhancers.score.weights]"])
        for source, weight in config.score.weights.items():
            lines.append(f"{_toml_string(source)} = {float(weight):g}")
    target.write_text("\n".join(lines) + "\n")
    config.source_path = target
    return target
