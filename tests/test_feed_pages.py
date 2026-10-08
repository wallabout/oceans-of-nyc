"""Tests for the static /feed pages built alongside oceans.json."""

from datetime import datetime, timedelta

import pytest

from web.generate_data import build_feed_pages

START = datetime(2026, 1, 1, 12, 0)


def _vehicle(vin, minutes, contributor="Sam", borough="Brooklyn"):
    return {
        "vin": vin,
        "license_plates": [{"license_plate": f"T{vin}C", "first_reported_on": "2025-01-01"}],
        "sightings": [
            {
                "id": int(f"{vin}{i}"),
                "timestamp": START + timedelta(minutes=m),
                "vehicle_sighting_index": i + 1,
                "contributor": contributor,
                "borough": borough,
            }
            for i, m in enumerate(minutes)
        ],
    }


@pytest.mark.unit
class TestBuildFeedPages:
    def test_pages_are_newest_first_and_sized(self):
        vehicles = [_vehicle("1", [0, 2, 4]), _vehicle("2", [1, 3])]
        pages = build_feed_pages(vehicles, [], page_size=2, max_pages=10)

        assert [p["page"] for p in pages] == [1, 2, 3]
        ids = [item["sighting"]["id"] for p in pages for item in p["items"]]
        assert ids == [12, 21, 11, 20, 10]
        assert [p["has_more"] for p in pages] == [True, True, False]
        assert all(p["pages"] == 3 and p["total_sightings"] == 5 for p in pages)

    def test_caps_static_pages_and_flags_more(self):
        pages = build_feed_pages([_vehicle("1", range(10))], [], page_size=2, max_pages=3)

        assert len(pages) == 3
        assert pages[-1]["pages"] == 3
        assert pages[-1]["has_more"] is True

    def test_vehicle_stub_carries_only_the_previous_sighting(self):
        pages = build_feed_pages([_vehicle("1", [0, 1, 2])], [], page_size=10)
        newest, _, oldest = pages[0]["items"]

        assert newest["vehicle"]["vin"] == "1"
        assert newest["vehicle"]["license_plates"][0]["license_plate"] == "T1C"
        assert newest["vehicle"]["sightings"] == [
            {"vehicle_sighting_index": 2, "timestamp": START + timedelta(minutes=1)}
        ]
        assert oldest["vehicle"]["sightings"] == []

    def test_first_page_carries_filter_options(self):
        vehicles = [
            _vehicle("1", [0], contributor="Zed", borough="Queens"),
            _vehicle("2", [1], contributor="Amy", borough="Bronx"),
            _vehicle("3", [2], contributor=None, borough=None),
        ]
        badges = [{"name": "b"}]
        first, second = build_feed_pages(vehicles, badges, page_size=2)

        assert first["contributors"] == ["Amy", "Zed"]
        assert first["boroughs"] == ["Bronx", "Queens"]
        assert first["badge_definitions"] == badges
        assert "contributors" not in second

    def test_no_sightings_still_publishes_an_empty_first_page(self):
        pages = build_feed_pages([{"vin": "1", "license_plates": [], "sightings": []}], [])

        assert len(pages) == 1
        assert pages[0]["items"] == [] and pages[0]["has_more"] is False
