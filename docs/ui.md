# User interface

The plugin's UI is built entirely with NetBox's own design system — Django
templates extending `base/layout.html`, NetBox cards/panels, tables, status
badges, Bootstrap utility classes, alerts and buttons. It introduces no custom
global CSS and respects NetBox dark/light mode. It should feel like a native
part of NetBox, not a separate web app.

## Navigation

The plugin registers a dedicated menu (`navigation.py`, via `PluginMenu`) under
**UniFi Sync**, grouped to match NetBox conventions:

| Group | Item | Purpose | Required permission |
|-------|------|---------|---------------------|
| Overview | **Dashboard** | Status overview + manual sync | `view_syncrun` |
| Configuration | **Controllers** | UniFi controllers (URL, auth) | `view_unificontroller` |
| Configuration | **Site Mappings** | UniFi ↔ NetBox site names | `view_sitemapping` |
| Configuration | **Settings** | Global sync settings | `change_globalsyncsettings` |
| Monitoring | **Job History** | Past sync runs | `view_syncrun` |
| Monitoring | **Logs** | Plugin audit log | `view_pluginauditevent` |

Menu items carry Add/Run buttons (`PluginMenuButton`) that appear only when the
user holds the corresponding `add_*` / `run_sync` permission.

## Dashboard

NetBox-style status panels show:

- **Sync Status** — current run status (badge), last sync time, next scheduled
  sync, interval and whether scheduling is enabled.
- **API Status** — NetBox API reachability (always reachable; the plugin runs
  in-process) and UniFi API reachability (aggregated from the controllers' last
  connection test), plus the number of enabled controllers.
- **Latest Run** — controllers/sites/devices processed and duration, with the
  latest error surfaced as a NetBox `alert-danger` when present.

The **Run sync** and **Dry run** buttons queue a job (subject to the `run_sync`
permission); the page auto-refreshes while a run is in progress.

## Settings

Settings render as NetBox fieldset/card sections, each field showing its help
text and any validation error inline. Secret-bearing controller fields use a
masked password widget and are **never** rendered in clear text — and they are
excluded from NetBox change-log snapshots.

## Testing connections

- **UniFi:** open **Controllers**, then use the **Test** button on a row (or the
  JSON endpoint `POST controllers/<id>/test/`). The result is stored on the
  controller (`last_test_status` / `last_test_error`) and shown as a badge.
- **NetBox:** the plugin runs inside NetBox and talks to it through the
  in-process ORM, so there is no separate NetBox connection to configure. The
  Dashboard's *API Status* panel and the `api/status/` JSON endpoint confirm the
  NetBox side is reachable.

## Permissions

Every write action is gated twice: server-side with `permission_required` on the
view, and in the template by hiding the button unless the user holds the matching
NetBox object permission. See [the permissions section of the README](../README.md#netbox-permissions).

## Secret handling

- Credentials are entered only via **Controllers** and stored masked in the form.
- They are excluded from change-log serialization, so they never appear in the
  object's change history.
- Run summaries, audit messages and errors are passed through a redactor before
  being persisted.
