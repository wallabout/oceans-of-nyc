-- Refactor tlc_vehicle_history table to track both cumulative and active counts
-- Migration: Rename ocean_count to global_ocean_count and add active_ocean_count

-- Rename existing column to clarify it tracks cumulative unique vehicles
ALTER TABLE tlc_vehicle_history
  RENAME COLUMN ocean_count TO global_ocean_count;

-- Add column for active count (vehicles present in that day's TLC export)
-- Default to 0 for existing records; will be updated by re-running backfill
ALTER TABLE tlc_vehicle_history
  ADD COLUMN active_ocean_count INT NOT NULL DEFAULT 0;

-- Add comment to clarify the difference between the two counts
COMMENT ON COLUMN tlc_vehicle_history.global_ocean_count IS
  'Cumulative count of unique Fisker Ocean VINs ever seen in TLC data (never decreases)';

COMMENT ON COLUMN tlc_vehicle_history.active_ocean_count IS
  'Count of Fisker Ocean vehicles actively present in TLC export on this date (can decrease)';
