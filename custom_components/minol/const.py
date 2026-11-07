"""Constants for the Minol integration."""
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume

DOMAIN = "minol"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_USER_NUM = "user_num"

DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

CONF_SCAN_INTERVAL = "scan_interval"
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 72

# consumption_type -> (device_class, unit)
CONSUMPTION_TYPES: dict[str, tuple[SensorDeviceClass, str]] = {
    "heating": (SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR),
    "warm_water": (SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS),
    "cold_water": (SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS),
}

# Map API unit strings to HA unit constants
UNIT_MAP: dict[str, str] = {
    "KWH": UnitOfEnergy.KILO_WATT_HOUR,
    "M3": UnitOfVolume.CUBIC_METERS,
}

# Map HA unit constants to recorder unit_class strings
UNIT_CLASS_MAP: dict[str, str] = {
    UnitOfEnergy.KILO_WATT_HOUR: "energy",
    UnitOfVolume.CUBIC_METERS: "volume",
}
