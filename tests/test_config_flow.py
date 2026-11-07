"""Tests for the Minol config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.minol.const import CONF_EMAIL, CONF_PASSWORD, CONF_USER_NUM, DOMAIN

from .conftest import MOCK_USER_INPUT


@pytest.fixture
def mock_validate_credentials():
    """Patch validate_credentials to succeed by default."""
    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        return_value=None,
    ) as mock_fn:
        yield mock_fn


# ---------------------------------------------------------------------------
# User step
# ---------------------------------------------------------------------------


async def test_user_step_show_form(hass: HomeAssistant) -> None:
    """Blank call to user step shows the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_step_success(
    hass: HomeAssistant, mock_validate_credentials: MagicMock
) -> None:
    """Valid credentials create a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=MOCK_USER_INPUT
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Minol {MOCK_USER_INPUT[CONF_USER_NUM]}"
    assert result["data"] == MOCK_USER_INPUT
    entry = result["result"]
    assert entry.unique_id == MOCK_USER_INPUT[CONF_USER_NUM]


async def test_user_step_invalid_auth(hass: HomeAssistant) -> None:
    """Authentication failure sets the invalid_auth error."""
    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=RuntimeError("Authentication failed"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=MOCK_USER_INPUT
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_step_cannot_connect(hass: HomeAssistant) -> None:
    """Connection error sets the cannot_connect error."""
    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=aiohttp.ClientError(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=MOCK_USER_INPUT
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_already_configured(
    hass: HomeAssistant, mock_validate_credentials: MagicMock
) -> None:
    """Second entry with the same user_num is aborted."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_USER_INPUT,
        unique_id=MOCK_USER_INPUT[CONF_USER_NUM],
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=MOCK_USER_INPUT
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------


async def test_reauth_show_form(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reauth flow shows the confirm form with the email pre-filled."""
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Successful reauth updates the entry and aborts."""
    result = await mock_config_entry.start_reauth_flow(hass)

    new_password = "newpassword456"
    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        return_value=None,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: MOCK_USER_INPUT[CONF_EMAIL],
                CONF_PASSWORD: new_password,
            },
        )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == new_password
    assert mock_config_entry.data[CONF_USER_NUM] == MOCK_USER_INPUT[CONF_USER_NUM]


async def test_reauth_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Auth failure during reauth shows errors."""
    result = await mock_config_entry.start_reauth_flow(hass)

    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=RuntimeError("Authentication failed"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: MOCK_USER_INPUT[CONF_EMAIL],
                CONF_PASSWORD: "wrong",
            },
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_reauth_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Connection error during reauth shows errors."""
    result = await mock_config_entry.start_reauth_flow(hass)

    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=aiohttp.ClientError(),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: MOCK_USER_INPUT[CONF_EMAIL],
                CONF_PASSWORD: "wrong",
            },
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Reconfigure
# ---------------------------------------------------------------------------


async def test_reconfigure_show_form(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure flow shows the form with pre-filled email."""
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Successful reconfigure updates email/password, preserves user_num."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    new_email = "new@example.com"
    new_password = "newpass"
    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        return_value=None,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: new_email, CONF_PASSWORD: new_password},
        )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_EMAIL] == new_email
    assert mock_config_entry.data[CONF_PASSWORD] == new_password
    assert mock_config_entry.data[CONF_USER_NUM] == MOCK_USER_INPUT[CONF_USER_NUM]


async def test_reconfigure_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Auth failure during reconfigure shows errors."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=RuntimeError("Authentication failed"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: MOCK_USER_INPUT[CONF_EMAIL],
                CONF_PASSWORD: "wrong",
            },
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Connection error during reconfigure shows errors."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    with patch(
        "custom_components.minol.config_flow.validate_credentials",
        side_effect=aiohttp.ClientError(),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: MOCK_USER_INPUT[CONF_EMAIL],
                CONF_PASSWORD: "wrong",
            },
        )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow_show_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Options flow shows the form with the default 6h scan interval."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    assert "scan_interval" in schema


async def test_options_flow_set_interval(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_scraper: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Setting scan_interval stores the value in entry.options."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"scan_interval": 12}
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["scan_interval"] == 12
