# sensor.py
from __future__ import annotations

import uuid
import logging
from functools import partial
from typing import Any, Final, Iterable, Optional, Dict, List
from dataclasses import dataclass
from collections import OrderedDict
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.storage import Store
from homeassistant.const import UnitOfVolume
from homeassistant.util import slugify

# Recorder statistics
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,  # sync; call via executor
)
from homeassistant.components.recorder import get_instance

from .const import DOMAIN
from .coordinator import VandcenterSydUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

ENTITY_NAME: Final = "Water Meter Total"
STORE_KEY: Final = "vandcentersyd_last_pushed"
STORE_VERSION: Final = 1

# If your API Value is per-hour usage (delta), keep True.
# If your API Value is a cumulative meter reading, set to False.
VALUES_ARE_HOURLY_DELTAS: Final = True


# ----------------- time & parsing helpers -----------------

def _parse_ts_iso_utc(s: str) -> datetime:
    # Accept both "...Z" and "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

def _hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

def _normalize_unit(api_unit: str | None) -> str:
    if not api_unit:
        return UnitOfVolume.CUBIC_METERS
    return UnitOfVolume.CUBIC_METERS if api_unit.lower().startswith("kubic") else api_unit


# ----------------- shape helpers -----------------

def _ensure_rows(data: Any) -> list[dict]:
    """
    Accepts:
      - list[dict] of rows
      - dict with "Rows": [...]
      - single dict row
      - anything else -> empty list
    Each row should look like: {'Timestamp': '2025-10-18T19:00:00Z', 'Value': 0.012, 'Count': 1}
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        if "Rows" in data and isinstance(data["Rows"], list):
            return [r for r in data["Rows"] if isinstance(r, dict)]
        # single row dict
        if "Timestamp" in data and "Value" in data:
            return [data]
    return []


def _build_hourly_points(
    api_rows: Iterable[Dict[str, Any]],
    values_are_hourly_deltas: bool,
) -> List[Dict[str, Any]]:
    """
    - Skips Count == 0 (non-current / empty interval)
    - Sorts by timestamp
    - De-dupes per UTC hour (last row wins)
    Returns:
      if deltas:  [{'start': dt_utc, 'delta': m3}, ...]
      if reads:   [{'start': dt_utc, 'reading': m3}, ...]
    """
    rows = [r for r in api_rows if int(r.get("Count", 0)) != 0]
    rows.sort(key=lambda r: r["Timestamp"])

    unique: "OrderedDict[datetime, Dict[str, Any]]" = OrderedDict()
    for r in rows:
        hour = _hour_floor(_parse_ts_iso_utc(r["Timestamp"]))
        unique[hour] = r  # last write wins for same hour

    out: List[Dict[str, Any]] = []
    for hour, r in unique.items():
        val = float(r.get("Value", 0.0) or 0.0)
        if values_are_hourly_deltas:
            out.append({"start": hour, "delta": val})
        else:
            out.append({"start": hour, "reading": val})
    return out


def _to_hourly_deltas(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn cumulative readings into per-hour deltas (non-negative)."""
    points.sort(key=lambda p: p["start"])
    deltas: List[Dict[str, Any]] = []
    prev: Optional[float] = None
    for p in points:
        reading = float(p["reading"])
        delta = 0.0 if prev is None else max(0.0, reading - prev)
        deltas.append({"start": p["start"], "delta": delta})
        prev = reading
    return deltas


# ----------------- persistence for "last pushed hour" -----------------

@dataclass
class _PusherState:
    last_pushed_start: Optional[datetime] = None

    @classmethod
    def _store(cls, hass: HomeAssistant) -> Store:
        return Store(hass, STORE_VERSION, STORE_KEY)

    @classmethod
    async def load(cls, hass: HomeAssistant) -> "_PusherState":
        data = await cls._store(hass).async_load() or {}
        v = data.get("last_pushed_start_utc")
        last = datetime.fromisoformat(v) if v else None
        return cls(last_pushed_start=last)

    async def save(self, hass: HomeAssistant) -> None:
        await self._store(hass).async_save(
            {"last_pushed_start_utc": self.last_pushed_start.isoformat() if self.last_pushed_start else None}
        )


def _filter_new(points: List[Dict[str, Any]], last_pushed: Optional[datetime]) -> List[Dict[str, Any]]:
    if not points:
        return points
    points.sort(key=lambda p: p["start"])
    if last_pushed is None:
        return points
    return [p for p in points if p["start"] > last_pushed]


# ----------------- read latest sum from recorder -----------------

async def _get_last_row(hass: HomeAssistant, statistic_id: str) -> tuple[Optional[datetime], float]:
    """
    Returns (end_datetime_utc, last_sum) for statistic_id, or (None, 0.0).
    """
    # Home Assistant changed get_last_statistics signature across versions.
    # Try known call patterns in order.
    call_variants = [
        (hass, 1, statistic_id, {"sum", "state"}),
        (hass, 1, statistic_id, None, {"sum", "state"}),
    ]

    res = None
    last_error: Exception | None = None
    recorder = get_instance(hass)

    for args in call_variants:
        try:
            res = await recorder.async_add_executor_job(partial(get_last_statistics, *args))
            break
        except TypeError as err:
            last_error = err

    if res is None:
        if last_error:
            raise last_error
        return None, 0.0

    series = res.get(statistic_id) or []
    if not series:
        return None, 0.0

    row = series[-1]
    end = row.get("end")
    if isinstance(end, (int, float)):
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
    elif isinstance(end, str):
        end_dt = _parse_ts_iso_utc(end)
    else:
        end_dt = end if isinstance(end, datetime) else None
        if isinstance(end_dt, datetime) and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

    last_sum = float(row.get("sum") or 0.0)
    return end_dt, last_sum


