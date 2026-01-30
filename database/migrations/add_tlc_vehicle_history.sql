-- Add tlc_vehicle_history table for tracking historical Ocean vehicle counts
-- Migration: Create table to track daily counts of Fisker Ocean vehicles in TLC database

-- Create the vehicle history table
CREATE TABLE IF NOT EXISTS tlc_vehicle_history (
  date DATE NOT NULL PRIMARY KEY,
  ocean_count INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index for efficient date range queries
CREATE INDEX IF NOT EXISTS idx_tlc_history_date ON tlc_vehicle_history(date DESC);
