from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


import logging

from custom_components.vandcentersyd import VandCenterAPI
from custom_components.vandcentersyd.const import MIN_TIME_BETWEEN_UPDATES

_LOGGER = logging.getLogger(__name__)


class VandcenterSydUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator for VandcenterSyd."""

    def __init__(
            self,
            ha: HomeAssistant,
            api: VandCenterAPI,
            entry: ConfigEntry,
    ) -> None:
        """Initialize DataUpdateCoordinator"""
        self.api = api
        self.ha = ha
        self.supplierId = entry.data['supplierId']

        super().__init__(
            ha,
            _LOGGER,
            name="VandcenterSyd",
            update_interval=MIN_TIME_BETWEEN_UPDATES,
        )

    async def _async_update_data(self):
        """Get the data for VandceterSyd."""
        try:
            if not await self.ha.async_add_executor_job(self.api.authenticate):
                raise InvalidAuth
        except InvalidAuth as error:
            return False
            # That one requires the config step to have a reauth step
            # https://developers.home-assistant.io/docs/config_entries_config_flow_handler/
            # raise ConfigEntryAuthFailed from error
        except:
            _LOGGER.error(f"Some error occurred!")

        # Retrieve latest data from the API
        try:
            data = await self.ha.async_add_executor_job(self.api.get_latest)
        except Exception as error:
            raise ConfigEntryNotReady from error

        # Return the data
        # The data is stored in the coordinator as a .data field.
        return data


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""