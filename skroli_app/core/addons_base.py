"""Addon contracts (SPECS §3).

0.0.1 ships built-in addons that implement these directly. Dynamic loading of
third-party addons from the store is a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dfield
from typing import Protocol, runtime_checkable

from .models import Item


# --- declarative config schema -------------------------------------------------
# Addons describe their config as data so the viewer can render and save any
# addon's settings without knowing what it is.

@dataclass
class Field:
    key: str
    kind: str                       # toggle | int | float | list | weights
    label: str = ""
    placeholder: str = ""
    prefix: str = ""                # shown before list inputs, e.g. "r/" or "@"
    action: str = ""                # optional client action id (e.g. import-following)
    min: float | None = None
    max: float | None = None
    step: float | None = None


@dataclass
class Section:
    """One configurable addon, as the UI sees it."""
    id: str
    group: str                      # "ingestor" | "enhancer"
    title: str
    attr: str                       # attribute on Config holding this addon's dataclass
    desc: str = ""
    fields: list[Field] = dfield(default_factory=list)


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
