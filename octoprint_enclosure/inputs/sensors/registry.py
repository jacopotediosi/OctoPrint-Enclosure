from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .aht10 import Aht10Sensor
from .am2320 import Am2320Sensor
from .base import SensorType
from .bme280 import Bme280Sensor
from .bme680 import Bme680Sensor
from .dht import Dht11Sensor, Dht22Sensor
from .dht20 import Dht20Sensor
from .ds18b20 import Ds18b20Sensor
from .max31855 import Max31855Sensor
from .mcp9808 import Mcp9808Sensor
from .raw_i2c import RawI2cHumiditySensor, RawI2cTemperatureSensor
from .rpi_cpu import RpiCpuSensor
from .si7021 import Si7021Sensor
from .tmp102 import Tmp102Sensor

if TYPE_CHECKING:
    from .base import Sensor

SENSORS: dict[SensorType, type[Sensor]] = {
    SensorType.AHT10: Aht10Sensor,
    SensorType.AM2302: Dht22Sensor,
    SensorType.AM2320: Am2320Sensor,
    SensorType.BME280: Bme280Sensor,
    SensorType.BME680: Bme680Sensor,
    SensorType.DHT11: Dht11Sensor,
    SensorType.DHT20: Dht20Sensor,
    SensorType.DHT22: Dht22Sensor,
    SensorType.DS18B20: Ds18b20Sensor,
    SensorType.MAX31855: Max31855Sensor,
    SensorType.MCP9808: Mcp9808Sensor,
    SensorType.RPI_CPU: RpiCpuSensor,
    SensorType.RAW_I2C_HUMIDITY: RawI2cHumiditySensor,
    SensorType.RAW_I2C_TEMPERATURE: RawI2cTemperatureSensor,
    SensorType.SI7021: Si7021Sensor,
    SensorType.TMP102: Tmp102Sensor,
}
"""The class implementing each type of temperature sensor."""

# Check that SENSORS contains every type of temperature sensor
check_all_members_mapped(SENSORS, SensorType)
