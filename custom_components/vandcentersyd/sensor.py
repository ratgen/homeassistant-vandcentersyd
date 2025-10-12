import uuid
from typing import Any, Final

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfVolume

from .const import DOMAIN
from .coordinator import VandcenterSydUpdateCoordinator

import logging

_LOGGER = logging.getLogger(__name__)

ENTITY_NAME: Final = "Water Meter Total"


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Vandcenter Syd sensor from a config entry."""
    # API object was stored by __init__.py as hass.data[DOMAIN][config_entry.entry_id]
    api = hass.data[DOMAIN][config_entry.entry_id]

    # IMPORTANT: pass (hass, api, entry) in this order
    coordinator = VandcenterSydUpdateCoordinator(hass, api, config_entry)

    # First refresh to populate coordinator.data (raises ConfigEntryNotReady on failure)
    await coordinator.async_config_entry_first_refresh()

    # Your API returns a single reading dict -> create one entity
    async_add_entities([VandcenterSydSensor(coordinator, config_entry)])


class VandcenterSydSensor(CoordinatorEntity[VandcenterSydUpdateCoordinator], SensorEntity):
    """Total water volume (m³) from Vandcenter Syd."""

    _attr_has_entity_name = True
    _attr_name = ENTITY_NAME
    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: VandcenterSydUpdateCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry

        # Make a stable unique_id using the username+supplierId if you have them in entry.data
        supplier_id = str(entry.data.get("supplierId", "unknown"))
        username = entry.data.get("username", "user")
        namespace = uuid.uuid3(uuid.NAMESPACE_URL, f"vandcentersyd-{username}-{supplier_id}")
        self._attr_unique_id = f"vandcentersyd-total-{namespace}"

        # Device info (optional but recommended)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"vandcentersyd-{username}-{supplier_id}")},
            "name": "Vandcenter Syd Water Meter",
            "manufacturer": "BD Forsyning",
            "model": "Water Meter",
        }

        self._attrs: dict[str, Any] = {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    @property
    def native_value(self) -> float | None:
        """Return the current total m³."""
        reading = self.coordinator.data
        if not isinstance(reading, dict):
            _LOGGER.debug("Coordinator data is not a dict: %s", reading)
            return None

        value = reading.get("Value")
        unit = (reading.get("Unit") or "").lower()

        # Normalize to m³ (your API says 'KubicMeter' -> assume already m³).
        # If the API later returns liters etc., convert here.
        if value is None:
            return None

        # set attributes for debugging/visibility
        self._attrs = {
            "raw_timestamp": reading.get("Timestamp"),
            "raw_quantity_type": reading.get("QuantityType"),
            "raw_unit": reading.get("Unit"),
            "device_identifier": getattr(self.coordinator.api, "_device_identifier", None),
            "device_id": getattr(self.coordinator.api, "_device_id", None),
        }

        return float(value)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Just tell HA our properties changed; HA will call native_value/attrs again
        self.async_write_ha_state()
