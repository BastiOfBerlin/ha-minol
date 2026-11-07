"""DataUpdateCoordinator for the Minol integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from minol import MinolScraper
from homeassistant.util import slugify
from homeassistant.util.dt import as_utc, now as ha_now

from .const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USER_NUM, DEFAULT_SCAN_INTERVAL, DOMAIN, UNIT_CLASS_MAP, UNIT_MAP
from .session import create_session

if TYPE_CHECKING:
    from . import MinolConfigEntry

_LOGGER = logging.getLogger(__name__)


class MinolDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the Minol portal at a configurable interval (default 6 hours)."""

    config_entry: MinolConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: MinolConfigEntry) -> None:
        scan_hours = int(config_entry.options.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL.total_seconds() / 3600,
        ))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=scan_hours),
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the portal."""
        data = self.config_entry.data
        email = data[CONF_EMAIL]
        password = data[CONF_PASSWORD]
        user_num = data[CONF_USER_NUM]

        now = ha_now()
        timeline_start = (now - relativedelta(months=13)).strftime("%Y%m")
        timeline_end = now.strftime("%Y%m")

        session_data: dict[str, Any] = self.config_entry.runtime_data.session_data
        scraper = MinolScraper(
            email=email, password=password, user_num=user_num,
            session=create_session(self.hass),
        )

        try:
            result = await scraper.login(session_data=session_data)
            if result is not None:
                session_data.update(result)
            return await scraper.fetch_all(timeline_start=timeline_start, timeline_end=timeline_end)
        except RuntimeError as err:
            if "authentication failed" in str(err).lower():
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(f"Error fetching Minol data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching Minol data: {err}") from err

    async def async_import_historical_data(
        self,
        start: str,
        end: str,
        consumption_types: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Import historical statistics for the given month range.

        Anchors imported data to the earliest existing statistic *after* the
        import range and accumulates the cumulative ``sum`` backwards from
        there, so the imported series connects seamlessly into whatever
        already exists (live-recorded or previously imported). If no such
        statistic exists yet (e.g. importing the newest months on a fresh
        install), falls back to forward accumulation seeded from the last
        statistic *before* the range, matching the previous behaviour.
        """
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.models import (
            StatisticData,
            StatisticMeanType,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
            get_last_statistics,
            statistics_during_period,
        )
        from homeassistant.helpers import entity_registry as er

        data = self.config_entry.data
        email = data[CONF_EMAIL]
        password = data[CONF_PASSWORD]
        user_num = data[CONF_USER_NUM]

        session_data: dict[str, Any] = self.config_entry.runtime_data.session_data
        scraper = MinolScraper(
            email=email, password=password, user_num=user_num,
            session=create_session(self.hass),
        )
        try:
            result = await scraper.login(session_data=session_data)
            if result is not None:
                session_data.update(result)
            raw = await scraper.fetch_all(timeline_start=start, timeline_end=end)
        except RuntimeError as err:
            if "authentication failed" in str(err).lower():
                raise ConfigEntryAuthFailed(str(err)) from err
            raise

        registry = er.async_get(self.hass)

        for consumption_type, type_data in raw.items():
            if not isinstance(type_data, dict):
                continue
            if consumption_types is not None and consumption_type not in consumption_types:
                continue
            unit_str = type_data.get("unit", "")
            unit = UNIT_MAP.get(unit_str, unit_str)
            unit_class = UNIT_CLASS_MAP.get(unit)

            for room_name, room_data in type_data.get("rooms", {}).items():
                monthly: dict[str, Any] = room_data.get("monthly", {})

                # Look up entity_id from entity registry using the sensor's unique_id
                safe_room = slugify(room_name)
                safe_type = slugify(consumption_type)
                unique_id = f"{user_num}_{safe_room}_{safe_type}"
                entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                if entity_id is None:
                    _LOGGER.warning("No sensor entity found for unique_id %s, skipping import", unique_id)
                    continue

                metadata = StatisticMetaData(
                    has_sum=True,
                    mean_type=StatisticMeanType.NONE,
                    name=None,
                    source="recorder",
                    statistic_id=entity_id,
                    unit_class=unit_class,
                    unit_of_measurement=unit,
                )

                sorted_keys = [k for k in sorted(monthly.keys()) if monthly[k] is not None]
                if not sorted_keys:
                    continue

                first_year = int(sorted_keys[0][:4])
                first_month_num = int(sorted_keys[0][4:])
                first_dt = as_utc(datetime(first_year, first_month_num, 1))

                last_year = int(sorted_keys[-1][:4])
                last_month_num = int(sorted_keys[-1][4:])
                last_dt = as_utc(datetime(last_year, last_month_num, 1))

                # Anchor point: the earliest existing statistic strictly after
                # the import range (first hour of the month following the
                # last imported month, onwards). If found, we accumulate
                # backwards from it so the imported series connects
                # seamlessly with no spike at the boundary.
                after_dt = last_dt + relativedelta(months=1)
                anchor_rows_by_id = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass, after_dt, None, {entity_id}, "hour", None, {"sum"},
                )
                anchor_rows = anchor_rows_by_id.get(entity_id) or []
                anchor_row = min(anchor_rows, key=lambda r: r["start"]) if anchor_rows else None
                sum_anchor = anchor_row.get("sum") if anchor_row else None

                stats: list[StatisticData] = []
                if sum_anchor is not None:
                    # Backward accumulation: anchor to the existing stat and
                    # work backwards through the imported months.
                    branch = "backward"
                    running_sum = sum_anchor
                    for month_key in reversed(sorted_keys):
                        value = float(monthly[month_key])
                        running_sum -= value
                        year = int(month_key[:4])
                        month_num = int(month_key[4:])
                        start_dt = as_utc(datetime(year, month_num, 1))
                        stats.append(StatisticData(start=start_dt, state=value, sum=running_sum))
                    stats.reverse()
                else:
                    # No statistic exists yet after the import range (fresh
                    # install, or importing the newest months). Fall back to
                    # forward accumulation, seeded from the last known stat
                    # before our first data point so that chained imports
                    # (e.g. Jan-Jun then Jul-Dec) stay continuous. Since
                    # nothing exists after the range, the recorder's future
                    # auto-compiled entries will continue from our last
                    # imported sum with no bridging needed.
                    branch = "forward"
                    running_sum = 0.0
                    last_stat = await get_instance(self.hass).async_add_executor_job(
                        get_last_statistics, self.hass, 1, entity_id, True, {"sum"}
                    )
                    if last_stat.get(entity_id):
                        last_entry = last_stat[entity_id][0]
                        last_start = last_entry.get("start")
                        if last_start is not None and last_start < first_dt.timestamp():
                            running_sum = last_entry.get("sum") or 0.0
                    for month_key in sorted_keys:
                        value = float(monthly[month_key])
                        running_sum += value
                        year = int(month_key[:4])
                        month_num = int(month_key[4:])
                        start_dt = as_utc(datetime(year, month_num, 1))
                        stats.append(StatisticData(start=start_dt, state=value, sum=running_sum))

                if not stats:
                    continue

                _LOGGER.info(
                    "Historical import for %s: %d month(s) [%s], anchor_sum=%s, "
                    "sum range %.3f -> %.3f%s",
                    entity_id,
                    len(stats),
                    branch,
                    f"{sum_anchor:.3f}" if sum_anchor is not None else "none",
                    stats[0]["sum"],
                    stats[-1]["sum"],
                    " (dry run, nothing written)" if dry_run else "",
                )

                if not dry_run:
                    async_import_statistics(self.hass, metadata, stats)
