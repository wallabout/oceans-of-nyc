"""Tests for community photo tagging."""

import pytest

from tags import (
    RATE_LIMIT_MAX_TAGS,
    TAG_DEFINITIONS,
    TAG_NAMES,
    client_ip,
    get_tag,
    hash_ip,
    is_valid_tag,
    normalize_fingerprint,
    process_tag_request,
    truncate_user_agent,
)


class FakeTagDB:
    """Minimal stand-in for SightingsDatabase's tag operations."""

    def __init__(self, known_sighting_ids=(1, 2, 3)):
        self.known_sighting_ids = set(known_sighting_ids)
        self.rows: list[dict] = []

    def add_sighting_tag(
        self, sighting_id, tag_name, submitter_fingerprint, ip_hash=None, user_agent=None
    ) -> bool:
        if sighting_id not in self.known_sighting_ids:
            return False
        key = (sighting_id, tag_name, submitter_fingerprint)
        if any((r["sighting_id"], r["tag_name"], r["fingerprint"]) == key for r in self.rows):
            return False
        self.rows.append(
            {
                "sighting_id": sighting_id,
                "tag_name": tag_name,
                "fingerprint": submitter_fingerprint,
                "ip_hash": ip_hash,
                "user_agent": user_agent,
            }
        )
        return True

    def count_recent_tags_by_fingerprint(self, submitter_fingerprint, minutes) -> int:
        return sum(1 for r in self.rows if r["fingerprint"] == submitter_fingerprint)


@pytest.mark.unit
class TestTagDefinitions:
    """The definition list is the allow-list for the API, so it has to be sane."""

    def test_names_are_unique(self):
        assert len(TAG_NAMES) == len(set(TAG_NAMES))

    def test_every_tag_has_display_fields(self):
        for tag in TAG_DEFINITIONS:
            assert tag.display_name
            assert tag.description
            assert tag.emoji

    def test_requested_tags_exist(self):
        for name in [
            "rare_color_red",
            "rare_color_coffee",
            "multi_ocean",
            "ca_mode",
            "great_photography",
            "so_nyc",
            "report",
        ]:
            assert is_valid_tag(name), f"{name} missing from TAG_DEFINITIONS"

    def test_report_is_not_public(self):
        assert get_tag("report").public is False

    def test_unknown_tag_rejected(self):
        assert not is_valid_tag("definitely_not_a_tag")
        assert not is_valid_tag("")
        assert get_tag("nope") is None


@pytest.mark.unit
class TestFingerprinting:
    """Anonymous identity handling: hashing IPs and validating fingerprints."""

    def test_ip_hash_is_stable_and_not_the_raw_ip(self):
        hashed = hash_ip("203.0.113.7")
        assert hashed == hash_ip("203.0.113.7")
        assert "203.0.113.7" not in hashed

    def test_different_ips_hash_differently(self):
        assert hash_ip("203.0.113.7") != hash_ip("203.0.113.8")

    def test_missing_ip_hashes_to_none(self):
        assert hash_ip(None) is None
        assert hash_ip("") is None

    def test_salt_changes_the_hash(self, monkeypatch):
        monkeypatch.setenv("TAG_IP_SALT", "salt-one")
        first = hash_ip("203.0.113.7")
        monkeypatch.setenv("TAG_IP_SALT", "salt-two")
        assert hash_ip("203.0.113.7") != first

    def test_valid_fingerprint_passes_through(self):
        uuid = "0b7f6c1a-7b7f-4e2a-9a1a-6f4b1d2e3c4d"
        assert normalize_fingerprint(uuid) == uuid

    def test_junk_fingerprint_falls_back_to_ip_hash(self):
        ip_hash = hash_ip("203.0.113.7")
        assert normalize_fingerprint("../../etc/passwd", ip_hash) == f"ip-{ip_hash}"
        assert normalize_fingerprint("short", ip_hash) == f"ip-{ip_hash}"
        assert normalize_fingerprint(None, ip_hash) == f"ip-{ip_hash}"

    def test_no_identifier_at_all_returns_none(self):
        assert normalize_fingerprint(None, None) is None

    def test_overlong_fingerprint_rejected(self):
        assert normalize_fingerprint("a" * 200) is None

    def test_client_ip_prefers_forwarded_header(self):
        headers = {"x-forwarded-for": "203.0.113.7, 70.41.3.18", "x-real-ip": "10.0.0.1"}
        assert client_ip(headers, "10.0.0.9") == "203.0.113.7"

    def test_client_ip_falls_back_to_socket_peer(self):
        assert client_ip({}, "10.0.0.9") == "10.0.0.9"
        assert client_ip({}) is None

    def test_user_agent_truncated(self):
        assert truncate_user_agent("x" * 500) == "x" * 300
        assert truncate_user_agent(None) is None


