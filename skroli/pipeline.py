"""The feed pipeline: ingest → enhance → view (SPECS §5)."""

from __future__ import annotations

from .addons_base import Enhancer, Ingestor, Viewer
from .config import Config
from .storage import Storage


class Pipeline:
    def __init__(
        self,
        config: Config,
        storage: Storage,
        ingestors: list[Ingestor],
        enhancers: list[Enhancer],
        viewer: Viewer,
    ):
        self.config = config
        self.storage = storage
        self.ingestors = ingestors
        self.enhancers = enhancers
        self.viewer = viewer

    def run_cycle(self) -> int:
        """One poll cycle. Returns the number of items in the rendered feed."""
        # 1–2. Ingest from every source (errors isolated, SPECS §5.3).
        fetched = []
        for ing in self.ingestors:
            try:
                fetched.extend(ing.fetch())
            except Exception as exc:  # noqa: BLE001 - resilience over correctness
                print(f"  ! ingestor '{ing.name}' failed: {exc}")

        # 3. Dedup into the store; 4. drop items past retention.
        new = self.storage.add_new(fetched)
        self.storage.prune(self.config.runtime.retention_hours)
        items = self.storage.load_recent(self.config.runtime.retention_hours)

        # 5. (federation sync — later versions.)
        # 6. Enhance.
        for enh in self.enhancers:
            try:
                items = enh.enhance(items)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! enhancer '{enh.name}' failed: {exc}")

        # 7–8. Render.
        self.viewer.render(items)
        print(f"  cycle: {new} new, {len(items)} in feed")
        return len(items)
