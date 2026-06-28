"""skroli command line: ``skroli run`` (SPECS §5, ROADMAP P6)."""

from __future__ import annotations

import argparse
import sys
import threading
import time

from . import __version__
from .ingestors.rss.ingestor import RssIngestor
from .ingestors.hackernews.ingestor import HackerNewsIngestor
from .enhancers.score.enhancer import ScoreEnhancer
from .enhancers.engagement.enhancer import EngagementEnhancer
from .viewer.viewer import SkroliViewer
from .core.config import load_config, save_config, SECTIONS
from .core.pipeline import Engine
from .core.storage import Storage
from .core.stream import Broadcaster


def _build(config) -> tuple[Engine, SkroliViewer]:
    storage = Storage(config.data_dir / "skroli.db")
    ingestors = [RssIngestor(config.rss), HackerNewsIngestor(config.hn)]
    # Order matters: score (recency) first, then engagement folds votes in.
    enhancers = [ScoreEnhancer(config.score), EngagementEnhancer(config.engagement)]
    broadcaster = Broadcaster()
    engine = Engine(config, storage, ingestors, enhancers, broadcaster)

    def on_save() -> None:
        # The viewer mutates the config dataclasses in place; persist + re-fetch.
        save_config(config)
        engine.refresh()

    # Named actions the UI can invoke generically (kept here, not in the viewer).
    from .ingestors.rss.ingestor import letterboxd_following
    actions = {
        "import-following": lambda p: {"users": letterboxd_following(str(p.get("username", "")))},
    }

    viewer = SkroliViewer(
        port=config.runtime.port,
        broadcaster=broadcaster,
        on_connect=engine.send_cached,   # new viewer gets cached items instantly
        on_refresh=engine.refresh,       # refresh button streams fresh items
        on_save=on_save,
        config=config,
        sections=SECTIONS,
        actions=actions,
    )
    return engine, viewer


def cmd_run(args) -> int:
    config = load_config(args.config)
    src = config.source_path or "(defaults — no skroli.config.toml found)"
    print(f"skroli {__version__}")
    print(f"  config: {src}")
    print(f"  feeds: {len(config.rss.feeds)}, subreddits: {len(config.rss.subreddits)}")

    engine, viewer = _build(config)

    # Kick off the first fetch in the background — the UI opens immediately and
    # fills in as items stream over the WebSocket.
    engine.refresh()

    # Background polling at the configured interval.
    interval = max(config.runtime.poll_interval_minutes, 1) * 60

    def poll_loop():
        while True:
            time.sleep(interval)
            engine.refresh()

    threading.Thread(target=poll_loop, daemon=True).start()

    viewer.serve(open_window=args.window or config.runtime.open_window)
    return 0


def cmd_fetch(args) -> int:
    """Run a single cycle and exit (useful for testing without the server)."""
    config = load_config(args.config)
    engine, _ = _build(config)
    n = engine.run_once()
    print(f"  done: {n} items in feed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skroli", description=__doc__)
    parser.add_argument("--version", action="version", version=f"skroli {__version__}")
    parser.add_argument("-c", "--config", help="path to skroli.config.toml")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="run the pipeline and serve the viewer")
    p_run.add_argument("--window", action="store_true", help="open a native window (needs skroli[desktop])")
    p_run.set_defaults(func=cmd_run)

    p_fetch = sub.add_parser("fetch", help="run one cycle and exit (no server)")
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args.command = "run"
        args.func = cmd_run
        args.window = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
