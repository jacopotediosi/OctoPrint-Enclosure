from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from .base import Action, ActionConfig, ActionError
from .registry import ACTIONS

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.frontend import Frontend

_ActionT = TypeVar("_ActionT", bound=Action)


class _InvalidAction(Action[ActionConfig]):
    """An action that can't be set up."""

    config_class = ActionConfig

    reason: str
    """Why the action can't be set up."""

    def __init__(
        self,
        reason: str,
        config: ActionConfig,
        printer: PrinterInterface,
        frontend: Frontend,
        logger: logging.Logger,
    ) -> None:
        super().__init__(config, printer, frontend, logger)
        self.reason = reason

    @override
    def run(self) -> None:
        raise ActionError(self.reason)


class Actions:
    """The actions."""

    _printer: PrinterInterface
    """The OctoPrint printer interface."""

    _frontend: Frontend
    """The frontend handler."""

    _logger: logging.Logger

    _actions: dict[int, Action]
    """The action with each id."""

    def __init__(self, printer: PrinterInterface, frontend: Frontend, logger: logging.Logger) -> None:
        """Set up the actions, with none until some settings are loaded.

        Args:
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            logger (logging.Logger): The logger to write to.

        """
        self._printer = printer
        self._frontend = frontend
        self._logger = logger.getChild("Actions")
        self._actions = {}

    def load(self, actions_settings: Iterable[dict]) -> None:
        """Load some actions from their settings.

        An action whose settings didn't change is kept as it is.

        Args:
            actions_settings (Iterable[dict]): The settings of the actions.

        """
        actions: dict[int, Action] = {}

        for action_settings in actions_settings:
            try:
                action_config = ActionConfig.from_settings(action_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an action: %s", error)
                continue

            action_class = ACTIONS.get(action_config.action_type)
            if action_class is None:
                action: Action = self._create_invalid_action(
                    action_config,
                    f"Unsupported action type: {action_config.action_type!r}",
                )
            else:
                action = self._create_action(action_class, action_config, action_settings)

            actions[action_config.index_id] = action

        self._actions = actions

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

    def get_all(self, action_class: type[_ActionT]) -> list[_ActionT]:
        """Get all the actions having a certain class.

        Args:
            action_class (type[_ActionT]): The class the actions must be an instance of.

        Returns:
            list[_ActionT]: The actions.

        """
        return [action for action in self._actions.values() if isinstance(action, action_class)]

    def get_ids(self) -> set[int]:
        """Get the ids of the actions.

        Returns:
            set[int]: The id of each action.

        """
        return set(self._actions)

    def run(self, index_id: int, action_class: type[Action] = Action) -> Action:
        """Run an action.

        Args:
            index_id (int): The id of the action.
            action_class (type[Action]): The class the action must be an instance of; any action by default.

        Returns:
            Action: The action run.

        Raises:
            ActionError: If no action of that class is set up with that id.
            Exception: If the action can't be run.

        """
        action = self.get(index_id, action_class)
        action.run()
        return action

    def _create_action(
        self,
        action_class: type[_ActionT],
        action_config: ActionConfig,
        action_settings: dict,
    ) -> _ActionT | _InvalidAction:
        try:
            config = action_class.config_class.from_settings(action_settings)
        except ValueError as error:
            return self._create_invalid_action(action_config, f"Invalid settings: {error}")

        # An action whose settings didn't change is kept
        action = self._actions.get(action_config.index_id)
        if isinstance(action, action_class) and action.config == config:
            action.config = config
            return action

        return action_class(
            config,
            self._printer,
            self._frontend,
            self._get_action_logger(action_class, action_config.index_id),
        )

    def _create_invalid_action(self, action_config: ActionConfig, reason: str) -> _InvalidAction:
        logger = self._get_action_logger(_InvalidAction, action_config.index_id)
        logger.warning("%s", reason)
        return _InvalidAction(reason, action_config, self._printer, self._frontend, logger)

    def _get_action_logger(self, action_class: type[Action], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{action_class.__name__}.{index_id}")
