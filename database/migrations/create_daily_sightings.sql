DROP VIEW IF EXISTS daily_sightings_export;
CREATE VIEW daily_sightings_export AS

with daily_sightings as (
  select 
    s.timestamp_et::date as sighting_date
    , min(s.global_unique_sighting_index) as starting_vehicles_sighted
    , sum(case when s.vehicle_sighting_index = 1 then 1 else 0 end) as first_sighting_count
    , count(s.sighting_id) as sighting_count
  from sightings_export as s
  group by 1
  order by 1
)

select
  s.*
  , first_sighting_count / (sighting_count * 1.0) as first_sighting_rate
  , v.global_ocean_count
  , v.active_ocean_count
  , (global_ocean_count - starting_vehicles_sighted) / (global_ocean_count * 1.0) as expected_first_sighting_rate
  , avg(sighting_count) over (order by sighting_date rows between 6 preceding and current row) AS rolling_avg_7_days 
from daily_sightings as s
left join tlc_vehicle_history as v
    on s.sighting_date = v.date;