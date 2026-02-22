from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


import logging

from .pyvandcentersyd.vandcentersyd import VandCenterAPI
from .const import DOMAIN, MIN_TIME_BETWEEN_UPDATES

_LOGGER = logging.getLogger(__name__)

INITIAL_BACKFILL_DAYS = 30
REGULAR_WINDOW_HOURS = 3
BACKFILL_STORE_VERSION = 1


class VandcenterSydUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator for VandcenterSyd."""

    def __init__(
            self,
            ha: HomeAssistant,
            api: VandCenterAPI,
            entry: ConfigEntry,
    ) -> None:
        """Initialize DataUpdateCoordinator"""
        self.api: VandCenterAPI = api
        self.ha = ha
        self._did_initial_backfill: bool | None = None
        self._forced_backfill_hours: int | None = None
        self._backfill_store = Store(
            ha,
            BACKFILL_STORE_VERSION,
            f"{DOMAIN}_{entry.entry_id}_backfill",
        )
        # self.supplierId = entry.data['supplierId']

        super().__init__(
            ha,
            _LOGGER,
            name="VandcenterSyd",
            update_interval=MIN_TIME_BETWEEN_UPDATES,
        )

    async def _async_update_data(self):
        """Get the data for VandceterSyd."""
        authenticated = await self.ha.async_add_executor_job(self.api.authenticate)
        if not authenticated:
            raise ConfigEntryNotReady("Authentication with Vandcenter Syd failed")

        # Retrieve hourly usage. First successful refresh performs a 30-day backfill,
        # then regular updates use a short rolling window.
        try:
            if self._did_initial_backfill is None:
                saved = await self._backfill_store.async_load() or {}
                self._did_initial_backfill = bool(saved.get("done", False))

            if self._forced_backfill_hours is not None:
                data = await self.ha.async_add_executor_job(
                    self.api.get_hourly_data,
                    self._forced_backfill_hours,
                )
            elif self._did_initial_backfill:
                data = await self.ha.async_add_executor_job(
                    self.api.get_hourly_data,
                    REGULAR_WINDOW_HOURS,
                )
            else:
                data = await self.ha.async_add_executor_job(
                    self.api.get_hourly_data,
                    INITIAL_BACKFILL_DAYS * 24,
                )

            total_data = await self.ha.async_add_executor_job(self.api.get_latest)
        except Exception as error:
            raise ConfigEntryNotReady from error

        rows = data or []
        if self._forced_backfill_hours is not None:
            self._forced_backfill_hours = None

        if not self._did_initial_backfill:
            self._did_initial_backfill = True
            await self._backfill_store.async_save({"done": True})

        return {
            "Rows": rows,
            "Latest": total_data,
        }

    async def async_request_backfill(self, days: int = INITIAL_BACKFILL_DAYS) -> None:
        """Force a backfill refresh for the requested number of days."""
        self._forced_backfill_hours = max(1, int(days)) * 24
        await self.async_request_refresh()


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
