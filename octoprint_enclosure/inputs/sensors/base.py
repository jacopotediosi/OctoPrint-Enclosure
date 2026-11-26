from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

from typing_extensions import override

from octoprint_enclosure.config import HexInt, config_field
from octoprint_enclosure.inputs.config import InputConfig, PullResistor
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend
    from octoprint_enclosure.utils import MeasurementType


##########
### All sensors
##########


@dataclass(frozen=True)
class Reading:
    """A reading of a temperature sensor."""

    temperature: float | None = None
    """The temperature, in Celsius."""

    humidity: float | None = None
    """The relative humidity, in percent."""

    airquality: float | None = None
    """The air quality index."""

    def __post_init__(self) -> None:
        """Round the values to one decimal."""
        for name in ("temperature", "humidity", "airquality"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, round(float(value), 1))


class SensorError(Exception):
    """Raised when a sensor can't be read, with the reason as message."""


class SensorType(LabeledEnum):
    """The type of a temperature sensor."""

    AHT10 = LabeledValue(value="aht10", label="AHT10")
    AM2302 = LabeledValue(value="2302", label="AM2302")
    AM2320 = LabeledValue(value="am2320", label="AM2320")
    BME280 = LabeledValue(value="bme280", label="BME280")
    BME680 = LabeledValue(value="bme680", label="BME680")
    DHT11 = LabeledValue(value="11", label="DHT11")
    DHT20 = LabeledValue(value="20", label="DHT20")
    DHT22 = LabeledValue(value="22", label="DHT22")
    DS18B20 = LabeledValue(value="18b20", label="DS18B20")
    MAX31855 = LabeledValue(value="max31855", label="MAX31855")
    MCP9808 = LabeledValue(value="mcp9808", label="MCP9808")
    RPI_CPU = LabeledValue(value="rpi", label=N_("Raspberry Pi CPU"))
    RAW_I2C_HUMIDITY = LabeledValue(value="hum_raw_i2c", label=N_("Raw I2C Humidity"))
    RAW_I2C_TEMPERATURE = LabeledValue(value="temp_raw_i2c", label=N_("Raw I2C Temperature"))
    SI7021 = LabeledValue(value="si7021", label="SI7021")
    TMP102 = LabeledValue(value="tmp102", label="TMP102")


@dataclass(frozen=True)
class SensorInputConfig(InputConfig):
    """The configuration shared by all the inputs with a temperature sensor."""

    type_field_name = "temp_sensor_type"

    temp_sensor_type: SensorType = config_field(label=N_("Sensor Type"))
    """The type of the sensor."""

    temp_sensor_navbar: bool = config_field(default=True, label=N_("Show temperature in navbar"), compare=False)
    """Whether the temperature is shown in the navbar."""

    show_graph_temp: bool = config_field(
        default=False,
        label=N_("Show temperature in graph"),
        help_text=N_(
            "Shows the temperature in the OctoPrint temperature graph. Requires a graph plugin like "
            '<a href="https://github.com/jneilliii/OctoPrint-PlotlyTempGraph" target="_blank">PlotlyTempGraph</a>.',
        ),
        compare=False,
    )
    """Whether the temperature is shown in the temperature graph."""

    show_graph_humidity: bool = config_field(
        default=False,
        label=N_("Show humidity in graph"),
        help_text=N_(
            "Shows the humidity in the OctoPrint temperature graph. Requires a graph plugin like "
            '<a href="https://github.com/jneilliii/OctoPrint-PlotlyTempGraph" target="_blank">PlotlyTempGraph</a>.',
        ),
        compare=False,
    )
    """Whether the humidity is shown in the temperature graph."""


_ConfigT = TypeVar("_ConfigT", bound=SensorInputConfig)


class Sensor(ABC, Generic[_ConfigT]):
    """A temperature sensor, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    measurement_types: ClassVar[frozenset[MeasurementType]]
    """What the sensor measures."""

    config: _ConfigT
    """The configuration of the sensor."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, gpio: GpioBackend, logger: logging.Logger) -> None:
        """Set up the sensor.

        Args:
            config (_ConfigT): The configuration of the sensor.
            gpio (GpioBackend): The GPIO backend.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._gpio = gpio
        self._logger = logger

    @property
    def gpio_pins(self) -> frozenset[int]:
        """The GPIO pins the sensor sets up."""
        return frozenset()

    def setup(self) -> None:
        """Set up the pins of the sensor.

        Raises:
            Exception: If the pins can't be set up.

        """

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """


##########
### Sensors on a GPIO pin
##########


@dataclass(frozen=True)
class PinSensorConfig(SensorInputConfig):
    """The configuration shared by the sensors with a data line on a GPIO pin."""

    gpio_pin: int = config_field(
        label=N_("GPIO"),
        help_text=N_("GPIO the data line of the sensor is connected to."),
        min_value=0,
    )
    """The GPIO pin of the data line."""

    input_pull_resistor: PullResistor = config_field(
        default=PullResistor.UP,
        label=N_("Input Pull Resistor"),
        help_text=N_(
            "A sensor on a board usually has the resistor it needs already: choose None. A bare sensor needs one: "
            "choose Input Pullup, or add a 4.7K to 10K resistor between its data pin and 3.3V. If in doubt, Input "
            "Pullup does no harm.",
        ),
        choices=[PullResistor.OFF, PullResistor.UP],
    )
    """The internal pull resistor of the data line."""


_PinConfigT = TypeVar("_PinConfigT", bound=PinSensorConfig)


class PinSensor(Sensor[_PinConfigT]):
    """A sensor with a data line on a GPIO pin."""

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        if self.config.input_pull_resistor is PullResistor.OFF:
            return frozenset()
        return frozenset({self.config.gpio_pin})

    @override
    def setup(self) -> None:
        config = self.config

        if config.input_pull_resistor is PullResistor.OFF:
            return

        pull_resistors = {PullResistor.UP: self._gpio.PUD_UP, PullResistor.DOWN: self._gpio.PUD_DOWN}
        pull_resistor = pull_resistors[config.input_pull_resistor]
        self._logger.debug(
            "Setting GPIO pin %s as INPUT with pull resistor: %s",
            config.gpio_pin,
            config.input_pull_resistor.name,
        )
        self._gpio.setup(config.gpio_pin, self._gpio.IN, pull_up_down=pull_resistor)


##########
### Sensors on the I2C bus
##########


@dataclass(frozen=True)
class I2cSensorConfig(SensorInputConfig):
    """The configuration shared by the sensors on the I2C bus."""

    type_help = N_(
        "The sensor connects to the I2C bus: SDA to GPIO 2 (SDA), SCL to GPIO 3 (SCL). I2C needs to be enabled: run "
        "<code>sudo raspi-config</code> and enable I2C in the interface options.",
    )

    temp_sensor_i2cbus: int = config_field(
        default=1,
        label=N_("i2c Bus"),
        help_text=N_(
            "1 is the bus of GPIO 2 and 3. For a sensor on another bus, for example one made on other pins with "
            "<code>dtoverlay=i2c-gpio</code>, use its number: <code>i2cdetect -l</code> lists the buses.",
        ),
        min_value=0,
    )
    """The number of the I2C bus."""

    temp_sensor_address: HexInt = config_field(
        label=N_("Sensor Address"),
        help_text=N_(
            "Address of the sensor, in hexadecimal. Find it by running <code>i2cdetect -y 1</code> (from the "
            "<code>i2c-tools</code> package) on your Raspberry Pi.",
        ),
        min_value=0,
        max_value=127,
    )
    """The I2C address of the sensor."""
