"""Tests for the Minol integration __init__: setup, unload, and service."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import MOCK_USER_INPUT


# ---------------------------------------------------------------------------
# async_setup
# ---------------------------------------------------------------------------


async def test_async_setup_registers_service(hass: HomeAssistant) -> None:
    """async_setup registers the import_historical_data service."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "import_historical_data")


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_setup_entry_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Full setup: runtime_data populated, hub device created, platforms forwarded."""
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    runtime = mock_config_entry.runtime_data
    assert runtime.coordinator is not None
    assert isinstance(runtime.session_data, dict)

    # Hub device created
    from homeassistant.helpers import device_registry as dr
    device_reg = dr.async_get(hass)
    hub_device = device_reg.async_get_device(
        identifiers={(DOMAIN, MOCK_USER_INPUT["user_num"])}
    )
    assert hub_device is not None
    assert hub_device.manufacturer == "Minol"


async def test_setup_entry_auth_failed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_session: MagicMock,
) -> None:
    """Auth error during login raises ConfigEntryAuthFailed → entry in auth_failed state."""
    with patch(
        "custom_components.minol.MinolScraper",
    ) as mock_cls:
        mock_instance = MagicMock()
        mock_instance.login = AsyncMock(
            side_effect=RuntimeError("Authentication failed")
        )
        mock_cls.return_value = mock_instance

        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Unload returns True and moves entry to NOT_LOADED state."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


# ---------------------------------------------------------------------------
# Options listener
# ---------------------------------------------------------------------------


async def test_options_updated_changes_interval(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Updating options immediately changes coordinator.update_interval."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(hours=6)

    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_SCAN_INTERVAL: 12}
    )
    await hass.async_block_till_done()

    assert coordinator.update_interval == timedelta(hours=12)


# ---------------------------------------------------------------------------
# import_historical_data service validation
# ---------------------------------------------------------------------------


async def _call_service(
    hass: HomeAssistant,
    start: str,
    end: str,
    consumption_types: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    data: dict = {"start_month": start, "end_month": end, "dry_run": dry_run}
    if consumption_types is not None:
        data["consumption_types"] = consumption_types
    await hass.services.async_call(
        DOMAIN,
        "import_historical_data",
        data,
        blocking=True,
    )


async def test_service_invalid_format(hass: HomeAssistant) -> None:
    """Non-6-digit value raises ServiceValidationError with invalid_month_format."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "2025-01", "202502")
    assert exc_info.value.translation_key == "invalid_month_format"


async def test_service_invalid_month_value(hass: HomeAssistant) -> None:
    """Month number out of 1-12 range raises ServiceValidationError."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "202513", "202513")
    assert exc_info.value.translation_key == "invalid_month_value"


async def test_service_start_after_end(hass: HomeAssistant) -> None:
    """start > end raises ServiceValidationError with start_after_end."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "202506", "202501")
    assert exc_info.value.translation_key == "start_after_end"


async def test_service_end_in_future(hass: HomeAssistant) -> None:
    """end beyond the current month raises ServiceValidationError with end_in_future."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "209901", "209912")
    assert exc_info.value.translation_key == "end_in_future"


async def test_service_no_entries(hass: HomeAssistant) -> None:
    """No loaded config entries raises ServiceValidationError with no_config_entries."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "202501", "202502")
    assert exc_info.value.translation_key == "no_config_entries"


async def test_service_invalid_consumption_type(hass: HomeAssistant) -> None:
    """Unknown consumption type raises ServiceValidationError with invalid_consumption_type."""
    from custom_components.minol import async_setup
    await async_setup(hass, {})

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_service(hass, "202501", "202502", consumption_types=["gas"])
    assert exc_info.value.translation_key == "invalid_consumption_type"


async def test_service_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Valid call with loaded entry invokes coordinator.async_import_historical_data."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.async_import_historical_data = AsyncMock()

    await _call_service(hass, "202501", "202502")
    coordinator.async_import_historical_data.assert_called_once_with(
        "202501", "202502", consumption_types=None, dry_run=False
    )


async def test_service_passes_consumption_types_and_dry_run(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """consumption_types and dry_run are forwarded to the coordinator unchanged."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.async_import_historical_data = AsyncMock()

    await _call_service(
        hass, "202501", "202502", consumption_types=["heating", "warm_water"], dry_run=True
    )
    coordinator.async_import_historical_data.assert_called_once_with(
        "202501", "202502", consumption_types=["heating", "warm_water"], dry_run=True
    )


async def test_service_import_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Exception from coordinator is wrapped in HomeAssistantError."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator.async_import_historical_data = AsyncMock(side_effect=RuntimeError("portal down"))

    with pytest.raises(HomeAssistantError) as exc_info:
        await _call_service(hass, "202501", "202502")
    assert exc_info.value.translation_key == "import_failed"
