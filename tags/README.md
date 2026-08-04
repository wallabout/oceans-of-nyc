"Tags" are community nominations on a *photo*, not achievements for a contributor.

Badges are earned and computed from SQL rules about a contributor's sightings.
Tags are the opposite: any visitor, logged in or not, can look at a photo and say
"that's a rare coffee-colored one" or "that belongs in a coffee table book".


# Where tagging happens

* `/feed` — a "Tag photo" button on every card opens the picker in a modal
* `/random` — one photo at a time, biased toward photos nobody has tagged yet,
  so the archive of older sightings gets covered too
* `/tagged` — the filter view: every photo that has earned a tag, filterable by
  tag and sortable by how many nominations it has


# Tag definitions

`definitions.py` is the single source of truth and doubles as the API's
allow-list — a nomination for anything not defined there is rejected rather than
stored. `web/src/lib/tags.ts` carries a copy of the list purely as a fallback for
the moment before `tags.json` loads; keep the two in sync when adding a tag.

Tags marked `public=False` (currently just `report`) are collected and
filterable, but never rendered as a chip on the photo — one visitor shouldn't be
able to publicly label someone's submission as broken.


# Identity without accounts

Visitors aren't logged in, so each nomination carries two weak identifiers:

* a **fingerprint** — a random id the browser generates once and keeps in
  `localStorage`
* an **ip_hash** — a salted SHA-256 of the request IP (`TAG_IP_SALT`). Raw IPs
  are never stored.

A unique index on `(sighting_id, tag_name, submitter_fingerprint)` drops repeat
nominations from the same person, and the fingerprint falls back to `ip-<hash>`
when the browser doesn't send one. Neither identifier is authoritative — a
determined user can reset both — which is fine, because tags are a popularity
signal rather than a vote of record. A per-fingerprint rate limit keeps scripted
spam from reaching the table at all.


# Data flow

```
browser  --POST /tag-->  web_tag_webhook  -->  sighting_tags
                                |
                                +--spawn--> refresh_tag_data --> R2 web/tags.json
```

The browser never waits on the response: the picker locks the button, the chip
appears optimistically, and a failed request is a lost vote rather than an error
the visitor has to see.

Counts are published to `tags.json`, separate from the much larger
`oceans.json`, because they change on every click and the payload is tiny. The
refresh is guarded by a Postgres advisory lock so a burst of tags produces one
regeneration, with a 15-minute scheduled run as a backstop.


# Tag ideas

* Rare Color: Red
* Rare Color: Coffee
* Multi-Ocean — two or more Oceans in one frame
* CA Mode — rear window down, the Ocean in California Mode
* Great Photography — belongs in a coffee table book
* That's So NYC — captures the city well
* Report — broken photo, or not the right vehicle
