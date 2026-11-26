from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .enum_utils import LabeledEnum, LabeledValue

if TYPE_CHECKING:
    from typing_extensions import Self


class MeasurementType(Enum):
    """What a sensor measures."""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"


@dataclass(frozen=True)
class TemperatureUnitValue(LabeledValue):
    """A temperature unit, with its label, its symbol and how it converts from Celsius."""

    symbol: str
    """The symbol of the unit, e.g. "°F"."""

    scale: float
    """How many degrees of the unit one degree Celsius is."""

    offset: float
    """The temperature that 0 °C is in the unit."""


class TemperatureUnit(LabeledEnum):
    """The unit the temperatures are shown and entered in. The plugin works in Celsius, the base unit.

    A temperature in a unit is its value in Celsius multiplied by the scale of the unit, plus the offset of the unit.
    """

    CELSIUS = TemperatureUnitValue(value="celsius", label="Celsius", symbol="°C", scale=1, offset=0)
    FAHRENHEIT = TemperatureUnitValue(value="fahrenheit", label="Fahrenheit", symbol="°F", scale=1.8, offset=32)

    symbol: str
    """The symbol of the unit."""

    scale: float
    """How many degrees of the unit one degree Celsius is."""

    offset: float
    """The temperature that 0 °C is in the unit."""

    def __new__(cls, unit_value: TemperatureUnitValue) -> Self:
        """Create a member.

        Args:
            unit_value (TemperatureUnitValue): The value, the label, the symbol and the conversion of the member.

        Returns:
            Self: The member.

        """
        member = object.__new__(cls)
        member._value_ = unit_value.value
        member.label = unit_value.label
        member.symbol = unit_value.symbol
        member.scale = unit_value.scale
        member.offset = unit_value.offset
        return member

    def from_celsius(self, celsius: float) -> float:
        """Convert a temperature from the plugin base unit, Celsius, to this unit.

        Args:
            celsius (float): The temperature, in Celsius.

        Returns:
            float: The temperature in this unit, rounded to one decimal.

        Examples:
            >>> TemperatureUnit.FAHRENHEIT.from_celsius(22.5)
            72.5
            >>> TemperatureUnit.CELSIUS.from_celsius(22.5)
            22.5

        """
        if self is TemperatureUnit.CELSIUS:
            return celsius
        return round(celsius * self.scale + self.offset, 1)

    def from_celsius_interval(self, interval: float) -> float:
        """Convert a temperature interval, a difference between two temperatures, from Celsius to this unit.

        Args:
            interval (float): The interval, in Celsius.

        Returns:
            float: The interval in this unit, rounded to one decimal.

        Examples:
            >>> TemperatureUnit.FAHRENHEIT.from_celsius_interval(5)
            9.0
            >>> TemperatureUnit.CELSIUS.from_celsius_interval(5)
            5

        """
        if self is TemperatureUnit.CELSIUS:
            return interval
        return round(interval * self.scale, 1)

    def to_celsius(self, temperature: float) -> float:
        """Convert a temperature from this unit to the plugin base unit, Celsius.

        Args:
            temperature (float): The temperature, in this unit.

        Returns:
            float: The temperature in Celsius, rounded to two decimals.

        Examples:
            >>> TemperatureUnit.FAHRENHEIT.to_celsius(74)
            23.33
            >>> TemperatureUnit.FAHRENHEIT.from_celsius(23.33)
            74.0
            >>> TemperatureUnit.CELSIUS.to_celsius(22.5)
            22.5

        """
        if self is TemperatureUnit.CELSIUS:
            return temperature
        return round((temperature - self.offset) / self.scale, 2)

    def to_celsius_interval(self, interval: float) -> float:
        """Convert a temperature interval, a difference between two temperatures, from this unit to Celsius.

        Args:
            interval (float): The interval, in this unit.

        Returns:
            float: The interval in Celsius, rounded to two decimals.

        Examples:
            >>> TemperatureUnit.FAHRENHEIT.to_celsius_interval(9)
            5.0
            >>> TemperatureUnit.CELSIUS.to_celsius_interval(5)
            5

        """
        if self is TemperatureUnit.CELSIUS:
            return interval
        return round(interval / self.scale, 2)
