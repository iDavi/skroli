"""RSS / Reddit / Letterboxd ingestor addon."""

from __future__ import annotations

from ...core.addons_base import Addon
from .config import SECTION, RssConfig
from .ingestor import RssIngestor, letterboxd_following


def _origins(cfg: RssConfig) -> set[str]:
    """Source identities this addon currently produces (must match the
    ``meta['origin']`` ingestors stamp on items), so the engine can prune
    sources the user removed without knowing anything addon-specific."""
    if not cfg.enabled:
        return set()
    origins = set(cfg.feeds)
    origins |= {f"reddit:{s.removeprefix('r/').strip('/')}" for s in cfg.subreddits}
    origins |= {f"letterboxd:{u.strip().lstrip('@').strip('/')}" for u in cfg.letterboxd}
    return origins


ADDON = Addon(
    section=SECTION,
    config_class=RssConfig,
    build=lambda cfg: RssIngestor(cfg),
    origins=_origins,
    actions={
        "import-following": lambda payload: {
            "users": letterboxd_following(str(payload.get("username", "")))
        },
    },
)
