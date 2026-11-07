"""Tests for the Minol sensor platform."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol.const import DOMAIN
from custom_components.minol.sensor import _latest_monthly

from .conftest import MOCK_FETCH_ALL_RESULT, MOCK_USER_INPUT

UTC = timezone.utc


# ---------------------------------------------------------------------------
# _latest_monthly (pure function)
# ---------------------------------------------------------------------------


def test_latest_monthly_normal() -> None:
    """Returns the latest non-null entry."""
    monthly = {"202501": 120.5, "202502": 95.3, "202503": None}
    assert _latest_monthly(monthly) == ("202502", 95.3)


def test_latest_monthly_all_null() -> None:
    """All null values returns (None, None)."""
    monthly = {"202501": None, "202502": None}
    assert _latest_monthly(monthly) == (None, None)


def test_latest_monthly_empty() -> None:
    """Empty dict returns (None, None)."""
    assert _latest_monthly({}) == (None, None)


def test_latest_monthly_skips_bad_values() -> None:
    """Non-numeric values are skipped."""
    monthly = {"202501": "bad", "202502": None}
    assert _latest_monthly(monthly) == (None, None)


def test_latest_monthly_numeric_string() -> None:
    """Numeric strings are coerced to float."""
    monthly = {"202501": "42.5"}
    assert _latest_monthly(monthly) == ("202501", 42.5)


def test_latest_monthly_single_valid() -> None:
    """Single valid value is returned correctly."""
    monthly = {"202501": 10.0}
    assert _latest_monthly(monthly) == ("202501", 10.0)


# ---------------------------------------------------------------------------
# Sensor entity properties (via full integration setup)
# ---------------------------------------------------------------------------


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> MockConfigEntry:
    """Set up the integration and return the loaded config entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def _get_sensor(hass: HomeAssistant, consumption_type: str, room: str = "Wohnung 1") -> object:
    """Retrieve a sensor entity by consumption type and room."""
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    user_num = MOCK_USER_INPUT["user_num"]
    safe_room = slugify(room)
    safe_type = slugify(consumption_type)
    unique_id = f"{user_num}_{safe_room}_{safe_type}"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None, f"Entity not found for unique_id={unique_id}"
    return hass.states.get(entity_id)


