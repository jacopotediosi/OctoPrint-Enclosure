from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, TypeVar

from .outputs import (
    ColorOutput,
    Output,
    OutputError,
    PwmOutput,
    RegularOutput,
    RegularSetState,
    ThermostatOutput,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable
    from typing import Any

    from typing_extensions import Protocol

    from .outputs import Outputs

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)

if TYPE_CHECKING:

    class _Command(Protocol[_T_co]):
        """A function running a command on the OutputExecutor thread."""

        @property
        def __name__(self) -> str: ...

        def __call__(self) -> _T_co: ...


COMMAND_TIMEOUT_SECONDS = 5
"""The maximum seconds a caller waits for the outcome of a command."""

SHUTDOWN_TIMEOUT_SECONDS = 15
"""The maximum seconds to wait during the shutdown."""


class _Shutdown:
    """The OutputExecutor shuts down."""


class OutputExecutor:
    """Executes the commands to the outputs, on a thread of its own.

    This is the only place that commands the outputs: from anywhere else they are only read. Every command runs on
    this one thread, one at a time and in the order it was asked, so two commands never write the output
    together.
    """

    _outputs: Outputs
    _logger: logging.Logger

    _update_ui_outputs: Callable[[], object]
    """The function pushing the state of the outputs to the UI."""

    _update_ui_outputs_already_requested: bool
    """Whether an outputs UI update has already been requested."""

    _shutting_down: bool
    """Whether the executor is shutting down, and discards every command."""

    _queue: queue.Queue[tuple[Future[Any], _Command[Any]] | _Shutdown]
    """The commands to run, in order, each with the future of its outcome."""

    _lock: threading.Lock
    """Held by every put in the queue."""

    _thread: threading.Thread

    def __init__(
        self,
        outputs: Outputs,
        logger: logging.Logger,
        *,
        update_ui_outputs: Callable[[], object],
    ) -> None:
        """Set up the executor and start executing.

        Args:
            outputs (Outputs): The outputs.
            logger (logging.Logger): The logger to write to.
            update_ui_outputs (Callable[[], object]): The function pushing the state of the outputs to the UI.

        """
        self._outputs = outputs
        self._logger = logger.getChild("OutputExecutor")
        self._update_ui_outputs = update_ui_outputs
        self._update_ui_outputs_already_requested = False
        self._shutting_down = False
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="EnclosureOutputExecutor", daemon=True)
        self._thread.start()

    def load_outputs(self, outputs_settings: Iterable[dict], *, wait: bool = False) -> None:
        """Load the outputs from their settings.

        Args:
            outputs_settings (Iterable[dict]): The settings of the outputs.
            wait (bool): Whether to wait for the load, up to the command timeout.

        """

        def load_outputs() -> None:
            try:
                self._outputs.load(outputs_settings)
            except Exception:
                self._logger.exception("Error loading the outputs")

        self._submit(load_outputs, wait=wait)

    def switch_output(self, index_id: int, state: RegularSetState, *, wait: bool = False) -> bool | None:
        """Switch a regular output.

        Args:
            index_id (int): The id of the output.
            state (RegularSetState): The state to set.
            wait (bool): Whether to wait for the switch.

        Returns:
            bool | None: Whether the output is on after the switch, or None without waiting, on a timeout or if it
                couldn't be switched.

        """

        def switch_output() -> bool | None:
            try:
                regular_output = self._outputs.get(index_id, RegularOutput)

                if state is RegularSetState.TOGGLE:
                    on = regular_output.toggle()
                elif state is RegularSetState.ON:
                    regular_output.turn_on()
                    on = True
                else:
                    regular_output.turn_off()
                    on = False
            except OutputError as error:
                self._logger.debug("Can't write on output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error writing on output %s", index_id)
                return None
            else:
                self._queue_update_ui_outputs()
                return on

        return self._submit(switch_output, wait=wait)

    def write_pwm(self, index_id: int, duty_cycle: float, *, wait: bool = False) -> None:
        """Set the duty cycle of a PWM output.

        Args:
            index_id (int): The id of the output.
            duty_cycle (float): The duty cycle, from 0 to 100.
            wait (bool): Whether to wait for the write, up to the command timeout.

        """

        def write_pwm() -> None:
            try:
                self._outputs.get(index_id, PwmOutput).set_duty_cycle(duty_cycle)
            except OutputError as error:
                self._logger.debug("Can't write PWM on output %s: %s", index_id, error)
            except Exception:
                self._logger.exception("Error writing PWM on output %s", index_id)
            else:
                self._queue_update_ui_outputs()

        self._submit(write_pwm, wait=wait)

    def set_color(self, index_id: int, red: int, green: int, blue: int, *, wait: bool = False) -> None:
        """Set the color of a ColorOutput.

        Args:
            index_id (int): The id of the output.
            red (int): The red component, from 0 to 255.
            green (int): The green component, from 0 to 255.
            blue (int): The blue component, from 0 to 255.
            wait (bool): Whether to wait for the write, up to the command timeout.

        """

        def set_color() -> None:
            try:
                self._outputs.get(index_id, ColorOutput).set_color(red, green, blue)
            except OutputError as error:
                self._logger.debug("Can't set the color of output %s: %s", index_id, error)
            except Exception:
                self._logger.exception("Error setting the color of output %s", index_id)
            else:
                self._queue_update_ui_outputs()

        self._submit(set_color, wait=wait)

    def switch_thermostat(self, index_id: int, *, on: bool, wait: bool = False) -> None:
        """Turn the device of a thermostat on or off.

        Args:
            index_id (int): The id of the thermostat.
            on (bool): Whether to turn the device on or off.
            wait (bool): Whether to wait for the switch, up to the command timeout.

        """

        def switch_thermostat() -> None:
            try:
                output = self._outputs.get(index_id, ThermostatOutput)
                if on:
                    output.turn_on()
                else:
                    output.turn_off()
            except OutputError as error:
                self._logger.debug("Can't write on output %s: %s", index_id, error)
            except Exception:
                self._logger.exception("Error writing on output %s", index_id)
            else:
                self._queue_update_ui_outputs()

        self._submit(switch_thermostat, wait=wait)

    def run_enc_command(self, index_id: int, gcode: str, *, wait: bool = False) -> str | None:
        """Apply an ENC command to an output.

        Args:
            index_id (int): The id of the output.
            gcode (str): The G-code line of the ENC command.
            wait (bool): Whether to wait for the reply, up to the command timeout.

        Returns:
            str | None: The reply to write in the terminal, or None without waiting, on a timeout, if the command
                couldn't be applied or if no output with that id supports an ENC command.

        """

        def run_enc_command() -> str | None:
            try:
                reply = self._outputs.run_enc_command(index_id, gcode)
            except OutputError as error:
                self._logger.debug("Can't run ENC command %s: %s", gcode, error)
                return None
            except Exception:
                self._logger.exception("Error running ENC command: %s", gcode)
                return None

            if reply is not None:
                self._queue_update_ui_outputs()

            return reply

        return self._submit(run_enc_command, wait=wait)

    def shutdown(self) -> None:
        """Turn every output off and stop executing.

        The commands still queued are discarded, and so is every command asked from now on.
        """
        with self._lock:
            self._shutting_down = True
            self._queue.put(_Shutdown())
        self._thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            self._logger.warning("The outputs are not all off after %s s", SHUTDOWN_TIMEOUT_SECONDS)

    def update_ui_outputs(self) -> None:
        """Update the outputs in the UI once the commands queued so far are executed."""
        self._submit(self._queue_update_ui_outputs, wait=False)

    def _queue_update_ui_outputs(self) -> None:
        def update_ui_outputs() -> None:
            self._update_ui_outputs_already_requested = False
            try:
                self._update_ui_outputs()
            except Exception:
                self._logger.exception("Error updating the outputs in the UI")

        if self._update_ui_outputs_already_requested:
            return

        self._submit(update_ui_outputs, wait=False)
        self._update_ui_outputs_already_requested = True

    def _submit(self, command: _Command[_T], *, wait: bool) -> _T | None:
        with self._lock:
            if self._shutting_down:
                return None

            future: Future[_T | None] = Future()
            self._queue.put((future, command))

        if not wait:
            return None

        try:
            outcome = future.result(timeout=COMMAND_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            self._logger.warning("Command %s not done after %s s", command.__name__, COMMAND_TIMEOUT_SECONDS)
            return None
        return outcome

    def _run(self) -> None:
        while True:
            item = self._queue.get()

            # Turn every output off and end the thread when the executor is shut down
            if isinstance(item, _Shutdown):
                for output in self._outputs.get_all(Output):
                    try:
                        output.turn_off()
                    except OutputError as error:
                        self._logger.debug("Can't turn off an output: %s", error)
                    except Exception:
                        self._logger.exception("Error turning off an output")
                return

            # Discard the command if the executor is shutting down
            future, command = item
            if self._shutting_down:
                future.set_result(None)
                continue

            # Run the command
            try:
                outcome = command()
            except Exception:
                self._logger.exception("Error running command %s", command.__name__)
                outcome = None
            future.set_result(outcome)
