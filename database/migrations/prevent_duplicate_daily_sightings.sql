-- Migration: Prevent duplicate sightings (same vehicle + contributor + calendar day)
--
-- Step 1 (required): Remove existing duplicates, keeping the earliest sighting per group.
-- Review the duplicates first:
--
  SELECT license_plate, contributor_id,
         DATE(timestamp AT TIME ZONE 'America/New_York') AS sighting_date,
         COUNT(*), array_agg(id ORDER BY created_at) AS ids
  FROM sightings
  WHERE contributor_id IS NOT NULL AND timestamp IS NOT NULL
  GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;
--
-- Then delete all but the first submission in each group:
--
--   DELETE FROM sightings
--   WHERE id IN (
--       SELECT id FROM (
--           SELECT id,
--                  ROW_NUMBER() OVER (
--                      PARTITION BY license_plate, contributor_id,
--                                   DATE(timestamp AT TIME ZONE 'America/New_York')
--                      ORDER BY created_at
--                  ) AS rn
--           FROM sightings
--           WHERE contributor_id IS NOT NULL AND timestamp IS NOT NULL
--       ) t
--       WHERE rn > 1
--   );
--
-- Step 2: Add the unique index (only after Step 1 completes successfully).

CREATE UNIQUE INDEX CONCURRENTLY idx_sightings_no_daily_duplicate
ON sightings (license_plate, contributor_id, DATE(timestamp AT TIME ZONE 'America/New_York'))
WHERE contributor_id IS NOT NULL AND timestamp IS NOT NULL;
