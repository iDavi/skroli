"""Addon contracts (SPECS §3).

0.0.1 ships built-in addons that implement these directly. Dynamic loading of
third-party addons from the store is a later milestone.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Item


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

    def render(self, items: list[Item]) -> None:
        """Present the final feed."""
        ...
