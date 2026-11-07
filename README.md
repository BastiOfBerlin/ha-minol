# Minol Verbrauchsdaten — Home Assistant Integration

A custom [Home Assistant](https://www.home-assistant.io/) integration that fetches heating, warm water, and cold water consumption data from the [Minol Kundenportal](https://minol.de/) and exposes it as sensors. Supports the [HA Energy Dashboard](https://www.home-assistant.io/docs/energy/) via historical statistics import.

## Features

- Sensors for **heating** (kWh), **warm water** (m³), and **cold water** (m³)
- One sensor per room and consumption type, organised under room devices
- Configurable polling interval (default: every 6 hours)
- On-demand **historical statistics import** to backfill the Energy Dashboard

## Prerequisites

- Home Assistant 2023.1 or newer
- [HACS](https://hacs.xyz/) (for the recommended installation method)
- An active Minol Kundenportal account (email + password)
- Your **Kundennummer** (customer number) — see [Finding your Kundennummer](#finding-your-kundennummer) below

## Installation

### Via HACS (recommended)

1. Open HACS in your Home Assistant sidebar.
2. Go to **Integrations** → click the three-dot menu → **Custom repositories**.
3. Add `https://codeberg.org/BastiOfBerlin/ha-minol` as an **Integration**.
4. Search for **Minol Verbrauchsdaten** and click **Download**.
5. Restart Home Assistant.

### Manual installation

1. Download or clone this repository.
2. Copy the `custom_components/minol/` directory into your HA config directory:
   ```
   <config>/custom_components/minol/
   ```
3. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Minol Verbrauchsdaten**.
3. Enter your credentials:
   | Field | Description |
   |---|---|
   | Email address | Your Minol portal login email |
   | Password | Your Minol portal password |
   | Customer number (Kundennummer) | Your 12-digit Kundennummer |
4. Click **Submit**. The integration connects to the portal and creates your sensors.

### Options

After setup, you can adjust the polling interval:

1. Go to **Settings → Devices & Services**.
2. Find **Minol** and click **Configure**.
3. Set the **Update interval** (1–72 hours, default 6).

Changes take effect immediately — no restart required.

## Sensors

For each room and consumption type the portal returns, a sensor is created:

| Sensor | Unit | Device class |
|---|---|---|
| Heating | kWh | Energy |
| Warm water | m³ | Water |
| Cold water | m³ | Water |

The sensor value is the **consumption of the most recently completed calendar month**. The current (in-progress) month always shows `null` in the portal and is skipped. Values update once a month, but the integration polls at the configured interval (default 6 hours) to catch the transition promptly.

Each sensor also exposes two extra attributes:

- `meter_serial` — the serial number of the physical meter
- `monthly` — the full monthly breakdown as a dict, e.g. `{"202501": 5.1, "202502": 3.2, "202503": null}`

### Device hierarchy

```
Minol <Kundennummer>          (hub — service device)
├── Wohnung 1
│   ├── Heating               sensor.wohnung_1_heating
│   ├── Warm water            sensor.wohnung_1_warm_water
│   └── Cold water            sensor.wohnung_1_cold_water
└── Wohnung 2
    └── ...
```

## Energy Dashboard

The sensors track live consumption, but the Energy Dashboard needs **long-term statistics**
to display historical charts. By default, statistics only accumulate from the moment the
integration is installed. To **backfill** older months — so the Energy Dashboard shows data
from before the integration was set up — use the import action:

1. Go to **Developer Tools → Actions** (or **Services** in older HA versions).
2. Select action **Minol: Import historical consumption data**.
3. Fill in the month range:
   ```yaml
   start_month: "202401"      # first month to import (YYYYMM)
   end_month: "202412"        # last month to import (YYYYMM)
   consumption_types:         # optional — omit to import all types
     - heating
   dry_run: false             # optional — set true to preview without writing
   ```
   Both `start_month` and `end_month` must be completed months — the current (in-progress)
   month and future months are rejected because the portal has no data for them yet.
4. Click **Perform action**.

The import is idempotent and can be re-run safely. It anchors imported data to whatever
statistics already exist (live-recorded or previously imported) so the Energy Dashboard shows
no spikes at the boundary, and reflects the changes immediately — no restart needed.
Incremental imports (e.g. Jan–Jun first, then Jul–Dec later) also work correctly, in either
order. Use `dry_run: true` first if you want to check the resulting sum range in the logs
before writing anything.

After importing, go to **Settings → Dashboards → Energy** and add the heating sensor as an
energy source and the water sensors as water sources.

### Example automation to import the latest month automatically

```yaml
automation:
  - alias: "Minol: import last month on the 2nd"
    trigger:
      - platform: time
        at: "06:00:00"
    condition:
      - condition: template
        value_template: "{{ now().day == 2 }}"
    action:
      - action: minol.import_historical_data
        data:
          start_month: "{{ (now().replace(day=1) - timedelta(days=1)).strftime('%Y%m') }}"
          end_month:   "{{ (now().replace(day=1) - timedelta(days=1)).strftime('%Y%m') }}"
```

## Finding your Kundennummer

The Kundennummer is a 12-digit number. You can find it in any of these places:

- **Paper correspondence** from Minol (invoices, annual statements)
- **Portal profile page** — log in at [minol.de](https://minol.de/) and check your account/profile section
- **Browser developer tools** — log in, open the Network tab, look for a `readData` POST request and find the `userNum` field in the payload

## Troubleshooting

**Integration fails to set up / "Invalid credentials"**
Verify your email, password, and Kundennummer by logging into the portal manually. The Kundennummer must match exactly the one visible in your portal account.

**Sensors show `unavailable`**
The coordinator failed its last update. Check **Settings → System → Logs** and filter for `minol`. Common causes: portal downtime, network issues, or an expired session.

**Sensor value does not update**
Data for the current month is always `null` — the value only changes once a month, after the previous month ends. This is expected behaviour.

**Statistics do not appear in the Energy Dashboard**
Run the `minol.import_historical_data` action first (see [Energy Dashboard](#energy-dashboard) above). Also confirm that the HA recorder is enabled and long-term statistics are not disabled in your configuration.

## Contributing

Issues and pull requests are welcome at the [Codeberg repository](https://codeberg.org/BastiOfBerlin/ha-minol).

## License

MIT
