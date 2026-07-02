"""Config schema for the image-discovery ingestor."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.addons_base import Field, Section

# A wide default spread so every kind of user finds something — art, fashion,
# subcultures, spaces, nature, food, retro, daily life. All of it is fetched in
# batched multireddit requests, so breadth costs (almost) nothing against
# Reddit's rate limit. Fully editable in the UI.
DEFAULT_SUBS = [
    # art & illustration
    "ArtPorn", "ImaginaryLandscapes", "museum", "Graffiti",
    # photography
    "itookapicture", "AnaloguePhotography",
    # history & retro
    "OldSchoolCool", "TheWayWeWere", "vintageads", "RetroFuturism",
    "AccidentalRenaissance",
    # design & spaces
    "DesignPorn", "RoomPorn", "CozyPlaces", "CabinPorn", "brutalism",
    "ArchitecturePorn", "AbandonedPorn",
    # fashion & subcultures
    "streetwear", "sneakers", "malefashion", "VintageFashion",
    "VaporwaveAesthetics", "cottagecore", "tattoos",
    # nature & space
    "EarthPorn", "BotanicalPorn", "houseplants", "SpacePorn",
    # daily life
    "FoodPorn", "Breadit", "carporn",
]

# Non-Reddit image feeds (any RSS/Atom whose entries carry pictures).
DEFAULT_FEEDS = [
    "https://apod.nasa.gov/apod.rss",                                               # NASA astronomy picture of the day
    "https://commons.wikimedia.org/w/api.php?action=featuredfeed&feed=potd&feedformat=atom",  # Wikimedia picture of the day
    "https://www.thisiscolossal.com/feed/",                                         # art & visual culture
]

SORTS = ["hot", "new", "rising", "top-week", "top-month", "top-all"]


@dataclass
class ImagesConfig:
    enabled: bool = True
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBS))
    feeds: list[str] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    sort: str = "hot"
    count: int = 100  # posts per batched reddit request
    allow_nsfw: bool = False


SECTION = Section(
    id="images", group="ingestor", title="Images", attr="images",
    desc="Fills the Images grid: image-centric subreddits (fetched in batched "
         "r/a+b+c requests, so adding more is nearly free) plus any RSS/Atom "
         "feeds that carry pictures (art blogs, picture-of-the-day feeds…).",
    fields=[
        Field("enabled", "toggle"),
        Field("subreddits", "list", label="Image subreddits", prefix="r/",
              placeholder="subreddit"),
        Field("feeds", "list", label="Image feeds (RSS/Atom)",
              placeholder="https://example.com/feed.xml"),
        Field("sort", "select", label="Reddit sort", options=SORTS),
        Field("count", "int", label="Images per reddit fetch", min=10, max=100, step=10),
        Field("allow_nsfw", "toggle", label="allow NSFW"),
    ],
)
