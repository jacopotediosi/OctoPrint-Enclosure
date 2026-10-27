from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, TypeVar

from .actions import Action, ActionError
from .outputs import (
    ColorOutput,
    Output,
    OutputError,
    PwmOutput,
    RegularOutput,
    RegularSetState,
    TempHumControlOutput,
    TempHumControlStatus,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from typing_extensions import Protocol

    from .actions import Actions
    from .outputs import Outputs

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)

if TYPE_CHECKING:

    class _Command(Protocol[_T_co]):
        """A function running a command on the Executor thread."""

        __name__: str

        def __call__(self) -> _T_co: ...


COMMAND_TIMEOUT_SECONDS = 5
"""The seconds a caller waits for the outcome of a command."""


class Executor:
    """Executes the commands to the outputs and the actions, on a thread of its own.

    This is the only place that commands the outputs: from anywhere else they are only read. Every command runs on
    this one thread, one at a time and in the order it was asked, so two commands never write the output
    together.
    """

    _outputs: Outputs
    _actions: Actions
    _logger: logging.Logger

    _update_ui: Callable[[], object]
    """The function refreshing the UI."""

    _thread: ThreadPoolExecutor
    """Runs the commands on the Executor thread."""

    def __init__(
        self,
        outputs: Outputs,
        actions: Actions,
        logger: logging.Logger,
        *,
        update_ui: Callable[[], object],
    ) -> None:
        """Set up the executor and start executing.

        Args:
            outputs (Outputs): The outputs.
            actions (Actions): The actions.
            logger (logging.Logger): The logger to write to.
            update_ui (Callable[[], object]): The function refreshing the UI.

        """
        self._outputs = outputs
        self._actions = actions
        self._logger = logger.getChild("Executor")
        self._update_ui = update_ui
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="EnclosureExecutor")

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

                self._update_ui()
            except OutputError as error:
                self._logger.debug("Can't write on output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error writing on output %s", index_id)
                return None
            else:
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

                self._update_ui()
            except OutputError as error:
                self._logger.debug("Can't write PWM on output %s: %s", index_id, error)
            except Exception:
                self._logger.exception("Error writing PWM on output %s", index_id)

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

        self._submit(set_color, wait=wait)

    def set_target(self, index_id: int, target: float, *, wait: bool = False) -> None:
        """Set the target of a temperature/humidity control, applied at its next regulation.

        Args:
            index_id (int): The id of the control.
            target (float): The target temperature or humidity, or 0 to turn the control off.
            wait (bool): Whether to wait for the target to be set, up to the command timeout.

        """

        def set_target() -> None:
            try:
                self._outputs.get(index_id, TempHumControlOutput).set_target(target)
            except OutputError as error:
                self._logger.debug("Can't set the target of output %s: %s", index_id, error)

        self._submit(set_target, wait=wait)

    def regulate(
        self,
        index_id: int,
        temperature: float | None,
        humidity: float | None,
        *,
        wait: bool = False,
    ) -> TempHumControlStatus | None:
        """Turn the device of a temperature/humidity control on or off, to keep its target.

        Args:
            index_id (int): The id of the control.
            temperature (float | None): The temperature read by its sensor, or None if it has none.
            humidity (float | None): The humidity read by its sensor, or None if it has none.
            wait (bool): Whether to wait for the regulation, up to the command timeout.

        Returns:
            TempHumControlStatus | None: What the control is doing after the regulation, or None without waiting, on
                a timeout or if it couldn't be regulated.

        """

        def regulate() -> TempHumControlStatus | None:
            try:
                status = self._outputs.get(index_id, TempHumControlOutput).regulate(temperature, humidity)
            except OutputError as error:
                self._logger.debug("Can't regulate output %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error reading or writing output %s", index_id)
                return None
            return status

        return self._submit(regulate, wait=wait)

    def run_action(
        self,
        index_id: int,
        action_class: type[Action] = Action,
        *,
        wait: bool = False,
    ) -> Action | None:
        """Run an action.

        Args:
            index_id (int): The id of the action.
            action_class (type[Action]): The class the action must be an instance of; any action by default.
            wait (bool): Whether to wait for the action, up to the command timeout.

        Returns:
            Action | None: The action run, or None without waiting, on a timeout or if it couldn't be run.

        """

        def run_action() -> Action | None:
            try:
                action = self._actions.get(index_id, action_class)
                action.run()
            except ActionError as error:
                self._logger.debug("Can't run action %s: %s", index_id, error)
                return None
            except Exception:
                self._logger.exception("Error running action %s", index_id)
                return None
            return action

        return self._submit(run_action, wait=wait)

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
            return reply

        return self._submit(run_enc_command, wait=wait)

    def turn_off_all_outputs(self, *, wait: bool = False) -> None:
        """Turn every output off.

        Args:
            wait (bool): Whether to wait for every output to be off, up to the command timeout.

        """

        def turn_off_all_outputs() -> None:
            for output in self._outputs.get_all(Output):
                try:
                    output.turn_off()
                except OutputError as error:
                    self._logger.debug("Can't turn off an output: %s", error)
                except Exception:
                    self._logger.exception("Error turning off an output")

        self._submit(turn_off_all_outputs, wait=wait)

    def _submit(self, command: _Command[_T], *, wait: bool) -> _T | None:
        future = self._thread.submit(command)

        if not wait:
            return None

        try:
            outcome = future.result(timeout=COMMAND_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            self._logger.warning("Command %s not done after %s s", command.__name__, COMMAND_TIMEOUT_SECONDS)
            return None
        return outcome
