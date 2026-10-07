-- Drops unsighted inactive Oceans from the "how many Oceans are there to find"
-- denominator.
--
-- An Ocean is inactive once it's missing from the latest TLC snapshot: none of
-- its plates were reported on the most recent most_recently_reported_on date
-- (the same rule as the grid's "Inactive" filter). Inactive Oceans nobody ever
-- sighted can no longer be found, so they leave the denominator. An Ocean that
-- was sighted stays in it for good.
--
-- ocean_findability has one row per VIN and is the single source of the rule:
--   * is_findable: counted today (active, or sighted at least once)
--   * the date columns let daily_ocean_stats count Oceans as of any past day:
--     debuted by then, and either still active then or already sighted.
CREATE OR REPLACE VIEW ocean_findability AS
with latest_report as (
  select max(most_recently_reported_on::date) as reported_on
  from tlc_vehicles
),

vehicles as (
  select
    vin
    , min(first_reported_on::date) as tlc_debut_on
    , max(most_recently_reported_on::date) as last_reported_on
  from tlc_vehicles
  group by vin
),

first_sightings as (
  select
    vin
    , min((created_at::timestamptz AT TIME ZONE 'America/New_York')::date) as first_sighted_on
  from sightings
  group by vin
)

select
  v.vin
  , v.tlc_debut_on
  , v.last_reported_on
  , f.first_sighted_on
  , v.last_reported_on = l.reported_on as is_active
  , v.last_reported_on = l.reported_on or f.first_sighted_on is not null as is_findable
from vehicles as v
cross join latest_report as l
left join first_sightings as f
  on v.vin = f.vin;

-- Expected first sighting rate now divides by the Oceans findable on each day
-- instead of every Ocean the TLC has ever listed. findable_ocean_count is
-- appended as the last column so CREATE OR REPLACE keeps the existing ones.
--
-- Otherwise identical to create_daily_ocean_stats.sql.
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

daily_findable as (
  select
    d.sighting_date
    , count(o.vin) as findable_ocean_count
  from daily_starting as d
  left join ocean_findability as o
    on (o.tlc_debut_on is null or o.tlc_debut_on <= d.sighting_date)
    and (
      o.is_active
      or o.last_reported_on >= d.sighting_date
      or o.first_sighted_on <= d.sighting_date
    )
  group by 1
),

daily_joined as (
  select
    d.sighting_date
    , d.starting_vehicles_sighted
    , v.global_ocean_count
    , v.active_ocean_count
    , f.findable_ocean_count
  from daily_starting as d
  left join tlc_vehicle_history as v
    on d.sighting_date = v.date
  left join daily_findable as f
    on d.sighting_date = f.sighting_date
),

-- count(col) over (...) advances only on non-null values, assigning each run of nulls
-- to the same group as the preceding non-null so max() can fill them forward
grouped as (
  select
    sighting_date
    , starting_vehicles_sighted
    , global_ocean_count
    , active_ocean_count
    , findable_ocean_count
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
    , findable_ocean_count
  from grouped
)

select
  sighting_date
  , starting_vehicles_sighted
  , global_ocean_count
  , active_ocean_count
  , (findable_ocean_count - starting_vehicles_sighted) / nullif(findable_ocean_count * 1.0, 0) as expected_first_sighting_rate
  , findable_ocean_count
from filled;