@pytest.mark.unit
class TestProcessTagRequest:
    """The POST /tag request path, exercised without Modal or Postgres."""

    HEADERS = {"x-forwarded-for": "203.0.113.7", "user-agent": "Mozilla/5.0"}
    FINGERPRINT = "0b7f6c1a-7b7f-4e2a-9a1a-6f4b1d2e3c4d"

    def _body(self, **overrides):
        body = {"sighting_id": 1, "tag": "so_nyc", "fingerprint": self.FINGERPRINT}
        body.update(overrides)
        return body

    def test_valid_nomination_is_recorded(self):
        db = FakeTagDB()
        status, payload = process_tag_request(db, self._body(), self.HEADERS)

        assert status == 200
        assert payload == {"success": True, "recorded": True}
        assert len(db.rows) == 1
        assert db.rows[0]["tag_name"] == "so_nyc"
        assert db.rows[0]["fingerprint"] == self.FINGERPRINT

    def test_raw_ip_is_never_stored(self):
        db = FakeTagDB()
        process_tag_request(db, self._body(), self.HEADERS)

        assert db.rows[0]["ip_hash"] == hash_ip("203.0.113.7")
        assert "203.0.113.7" not in str(db.rows[0])

    def test_repeat_nomination_from_same_visitor_is_dropped(self):
        db = FakeTagDB()
        process_tag_request(db, self._body(), self.HEADERS)
        status, payload = process_tag_request(db, self._body(), self.HEADERS)

        assert status == 200
        assert payload == {"success": True, "recorded": False}
        assert len(db.rows) == 1

    def test_second_visitor_same_tag_is_kept(self):
        db = FakeTagDB()
        process_tag_request(db, self._body(), self.HEADERS)
        other = self._body(fingerprint="ffffffff-1111-2222-3333-444444444444")
        _, payload = process_tag_request(db, other, self.HEADERS)

        assert payload["recorded"] is True
        assert len(db.rows) == 2

    def test_same_visitor_can_apply_different_tags(self):
        db = FakeTagDB()
        process_tag_request(db, self._body(tag="so_nyc"), self.HEADERS)
        _, payload = process_tag_request(db, self._body(tag="great_photography"), self.HEADERS)

        assert payload["recorded"] is True
        assert len(db.rows) == 2

    def test_unknown_tag_rejected(self):
        db = FakeTagDB()
        status, payload = process_tag_request(db, self._body(tag="drop table"), self.HEADERS)

        assert status == 400
        assert payload["error"] == "unknown_tag"
        assert db.rows == []

    @pytest.mark.parametrize("value", [None, "abc", 3.5, {}, "12abc", 0, -4, True])
    def test_bad_sighting_id_rejected(self, value):
        db = FakeTagDB()
        status, payload = process_tag_request(db, self._body(sighting_id=value), self.HEADERS)

        assert status == 400
        assert payload["error"] == "invalid_sighting_id"
        assert db.rows == []

    def test_missing_sighting_id_rejected(self):
        db = FakeTagDB()
        body = {"tag": "so_nyc", "fingerprint": self.FINGERPRINT}
        status, payload = process_tag_request(db, body, self.HEADERS)

        assert status == 400
        assert payload["error"] == "invalid_sighting_id"

    def test_unknown_sighting_records_nothing(self):
        db = FakeTagDB(known_sighting_ids=(1,))
        status, payload = process_tag_request(db, self._body(sighting_id=9999), self.HEADERS)

        assert status == 200
        assert payload["recorded"] is False
        assert db.rows == []

    def test_missing_fingerprint_falls_back_to_ip(self):
        db = FakeTagDB()
        status, payload = process_tag_request(db, self._body(fingerprint=None), self.HEADERS)

        assert status == 200
        assert payload["recorded"] is True
        assert db.rows[0]["fingerprint"].startswith("ip-")

    def test_no_fingerprint_and_no_ip_is_rejected(self):
        db = FakeTagDB()
        status, payload = process_tag_request(db, self._body(fingerprint=None), {})

        assert status == 400
        assert payload["error"] == "missing_fingerprint"
        assert db.rows == []

    def test_rate_limited_after_burst(self):
        db = FakeTagDB(known_sighting_ids=range(1, RATE_LIMIT_MAX_TAGS + 5))
        for sighting_id in range(1, RATE_LIMIT_MAX_TAGS + 1):
            process_tag_request(db, self._body(sighting_id=sighting_id), self.HEADERS)

        assert len(db.rows) == RATE_LIMIT_MAX_TAGS

        status, payload = process_tag_request(
            db, self._body(sighting_id=RATE_LIMIT_MAX_TAGS + 1), self.HEADERS
        )
        assert status == 429
        assert payload["error"] == "rate_limited"
        assert len(db.rows) == RATE_LIMIT_MAX_TAGS
