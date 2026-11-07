"""The Minol integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import voluptuous as vol

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from minol import MinolScraper

from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USER_NUM,
    CONSUMPTION_TYPES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import MinolDataCoordinator
from .session import create_session

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

IMPORT_HISTORICAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("start_month"): str,
        vol.Required("end_month"): str,
        vol.Optional("consumption_types"): [str],
        vol.Optional("dry_run", default=False): bool,
    }
)


@dataclass
class MinolRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: MinolDataCoordinator
    session_data: dict[str, Any]


type MinolConfigEntry = ConfigEntry[MinolRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register domain-level services."""

    async def handle_import_historical_data(call: ServiceCall) -> None:
        start: str = call.data["start_month"]
        end: str = call.data["end_month"]
        consumption_types: list[str] | None = call.data.get("consumption_types")
        dry_run: bool = call.data["dry_run"]

        for value in (start, end):
            if not re.fullmatch(r"\d{6}", value):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_month_format",
                    translation_placeholders={"value": value},
                )
            month_num = int(value[4:])
            if month_num < 1 or month_num > 12:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_month_value",
                    translation_placeholders={"value": value},
                )

        if start > end:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="start_after_end",
                translation_placeholders={"start": start, "end": end},
            )

        from homeassistant.util.dt import now as ha_now
        current_month = ha_now().strftime("%Y%m")
        if end > current_month:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="end_in_future",
                translation_placeholders={"end": end, "current": current_month},
            )

        if consumption_types is not None:
            for consumption_type in consumption_types:
                if consumption_type not in CONSUMPTION_TYPES:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="invalid_consumption_type",
                        translation_placeholders={
                            "value": consumption_type,
                            "valid": ", ".join(CONSUMPTION_TYPES),
                        },
                    )

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_config_entries",
            )

        for entry in entries:
            runtime_data: MinolRuntimeData | None = getattr(entry, "runtime_data", None)
            coordinator = runtime_data.coordinator if runtime_data is not None else None
            if coordinator is not None:
                try:
                    await coordinator.async_import_historical_data(
                        start, end, consumption_types=consumption_types, dry_run=dry_run
                    )
                except Exception as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="import_failed",
                        translation_placeholders={"error": str(err)},
                    ) from err

    hass.services.async_register(
        DOMAIN,
        "import_historical_data",
        handle_import_historical_data,
        schema=IMPORT_HISTORICAL_DATA_SCHEMA,
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: MinolConfigEntry) -> None:
    """Apply updated options to the running coordinator."""
    scan_hours = int(entry.options.get(
        CONF_SCAN_INTERVAL,
        DEFAULT_SCAN_INTERVAL.total_seconds() / 3600,
    ))
    coordinator = entry.runtime_data.coordinator
    coordinator.update_interval = timedelta(hours=scan_hours)
    await coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Set up Minol from a config entry."""
    session_data: dict[str, Any] = {}
    scraper = MinolScraper(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        user_num=entry.data[CONF_USER_NUM],
        session=create_session(hass),
    )
    try:
        await scraper.login(session_data=session_data)
    except RuntimeError as err:
        if "authentication failed" in str(err).lower():
            raise ConfigEntryAuthFailed(str(err)) from err
        raise

    coordinator = MinolDataCoordinator(hass, entry)
    entry.runtime_data = MinolRuntimeData(coordinator=coordinator, session_data=session_data)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await coordinator.async_config_entry_first_refresh()

    # Register a hub device for this account
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_USER_NUM])},
        name=f"Minol {entry.data[CONF_USER_NUM]}",
        manufacturer="Minol",
        model="Kundenportal",
        entry_type=DeviceEntryType.SERVICE,
    )

    user_num: str = entry.data[CONF_USER_NUM]

    @callback
    def _async_remove_stale_devices() -> None:
        current_rooms: set[str] = set()
        for type_data in coordinator.data.values():
            if not isinstance(type_data, dict):
                continue
            for room_name in type_data.get("rooms", {}):
                current_rooms.add(f"{user_num}_{room_name}")

        device_reg = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
            for domain, identifier in device.identifiers:
                if domain == DOMAIN and identifier != user_num and identifier not in current_rooms:
                    device_reg.async_update_device(
                        device.id, remove_config_entry_id=entry.entry_id
                    )

    entry.async_on_unload(coordinator.async_add_listener(_async_remove_stale_devices))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
