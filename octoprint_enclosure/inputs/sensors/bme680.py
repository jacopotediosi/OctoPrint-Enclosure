from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from bme680 import BME680, constants
from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.utils import clamp

from .base import Reading, Sensor

BUS = 1

GAS_HEATER_TEMPERATURE_C = 320
GAS_HEATER_DURATION_MS = 150
GAS_REFERENCE_READINGS = 10

# Air quality score, from 0 (bad) to 100 (good).
# The humidity weighs 25% and is best around HUMIDITY_RELATIVE_REFERENCE.
# The gas resistance weighs 75% and is best from GAS_OHM_UPPER_LIMIT up.
HUMIDITY_WEIGHT = 0.25
HUMIDITY_RELATIVE_REFERENCE = 40
HUMIDITY_RELATIVE_REFERENCE_MARGIN = 2
GAS_WEIGHT = 0.75
GAS_OHM_LOWER_LIMIT = 5000
GAS_OHM_UPPER_LIMIT = 50000


@dataclass(frozen=True)
class Bme680Config:
    """The configuration of a BME680 sensor."""


class Bme680Sensor(Sensor[Bme680Config]):
    """A BME680 temperature, humidity and air quality sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Bme680Config:
        return Bme680Config()

    @override
    def read(self) -> Reading:
        with SMBus(BUS) as bus:
            try:
                sensor = BME680(constants.I2C_ADDR_PRIMARY, bus)
            except RuntimeError:
                sensor = BME680(constants.I2C_ADDR_SECONDARY, bus)

            sensor.set_humidity_oversample(constants.OS_2X)
            sensor.set_pressure_oversample(constants.OS_2X)
            sensor.set_temperature_oversample(constants.OS_2X)
            sensor.set_filter(constants.FILTER_SIZE_3)

            # Measure temperature and humidity
            sensor.get_sensor_data()
            temperature = cast("float", sensor.data.temperature)
            humidity = cast("float", sensor.data.humidity)

            # Measure the gas resistance, once the heater is stable
            sensor.set_gas_heater_profile(GAS_HEATER_TEMPERATURE_C, GAS_HEATER_DURATION_MS)
            while True:
                sensor.get_sensor_data()
                if sensor.data.heat_stable:
                    break
            gas_reference = 0.0
            for _ in range(1, GAS_REFERENCE_READINGS):
                sensor.get_sensor_data()
                gas_reference += cast("float", sensor.data.gas_resistance)
            gas_reference /= GAS_REFERENCE_READINGS

        # Air quality score: each part goes from 0 (worst) to 1 (best)
        if abs(humidity - HUMIDITY_RELATIVE_REFERENCE) <= HUMIDITY_RELATIVE_REFERENCE_MARGIN:
            humidity_score = 1.0
        elif humidity < HUMIDITY_RELATIVE_REFERENCE:
            humidity_score = humidity / HUMIDITY_RELATIVE_REFERENCE
        else:
            humidity_score = (100 - humidity) / (100 - HUMIDITY_RELATIVE_REFERENCE)
        gas_reference = clamp(gas_reference, GAS_OHM_LOWER_LIMIT, GAS_OHM_UPPER_LIMIT)
        gas_score = (gas_reference - GAS_OHM_LOWER_LIMIT) / (GAS_OHM_UPPER_LIMIT - GAS_OHM_LOWER_LIMIT)
        air_quality = (HUMIDITY_WEIGHT * humidity_score + GAS_WEIGHT * gas_score) * 100

        return Reading(
            temperature=round(temperature, 1),
            humidity=round(humidity, 1),
            airquality=round(air_quality, 1),
        )
