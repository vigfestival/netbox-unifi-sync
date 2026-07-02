# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- **Live port link state → NetBox "connected" marker.** When something is plugged into a switch/AP port (the UniFi port link is up), the matching NetBox interface is now marked connected (`mark_connected`) and its description notes the negotiated link speed (e.g. `Link: up @ 1000Mbps`); empty ports show `Link: down`. The UniFi Integration API exposes only the link state and speed per port — not which device is attached — so only the connection status is reflected, not a neighbour/MAC. Administrative `enabled` state is now kept separate from link state (a port with nothing plugged in is no longer shown as disabled). Uplink ports (which receive a real NetBox cable) are left for the cable sync to connect. Toggle via **Settings → Reflect port link state** (`sync_port_link_state`, env `SYNC_PORT_LINK_STATE`; default on).
- **Dedicated role for non-SNMP switches.** Switches that don't support SNMP (e.g. the USW Flex Mini) are now assigned a `SWITCH_MINI` role key — map it to a NetBox role (default name "Switch-Mini") in **Settings → role mappings**. UniFi's device payload exposes no SNMP flag, so these are matched by model: the default marker is `flex mini`, extendable via the `UNIFI_NON_SNMP_SWITCH_MODELS` environment variable (comma-separated, case-insensitive substring match). If `SWITCH_MINI` isn't mapped, such switches fall back to the `LAN`/Switch role as before.

### Fixed

- **A duplicate asset tag no longer blocks the rest of a device's sync.** When two UniFi devices encode the same AID in their names (e.g. a switch mistakenly renamed to end in another AP's `-AIDxxxx`), the derived asset tag collides on NetBox's unique `asset_tag` constraint. Previously the failed `asset_tag` save left the bad value on the in-memory device object, so *every* subsequent `save()` in the same pass (zabbix tag, device status, custom fields) re-raised the same constraint error — the device silently stopped syncing firmware/uptime/MAC each run. Now: (1) on an existing device the asset tag is rolled back to the DB value after a failed update, so the rest of the device still syncs; (2) a new device whose asset tag collides is created *without* an asset tag instead of failing; and (3) both cases log an actionable warning naming the other device (name + serial) that already holds the tag, so the operator can fix the duplicate name in UniFi. Plain per-site device-name collisions are still disambiguated by serial suffix as before.
- **Client-lease IPs no longer churn (created and deleted every sync).** A UniFi client whose MAC has no matching NetBox interface — i.e. every wireless end-user client — had its IP created *unassigned* by `sync_client_ips()`, then deleted by the generic `cleanup_orphan_ips` sweep, then recreated on the next sync: a create/delete loop (one client alone logged 154 deletions over two months). Two changes break the loop: (1) `cleanup_orphan_ips` now skips client-lease IPs entirely (`_CLIENT_LIFECYCLE_TAGS`), deferring their lifecycle to the client sync; (2) the client sync's own stale-IP cleanup now also covers *unassigned* client IPs, attributing them to a site by VRF — it keeps an IP while its client is active and deletes it once when the client has been offline > 24 h. Net effect: an active client's IP is created once and kept; a departed client's IP is removed a single time.
- **Device-spec cache is now readable by the NetBox worker after a refresh.** `write_specs_bundle()` wrote the spec file via `tempfile.mkstemp()` (mode `0600`) and `os.replace()`, which preserved that mode — so when a spec refresh ran as a different user than the worker (e.g. root vs `netbox`), the worker got `Permission denied` reading `ubiquiti_device_specs.json` and silently fell back to no/partial device specs. The temp file is now `chmod 0644` before the atomic replace so the cache is always world-readable.
- **Cleanup no longer deletes management / out-of-band or other hand-managed IPs.** `cleanup_orphan_ips` previously deleted *every* unassigned IP in the synced tenant, so any tenant address not currently bound to an interface — reserved IPs, gateway/management/out-of-band IPs, anything created outside the sync — was destroyed on each cleanup run. It now deletes an orphan only when it is genuinely sync-owned (carries the `unifi-client` tag), is not `reserved`/`deprecated`, and is not a management/out-of-band address. A shared `_ip_is_mgmt_or_oob()` guard preserves any IP whose NetBox role is set, whose description/DNS/tag mentions mgmt/oob/management, or that is a device's `primary_ip4`/`primary_ip6`/`oob_ip`; the same guard now also protects the device primary-IP-change and stale-client-IP cleanup paths. (Sync-owned client leases use the `dhcp` status, so the guard keys off reservation/management state rather than `active` vs `dhcp` — stale client leases are still cleaned, deliberately-held addresses are not.)
- **Uplink cable sync now reconciles instead of giving up on the first existing cable.** Previously, if the chosen uplink port already had *any* cable — including a malformed single-ended/dangling cable left over from earlier runs — the sync logged "cable already exists" and skipped, so the real device-to-device uplink was never created. Now it: short-circuits when the device is already correctly cabled to its UniFi upstream (on any port, leaving valid cables untouched); removes malformed/dangling cables and recreates the correct uplink; removes cables pointing at the *wrong* upstream and reconnects to the right one; and, when a port is legitimately occupied by a downstream device's uplink (a downlink), steps aside to another free port instead of disturbing it. A malformed-cable sweep also clears orphaned single-ended cables on a device's ports. Patch-panel (front/rear-port) connections are still never touched. (UniFi's Integration API reports only the upstream device, not the port on either end, so port selection remains heuristic: last free physical port ↔ first free upstream port.)

### Changed

- The polled JSON status endpoints (`api/status/`, `runs/<id>/status/`) are now read-only: stale-run reaping moved to the scheduler tick (it still also runs on page loads), so the few-second dashboard poll no longer writes.
- `InsecureRequestWarning` is suppressed only when SSL verification is actually disabled (per UniFi client) instead of globally at import.
- **UniFi client no longer retries non-idempotent writes after the server may have applied them.** POST/PATCH requests are retried only on connection errors (request never reached the server) or HTTP 429, never on 5xx/read-timeout — preventing duplicate creates on flaky links. Idempotent methods (GET/HEAD/PUT/DELETE) retry as before.
- **The shared UniFi `requests.Session`'s stateful auth transitions are now serialized.** Login re-authentication and Integration-API reconfiguration take a per-client lock so concurrent device/site threads can't interleave their writes to the session's cookie/CSRF/auth-header state. Plain HTTP sends remain unsynchronized (urllib3's pool is thread-safe).
- Secret resolution (`env:`/`file:` references) now logs a warning when an env var is unset or a file can't be read (logging only the name/path, never the value), with optional `file:` path confinement via `UNIFI_SECRETS_DIR`.
- Log/audit redaction recognises more secret-bearing keys (credential, authorization, bearer, session key, cookie, …).

