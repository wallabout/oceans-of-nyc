"""Mock implementation of SightingsDatabase for testing."""

from datetime import datetime


class MockSightingsDatabase:
    """Mock database that stores data in memory."""

    def __init__(self, connection_string: str | None = None):
        """Initialize mock database."""
        self.connection_string = connection_string or "mock://test"

        # In-memory storage
        self.sightings: list[dict] = []
        self.contributors: list[dict] = []
        self.chat_sessions: dict[str, dict] = {}
        self.tlc_vehicles: list[dict] = []

        # Auto-increment IDs
        self._next_sighting_id = 1
        self._next_contributor_id = 1

        # Add default admin contributor
        self.contributors.append(
            {
                "id": 1,
                "phone_number": "+15551234567",
                "name": "Admin",
                "bluesky_handle": "admin.bsky.social",
                "created_at": datetime.now(),
            }
        )
        self._next_contributor_id = 2

    def add_sighting(
        self,
        plate_number: str | None = None,
        license_plate: str | None = None,
        borough: str | None = None,
        image_filename: str | None = None,
        phone_number: str | None = None,
        contributor_id: int | None = None,
        gps_latitude: float | None = None,
        gps_longitude: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        timestamp: datetime | str | None = None,
        image_timestamp: datetime | None = None,
    ) -> dict | None:
        """Mock add sighting."""
        plate = license_plate if license_plate else plate_number
        lat = latitude if latitude is not None else gps_latitude
        lon = longitude if longitude is not None else gps_longitude

        sighting_id = self._next_sighting_id
        self._next_sighting_id += 1

        sighting = {
            "id": sighting_id,
            "license_plate": plate,
            "borough": borough,
            "image_filename": image_filename,
            "phone_number": phone_number,
            "contributor_id": contributor_id,
            "latitude": lat,
            "longitude": lon,
            "image_timestamp": image_timestamp,
            "created_at": datetime.now(),
            "posted": False,
        }

        self.sightings.append(sighting)

        return {"id": sighting_id}

    def get_sighting(self, sighting_id: int) -> dict | None:
        """Get a sighting by ID."""
        for sighting in self.sightings:
            if sighting["id"] == sighting_id:
                return sighting
        return None

    def get_unposted_sightings(self, limit: int = 10) -> list[dict]:
        """Get unposted sightings."""
        unposted = [s for s in self.sightings if not s.get("posted")]
        return unposted[:limit]

    def mark_as_posted(self, sighting_id: int, post_url: str | None = None) -> None:
        """Mark a sighting as posted."""
        for sighting in self.sightings:
            if sighting["id"] == sighting_id:
                sighting["posted"] = True
                sighting["post_url"] = post_url
                break

    def acquire_posting_lock(self):
        """Mock advisory lock: grant to the first caller, refuse while held."""
        if getattr(self, "_posting_lock_held", False):
            return None
        self._posting_lock_held = True
        return object()  # opaque "connection" handle

    def release_posting_lock(self, conn):
        """Release the mock advisory lock."""
        self._posting_lock_held = False

    def claim_sightings_for_posting(self, sighting_ids: list[int]) -> list[int]:
        """Mock atomic claim: grant only sightings that are unposted and unclaimed."""
        claimed = []
        for sighting in self.sightings:
            if sighting["id"] in sighting_ids and not sighting.get("posted") and not sighting.get(
                "posting_claimed"
            ):
                sighting["posting_claimed"] = True
                claimed.append(sighting["id"])
        return claimed

    def release_sighting_claims(self, sighting_ids: list[int]) -> None:
        """Release mock claims on sightings that were never posted."""
        for sighting in self.sightings:
            if sighting["id"] in sighting_ids and not sighting.get("posted"):
                sighting["posting_claimed"] = False

    def add_contributor(
        self,
        phone_number: str,
        name: str | None = None,
        bluesky_handle: str | None = None,
    ) -> int:
        """Add a new contributor."""
        contributor_id = self._next_contributor_id
        self._next_contributor_id += 1

        contributor = {
            "id": contributor_id,
            "phone_number": phone_number,
            "name": name,
            "bluesky_handle": bluesky_handle,
            "created_at": datetime.now(),
        }

        self.contributors.append(contributor)
        return contributor_id

    def get_contributor(
        self, contributor_id: int | None = None, phone_number: str | None = None
    ) -> dict | None:
        """Get a contributor by ID or phone number."""
        for contributor in self.contributors:
            if contributor_id and contributor["id"] == contributor_id:
                return contributor
            if phone_number and contributor["phone_number"] == phone_number:
                return contributor
        return None

    def update_contributor(
        self,
        contributor_id: int,
        name: str | None = None,
        bluesky_handle: str | None = None,
    ) -> None:
        """Update contributor information."""
        for contributor in self.contributors:
            if contributor["id"] == contributor_id:
                if name is not None:
                    contributor["name"] = name
                if bluesky_handle is not None:
                    contributor["bluesky_handle"] = bluesky_handle
                break

    def save_chat_session(self, phone_number: str, state: str, data: dict | None = None) -> None:
        """Save chat session state."""
        self.chat_sessions[phone_number] = {
            "phone_number": phone_number,
            "state": state,
            "data": data or {},
            "updated_at": datetime.now(),
        }

    def get_chat_session(self, phone_number: str) -> dict | None:
        """Get chat session state."""
        return self.chat_sessions.get(phone_number)

    def delete_chat_session(self, phone_number: str) -> None:
        """Delete chat session."""
        if phone_number in self.chat_sessions:
            del self.chat_sessions[phone_number]

    def add_tlc_vehicle(self, plate_number: str, vin: str, vehicle_type: str = "FOR_HIRE") -> None:
        """Add a TLC vehicle record."""
        self.tlc_vehicles.append(
            {
                "plate_number": plate_number,
                "vin": vin,
                "vehicle_type": vehicle_type,
            }
        )

    def get_vehicle_by_plate(self, plate_number: str) -> tuple | None:
        """Get TLC vehicle by plate number."""
        for vehicle in self.tlc_vehicles:
            if vehicle["plate_number"] == plate_number:
                return (vehicle["plate_number"], vehicle["vin"], vehicle["vehicle_type"])
        return None

    def clear(self) -> None:
        """Clear all data (test helper)."""
        self.sightings.clear()
        self.contributors.clear()
        self.chat_sessions.clear()
        self.tlc_vehicles.clear()
        self._next_sighting_id = 1
        self._next_contributor_id = 1

    def get_sighting_count(self) -> int:
        """Get total sighting count (test helper)."""
        return len(self.sightings)

    def get_posted_sighting_count(self) -> int:
        """Get posted sighting count (test helper)."""
        return sum(1 for s in self.sightings if s.get("posted"))
