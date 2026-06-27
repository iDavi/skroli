"""skroli command line: ``skroli run`` (SPECS §5, ROADMAP P6)."""

from __future__ import annotations

import argparse
import sys
import threading
import time

from . import __version__
from .addons.rss_ingestor import RssIngestor
from .addons.score_enhancer import ScoreEnhancer
from .addons.skroli_viewer import SkroliViewer
from .config import load_config
from .pipeline import Pipeline
from .storage import Storage


def _build_pipeline(config) -> tuple[Pipeline, SkroliViewer]:
    storage = Storage(config.data_dir / "skroli.db")
    ingestors = [RssIngestor(config.rss)]
    enhancers = [ScoreEnhancer(config.score)]
    viewer = SkroliViewer(port=config.runtime.port, rss=config.rss, score=config.score)
    pipeline = Pipeline(config, storage, ingestors, enhancers, viewer)
    viewer._on_refresh = pipeline.run_cycle  # wire the "Refresh feed" button
    return pipeline, viewer


def cmd_run(args) -> int:
    config = load_config(args.config)
    src = config.source_path or "(defaults — no skroli.config.toml found)"
    print(f"skroli {__version__}")
    print(f"  config: {src}")
    print(f"  feeds: {len(config.rss.feeds)}, subreddits: {len(config.rss.subreddits)}")

    pipeline, viewer = _build_pipeline(config)

    print("  fetching…")
    pipeline.run_cycle()

    # Background polling at the configured interval.
    interval = max(config.runtime.poll_interval_minutes, 1) * 60

    def poll_loop():
        while True:
            time.sleep(interval)
            try:
                pipeline.run_cycle()
            except Exception as exc:  # noqa: BLE001
                print(f"  ! cycle failed: {exc}")

    threading.Thread(target=poll_loop, daemon=True).start()

    viewer.serve(open_window=args.window or config.runtime.open_window)
    return 0


def cmd_fetch(args) -> int:
    """Run a single cycle and exit (useful for testing without the server)."""
    config = load_config(args.config)
    pipeline, _ = _build_pipeline(config)
    n = pipeline.run_cycle()
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
