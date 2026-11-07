"""Tests for Minol diagnostics."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol.diagnostics import async_get_config_entry_diagnostics

from .conftest import MOCK_FETCH_ALL_RESULT, MOCK_USER_INPUT


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


async def test_diagnostics_redacts_password(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Password is redacted in the diagnostics output."""
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    config = result["config_entry"]
    assert config["password"] == "**REDACTED**"


async def test_diagnostics_includes_email_and_user_num(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Non-sensitive config fields are present and unredacted."""
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    config = result["config_entry"]
    assert config["email"] == MOCK_USER_INPUT["email"]
    assert config["user_num"] == MOCK_USER_INPUT["user_num"]


async def test_diagnostics_includes_coordinator_data(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Coordinator data is present in the diagnostics output."""
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    assert "coordinator_data" in result
    data = result["coordinator_data"]
    # The mock fetch_all returns MOCK_FETCH_ALL_RESULT
    assert "heating" in data
    assert "warm_water" in data
    assert "cold_water" in data
