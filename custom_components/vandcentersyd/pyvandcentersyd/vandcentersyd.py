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
            result = requests.post(self._baseurl + url, json=payload, headers=self._create_headers())
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
            result = requests.get(self._baseurl + url, headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        _LOGGER.debug(f"Response from API. Status: {result.status_code}, Body: {result.text}")

        result_json = result.json()
        print(result_json)
        
        locations = result_json['Locations'][0]
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
            result = requests.post(self._baseurl + url, json=payload, headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        result_json = result.json()
        print(result_json)

        return result_json[0]["Readings"][0]

    def _get_hourly_data(self, from_time: datetime = None, to_time: datetime = None):
        url = "/api/Stats/usage/devices"

        def iso_z(dt: datetime) -> str:
            # Milliseconds + 'Z' for UTC
            return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


        payload = {
            "DeviceIds" : [self._device_id],
            "QuantityTypes": ["WaterVolume"],
            "Interval": "Hourly",
            "From": iso_z(from_time),
            "To": iso_z(to_time),
            "Unit":	"KubicMeter"
        }

        try:
            result = requests.post(self._baseurl + url, json=payload, headers=self._create_headers())
            result.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPFailed(str(e))

        result_json = result.json()
        rows = result_json["Buckets"]

        print(rows)
        print(rows[0]["Count"])

        filtered = [r for r in rows if r["Count"] == 1]
        print(filtered)
        return filtered
    
    def get_data_to(self):

        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - timedelta(days=30)

        return self._get_hourly_data(from_time=start, to_time=now)


    def authenticate(self):
        try: 
            self._login()
            self._get_customer_data()
        except (LoginFailed, HTTPFailed) as err:
            _LOGGER.error(err)
            return False

        return True

