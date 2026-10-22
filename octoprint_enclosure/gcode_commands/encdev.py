from __future__ import annotations

import functools
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint.events import Events

from octoprint_enclosure.hardware import dummy_gpio
from octoprint_enclosure.inputs import PullResistor
from octoprint_enclosure.utils import to_int

if TYPE_CHECKING:
    from collections.abc import Callable

    from octoprint.util.comm import MachineCom

    from octoprint_enclosure.inputs.sensors.dummy import DummySensor
    from octoprint_enclosure.plugin import EnclosurePlugin

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

    _plugin: EnclosurePlugin
    _commands: tuple[_Command, ...]

    def __init__(self, plugin: EnclosurePlugin) -> None:
        """Set up the handler.

        Args:
            plugin (EnclosurePlugin): The plugin instance.

        """
        self._plugin = plugin

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

    def handle(self, comm_instance: MachineCom, command: str, parameters: str) -> None:
        """Run an @ENCDEV command.

        Args:
            comm_instance (MachineCom): The connection to the printer.
            command (str): The name of the @ command, without the @.
            parameters (str): The parameters of the @ command.

        """
        if command.upper() != "ENCDEV":
            return

        send_reply = comm_instance._log

        if not self._plugin.development_mode:
            send_reply("@ENCDEV commands are available only in development mode")
            return

        line = " ".join(parameters.upper().split())
        for encdev_command in self._commands:
            match = re.fullmatch(encdev_command.pattern, line)
            if match:
                action = functools.partial(encdev_command.method, send_reply, *match.groups())

                # Run outside the printer communication thread
                threading.Thread(target=self._run, args=(action, line, send_reply), name="EncDev", daemon=True).start()

                return

        self._send_usage_reply(send_reply)

    def _run(self, action: Callable[[], None], line: str, send_reply: Callable[[str], None]) -> None:
        try:
            action()
        except _CommandError as error:
            send_reply(str(error))
        except Exception:
            self._plugin._logger.exception("Error running @ENCDEV %s", line)
            send_reply("@ENCDEV failed, see plugin logs")

    ##########
    ### Status command
    ##########

    def _status(self, send_reply: Callable[[str], None]) -> None:
        # Pin numbering
        numbering = {dummy_gpio.BOARD: "BOARD", dummy_gpio.BCM: "BCM", None: "not set"}[dummy_gpio.getmode()]
        send_reply(f"Pin numbering: {numbering}")

        # Pins
        pin_labels = self._get_pin_labels()
        edges = {dummy_gpio.RISING: "rising", dummy_gpio.FALLING: "falling", dummy_gpio.BOTH: "both"}
        for pin, status in sorted(dummy_gpio.get_pins().items()):
            line = f"Pin {pin} - {pin_labels[pin]}" if pin in pin_labels else f"Pin {pin}"
            line += f": {'HIGH' if status.level else 'LOW'}"
            if status.edge is not None:
                line += f", detecting {edges.get(status.edge, status.edge)} edges"
            if status.pwm is not None:
                pwm_state = "running" if status.pwm.running else "stopped"
                line += f", PWM {pwm_state} at {status.pwm.duty_cycle}% and {status.pwm.frequency} Hz"
            send_reply(line)

        # Sensors
        for config in self._plugin.rpi_inputs:
            if config["input_type"] == "temperature_sensor":
                send_reply(self._describe_sensor(config))

    ##########
    ### Input command
    ##########

    def _input(self, send_reply: Callable[[str], None], index_id: str, state: str) -> None:
        config = self._get_input_config(index_id, "gpio")
        pin = to_int(config["gpio_pin"])
        active_level = dummy_gpio.LOW if config["input_pull_resistor"] == PullResistor.UP.value else dummy_gpio.HIGH
        inactive_level = dummy_gpio.LOW if active_level == dummy_gpio.HIGH else dummy_gpio.HIGH

        if state == "PRESS":
            dummy_gpio.set_input_level(pin, active_level)
            dummy_gpio.set_input_level(pin, inactive_level)
        elif state == "ACTIVE":
            dummy_gpio.set_input_level(pin, active_level)
        elif state == "INACTIVE":
            dummy_gpio.set_input_level(pin, inactive_level)

        send_reply(f"Input {config['index_id']} ({config['label']}): {state.lower()}")

    ##########
    ### Sensor command
    ##########

    def _set_sensor(self, send_reply: Callable[[str], None], index_id: str, values: str) -> None:
        config = self._get_input_config(index_id, "temperature_sensor")
        sensor = self._get_dummy_sensor(config)
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

        send_reply(self._describe_sensor(config))
        self._read_sensors_now()

    def _fail_sensor(self, send_reply: Callable[[str], None], index_id: str) -> None:
        config = self._get_input_config(index_id, "temperature_sensor")

        self._get_dummy_sensor(config).failing = True

        send_reply(self._describe_sensor(config))
        self._read_sensors_now()

    ##########
    ### Event command
    ##########

    def _event(self, send_reply: Callable[[str], None], name: str) -> None:
        event = getattr(Events, name, None)
        if name.startswith("_") or not isinstance(event, str):
            msg = f"No OctoPrint event named {name}"
            raise _CommandError(msg)

        self._plugin.on_event(event, dict(EVENT_PAYLOAD))
        send_reply(f"Event {event} handled")

    ##########
    ### Helpers
    ##########

    def _send_usage_reply(self, send_reply: Callable[[str], None]) -> None:
        send_reply("Usage:")
        for encdev_command in self._commands:
            send_reply(f"  @ENCDEV {encdev_command.usage}")

    def _read_sensors_now(self) -> None:
        self._plugin.check_enclosure_temp()

    def _describe_sensor(self, config: dict) -> str:
        description = f"Sensor {config['index_id']} ({config['label']}) on pin {to_int(config['gpio_pin'])}"

        try:
            sensor = self._get_dummy_sensor(config)
        except _CommandError:
            return f"{description}: not set up"

        state = " ".join(
            f"{prefix}={simulated.value} {prefix}MIN={simulated.minimum} {prefix}MAX={simulated.maximum}"
            f" {prefix}DELTA={simulated.delta}"
            for prefix, simulated in (("T", sensor.temperature), ("H", sensor.humidity))
        )
        if sensor.failing:
            state += ", failing"

        return f"{description}: {state}"

    def _get_dummy_sensor(self, config: dict) -> DummySensor:
        try:
            return self._plugin._sensors.get_dummy(config["index_id"])
        except LookupError as error:
            raise _CommandError(str(error)) from error

    def _get_pin_labels(self) -> dict[int, str]:
        labels: dict[int, list[str]] = {}

        def add(pin: object, label: str) -> None:
            if pin != "":
                labels.setdefault(to_int(pin), []).append(label)

        for config in self._plugin.rpi_outputs:
            output_type = config["output_type"]
            label = f"Output {config['index_id']} ({config['label']})"
            if output_type == "pwm" or (
                output_type in ("regular", "temp_hum_control") and not config["gpio_i2c_enabled"]
            ):
                add(config["gpio_pin"], label)
            elif output_type == "ledstrip":
                add(config["ledstrip_gpio_clk"], f"{label} CLK")
                add(config["ledstrip_gpio_dat"], f"{label} DAT")
        for config in self._plugin.rpi_inputs:
            if config["input_type"] == "gpio":
                add(config["gpio_pin"], f"Input {config['index_id']} ({config['label']})")
            elif config["input_type"] == "temperature_sensor":
                add(config["gpio_pin"], f"Sensor {config['index_id']} ({config['label']})")

        return {pin: ", ".join(pin_labels) for pin, pin_labels in labels.items()}

    def _get_input_config(self, index_id: str, input_type: str) -> dict:
        config = next(
            (
                config
                for config in self._plugin.rpi_inputs
                if config["index_id"] == to_int(index_id) and config["input_type"] == input_type
            ),
            None,
        )
        if config is None:
            kind = {"gpio": "GPIO input", "temperature_sensor": "temperature sensor"}[input_type]
            msg = f"No {kind} with id {index_id}"
            raise _CommandError(msg)

        return config
