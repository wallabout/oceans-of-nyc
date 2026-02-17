-- Create tlc_vehicles_minimal table for efficient VIN-to-plate lookups
-- Migration: Create minimal table with only essential columns for plate validation
-- This table tracks the relationship between VINs and license plates with date ranges

-- Create the minimal vehicles table
CREATE TABLE IF NOT EXISTS tlc_vehicles_minimal (
  license_plate TEXT NOT NULL,
  vin TEXT NOT NULL,
  first_reported_on DATE NOT NULL,
  most_recently_reported_on DATE NOT NULL,
  PRIMARY KEY (vin, license_plate)
);

-- Add indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_tlc_vehicles_minimal_plate ON tlc_vehicles_minimal(license_plate);
CREATE INDEX IF NOT EXISTS idx_tlc_vehicles_minimal_vin ON tlc_vehicles_minimal(vin);
CREATE INDEX IF NOT EXISTS idx_tlc_vehicles_minimal_recent ON tlc_vehicles_minimal(most_recently_reported_on DESC);

-- Add comments to document the table and columns
COMMENT ON TABLE tlc_vehicles_minimal IS
  'Minimal table tracking VIN-to-license-plate relationships from TLC data. Used for efficient plate validation.';

COMMENT ON COLUMN tlc_vehicles_minimal.license_plate IS
  'DMV license plate number (renamed from dmv_license_plate_number for clarity)';

COMMENT ON COLUMN tlc_vehicles_minimal.vin IS
  'Vehicle Identification Number (renamed from vehicle_vin_number for clarity)';

COMMENT ON COLUMN tlc_vehicles_minimal.first_reported_on IS
  'Date this VIN+plate combination was first seen in TLC data';

COMMENT ON COLUMN tlc_vehicles_minimal.most_recently_reported_on IS
  'Most recent date this VIN+plate combination was seen in TLC data';
