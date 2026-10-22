from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.core import BaseConfig

from .edge import Edge
from .gpio_input import GpioInput, GpioInputError

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Collection, Iterable, Mapping

    from octoprint_enclosure.hardware import GpioBackend

BOUNCE_TIME_MS = 200


@dataclass(frozen=True)
class GpioInputConfig(BaseConfig):
    """The configuration shared by all the GPIO inputs."""

    index_id: int
    """The id of the input."""


class _InvalidGpioInput:
    """A GPIO input that can't be set up."""

    reason: str
    """Why the input can't be set up."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


class GpioInputs:
    """The GPIO inputs."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _on_edge: Callable[[int, int], object]
    """The function called when an edge is detected, with the id of the input and the level of its pin."""

    _logger: logging.Logger

    _gpio_inputs: dict[int, GpioInput | _InvalidGpioInput]
    """The GPIO input with each id."""

    def __init__(
        self,
        gpio_inputs_settings: Iterable[dict],
        gpio: GpioBackend,
        on_edge: Callable[[int, int], object],
        logger: logging.Logger,
    ) -> None:
        """Set up some GPIO inputs.

        Args:
            gpio_inputs_settings (Iterable[dict]): The settings of the GPIO inputs.
            gpio (GpioBackend): The GPIO backend, with the API of RPi.GPIO.
            on_edge (Callable[[int, int], object]): The function called when an edge is detected on the pin of an
                input, with the id of the input and the level of the pin, 1 if high or 0 if low.
            logger (logging.Logger): The logger to write to.

        """
        self._gpio = gpio
        self._on_edge = on_edge
        self._logger = logger.getChild("GpioInputs")
        self._gpio_inputs = {}

        for gpio_input_settings in gpio_inputs_settings:
            try:
                gpio_input_config = GpioInputConfig.from_settings(gpio_input_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for a GPIO input: %s", error)
                continue

            gpio_input = self._create_gpio_input(gpio_input_config.index_id, gpio_input_settings)

            self._gpio_inputs[gpio_input_config.index_id] = gpio_input

    def get(self, index_id: int) -> GpioInput:
        """Get a GPIO input.

        Args:
            index_id (int): The id of the input.

        Returns:
            GpioInput: The input.

        Raises:
            GpioInputError: If no GPIO input is set up with that id.

        """
        gpio_input = self._gpio_inputs.get(index_id)

        if isinstance(gpio_input, GpioInput):
            return gpio_input

        reason = gpio_input.reason if isinstance(gpio_input, _InvalidGpioInput) else "The GPIO input is not set up"
        raise GpioInputError(reason)

    def get_all(self) -> list[GpioInput]:
        """Get all the GPIO inputs.

        Returns:
            list[GpioInput]: The inputs.

        """
        return [gpio_input for _, gpio_input in self._get_valid_gpio_inputs()]

    def setup_pins(self, edges: Mapping[int, Collection[Edge]]) -> None:
        """Set up the pins of the inputs, and start detecting edges on them.

        Args:
            edges (Mapping[int, Collection[Edge]]): The edges to detect on each input, by the id of the input. The edges
                of an input not listed aren't detected.

        Raises:
            Exception: If a pin can't be set up, or its edges can't be detected.

        """
        pin_edges: dict[int, set[Edge]] = {}
        for index_id, gpio_input in self._get_valid_gpio_inputs():
            gpio_input.setup_pin()
            pin_edges.setdefault(gpio_input.config.gpio_pin, set()).update(edges.get(index_id, ()))

        gpio_edges = {
            frozenset({Edge.RISE}): self._gpio.RISING,
            frozenset({Edge.FALL}): self._gpio.FALLING,
            frozenset({Edge.RISE, Edge.FALL}): self._gpio.BOTH,
        }
        for pin, detected_edges in pin_edges.items():
            if not detected_edges:
                continue

            gpio_edge = gpio_edges[frozenset(detected_edges)]
            self._logger.info("Adding GPIO event detect on pin %s with edge: %s", pin, gpio_edge)
            self._gpio.add_event_detect(pin, gpio_edge, callback=self._handle_edge, bouncetime=BOUNCE_TIME_MS)

    def clear(self) -> None:
        """Stop detecting the edges, and release the pins of the inputs.

        Raises:
            Exception: If a pin can't be released.

        """
        for pin in dict.fromkeys(gpio_input.config.gpio_pin for gpio_input in self.get_all()):
            with contextlib.suppress(Exception):
                self._gpio.remove_event_detect(pin)
            self._gpio.cleanup(pin)

    def _get_valid_gpio_inputs(self) -> list[tuple[int, GpioInput]]:
        return [
            (index_id, gpio_input)
            for index_id, gpio_input in self._gpio_inputs.items()
            if isinstance(gpio_input, GpioInput)
        ]

    def _handle_edge(self, channel: int) -> None:
        try:
            self._logger.debug("GPIO event triggered on channel %s", channel)
            level = self._gpio.input(channel)
            for index_id, gpio_input in self._get_valid_gpio_inputs():
                if gpio_input.config.gpio_pin == channel:
                    self._on_edge(index_id, level)
        except Exception:
            self._logger.exception("Error handling an edge on pin %s", channel)

    def _create_gpio_input(self, index_id: int, gpio_input_settings: dict) -> GpioInput | _InvalidGpioInput:
        try:
            gpio_config = GpioInput.config_class.from_settings(gpio_input_settings)
        except ValueError as error:
            return self._create_invalid_gpio_input(index_id, f"Invalid settings: {error}")

        return GpioInput(gpio_config, self._gpio, self._get_gpio_input_logger(index_id))

    def _create_invalid_gpio_input(self, index_id: int, reason: str) -> _InvalidGpioInput:
        self._get_gpio_input_logger(index_id).warning("%s", reason)
        return _InvalidGpioInput(reason)

    def _get_gpio_input_logger(self, index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{GpioInput.__name__}.{index_id}")
