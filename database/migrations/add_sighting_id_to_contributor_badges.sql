ALTER TABLE contributors_badges
ADD COLUMN sighting_id INTEGER REFERENCES sightings(id);
