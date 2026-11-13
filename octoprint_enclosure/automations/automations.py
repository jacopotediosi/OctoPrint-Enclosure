from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any, TypeVar

from octoprint_enclosure.outputs import Output, OutputError
from octoprint_enclosure.settings import ActionId, GpioInputId, OutputId, SensorInputId

from .base import Automation, AutomationConfig, AutomationError
from .registry import AUTOMATIONS
from .triggers import GpioInputTrigger

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.inputs import Edge, GpioInputs, Sensors
    from octoprint_enclosure.outputs import Outputs

    from .events import AutomationEvent

_AutomationT = TypeVar("_AutomationT", bound=Automation)


class _InvalidAutomation(Automation[AutomationConfig]):
    """An automation that can't be set up."""

    config_class = AutomationConfig

    reason: str
    """Why the automation can't be set up."""

    def __init__(self, config: AutomationConfig, reason: str, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self.reason = reason


class Automations:
    """The automations."""

    _logger: logging.Logger

    _automations: dict[int, Automation]
    """The automation with each id."""

    def __init__(self, logger: logging.Logger) -> None:
        """Set up the automations, with none until some settings are loaded.

        Args:
            logger (logging.Logger): The logger to write to.

        """
        self._logger = logger.getChild("Automations")
        self._automations = {}

    def load(self, automations_settings: Iterable[dict]) -> None:
        """Load some automations from their settings.

        An automation whose settings didn't change is kept as it is, with its state.

        Args:
            automations_settings (Iterable[dict]): The settings of the automations.

        """
        automations: dict[int, Automation] = {}

        for automation_settings in automations_settings:
            try:
                automation_config = AutomationConfig.from_settings(automation_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an automation: %s", error)
                continue

            automation_class = AUTOMATIONS.get(automation_config.automation_type)
            if automation_class is None:
                automation: Automation = self._create_invalid_automation(
                    automation_config,
                    f"Unsupported automation type: {automation_config.automation_type!r}",
                )
            else:
                automation = self._create_automation(automation_class, automation_config, automation_settings)

            automations[automation_config.index_id] = automation

        self._automations = automations

    def check_links(self, sensors: Sensors, gpio_inputs: GpioInputs, outputs: Outputs, actions: Actions) -> None:
        """Check the links of the automations to the other entries, and log a warning for each problem.

        E.g., a problem is a link to an entry that doesn't exist, or an output turned on without a value its setpoint
        needs.

        Args:
            sensors (Sensors): The sensors inputs.
            gpio_inputs (GpioInputs): The GPIO inputs.
            outputs (Outputs): The outputs.
            actions (Actions): The actions.

        """
        # The name and the known ids of the entries of each type an automation can be linked to
        known_ids: dict[Any, tuple[str, set[int]]] = {
            SensorInputId: ("sensor input", sensors.get_ids()),
            GpioInputId: ("GPIO input", gpio_inputs.get_ids()),
            OutputId: ("output", outputs.get_ids()),
            ActionId: ("action", actions.get_ids()),
        }

        for index_id, automation in self._automations.items():
            # A link to an entry that doesn't exist
            for id_type, (name, ids) in known_ids.items():
                linked_ids = {
                    linked_id for config in automation.configs for linked_id in config.get_linked_ids(id_type)
                }
                for linked_id in sorted(linked_ids - ids):
                    self._logger.warning(
                        "Automation %s is linked to %s %s, which doesn't exist",
                        index_id,
                        name,
                        linked_id,
                    )

            # An output turned on without a value its setpoint needs
            for output_id, setpoint_config in automation.get_output_setpoints():
                try:
                    output = outputs.get(output_id, Output)
                except OutputError:
                    continue

                for field in fields(output.setpoint_class):
                    if getattr(setpoint_config, field.name) is None:
                        self._logger.warning(
                            "Automation %s turns on output %s without a %s",
                            index_id,
                            output_id,
                            field.name,
                        )

    def get(self, index_id: int, automation_class: type[_AutomationT]) -> _AutomationT:
        """Get an automation.

        Args:
            index_id (int): The id of the automation.
            automation_class (type[_AutomationT]): The class the automation must be an instance of.

        Returns:
            _AutomationT: The automation.

        Raises:
            AutomationError: If no automation of that class is set up with that id.

        """
        automation = self._automations.get(index_id)

        if isinstance(automation, automation_class):
            return automation

        reason = automation.reason if isinstance(automation, _InvalidAutomation) else "The automation is not set up"
        raise AutomationError(reason)

    def get_all(self, automation_class: type[_AutomationT], *, include_disabled: bool = False) -> list[_AutomationT]:
        """Get all the automations having a certain class.

        Args:
            automation_class (type[_AutomationT]): The class the automations must be an instance of.
            include_disabled (bool): Whether to include the disabled automations too, which do nothing.

        Returns:
            list[_AutomationT]: The automations.

        """
        return [
            automation
            for automation in self._automations.values()
            if isinstance(automation, automation_class) and (include_disabled or automation.enabled)
        ]

    def get_triggered(self, event: AutomationEvent) -> list[Automation]:
        """Get the automations that an event starts.

        Args:
            event (AutomationEvent): What happened.

        Returns:
            list[Automation]: The automations.

        """
        return [
            automation
            for automation in self._automations.values()
            if automation.enabled and automation.trigger is not None and automation.trigger.matches(event)
        ]

    def get_gpio_input_edges(self) -> dict[int, set[Edge]]:
        """Get the edges of the GPIO inputs that start the automations.

        Returns:
            dict[int, set[Edge]]: The edges of each input, by the id of the input.

        """
        input_edges: dict[int, set[Edge]] = {}
        for automation in self._automations.values():
            trigger = automation.trigger
            if isinstance(trigger, GpioInputTrigger):
                input_edges.setdefault(trigger.config.input, set()).add(trigger.config.edge)
        return input_edges

    def _create_automation(
        self,
        automation_class: type[_AutomationT],
        automation_config: AutomationConfig,
        automation_settings: dict,
    ) -> _AutomationT | _InvalidAutomation:
        index_id = automation_config.index_id
        try:
            automation = automation_class.from_settings(
                automation_settings,
                self._get_automation_logger(automation_class, index_id),
            )
        except ValueError as error:
            return self._create_invalid_automation(automation_config, f"Invalid settings: {error}")

        # An automation whose settings didn't change is kept, with its state
        old_automation = self._automations.get(index_id)
        if isinstance(old_automation, automation_class) and old_automation.has_same_config(automation):
            old_automation.config = automation.config
            old_automation.enabled = automation.enabled
            return old_automation

        return automation

    def _create_invalid_automation(self, automation_config: AutomationConfig, reason: str) -> _InvalidAutomation:
        logger = self._get_automation_logger(_InvalidAutomation, automation_config.index_id)
        logger.warning("%s", reason)
        return _InvalidAutomation(automation_config, reason, logger)

    def _get_automation_logger(self, automation_class: type[Automation], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{automation_class.__name__}.{index_id}")
