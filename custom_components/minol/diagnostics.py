"""Diagnostics support for the Minol integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MinolConfigEntry
from .const import CONF_PASSWORD

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MinolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator_data": coordinator.data,
    }
