from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Action, ActionError
from .registry import ACTIONS

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.core import Frontend

_ActionT = TypeVar("_ActionT", bound=Action)


@dataclass(frozen=True)
class ActionConfig(BaseConfig):
    """The configuration shared by all the actions."""

    index_id: int
    """The id of the action."""

    action_type: str = ""
    """The type of the action."""


class _InvalidAction(Action[BaseConfig]):
    """An action that can't be set up."""

    config_class = BaseConfig

    reason: str
    """Why the action can't be set up."""

    def __init__(self, reason: str, printer: PrinterInterface, frontend: Frontend, logger: logging.Logger) -> None:
        super().__init__(BaseConfig(), printer, frontend, logger)
        self.reason = reason

    @override
    def run(self) -> None:
        raise ActionError(self.reason)


class Actions:
    """The actions."""

    _logger: logging.Logger

    _actions: dict[int, Action]
    """The action with each id."""

    def __init__(
        self,
        actions_settings: Iterable[dict],
        printer: PrinterInterface,
        frontend: Frontend,
        logger: logging.Logger,
    ) -> None:
        """Set up some actions.

        Args:
            actions_settings (Iterable[dict]): The settings of the actions.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            logger (logging.Logger): The logger to write to.

        """
        self._logger = logger.getChild("Actions")
        self._actions = {}

        for action_settings in actions_settings:
            try:
                action_config = ActionConfig.from_settings(action_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an action: %s", error)
                continue

            action_class = ACTIONS.get(action_config.action_type)
            if action_class is None:
                action: Action = _InvalidAction(
                    f"Unsupported action type: {action_config.action_type!r}",
                    printer,
                    frontend,
                    self._get_action_logger(_InvalidAction, action_config.index_id),
                )
            else:
                action = self._create_action(action_class, action_config.index_id, action_settings, printer, frontend)

            self._actions[action_config.index_id] = action

    def get(self, index_id: int, action_class: type[_ActionT]) -> _ActionT:
        """Get an action.

        Args:
            index_id (int): The id of the action.
            action_class (type[_ActionT]): The class the action must be an instance of.

        Returns:
            _ActionT: The action.

        Raises:
            ActionError: If no action of that class is set up with that id.

        """
        action = self._actions.get(index_id)

        if isinstance(action, action_class):
            return action

        reason = action.reason if isinstance(action, _InvalidAction) else "The action is not set up"
        raise ActionError(reason)

    def _create_action(
        self,
        action_class: type[_ActionT],
        index_id: int,
        action_settings: dict,
        printer: PrinterInterface,
        frontend: Frontend,
    ) -> _ActionT | _InvalidAction:
        try:
            action_config = action_class.config_class.from_settings(action_settings)
        except ValueError as error:
            logger = self._get_action_logger(_InvalidAction, index_id)
            logger.warning("Invalid settings: %s", error)
            return _InvalidAction(f"Invalid settings: {error}", printer, frontend, logger)

        return action_class(action_config, printer, frontend, self._get_action_logger(action_class, index_id))

    def _get_action_logger(self, action_class: type[Action], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{action_class.__name__}.{index_id}")
