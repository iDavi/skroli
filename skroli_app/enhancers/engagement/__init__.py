"""Engagement (votes) score-blending enhancer addon."""

from __future__ import annotations

from ...core.addons_base import Addon
from .config import SECTION, EngagementConfig
from .enhancer import EngagementEnhancer

ADDON = Addon(
    section=SECTION,
    config_class=EngagementConfig,
    build=lambda cfg: EngagementEnhancer(cfg),
)
