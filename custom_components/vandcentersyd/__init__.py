from __future__ import annotations

import logging

from .const import DOMAIN

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from custom_components.vandcentersyd.coordinator import VandcenterSydUpdateCoordinator
from custom_components.vandcentersyd.pyvandcentersyd.vandcentersyd import VandCenterAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BDForsyning from a config entry."""
    username = entry.data['username']
    password = entry.data['password']

    _LOGGER.debug(f"eForsyning ConfigData: {entry.data}")

    # Use the coordinator which handles regular fetch of API data.
    api = VandCenterAPI(username, password)
    coordinator = VandcenterSydUpdateCoordinator(hass, api, entry)
    # If you do not want to retry setup on failure, use
    #await coordinator.async_refresh()

    # This one repeats connecting to the API until first success.
    await coordinator.async_config_entry_first_refresh()

    # Add the HomeAssistant specific API to the eForsyning integration.
    # The Sensor entity in the integration will call function here to do its thing.
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator" : coordinator
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

