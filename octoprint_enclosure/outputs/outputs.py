from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Output, OutputError
from .registry import OUTPUTS

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend

_OutputT = TypeVar("_OutputT", bound=Output)


@dataclass(frozen=True)
class OutputConfig(BaseConfig):
    """The configuration shared by all the outputs."""

    index_id: int
    """The id of the output."""

    output_type: str = ""
    """The type of the output."""


class _InvalidOutput(Output[BaseConfig]):
    """An output that can't be set up."""

    config_class = BaseConfig

    reason: str
    """Why the output can't be set up."""

    def __init__(self, reason: str, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        super().__init__(BaseConfig(), gpio, i2c, logger)
        self.reason = reason

    @override
    def run_enc_command(self, command: str) -> str | None:
        raise OutputError(self.reason)


class Outputs:
    """The outputs that drive a device."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _i2c: I2cBackend
    """The I2C backend."""

    _logger: logging.Logger

    _outputs: dict[int, Output]
    """The output with each id."""

    def __init__(self, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the outputs, with none until some settings are loaded.

        Args:
            gpio (GpioBackend): The GPIO backend, with the API of RPi.GPIO.
            i2c (I2cBackend): The I2C backend, with the API of smbus2.
            logger (logging.Logger): The logger to write to.

        """
        self._gpio = gpio
        self._i2c = i2c
        self._logger = logger.getChild("Outputs")
        self._outputs = {}

    def load(self, outputs_settings: Iterable[dict]) -> None:
        """Load some outputs from their settings.

        An output whose settings didn't change is kept as it is, with its state and the hardware it drives.
        An output that is gone, or whose settings changed, is stopped, and its pins are released unless another
        output drives them.

        Args:
            outputs_settings (Iterable[dict]): The settings of the outputs.

        """
        outputs: dict[int, Output] = {}

        # Create new outputs
        for output_settings in outputs_settings:
            try:
                output_config = OutputConfig.from_settings(output_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an output: %s", error)
                continue

            output_class = OUTPUTS.get(output_config.output_type)
            if output_class is None:
                output: Output = self._create_invalid_output(
                    output_config.index_id,
                    f"Unsupported output type: {output_config.output_type!r}",
                )
            else:
                output = self._create_output(output_class, output_config.index_id, output_settings)

            outputs[output_config.index_id] = output

        outputs_before = self._outputs
        self._outputs = outputs

        # Stop unused hardware and clear unused GPIO pins
        pins_in_use = {pin for output in outputs.values() for pin in output.gpio_pins}
        for index_id, output in outputs_before.items():
            if output in outputs.values():
                continue
            try:
                output.stop()
                for pin in output.gpio_pins - pins_in_use:
                    self._gpio.cleanup(pin)
            except Exception:
                self._logger.exception("Error releasing the hardware of output %s", index_id)

    def get(self, index_id: int, output_class: type[_OutputT]) -> _OutputT:
        """Get an output.

        Args:
            index_id (int): The id of the output.
            output_class (type[_OutputT]): The class the output must be an instance of.

        Returns:
            _OutputT: The output.

        Raises:
            OutputError: If no output of that class is set up with that id.

        """
        output = self._outputs.get(index_id)

        if isinstance(output, output_class):
            return output

        reason = output.reason if isinstance(output, _InvalidOutput) else "The output is not set up"
        raise OutputError(reason)

    def get_all(self, output_class: type[_OutputT]) -> list[_OutputT]:
        """Get all the outputs having a certain class.

        Args:
            output_class (type[_OutputT]): The class the outputs must be an instance of.

        Returns:
            list[_OutputT]: The outputs.

        """
        return [output for output in self._outputs.values() if isinstance(output, output_class)]

    def run_enc_command(self, index_id: int, command: str) -> str | None:
        """Apply an ENC command to an output.

        Args:
            index_id (int): The id of the output.
            command (str): The G-code line of the ENC command.

        Returns:
            str | None: The reply to write in the terminal, or None if no output with that id supports an ENC command.

        Raises:
            OutputError: If the output has invalid settings.
            Exception: If the command can't be applied.

        """
        output = self._outputs.get(index_id)

        if output is None:
            return None

        return output.run_enc_command(command)

    def _create_output(
        self,
        output_class: type[_OutputT],
        index_id: int,
        output_settings: dict,
    ) -> _OutputT | _InvalidOutput:
        try:
            output_config = output_class.config_class.from_settings(output_settings)
        except ValueError as error:
            return self._create_invalid_output(index_id, f"Invalid settings: {error}")

        # An output whose settings didn't change is kept, with its state and the hardware it drives
        output = self._outputs.get(index_id)
        if isinstance(output, output_class) and output.config == output_config:
            return output

        return output_class(output_config, self._gpio, self._i2c, self._get_output_logger(output_class, index_id))

    def _create_invalid_output(self, index_id: int, reason: str) -> _InvalidOutput:
        logger = self._get_output_logger(_InvalidOutput, index_id)
        logger.warning("%s", reason)
        return _InvalidOutput(reason, self._gpio, self._i2c, logger)

    def _get_output_logger(self, output_class: type[Output], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{output_class.__name__}.{index_id}")
