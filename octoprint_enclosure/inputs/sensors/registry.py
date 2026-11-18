from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .aht10 import Aht10Sensor
from .am2320 import Am2320Sensor
from .bme280 import Bme280Sensor
from .bme680 import Bme680Sensor
from .dht import Dht11Sensor, Dht22Sensor
from .dht20 import Dht20Sensor
from .ds18b20 import Ds18b20Sensor
from .dummy import DummySensor
from .max31855 import Max31855Sensor
from .mcp9808 import Mcp9808Sensor
from .raw_i2c import RawI2cHumiditySensor, RawI2cTemperatureSensor
from .rpi_cpu import RpiCpuSensor
from .si7021 import Si7021Sensor
from .tmp102 import Tmp102Sensor

if TYPE_CHECKING:
    from .base import Sensor


@dataclass(frozen=True)
class SensorDefinition:
    """Describes a kind of temperature sensor."""

    label: str
    """The name of the kind of sensor."""

    implementation: type[Sensor]
    """The class implementing the sensor."""


SENSORS: dict[str, SensorDefinition] = {
    "aht10": SensorDefinition(label="AHT10", implementation=Aht10Sensor),
    "2302": SensorDefinition(label="AM2302", implementation=Dht22Sensor),
    "am2320": SensorDefinition(label="AM2320", implementation=Am2320Sensor),
    "bme280": SensorDefinition(label="BME280", implementation=Bme280Sensor),
    "bme680": SensorDefinition(label="BME680", implementation=Bme680Sensor),
    "11": SensorDefinition(label="DHT11", implementation=Dht11Sensor),
    "20": SensorDefinition(label="DHT20", implementation=Dht20Sensor),
    "22": SensorDefinition(label="DHT22", implementation=Dht22Sensor),
    "18b20": SensorDefinition(label="DS18B20", implementation=Ds18b20Sensor),
    "dummy": SensorDefinition(label="Dummy", implementation=DummySensor),
    "max31855": SensorDefinition(label="MAX31855", implementation=Max31855Sensor),
    "mcp9808": SensorDefinition(label="MCP9808", implementation=Mcp9808Sensor),
    "rpi": SensorDefinition(label="Raspberry Pi CPU", implementation=RpiCpuSensor),
    "hum_raw_i2c": SensorDefinition(label="Raw I2C Humidity", implementation=RawI2cHumiditySensor),
    "temp_raw_i2c": SensorDefinition(label="Raw I2C Temperature", implementation=RawI2cTemperatureSensor),
    "si7021": SensorDefinition(label="SI7021", implementation=Si7021Sensor),
    "tmp102": SensorDefinition(label="TMP102", implementation=Tmp102Sensor),
}
"""The supported kinds of temperature sensors, by identifier."""
