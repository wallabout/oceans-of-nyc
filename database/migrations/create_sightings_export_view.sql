-- Create sightings_export view with VIN-based partitioning
-- This view provides enriched sighting data with indexes for analytics

CREATE OR REPLACE VIEW sightings_export AS
WITH base_sightings AS (
    SELECT
        s.id,
        s.license_plate,
        COALESCE(s.vin, t.vin) as vin,
        s.timestamp,
        s.borough,
        s.image_filename,
        s.contributor_id,
        c.preferred_name as contributor_name,
        c.phone_number,
        c.bluesky_handle,
        c.email
    FROM sightings s
    LEFT JOIN contributors c ON s.contributor_id = c.id
    LEFT JOIN LATERAL (
        SELECT vin
        FROM tlc_vehicles_minimal
        WHERE license_plate = s.license_plate
        ORDER BY most_recently_reported_on DESC
        LIMIT 1
    ) t ON true
    WHERE COALESCE(s.vin, t.vin) IS NOT NULL
),
sighting_indexes AS (
    SELECT
        *,
        -- Vehicle sighting index: 1st, 2nd, 3rd sighting for this VIN
        ROW_NUMBER() OVER (
            PARTITION BY vin
            ORDER BY timestamp
        ) as vehicle_sighting_index,
        -- Global sighting index: all sightings numbered chronologically
        ROW_NUMBER() OVER (
            ORDER BY timestamp
        ) as global_sighting_index,
        -- Contributor vehicle sighting index: 1st, 2nd, 3rd sighting of this VIN by this contributor
        ROW_NUMBER() OVER (
            PARTITION BY contributor_id, vin
            ORDER BY timestamp
        ) as contributor_vehicle_sighting_index
    FROM base_sightings
),
unique_sighting_numbers AS (
    SELECT
        *,
        -- Number only the first sightings per VIN chronologically
        CASE
            WHEN vehicle_sighting_index = 1 THEN
                DENSE_RANK() OVER (
                    ORDER BY CASE WHEN vehicle_sighting_index = 1 THEN timestamp END
                )
            ELSE NULL
        END as global_unique_sighting_index,
        -- Number only the first sightings per VIN per contributor chronologically
        CASE
            WHEN contributor_vehicle_sighting_index = 1 THEN
                DENSE_RANK() OVER (
                    PARTITION BY contributor_id
                    ORDER BY CASE WHEN contributor_vehicle_sighting_index = 1 THEN timestamp END
                )
            ELSE NULL
        END as contributor_unique_sighting_index
    FROM sighting_indexes
)
SELECT
    id,
    license_plate,
    vin,
    timestamp,
    borough,
    image_filename,
    contributor_id,
    contributor_name,
    phone_number,
    bluesky_handle,
    email,
    vehicle_sighting_index,
    global_sighting_index,
    contributor_vehicle_sighting_index,
    global_unique_sighting_index,
    contributor_unique_sighting_index
FROM unique_sighting_numbers
ORDER BY timestamp;

-- Add comment explaining the view
COMMENT ON VIEW sightings_export IS 'Enriched sighting data with VIN-based partitioning for analytics and exports';
