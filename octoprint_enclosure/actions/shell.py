from __future__ import annotations

import subprocess
from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Action


@dataclass(frozen=True)
class ShellConfig(BaseConfig):
    """The configuration of an action that runs a shell script."""

    shell_script: str = ""
    """The shell script to run."""


class ShellAction(Action[ShellConfig]):
    """An action that runs a shell script."""

    config_class = ShellConfig

    @override
    def run(self) -> None:
        """Run the shell script, and show the result within a frontend notification."""
        command = self.config.shell_script

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            self._logger.exception("Could not execute shell script: %s", command)
            self._frontend.show_message("Could not execute a shell script, check logs", "error")
            return

        if result.returncode == 0:
            self._logger.debug("Shell script executed. Output: %s", result.stdout)
            self._frontend.show_message(f"Shell script executed. Output: {result.stdout}", "success")
        else:
            self._logger.warning("Shell script %s exited with code %s: %s", command, result.returncode, result.stderr)
            self._frontend.show_message(
                f"Shell script failed with exit code {result.returncode}. Error: {result.stderr}",
                "error",
            )
