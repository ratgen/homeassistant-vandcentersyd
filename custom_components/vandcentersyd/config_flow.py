"""Config flow for Eforsyning integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import CONF_NAME

from .const import DOMAIN


import logging

from .pyvandcentersyd.vandcentersyd import VandCenterAPI, LoginFailed, HTTPFailed

_LOGGER = logging.getLogger(__name__)


# Username/password are the ones for the website
# supplierID is found by following the README.md instruction
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


async def validate_input(ha: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # Returns True or False.  The API is not built for async operation
    # therefore it is wrapped in an async executor function.
    try:
        api = VandCenterAPI(data["username"], data["password"])
        await ha.async_add_executor_job(api.authenticate)
    except LoginFailed:
        raise InvalidAuth
    except HTTPFailed:
        raise CannotConnect

    # Return info to store in the config entry.
    # title becomes the title on the integrations screen in the UI
    return {"title": f"VandcenterSyd"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configuration flow for VandcenterSyd"""

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        _LOGGER.debug(f"Setup Step User_input = {user_input}")

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
