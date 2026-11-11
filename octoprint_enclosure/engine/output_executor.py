from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, TypeVar

from octoprint_enclosure.outputs import Output, OutputError, Switchable, ThermostatOutput

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable
    from typing import Any

    from typing_extensions import Protocol

    from octoprint_enclosure.frontend import Frontend
    from octoprint_enclosure.outputs import Outputs
    from octoprint_enclosure.settings import BaseConfig

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
    _frontend: Frontend
    _logger: logging.Logger

    _update_ui_outputs_already_requested: bool
    """Whether an outputs UI update has already been requested."""

    _shutting_down: bool
    """Whether the executor is shutting down, and discards every command."""

    _queue: queue.Queue[tuple[Future[Any], _Command[Any]] | _Shutdown]
    """The commands to run, in order, each with the future of its outcome."""

    _lock: threading.Lock
    """Held by every put in the queue."""

    _thread: threading.Thread

    def __init__(self, outputs: Outputs, frontend: Frontend, logger: logging.Logger) -> None:
        """Set up the executor and start executing.

        Args:
            outputs (Outputs): The outputs.
            frontend (Frontend): The frontend handler.
            logger (logging.Logger): The logger to write to.

        """
        self._outputs = outputs
        self._frontend = frontend
        self._logger = logger.getChild("OutputExecutor")
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

    def turn_on(self, index_id: int, setpoint: BaseConfig, *, wait: bool = False) -> bool | None:
        """Turn an output on.

        Args:
            index_id (int): The id of the output.
            setpoint (BaseConfig): The setpoint the output is turned on to.
            wait (bool): Whether to wait for the write, up to the command timeout.

        Returns:
            bool | None: True once the output is on, or None without waiting, on a timeout or if it couldn't be
                turned on.

        """

        def turn_on() -> bool | None:
            try:
                self._get_switchable(index_id, setpoint).turn_on(setpoint)
            except OutputError as error:
                self._logger.debug("Can't turn on output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error turning on output %s", index_id)
                return None
            else:
                self._queue_update_ui_outputs()
                return True

        return self._submit(turn_on, wait=wait)

    def turn_off(self, index_id: int, *, wait: bool = False) -> bool | None:
        """Turn an output off.

        Args:
            index_id (int): The id of the output.
            wait (bool): Whether to wait for the write, up to the command timeout.

        Returns:
            bool | None: False once the output is off, or None without waiting, on a timeout or if it couldn't be
                turned off.

        """

        def turn_off() -> bool | None:
            try:
                self._get_switchable(index_id).turn_off()
            except OutputError as error:
                self._logger.debug("Can't turn off output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error turning off output %s", index_id)
                return None
            else:
                self._queue_update_ui_outputs()
                return False

        return self._submit(turn_off, wait=wait)

    def toggle(self, index_id: int, setpoint: BaseConfig, *, wait: bool = False) -> bool | None:
        """Turn an output off if it is on, and on if it is off.

        Args:
            index_id (int): The id of the output.
            setpoint (BaseConfig): The setpoint the output is turned on to.
            wait (bool): Whether to wait for the toggle, up to the command timeout.

        Returns:
            bool | None: Whether the output is on after the toggle, or None without waiting, on a timeout or if it
                couldn't be toggled.

        """

        def toggle() -> bool | None:
            try:
                output = self._get_switchable(index_id, setpoint)
                should_be_on = not output.is_on()
                if should_be_on:
                    output.turn_on(setpoint)
                else:
                    output.turn_off()
            except OutputError as error:
                self._logger.debug("Can't toggle output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error toggling output %s", index_id)
                return None
            else:
                self._queue_update_ui_outputs()
                return should_be_on

        return self._submit(toggle, wait=wait)

    def switch_thermostat(self, index_id: int, *, on: bool, wait: bool = False) -> None:
        """Turn the device of a thermostat on or off.

        Args:
            index_id (int): The id of the thermostat.
            on (bool): Whether to turn the device on or off.
            wait (bool): Whether to wait for the switch, up to the command timeout.

        """

        def switch_thermostat() -> None:
            try:
                self._outputs.get(index_id, ThermostatOutput).switch.set(on=on)
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

    def run_after_commands(self, callback: Callable[[], object]) -> None:
        """Call a function once the commands queued so far are executed.

        Args:
            callback (Callable[[], object]): The function to call, on the thread of the executor.

        """

        def run_after_commands() -> None:
            callback()

        self._submit(run_after_commands, wait=False)

    def _get_switchable(self, index_id: int, setpoint: BaseConfig | None = None) -> Switchable:
        output = self._outputs.get(index_id, Output)
        if not isinstance(output, Switchable):
            msg = "The output is not turned on and off directly"
            raise OutputError(msg)
        if setpoint is not None and not isinstance(setpoint, output.setpoint_class):
            msg = f"The setpoint must be a {output.setpoint_class.__name__}, not a {type(setpoint).__name__}"
            raise OutputError(msg)
        return output

    def _queue_update_ui_outputs(self) -> None:
        def update_ui_outputs() -> None:
            self._update_ui_outputs_already_requested = False
            try:
                self._frontend.update_outputs()
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
