"""Config schema for the image-discovery ingestor."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.addons_base import Field, Section

# A starter spread of image-heavy, eclectic subreddits — the "all kinds of
# esoteric photos" Pinterest feel. Fully editable in the UI.
DEFAULT_SUBS = [
    "ArtPorn",
    "ImaginaryLandscapes",
    "AccidentalRenaissance",
    "itookapicture",
    "RetroFuturism",
    "brutalism",
    "AbandonedPorn",
    "CozyPlaces",
    "DesignPorn",
    "vintageads",
    "AnaloguePhotography",
    "SpacePorn",
]


@dataclass
class ImagesConfig:
    enabled: bool = True
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBS))
    count: int = 100  # posts per fetch across ALL subreddits (one request)


SECTION = Section(
    id="images", group="ingestor", title="Images", attr="images",
    desc="Fills the Images grid with photos from image-centric subreddits. All "
         "subreddits are fetched in a single batched request (r/a+b+c), so "
         "adding more costs nothing against Reddit's rate limit.",
    fields=[
        Field("enabled", "toggle"),
        Field("subreddits", "list", label="Image subreddits", prefix="r/",
              placeholder="subreddit"),
        Field("count", "int", label="Images per fetch (all subs combined)",
              min=10, max=100, step=10),
    ],
)
