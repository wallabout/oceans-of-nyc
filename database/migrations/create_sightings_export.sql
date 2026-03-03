CREATE OR REPLACE VIEW sightings_export AS
with indexed_sightings as (
  select
    id as sighting_id
    , vin
    , license_plate
    , contributor_id
    , borough
    , image_filename
    , timestamp 
    , ROW_NUMBER() over(order by timestamp) as global_sighting_index
    , ROW_NUMBER() over(partition by vin order by timestamp) as vehicle_sighting_index
    , ROW_NUMBER() over(partition by contributor_id order by timestamp) as contributor_sighting_index
  from sightings
)

, sightings_with_uniques as (

  select
    *
    , sum (
        case when vehicle_sighting_index = 1 then 1 else 0 end
      ) over (
          order by timestamp rows between unbounded preceding and current row
      ) as global_unique_sighting_index
    , sum (
        case when vehicle_sighting_index = 1 then 1 else 0 end
      ) over (
          partition by contributor_id
          order by timestamp rows between unbounded preceding and current row
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
  , timestamp AT TIME ZONE 'America/New_York' as timestamp_et
  , borough
  , image_filename
  , global_sighting_index
  , global_unique_sighting_index
  , vehicle_sighting_index
  , contributor_sighting_index
  , contributor_unique_sighting_index
from sightings_with_uniques
join contributors as c
  on c.id = sightings_with_uniques.contributor_id
order by global_sighting_index;