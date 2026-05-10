CREATE OR REPLACE VIEW daily_ocean_stats AS

with indexed_first_sightings as (
  select
    (created_at::timestamptz AT TIME ZONE 'America/New_York')::date as sighting_date
    , created_at::timestamptz AT TIME ZONE 'America/New_York' as timestamp_et
    , ROW_NUMBER() over(partition by vin order by created_at) as vehicle_sighting_index
  from sightings
),

running_uniques as (
  select
    sighting_date
    , count(*) over (order by timestamp_et rows between unbounded preceding and current row) as global_unique_sighting_index
  from indexed_first_sightings
  where vehicle_sighting_index = 1
),

daily_starting as (
  select
    sighting_date
    , min(global_unique_sighting_index) as starting_vehicles_sighted
  from running_uniques
  group by 1
),

daily_joined as (
  select
    d.sighting_date
    , d.starting_vehicles_sighted
    , v.global_ocean_count
    , v.active_ocean_count
  from daily_starting as d
  left join tlc_vehicle_history as v
    on d.sighting_date = v.date
),

-- count(col) over (...) advances only on non-null values, assigning each run of nulls
-- to the same group as the preceding non-null so max() can fill them forward
grouped as (
  select
    sighting_date
    , starting_vehicles_sighted
    , global_ocean_count
    , active_ocean_count
    , count(global_ocean_count) over (order by sighting_date) as grp_global
    , count(active_ocean_count) over (order by sighting_date) as grp_active
  from daily_joined
),

filled as (
  select
    sighting_date
    , starting_vehicles_sighted
    , max(global_ocean_count) over (partition by grp_global) as global_ocean_count
    , max(active_ocean_count) over (partition by grp_active) as active_ocean_count
  from grouped
)

select
  sighting_date
  , starting_vehicles_sighted
  , global_ocean_count
  , active_ocean_count
  , (global_ocean_count - starting_vehicles_sighted) / (global_ocean_count * 1.0) as expected_first_sighting_rate
from filled;
