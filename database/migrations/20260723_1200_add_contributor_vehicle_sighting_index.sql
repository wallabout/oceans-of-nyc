-- Adds contributor_vehicle_sighting_index to sightings_export: how many times a
-- given contributor has sighted a given vehicle (by VIN), used to tell contributors
-- "your Nth time spotting this Ocean" in the sighting confirmation.
--
-- This is a NEW migration rather than an edit to create_sightings_export.sql because
-- the deploy runner keys on filename and applies each file exactly once; editing an
-- already-applied migration in place would be silently skipped in production.
CREATE OR REPLACE VIEW sightings_export AS
with indexed_sightings as (
  select
    id as sighting_id
    , vin
    , license_plate
    , contributor_id
    , borough
    , image_filename
    , created_at
    , ROW_NUMBER() over(order by created_at) as global_sighting_index
    , ROW_NUMBER() over(partition by vin order by created_at) as vehicle_sighting_index
    , ROW_NUMBER() over(partition by contributor_id order by created_at) as contributor_sighting_index
    , ROW_NUMBER() over(partition by vin, contributor_id order by created_at) as contributor_vehicle_sighting_index
  from sightings
)

, sightings_with_uniques as (

  select
    *
    , case when vehicle_sighting_index = 1 then
        sum (
          case when vehicle_sighting_index = 1 then 1 else 0 end
        ) over (
            order by created_at rows between unbounded preceding and current row
        )
      else null
      end as global_unique_sighting_index
    , sum (
        case when vehicle_sighting_index = 1 then 1 else 0 end
      ) over (
          partition by contributor_id
          order by created_at rows between unbounded preceding and current row
      ) as contributor_unique_sighting_index
    , sum(case when vehicle_sighting_index = 1 then 1 else 0 end) over (
          order by created_at rows between 200 preceding and 1 preceding
      )::numeric
      / count(*) over (order by created_at rows between 200 preceding and 1 preceding)
      as rolling_first_sighting_rate
  from indexed_sightings
)

select
  sighting_id
  , vin
  , license_plate
  , contributor_id
  , c.preferred_name
  , c.bluesky_handle
  , s.created_at::timestamptz AT TIME ZONE 'America/New_York' as timestamp_et
  , borough
  , image_filename
  , global_sighting_index
  , global_unique_sighting_index
  , vehicle_sighting_index
  , contributor_sighting_index
  , contributor_unique_sighting_index
  , case when s.vehicle_sighting_index = 1 then 1.0 / NULLIF(s.rolling_first_sighting_rate, 0) else 0 end as ocean_points
  , rolling_first_sighting_rate
  -- Appended at the end so CREATE OR REPLACE VIEW can add it without a DROP
  -- (Postgres only allows new view columns to be added after existing ones).
  , contributor_vehicle_sighting_index
from sightings_with_uniques as s
join contributors as c
  on c.id = s.contributor_id
order by global_sighting_index;
