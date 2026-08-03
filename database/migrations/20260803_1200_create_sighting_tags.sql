-- Community photo tags: anonymous visitors nominate attributes on a sighting's
-- photo ("rare color: coffee", "great photography", "report").
--
-- Visitors aren't logged in, so each row carries two weak identifiers instead of
-- a contributor_id: a browser-generated fingerprint (localStorage) and a salted
-- hash of the request IP. The unique index collapses the same person tagging the
-- same photo the same way more than once, so counts stay meaningful without
-- needing accounts.

CREATE TABLE IF NOT EXISTS sighting_tags (
    id SERIAL PRIMARY KEY,
    sighting_id INTEGER NOT NULL REFERENCES sightings(id) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    submitter_fingerprint TEXT NOT NULL,
    ip_hash TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One nomination per (photo, tag, person). Repeat submissions hit ON CONFLICT
-- DO NOTHING in the API and are silently dropped.
CREATE UNIQUE INDEX IF NOT EXISTS sighting_tags_unique_nomination
    ON sighting_tags (sighting_id, tag_name, submitter_fingerprint);

-- Aggregating counts per photo (web data generation) and per tag (filter view).
CREATE INDEX IF NOT EXISTS sighting_tags_sighting_id_idx ON sighting_tags (sighting_id);
CREATE INDEX IF NOT EXISTS sighting_tags_tag_name_idx ON sighting_tags (tag_name);

-- Backs the per-fingerprint rate limit check on write.
CREATE INDEX IF NOT EXISTS sighting_tags_fingerprint_created_at_idx
    ON sighting_tags (submitter_fingerprint, created_at DESC);

-- Aggregated view consumed by web/generate_data.py to build tags.json.
-- Counts DISTINCT fingerprints so a row-level duplicate that slips past the
-- unique index (e.g. from a backfill) still can't inflate a count.
CREATE OR REPLACE VIEW sighting_tags_export AS
SELECT
    sighting_id
    , tag_name
    , COUNT(DISTINCT submitter_fingerprint) AS nomination_count
    , MIN(created_at) AS first_tagged_at
    , MAX(created_at) AS last_tagged_at
FROM sighting_tags
GROUP BY sighting_id, tag_name;
