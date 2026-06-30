"""Recency/weight score enhancer addon."""

from __future__ import annotations

from ...core.addons_base import Addon
from .config import SECTION, ScoreConfig
from .enhancer import ScoreEnhancer

ADDON = Addon(
    section=SECTION,
    config_class=ScoreConfig,
    build=lambda cfg: ScoreEnhancer(cfg),
)
