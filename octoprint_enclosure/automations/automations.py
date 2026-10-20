from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from octoprint_enclosure.core import BaseConfig

from .base import Automation, AutomationError
from .registry import AUTOMATIONS
from .triggers import GpioInputTrigger

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from octoprint_enclosure.inputs import Edge

_AutomationT = TypeVar("_AutomationT", bound=Automation)


@dataclass(frozen=True)
class AutomationConfig(BaseConfig):
    """The configuration shared by all the automations."""

    index_id: int
    """The id of the automation."""

    automation_type: str = ""
    """The type of the automation."""


class _InvalidAutomation(Automation[BaseConfig]):
    """An automation that can't be set up."""

    config_class = BaseConfig

    reason: str
    """Why the automation can't be set up."""

    def __init__(self, reason: str, logger: logging.Logger) -> None:
        super().__init__(BaseConfig(), logger)
        self.reason = reason


class Automations:
    """The automations."""

    _logger: logging.Logger

    _automations: dict[int, Automation]
    """The automation with each id."""

    def __init__(self, automations_settings: Iterable[dict], logger: logging.Logger) -> None:
        """Set up some automations.

        Args:
            automations_settings (Iterable[dict]): The settings of the automations.
            logger (logging.Logger): The logger to write to.

        """
        self._logger = logger.getChild("Automations")
        self._automations = {}

        for automation_settings in automations_settings:
            try:
                automation_config = AutomationConfig.from_settings(automation_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an automation: %s", error)
                continue

            automation_class = AUTOMATIONS.get(automation_config.automation_type)
            if automation_class is None:
                automation: Automation = self._create_invalid_automation(
                    automation_config.index_id,
                    f"Unsupported automation type: {automation_config.automation_type!r}",
                )
            else:
                automation = self._create_automation(automation_class, automation_config.index_id, automation_settings)

            self._automations[automation_config.index_id] = automation

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

    def get_all(self, automation_class: type[_AutomationT]) -> list[_AutomationT]:
        """Get all the automations having a certain class.

        Args:
            automation_class (type[_AutomationT]): The class the automations must be an instance of.

        Returns:
            list[_AutomationT]: The automations.

        """
        return [automation for automation in self._automations.values() if isinstance(automation, automation_class)]

    def get_triggered_by_gpio_input(self, input_id: int, level: int) -> list[Automation]:
        """Get the automations that a GPIO input starts, when an edge is detected on its pin.

        Args:
            input_id (int): The id of the input.
            level (int): The level of the input, read after the edge, 1 if high or 0 if low.

        Returns:
            list[Automation]: The automations.

        """
        return [
            automation
            for automation, trigger in self._get_gpio_input_triggers()
            if trigger.config.input == input_id and trigger.matches_level(level)
        ]

    def get_gpio_input_edges(self) -> dict[int, set[Edge]]:
        """Get the edges of the GPIO inputs that start the automations.

        Returns:
            dict[int, set[Edge]]: The edges of each input, by the id of the input.

        """
        input_edges: dict[int, set[Edge]] = {}
        for _, trigger in self._get_gpio_input_triggers():
            input_edges.setdefault(trigger.config.input, set()).add(trigger.config.edge)
        return input_edges

    def _create_automation(
        self,
        automation_class: type[_AutomationT],
        index_id: int,
        automation_settings: dict,
    ) -> _AutomationT | _InvalidAutomation:
        try:
            automation = automation_class.from_settings(
                automation_settings,
                self._get_automation_logger(automation_class, index_id),
            )
        except ValueError as error:
            return self._create_invalid_automation(index_id, f"Invalid settings: {error}")

        return automation

    def _create_invalid_automation(self, index_id: int, reason: str) -> _InvalidAutomation:
        logger = self._get_automation_logger(_InvalidAutomation, index_id)
        logger.warning("%s", reason)
        return _InvalidAutomation(reason, logger)

    def _get_automation_logger(self, automation_class: type[Automation], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{automation_class.__name__}.{index_id}")

    def _get_gpio_input_triggers(self) -> list[tuple[Automation, GpioInputTrigger]]:
        return [
            (automation, automation.trigger)
            for automation in self._automations.values()
            if isinstance(automation.trigger, GpioInputTrigger)
        ]
