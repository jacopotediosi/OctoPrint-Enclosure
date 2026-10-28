from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Action

SHELL_TIMEOUT_SECONDS = 5 * 60
"""The seconds a shell script may run before it is killed."""


@dataclass(frozen=True)
class ShellConfig(BaseConfig):
    """The configuration of an action that runs a shell script."""

    shell_script: str = ""
    """The shell script to run."""


class ShellAction(Action[ShellConfig]):
    """An action that runs a shell script.

    The script runs on a thread of its own, with a timeout, so a slow or stuck script holds up nothing else. At the
    timeout the script is killed together with everything it started, while what a script that already ended left
    running in the background (with `&`) is left alone.
    """

    config_class = ShellConfig

    @override
    def run(self) -> None:
        """Start the shell script; its result is shown within a frontend notification when it ends."""
        threading.Thread(target=self._run_script, name="EnclosureShellAction", daemon=True).start()

    def _run_script(self) -> None:
        command = self.config.shell_script

        try:
            with subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            ) as process:
                try:
                    stdout, stderr = process.communicate(timeout=SHELL_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as expired:
                    if process.poll() is None:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        self._logger.warning("Shell script %s killed after %s s", command, SHELL_TIMEOUT_SECONDS)
                        self._frontend.show_message(
                            f"Shell script killed after {SHELL_TIMEOUT_SECONDS} s, check logs",
                            "error",
                        )
                        return

                    stdout = (expired.stdout or b"").decode("utf-8", errors="replace")
                    stderr = (expired.stderr or b"").decode("utf-8", errors="replace")
                returncode = process.returncode
        except Exception:
            self._logger.exception("Could not execute shell script: %s", command)
            self._frontend.show_message("Could not execute a shell script, check logs", "error")
            return

        if returncode == 0:
            self._logger.debug("Shell script executed. Output: %s", stdout)
            self._frontend.show_message(f"Shell script executed. Output: {stdout}", "success")
        else:
            self._logger.warning("Shell script %s exited with code %s: %s", command, returncode, stderr)
            self._frontend.show_message(f"Shell script failed with exit code {returncode}. Error: {stderr}", "error")
