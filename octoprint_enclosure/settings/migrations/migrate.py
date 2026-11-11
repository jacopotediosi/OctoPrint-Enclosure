from __future__ import annotations

from typing import TYPE_CHECKING

from . import v10, v11

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from octoprint.plugin import PluginSettings

MIGRATIONS: tuple[tuple[int, Callable[[PluginSettings, logging.Logger], None]], ...] = (
    (10, v10.migrate),
    (11, v11.migrate),
)
"""The migration to each settings version, in order."""


def migrate_settings(target: int, current: int | None, settings: PluginSettings, logger: logging.Logger) -> None:
    """Run, in order, the migration of every settings version newer than the stored one.

    Args:
        target (int): The settings version the plugin needs.
        current (int | None): The settings version in storage, or None if the settings were never saved with a
            version, in which case every migration runs.
        settings (PluginSettings): The settings to migrate, updated in place; OctoPrint saves them, with the new
            version number, when this returns.
        logger (logging.Logger): The logger to write to.

    """
    logger = logger.getChild("Migration")
    logger.warning("Start migration from v%s to v%s", current, target)

    logger.info("Old settings:")
    logger.info("rpi_inputs: %s", settings.get(["rpi_inputs"]))
    logger.info("rpi_outputs: %s", settings.get(["rpi_outputs"]))
    logger.info("actions: %s", settings.get(["actions"]))
    logger.info("automations: %s", settings.get(["automations"]))

    current = 0 if current is None else current
    for version, migrate in MIGRATIONS:
        if current < version:
            logger.warning("Migrating settings to v%s", version)
            migrate(settings, logger)

    logger.info("Migrated settings:")
    logger.info("rpi_inputs: %s", settings.get(["rpi_inputs"]))
    logger.info("rpi_outputs: %s", settings.get(["rpi_outputs"]))
    logger.info("actions: %s", settings.get(["actions"]))
    logger.info("automations: %s", settings.get(["automations"]))
