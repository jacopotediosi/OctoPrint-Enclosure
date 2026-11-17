from __future__ import annotations

import functools
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint.events import Events

from octoprint_enclosure.hardware import dummy_gpio, dummy_i2c
from octoprint_enclosure.inputs import GpioInputError, PullResistor
from octoprint_enclosure.outputs import Output

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.engine import ControlLoop
    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.inputs.config import InputConfig
    from octoprint_enclosure.inputs.sensors.dummy import DummySensor
    from octoprint_enclosure.outputs import Outputs
    from octoprint_enclosure.plugin_context import PluginContext

NUMBER_REGEX = r"-?\d+(?:\.\d+)?"

EVENT_PAYLOAD = {"path": "encdev.gcode", "name": "encdev.gcode", "time": 0, "state_string": "Error: @ENCDEV"}


class _CommandError(Exception):
    """Raised when a command can't run, with the reason as message."""


@dataclass(frozen=True)
class _Command:
    """An @ENCDEV command."""

    pattern: str
    """The regular expression the command (and its parameters) match."""

    usage: str
    """The human-readable syntax of the command."""

    method: Callable[..., None]
    """The method running the command."""


class EncDevHandler:
    """Handles the @ENCDEV G-code commands."""

    _printer: PrinterInterface
    _sensors: Sensors
    _gpio_inputs: GpioInputs
    _sensor_poller: SensorPoller
    _outputs: Outputs
    _control_loop: ControlLoop
    _logger: logging.Logger

    _development_mode: bool
    """Whether the plugin runs in development mode."""

    _commands: tuple[_Command, ...]

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the handler.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        self._printer = plugin_context.printer
        self._sensors = plugin_context.sensors
        self._gpio_inputs = plugin_context.gpio_inputs
        self._sensor_poller = plugin_context.sensor_poller
        self._outputs = plugin_context.outputs
        self._control_loop = plugin_context.control_loop
        self._logger = plugin_context.logger.getChild("EncDevHandler")

        self._development_mode = plugin_context.development_mode

        self._commands = (
            _Command(
                pattern=r"STATUS",
                usage="STATUS",
                method=self._status,
            ),
            _Command(
                pattern=r"INPUT (\d+) (PRESS|ACTIVE|INACTIVE)",
                usage="INPUT <id> PRESS|ACTIVE|INACTIVE",
                method=self._input,
            ),
            _Command(
                pattern=rf"SENSOR (\d+)((?: [TH](?:MIN|MAX|DELTA)?={NUMBER_REGEX})*)",
                usage=(
                    "SENSOR <id> [T=<value>] [TMIN=<value>] [TMAX=<value>] [TDELTA=<value>]"
                    " [H=<value>] [HMIN=<value>] [HMAX=<value>] [HDELTA=<value>]"
                ),
                method=self._set_sensor,
            ),
            _Command(
                pattern=r"SENSOR (\d+) FAIL",
                usage="SENSOR <id> FAIL",
                method=self._fail_sensor,
            ),
            _Command(
                pattern=r"EVENT (\w+)",
                usage="EVENT <OctoPrint event name>",
                method=self._event,
            ),
        )

    def handle(self, command: str, parameters: str) -> None:
        """Run an @ENCDEV command.

        Args:
            command (str): The name of the @ command, without the @.
            parameters (str): The parameters of the @ command.

        """
        if command.upper() != "ENCDEV":
            return

        if not self._development_mode:
            self._printer.log_lines("@ENCDEV commands are available only in development mode")
            return

        line = " ".join(parameters.upper().split())
        for encdev_command in self._commands:
            match = re.fullmatch(encdev_command.pattern, line)
            if match:
                action = functools.partial(encdev_command.method, *match.groups())

                # Run outside the printer communication thread
                threading.Thread(target=self._run, args=(action, line), name="EncDev", daemon=True).start()

                return

        self._send_usage_reply()

    def _run(self, action: Callable[[], None], line: str) -> None:
        try:
            action()
        except _CommandError as error:
            self._printer.log_lines(str(error))
        except Exception:
            self._logger.exception("Error running @ENCDEV %s", line)
            self._printer.log_lines("@ENCDEV failed, see plugin logs")

    ##########
    ### Status command
    ##########

    def _status(self) -> None:
        # Pins
        pin_labels = self._get_pin_labels()
        edges = {dummy_gpio.RISING: "rising", dummy_gpio.FALLING: "falling", dummy_gpio.BOTH: "both"}
        for pin, status in sorted(dummy_gpio.get_pins().items()):
            line = f"GPIO {pin} - {pin_labels[pin]}" if pin in pin_labels else f"GPIO {pin}"
            line += f": {'HIGH' if status.level else 'LOW'}"
            if status.edge is not None:
                line += f", detecting {edges.get(status.edge, status.edge)} edges"
            if status.pwm is not None:
                pwm_state = "running" if status.pwm.running else "stopped"
                line += f", PWM {pwm_state} at {status.pwm.duty_cycle}% and {status.pwm.frequency} Hz"
            self._printer.log_lines(line)

        # I2C registers
        for (bus, address, register), value in sorted(dummy_i2c.get_registers().items()):
            self._printer.log_lines(f"I2C bus {bus}, address {address:#04x}, register {register}: {value}")

        # Sensors
        for sensor in self._sensors.get_all().values():
            self._printer.log_lines(self._describe_sensor(sensor.config))

    ##########
    ### Input command
    ##########

    def _input(self, index_id: str, state: str) -> None:
        try:
            config = self._gpio_inputs.get(int(index_id)).config
        except GpioInputError as error:
            msg = f"Can't use GPIO input {index_id}: {error}"
            raise _CommandError(msg) from error

        pin = config.gpio_pin
        active_level = dummy_gpio.LOW if config.input_pull_resistor is PullResistor.UP else dummy_gpio.HIGH
        inactive_level = dummy_gpio.LOW if active_level == dummy_gpio.HIGH else dummy_gpio.HIGH

        if state == "PRESS":
            dummy_gpio.set_input_level(pin, active_level)
            dummy_gpio.set_input_level(pin, inactive_level)
        elif state == "ACTIVE":
            dummy_gpio.set_input_level(pin, active_level)
        elif state == "INACTIVE":
            dummy_gpio.set_input_level(pin, inactive_level)

        self._printer.log_lines(f"Input {config.index_id} ({config.label}): {state.lower()}")

    ##########
    ### Sensor command
    ##########

    def _set_sensor(self, index_id: str, values: str) -> None:
        sensor = self._get_dummy_sensor(int(index_id))
        new_values = {}
        for item in values.split():
            key, _, value = item.partition("=")
            new_values[key] = float(value)

        simulated_values = (("T", sensor.temperature), ("H", sensor.humidity))
        for prefix, simulated in simulated_values:
            minimum = new_values.get(f"{prefix}MIN", simulated.minimum)
            maximum = new_values.get(f"{prefix}MAX", simulated.maximum)
            if minimum >= maximum:
                msg = f"{prefix}MIN={minimum} must be lower than {prefix}MAX={maximum}"
                raise _CommandError(msg)

        for prefix, simulated in simulated_values:
            simulated.value = new_values.get(prefix, simulated.value)
            simulated.minimum = new_values.get(f"{prefix}MIN", simulated.minimum)
            simulated.maximum = new_values.get(f"{prefix}MAX", simulated.maximum)
            simulated.delta = new_values.get(f"{prefix}DELTA", simulated.delta)
        sensor.failing = False

        self._printer.log_lines(self._describe_sensor(sensor.config))

        self._sensor_poller.read_all()

    def _fail_sensor(self, index_id: str) -> None:
        sensor = self._get_dummy_sensor(int(index_id))
        sensor.failing = True

        self._printer.log_lines(self._describe_sensor(sensor.config))

        self._sensor_poller.read_all()

    ##########
    ### Event command
    ##########

    def _event(self, name: str) -> None:
        event = getattr(Events, name, None)
        if name.startswith("_") or not isinstance(event, str):
            msg = f"No OctoPrint event named {name}"
            raise _CommandError(msg)

        self._control_loop.evaluate_octoprint_event(event, dict(EVENT_PAYLOAD))
        self._printer.log_lines(f"Event {event} handled")

    ##########
    ### Helpers
    ##########

    def _send_usage_reply(self) -> None:
        self._printer.log_lines("Usage:")
        for encdev_command in self._commands:
            self._printer.log_lines(f"  @ENCDEV {encdev_command.usage}")

    def _describe_sensor(self, config: InputConfig) -> str:
        description = f"Sensor {config.index_id} ({config.label})"

        try:
            sensor = self._sensors.get_dummy(config.index_id)
        except LookupError:
            return f"{description}: not set up"

        state = " ".join(
            f"{prefix}={simulated.value} {prefix}MIN={simulated.minimum} {prefix}MAX={simulated.maximum}"
            f" {prefix}DELTA={simulated.delta}"
            for prefix, simulated in (("T", sensor.temperature), ("H", sensor.humidity))
        )
        if sensor.failing:
            state += ", failing"

        return f"{description}: {state}"

    def _get_dummy_sensor(self, index_id: int) -> DummySensor:
        try:
            return self._sensors.get_dummy(index_id)
        except LookupError as error:
            raise _CommandError(str(error)) from error

    def _get_pin_labels(self) -> dict[int, str]:
        labels: dict[int, list[str]] = {}

        for gpio_input in self._gpio_inputs.get_all():
            config = gpio_input.config
            labels.setdefault(config.gpio_pin, []).append(f"Input {config.index_id} ({config.label})")
        for sensor in self._sensors.get_all().values():
            for pin in sensor.gpio_pins:
                labels.setdefault(pin, []).append(f"Sensor {sensor.config.index_id} ({sensor.config.label})")
        for output in self._outputs.get_all(Output):
            for pin in output.gpio_pins:
                labels.setdefault(pin, []).append(f"Output {output.config.index_id} ({output.config.label})")

        return {pin: ", ".join(pin_labels) for pin, pin_labels in labels.items()}