async def test_sensor_setup_creates_entities(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """3 consumption types × 1 room = 3 sensor entities created."""
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    minol_entities = [
        e for e in registry.entities.values() if e.domain == "sensor" and e.platform == DOMAIN
    ]
    assert len(minol_entities) == 3


async def test_sensor_native_value_heating(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Heating sensor reports the latest non-null monthly value."""
    state = _get_sensor(hass, "heating")
    assert state is not None
    assert float(state.state) == pytest.approx(95.3)


async def test_sensor_native_value_warm_water(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Warm water sensor reports the latest non-null monthly value."""
    state = _get_sensor(hass, "warm_water")
    assert float(state.state) == pytest.approx(2.8)


async def test_sensor_last_reset(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """last_reset is the 1st of the latest month in UTC."""
    state = _get_sensor(hass, "heating")
    last_reset = state.attributes.get("last_reset")
    assert last_reset is not None
    # last_reset is an ISO string in HA state attributes
    parsed = datetime.fromisoformat(last_reset)
    assert parsed.day == 1
    assert parsed.month == 2
    assert parsed.year == 2025


async def test_sensor_extra_attributes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """extra_state_attributes contains meter_serial and monthly keys."""
    state = _get_sensor(hass, "heating")
    assert "monthly" in state.attributes
    assert "meter_serial" in state.attributes
    monthly = state.attributes["monthly"]
    assert "202501" in monthly
    assert "202502" in monthly


async def test_sensor_unit_heating(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Heating sensor unit is kWh."""
    state = _get_sensor(hass, "heating")
    assert state.attributes["unit_of_measurement"] == UnitOfEnergy.KILO_WATT_HOUR


async def test_sensor_unit_warm_water(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Warm water sensor unit is m³."""
    state = _get_sensor(hass, "warm_water")
    assert state.attributes["unit_of_measurement"] == UnitOfVolume.CUBIC_METERS


async def test_sensor_state_class(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """state_class is SensorStateClass.TOTAL."""
    state = _get_sensor(hass, "heating")
    assert state.attributes["state_class"] == SensorStateClass.TOTAL


async def test_sensor_device_class_heating(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Heating sensor device_class is ENERGY."""
    state = _get_sensor(hass, "heating")
    assert state.attributes["device_class"] == SensorDeviceClass.ENERGY


async def test_sensor_device_class_water(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Water sensors device_class is WATER."""
    for ct in ("warm_water", "cold_water"):
        state = _get_sensor(hass, ct)
        assert state.attributes["device_class"] == SensorDeviceClass.WATER


async def test_sensor_unique_id(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Unique ID follows the {user_num}_{safe_room}_{safe_type} format."""
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    user_num = MOCK_USER_INPUT["user_num"]
    safe_room = slugify("Wohnung 1")
    safe_type = slugify("heating")
    expected_uid = f"{user_num}_{safe_room}_{safe_type}"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, expected_uid)
    assert entity_id is not None


async def test_sensor_device_per_meter_linked_to_hub(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Each room x type gets its own meter device, linked to the hub."""
    from homeassistant.helpers import device_registry as dr
    device_reg = dr.async_get(hass)

    user_num = MOCK_USER_INPUT["user_num"]
    room_name = "Wohnung 1"

    hub_device = device_reg.async_get_device_by_identifier(
        (DOMAIN, user_num), loaded_entry.entry_id
    )
    assert hub_device is not None

    expected = {
        "heating": ("Heat cost allocator Wohnung 1", "04B648FD82639440"),
        "warm_water": ("Hot water meter Wohnung 1", "04B648FD82639441"),
        "cold_water": ("Cold water meter Wohnung 1", "04B648FD82639442"),
    }
    for consumption_type, (name, serial) in expected.items():
        device = device_reg.async_get_device_by_identifier(
            (DOMAIN, f"{user_num}_{room_name}_{consumption_type}"),
            loaded_entry.entry_id,
        )
        assert device is not None, consumption_type
        assert device.name == name
        assert device.serial_number == serial
        assert device.manufacturer == "Minol"
        assert device.via_device_id == hub_device.id
        # No suggested_area: HA would prefix entity IDs with the area name,
        # duplicating the room that is already part of the device name.
        assert device.area_id is None


async def test_sensor_entity_uses_device_name(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The sensor is the device's main feature: friendly name == device name."""
    state = _get_sensor(hass, "cold_water")
    assert state.attributes["friendly_name"] == "Cold water meter Wohnung 1"


async def test_sensor_extra_attributes_meter_serial_value(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """meter_serial is taken from the portal's "device" field."""
    state = _get_sensor(hass, "heating")
    assert state.attributes["meter_serial"] == "04B648FD82639440"


async def test_legacy_room_device_is_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Room devices from earlier versions are dropped; entities keep their IDs."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    user_num = MOCK_USER_INPUT["user_num"]
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    legacy_device = device_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{user_num}_Wohnung 1")},
        name="Wohnung 1",
    )
    legacy_entity = entity_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{user_num}_wohnung_1_heating",
        config_entry=mock_config_entry,
        device_id=legacy_device.id,
        suggested_object_id="wohnung_1_heating",
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Entity moved to the new meter device and kept its entity_id
    moved = entity_reg.async_get(legacy_entity.entity_id)
    assert moved is not None
    assert moved.entity_id == "sensor.wohnung_1_heating"
    assert moved.device_id != legacy_device.id

    # The next coordinator update removes the now-empty legacy room device
    coordinator = mock_config_entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert device_reg.async_get(legacy_device.id) is None
    assert entity_reg.async_get(legacy_entity.entity_id) is not None


async def test_sensor_device_info_no_deprecated_via_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Room devices link to the hub via via_device_id, not deprecated via_device."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert "deprecated `via_device`" not in caplog.text


async def test_sensor_unavailable_when_coordinator_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_session: MagicMock,
) -> None:
    """Sensor is unavailable when the coordinator has no data (update failed)."""
    with patch(
        "custom_components.minol.MinolScraper",
    ) as mock_cls, patch(
        "custom_components.minol.coordinator.MinolScraper",
    ) as coord_cls:
        # Setup scraper for __init__ (login succeeds)
        init_instance = MagicMock()
        init_instance.login = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=None)
        mock_cls.return_value = init_instance

        # Coordinator fetch fails
        coord_instance = MagicMock()
        coord_instance.login = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=None)
        coord_instance.fetch_all = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            side_effect=RuntimeError("portal unavailable")
        )
        coord_cls.return_value = coord_instance

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Entry should fail to load when coordinator first refresh fails
    assert mock_config_entry.state is not __import__(
        "homeassistant.config_entries", fromlist=["ConfigEntryState"]
    ).ConfigEntryState.LOADED
