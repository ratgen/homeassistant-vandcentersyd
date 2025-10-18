from __future__ import annotations
from datetime import datetime, timezone
from homeassistant.helpers.storage import Store
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics, StatisticMetaData, StatisticData
)

STAT_ID = "vandcentersyd:water"    # keep stable
UNIT = "m³"                        # or "L"
NAME = "Vandforbrug"


def _parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)

class StatsState:
    def __init__(self, hass):
        self._store = Store(hass, 1, "vandcentersyd_stats.json")
        self.last_start: datetime | None = None
        self.last_sum: float = 0.0

    async def load(self):
        data = await self._store.async_load() or {}
        if "last_start" in data:
            self.last_start = _parse_utc(data["last_start"])
        self.last_sum = float(data.get("last_sum", 0.0))

    async def save(self):
        await self._store.async_save({
            "last_start": self.last_start.isoformat().replace("+00:00", "Z") if self.last_start else None,
            "last_sum": self.last_sum,
        })

async def push_hourly_stats(hass, rows: list[dict]):
    # Recorder must be ready
    if not get_instance(hass).async_db_ready:
        return

    state = StatsState(hass)
    await state.load()

    # de-dup by timestamp + sort
    seen = set()
    uniq = [r for r in rows if not (r["Timestamp"] in seen or seen.add(r["Timestamp"]))]
    uniq.sort(key=lambda r: r["Timestamp"])

    points: list[StatisticData] = []
    cumulative = state.last_sum
    last_kept: datetime | None = state.last_start

    for r in uniq:
        ts = _parse_utc(r["Timestamp"])
        if state.last_start and ts <= state.last_start:
            continue
        cumulative += float(r.get("Value", 0.0))
        points.append(StatisticData(start=ts, state=None, sum=cumulative))
        last_kept = ts

    if not points:
        return

    meta = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=NAME,
        source="vandcentersyd",
        statistic_id=STAT_ID,
        unit_of_measurement=UNIT,
    )

    async_add_external_statistics(hass, meta, points)

    # persist new watermark
    state.last_sum = cumulative
    state.last_start = last_kept
    await state.save()