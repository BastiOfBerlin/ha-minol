"""Shared test fixtures and mock data for the Minol integration tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol.const import DOMAIN

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

MOCK_USER_INPUT = {
    "email": "test@example.com",
    "password": "testpassword123",
    "user_num": "123456789012",
}

MOCK_FETCH_ALL_RESULT = {
    "heating": {
        "unit": "KWH",
        "rooms": {
            "Wohnung 1": {
                "total": 500.0,
                "device": "04B648FD82639440",
                "monthly": {
                    "202501": 120.5,
                    "202502": 95.3,
                    "202503": None,  # current month, always null
                },
            },
        },
    },
    "warm_water": {
        "unit": "M3",
        "rooms": {
            "Wohnung 1": {
                "total": 15.0,
                "device": "04B648FD82639441",
                "monthly": {
                    "202501": 3.2,
                    "202502": 2.8,
                    "202503": None,
                },
            },
        },
    },
    "cold_water": {
        "unit": "M3",
        "rooms": {
            "Wohnung 1": {
                "total": 20.0,
                "device": "04B648FD82639442",
                "monthly": {
                    "202501": 5.1,
                    "202502": 4.7,
                    "202503": None,
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Auto-enable custom integration loading for all tests."""


@pytest.fixture
def mock_scraper() -> Generator[MagicMock]:
    """Patch MinolScraper at all three import sites and return the mock instance."""
    mock_instance = MagicMock()
    mock_instance.login = AsyncMock(return_value=None)
    mock_instance.fetch_all = AsyncMock(return_value=MOCK_FETCH_ALL_RESULT)

    mock_cls = MagicMock(return_value=mock_instance)

    with (
        patch("custom_components.minol.config_flow.MinolScraper", mock_cls),
        patch("custom_components.minol.MinolScraper", mock_cls),
        patch("custom_components.minol.coordinator.MinolScraper", mock_cls),
    ):
        yield mock_instance


@pytest.fixture
def mock_session() -> Generator[MagicMock]:
    """Patch create_session at all three import sites."""
    session = MagicMock()
    with (
        patch("custom_components.minol.config_flow.create_session", return_value=session),
        patch("custom_components.minol.create_session", return_value=session),
        patch("custom_components.minol.coordinator.create_session", return_value=session),
    ):
        yield session


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a MockConfigEntry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_USER_INPUT,
        unique_id="123456789012",
        version=1,
        options={},
    )
    entry.add_to_hass(hass)
    return entry
