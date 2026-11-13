from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Optional

from octoprint_enclosure.outputs import (
    ColorOutput,
    ColorSetpoint,
    Output,
    OutputError,
    PwmOutput,
    PwmSetpoint,
    RegularOutput,
    RegularSetpoint,
    ThermostatOutput,
)
from octoprint_enclosure.outputs.registry import OUTPUTS
from octoprint_enclosure.permissions import PluginPermission
from octoprint_enclosure.utils import MeasurementType, Rgb, format_hex_color

from .base import BaseApi
from .bodies import UNSET, Body, Percent
from .responses import ItemResponse, error_response, item_response, list_response
from .routes import route

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from flask import Response

    from octoprint_enclosure.engine import ControlLoop, OutputExecutor
    from octoprint_enclosure.outputs import Outputs, Thermostat
    from octoprint_enclosure.plugin_context import PluginContext


def _output_types(output_class: type[Output]) -> list[str]:
    return [output_type.value for output_type, registered in OUTPUTS.items() if issubclass(registered, output_class)]


@dataclass(frozen=True)
class OutputResponse(ItemResponse):
    """An output, and its state."""

    on: bool | None
    """Whether the output is on, or null if it can't be read."""

    @classmethod
    def from_output(cls, output: Output, target: float | None, logger: logging.Logger) -> OutputResponse:
        """Describe an output, reading its state.

        Args:
            output (Output): The output.
            target (float | None): The target of the thermostat of the output, or None if the thermostat is off or
                the output is not a thermostat.
            logger (logging.Logger): The logger to write to if the output can't be read.

        Returns:
            OutputResponse: The output with its state, as the response of its type.

        Raises:
            OutputError: If the output is not set up.

        """
        config = output.config
        item = {"id": config.index_id, "type": config.output_type.value, "label": config.label}

        try:
            on = output.is_on()
        except OutputError:
            raise
        except Exception as error:  # noqa: BLE001 - a traceback at every push would fill the log
            logger.debug("Can't read output %s: %s", config.index_id, error)
            on = None

        if isinstance(output, RegularOutput):
            return RegularOutputResponse(**item, on=on)
        if isinstance(output, PwmOutput):
            return PwmOutputResponse(**item, on=on, duty_cycle=output.duty_cycle)
        if isinstance(output, ColorOutput):
            color = Rgb(0, 0, 0) if output.color is None else output.color
            return ColorOutputResponse(**item, on=on, color=format_hex_color(color))
        if isinstance(output, ThermostatOutput):
            measurement = output.config.temp_ctr_type.measurement_type.value
            return ThermostatOutputResponse(**item, on=on, target=target, measurement=measurement)

        msg = "The output is not set up"
        raise OutputError(msg)

    @classmethod
    def from_outputs(
        cls,
        outputs: Outputs,
        thermostats: Mapping[int, Thermostat],
        logger: logging.Logger,
    ) -> list[OutputResponse]:
        """Describe the outputs that are set up, reading their state.

        Args:
            outputs (Outputs): The outputs.
            thermostats (Mapping[int, Thermostat]): The thermostats, by the id of their output.
            logger (logging.Logger): The logger to write to if an output can't be read.

        Returns:
            list[OutputResponse]: The outputs with their state, each as the response of its type.

        """
        responses = []
        for output in outputs.get_all(Output):
            thermostat = thermostats.get(output.config.index_id)
            target = None if thermostat is None else thermostat.target
            try:
                responses.append(cls.from_output(output, target, logger))
            except OutputError:
                continue
        return responses


@dataclass(frozen=True)
class RegularOutputResponse(OutputResponse):
    """An output that is only on or off, like a relay."""

    type: str = field(metadata={"enum": _output_types(RegularOutput)})


@dataclass(frozen=True)
class PwmOutputResponse(OutputResponse):
    """A PWM output."""

    type: str = field(metadata={"enum": _output_types(PwmOutput)})

    duty_cycle: float = field(metadata={"examples": [40]})
    """The duty cycle, from 0 to 100."""


@dataclass(frozen=True)
class ColorOutputResponse(OutputResponse):
    """An output that shows a color, like a LED strip."""

    type: str = field(metadata={"enum": _output_types(ColorOutput)})

    color: str = field(metadata={"examples": ["#ff8800"]})
    """The color, as "#rrggbb"."""


@dataclass(frozen=True)
class ThermostatOutputResponse(OutputResponse):
    """A thermostat. It is on when its device, like a heater, is on."""

    type: str = field(metadata={"enum": _output_types(ThermostatOutput)})

    target: float | None = field(metadata={"examples": [30]})
    """The target temperature in Celsius, or the target relative humidity in percent, or null if the thermostat is
    off."""

    measurement: str = field(metadata={"enum": [measurement.value for measurement in MeasurementType]})
    """What the thermostat keeps at its target: "temperature" or "humidity"."""


