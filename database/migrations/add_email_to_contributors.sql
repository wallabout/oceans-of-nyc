-- Add email column to contributors for stable web contributor identification
-- Migration: Web submissions can now use email to identify returning contributors

-- Add email column (nullable - email is optional)
ALTER TABLE contributors ADD COLUMN IF NOT EXISTS email VARCHAR(255);

-- Create index for case-insensitive email lookups
-- Using LOWER() for consistent matching regardless of case
CREATE INDEX IF NOT EXISTS idx_contributors_email_lower
ON contributors (LOWER(email)) WHERE email IS NOT NULL;
