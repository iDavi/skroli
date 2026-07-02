"""Addon contracts (SPECS §3).

0.0.1 ships built-in addons that implement these directly. Dynamic loading of
third-party addons from the store is a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dfield
from typing import Any, Callable, Protocol, runtime_checkable

from .models import Item


# --- declarative config schema -------------------------------------------------
# Addons describe their config as data so the viewer can render and save any
# addon's settings without knowing what it is.

@dataclass
class Field:
    key: str
    kind: str                       # toggle | int | float | list | weights | select
    label: str = ""
    placeholder: str = ""
    prefix: str = ""                # shown before list inputs, e.g. "r/" or "@"
    action: str = ""                # optional client action id (e.g. import-following)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None  # allowed values for kind="select"


@dataclass
class Section:
    """One configurable addon, as the UI sees it."""
    id: str
    group: str                      # "ingestor" | "enhancer"
    title: str
    attr: str                       # attribute on Config holding this addon's dataclass
    desc: str = ""
    fields: list[Field] = dfield(default_factory=list)


@dataclass
class Addon:
    """Everything core needs to know about one addon, declared by the addon
    itself. The registry collects these; config/cli/pipeline drive off them, so
    a new addon plugs in by exporting an ``Addon`` from its package — no edits to
    core. (Future: third-party addons discovered via entry points / the store.)

    ``build`` turns the addon's config dataclass into a live Ingestor/Enhancer.
    ``origins`` (ingestors only) reports the source identities the addon is
    currently configured to produce, so pruning isn't hardcoded in the engine.
    ``actions`` are named operations the UI can invoke generically.
    """

    section: Section
    config_class: type
    build: Callable[[Any], Any]
    origins: Callable[[Any], set[str]] | None = None
    actions: dict[str, Callable[[dict], dict]] = dfield(default_factory=dict)

    @property
    def id(self) -> str:
        return self.section.id

    @property
    def group(self) -> str:
        return self.section.group

    @property
    def attr(self) -> str:
        return self.section.attr


@runtime_checkable
class Ingestor(Protocol):
    name: str

    def fetch(self) -> list[Item]:
        """Pull fresh items from a source."""
        ...


@runtime_checkable
class Enhancer(Protocol):
    name: str

    def enhance(self, items: list[Item]) -> list[Item]:
        """Process items (rank, enrich, filter) and return the new list."""
        ...


@runtime_checkable
class Viewer(Protocol):
    name: str

    def serve(self, open_window: bool = False) -> None:
        """Present the feed. The built-in viewer serves a UI and streams items in
        over a WebSocket as the engine produces them, rather than receiving one
        finished list — so the window can open before any data has arrived."""
        ...
