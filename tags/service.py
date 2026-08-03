"""Helpers for accepting anonymous photo-tag nominations.

Visitors aren't logged in, so "who tagged this" is approximated with two weak
identifiers that are enough to collapse repeat nominations from one person:

- a **fingerprint**: a random id the browser generates once and keeps in
  ``localStorage``. Stable for a person until they clear site data.
- an **IP hash**: a salted SHA-256 of the request IP. Never store the raw IP —
  it's only kept as a hashed fallback identifier and for spotting abuse.

Neither is trustworthy on its own (a determined user can reset both), which is
fine: tags are a popularity signal, not a vote of record. The unique index on
``(sighting_id, tag_name, submitter_fingerprint)`` drops the common case of the
same person tagging the same photo repeatedly.
"""

import hashlib
import os
import re
from collections.abc import Mapping
from typing import Any

from tags.definitions import is_valid_tag

# Fingerprints are generated client-side (crypto.randomUUID) so we only accept a
# conservative charset and length — this value ends up in a SQL unique index.
_FINGERPRINT_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

# Max nominations a single fingerprint may record in the rate-limit window,
# beyond which we stop writing rows. Tagging is a couple of clicks per photo, so
# this is far above enthusiastic use and only trips on scripted spam.
RATE_LIMIT_MAX_TAGS = 200
RATE_LIMIT_WINDOW_MINUTES = 60


def hash_ip(ip: str | None) -> str | None:
    """
    Hash a request IP with the ``TAG_IP_SALT`` pepper.

    Returns None when there's no IP to hash. The salt makes the hash useless for
    reversing back to an address by brute-forcing the (small) IPv4 space.
    """
    if not ip:
        return None
    salt = os.getenv("TAG_IP_SALT", "oceans-of-nyc")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def normalize_fingerprint(fingerprint: str | None, ip_hash: str | None = None) -> str | None:
    """
    Validate a client-supplied fingerprint, falling back to the IP hash.

    Args:
        fingerprint: Raw value sent by the browser (may be None or junk)
        ip_hash: Hashed request IP, used when the fingerprint is missing/invalid

    Returns:
        A fingerprint safe to store, or None when neither identifier is usable
        (in which case the nomination can't be de-duplicated and is rejected).
    """
    if fingerprint:
        candidate = fingerprint.strip()
        if _FINGERPRINT_RE.match(candidate):
            return candidate
    if ip_hash:
        # Prefix so an IP-derived fallback is distinguishable from a real one.
        return f"ip-{ip_hash}"
    return None


def client_ip(headers: Mapping[str, str], fallback: str | None = None) -> str | None:
    """
    Extract the originating client IP from proxy headers.

    Modal terminates TLS in front of the app, so ``request.client.host`` is the
    proxy. ``X-Forwarded-For`` holds the chain, with the original client first.

    Args:
        headers: Request headers (case-insensitive mapping, e.g. Starlette's)
        fallback: Value to use when no forwarding header is present

    Returns:
        The client IP as a string, or None.
    """
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return fallback


def truncate_user_agent(user_agent: str | None, max_length: int = 300) -> str | None:
    """Trim a User-Agent string to a sane storage length (None stays None)."""
    if not user_agent:
        return None
    return user_agent[:max_length]


def process_tag_request(
    db: Any,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    client_host: str | None = None,
) -> tuple[int, dict]:
    """
    Validate and store one tag nomination.

    This is the whole body of the ``POST /tag`` endpoint, kept out of
    ``modal_app.py`` so it can be tested without Modal or a live database.

    Args:
        db: Object exposing ``count_recent_tags_by_fingerprint`` and ``add_sighting_tag``
        body: Parsed JSON request body
        headers: Request headers (lower-cased keys, e.g. Starlette's Headers)
        client_host: Socket peer address, used when no forwarding header is present

    Returns:
        (status_code, response_body). ``recorded`` is False when the nomination
        was a duplicate from this visitor or the sighting doesn't exist — both
        are successful outcomes as far as the caller is concerned.
    """
    tag_name = str(body.get("tag") or "").strip()
    if not is_valid_tag(tag_name):
        return 400, {"success": False, "error": "unknown_tag"}

    # Strict: a float or "12abc" would otherwise coerce to some *other* photo's
    # id, so only a whole positive number (or its digit string) is accepted.
    raw_id = body.get("sighting_id")
    if isinstance(raw_id, bool):
        sighting_id = None
    elif isinstance(raw_id, int):
        sighting_id = raw_id
    elif isinstance(raw_id, str) and raw_id.strip().isdigit():
        sighting_id = int(raw_id.strip())
    else:
        sighting_id = None
    if sighting_id is None or sighting_id <= 0:
        return 400, {"success": False, "error": "invalid_sighting_id"}

    ip_hash = hash_ip(client_ip(headers, client_host))
    fingerprint = normalize_fingerprint(body.get("fingerprint"), ip_hash)
    if not fingerprint:
        # With no identifier at all we can't de-duplicate, so we don't store it.
        return 400, {"success": False, "error": "missing_fingerprint"}

    recent = db.count_recent_tags_by_fingerprint(fingerprint, RATE_LIMIT_WINDOW_MINUTES)
    if recent >= RATE_LIMIT_MAX_TAGS:
        return 429, {"success": False, "error": "rate_limited"}

    recorded = db.add_sighting_tag(
        sighting_id=sighting_id,
        tag_name=tag_name,
        submitter_fingerprint=fingerprint,
        ip_hash=ip_hash,
        user_agent=truncate_user_agent(headers.get("user-agent")),
    )
    return 200, {"success": True, "recorded": bool(recorded)}
