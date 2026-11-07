# CLAUDE.md — Minol HA Integration

## Repository layout

```
hacs.json                              # HACS metadata (root)
.github/workflows/validate.yaml        # HACS + hassfest validation GitHub Action
.github/workflows/tests.yaml           # pytest (Python 3.14, pytest-homeassistant-custom-component)
requirements_test.txt                  # Pinned test dependencies
custom_components/minol/
    __init__.py       async_setup (service registration) + async_setup_entry/unload
    manifest.json     HA integration manifest; pins minol==1.3.0; requires HA 2026.7+
    config_flow.py    Config flow: initial setup + reauthentication
    const.py          DOMAIN, config keys, CONSUMPTION_TYPES, UNIT_MAP
    coordinator.py    MinolDataCoordinator + async_import_historical_data()
    sensor.py         MinolSensor (one per room × consumption type)
    services.yaml     import_historical_data action description
    strings.json      English UI strings (source of truth for translations)
    translations/
        en.json       English
        de.json       German
    brand/
        logo.png      Minol landscape logo (for HA brand display, HA 2026.3+)
        icon.png      Square 256×256 icon — MISSING, needs to be created manually
.claude/skills/homeassistant/SKILL.md  HA development skill
```

## Non-obvious design decisions

### Historical import: backward anchor accumulation (no bridge entry needed)
`async_import_historical_data()` uses `source="recorder"` and `statistic_id=entity_id`,
placing imported monthly data into the **same** statistics series as the recorder's
auto-compiled hourly entries for the sensor. An earlier version of this method accumulated
`sum` forward from zero (or from the last stat before the range) and then had to patch a
"bridge" entry afterwards to reconcile with the recorder's auto-compiled sum — see the git
history if you need the old approach.

The current method instead queries `statistics_during_period()` for the **earliest existing
statistic strictly after the import range** (the month following the last imported month,
onward). If found, that entry's `sum` becomes the anchor, and monthly deltas are subtracted
working **backwards** from it — so the last imported entry's `sum` is exactly
`anchor_sum - last_month_delta`, guaranteeing continuity with no spike, no bridge entry
required. If nothing exists yet after the range (fresh install, or importing the newest
months), it falls back to forward accumulation seeded from the last stat *before* the range
(or zero) — see the inline comments in `coordinator.py` for the full explanation.

### Import validation: end ≤ current month
The portal returns `null` for the in-progress month and has no future data. The import
service therefore rejects `end` values beyond the current month with a clear error message.
Allowing future months would import no useful data and could seed `running_sum` incorrectly
if the portal ever returned unexpected values for those months.

### `total` field is not used — use monthly values instead
The portal's `total` field for heating is in **raw meter units**, not KWH. Monthly values are
already normalized (KWH / M³). The sensor `native_value` is therefore the **latest non-null
monthly value**, and `last_reset` is set to the 1st of that month.

### Current month is always null
The portal only posts a value after a calendar month fully ends. `"202503": null` is normal
for an in-progress month. `_latest_monthly()` in `sensor.py` skips nulls and returns the most
recent completed month. Don't treat null as an error.

### Re-auth: fresh scraper per call, in-memory session caching
A new `MinolScraper` is created on every coordinator update. The session token is kept in a
`session_data: dict` stored on `entry.runtime_data` (a `MinolRuntimeData` dataclass). Passing
this dict to `scraper.login(session_data=...)` is nearly free when the session is still valid;
the library re-authenticates transparently on expiry and returns an updated dict. On HA restart,
`async_setup_entry` does a fresh login and repopulates `session_data`. No disk I/O required.

### Reauthentication flow

When `_async_update_data()` in the coordinator raises `ConfigEntryAuthFailed`, HA calls
`async_step_reauth` on the config flow, which delegates to `async_step_reauth_confirm`.

The confirm step shows a form with email (pre-filled from the existing entry) and password.
`user_num` is preserved — it never changes. On success, `async_update_reload_and_abort()`
atomically updates `entry.data`, reloads the integration, and aborts with `"reauth_successful"`.

Auth errors from the scraper are `RuntimeError` with messages containing `"authentication failed"`
(case-insensitive). The coordinator catches these and raises `ConfigEntryAuthFailed` to trigger
the flow. Non-auth `RuntimeError`s go to `UpdateFailed` as before.

### Configurable poll interval (Options flow)
The scan interval defaults to 6 hours (`DEFAULT_SCAN_INTERVAL`) and can be changed per config
entry via the HA Options flow (1–72 hours). The value is stored in `entry.options["scan_interval"]`
as an integer (hours). An update listener (`_async_options_updated`) in `async_setup_entry` applies
changes immediately without requiring a restart.

