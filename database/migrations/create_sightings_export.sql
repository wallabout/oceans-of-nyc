DROP VIEW IF EXISTS sightings_export;
CREATE VIEW sightings_export AS
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
  from sightings
)

, sightings_with_uniques as (

  select
    *
    , sum (
        case when vehicle_sighting_index = 1 then 1 else 0 end
      ) over (
          order by created_at rows between unbounded preceding and current row
      ) as global_unique_sighting_index
    , sum (
        case when vehicle_sighting_index = 1 then 1 else 0 end
      ) over (
          partition by contributor_id
          order by created_at rows between unbounded preceding and current row
      ) as contributor_unique_sighting_index
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
from sightings_with_uniques as s
join contributors as c
  on c.id = s.contributor_id
order by global_sighting_index;
