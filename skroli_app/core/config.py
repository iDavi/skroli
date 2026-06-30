"""Top-level configuration (SPECS §9).

Addons own their config schema (``ingestors/rss/config.py`` etc.) and are listed
in ``registry``. This module is generic: it builds the live config, and reads /
writes the TOML file, purely by walking each addon's declared ``Field``s — it
never names a specific addon, so a new addon needs no changes here.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import registry
from .addons_base import Addon, Field

# The configurable addons, in display order — the viewer renders/saves these
# generically. Kept as a module attribute for back-compat with importers.
SECTIONS = registry.sections()

DEFAULT_CONFIG_NAME = "skroli.config.toml"


@dataclass
class RuntimeConfig:
    poll_interval_minutes: int = 15
    retention_hours: int = 48
    port: int = 4242
    open_window: bool = False  # use a native window if available


@dataclass
class Config:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    data_dir: Path = field(default_factory=lambda: Path.home() / ".skroli")
    source_path: Path | None = None
    # Live addon config dataclasses, keyed by addon ``attr`` (e.g. "rss", "hn").
    # Also exposed as attributes (``config.rss``) for ergonomic access.
    addons: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        # Only reached when normal lookup fails — serve addon configs by attr.
        addons = self.__dict__.get("addons", {})
        if name in addons:
            return addons[name]
        raise AttributeError(name)

    def set_addon(self, addon: Addon, inst: Any) -> None:
        self.addons[addon.attr] = inst


# --- starter content for a fresh install (no config file yet) ------------------
def _apply_starter(cfg: Config) -> None:
    rss = cfg.addons.get("rss")
    if rss is not None:
        rss.feeds = ["https://www.theverge.com/rss/index.xml"]
        rss.subreddits = ["programming", "selfhosted"]


# --- generic field <-> value coercion -----------------------------------------
def _coerce(f: Field, value: Any) -> Any:
    if f.kind == "toggle":
        return bool(value)
    if f.kind == "int":
        return int(value)
    if f.kind == "float":
        return float(value)
    if f.kind == "list":
        return [str(x) for x in (value or [])]
    if f.kind == "weights":
        out: dict[str, float] = {}
        for k, v in (value or {}).items():
            try:
                out[str(k)] = float(v)
            except (ValueError, TypeError):
                continue
        return out
    return value


def _addon_from_table(addon: Addon, table: dict) -> Any:
    inst = addon.config_class()   # defaults
    for f in addon.section.fields:
        if f.key in table:
            try:
                setattr(inst, f.key, _coerce(f, table[f.key]))
            except (ValueError, TypeError):
                pass
    return inst


# --- TOML serialization (driven by field kinds) -------------------------------
def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_array(items: list[str]) -> str:
    return "[" + ", ".join(f'"{_toml_escape(i)}"' for i in items) + "]"


def _toml_num(value: float) -> str:
    # Keep whole numbers tidy (12.0 -> "12.0", 1.2 -> "1.2") without float noise.
    return f"{value:g}" if value != int(value) else f"{value:.1f}"


def _toml_scalar(kind: str, value: Any) -> str:
    if kind == "toggle":
        return "true" if value else "false"
    if kind == "int":
        return str(int(value))
    if kind == "float":
        return _toml_num(float(value))
    if kind == "list":
        return _toml_array(value or [])
    return str(value)


def save_config(config: Config) -> Path:
    """Write ``config`` back to disk as TOML (used by the in-UI editor).

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
    ]

    for addon in registry.all_addons():
        inst = config.addons[addon.attr]
        lines += ["", f"[{addon.group}s.{addon.id}]"]
        weights: list[tuple[str, dict]] = []
        for f in addon.section.fields:
            val = getattr(inst, f.key)
            if f.kind == "weights":
                weights.append((f.key, val or {}))
            else:
                lines.append(f"{f.key} = {_toml_scalar(f.kind, val)}")
        for key, mapping in weights:
            if mapping:
                lines += ["", f"[{addon.group}s.{addon.id}.{key}]"]
                lines += [f'"{_toml_escape(k)}" = {_toml_num(v)}'
                          for k, v in mapping.items()]

    target.write_text("\n".join(lines) + "\n")
    config.source_path = target
    return target


def load_config(path: str | Path | None = None) -> Config:
    """Load config from ``path`` (or the default location), applying defaults.

    Missing file is not an error: you get a working starter config.
    """
    cfg = Config()
    raw: dict = {}

    candidate = Path(path) if path else Path.cwd() / DEFAULT_CONFIG_NAME
    has_file = candidate.exists()
    if has_file:
        raw = tomllib.loads(candidate.read_text())
        cfg.source_path = candidate

        rt = raw.get("runtime", {})
        cfg.runtime = RuntimeConfig(
            poll_interval_minutes=int(rt.get("poll_interval_minutes", 15)),
            retention_hours=int(rt.get("retention_hours", 48)),
            port=int(rt.get("port", 4242)),
            open_window=bool(rt.get("open_window", False)),
        )
        if "data_dir" in raw:
            cfg.data_dir = Path(raw["data_dir"]).expanduser()

    for addon in registry.all_addons():
        table = raw.get(f"{addon.group}s", {}).get(addon.id, {})
        cfg.set_addon(addon, _addon_from_table(addon, table))

    if not has_file:
        _apply_starter(cfg)   # ship something to look at out of the box

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
