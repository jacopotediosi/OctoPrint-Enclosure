from __future__ import annotations

from enum import Enum


class MeasurementType(Enum):
    """What a sensor measures."""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"


class TemperatureUnit(Enum):
    """The unit the temperatures are shown and entered in. The plugin works in Celsius, the base unit."""

    CELSIUS = "celsius"
    FAHRENHEIT = "fahrenheit"

    @property
    def symbol(self) -> str:
        """The symbol of the unit."""
        return "°F" if self is TemperatureUnit.FAHRENHEIT else "°C"

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
        if self is TemperatureUnit.FAHRENHEIT:
            return round(celsius * 1.8 + 32, 1)
        return celsius

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
        if self is TemperatureUnit.FAHRENHEIT:
            return round(interval * 1.8, 1)
        return interval

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
        if self is TemperatureUnit.FAHRENHEIT:
            return round((temperature - 32) / 1.8, 2)
        return temperature

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
        if self is TemperatureUnit.FAHRENHEIT:
            return round(interval / 1.8, 2)
        return interval