@dataclass(frozen=True)
class OutputBody(Body):
    """What to change in an output, with exactly one attribute."""

    exactly_one_attribute = True

    examples = {
        "Turn a relay on": {"on": True},
        "Turn any output off": {"on": False},
        "Set the duty cycle of a PWM output": {"duty_cycle": 40},
        "Set the color of a LED strip": {"color": "#ff8800"},
        "Set the target of a thermostat": {"target": 30},
        "Turn a thermostat off": {"target": None},
    }

    on: bool = UNSET
    """Whether the output is on. False turns any output off, true turns on only an output that is only on or off."""

    duty_cycle: Percent = UNSET
    """The duty cycle of a PWM output, from 0 to 100."""

    color: Rgb = UNSET
    """The color of an output that shows a color, as "#rrggbb"."""

    target: Optional[float] = UNSET  # noqa: UP045 - Body.from_json evaluates, and float | None fails on Python < 3.10
    """The target of a thermostat, as a temperature in Celsius or a relative humidity in percent, or null to turn
    the thermostat off."""


class OutputsApi(BaseApi):
    """The HTTP API of the outputs."""

    _outputs: Outputs
    _output_executor: OutputExecutor
    _control_loop: ControlLoop

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        super().__init__(plugin_context)
        self._outputs = plugin_context.outputs
        self._output_executor = plugin_context.output_executor
        self._control_loop = plugin_context.control_loop

    @route("GET", "/outputs", permission=PluginPermission.STATUS, responses={200: [OutputResponse]})
    def get_outputs(self) -> Response:
        """List the outputs that are set up, ordered by id, with their state."""
        thermostats = self._control_loop.get_thermostats()
        return list_response(OutputResponse.from_outputs(self._outputs, thermostats, self._logger))

    @route(
        "GET",
        "/outputs/<int:output_id>",
        permission=PluginPermission.STATUS,
        responses={200: OutputResponse},
        errors={404: "No output is set up with that id."},
    )
    def get_output(self, output_id: int) -> Response:
        """Get an output, with its state."""
        try:
            return item_response(self._get_output_response(self._outputs.get(output_id, Output)))
        except OutputError:
            return error_response(404, f"No output is set up with id {output_id}.")

    @route(
        "PATCH",
        "/outputs/<int:output_id>",
        permission=PluginPermission.OUTPUTS_CONTROL,
        body=OutputBody,
        responses={200: OutputResponse},
        errors={
            404: "No output is set up with that id.",
            422: "The body is not a JSON object, or its attributes are unknown, missing, not valid, or not valid for "
            "the type of the output.",
        },
    )
    def set_output(self, output_id: int, body: OutputBody) -> Response:
        """Control an output.

        The attribute to send depends on the type of the output:

        - `on`: false turns any output off; true turns on only an output that is only on or off.
        - `duty_cycle`: for a PWM output.
        - `color`: for an output that shows a color.
        - `target`: for a thermostat; null turns it off.
        """
        try:
            output = self._outputs.get(output_id, Output)
        except OutputError:
            return error_response(404, f"No output is set up with id {output_id}.")

        is_thermostat = isinstance(output, ThermostatOutput)
        if body.on is False or (is_thermostat and body.target is None):
            if is_thermostat:
                self._control_loop.set_thermostat_target(output_id, None, wait=True)
            else:
                self._output_executor.turn_off(output_id, wait=True)
        elif is_thermostat and body.target is not None and body.target is not UNSET:
            self._control_loop.set_thermostat_target(output_id, body.target, wait=True)
        elif isinstance(output, RegularOutput) and body.on is True:
            self._output_executor.turn_on(output_id, RegularSetpoint(), wait=True)
        elif isinstance(output, PwmOutput) and body.duty_cycle is not UNSET:
            self._output_executor.turn_on(output_id, PwmSetpoint(body.duty_cycle), wait=True)
        elif isinstance(output, ColorOutput) and body.color is not UNSET:
            self._output_executor.turn_on(output_id, ColorSetpoint(body.color), wait=True)
        else:
            attribute = next(field.name for field in fields(body) if getattr(body, field.name) is not UNSET)
            problem = "can only be false" if attribute == "on" else "is not valid"
            output_type = output.config.output_type.value
            return error_response(
                422,
                f"Invalid attributes: '{attribute}' {problem} for an output of type {output_type}.",
            )

        return item_response(self._get_output_response(output))

    def _get_output_response(self, output: Output) -> OutputResponse:
        thermostat = self._control_loop.get_thermostats().get(output.config.index_id)
        target = None if thermostat is None else thermostat.target
        return OutputResponse.from_output(output, target, self._logger)
