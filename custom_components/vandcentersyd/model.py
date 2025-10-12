
from dataclasses import dataclass
from homeassistant.components.sensor import SensorEntityDescription

class VandcenterSydSensorDescription(SensorEntityDescription):
    attribute_data: str | None = None