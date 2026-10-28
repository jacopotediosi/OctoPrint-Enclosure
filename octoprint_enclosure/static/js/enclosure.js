$(function () {
  function rgbToHex(rgb) {
    var match = /^\s*rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)\s*$/.exec(rgb || "");
    if (!match) return "#000000";
    return "#" + match.slice(1).map(function (component) {
      return ("0" + Math.min(parseInt(component, 10), 255).toString(16)).slice(-2);
    }).join("");
  }

  function hexToRgb(hex) {
    var value = parseInt(hex.slice(1), 16);
    return "rgb(" + ((value >> 16) & 255) + "," + ((value >> 8) & 255) + "," + (value & 255) + ")";
  }

  ko.bindingHandlers.rgbColor = {
    init: function (element, valueAccessor) {
      ko.utils.registerEventHandler(element, "change", function () {
        valueAccessor()(hexToRgb(element.value));
      });
    },
    update: function (element, valueAccessor, allBindings) {
      element.value = rgbToHex(ko.unwrap(valueAccessor()) || ko.unwrap(allBindings.get("rgbColorPlaceholder")));
    }
  };

  ko.bindingHandlers.placeholderWhenUnset = {
    after: ["options", "value"],
    update: function (element, valueAccessor, allBindings) {
      ko.unwrap(allBindings.get("value"));
      ko.unwrap(allBindings.get("options"));
      setTimeout(function () {
        if (element.selectedIndex === -1) {
          element.selectedIndex = 0;
        }
      }, 0);
    }
  };

  function EnclosureViewModel(parameters) {
    var self = this;

    self.pluginName = "enclosure";

    self.settingsViewModel = parameters[0];
    self.connectionViewModel = parameters[1];
    self.printerStateViewModel = parameters[2];

    self.rpi_inputs = ko.observableArray();
    self.rpi_outputs = ko.observableArray();
    self.actions = ko.observableArray();
    self.automations = ko.observableArray();

    self.settingsOpen = false;

    self.settings_gpio_inputs = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_inputs(), function (item) {
        return (item.input_type() === "gpio");
      });
    });

    self.settings_temperature_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_inputs(), function (item) {
        return (item.input_type() === "temperature_sensor");
      });
    });

    self.settings_hum_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settings_temperature_sensors(), function (sensor) {
        return (self.humidityCapableSensor(sensor.temp_sensor_type()));
      });
    });

    self.humidityCapableSensor = function (sensor) {
      return ['11', '20', '22', '2302', 'bme280', 'bme680', 'am2320', 'aht10', 'si7021', 'hum_raw_i2c', 'temp_raw_i2c'].indexOf(sensor) >= 0;
    };

    self.disablePlaceholderOption = function (option, item) {
      if (item === undefined) {
        option.disabled = true;
      }
    };

    self.settings_outputs_regular = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs(), function (item) {
        return (item.output_type() === "regular" && !item.toggle_timer());
      });
    });

    self.settings_outputs_pwm = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs(), function (item) {
        return (item.output_type() === "pwm");
      });
    });

    self.rpi_inputs_temperature_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_inputs(), function (item) {
        return (item.input_type() === "temperature_sensor");
      });
    });

    self.navbar_temperature_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_inputs_temperature_sensors(), function (item) {
        return (item.temp_sensor_navbar());
      });
    });

    self.navbar_items = ko.pureComputed(function () {
      var outputs = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
        return (item.output_type() === "regular" && item.show_on_navbar());
      });
      var actions = ko.utils.arrayFilter(self.actions(), function (item) {
        return (item.action_type() !== "" && item.show_on_navbar());
      });
      return outputs.concat(actions);
    });

    self.navbarItemType = function (item) {
      return ko.unwrap(item.output_type || item.action_type);
    };

    self.tab_temperature_table_rows = ko.pureComputed(function () {
      var rows = [];
      self.rpi_inputs_temperature_sensors().forEach(function (sensor) {
        var thermostats = self.linkedThermostats(sensor.index_id())();
        var rowspan = Math.max(thermostats.length, 1);
        if (thermostats.length === 0) {
          rows.push({sensor: sensor, thermostat: null, first: true, rowspan: rowspan});
        }
        thermostats.forEach(function (thermostat, index) {
          rows.push({sensor: sensor, thermostat: thermostat, first: index === 0, rowspan: rowspan});
        });
      });
      return rows;
    });

    self.tab_outputs = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
        return (item.output_type() !== "" && !item.hide_btn_ui());
      });
    });

    self.tab_actions = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.actions(), function (item) {
        return (item.action_type() !== "" && !item.hide_btn_ui());
      });
    });

    self.tab_filament_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.automations(), function (item) {
        return (item.automation_type() === "filament" && item.input() !== "");
      });
    });

    self.isRegularOutput = function (index_id) {
      return self.settingsViewModel.settings.plugins.enclosure.rpi_outputs().some(function (output) {
        return output.index_id() == index_id && output.output_type() == "regular";
      });
    };

    self.isPwmLinked = function (index_id) {
      return self.settingsViewModel.settings.plugins.enclosure.automations().some(function (automation) {
        return automation.automation_type() == "pwm_temperature_linked" && automation.output() == index_id;
      });
    };

    self.linkedThermostats = function(sensor_index){
      return ko.pureComputed(function () {
        return ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
          if (item.linked_temp_sensor){
            return (item.linked_temp_sensor() == sensor_index && item.output_type() == "temp_hum_control");
          }else{
            return false;
          }
        });
      });
    };

    self.hasAnySensorWithHumidity = function () {
      return self.rpi_inputs_temperature_sensors().some(function (sensor) {
        return self.humidityCapableSensor(sensor.temp_sensor_type());
      });
    };

    self.hasAnyThermostat = function () {
      return self.rpi_outputs().some(function (output) {
        return output.output_type() == "temp_hum_control";
      });
    };

    self.onDataUpdaterPluginMessage = function (plugin, data) {

      if (typeof plugin == 'undefined'){
        return;
      }

      if (plugin != "enclosure") {
        return;
      }

      if(self.settingsOpen){
        return;
      }

      if (data.hasOwnProperty("sensor_data")) {
        data.sensor_data.forEach(function (sensor_data) {
          var linked_temp_sensor = ko.utils.arrayFilter(self.rpi_inputs_temperature_sensors(), function (temperature_sensor) {
            return (sensor_data['index_id'] == temperature_sensor.index_id());
          }).pop();
          if (linked_temp_sensor){
            linked_temp_sensor.temp_sensor_temp(sensor_data['temperature'] === null ? "" : sensor_data['temperature'])
            linked_temp_sensor.temp_sensor_humidity(sensor_data['humidity'] === null ? "" : sensor_data['humidity'])
          }
        })
      }

      if (data.hasOwnProperty("set_temperature")) {
        data.set_temperature.forEach(function (set_temperature) {
          var linked_thermostat = ko.utils.arrayFilter(self.rpi_outputs(), function (thermostat) {
            return (set_temperature['index_id'] == thermostat.index_id());
          }).pop();
          if (linked_thermostat) {
            linked_thermostat.temp_ctr_set_value(set_temperature['set_temperature'])
          }
        })
      }

      if (data.hasOwnProperty("rpi_output_regular")) {
        data.rpi_output_regular.forEach(function (output) {
          var linked_output = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
            return (output['index_id'] == item.index_id());
          }).pop();
          if (linked_output) {
            linked_output.gpio_status(output['status'])
            linked_output.auto_shutdown(output['auto_shutdown'])
            linked_output.auto_startup(output['auto_startup'])
          }
        })
      }

      if (data.hasOwnProperty("rpi_output_thermostat")) {
        data.rpi_output_thermostat.forEach(function (output) {
          var linked_output = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
            return (output['index_id'] == item.index_id());
          }).pop();
          if (linked_output) {
            linked_output.gpio_status(output['status'])
            linked_output.auto_shutdown(output['auto_shutdown'])
            linked_output.auto_startup(output['auto_startup'])
          }
        })
      }

      if (data.hasOwnProperty("rpi_output_pwm")) {
        data.rpi_output_pwm.forEach(function (output) {
          var linked_output = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
            return (output['index_id'] == item.index_id());
          }).pop();
          if (linked_output) {
            linked_output.duty_cycle(output['pwm_value'])
            linked_output.auto_shutdown(output['auto_shutdown'])
            linked_output.auto_startup(output['auto_startup'])
          }
        })
      }

      if (data.hasOwnProperty("rpi_output_neopixel")) {
        data.rpi_output_neopixel.forEach(function (output) {
          var linked_output = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
            return (output['index_id'] == item.index_id());
          }).pop();
          if (linked_output) {
            linked_output.neopixel_color(output['color'])
            linked_output.auto_shutdown(output['auto_shutdown'])
            linked_output.auto_startup(output['auto_startup'])
          }
        })
      }

      if (data.hasOwnProperty("rpi_output_ledstrip")) {
        data.rpi_output_ledstrip.forEach(function (output) {
          var linked_output = ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
            return (output['index_id'] == item.index_id());
          }).pop();
          if (linked_output) {
            linked_output.ledstrip_color(output['color'])
            linked_output.auto_shutdown(output['auto_shutdown'])
            linked_output.auto_startup(output['auto_startup'])
          }
        })
      }

      if (data.hasOwnProperty("filament_sensor_status")) {
        data.filament_sensor_status.forEach(function (filament_sensor) {
          var linked_filament_sensor = ko.utils.arrayFilter(self.automations(), function (item) {
            return (filament_sensor['index_id'] == item.index_id());
          }).pop();
          if (linked_filament_sensor) {
            linked_filament_sensor.filament_sensor_enabled(filament_sensor['filament_sensor_enabled'])
          }
        })
      }

      if (data.is_msg) {
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: data.msg,
          text_escape: true,
          type: data.msg_type
        });
      }
    };

    self.isUser = ko.computed(function () {
      return self.connectionViewModel.loginState.isUser();
    });

    self.isOperational = ko.computed(function () {
      return self.connectionViewModel.loginState.isUser() && self.printerStateViewModel.isOperational();
    });


    self.getCleanTemperature = function (temp) {
      if (temp === undefined || isNaN(parseFloat(temp))) return "-";
      if (temp < 10) return String("off");
      return temp;
    }

    self.getDutyCycle = function (duty_cycle) {
      if (duty_cycle === undefined || isNaN(parseFloat(duty_cycle))) return "-";
      if (parseInt(duty_cycle) == 0) return String("off");
      return duty_cycle;
    }

    self.inputStates = {};
    self.outputStates = {};

    self.newInputState = function () {
      return {
        temp_sensor_temp: ko.observable(""),
        temp_sensor_humidity: ko.observable("")
      };
    };

    self.newOutputState = function () {
      return {
        gpio_status: ko.observable(false),
        duty_cycle: ko.observable(0),
        new_duty_cycle: ko.observable(""),
        neopixel_color: ko.observable("rgb(0,0,0)"),
        new_neopixel_color: ko.observable(""),
        ledstrip_color: ko.observable("rgb(0,0,0)"),
        new_ledstrip_color: ko.observable(""),
        temp_ctr_set_value: ko.observable(0),
        temp_ctr_new_set_value: ko.observable("")
      };
    };

    self.withState = function (items, states, newState) {
      var kept = {};
      var wrapped = items.map(function (item) {
        var index_id = item.index_id();
        kept[index_id] = states[index_id] || newState();
        return $.extend({}, item, kept[index_id]);
      });
      return {states: kept, items: wrapped};
    };

    self.bindFromSettings = function(){
      var settings = self.settingsViewModel.settings.plugins.enclosure;
      var inputs = self.withState(settings.rpi_inputs(), self.inputStates, self.newInputState);
      var outputs = self.withState(settings.rpi_outputs(), self.outputStates, self.newOutputState);
      self.inputStates = inputs.states;
      self.outputStates = outputs.states;
      self.rpi_inputs(inputs.items);
      self.rpi_outputs(outputs.items);
      self.actions(settings.actions());
      self.automations(settings.automations());
    };

    self.onBeforeBinding = function () {
      self.bindFromSettings();
    };

    self.onSettingsBeforeSave = function() {
      self.bindFromSettings();
    };

    self.onStartupComplete = function () {
      self.settingsOpen = false;
      self.notifyGpioAlert();
      self.getUpdateUI();
    };

    self.notifyGpioAlert = function () {
      var gpioAlert = $(".enclosure-gpio-alert").first();
      if (gpioAlert.length) {
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: gpioAlert.text(),
          text_escape: true,
          type: "error",
          hide: false
        });
      }
    };

    self.onSettingsShown = function () {
      self.settingsOpen = true;
    };

    self.onSettingsHidden = function () {
      self.settingsOpen = false;
      self.getUpdateUI();
    };

    self.onServerReconnect = function () {
      self.getUpdateUI();
    };

    self.setTemperature = function (item, form) {

      var newSetTemperature = item.temp_ctr_new_set_value();
      if (form !== undefined) {
        $(form).find("input").blur();
      }

      if(self.isNumeric(newSetTemperature)){
        OctoPrint.patchJson(self.buildPluginUrl("temperature/" + item.index_id()), {temperature: parseFloat(newSetTemperature)})
          .done(function () {
            item.temp_ctr_new_set_value("");
          })
          .fail(function () {
            new PNotify({
              title: "Enclosure",
              title_escape: true,
              text: "Error setting temperature",
              text_escape: true,
              type: "error"
            });
          });
      }else{
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: "Invalid set temperature",
          text_escape: true,
          type: "error"
        });
      }
    };

    self.addRpiInput = function () {
      var arrRelaysLength = self.settingsViewModel.settings.plugins.enclosure.rpi_inputs().length;
      var nextIndex = arrRelaysLength == 0 ? 1 : self.settingsViewModel.settings.plugins.enclosure.rpi_inputs()[arrRelaysLength - 1].index_id() + 1;

      self.settingsViewModel.settings.plugins.enclosure.rpi_inputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Input " + nextIndex),
        input_type: ko.observable(""),
        gpio_pin: ko.observable(0),
        input_pull_resistor: ko.observable("input_pull_up"),
        temp_sensor_type: ko.observable(""),
        temp_sensor_address: ko.observable(""),
        ds18b20_serial: ko.observable(""),
        use_fahrenheit: ko.observable(false),
        temp_sensor_navbar: ko.observable(true),
        temp_sensor_i2cbus: ko.observable(1),
        temp_i2c_bus: ko.observable(1),
        temp_i2c_address: ko.observable(1),
        temp_i2c_register: ko.observable(1),
        show_graph_temp: ko.observable(false),
        show_graph_humidity: ko.observable(false)
      });
    };

    self.removeRpiInput = function (definition) {
      self.settingsViewModel.settings.plugins.enclosure.rpi_inputs.remove(definition);
    };

    // Outputs, actions and automations share the ids, because many actions and automations used to be inputs/outputs and keep their ids
    self.nextSharedIndex = function () {
      var enclosure = self.settingsViewModel.settings.plugins.enclosure;
      var indexes = enclosure.rpi_outputs().concat(enclosure.actions(), enclosure.automations()).map(function (item) {
        return parseInt(item.index_id(), 10) || 0;
      });
      return indexes.length == 0 ? 1 : Math.max.apply(null, indexes) + 1;
    };

    self.addRpiOutput = function () {
      var nextIndex = self.nextSharedIndex();

      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Output " + nextIndex),
        output_type: ko.observable(""),
        gpio_pin: ko.observable(0),
        hide_btn_ui: ko.observable(false),
        active_low: ko.observable(true),
        toggle_timer: ko.observable(false),
        toggle_timer_on: ko.observable(0),
        toggle_timer_off: ko.observable(0),
        startup_with_server: ko.observable(false),
        auto_startup: ko.observable(false),
        startup_time: ko.observable(0),
        auto_shutdown: ko.observable(false),
        shutdown_on_failed: ko.observable(false),
        shutdown_time: ko.observable(0),
        linked_temp_sensor: ko.observable(""),
        temp_ctr_type: ko.observable(""),
        temp_ctr_deadband: ko.observable(0),
        temp_ctr_default_value: ko.observable(0),
        temp_ctr_max_temp: ko.observable(0),
        pwm_frequency: ko.observable(50),
        default_duty_cycle: ko.observable(0),
        default_neopixel_color: ko.observable(""),
        neopixel_count: ko.observable(0),
        neopixel_brightness: ko.observable(255),
        neopixel_dma: ko.observable(10),
        default_ledstrip_color: ko.observable(""),
        ledstrip_gpio_clk: ko.observable(""),
        ledstrip_gpio_dat: ko.observable(""),
        microcontroller_address: ko.observable(0),
        show_on_navbar: ko.observable(false),
        gpio_i2c_enabled: ko.observable(false),
        gpio_i2c_bus: ko.observable(1),
        gpio_i2c_address: ko.observable(1),
        gpio_i2c_register: ko.observable(1),
        gpio_i2c_data_on: ko.observable(1),
        gpio_i2c_data_off: ko.observable(0),
        gpio_i2c_register_status: ko.observable(1),
        shutdown_on_error:ko.observable(false),
      });

    };

    self.removeRpiOutput = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.remove(data);
    };

    self.addAction = function () {
      var nextIndex = self.nextSharedIndex();

      self.settingsViewModel.settings.plugins.enclosure.actions.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Action " + nextIndex),
        action_type: ko.observable(""),
        gcode: ko.observable(""),
        shell_script: ko.observable(""),
        printer_action: ko.observable("pause"),
        hide_btn_ui: ko.observable(false),
        show_on_navbar: ko.observable(false)
      });
    };

    self.removeAction = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.actions.remove(data);
    };

    self.addAutomation = function () {
      var nextIndex = self.nextSharedIndex();

      self.settingsViewModel.settings.plugins.enclosure.automations.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Automation " + nextIndex),
        automation_type: ko.observable(""),
        trigger_type: ko.observable(""),
        input: ko.observable(""),
        edge: ko.observable("fall"),
        linked_temp_sensor: ko.observable(""),
        alarm_set_temp: ko.observable(""),
        repeat_while_above: ko.observable(false),
        reaction_type: ko.observable(""),
        controlled_io: ko.observable(""),
        controlled_io_set_state: ko.observable("on"),
        action: ko.observable(""),
        filament_sensor_enabled: ko.observable(true),
        filament_sensor_timeout: ko.observable(120),
        output: ko.observable(""),
        temperature_a: ko.observable(0),
        duty_a: ko.observable(0),
        temperature_b: ko.observable(0),
        duty_b: ko.observable(0)
      });
    };

    self.removeAutomation = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.automations.remove(data);
    };

    self.turnOffHeater = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("temperature/" + item.index_id()), {temperature: 0});
    };

    self.getUpdateUI = function () {
      OctoPrint.post(self.buildPluginUrl("update"));
    };

    self.handleIO = function (item, form) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id()), {status: !item.gpio_status()});
    };

    self.handleGcode = function (item, form) {
      OctoPrint.post(self.buildPluginUrl("gcode/" + item.index_id()));
    };

    self.handleShellOutput = function (item, form) {
      OctoPrint.post(self.buildPluginUrl("shell/" + item.index_id()));
    };

    self.handlePrinterAction = function (item, form) {
      OctoPrint.post(self.buildPluginUrl("printer/" + item.index_id()));
    };

    self.switchAutoStartUp = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id() + "/auto-startup"), {status: !item.auto_startup()});
    };

    self.switchAutoShutdown = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id() + "/auto-shutdown"), {status: !item.auto_shutdown()});
    };

    self.switchFilamentSensor = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("filament/" + item.input()), {status: !item.filament_sensor_enabled()});
    };

    self.handlePWM = function (item) {
      var pwm_value = item.new_duty_cycle();

      pwm_value = parseInt(pwm_value);

      if (pwm_value < 0 || pwm_value > 100 || isNaN(pwm_value)) {
        item.new_duty_cycle("")
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: "Duty Cycle value needs to be between 0 and 100!",
          text_escape: true,
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("pwm/" + item.index_id()), {duty_cycle: pwm_value})
          .done(function () {
            item.new_duty_cycle("");
          });
      }
    };

    self.handleNeopixel = function (item) {

      var index = item.index_id() ;
      var or_tempStr = item.new_neopixel_color() || item.neopixel_color();
      var tempStr = or_tempStr.replace("rgb(", "");

      var r = parseInt(tempStr.substring(0, tempStr.indexOf(",")));
      tempStr = tempStr.slice(tempStr.indexOf(",") + 1);
      var g = parseInt(tempStr.substring(0, tempStr.indexOf(",")));
      tempStr = tempStr.slice(tempStr.indexOf(",") + 1);
      var b = parseInt(tempStr.substring(0, tempStr.indexOf(")")));

      if (r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255 || isNaN(r) || isNaN(g) || isNaN(b)) {
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: "Color needs to follow the format rgb(value_red,value_green,value_blue)!",
          text_escape: true,
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("neopixel/" + index), {red: r, green: g, blue: b})
          .done(function () {
            item.new_neopixel_color("");
          });
      }
    };

    self.handleLedstripColor = function (item) {
      var index = item.index_id() ;
      var or_tempStr = item.new_ledstrip_color() || item.ledstrip_color();
      var tempStr = or_tempStr.replace("rgb(", "");

      var r = parseInt(tempStr.substring(0, tempStr.indexOf(",")));
      tempStr = tempStr.slice(tempStr.indexOf(",") + 1);
      var g = parseInt(tempStr.substring(0, tempStr.indexOf(",")));
      tempStr = tempStr.slice(tempStr.indexOf(",") + 1);
      var b = parseInt(tempStr.substring(0, tempStr.indexOf(")")));
      if (r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255 || isNaN(r) || isNaN(g) || isNaN(b)) {
        new PNotify({
          title: "Enclosure",
          title_escape: true,
          text: "Color needs to follow the format rgb(value_red,value_green,value_blue)!",
          text_escape: true,
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("rgb-led/" + index), {rgb: or_tempStr})
          .done(function () {
            item.new_ledstrip_color("");
          });
      }
    };

    self.isNumeric = function (n) {
      return !isNaN(parseFloat(n)) && isFinite(n);
    };

    self.buildPluginUrl = function (path) {
      return OctoPrint.getBlueprintUrl(self.pluginName) + path;
    };
  }

  OCTOPRINT_VIEWMODELS.push({
    construct: EnclosureViewModel,
    // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
    dependencies: ["settingsViewModel", "connectionViewModel", "printerStateViewModel"],
    // Elements to bind to, e.g. #settings_plugin_tasmota-mqtt, #tab_plugin_tasmota-mqtt, ...
    elements: ["#tab_plugin_enclosure", "#settings_plugin_enclosure", "#navbar_plugin_enclosure_1", "#navbar_plugin_enclosure_2"]
  });

});
