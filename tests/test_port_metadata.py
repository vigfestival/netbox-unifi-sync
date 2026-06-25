from main import normalize_port_data, normalize_radio_data


def test_normalize_integration_port_enriches_description_with_profile_vlan_and_poe():
    ports = normalize_port_data(
        {
            "interfaces": {
                "ports": [
                    {
                        "name": "Port 1",
                        "maxSpeed": 2500,
                        "enabled": True,
                        "poeMode": "auto",
                        "poePower": 6400,
                        "portProfileName": "AP Trunk",
                        "nativeVlan": 10,
                        "taggedVlanIds": [20, 30],
                        "isUplink": True,
                    }
                ]
            }
        },
        api_style="integration",
    )

    assert ports == [
        {
            "name": "Port 1",
            "type": "2.5gbase-t",
            "speed_kbps": 2500000,
            "enabled": True,
            "link_up": None,
            "poe_mode": "pse",
            "mac_address": None,
            "is_uplink": True,
            "description": (
                "Uplink | Profile: AP Trunk | Native VLAN: 10 | "
                "Tagged VLANs: 20, 30 | PoE: auto | PoE draw: 6.4W | "
                "Max speed: 2500Mbps"
            ),
        }
    ]


def test_normalize_legacy_port_enriches_description_from_portconf_and_vlans():
    ports = normalize_port_data(
        {
            "port_table": [
                {
                    "name": "Port 2",
                    "speed": 1000,
                    "up": True,
                    "poe_mode": "off",
                    "portconf_name": "Client Access",
                    "vlan": 40,
                    "tagged_vlans": "50,60",
                    "mac": "aa:bb:cc:dd:ee:ff",
                }
            ]
        },
        api_style="legacy",
    )

    assert ports[0]["description"] == (
        "Profile: Client Access | Native VLAN: 40 | Tagged VLANs: 50, 60 | "
        "PoE: off | Max speed: 1000Mbps | Link: up @ 1000Mbps"
    )
    assert ports[0]["link_up"] is True
    assert ports[0]["mac_address"] == "aa:bb:cc:dd:ee:ff"


def test_normalize_radio_data_enriches_description_with_operational_metadata():
    radios = normalize_radio_data(
        {
            "interfaces": {
                "radios": [
                    {
                        "name": "radio0",
                        "band": "5GHz",
                        "channel": 44,
                        "channelWidth": "HE80",
                        "txPower": 18,
                        "utilization": 37,
                        "noiseFloor": -95,
                        "state": "RUNNING",
                    }
                ]
            }
        },
        api_style="integration",
    )

    assert radios == [
        {
            "name": "radio0",
            "type": "ieee802.11ac",
            "enabled": True,
            "description": (
                "Band: 5GHZ | Channel: 44 | Width: HE80 | TX: 18dBm | "
                "Utilization: 37% | Noise: -95dBm | State: RUNNING"
            ),
        }
    ]


def test_integration_link_state_maps_to_mark_connected_and_speed(monkeypatch):
    monkeypatch.delenv("SYNC_PORT_LINK_STATE", raising=False)
    ports = normalize_port_data(
        {
            "interfaces": {
                "ports": [
                    {"name": "Port 1", "maxSpeedMbps": 1000, "speedMbps": 1000, "state": "UP"},
                    {"name": "Port 2", "maxSpeedMbps": 1000, "state": "DOWN"},
                ]
            }
        },
        api_style="integration",
    )
    up, down = ports
    # The link state is surfaced separately from admin enabled state.
    assert up["enabled"] is True and up["link_up"] is True
    assert "Link: up @ 1000Mbps" in up["description"]
    assert down["enabled"] is True and down["link_up"] is False
    assert down["description"].endswith("Link: down")


def test_link_state_disabled_leaves_connection_state_untouched(monkeypatch):
    monkeypatch.setenv("SYNC_PORT_LINK_STATE", "false")
    ports = normalize_port_data(
        {"interfaces": {"ports": [{"name": "Port 1", "maxSpeedMbps": 1000, "state": "UP"}]}},
        api_style="integration",
    )
    # link_up is None so callers leave NetBox's mark_connected alone, and no
    # "Link:" suffix is added to the description.
    assert ports[0]["link_up"] is None
    assert "Link:" not in ports[0]["description"]


def test_integration_poe_dict_renders_as_standard_label():
    ports = normalize_port_data(
        {
            "interfaces": {
                "ports": [
                    {
                        "name": "Port 5",
                        "maxSpeedMbps": 1000,
                        "state": "DOWN",
                        "poe": {"standard": "802.3af", "type": 1, "enabled": True, "state": "DOWN"},
                    }
                ]
            }
        },
        api_style="integration",
    )
    # The raw PoE dict must not leak into the description.
    assert "PoE: 802.3af" in ports[0]["description"]
    assert "{" not in ports[0]["description"]
    assert ports[0]["poe_mode"] == "pse"


def test_normalize_radio_data_marks_disabled_radios():
    radios = normalize_radio_data(
        {
            "radio_table": [
                {
                    "name": "radio1",
                    "radio": "ng",
                    "channel": 6,
                    "tx_power_mode": "auto",
                    "enabled": False,
                }
            ]
        },
        api_style="legacy",
    )

    assert radios[0]["type"] == "ieee802.11n"
    assert radios[0]["enabled"] is False
    assert radios[0]["description"] == (
        "Band: NG | Channel: 6 | TX: auto | Disabled"
    )
