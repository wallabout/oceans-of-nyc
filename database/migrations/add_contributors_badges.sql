-- Add contributors_badges table for Bumper Stickers gamification feature
-- Migration: Create table to track badges earned by contributors

-- Create the badges table
CREATE TABLE IF NOT EXISTS contributors_badges (
  contributor_id INT NOT NULL REFERENCES contributors(id),
  badge_name TEXT NOT NULL,
  earned_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (contributor_id, badge_name)
);

-- Add indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_badges_contributor ON contributors_badges(contributor_id);
CREATE INDEX IF NOT EXISTS idx_badges_earned_on ON contributors_badges(earned_on);