def _stats_metadata(name: str, statistic_id: str) -> Dict[str, Any]:
    return {
        "has_mean": False,
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "device_class": "water",
    }


# ----------------- Sensor entity -----------------

async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    stored = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: VandcenterSydUpdateCoordinator = stored["coordinator"]
    async_add_entities([VandcenterSydSensor(coordinator, config_entry)])


class VandcenterSydSensor(CoordinatorEntity[VandcenterSydUpdateCoordinator], SensorEntity):
    """Total water volume (m³) from Vandcenter Syd, with external statistics ingest."""

    _attr_has_entity_name = True
    _attr_name = ENTITY_NAME
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:water"

    def __init__(self, coordinator: VandcenterSydUpdateCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        supplier_id = str(entry.data.get("supplierId", "unknown"))
        username = entry.data.get("username", "user")

        # Stable unique id for the entity
        namespace = uuid.uuid3(uuid.NAMESPACE_URL, f"vandcentersyd-{username}-{supplier_id}")
        self._attr_unique_id = f"vandcentersyd-total-{namespace}"

        # Use a stable, unique statistics id (must look like "sensor.something")
        stats_slug = slugify(f"vandcentersyd_total_{username}_{supplier_id}") or "vandcentersyd_total"
        self._statistic_id = f"sensor.{stats_slug}"

        # Device info (optional but recommended)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"vandcentersyd-{username}-{supplier_id}")},
            "name": "Vandcenter Syd Water Meter",
            "manufacturer": "VandCenter Syd",
            "model": "Axioma W1",
        }

        self._attrs: dict[str, Any] = {}
        self._state: Optional[float] = None  # cumulative total shown on the entity

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base = {
            "statistic_id": self._statistic_id,
            "last_pushed_start": getattr(self, "_last_pushed_start_iso", None),
        }
        base.update(self._attrs)
        return base

    @property
    def native_value(self) -> float | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        """On add, mirror the latest cumulative sum into the entity state."""
        _, last_sum = await _get_last_row(self.hass, self._statistic_id)
        self._state = last_sum
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Schedule async ingest (can't await in a callback)
        self.hass.async_create_task(self._ingest_and_update())
        # Also refresh attributes from the latest coordinator payload
        reading = self.coordinator.data

        latest: Optional[dict[str, Any]] = None
        raw_rows_count: Optional[int] = None

        if isinstance(reading, dict):
            rows = reading.get("Rows")
            if isinstance(rows, list):
                raw_rows_count = len(rows)

            if isinstance(reading.get("Latest"), dict):
                latest = reading.get("Latest")
            elif "Timestamp" in reading and "Value" in reading:
                latest = reading

        if isinstance(latest, dict):
            self._attrs.update({
                "raw_timestamp": latest.get("Timestamp"),
                "raw_quantity_type": latest.get("QuantityType"),
                "raw_unit": latest.get("Unit"),
                "device_identifier": getattr(self.coordinator.api, "_device_identifier", None),
                "device_id": getattr(self.coordinator.api, "_device_id", None),
            })

        if raw_rows_count is not None:
            self._attrs["raw_rows_count"] = raw_rows_count

        self.async_write_ha_state()

    async def _ingest_and_update(self) -> None:
        """
        - Takes window from coordinator (list or single row)
        - Filters Count==0, de-dupes per hour
        - Converts to cumulative and pushes external statistics
        - Updates visible sensor to latest cumulative sum
        """
        data = self.coordinator.data
        rows = _ensure_rows(data)
        if not rows:
            _LOGGER.debug("No rows to ingest from coordinator.data=%s", type(data))
            return

        # Normalize unit (not strictly needed if already m³)
        unit = _normalize_unit(rows[0].get("Unit") if rows else None)
        if unit != UnitOfVolume.CUBIC_METERS:
            _LOGGER.warning("Unexpected unit '%s' (expected m³) – please add conversion.", unit)

        # Build per-hour list
        points = _build_hourly_points(rows, values_are_hourly_deltas=VALUES_ARE_HOURLY_DELTAS)
        if not points:
            return
        if not VALUES_ARE_HOURLY_DELTAS:
            points = _to_hourly_deltas(points)

        # Load watermark (last pushed hour)
        state = await _PusherState.load(self.hass)
        new_points = _filter_new(points, state.last_pushed_start)
        if not new_points:
            # Still update entity state from DB to reflect any prior imports
            _, last_sum = await _get_last_row(self.hass, self._statistic_id)
            self._state = last_sum
            self.async_write_ha_state()
            return

        # Resume cumulative sum from recorder
        _, last_sum = await _get_last_row(self.hass, self._statistic_id)

        # Build stats payload
        running = last_sum
        payload: List[Dict[str, Any]] = []
        for p in sorted(new_points, key=lambda x: x["start"]):
            d = max(0.0, float(p["delta"]))
            running += d
            payload.append({"start": p["start"], "state": running, "sum": running})

        # Write external statistics
        await async_add_external_statistics(
            self.hass,
            _stats_metadata(self._attr_name or ENTITY_NAME, self._statistic_id),
            payload,
        )

        # Persist new watermark
        state.last_pushed_start = new_points[-1]["start"]
        self._last_pushed_start_iso = state.last_pushed_start.isoformat()
        await state.save(self.hass)

        # Update visible sensor to the new cumulative total
        self._state = running
        self.async_write_ha_state()
