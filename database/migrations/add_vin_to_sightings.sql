-- Add VIN column to sightings table to track the vehicle identity
-- This allows us to properly track vehicles even when they change license plates

ALTER TABLE sightings
ADD COLUMN vin TEXT;

-- Add index on VIN for efficient lookups
CREATE INDEX idx_sightings_vin ON sightings(vin);

-- Add comment to document the column
COMMENT ON COLUMN sightings.vin IS 'Vehicle Identification Number from TLC database, populated when license plate is validated';
