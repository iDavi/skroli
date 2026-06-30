"""Hacker News ingestor addon."""

from __future__ import annotations

from ...core.addons_base import Addon
from .config import SECTION, HnConfig
from .ingestor import HackerNewsIngestor


def _origins(cfg: HnConfig) -> set[str]:
    return {"hn"} if cfg.enabled and cfg.count > 0 else set()


ADDON = Addon(
    section=SECTION,
    config_class=HnConfig,
    build=lambda cfg: HackerNewsIngestor(cfg),
    origins=_origins,
)