### aiohttp session: `async_create_clientsession` with `quote_cookie=False`
All `MinolScraper` instances are created with `session=create_session(hass)` (defined in
`session.py`) instead of HA's shared `async_get_clientsession`. Reason: Azure AD B2C sets
cookies whose base64 values contain `+`, `/`, `=`. HA's shared session uses the aiohttp-default
`quote_cookie=True`, which wraps those values in double-quotes — RFC 6265 §4.2.1 forbids
quoted-string in Cookie request headers, so B2C rejects them with HTTP 400.

`create_session` calls `async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True,
quote_cookie=False))` — this still shares HA's TCP connector (connection pool + SSL config) and
auto-cleans on entry unload, while substituting our own jar. This is the HA-blessed pattern for
cookie-using integrations (HA quality scale rule `inject-websession`; precedent: LaMarzocco PR #148385).

### `async_setup` vs `async_setup_entry` for service registration
`minol.import_historical_data` is registered in `async_setup` (domain-level, called once at startup)
rather than `async_setup_entry` (called per config entry). This prevents duplicate registration
if the user configures multiple accounts, and matches HA convention for domain-wide services.
The handler then walks `hass.config_entries.async_entries(DOMAIN)` to find active coordinators.

### Statistic ID = the sensor's own entity_id (source="recorder")
Imported statistics are **not** written under a custom `minol:...` external statistic id.
`coordinator.py` resolves the sensor's real `entity_id` (e.g. `sensor.wohnung_1_heating`) from
the entity registry via its `unique_id` (`{user_num}_{safe_room}_{safe_type}`, slugified) and
passes that as `statistic_id` with `source="recorder"` — the only valid pairing for an internal
statistic tied to a live entity. This must stay consistent between `coordinator.py` and
`sensor.py`'s unique_id construction, as a mismatch would silently skip the import (logged as a
warning) rather than create orphaned statistics.

### `state_class = TOTAL` with `last_reset`, not `TOTAL_INCREASING`
Each sensor value is a **per-period** consumption (one month), not a cumulative odometer reading.
`TOTAL` + `last_reset` signals to HA that the counter resets each period, which is correct for
the Energy Dashboard. `TOTAL_INCREASING` would be wrong here.

## Device hierarchy

```
Hub device:  identifiers={(DOMAIN, user_num)}           — DeviceEntryType.SERVICE
Room device: identifiers={(DOMAIN, f"{user_num}_{room_name}")}  — via_device → hub
Sensors:     attached to room device
```

## Unique IDs

- Config entry unique ID: `user_num` (prevents duplicate accounts)
- Sensor unique ID: `{user_num}_{safe_room}_{consumption_type}`

`safe_room` = `room_name.lower().replace(" ", "_")`. If room names from the portal ever change,
entities will be re-created with new IDs (old ones become unavailable). This is a known limitation.

## Data flow

```
config_flow      →  await scraper.login(use_cache=False)   validates at setup time
async_setup_entry→  await scraper.login(session_data={})   initial auth, fills session_data
coordinator      →  every N hours (default 6, configurable via options): await scraper.login(session_data) + await scraper.fetch_all(...)
                     timeline_start = ~13 months ago, timeline_end = current month
                     session_data lives in entry.runtime_data (MinolRuntimeData)
sensor           →  reads coordinator.data, shows latest non-null monthly value
service          →  import_historical_data(start, end, consumption_types?, dry_run?): fetches
                     range, calls async_import_historical_data() (backward-anchor accumulation)
```

## Syntax / validity checks

```bash
# Python syntax
for f in custom_components/minol/*.py; do
  python3 -c "import ast; ast.parse(open('$f').read())" && echo "OK: $f"
done

# JSON validity
for f in hacs.json custom_components/minol/manifest.json \
         custom_components/minol/strings.json \
         custom_components/minol/translations/*.json; do
  python3 -m json.tool "$f" > /dev/null && echo "OK: $f"
done
```

## Installing the library for local testing

`pip install -e .` fails on the `/workspace` filesystem (`EPERM` on `os.rename`). Workarounds:

```bash
# Option A: copy to /tmp first
mkdir -p /tmp/minol-build
cp -r /workspace/minol /workspace/pyproject.toml /tmp/minol-build/
pip install /tmp/minol-build

# Option B: run without installing (works because /workspace is on sys.path)
python -m minol --help
```

## Things to keep in mind when making changes

- **strings.json is the source of truth** — `translations/en.json` must be a copy of it.
  HA validates that all keys in `strings.json` exist in each translation file.
- **manifest.json `version`** must be bumped for HACS to offer an update to users.
- **`requirements`** pins `minol==1.3.0`. If the scraper API changes in a new release, update
  both `manifest.json` and verify `fetch_all()` kwargs and response shape still match.
- **No entities are added dynamically** after initial setup. If the user registers a new meter
  in the portal, they need to reload the integration to pick it up.

## HACS compliance TODOs

These items cannot be resolved in-repo and require manual action:

- **First release**: Create a tagged release (e.g. `v1.0.0`) on the hosting platform so HACS
  can offer version-based installs to users.

