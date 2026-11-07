"""Config flow for the Minol integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from minol import MinolScraper

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USER_NUM,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)
from .session import create_session

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_USER_NUM): str,
    }
)


async def validate_credentials(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate credentials by attempting a login (no cache)."""
    scraper = MinolScraper(
        email=data[CONF_EMAIL],
        password=data[CONF_PASSWORD],
        user_num=data[CONF_USER_NUM],
        session=create_session(hass),
    )
    await scraper.login(use_cache=False)


class MinolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Minol."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> MinolOptionsFlowHandler:
        """Return the options flow handler."""
        return MinolOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_num = user_input[CONF_USER_NUM]
            await self.async_set_unique_id(user_num)
            self._abort_if_unique_id_configured()

            try:
                await validate_credentials(self.hass, user_input)
            except RuntimeError as err:
                if "authentication failed" in str(err).lower():
                    errors["base"] = "invalid_auth"
                else:
                    raise
            except aiohttp.ClientError:
                _LOGGER.exception("Connection error during setup")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Minol {user_num}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            data = {
                CONF_EMAIL: user_input[CONF_EMAIL],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_USER_NUM: reconfigure_entry.data[CONF_USER_NUM],
            }
            try:
                await validate_credentials(self.hass, data)
            except RuntimeError as err:
                if "authentication failed" in str(err).lower():
                    errors["base"] = "invalid_auth"
                else:
                    raise
            except aiohttp.ClientError:
                _LOGGER.exception("Connection error during reconfiguration")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=reconfigure_entry.data[CONF_EMAIL]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            data = {
                CONF_EMAIL: user_input[CONF_EMAIL],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_USER_NUM: reauth_entry.data[CONF_USER_NUM],
            }
            try:
                await validate_credentials(self.hass, data)
            except RuntimeError as err:
                if "authentication failed" in str(err).lower():
                    errors["base"] = "invalid_auth"
                else:
                    raise
            except aiohttp.ClientError:
                _LOGGER.exception("Connection error during reauthentication")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=reauth_entry.data[CONF_EMAIL]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class MinolOptionsFlowHandler(OptionsFlow):
    """Handle Minol options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_hours = int(self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL.total_seconds() / 3600,
        ))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_hours): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_HOURS,
                            max=MAX_SCAN_INTERVAL_HOURS,
                            step=1,
                            unit_of_measurement="hours",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
