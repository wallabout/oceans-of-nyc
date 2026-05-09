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
    sighting_sql: str | None = None


# Badge definitions organized by category
BADGE_DEFINITIONS: list[BadgeDefinition] = [
    # ==================== COUNT-BASED BADGES ====================
    BadgeDefinition(
        name="ocean_spotter",
        display_name="Ocean Spotter",
        description="Submitted your first sighting",
        emoji="🌊",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 1)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 1",
    ),
    BadgeDefinition(
        name="5_club",
        display_name="5 Club",
        description="Reached 5 sightings",
        emoji="🖐️",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 5)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 5",
    ),
    BadgeDefinition(
        name="10_club",
        display_name="10 Club",
        description="Reached 10 sightings",
        emoji="🔟",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 10)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 10",
    ),
    BadgeDefinition(
        name="25_club",
        display_name="25 Club",
        description="Reached 25 sightings",
        emoji="🏅",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 25)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 25",
    ),
    BadgeDefinition(
        name="50_club",
        display_name="50 Club",
        description="Reached 50 sightings",
        emoji="🎖️",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 50)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 50",
    ),
    BadgeDefinition(
        name="100_club",
        display_name="100 Club",
        description="Reached 100 sightings",
        emoji="💯",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 100)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 100",
    ),
    BadgeDefinition(
        name="500_club",
        display_name="500 Club",
        description="Reached 500 sightings",
        emoji="🏆",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index >= 500)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND contributor_sighting_index = 500",
    ),
    # ==================== TIME-BASED BADGES ====================
    BadgeDefinition(
        name="busy_week",
        display_name="Busy Week",
        description="Got 7 sightings in a single week",
        emoji="📅",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings_export
                WHERE contributor_id = $1
                GROUP BY DATE_TRUNC('week', timestamp_et)
                HAVING COUNT(*) >= 7
            )
        """,
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('week', timestamp_et) ORDER BY timestamp_et) AS rn,
                       COUNT(*) OVER (PARTITION BY DATE_TRUNC('week', timestamp_et)) AS week_count
                FROM sightings_export
                WHERE contributor_id = $1
            ) ranked
            WHERE week_count >= 7 AND rn = 7
            ORDER BY sighting_id ASC
            LIMIT 1
        """,
    ),
    BadgeDefinition(
        name="busy_month",
        display_name="Busy Month",
        description="Got 30 sightings in a single month",
        emoji="📆",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings_export
                WHERE contributor_id = $1
                GROUP BY DATE_TRUNC('month', timestamp_et)
                HAVING COUNT(*) >= 30
            )
        """,
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('month', timestamp_et) ORDER BY timestamp_et) AS rn,
                       COUNT(*) OVER (PARTITION BY DATE_TRUNC('month', timestamp_et)) AS month_count
                FROM sightings_export
                WHERE contributor_id = $1
            ) ranked
            WHERE month_count >= 30 AND rn = 30
            ORDER BY sighting_id ASC
            LIMIT 1
        """,
    ),
    BadgeDefinition(
        name="ocean_month",
        display_name="Ocean Month",
        description="Logged a sighting in 4 different weeks",
        emoji="🗓️",
        sql_check="""
            SELECT COUNT(DISTINCT DATE_TRUNC('week', timestamp_et)) >= 4
            FROM sightings_export
            WHERE contributor_id = $1
        """,
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       DENSE_RANK() OVER (ORDER BY DATE_TRUNC('week', timestamp_et)) AS week_rank
                FROM sightings_export
                WHERE contributor_id = $1
            ) ranked
            WHERE week_rank = 4
            ORDER BY sighting_id ASC
            LIMIT 1
        """,
    ),
    BadgeDefinition(
        name="ocean_quarter",
        display_name="Ocean Quarter",
        description="Logged a sighting in 12 different weeks",
        emoji="📊",
        sql_check="""
            SELECT COUNT(DISTINCT DATE_TRUNC('week', timestamp_et)) >= 12
            FROM sightings_export
            WHERE contributor_id = $1
        """,
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       DENSE_RANK() OVER (ORDER BY DATE_TRUNC('week', timestamp_et)) AS week_rank
                FROM sightings_export
                WHERE contributor_id = $1
            ) ranked
            WHERE week_rank = 12
            ORDER BY sighting_id ASC
            LIMIT 1
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND borough = 'Brooklyn' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND borough = 'Manhattan' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND borough = 'Queens' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND borough = 'Bronx' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND borough = 'Staten Island' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       DENSE_RANK() OVER (ORDER BY MIN(timestamp_et)) AS borough_rank
                FROM sightings_export
                WHERE contributor_id = $1
                  AND borough IN ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')
                GROUP BY borough, sighting_id
            ) ranked
            WHERE borough_rank = 5
            ORDER BY sighting_id ASC
            LIMIT 1
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
        sighting_sql="""
            SELECT sighting_id FROM sightings_export
            WHERE contributor_id = $1
              AND borough IS NOT NULL
              AND borough NOT IN ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')
            ORDER BY timestamp_et ASC LIMIT 1
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND LEFT(license_plate, 2) = 'T8' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND LEFT(license_plate, 2) = 'T5' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="""
            SELECT sighting_id FROM (
                SELECT sighting_id,
                       DENSE_RANK() OVER (ORDER BY MIN(timestamp_et)) AS series_rank
                FROM sightings_export
                WHERE contributor_id = $1
                  AND LEFT(license_plate, 2) IN ('T1', 'T5', 'T6', 'T7', 'T8')
                GROUP BY LEFT(license_plate, 2), sighting_id
            ) ranked
            WHERE series_rank = 5
            ORDER BY sighting_id ASC
            LIMIT 1
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
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND vehicle_sighting_index >= 2)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND vehicle_sighting_index >= 2 ORDER BY timestamp_et ASC LIMIT 1",
    ),
    BadgeDefinition(
        name="popular",
        display_name="Popular",
        description="Got the 5th or more sighting of a vehicle",
        emoji="⭐",
        sql_check="""
            SELECT EXISTS(
                SELECT 1 FROM sightings_export
                WHERE contributor_id = $1
                  AND vehicle_sighting_index >= 5
            )
        """,
        sighting_sql="""
            SELECT sighting_id FROM sightings_export
            WHERE contributor_id = $1
              AND vehicle_sighting_index >= 5
            ORDER BY timestamp_et ASC
            LIMIT 1
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
        sighting_sql="""
            SELECT sighting_id FROM sightings_export s
            WHERE contributor_id = $1
              AND (
                  SELECT COUNT(*) FROM sightings_export s2
                  WHERE s2.contributor_id = $1
                    AND s2.license_plate = s.license_plate
                    AND s2.timestamp_et <= s.timestamp_et
              ) = 2
            ORDER BY timestamp_et ASC
            LIMIT 1
        """,
    ),
    # ==================== GLOBAL MILESTONE BADGES ====================
    BadgeDefinition(
        name="sightings_benjamin",
        display_name="Sightings Benjamin",
        description="Your sighting was the 100th, 200th, 300th... ever logged",
        emoji="💵",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND global_sighting_index %% 100 = 0)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND global_sighting_index %% 100 = 0 ORDER BY timestamp_et ASC LIMIT 1",
    ),
    BadgeDefinition(
        name="oceans_century",
        display_name="Oceans Century",
        description="Your sighting was the 100th, 200th, 300th... unique Ocean ever spotted",
        emoji="🐋",
        sql_check="SELECT EXISTS(SELECT 1 FROM sightings_export WHERE contributor_id = $1 AND global_unique_sighting_index %% 100 = 0)",
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND global_unique_sighting_index %% 100 = 0 ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND license_plate ~ '000|111|222|333|444|555|666|777|888|999' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND license_plate ~ '012|123|234|345|456|567|678|789' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND license_plate ~ '0000|1111|2222|3333|4444|5555|6666|7777|8888|9999' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="""
            SELECT sighting_id FROM sightings_export
            WHERE contributor_id = $1
              AND (EXISTS (
                  SELECT 1 FROM regexp_matches(license_plate, '([0-9])\\1\\1([0-9])\\2') AS m
                  WHERE m[1] != m[2]
              )
              OR EXISTS (
                  SELECT 1 FROM regexp_matches(license_plate, '([0-9])\\1([0-9])\\2\\2') AS m
                  WHERE m[1] != m[2]
              ))
            ORDER BY timestamp_et ASC LIMIT 1
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND license_plate !~ '^T[0-9]{6}C$' ORDER BY timestamp_et ASC LIMIT 1",
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
        sighting_sql="SELECT sighting_id FROM sightings_export WHERE contributor_id = $1 AND license_plate ~ '00000|11111|22222|33333|44444|55555|66666|77777|88888|99999' ORDER BY timestamp_et ASC LIMIT 1",
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
