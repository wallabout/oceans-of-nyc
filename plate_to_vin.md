
# 1. TLC data
* ✅ create tlc_vehicles_minimal table with only 4 columns
    - license_plate (renamed from dmv_license_plate_number)
    - vin (renamed from vehicle_vin_number)
    - first_reported_on - based on date of TLC snapshot
    - most_recently_reported_on - based on date of TLC snapshot
* ✅ create license_plate+vin compound key and uniqueness constraint
* ✅ update nightly loading function to populate new schema
    - import_tlc_data() now populates both tlc_vehicles and tlc_vehicles_minimal
    - import_to_minimal_only() available for minimal-only imports
* ✅ tlc_history.global_ocean_count already uses count of distinct VIN values
* ✅ tlc_history.active_ocean_count already uses count of distinct VIN values
* 🔄 re-process all existing tlc data files in chronological order (IN PROGRESS)
    * 🔄 populate tlc_vehicles_minimal (running now via migrate_tlc_vehicles_minimal.py)
    * ⏸️ drop and re-populate tlc_vehicle_history (deferred - not needed for minimal table)
* ✅ update read-references to tlc_vehicles to use tlc_vehicles_minimal
    - get_vehicle_by_plate() now queries tlc_vehicles_minimal
    - get_tlc_vehicle_by_plate() now queries tlc_vehicles_minimal
    - validate_plate() returns data from tlc_vehicles_minimal

# 2. Sightings
* ✅ add vin column to sightings table (already existed, nullable)
* ✅ when confirming the validity of a plate, get the most recent record based on tlc_vehicles_minimal.most_recently_reported_on
    * ✅ return the vin from that record
* ✅ write both the vin and license_plate to a new sightings record
    * ✅ web submission pathway (modal_app.py)
    * ✅ SMS submission pathways (chat/webhook.py - 3 pathways)
    * ✅ CLI submission pathways (main.py - 2 pathways)
* ✅ when confirming a sighting, report the new count of sightings by VIN not license_plate
    * ✅ created get_sighting_count_by_vin() method
    * ✅ updated get_confirmation_data() to use VIN-based counts when available
    * ✅ updated all 5 call sites to pass VIN parameter

# 3. Generate Data
* ✅ when generating vehicles.json for use in the static site, vin should be the primary identifier
* ✅ license_plates should be an array as there may be more than one associated with the vin (sorted alphabetically)
* ✅ the sightings array should include a key for license_plate
* ✅ add a new array of license_plate_history records, one per record in tlc_vehicles_minimal with
    * license_plate
    * first_reported_on
    * most_recently_reported_on
* ✅ removed unused sighting fields: globalUniqueSightingIndex, vehicleSightingIndex, contributorSightingIndex, contributorUniqueSightingIndex
* ✅ updated generate_web_sightings_data() in web/generate_data.py
    * queries tlc_vehicles_minimal instead of tlc_vehicles
    * uses COALESCE to get VIN from sightings or tlc_vehicles_minimal (for backfill compatibility)
    * includes all VINs even those without sightings

# 4. Web
* ✅ the vehicle modal headers should contain a comma concatenated list of licenses plates
* ✅ the vehicle modal should display the VIN under the image
* ✅ the vehicle modal should display the License Plate records beneath the sightings
* ✅ updated web/index.html to use new VIN-centric data structure
    * modal title shows comma-separated license plates
    * VIN displayed as first row in modal info
    * license plate history table added below sightings
    * tile overlay shows comma-separated plates (removed borough)
    * image alt text uses comma-separated plates
    * sorting updated to use first plate from license_plates array 

# 5. Stats
* ✅ add vin to sightings_export
* ✅ the sightings_export view should partition based on vin rather than license_plate
    * ✅ global_unique_sighting_index
    * ✅ vehicle_sighting_index
    * ✅ contributor_unique_sighting_index
* ✅ the nav-stats should report the total Ocean population as the count distinct vin rather than license_plate
    * nav-stats already uses data.total from vehicles.json which counts unique VINs
    * generate_data.py builds vehicles array from SELECT DISTINCT vin

# 6. Follow-ups
* ✅ backfill sightings.vin
    * scripts/backfill_sightings_vin.py - dry run by default, --apply to commit
    * uses most recently reported VIN per plate from tlc_vehicles_minimal

# Test Updates
* ✅ updated test fixtures to populate both tlc_vehicles and tlc_vehicles_minimal
    * ✅ conftest.py - sample_tlc_vehicles fixture
    * ✅ test_database_tlc.py - 3 test methods with direct inserts
    * ✅ all 25 TLC database tests passing