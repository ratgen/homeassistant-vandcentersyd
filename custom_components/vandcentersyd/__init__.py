from __future__ import annotations

import logging
import voluptuous as vol

from .const import DOMAIN, SERVICE_BACKFILL_HOURLY

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from custom_components.vandcentersyd.coordinator import VandcenterSydUpdateCoordinator
from custom_components.vandcentersyd.pyvandcentersyd.vandcentersyd import VandCenterAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

BACKFILL_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("days", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
    }
)


async def _async_handle_backfill_service(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle manual backfill service call."""
    if DOMAIN not in hass.data:
        return

    target_entry_id = call.data.get("entry_id")
    days = int(call.data.get("days", 30))

    coordinators: list[VandcenterSydUpdateCoordinator] = []
    for entry_id, stored in hass.data[DOMAIN].items():
        if target_entry_id and entry_id != target_entry_id:
            continue
        coordinator = stored.get("coordinator")
        if coordinator:
            coordinators.append(coordinator)

    for coordinator in coordinators:
        await coordinator.async_request_backfill(days=days)


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

    async def _service_backfill(call: ServiceCall) -> None:
        await _async_handle_backfill_service(hass, call)

    if not hass.services.has_service(DOMAIN, SERVICE_BACKFILL_HOURLY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_BACKFILL_HOURLY,
            _service_backfill,
            schema=BACKFILL_SERVICE_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
            if hass.services.has_service(DOMAIN, SERVICE_BACKFILL_HOURLY):
                hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_HOURLY)

    return True
