from __future__ import annotations

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

SENSORS: dict[str, type[Sensor]] = {
    "11": Dht11Sensor,
    "18b20": Ds18b20Sensor,
    "20": Dht20Sensor,
    "22": Dht22Sensor,
    "2302": Dht22Sensor,
    "aht10": Aht10Sensor,
    "am2320": Am2320Sensor,
    "bme280": Bme280Sensor,
    "bme680": Bme680Sensor,
    "dummy": DummySensor,
    "hum_raw_i2c": RawI2cHumiditySensor,
    "max31855": Max31855Sensor,
    "mcp9808": Mcp9808Sensor,
    "rpi": RpiCpuSensor,
    "si7021": Si7021Sensor,
    "temp_raw_i2c": RawI2cTemperatureSensor,
    "tmp102": Tmp102Sensor,
}
"""The supported kinds of temperature sensors, by identifier."""
