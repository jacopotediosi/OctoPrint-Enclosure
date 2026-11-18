from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.settings import setting

from .base import Action, ActionConfig

SHELL_TIMEOUT_SECONDS = 5 * 60
"""The seconds a shell script may run before it is killed."""


@dataclass(frozen=True)
class ShellConfig(ActionConfig):
    """The configuration of an action that runs a shell script."""

    shell_script: str = setting(default="", label="Script")
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
        self._logger.info("Shell action %s started", self.config.index_id)
        threading.Thread(target=self._run_script, name="EnclosureShellAction", daemon=True).start()

    def _run_script(self) -> None:
        index_id = self.config.index_id
        command = self.config.shell_script

        try:
            with subprocess.Popen(  # noqa: S602 - the script can be set only by who can change the OctoPrint settings
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
                        self._logger.warning("Shell action %s killed after %s s", index_id, SHELL_TIMEOUT_SECONDS)
                        self._frontend.show_message(
                            f"Shell script killed after {SHELL_TIMEOUT_SECONDS} s, check logs",
                            "error",
                        )
                        return

                    stdout = (expired.stdout or b"").decode("utf-8", errors="replace")
                    stderr = (expired.stderr or b"").decode("utf-8", errors="replace")
                returncode = process.returncode
        except Exception:
            self._logger.exception("Shell action %s can't be executed", index_id)
            self._frontend.show_message("Could not execute a shell script, check logs", "error")
            return

        if returncode == 0:
            self._logger.debug("Shell action %s ended. Output: %s", index_id, stdout)
            self._frontend.show_message(f"Shell script executed. Output: {stdout}", "success")
        else:
            self._logger.warning("Shell action %s exited with code %s: %s", index_id, returncode, stderr)
            self._frontend.show_message(f"Shell script failed with exit code {returncode}. Error: {stderr}", "error")
