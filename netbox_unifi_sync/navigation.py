from __future__ import annotations

from netbox.choices import ButtonColorChoices
from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

# --- Overview -------------------------------------------------------------

dashboard_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:dashboard",
    link_text="Dashboard",
    permissions=["netbox_unifi_sync.view_syncrun"],
    buttons=(
        PluginMenuButton(
            link="plugins:netbox_unifi_sync:dashboard",
            title="Run sync",
            icon_class="mdi mdi-play-circle",
            color=ButtonColorChoices.BLUE,
            permissions=["netbox_unifi_sync.run_sync"],
        ),
    ),
)

# --- Configuration --------------------------------------------------------

controllers_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:controllers",
    link_text="Controllers",
    permissions=["netbox_unifi_sync.view_unificontroller"],
    buttons=(
        PluginMenuButton(
            link="plugins:netbox_unifi_sync:controller_add",
            title="Add controller",
            icon_class="mdi mdi-plus-thick",
            color=ButtonColorChoices.GREEN,
            permissions=["netbox_unifi_sync.add_unificontroller"],
        ),
    ),
)

mappings_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:mappings",
    link_text="Site Mappings",
    permissions=["netbox_unifi_sync.view_sitemapping"],
    buttons=(
        PluginMenuButton(
            link="plugins:netbox_unifi_sync:mapping_add",
            title="Add site mapping",
            icon_class="mdi mdi-plus-thick",
            color=ButtonColorChoices.GREEN,
            permissions=["netbox_unifi_sync.add_sitemapping"],
        ),
    ),
)

settings_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:settings",
    link_text="Settings",
    permissions=["netbox_unifi_sync.change_globalsyncsettings"],
)

# --- Monitoring -----------------------------------------------------------

runs_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:runs",
    link_text="Job History",
    permissions=["netbox_unifi_sync.view_syncrun"],
)

audit_item = PluginMenuItem(
    link="plugins:netbox_unifi_sync:audit",
    link_text="Logs",
    permissions=["netbox_unifi_sync.view_pluginauditevent"],
)


menu = PluginMenu(
    label="UniFi Sync",
    icon_class="mdi mdi-wifi-sync",
    groups=(
        ("Overview", (dashboard_item,)),
        ("Configuration", (controllers_item, mappings_item, settings_item)),
        ("Monitoring", (runs_item, audit_item)),
    ),
)

# Provided so the plugin config can disable the default flat registration
# under the generic "Plugins" menu in favour of the dedicated menu above.
empty_menu_items = ()
