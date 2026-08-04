"""Tag definitions for the community photo-tagging feature.

Tags are *nominations* from anonymous visitors on the website: "this photo is a
rare coffee-colored Ocean", "this one belongs in a coffee table book". Unlike
badges — which are earned by contributors and computed from SQL rules — tags are
crowd-sourced onto an individual sighting photo.

Each tag is defined with:
- name: Internal identifier, stored in ``sighting_tags.tag_name``
- display_name: Human-readable label shown in the tagging UI
- description: One-line explanation shown as a hint/tooltip
- emoji: Shown alongside the display name
- public: Whether the tag is displayed as a chip on the photo once earned.
  Moderation tags (``report``) are collected and filterable but never shown
  publicly, so a photo isn't publicly labelled as broken by a single visitor.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TagDefinition:
    """Definition of a photo tag visitors can nominate."""

    name: str
    display_name: str
    description: str
    emoji: str = ""
    public: bool = True


TAG_DEFINITIONS: list[TagDefinition] = [
    TagDefinition(
        name="rare_color_red",
        display_name="Rare Color: Red",
        description="One of the rare red Oceans",
        emoji="🟥",
    ),
    TagDefinition(
        name="rare_color_coffee",
        display_name="Rare Color: Coffee",
        description="One of the rare coffee-colored Oceans",
        emoji="🟫",
    ),
    TagDefinition(
        name="multi_ocean",
        display_name="Multi-Ocean",
        description="Two or more Oceans in a single frame",
        emoji="👯",
    ),
    TagDefinition(
        name="ca_mode",
        display_name="CA Mode",
        description="Rear window down — the Ocean in California Mode",
        emoji="🌴",
    ),
    TagDefinition(
        name="great_photography",
        display_name="Great Photography",
        description="A photo that belongs in a coffee table book",
        emoji="📸",
    ),
    TagDefinition(
        name="so_nyc",
        display_name="That's So NYC",
        description="A photo that captures New York City perfectly",
        emoji="🗽",
    ),
    TagDefinition(
        name="report",
        display_name="Report",
        description="Photo is broken, or isn't of the right vehicle",
        emoji="🚩",
        public=False,
    ),
]

# Lookup by internal name. Also serves as the allow-list for the tagging API —
# anything not in here is rejected rather than stored.
TAG_DEFINITIONS_BY_NAME: dict[str, TagDefinition] = {tag.name: tag for tag in TAG_DEFINITIONS}

TAG_NAMES: list[str] = [tag.name for tag in TAG_DEFINITIONS]


def get_tag(name: str) -> TagDefinition | None:
    """Return the tag definition for ``name``, or None if it isn't a known tag."""
    return TAG_DEFINITIONS_BY_NAME.get(name)


def is_valid_tag(name: str) -> bool:
    """Return True if ``name`` is a tag visitors are allowed to nominate."""
    return name in TAG_DEFINITIONS_BY_NAME
