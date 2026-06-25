"""Unit tests for the unifi-client IP MAC recovery (cleanup fail-safe)."""
from netbox_unifi_sync.services.sync_engine import _parse_client_mac_from_description


class TestParseClientMac:
    def test_conforming_description(self):
        desc = "unifi-client:AA:BB:CC:DD:EE:FF|UniFi client: phone|IP: 10.0.0.5"
        assert _parse_client_mac_from_description(desc) == "AA:BB:CC:DD:EE:FF"

    def test_lowercase_is_uppercased(self):
        assert _parse_client_mac_from_description("unifi-client:aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_mac_only(self):
        assert _parse_client_mac_from_description("unifi-client:11:22:33:44:55:66") == "11:22:33:44:55:66"

    def test_edited_description_returns_none(self):
        # A user-edited description no longer starts with the marker -> unidentifiable,
        # so cleanup must keep (never delete) the IP.
        assert _parse_client_mac_from_description("My phone in the office") is None

    def test_empty_and_none(self):
        assert _parse_client_mac_from_description("") is None
        assert _parse_client_mac_from_description(None) is None

    def test_marker_with_empty_mac_returns_none(self):
        assert _parse_client_mac_from_description("unifi-client:|note") is None
        assert _parse_client_mac_from_description("unifi-client:") is None
