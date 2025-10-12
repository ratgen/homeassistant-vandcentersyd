from __future__ import annotations
from custom_components.eforsyning.coordinator import EforsyningUpdateCoordinator

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BDForsyning from a config entry."""
    username = entry.data['username']
    password = entry.data['password']

    # supplierid = entry.data['supplierid']
    # entityname = entry.data['entityname']
    # billing_period_skew = entry.data['billing_period_skew'] # This one is true if the billing period is from July to June
    # is_water_supply = entry.data['is_water_supply'] # This one is true if the module is for eforsyning water delivery (false for regional heating)

    _LOGGER.debug(f"eForsyning ConfigData: {entry.data}")

    # Use the coordinator which handles regular fetch of API data.
    api = BDForsyning(username, password)
    coordinator = EforsyningUpdateCoordinator(hass, api, entry)
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

