"""Unit tests for Integration-API pagination (no Django/NetBox required)."""
from unittest.mock import MagicMock

from netbox_unifi_sync.services.unifi.resources import BaseResource


def _resource(pages):
    """Build a BaseResource whose make_request yields the given response dicts."""
    unifi = MagicMock()
    unifi.api_style = "integration"
    seq = list(pages)

    def fake_make_request(url, method, params=None):
        return seq.pop(0) if seq else {"data": []}

    unifi.make_request.side_effect = fake_make_request
    site = MagicMock()
    site.api_id = "site-id"
    site.name = "site-id"
    return BaseResource(unifi, site, endpoint="devices", api_path="/sites")


class TestIntegrationPagination:
    def test_no_total_count_server_caps_page_size_does_not_truncate(self):
        # Server caps pages at 2 items and omits totalCount; 5 items total.
        # The old `len(batch) < requested_limit` break truncated this to 2.
        res = _resource([
            {"data": [1, 2]},
            {"data": [3, 4]},
            {"data": [5]},
            {"data": []},
        ])
        assert res.all(limit=200) == [1, 2, 3, 4, 5]

    def test_total_count_is_authoritative_across_capped_pages(self):
        res = _resource([
            {"data": [1, 2], "totalCount": 5},
            {"data": [3, 4], "totalCount": 5},
            {"data": [5], "totalCount": 5},
        ])
        assert res.all(limit=200) == [1, 2, 3, 4, 5]

    def test_single_page_then_empty(self):
        res = _resource([{"data": [1, 2, 3]}, {"data": []}])
        assert res.all(limit=200) == [1, 2, 3]

    def test_total_count_zero_returns_empty(self):
        res = _resource([{"data": [], "totalCount": 0}])
        assert res.all(limit=200) == []
