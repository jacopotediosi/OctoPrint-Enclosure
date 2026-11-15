from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.outputs import Thermostat, ThermostatOutput

if TYPE_CHECKING:
    from octoprint_enclosure.frontend import Frontend
    from octoprint_enclosure.outputs import Outputs


class Thermostats:
    """The thermostats."""

    _outputs: Outputs
    _frontend: Frontend

    _thermostats: dict[int, Thermostat]
    """The thermostats, by the id of their output."""

    def __init__(self, outputs: Outputs, frontend: Frontend) -> None:
        """Set up the thermostats.

        Args:
            outputs (Outputs): The outputs.
            frontend (Frontend): The frontend handler.

        """
        self._outputs = outputs
        self._frontend = frontend

        self._thermostats = {}

    def load(self) -> None:
        """Load the thermostats of the outputs that are thermostats.

        The thermostat of an output whose settings didn't change is kept, with its target.
        """
        thermostats: dict[int, Thermostat] = {}

        for output in self._outputs.get_all(ThermostatOutput):
            # Keep the thermostat of an output the settings didn't change, with its target
            index_id = output.config.index_id
            thermostat = self._thermostats.get(index_id)
            if thermostat is None or thermostat.config != output.config:
                thermostat = Thermostat(output.config)
            thermostats[index_id] = thermostat

        self._thermostats = thermostats
        self._frontend.set_thermostats(self.get_all())

    def get(self, index_id: int) -> Thermostat | None:
        """Get a thermostat.

        Args:
            index_id (int): The id of the output of the thermostat.

        Returns:
            Thermostat | None: The thermostat, or None if the output is not a thermostat.

        """
        return self._thermostats.get(index_id)

    def get_all(self) -> dict[int, Thermostat]:
        """Get the thermostats.

        Returns:
            dict[int, Thermostat]: The thermostats, by the id of their output.

        """
        return dict(self._thermostats)
