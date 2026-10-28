from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.automations import Automations
    from octoprint_enclosure.control_loop import ControlLoop
    from octoprint_enclosure.hardware import GpioBackend, I2cBackend
    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.integrations import Mqtt
    from octoprint_enclosure.notifications import Notifications
    from octoprint_enclosure.output_executor import OutputExecutor
    from octoprint_enclosure.outputs import Outputs

    from .frontend import Frontend
    from .scheduler import Scheduler
    from .settings import Settings


@dataclass(frozen=True)
class PluginContext:
    """Everything a plugin's component needs to do its work."""

    # Plugin general components
    logger: logging.Logger
    settings: Settings
    frontend: Frontend

    # OctoPrint interfaces
    printer: PrinterInterface

    # Hardware
    gpio: GpioBackend
    i2c: I2cBackend

    # Inputs, outputs, actions and automations
    sensors: Sensors
    gpio_inputs: GpioInputs
    outputs: Outputs
    actions: Actions
    automations: Automations

    # Threads
    sensor_poller: SensorPoller
    scheduler: Scheduler
    output_executor: OutputExecutor
    control_loop: ControlLoop

    # Notifications
    notifications: Notifications

    # Integrations
    mqtt: Mqtt
