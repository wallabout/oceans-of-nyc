ALTER TABLE contributors_badges
DROP CONSTRAINT contributors_badges_sighting_id_fkey;

ALTER TABLE contributors_badges
ADD CONSTRAINT contributors_badges_sighting_id_fkey
    FOREIGN KEY (sighting_id) REFERENCES sightings(id) ON DELETE CASCADE;
