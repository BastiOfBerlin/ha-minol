"""aiohttp session factory for the Minol integration."""
from __future__ import annotations

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Create an aiohttp session with quote_cookie=False for Azure AD B2C compat.

    HA's shared session uses quote_cookie=True (aiohttp default), which wraps
    base64 cookie values in double-quotes. Azure AD B2C rejects those per
    RFC 6265 §4.2.1. We use async_create_clientsession so we still share HA's
    TCP connector (connection pool + SSL config) and auto-clean on entry unload,
    while substituting our own jar.
    """
    return async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(unsafe=True, quote_cookie=False),
    )
