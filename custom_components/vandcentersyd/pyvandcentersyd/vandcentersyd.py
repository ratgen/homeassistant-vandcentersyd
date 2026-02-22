from datetime import timedelta, datetime, timezone
from typing import Mapping

import requests
import random
import logging
import datetime

from pytz import timezone

_LOGGER = logging.getLogger(__name__)

class LoginFailed(Exception):
    """"""

class HTTPFailed(Exception):
    """Exception for HTTP Failure   """


class VandCenterAPI:
    """API for Vandcenter Syds provider BD Smart Forsyning."""
    def  __init__(self, username, password):
        self._x_session_id = None
        self._username = username
        self._password = password
        # Keep trailing slash to stay safe even if older code concatenates paths.
        self._baseurl = 'https://vandcenter.bdforsyning.dk/'

        ## Might be used later? From Eforsyning
        self._asset_id = "1"
        self._user_id = None
        self._first_year = None
        self._installation_id = "1"
        self._access_token = ""
        self._latest_year = 2000
        self._latest_year_begin = ""
        self._latest_year_end = ""
        self._customer_id = None
        self._location_id = None

    def _url(self, path: str) -> str:
        """Build absolute URL robustly regardless of leading/trailing slashes."""
        return f"{self._baseurl.rstrip('/')}/{path.lstrip('/')}"

    def _create_headers(self) -> Mapping[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": "".join(random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(8)),
            "User-Agent": "Home Assistant - Vandcenter Syd BD Forsyning Integration (requests)",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._x_session_id:
            headers["X-Session-ID"] = self._x_session_id
        return headers

    def _login(self):
        url = "api/Customer/login"
        payload = {
            "Email": self._username,
            "Password": self._password
        }

        try:
            result = requests.post(self._url(url), json=payload, headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        result_json = result.json()

        _LOGGER.debug(f"Response from API. Status: {result.status_code}, Body: {result_json}")

        self._access_token = result_json["AuthToken"]
        self._token_ttl = 3600

        return True

    def _get_customer_data(self):
        """
        Get data on the signed in customer.
        """
        url = "api/Customer?IncludeDisabledDevices=true"

        try:
            result = requests.get(self._url(url), headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        _LOGGER.debug(f"Response from API. Status: {result.status_code}, Body: {result.text}")

        result_json = result.json()

        self._customer_id = str(result_json.get("Id")) if result_json.get("Id") else None

        locations = result_json['Locations'][0]
        self._location_id = str(locations.get("LocationId")) if locations.get("LocationId") else None
        device = locations["Devices"][0]

        self._device_id = str(device['Id'])
        self._device_identifier = str(device['DeviceIdent'])

        _LOGGER.debug(f"Got installation device: {self._installation_id}")
        return device

    def get_latest(self):
        """
        Get the status of the watermeter device.
        """
        _LOGGER.debug(f"Getting latest data")

        url = "api/Stats/readings/devices"
        payload = {
            "DeviceContainerIds" : [self._device_id],
            "QuantityTypes": ["WaterVolume"],
            "Size": 1
        }

        try:
            result = requests.post(self._url(url), json=payload, headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        result_json = result.json()

        return result_json[0]["Readings"][0]

    def _get_hourly_data(self, from_time: datetime = None, to_time: datetime = None):
        def iso_z(dt: datetime) -> str:
            # Milliseconds + 'Z' for UTC
            return dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        base_payload = {
            "QuantityType": "WaterVolume",
            "Interval": "Hourly",
            "From": iso_z(from_time),
            "To": iso_z(to_time),
            "Unit": "KubicMeter",
        }

        scoped_paths = []
        if self._customer_id:
            scoped_paths.append(f"api/Stats/usage/{self._customer_id}/devices")
        if self._location_id and self._location_id != self._customer_id:
            scoped_paths.append(f"api/Stats/usage/{self._location_id}/devices")

        request_variants = [
            *[(p, {**base_payload, "DeviceIds": [self._device_id]}) for p in scoped_paths],
            ("api/Stats/usage/devices", {**base_payload, "DeviceIds": [self._device_id]}),
            ("api/Stats/usage/devicecontainers", {**base_payload, "DeviceContainerIds": [self._device_id]}),
            ("api/Stats/usage/devicecontainers", {**base_payload, "DeviceIds": [self._device_id]}),
            ("api/Stats/usage/devices", {**base_payload, "DeviceContainerIds": [self._device_id]}),
        ]

        errors: list[str] = []

        for path, payload in request_variants:
            try:
                result = requests.post(self._url(path), json=payload, headers=self._create_headers())
                result.raise_for_status()
            except requests.exceptions.RequestException as e:
                errors.append(f"{path}: {e}")
                continue

            result_json = result.json()

            rows = None
            if isinstance(result_json, dict):
                rows = result_json.get("Buckets")
                if rows is None and isinstance(result_json.get("Usage"), list):
                    rows = result_json.get("Usage")
            elif isinstance(result_json, list):
                rows = result_json

            if not isinstance(rows, list):
                errors.append(f"{path}: unexpected response shape {type(result_json).__name__}")
                continue

            filtered = [r for r in rows if isinstance(r, dict) and int(r.get("Count", 0)) > 0]
            _LOGGER.debug("Hourly usage fetched via %s (%s rows, %s kept)", path, len(rows), len(filtered))
            return filtered

        raise HTTPFailed("Hourly usage request failed for all variants: " + " | ".join(errors))
    
    def get_hourly_data(self, hours: int) -> list[dict]:
        """Fetch hourly usage for a rolling window ending now (UTC)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - timedelta(hours=hours)
        return self._get_hourly_data(from_time=start, to_time=now)

    def get_data_to(self):
        """Backward compatible alias for old callers (30-day window)."""
        return self.get_hourly_data(hours=30 * 24)


    def authenticate(self):
        try: 
            self._login()
            self._get_customer_data()
        except (LoginFailed, HTTPFailed) as err:
            _LOGGER.error(err)
            return False

        return True
