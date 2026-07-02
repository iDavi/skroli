"""Image-discovery ingestor addon (the Images grid)."""

from __future__ import annotations

from ...core.addons_base import Addon
from .config import SECTION, ImagesConfig
from .ingestor import ImagesIngestor


def _origins(cfg: ImagesConfig) -> set[str]:
    if not cfg.enabled:
        return set()
    return {
        f"img:reddit:{s.removeprefix('r/').strip('/').lower()}"
        for s in cfg.subreddits if s.strip()
    }


ADDON = Addon(
    section=SECTION,
    config_class=ImagesConfig,
    build=lambda cfg: ImagesIngestor(cfg),
    origins=_origins,
)
