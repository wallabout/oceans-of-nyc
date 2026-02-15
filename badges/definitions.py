"""Badge definitions for Bumper Stickers feature.

Each badge is defined with:
- name: Internal identifier
- display_name: Human-readable name for display
- description: Text shown when badge is earned
- sql_check: SQL query that returns TRUE if contributor qualifies
- emoji: Optional emoji for SMS notifications
- requires_context: Whether the badge needs sighting context (license_plate, borough, etc.)

SQL queries use $1 for contributor_id and may use additional parameters for context.
"""

from dataclasses import dataclass


@dataclass
class BadgeDefinition:
    """Definition of a badge and its qualification criteria."""

    name: str
    display_name: str
    description: str
    sql_check: str
    emoji: str = ""
    requires_context: bool = False


# Badge definitions organized by category
BADGE_DEFINITIONS: list[BadgeDefinition] = [
    # ==================== COUNT-BASED BADGES ====================
    BadgeDefinition(
        name="ocean_spotter",
        display_name="Ocean Spotter",
        description="Submitted your first sighting",
        emoji="🌊",
        sql_check="SELECT COUNT(*) >= 1 FROM sightings WHERE contributor_id = $1",
    ),
    BadgeDefinition(
        name="5_club",
        display_name="5 Club",
        description="Reached 5 sightings",
        emoji="🖐️",
        sql_check="SELECT COUNT(*) >= 5 FROM sightings WHERE contributor_id = $1",
    ),
    BadgeDefinition(
        name="10_club",
        display_name="10 Club",
        description="Reached 10 sightings",
        emoji="🔟",
        sql_check="SELECT COUNT(*) >= 10 FROM sightings WHERE contributor_id = $1",
    ),
    BadgeDefinition(
        name="25_club",
        display_name="25 Club",
        description="Reached 25 sightings",
        emoji="🏅",
        sql_check="SELECT COUNT(*) >= 25 FROM sightings WHERE contributor_id = $1",
    ),
    BadgeDefinition(
        name="50_club",
        display_name="50 Club",
        description="Reached 50 sightings",
        emoji="🎖️",
        sql_check="SELECT COUNT(*) >= 50 FROM sightings WHERE contributor_id = $1",
    ),
    BadgeDefinition(
        name="100_club",
        display_name="100 Club",
        description="Reached 100 sightings",
        emoji="💯",
        sql_check="SELECT COUNT(*) >= 100 FROM sightings WHERE contributor_id = $1",
    ),
    # ==================== TIME-BASED BADGES ====================
    BadgeDefinition(
        name="busy_week",
        display_name="Busy Week",
        description="Got 7 sightings in a single week",
        emoji="📅",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                GROUP BY DATE_TRUNC('week', timestamp)
                HAVING COUNT(*) >= 7
            )
        """,
    ),
    BadgeDefinition(
        name="busy_month",
        display_name="Busy Month",
        description="Got 30 sightings in a single month",
        emoji="📆",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                GROUP BY DATE_TRUNC('month', timestamp)
                HAVING COUNT(*) >= 30
            )
        """,
    ),
    BadgeDefinition(
        name="ocean_month",
        display_name="Ocean Month",
        description="Logged a sighting in 4 different weeks",
        emoji="🗓️",
        sql_check="""
            SELECT COUNT(DISTINCT DATE_TRUNC('week', timestamp)) >= 4
            FROM sightings
            WHERE contributor_id = $1
        """,
    ),
    BadgeDefinition(
        name="ocean_quarter",
        display_name="Ocean Quarter",
        description="Logged a sighting in 12 different weeks",
        emoji="📊",
        sql_check="""
            SELECT COUNT(DISTINCT DATE_TRUNC('week', timestamp)) >= 12
            FROM sightings
            WHERE contributor_id = $1
        """,
    ),
    # ==================== LOCATION-BASED BADGES ====================
    BadgeDefinition(
        name="brooklyn",
        display_name="Brooklyn",
        description="Got a sighting in Brooklyn",
        emoji="🌉",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1 AND borough = 'Brooklyn'
            )
        """,
    ),
    BadgeDefinition(
        name="manhattan",
        display_name="Manhattan",
        description="Got a sighting in Manhattan",
        emoji="🏙️",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1 AND borough = 'Manhattan'
            )
        """,
    ),
    BadgeDefinition(
        name="queens",
        display_name="Queens",
        description="Got a sighting in Queens",
        emoji="👑",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1 AND borough = 'Queens'
            )
        """,
    ),
    BadgeDefinition(
        name="bronx",
        display_name="Bronx",
        description="Got a sighting in the Bronx",
        emoji="🦁",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1 AND borough = 'Bronx'
            )
        """,
    ),
    BadgeDefinition(
        name="staten_island",
        display_name="Staten Island",
        description="Got a sighting in Staten Island",
        emoji="⛴️",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1 AND borough = 'Staten Island'
            )
        """,
    ),
    BadgeDefinition(
        name="5_boro",
        display_name="5 Boro",
        description="Got sightings in all 5 NYC boroughs",
        emoji="🗽",
        sql_check="""
            SELECT COUNT(DISTINCT borough) >= 5
            FROM sightings
            WHERE contributor_id = $1
              AND borough IN ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')
        """,
    ),
    BadgeDefinition(
        name="road_tripper",
        display_name="Road Tripper",
        description="Got a sighting outside of NYC",
        emoji="🚗",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND borough IS NOT NULL
                  AND borough NOT IN ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')
            )
        """,
    ),
    # ==================== VEHICLE-BASED BADGES ====================
    BadgeDefinition(
        name="t8_club",
        display_name="T8 Club",
        description="Spotted a T8 series vehicle (~ 1 in 20)",
        emoji="🚗",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND LEFT(license_plate, 2) = 'T8'
            )
        """,
    ),
    BadgeDefinition(
        name="t5_club",
        display_name="T5 Club",
        description="Spotted a T5 series vehicle (~ 1 in 100)",
        emoji="🚕",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND LEFT(license_plate, 2) = 'T5'
            )
        """,
    ),
    BadgeDefinition(
        name="t_series",
        display_name="TSeries",
        description="Spotted one from each T-series (T1, T5, T6, T7, T8)",
        emoji="🔤",
        sql_check="""
            SELECT COUNT(DISTINCT LEFT(license_plate, 2)) >= 5
            FROM sightings
            WHERE contributor_id = $1
              AND LEFT(license_plate, 2) IN ('T1', 'T5', 'T6', 'T7', 'T8')
        """,
    ),
    # BadgeDefinition(
    #     name="a_red_one",
    #     display_name="A Red One!",
    #     description="Spotted a red Fisker Ocean",
    #     emoji="🔴",
    #     # Note: This requires vehicle color data which may not be tracked
    #     # Placeholder SQL - will need adjustment based on data availability
    #     sql_check="""
    #         SELECT EXISTS(
    #             SELECT 1 FROM sightings s
    #             JOIN tlc_vehicles t ON s.license_plate = t.dmv_license_plate_number
    #             WHERE s.contributor_id = $1
    #               AND LOWER(t.vehicle_color) LIKE '%red%'
    #         )
    #     """,
    # ),
    # ==================== SEQUENCE-BASED BADGES ====================
    BadgeDefinition(
        name="seconds",
        display_name="Seconds",
        description="Got a sighting that was not the first for that vehicle",
        emoji="✌️",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings s1
                WHERE s1.contributor_id = $1
                  AND EXISTS(
                      SELECT 1 FROM sightings s2
                      WHERE s2.license_plate = s1.license_plate
                        AND s2.timestamp < s1.timestamp
                  )
            )
        """,
    ),
    BadgeDefinition(
        name="popular",
        display_name="Popular",
        description="Got the 5th or more sighting of a vehicle",
        emoji="⭐",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM (
                    SELECT license_plate,
                           ROW_NUMBER() OVER (PARTITION BY license_plate ORDER BY timestamp) as sighting_num
                    FROM sightings
                ) ranked
                JOIN sightings s ON ranked.license_plate = s.license_plate
                                AND s.contributor_id = $1
                WHERE ranked.sighting_num >= 5
                  AND ranked.license_plate = s.license_plate
            )
        """,
    ),
    BadgeDefinition(
        name="self_dupe",
        display_name="Self-Dupe",
        description="Logged two sightings of the same vehicle",
        emoji="🔁",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                GROUP BY license_plate
                HAVING COUNT(*) >= 2
            )
        """,
    ),
    # ==================== PATTERN-BASED BADGES ====================
    BadgeDefinition(
        name="three_of_a_kind",
        display_name="Three of a Kind",
        description="Spotted a plate with 3 consecutive identical digits (~ 1 in 10)",
        emoji="🃏",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND license_plate ~ '000|111|222|333|444|555|666|777|888|999'
            )
        """,
    ),
    BadgeDefinition(
        name="short_straight",
        display_name="Short Straight",
        description="Spotted a plate with 3 consecutive ordered digits (~ 1 in 50)",
        emoji="📈",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND license_plate ~ '012|123|234|345|456|567|678|789'
            )
        """,
    ),
    BadgeDefinition(
        name="four_of_a_kind",
        display_name="Four of a Kind",
        description="Spotted a plate with 4 consecutive identical digits (~ 1 in 100)",
        emoji="🎴",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND license_plate ~ '0000|1111|2222|3333|4444|5555|6666|7777|8888|9999'
            )
        """,
    ),
    BadgeDefinition(
        name="full_house",
        display_name="Full House",
        description="Spotted a plate with a triple and a double sequence (~ 1 in 100)",
        emoji="🏠",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND (EXISTS (
                      SELECT 1 FROM regexp_matches(license_plate, '([0-9])\\1\\1([0-9])\\2') AS m
                      WHERE m[1] != m[2]
                  )
                  OR EXISTS (
                      SELECT 1 FROM regexp_matches(license_plate, '([0-9])\\1([0-9])\\2\\2') AS m
                      WHERE m[1] != m[2]
                  ))
            )
        """,
    ),
    BadgeDefinition(
        name="no1boss",
        display_name="NO1BOSS",
        description="Spotted a vehicle without a T######C plate number (~ 1 in 1,000)",
        emoji="👔",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND license_plate !~ '^T[0-9]{6}C$'
            )
        """,
    ),
    BadgeDefinition(
        name="jackpot",
        display_name="Jackpot",
        description="Spotted a plate with 5 consecutive identical digits (~ 1 in 2,000)",
        emoji="🎰",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings
                WHERE contributor_id = $1
                  AND license_plate ~ '00000|11111|22222|33333|44444|55555|66666|77777|88888|99999'
            )
        """,
    ),
]

# Create a lookup dictionary for quick access by name
BADGE_BY_NAME: dict[str, BadgeDefinition] = {badge.name: badge for badge in BADGE_DEFINITIONS}


def get_badge(name: str) -> BadgeDefinition | None:
    """Get a badge definition by name."""
    return BADGE_BY_NAME.get(name)


def get_all_badge_names() -> list[str]:
    """Get all badge names."""
    return [badge.name for badge in BADGE_DEFINITIONS]
