"""Addon registry — the one place that knows which addons exist.

Core (config, cli, pipeline) drives off this list instead of importing specific
addons, so a new ingestor/enhancer plugs in by exporting an ``Addon`` from its
package and being listed here. The order is significant: enhancers run in this
order (score before engagement folds votes in).

Future: discover third-party addons via ``importlib.metadata`` entry points
(group ``skroli.addons``) and merge them into ``_BUILTINS`` — the rest of core
won't need to change.
"""

from __future__ import annotations

from ..enhancers.engagement import ADDON as _engagement
from ..enhancers.score import ADDON as _score
from ..ingestors.hackernews import ADDON as _hackernews
from ..ingestors.images import ADDON as _images
from ..ingestors.rss import ADDON as _rss
from .addons_base import Addon

_BUILTINS: list[Addon] = [_rss, _hackernews, _images, _score, _engagement]


def all_addons() -> list[Addon]:
    return list(_BUILTINS)


def ingestors() -> list[Addon]:
    return [a for a in _BUILTINS if a.group == "ingestor"]


def enhancers() -> list[Addon]:
    return [a for a in _BUILTINS if a.group == "enhancer"]


def sections() -> list:
    return [a.section for a in _BUILTINS]


def actions() -> dict:
    merged: dict = {}
    for addon in _BUILTINS:
        merged.update(addon.actions)
    return merged
