from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.core import BaseConfig

if TYPE_CHECKING:
    import logging

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.core import Frontend

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class ActionError(Exception):
    """Raised when an action can't be used, with the reason as message."""


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
