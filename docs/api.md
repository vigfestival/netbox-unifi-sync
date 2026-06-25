# JSON endpoints

The plugin exposes a few lightweight JSON endpoints (plain `JsonResponse`, not
DRF) used by the UI for live status and connection testing. All require an
authenticated session and the relevant NetBox permission; there is no separate
API token (the plugin runs in-process).

| Method | Path | Permission | Purpose |
|--------|------|-----------|---------|
| GET | `/plugins/unifi-sync/api/status/` | `view_syncrun` | Plugin + latest-run status (drives the dashboard live refresh). |
| GET | `/plugins/unifi-sync/runs/<id>/status/` | `view_syncrun` | Status/elapsed/counters for one run (drives the run-detail live refresh). |
| POST | `/plugins/unifi-sync/controllers/<id>/test/` | `test_controller` or `change_unificontroller` | Test a UniFi controller connection; returns `{status, sites, ...}` or `{status: "error", error}`. |

## `GET api/status/`

```json
{
  "enabled": true,
  "schedule_enabled": true,
  "sync_interval_minutes": 120,
  "latest_run": {
    "id": 406,
    "status": "success",
    "created": "2026-06-25T12:08:21+00:00",
    "completed": "2026-06-25T12:09:53+00:00",
    "summary": "mode=sync controllers=1 sites=21 devices=103",
    "controllers": 1,
    "sites": 21,
    "devices": 103
  }
}
```

## `GET runs/<id>/status/`

```json
{
  "id": 406, "status": "running", "status_display": "Running",
  "is_terminal": false, "started": "...", "completed": null,
  "elapsed_ms": 4200, "duration_ms": 0,
  "controllers": 0, "sites": 0, "devices": 0,
  "summary": "", "error": ""
}
```

Secrets are never included in any of these payloads; the controller-test
response returns only a redacted runtime view.

## NetBox REST API

The plugin's models (`SyncRun`, `UnifiController`, `SiteMapping`,
`GlobalSyncSettings`, `PluginAuditEvent`) are not registered with the NetBox REST
API; configuration and triggering are done through the UI and the
`netbox_unifi_sync_run` management command. Secrets are excluded from NetBox
change-log snapshots.