## [0.4.0] - 2026-06-25

### Changed

- **UI reworked to follow NetBox's native design system.** All plugin pages now use NetBox's standard cards/panels (`<h2 class="card-header">`), tables, status badges (`{% badge %}` with the NetBox colour palette), Bootstrap utility classes, alerts and buttons (mdi icons + NetBox button colours). No custom global CSS is introduced and dark/light mode is respected throughout.
  - **Navigation:** the plugin menu is grouped into *Overview* (Dashboard), *Configuration* (Controllers, Site Mappings, Settings) and *Monitoring* (Job History, Logs), each menu item carrying the appropriate `view`/`add` permission and Add/Run buttons (`PluginMenuButton`).
  - **Dashboard:** NetBox-style status panels for Sync Status (current status, last/next sync, interval), API Status (NetBox + UniFi reachability badges, enabled controllers) and Latest Run metrics (controllers/sites/devices, duration), plus dedicated **Run sync** and **Dry run** buttons and live auto-refresh while a run is in progress.
  - **Settings:** rendered as NetBox fieldset/card sections with per-field help text and validation errors, secret fields masked (`PasswordInput`) and never shown in clear text, and a NetBox Save/Cancel action bar.
  - **Forms** (Controllers, Site Mappings) now render via NetBox's `render_field`/`render_errors` form helpers for native field layout, help text and error display.
  - **Job History & Logs:** NetBox list views with status badges and filter panels (status + search). Logs are filterable by status and searchable.
  - **Permissions:** every action button (run sync, add/edit/delete/test controllers and mappings, edit settings) is shown only when the user holds the matching NetBox object permission, on top of the existing server-side `permission_required` checks.

### Added

- New colour-helper methods (`SyncRun.get_status_color`, `UnifiController.get_last_test_color`, `PluginAuditEvent.get_status_color`) backing the status badges.
- `.env.example` documenting the environment variables the sync engine honours (for CLI/advanced use; the Settings UI remains the normal configuration path).

### Fixed

