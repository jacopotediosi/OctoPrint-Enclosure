from octoprint.util.version import is_octoprint_compatible

from .plugin import EnclosurePlugin


def _get_plugin_implementation() -> EnclosurePlugin:
    """Build the plugin implementation.

    Returns:
        EnclosurePlugin: The implementation OctoPrint loads.

    Raises:
        RuntimeError: If the OctoPrint version is not supported.

    """
    if not is_octoprint_compatible(">=1.4.0"):
        raise RuntimeError("OctoPrint 1.4.0 or greater required.")

    return EnclosurePlugin()


__plugin_name__ = "Enclosure Plugin"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = _get_plugin_implementation()
__plugin_hooks__ = {
    "octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.hook_gcode_queuing,
    "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
    "octoprint.comm.protocol.temperatures.received": (__plugin_implementation__.get_graph_data, 1),
}
