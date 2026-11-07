"""Sensor platform for the Minol integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.util import slugify
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_utc

from . import MinolConfigEntry
from .const import CONF_USER_NUM, CONSUMPTION_TYPES, DOMAIN, UNIT_MAP
from .coordinator import MinolDataCoordinator, meter_device_identifier

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MinolConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Minol sensor entities."""
    coordinator: MinolDataCoordinator = entry.runtime_data.coordinator
    user_num: str = entry.data[CONF_USER_NUM]
    known_ids: set[str] = set()

    # The hub device is registered in async_setup_entry (__init__.py) before
    # platforms are forwarded; room devices link to it via its device id.
    hub_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, user_num), entry.entry_id
    )
    hub_device_id = hub_device.id if hub_device else None

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[MinolSensor] = []
        for consumption_type, type_data in coordinator.data.items():
            if not isinstance(type_data, dict):
                continue
            safe_type = slugify(consumption_type)
            for room_name in type_data.get("rooms", {}):
                safe_room = slugify(room_name)
                uid = f"{user_num}_{safe_room}_{safe_type}"
                if uid not in known_ids:
                    known_ids.add(uid)
                    new_entities.append(
                        MinolSensor(
                            coordinator=coordinator,
                            entry=entry,
                            consumption_type=consumption_type,
                            room_name=room_name,
                            user_num=user_num,
                            hub_device_id=hub_device_id,
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


def _latest_monthly(monthly: dict[str, Any]) -> tuple[str | None, float | None]:
    """Return (month_key, value) for the latest non-null monthly entry."""
    for key in sorted(monthly.keys(), reverse=True):
        value = monthly[key]
        if value is not None:
            try:
                return key, float(value)
            except (ValueError, TypeError):
                continue
    return None, None


class MinolSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """Represents one consumption meter for one room."""

    _attr_has_entity_name = True
    # The meter device is named after its type and room
    # ("Heizkostenverteiler Wohnzimmer"), so the entity is its main feature
    # and uses the device name as-is.
    _attr_name = None
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        consumption_type: str,
        room_name: str,
        user_num: str,
        hub_device_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._consumption_type = consumption_type
        self._room_name = room_name
        self._user_num = user_num

        safe_room = slugify(room_name)
        safe_type = slugify(consumption_type)
        self._attr_unique_id = f"{user_num}_{safe_room}_{safe_type}"
        self._attr_translation_key = consumption_type

        device_class, default_unit = CONSUMPTION_TYPES.get(
            consumption_type, (None, None)
        )
        self._attr_device_class = device_class

        serial = self._room_data.get("device") or None
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    meter_device_identifier(user_num, consumption_type, room_name),
                )
            },
            translation_key=consumption_type,
            translation_placeholders={"room": room_name},
            manufacturer="Minol",
            serial_number=serial,
        )
        if hub_device_id is not None:
            self._attr_device_info["via_device_id"] = hub_device_id

    @property
    def _type_data(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._consumption_type, {})

    @property
    def _room_data(self) -> dict[str, Any]:
        return self._type_data.get("rooms", {}).get(self._room_name, {})

    @property
    def _latest(self) -> tuple[str | None, float | None]:
        return _latest_monthly(self._room_data.get("monthly", {}))

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._room_name in self._type_data.get("rooms", {})
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        unit_str = self._type_data.get("unit", "")
        if unit_str in UNIT_MAP:
            return UNIT_MAP[unit_str]
        # Fall back to default from CONSUMPTION_TYPES
        _, default_unit = CONSUMPTION_TYPES.get(self._consumption_type, (None, None))
        return default_unit

    @property
    def native_value(self) -> float | None:
        _, value = self._latest
        return value

    @property
    def last_reset(self) -> datetime | None:
        month_key, _ = self._latest
        if month_key is None:
            return None
        try:
            year = int(month_key[:4])
            month = int(month_key[4:])
        except (ValueError, TypeError):
            return None
        return as_utc(datetime(year, month, 1))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self._room_data
        return {
            "meter_serial": room.get("device"),
            "monthly": dict(room.get("monthly", {})),
        }
