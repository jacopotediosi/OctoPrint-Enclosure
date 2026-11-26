from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue

if TYPE_CHECKING:
    import logging

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.frontend import Frontend


class ActionError(Exception):
    """Raised when an action can't be used, with the reason as message."""


class ActionType(LabeledEnum):
    """The type of an action."""

    GCODE = LabeledValue(value="gcode_output", label=N_("Gcode"))
    SHELL = LabeledValue(value="shell_output", label=N_("Shell Script"))
    PRINTER = LabeledValue(value="printer", label=N_("Printer"))


@dataclass(frozen=True)
class ActionConfig(BaseConfig):
    """The configuration shared by all the actions."""

    type_field_name = "action_type"

    index_id: int = config_field(label=N_("Id"), widget="id")
    """The id of the action."""

    label: str = config_field(optional=True, label=N_("Label"), compare=False)
    """The label of the action."""

    action_type: ActionType = config_field(label=N_("Action Type"))
    """The type of the action."""

    hide_btn_ui: bool = config_field(default=False, label=N_("Hide in tab"), compare=False)
    """Whether the button of the action is hidden in the Enclosure tab."""

    show_on_navbar: bool = config_field(default=False, label=N_("Show in navbar"), compare=False)
    """Whether the action has a button in the navbar."""


_ConfigT = TypeVar("_ConfigT", bound=ActionConfig)


class Action(ABC, Generic[_ConfigT]):
    """An action, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the action."""

    config: _ConfigT
    """The configuration of the action."""

    _printer: PrinterInterface
    """The OctoPrint printer interface."""

    _frontend: Frontend
    """The frontend handler."""

    _logger: logging.Logger

    def __init__(
        self,
        config: _ConfigT,
        printer: PrinterInterface,
        frontend: Frontend,
        logger: logging.Logger,
    ) -> None:
        """Set up the action.

        Args:
            config (_ConfigT): The configuration of the action.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._printer = printer
        self._frontend = frontend
        self._logger = logger

    @abstractmethod
    def run(self) -> None:
        """Run the action.

        Raises:
            Exception: If the action can't be run.

        """
