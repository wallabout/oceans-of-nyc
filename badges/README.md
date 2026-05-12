"Badges" is a gamification feature in Oceans of NYC. 


# Badge definition and evaluation
Each badge will be definable based on the sightings record of a contributor. For example 
* "10 Club" would be earned by having 10 or more records in the sightings table.
* "5 boro" would be earned by the count of distinct boroughs = 5
* "Busy week" would be earned by the count of sightings >= 7 in a given calendar week

For this reason, I believe the badge definitions should be expressed as modular SQL. 

After each new sighting is confirmed
- identify the badges the contributor does NOT have
- evaluate each potential badge
- persist each new badge earned to contributors_badges
- if the sighting was reported by SMS, message indicating the badge

# Data Structure

contributors_badges - many:many relationship table persisting the badge's each 
* contributor_id
* badge
* earned_on


# Badge ideas

* Ocean Spotter - 1st sighting
* 5 Club - 5 sightings all-time
* 10 Club - 10 sightings all-time
* 25 Club - 25 sightings all-time
* 50 Club - 50 sightings all-time
* 100 Club - 100 sightings all-time
* Busy week - got 7 sightings in a week 
* Busy month - got 30 sightings in a month
* Week-Streak x 4 - at least one sighting each week for a month
* Week-Streak x 12 - at least one sighting each week for a quarter
* Seconds - Got a sighting that was not the first
* Popular - Got the 5th or more sighting of a vehicle
* Brooklyn - Got a sighting in Brooklyn
* Manhattan - Got a sighting in Manhattan
* Queens - Got a sighting in Queens
* Bronx - Got a sighting in Bronx
* Staten Island - Got a sighting in Staten Island
* 5 boro - Got sightings in all 5 boroughs
* Road Tripper - Got a sighting outside of NYC
* T5 Club - got a sighting of a T5 series vehicle
* T8 Club - got a sighting of a T8 series vehicle
* TSeries - got one sighting from each T-series (ie T1,T5,T6,T7,T8)
* Jackpot - any plate containing 3 consecutive numbers
* NO1BOSS - get a sighting of one of the vehicles w/o a T######C plate number
* A Red One! - spotted a red Ocean