- **Integration-API pagination can no longer silently truncate devices/clients** — the page loop stopped as soon as a page was smaller than the server-echoed `limit`. A controller that caps its page size below the requested limit (while echoing the requested limit) would end pagination after the first capped page, silently dropping the rest — which in turn could let stale cleanup delete the "missing" devices. `totalCount` is now authoritative (paging continues until it is reached regardless of page size); without `totalCount`, only an empty page terminates. A safety cap bounds the loop if a controller ignores `offset`. The current controller reports `totalCount`, so behaviour is unchanged there.
- **A device changing IP no longer unconditionally deletes the old IP** — when a device's management IP changed, the previous primary IP address was deleted outright, destroying any manual notes, tags, NAT relationships or services on it (e.g. an IP documented "Reserved by IT"). The old IP is now deleted only when it is plainly sync-owned (description equal to the device name, no tags/NAT/services); otherwise it is unassigned and kept. Verified on prod data: 110 plain IPs still deleted, 20 annotated/tagged IPs preserved.
- **Client-IP cleanup no longer deletes IPs whose description was edited** — stale `unifi-client` IP cleanup recovered the client MAC by parsing the IP description (`unifi-client:<MAC>|...`). If that description had been edited or cleared, the MAC parsed as empty and the IP was treated as stale and deleted — destroying user-annotated or externally-tagged IPs. Cleanup now keeps (never deletes) any IP whose MAC can't be recovered from its description. MAC parsing was extracted to a tested helper.
- **Device types use the canonical "Ubiquiti" manufacturer** — the plugin created device types under a legacy "Ubiquity Networks" manufacturer (slug `ubiquity`) while community-library types use "Ubiquiti" (slug `ubiquiti`), splitting devices across two manufacturers. New device types now use the canonical "Ubiquiti" (falling back to the legacy name only if it is absent). Added a `netbox_unifi_sync_consolidate_manufacturer` command (dry run by default, `--commit` to apply) that reassigns or merges existing legacy device types into the canonical manufacturer and moves their devices.
- **UniFi client IPs are now scoped to the site VRF** — `sync_client_ips` created and looked up client IP addresses without a VRF while device IPs and prefixes used the site VRF, leaving client IPs orphaned from their prefix in the IPAM hierarchy. Client IPs now use the same site VRF (looked up via `get_vrf_for_site`), an existing global client IP is moved into the VRF in place rather than duplicated, and `sync_site_prefixes` likewise scopes new prefixes to the site VRF. Added a `netbox_unifi_sync_backfill_vrf` management command (with `--dry-run`) to move pre-existing global UniFi IPs into their containing prefix's VRF, skipping any address collision.
- **Community device-spec loading is now thread-safe** — the lazy spec cache was loaded without a lock under the device thread pool, so the first batch of threads could each load the file and (with auto-refresh enabled) fire concurrent network fetches and interleaved cache writes. Loading is now guarded by a double-checked lock, and the cache file is written atomically (temp file + rename) so a crash or race can't leave a truncated cache.
- **Controller credentials are no longer held in clear text in the auth-grouping key** — `auth_signature` (used to group controllers that share identical auth) hashed instead of embedding the raw api key / password / MFA secret, so they can't leak if that structure is ever logged.
- **Stale-device cleanup no longer deletes non-UniFi devices** — cleanup deleted any device in a synced site+tenant that was absent from UniFi, including devices created by *other* integrations (e.g. virtualization hosts, cameras) that merely shared the site/tenant; only the grace period stood between them and deletion. Cleanup is now restricted to Ubiquiti-manufactured devices (matching both the "Ubiquiti" and "Ubiquity Networks" manufacturer names the plugin has used). Additionally, the UniFi serial set is now normalized the same way as the NetBox serial (upper-case, colon-stripped) before comparison, so a case/format difference can no longer make a live device look stale and get deleted.
- **Overlapping sync runs are now prevented** — a scheduled tick coinciding with a manual trigger (or duplicate scheduler jobs) could run two syncs at once, which race on the shared `os.environ` config transport and double-write NetBox objects. Sync runs now take a non-blocking PostgreSQL advisory lock; if one is already running, the new trigger is skipped (logged) instead of overlapping.
- **Security: plugin change-log views require the matching view permission** — the controller/settings/mapping change-log routes previously enforced login only, exposing change history to any authenticated user. They now require `view_unificontroller` / `view_globalsyncsettings` / `view_sitemapping` respectively (in addition to the credential-field exclusion below).
- **Security: UniFi controller credentials no longer leak into the change log** — credential reference fields (`api_key_ref`, `password_ref`, `username_ref`, `mfa_secret_ref`), which may hold raw secret values, were serialized verbatim into NetBox `ObjectChange` snapshots and thus readable via the controller's change log. They are now excluded from change-log serialization. (Pre-existing change records still contain old values; purge them separately if needed.)
- **ORM shim now reports save/delete failures consistently** — the in-process NetBox ORM shim wrapped `create()` errors as `RuntimeError` but let `save()`/`delete()` raise raw Django exceptions, so the many `except pynetbox...RequestError` handlers silently missed them (a failed update aborted the whole device). `save()`/`delete()` now wrap errors the same way, so existing recovery handlers (e.g. unique-name disambiguation on rename) work.
- **Device-type weights with non-metric units no longer crash spec sync** — weight was assigned as a `float`; NetBox multiplies it by a `Decimal` for `lb`/`oz` units on save, raising `unsupported operand type(s) for *: 'float' and 'Decimal'` (seen for `USW Pro Aggregation`). Weights are now `Decimal`, which also makes the change-detection idempotent (no more redundant re-saves).
- **Failed controller connection tests now record `last_tested`** — the non-API test view updated status/error but never stamped `last_tested` on failure (the JSON API view already did).
- **Device type updates crashed with "Cannot assign … must be a DeviceType instance"** — when an existing device's model changed, the update path assigned a raw integer id to the `device_type` related field instead of `device_type_id`, raising an uncaught `ValueError` that aborted processing for that device. Fixed to assign via `device_type_id` (matching the adjacent role update).
- **Both halves of a UniFi Building Bridge (UBB) kit are now created** — the controller reports the two UBB units as separate devices that share a single name, and NetBox enforces unique device names per site. The existing serial-disambiguation fallback never fired because it only caught `pynetbox.RequestError` with the text "Device name must be unique per site", whereas the Django-ORM shim raises `RuntimeError` wrapping a raw unique-constraint violation. Name collisions are now recognised regardless of error style, the second unit is stored under a serial-suffixed name, and that name is left stable on subsequent syncs instead of repeatedly colliding.
- **Devices skipped when a community device type already existed under its canonical name** — UniFi reports short model strings (e.g. `USW Pro Max 24 PoE`) while device types imported from the community library use canonical names (e.g. `UniFi Switch Pro Max 24 PoE`) with their own slug/part number. The plugin only looked up the type by the raw UniFi model, then tried to create a new one whose spec-derived slug collided with the existing type; the create failure was not recognised (the ORM shim raises `RuntimeError`, and NetBox can return a DRF "already exists" message rather than the raw Postgres error), so the device was silently skipped. Device types are now matched by canonical model, slug, and part number before creating, and duplicate-create recovery recognises both error styles. Auto-creation of genuinely new device types is unchanged.
- **Automatic (scheduled) sync could stop permanently** — a historical NetBox job-reschedule race (upstream #22232) could fill `core_job` with millions of orphaned `UniFi Sync Scheduler` rows. Once present, NetBox's idempotent `enqueue_once()` kept finding an orphaned row and never re-registered a working schedule, silently stopping automatic sync. Added a `netbox_unifi_sync_cleanup_jobs` management command to purge the stale rows and re-register the schedule, plus a light self-prune on every scheduler tick so the table cannot re-bloat. The purge uses `_raw_delete` (no model references `core_job` by FK) so clearing a multi-million-row backlog takes minutes rather than hours.

### Added

- **Live sync progress in the UI** — the dashboard and run-detail pages now poll the status endpoint and update the run state/elapsed time, then refresh automatically when a run finishes, instead of requiring a manual page reload. Added a per-run JSON status endpoint (`runs/<pk>/status/`).

## [0.3.23] - 2026-04-20

### Added

- **Granular UniFi sync controls** — added UI/settings support for choosing which UniFi data domains should sync.
- **UniFi client IP sync improvements** — client IPs now support Integration API field names, include richer descriptions, and can be assigned to NetBox DCIM/virtualization interfaces by MAC address.
- **NetBox Change Log views** — added Change Log access for global settings, controllers, and site mappings.

### Fixed

- **Template routing and API namespace issues** — fixed plugin dashboard/template routing and made the UniFi status API route reverseable.
- **ORM adapter edge cases** — fixed DHCP range creation, tag assignment by ID, duplicate interface create handling, and stale sync-run reconciliation.
- **Integration API writeback behavior** — DHCP writeback now skips unsupported Integration API static-IP calls instead of logging 404 errors.
- **Runtime cache permissions** — refreshed UniFi device specs cache now falls back to a writable service path.

## [0.3.22] - 2026-04-19

### Changed

- **Release instructions clarified** — documented maintainer release flow for version bumps, PyPI Trusted Publisher (OIDC), tagging, and workflow sequencing for `release.yml` and `publish-python-package.yml`.

## [0.3.21] - 2026-04-06

### Fixed

- **Controller test endpoints hardened** — changed controller test views to POST-only and updated UI actions to submit CSRF-protected forms, preventing state-changing GET requests.
- **Release dependency security advisory** — upgraded `requests` to `>=2.33.0` to address the Dependabot alert for insecure temp file reuse in `extract_zipped_paths()`.
- **Regression protection for HTTP method enforcement** — added tests that verify controller test endpoints remain POST-only and that controller list actions use POST for test triggers.

### Changed

- **Release workflow chaining** — aligned tag/release/publish workflow behavior so release creation and package publishing run in the intended sequence.
- **Documentation alignment** — updated docs to reflect current sync flags, runtime behavior, and troubleshooting guidance.

## [0.3.20] - 2026-04-06

### Fixed

- **NetBox 4.5.7 compatibility and UniFi controller session behavior** — fixed controller test timestamp field handling, aligned preflight SSL verification with controller DB settings, and changed UniFi session persistence default to disabled to avoid stale session-cache auth failures.
- **Release pipeline runtime tests aligned with secure defaults** — updated runtime tests for `UNIFI_PERSIST_SESSION=false` default and explicit session-cache behavior checks when persistence is enabled.

### Changed

- **GitHub Actions updated for Node.js 24 migration path** — upgraded workflow actions from `actions/checkout@v4` and `actions/setup-python@v5` to `@v6` to remove Node.js 20 deprecation warnings in CI/release runs.
- **Manual release-tag workflow added** — new `create-release-tag.yml` lets maintainers create/push `vX.Y.Z` tags from GitHub UI with version consistency checks before triggering `release.yml`.

---

## [0.3.18] - 2026-03-16

### Fixed

- **DHCP IP range sync works with the Django ORM adapter** — `IPRange.start_address` and `end_address` are now normalized to plain host addresses before ORM `get()`/`create()` calls, matching the payloads used by the sync engine and preventing DHCP range creation failures in plugin mode.
- **Overlapping prefixes now pick the most specific match** — client IP sync, DHCP-to-static reassignment, fallback `primary_ip4` lookup, and final device IP assignment now sort matching prefixes by prefix length instead of taking the first result, so nested subnets resolve to the correct mask.

---

## [0.3.17] - 2026-03-01

### Fixed

- **Cleanup no longer aborts sync with mixed controller credentials** — previously, running with `--cleanup` when controllers used different credential sets raised `SyncConfigurationError` and stopped the entire sync. Cleanup is now safely skipped with a warning log and sync continues normally.
- **Silent exception swallowing removed** — replaced bare `except Exception: pass` with specific exception types (`ValueError`, `LookupError`) and added `logger.debug` calls so failures are observable in logs rather than silently ignored.
- **False-positive bandit B105 findings suppressed** — `# nosec B105` added to error-message strings that contained words like "password" or "token" but are not credentials.
- **Stale test references updated** — `extract_dhcp_ranges_from_unifi` → `extract_dhcp_pools_from_unifi` in test suite; `_sync_interval_seconds` and `_netbox_verify_ssl` re-exported from `sync_engine` for test alias compatibility.

---

## [0.3.16] - 2026-03-01

### Fixed

- **`GlobalSyncSettings` thread/timeout bounds** — `PositiveIntegerField` allows 0 at the DB level. Setting `max_controller_threads`, `max_site_threads`, `max_device_threads`, or `request_timeout` to 0 causes thread pool failures or zero-second timeouts. Added `clean()` validation enforcing >= 1 for all four fields.
- **Removed stale `pynetbox~=7.4.1` from `requirements.txt`** — pynetbox was removed from `pyproject.toml` in v0.2.0. Keeping it installed an unnecessary dependency.

---

## [0.3.15] - 2026-02-28

### Added — **MAC address sync (NetBox 4.5 compatible)**

MAC addresses from UniFi devices are now synced to NetBox interface objects.

- NetBox 4.5 uses a dedicated `MACAddress` model (not `Interface.mac_address`) — implemented correctly via `get_or_create` + `primary_mac_address` OneToOneField using `queryset.update()` to bypass `Interface.clean()` validation.
- **Legacy API controllers:** per-port MAC address from `port_table` is set on each interface individually.
- **Integration API controllers:** only a device-level base MAC is available; it is assigned to Port 1.

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/services/sync_engine.py` | New `_set_interface_mac()` helper; port loop sets per-port MAC; device-MAC fallback to Port 1 |

---

## [0.3.14] - 2026-02-28

### Fixed — **Integration API does not support static IP configuration**

`set_unifi_device_static_ip` previously attempted `PATCH /sites/{id}/devices/{id}` via the Integration API, which returns **405 Method Not Allowed**.

The Integration API path is now skipped entirely; the function falls through directly to the Legacy API (`PUT /api/s/{site}/rest/device/{id}`) which supports static IP configuration.

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/services/sync/ipam.py` | Removed Integration API PATCH attempt; always use Legacy API for static IP |

---

## [0.3.13] - 2026-02-28

### Fixed — **Security Appliance primary IP (WAN vs LAN) + VPN filter + dedup**

Three related fixes for Security Appliance (UCG Ultra / UDM / USG) sync:

**Primary IP fallback:**
UniFi Integration API reports the WAN IP as `ipAddress` for gateways, so the `primary_ip4` match (`gateway_ip == device_ip`) never fires for LAN-managed appliances. A new `first_private_ip` fallback tracks the first non-WAN private gateway IP encountered in the network config loop; if `primary_ip4` is still unset after the loop, it is assigned this LAN IP.

**VPN network filter:**
Legacy API network configs include VPN tunnel entries (`purpose: vpn-client / remote-user-vpn / site-vpn / openvpn`) which previously created spurious IPs (e.g. `10.13.13.x/32`) on the `mgmt` interface. These purposes are now skipped.

**Deduplication:**
When merging Integration API + Legacy API network configs the same network could appear twice. Records are now deduplicated by `(name, purpose, vlanId)` before processing.

**Removed — untagged_vlan on virtual gateway interfaces:**
NetBox's `Interface.clean()` rejects `untagged_vlan` for non-access-mode interfaces. Virtual gateway VLAN interfaces (e.g. `vlan10`) do not need this link anyway — their name and IP address already identify the VLAN unambiguously.

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/services/sync_engine.py` | `first_private_ip` fallback; VPN purpose filter; `(name,purpose,vlanId)` dedup; removed `untagged_vlan` assignment |

---

## [0.3.12] - 2026-02-28

### Fixed — **Security Appliance VLAN interfaces and IPs missing with Integration API**

`sync_gateway_interfaces()` only fetched network configs from the Integration API (`site_obj.network_conf.all()`).  The Integration API omits `ip_subnet` / `gateway_ip` fields for many network entries, so no VLAN subinterfaces or IPs were created for Security Appliances when the controller used the Integration API.

**Fix:** Added the same Legacy API fallback used by `sync_site_prefixes`: `_fetch_legacy_networkconf(unifi, site_obj)` is now called when a `unifi` session is available, and the results are merged with the Integration API results.

`sync_gateway_interfaces` now accepts an optional `unifi=` keyword argument; the call site passes the active session.

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/services/sync_engine.py` | `sync_gateway_interfaces(unifi=None)` parameter; legacy networkconf fallback; updated call site |

---

## [0.3.11] - 2026-02-27

### Added — **Client IP sync + Security Appliance interface sync**

- Client IP addresses from UniFi are now synced to NetBox.
- Security Appliance (GATEWAY role) interfaces are correctly created with names, types, and IP assignments.

---

## [0.3.10] - 2026-02-27

### Added — **NetBox Change Log integration**

All sync operations (create / update / delete) are now written to NetBox's built-in Change Log via `ChangeLoggingMixin`.

---

## [0.3.9] - 2026-02-27

### Changed — Version bump

---

## [0.3.8] - 2026-02-27

### Fixed — **Audit log bugs + complete interface/VLAN/WLAN/cable/IP sync**

- Incorrect role assigned to some devices.
- `interface` was `None` in some code paths — NoneType crash.
- WLAN passphrase handled incorrectly in audit log.
- Interface sync: all types (ethernet, SFP, WiFi) synced correctly.
- VLAN sync: VLAN groups and VLAN ID matching corrected.
- WLAN sync: SSIDs and security settings synced.
- Cable sync: cables created with correct terminations.
- IP sync: primary IP assigned to correct interface.
- UniFi Integration API v1 gateway port field normalization — avoids `KeyError` on missing port data.

---

## [0.3.7] - 2026-02-27

### Fixed — **16 Bandit CI errors + cable sync bugs + 5 ORM compatibility errors**

- B607 (start process with partial path), misplaced docstring, and other Bandit static-analysis warnings.
- `_ChoiceValue` wrapper for cable-type choices.
- `get()` positional PK error in cable termination.
- Field name `last_updated` used incorrectly in `update_fields`.
- ORM fields aligned to NetBox 4.x naming conventions.

---

## [0.3.6] - 2026-02-27

### Changed — Version bump

---

## [0.3.5] - 2026-02-27

### Changed — **Refactor: consolidate `unifi2netbox/` into `netbox_unifi_sync/`**

The separate `unifi2netbox/` package has been removed. All sync logic is now consolidated under `netbox_unifi_sync/services/`, simplifying imports and deployment.

---

## [0.3.4] - 2026-02-27

### Changed — **CI: publish to PyPI directly from release workflow**

---

## [0.3.3] - 2026-02-27

### Changed — **Canonical role keys migration**

Old role keys (`SWITCH`, `SECURITY`, `OTHER`, `PHONE`) are automatically migrated to the canonical set (`WIRELESS`, `LAN`, `GATEWAY`, `ROUTER`, `UNKNOWN`) via `_migrate_role_keys()` which runs at plugin startup.

---

## [0.3.2] - 2026-02-26

### Fixed — **TemplateSyntaxError in settings.html**

Removed Jinja2 macro blocks from `settings.html` — NetBox uses Django templates, not Jinja2.

---

## [0.3.1] - 2026-02-26

### Fixed — **ORM adapter IP assignment**

`assigned_object_type` and `primary_ip4` are now set correctly on VirtualMachine and Device objects.

---

## [0.3.0] - 2026-02-26

### Changed — **ChangeLoggingMixin added to key models**

`GlobalSyncSettings`, `UnifiController`, `SiteMapping`, and `SyncRun` now integrate with NetBox's Change Log.

---

## [0.2.9] - 2026-02-26

### Fixed — **Protect Front Port / Rear Port cables from sync overwrite**

Cables on patch-panel ports are no longer overwritten by sync.

---

## [0.2.8] - 2026-02-26

### Added — **Register plugin models as NetBox ObjectTypes**

Plugin models are now available in NetBox's Content Type framework (webhooks, scripts, etc.).

---

## [0.2.7] - 2026-02-26

### Fixed — **Cable creation via ORM**

`CableTermination` rows are now created correctly when a cable is created. Cable sync works end-to-end.

---

## [0.2.6] - 2026-02-26

### Changed — **Settings page redesign**

Grouped Bootstrap card sections with a user-friendly overview of all sync settings.

---

## [0.2.5] - 2026-02-26

### Changed — **JSON fields replaced with user-friendly inputs**

The three Settings fields that previously required raw JSON are now ordinary
text fields that everyone can use without knowing JSON syntax.

| Field | Old format | New format |
|---|---|---|
| **Default tags** | `["unifi", "wifi"]` | `unifi, wifi` (comma-separated text input) |
| **Asset tag patterns** | `["[-_]?(A?ID\\d+)$"]` | One regex per line (textarea) |
| **NetBox role mappings** | `{"WIRELESS": "Wireless AP", ...}` | `WIRELESS = Wireless AP` (one mapping per line) |

All three fields continue to store the same data in the database — only the
input widget has changed.  Existing saved values are converted automatically
when the Settings page is loaded.

Validation is unchanged: asset-tag patterns are still tested as regular
expressions, and role mappings still require at least one entry.

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/forms.py` | New `_CommaSeparatedField`, `_OnePerLineField`, `_KeyValueField`; replaced `JSONTextAreaField`; renamed form fields |

## [0.2.4] - 2026-02-26

### Fixed — **Complete and validated device status dropdown**

`netbox_device_status` now uses the full set of NetBox 4.x `DeviceStatusChoices`
slugs in the correct order, including the previously missing `failed` value.

`GlobalSyncSettings.clean()` now validates the stored value against the known
set and normalises it to lowercase before saving, so manually entered values
(e.g. via shell or PLUGINS_CONFIG) are also validated.

**Valid values:** `offline`, `active`, `planned`, `staged`, `failed`,
`inventory`, `decommissioning`

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/forms.py` | Added `failed`; reordered choices to match NetBox UI order |
| `netbox_unifi_sync/models.py` | Added `VALID_DEVICE_STATUSES` + validation in `clean()` |

## [0.2.3] - 2026-02-26

### Added — **Feature parity with standalone unifi2netbox**

Six settings that existed in the standalone CLI tool were missing from the
plugin UI and DB model.  They have now been added to `GlobalSyncSettings`
(migration `0005`) and are fully wired through the orchestrator and the
`plugin_settings_to_env` layer so the sync engine picks them up as env vars.

| New field | Env var | Default | Description |
|---|---|---|---|
| `dhcp_ranges` (TextField) | `DHCP_RANGES` | *(empty)* | Manual DHCP CIDR ranges, one per line.  Merged with auto-discovered ranges. |
| `sync_dhcp_ranges` (BooleanField) | `SYNC_DHCP_RANGES` | `true` | Toggle syncing DHCP IP ranges to NetBox IPAM. |
| `default_gateway` (GenericIPAddressField) | `DEFAULT_GATEWAY` | *(null)* | Fallback gateway for DHCP→static IP conversion when UniFi lacks gateway config. |
| `default_dns` (CharField, comma-separated) | `DEFAULT_DNS` | *(empty)* | Fallback DNS server(s) for DHCP→static conversion. |
| `netbox_device_status` (CharField) | `NETBOX_DEVICE_STATUS` | `planned` | Status assigned to newly created NetBox devices. |
| `sync_prefixes` (BooleanField) | `SYNC_PREFIXES` | `true` | Sync network prefixes from UniFi to NetBox IPAM. |

### Files changed

| File | Change |
|---|---|
| `netbox_unifi_sync/models.py` | Six new fields on `GlobalSyncSettings` |
| `netbox_unifi_sync/migrations/0005_feature_parity.py` | New migration |
| `netbox_unifi_sync/services/orchestrator.py` | `_build_override()` passes new fields |
| `netbox_unifi_sync/configuration.py` | New keys in `DEFAULT_SETTINGS` and `_ENV_MAP` |
| `netbox_unifi_sync/forms.py` | Widget overrides for `dhcp_ranges` and `netbox_device_status` |

### Migration

Run `python manage.py migrate netbox_unifi_sync` to apply migration `0005`
which adds the six new columns.  All columns have safe defaults so existing
rows are migrated automatically without data loss.

## [0.2.2] - 2026-02-26

### Fixed — **Device types and devices not created (ORM create regression)**

Two bugs in the Django ORM adapter (`netbox_orm.py`) introduced in v0.2.0
prevented all new Device Types and Devices from being created during sync.

#### Bug 1 — `full_clean()` rejected valid payloads

`_Endpoint.create()` called `instance.full_clean()` before `instance.save()`.
NetBox model validators (notably `_clean_custom_fields()`) run against the full
NetBox runtime context and raise `ValidationError` on unsaved instances even
when the payload is valid.  The NetBox REST API uses DRF serialiser validation,
not `model.full_clean()`, so the ORM adapter must match that behaviour.

**Fix:** Removed `full_clean()` call.  Django's `save()` enforces `NOT NULL` and
`UNIQUE` constraints at the database level.

#### Bug 2 — FK fields passed as integers caused descriptor errors

Payloads like `{'manufacturer': 5, 'model': 'UAP-AC-Pro', ...}` assigned an
integer directly to a `ForeignKey` field.  Under Django 5 (used by NetBox 4.x),
the FK descriptor can attempt to resolve the related instance during model
construction, which may raise `ValueError` or trigger an unexpected DB query.

**Fix:** `_Endpoint.create()` now introspects `model._meta` to find all
`ForeignKey` fields and rewrites `{'field': int}` → `{'field_id': int}` before
constructing the model instance.  This is the canonical Django ORM pattern.

#### Bug 3 — `get_postable_fields()` fallback was insufficient

If Django model introspection failed (e.g. during tests or early boot),
`get_postable_fields('', '', 'dcim/devices')` returned `{}`.  The device
creation code checked `if 'role' in available_fields` and silently skipped
every device with log message *"Could not determine the syntax for the role"*.

**Fix:** A guaranteed minimum field set is now always merged in after
introspection so callers never get a false negative:
```python
_GUARANTEED = {
    "dcim/devices": {"role": True, "status": True, "device_role": True},
}
```

### Files changed

| File | Change |
|---|---|
| `unifi2netbox/services/sync/netbox_orm.py` | Remove `full_clean()`; add `_fk_fields()` to rewrite FK ints to `_id` attnames |
| `unifi2netbox/services/sync_engine.py` | Add `_GUARANTEED` field set to `get_postable_fields()` |

## [0.2.1] - 2026-02-26

### Fixed — **NetBox plugin entry point added to wheel**

The package was missing the `[project.entry-points."netbox.plugins"]` declaration
in `pyproject.toml`.  Without it the built wheel contained no `entry_points.txt`,
so package-manager based plugin discovery (the mechanism NetBox uses to locate
plugins installed via `pip`) did not work.

**Required in every NetBox plugin:**
```toml
[project.entry-points."netbox.plugins"]
netbox_unifi_sync = "netbox_unifi_sync"
```

Manual installation via `PLUGINS = ["netbox_unifi_sync"]` in `configuration.py`
continued to work, but the entry point is required for full standard compliance.

### Verified — NetBox plugin standard checklist

| Check | Status |
|---|---|
| `PluginConfig` with `name`, `verbose_name`, `version`, `author`, `base_url` | ✅ |
| `min_version` / `max_version` (`4.2.0` – `4.99.99`) | ✅ |
| `config = NetBoxUnifiSyncConfig` in `__init__.py` | ✅ |
| `menu = "navigation.menu"` (relative dotted path) | ✅ |
| `PluginMenu` / `PluginMenuItem` / `PluginMenuButton` in `navigation.py` | ✅ |
| `app_name` set in `urls.py` | ✅ |
| `netbox.jobs.JobRunner` + `system_job` for scheduled tasks | ✅ |
| Migrations present and clean (0001–0004) | ✅ |
| `[project.entry-points."netbox.plugins"]` in `pyproject.toml` | ✅ (added this release) |

## [0.2.0] - 2026-02-26

### Changed — **Architecture: Django ORM replaces pynetbox HTTP self-calls**

The sync engine previously used `pynetbox` (an HTTP REST client) to read and
write NetBox data.  Because the plugin runs *inside* the NetBox/Django process
it can access the database directly via the Django ORM — no HTTP round-trip
is needed.

All NetBox reads and writes in `sync_engine.py`, `vrf.py`, and the surrounding
helper modules now go through a thin Django ORM adapter
(`unifi2netbox.services.sync.netbox_orm.build_netbox_orm_client()`).  The
adapter exposes the same `nb.dcim.devices.get(...)`, `.filter(...)`, `.all()`
and `.create(...)` surface that the sync engine already used, so no logic in
the sync engine needed to change.

### Removed

- **`netbox_url`** field removed from `GlobalSyncSettings` model (migration
  `0004` drops the column).  The field was added in 0.1.8 to let operators
  override the internal HTTP self-call URL — it is no longer needed.
- **`pynetbox~=7.4.1`** removed from package dependencies.
- `_resolve_internal_netbox_url()`, `_resolve_internal_netbox_token()`, and
  `_inject_internal_netbox_runtime_context()` removed from `sync_service.py`.
- `netbox_url`/`netbox_token` removed from `DEFAULT_SETTINGS` and `_ENV_MAP`
  in `configuration.py`; `netbox_token` removed from `_SECRET_FIELDS`.
- `get_postable_fields()` in `sync_engine.py` no longer makes HTTP OPTIONS
  requests — it now introspects Django model `_meta` to discover writable
  fields.

### Migration

Run `python manage.py migrate netbox_unifi_sync` to apply migration `0004`
which drops the `netbox_url` column.

If you have `netbox_url` set in your `PLUGINS_CONFIG`, remove it — it is no
longer used.

### Added
- Gateway and DNS are now read from UniFi network config (`gateway_ip`, `dhcpd_dns_1-4`) for DHCP-to-static IP conversion.
- Fallback env vars `DEFAULT_GATEWAY` and `DEFAULT_DNS` when UniFi network config lacks gateway/DNS.
- 20 new unit tests covering `_get_network_info_for_ip`, `extract_dhcp_ranges_from_unifi` network info, and `is_ip_in_dhcp_range`.
- TLS verification configuration flags:
  - `UNIFI_VERIFY_SSL` (default: `true`)
  - `NETBOX_VERIFY_SSL` (default: `true`)
- UniFi session cache control:
  - `UNIFI_PERSIST_SESSION` (default: `true`)
- Robust integer parsing helper for runtime env vars (used for sync interval and cleanup grace period).

### Changed
- Runtime startup validation logs now use `logger.error(...)` for fail-fast config checks (instead of `logger.exception(...)` outside `except` blocks).
- NetBox HTTP session verify behavior is now driven by `NETBOX_VERIFY_SSL`.
- UniFi request verify behavior is now driven by `UNIFI_VERIFY_SSL`.
- `README.md`, `docs/configuration.md`, `docs/architecture.md`, and `docs/troubleshooting.md` updated to match current TLS/session behavior.
- Docker image metadata source URL corrected to the active repository.

### Security
- UniFi session cache file writes now enforce restrictive permissions (`0600`).
- Integration API auth headers are no longer persisted to session cache on disk.

### Removed
- Raw auto-generated git-log changelog format replaced by structured release notes.

## [0.1.9] - 2026-02-26

### Fixed
- JSON API endpoints (`api/status/`, `api/controllers/<pk>/test/`) were defined but
  not reachable — `api/urls.py` was never included in the plugin's `urls.py`.
  Endpoints are now mounted at `/plugins/unifi-sync/api/` and return JSON responses.

### Changed
- `api/urls.py` `app_name` corrected from `"netbox_unifi_sync-api"` (dash breaks Django
  namespace resolution) to `"netbox_unifi_sync_api"`.

## [0.1.8] - 2026-02-26

### Fixed
- Sync worker no longer falls back to `http://localhost` when `ALLOWED_HOSTS` contains
  only `["*"]` or a hostname without a port. The internal NetBox URL is now resolved as
  `http://127.0.0.1:<port>` (port extracted from `ALLOWED_HOSTS` when present, defaulting
  to `8000`). Fixes `could not be found` errors on standard Debian/venv installs where
  gunicorn listens on port 8000.

### Added
- `netbox_url` field on `GlobalSyncSettings` (Settings UI). Set this to the internal API
  base URL (e.g. `http://127.0.0.1:8000`) to override auto-detection. Leave blank to
  auto-detect.

## [0.1.7] - 2026-02-26

### Fixed
- `verify_ssl` controller setting now propagates correctly through the dry-run preflight path (`auth.py` `build_client()`).
  Previously `UnifiAuthSettings` had no `verify_ssl` field, so dry-run connection tests always used `verify_ssl=True`
  regardless of the controller's setting, causing SSL failures on self-signed certificates during dry-run.

## [0.1.6] - 2026-02-26

### Fixed
- `verify_ssl` controller setting now takes effect during Integration API probe.
  Previously `verify_ssl=False` on the controller was ignored during `__init__`
  because `configure_integration_api()` ran before the setting was applied,
  causing SSL validation failures on self-signed certificates.

## [0.1.5] - 2026-02-26

### Fixed
- Documentation corrections: removed outdated `API_TOKEN_PEPPERS` snippet, fixed `netbox:8080` references, translated wiki to English.

## [0.1.4] - 2026-02-26

### Fixed
- NetBox URL resolution now works on all platforms (venv, Docker, LXC).
  The plugin derives the internal NetBox URL from Django `ALLOWED_HOSTS` and
  `SESSION_COOKIE_SECURE`, falling back to `http://localhost`. The hardcoded
  Docker-only fallback `http://netbox:8080` has been removed.

## [0.1.3] - 2026-02-26

### Changed
- Bumped release version to `0.1.3`.
- Clarified credential policy: UniFi API key/login credentials are configured in `Controllers` UI fields.
- Updated install/config docs and wiki for Debian server flow and plugin bootstrap usage.

### Fixed
- Improved controller credential guidance in UI help and runtime error messages.

## 2026-02-25

### Fixed
- Bumped release version to `0.1.2` to avoid PyPI filename reuse rejection after prior `0.1.0` artifact deletion and existing `v0.1.1` tag collision.

## 2026-02-16

### Changed
- Repository cleanup and documentation alignment with current implementation.
- CI workflow updated to install `pytest` explicitly while keeping runtime dependencies minimal.
- Dockerfile aligned with current runtime files.
- LXC scripts updated for current repository URL and simplified install flow.

### Removed
- Unused standalone files: `unifi_client.py`, `config.py`, `exceptions.py`, `utils.py`.
- Dead code and unused imports across core modules and tests.

## 2025-02-12

### Added
- Unit test suite and CI pipeline.
- Thread limits configurable via environment variables.

### Removed
- `README-old.md` (obsolete).

### Fixed
- `.gitignore` updated with key file ignores.

## 2025-02-11

### Added
- Community device specs bundle integration.
- Generic template sync for interface/console/power templates.
- NetBox cleanup workflow.
- Auto-create device types from discovered models.
- Continuous sync loop via `SYNC_INTERVAL`.

### Fixed
- Case-insensitive part number lookup behavior.

## 2025-02-10

### Added
- DHCP auto-discovery from UniFi network configuration.
- Merge of discovered DHCP ranges with manual `DHCP_RANGES`.
- `DHCP_AUTO_DISCOVER` toggle.

## 2025-02-09

### Added
- Built-in UniFi model specs and interface template sync.
- Device type enrichment (part number, U height, PoE budget).

### Changed
- Concurrency/race condition hardening for tagging paths.

## 2025-02-08

### Added
- Cable sync and stale/offline device handling.

### Improved
- Reliability improvements in concurrent controller processing.
