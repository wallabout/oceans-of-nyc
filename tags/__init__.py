"""Community photo tagging: definitions and submission helpers."""

from tags.definitions import (
    TAG_DEFINITIONS,
    TAG_DEFINITIONS_BY_NAME,
    TAG_NAMES,
    TagDefinition,
    get_tag,
    is_valid_tag,
)
from tags.service import (
    RATE_LIMIT_MAX_TAGS,
    RATE_LIMIT_WINDOW_MINUTES,
    client_ip,
    hash_ip,
    normalize_fingerprint,
    process_tag_request,
    truncate_user_agent,
)

__all__ = [
    "RATE_LIMIT_MAX_TAGS",
    "RATE_LIMIT_WINDOW_MINUTES",
    "TAG_DEFINITIONS",
    "TAG_DEFINITIONS_BY_NAME",
    "TAG_NAMES",
    "TagDefinition",
    "client_ip",
    "get_tag",
    "hash_ip",
    "is_valid_tag",
    "normalize_fingerprint",
    "process_tag_request",
    "truncate_user_agent",
]
