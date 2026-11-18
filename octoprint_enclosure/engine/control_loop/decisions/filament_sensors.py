from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint.events import Events
from typing_extensions import override

from octoprint_enclosure.actions import ActionError
from octoprint_enclosure.automations import FilamentAutomation, GpioEdgeEvent, OctoprintEvent
from octoprint_enclosure.inputs import GpioInputError
from octoprint_enclosure.notifications import NotificationType

from .base import Decision

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterator, Mapping

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.automations import AutomationEvent, Automations, ConditionsState
    from octoprint_enclosure.inputs import GpioInputs, Reading
    from octoprint_enclosure.notifications import Notifications


class FilamentSensorDecision(Decision):
    """The decision regarding the filament sensors.

    Each sensor runs an action when the filament ends during a print.
    """

    _gpio_inputs: GpioInputs
    _actions: Actions
    _automations: Automations
    _notifications: Notifications
    _printer: PrinterInterface
    _logger: logging.Logger

    def __init__(
        self,
        gpio_inputs: GpioInputs,
        actions: Actions,
        automations: Automations,
        notifications: Notifications,
        printer: PrinterInterface,
        logger: logging.Logger,
    ) -> None:
        """Set up the decision regarding the filament sensors automations.

        Args:
            gpio_inputs (GpioInputs): The GPIO inputs.
            actions (Actions): The actions.
            automations (Automations): The automations.
            notifications (Notifications): The notifications.
            printer (PrinterInterface): The OctoPrint printer interface.
            logger (logging.Logger): The logger to write to.

        """
        self._gpio_inputs = gpio_inputs
        self._actions = actions
        self._automations = automations
        self._notifications = notifications
        self._printer = printer
        self._logger = logger

    @override
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        """Update since when the filament is present, from the input of each filament sensor."""
        for automation, level in self._read_levels():
            automation.update_filament_presence(level)

    @override
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        """React to an automation event, e.g. run the action of a filament sensor when the filament ends."""
        if isinstance(event, OctoprintEvent) and event.name in (Events.PRINT_STARTED, Events.PRINT_RESUMED):
            # Pause a print that starts or resumes with no filament
            for automation, level in self._read_levels():
                automation.update_filament_presence(level)
                if automation.enabled and automation.is_filament_missing(level):
                    self._printer.pause_print()
                    self._logger.info(
                        "Paused the print: filament sensor automation %s finds no filament",
                        automation.config.index_id,
                    )
        elif isinstance(event, GpioEdgeEvent):
            # Run the action of the filament sensors whose filament ended
            for automation in self._automations.get_triggered(event, FilamentAutomation):
                try:
                    printing = bool(self._printer.is_printing() and not self._printer.is_paused())
                    if not automation.detect_filament_end(printing=printing):
                        continue

                    try:
                        self._actions.run(automation.config.action)
                    except ActionError as error:
                        self._logger.warning(
                            "Automation %s can't run action %s: %s",
                            automation.config.index_id,
                            automation.config.action,
                            error,
                        )
                        continue

                    try:
                        input_label = self._gpio_inputs.get(event.input_id).config.label
                    except GpioInputError:
                        input_label = ""

                    self._notifications.send(
                        NotificationType.FILAMENT_CHANGE,
                        f"Filament change action caused by sensor: {input_label}",
                    )
                except Exception:
                    self._logger.exception("Error handling filament detection of input %s", event.input_id)

    def _read_levels(self) -> Iterator[tuple[FilamentAutomation, int]]:
        for automation in self._automations.get_all(FilamentAutomation, include_disabled=True):
            input_id = automation.trigger.config.input

            try:
                level = self._gpio_inputs.get(input_id).read_pin_level()
            except GpioInputError as error:
                self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                continue

            if level is not None:
                yield automation, level
