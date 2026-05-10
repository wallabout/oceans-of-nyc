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
  , dos.global_ocean_count
  , dos.active_ocean_count
  , dos.expected_first_sighting_rate
  , avg(sighting_count) over (order by s.sighting_date rows between 6 preceding and current row) AS rolling_avg_7_days
from daily_sightings as s
left join daily_ocean_stats as dos
    on s.sighting_date = dos.sighting_date;