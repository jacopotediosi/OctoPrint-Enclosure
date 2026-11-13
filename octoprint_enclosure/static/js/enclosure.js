$(function () {
  ko.bindingHandlers.temperature = {
    init: function (element, valueAccessor, allBindings, viewModel, bindingContext) {
      ko.utils.registerEventHandler(element, "change", function () {
        var value = parseFloat(element.value);
        if (isNaN(value)) {
          valueAccessor()(element.value.trim() === "" ? null : element.value);
          return;
        }
        var toCelsius = allBindings.get("temperatureInterval") ? bindingContext.$root.toCelsiusInterval : bindingContext.$root.toCelsius;
        valueAccessor()(toCelsius(value));
      });
    },
    update: function (element, valueAccessor, allBindings, viewModel, bindingContext) {
      var value = parseFloat(ko.unwrap(valueAccessor()));
      if (isNaN(value)) {
        element.value = ko.unwrap(valueAccessor());
        return;
      }
      var fromCelsius = allBindings.get("temperatureInterval") ? bindingContext.$root.fromCelsiusInterval : bindingContext.$root.fromCelsius;
      element.value = fromCelsius(value);
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
    self.loginState = parameters[1];
    self.access = parameters[2];
    self.printerStateViewModel = parameters[3];

    self.rpi_inputs = ko.observableArray();
    self.rpi_outputs = ko.observableArray();
    self.actions = ko.observableArray();
    self.automations = ko.observableArray();

    self.settingsOpen = false;

    self.temperatureUnit = ko.pureComputed(function () {
      return self.settingsViewModel.settings.plugins.enclosure.temperature_unit();
    });

    self.temperatureUnitLabel = ko.pureComputed(function () {
      return self.temperatureUnit() === "fahrenheit" ? "°F" : "°C";
    });

    self.fromCelsius = function (celsius) {
      if (celsius === null || self.temperatureUnit() !== "fahrenheit") return celsius;
      return Math.round((celsius * 1.8 + 32) * 10) / 10;
    };

    self.fromCelsiusInterval = function (interval) {
      if (self.temperatureUnit() !== "fahrenheit") return interval;
      return Math.round(interval * 1.8 * 10) / 10;
    };

    self.toCelsius = function (temperature) {
      if (self.temperatureUnit() !== "fahrenheit") return temperature;
      return Math.round((temperature - 32) / 1.8 * 100) / 100;
    };

    self.toCelsiusInterval = function (interval) {
      if (self.temperatureUnit() !== "fahrenheit") return interval;
      return Math.round(interval / 1.8 * 100) / 100;
    };

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
        return (item.automation_type() === "filament" && item.input() !== "" && item.show_in_tab());
      });
    });

    self.tab_automations = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.automations(), function (item) {
        return item.show_in_tab() && item.automation_type() !== "filament" && self.controlledOutputs(item).length != 1;
      });
    });

    self.settingsOutput = function (index_id) {
      return ko.utils.arrayFirst(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs(), function (output) {
        return output.index_id() == index_id;
      });
    };

    self.outputType = function (index_id) {
      var output = self.settingsOutput(index_id);
      return output ? output.output_type() : "";
    };

    self.thermostatDeviceType = function (index_id) {
      var output = self.settingsOutput(index_id);
      return output ? output.temp_ctr_type() : "";
    };

    self.isPwmLinked = function (index_id) {
      return self.automations().some(function (automation) {
        return automation.automation_type() == "pwm_temperature_linked" && automation.output() == index_id && automation.enabled();
      });
    };

    self.isTurnedOffAtPrintEnd = function (index_id) {
      return self.automations().some(function (automation) {
        return automation.automation_type() == "rule" && automation.enabled() && automation.trigger_type() == "octoprint_event"
          && automation.octoprint_events().indexOf("PrintDone") >= 0
          && automation.reactions().some(function (reaction) {
            return reaction.reaction_type() == "output_control" && reaction.controlled_io() == index_id
              && reaction.controlled_io_set_state() == "off";
          });
      });
    };

    self.controlledOutputs = function (automation) {
      var outputs = [];
      if (automation.automation_type() == "pwm_temperature_linked" || automation.automation_type() == "toggle_timer") {
        outputs = [automation.output()];
      } else if (automation.automation_type() == "rule") {
        outputs = automation.reactions().filter(function (reaction) {
          return reaction.reaction_type() == "output_control";
        }).map(function (reaction) {
          return reaction.controlled_io();
        });
      }
      return outputs.filter(function (output_id, index) {
        return outputs.indexOf(output_id) == index && self.rpi_outputs().some(function (output) {
          return output.index_id() == output_id;
        });
      });
    };

    self.automationsOn = function (index_id) {
      return ko.utils.arrayFilter(self.automations(), function (automation) {
        var outputs = self.controlledOutputs(automation);
        return automation.show_in_tab() && outputs.length == 1 && outputs[0] == index_id;
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
      if (plugin != "enclosure" || self.settingsOpen) {
        return;
      }

      Object.keys(self.pushCounts).forEach(function (kind) {
        if (data.hasOwnProperty(kind)) {
          self.pushCounts[kind]++;
        }
      });
      self.applyState(data);

      if (data.is_msg) {
        self.notify(data.msg, data.msg_type);
      }
    };

    self.applyState = function (data) {
      var states = {inputs: self.inputStates, outputs: self.outputStates, automations: {}};
      self.automations().forEach(function (automation) {
        states.automations[automation.index_id()] = {enabled: automation.enabled};
      });

      Object.keys(states).forEach(function (kind) {
        (data[kind] || []).forEach(function (item) {
          var state = states[kind][item.id] || {};
          Object.keys(state).forEach(function (key) {
            if (item.hasOwnProperty(key)) {
              state[key](item[key]);
            }
          });
        });
      });
    };

    self.pushCounts = {inputs: 0, outputs: 0, automations: 0};

    self.refreshState = function () {
      if (!self.hasStatusPermission()) {
        return;
      }

      Object.keys(self.pushCounts).forEach(function (kind) {
        var pushCount = self.pushCounts[kind];
        OctoPrint.get(self.buildPluginUrl(kind)).done(function (items) {
          if (self.settingsOpen || self.pushCounts[kind] !== pushCount) {
            return;
          }
          var data = {};
          data[kind] = items;
          self.applyState(data);
        });
      });
    };

    self.notify = function (text, type, options) {
      new PNotify($.extend({
        title: "Enclosure",
        title_escape: true,
        text: text,
        text_escape: true,
        type: type
      }, options));
    };

    self.hasPluginPermissionKo = function (key) {
      return ko.pureComputed(function () {
        return self.loginState.hasPermission(self.access.permissions["PLUGIN_ENCLOSURE_" + key]);
      });
    };

    self.hasStatusPermission = self.hasPluginPermissionKo("STATUS");
    self.hasOutputsControlPermission = self.hasPluginPermissionKo("OUTPUTS_CONTROL");
    self.hasActionsRunPermission = self.hasPluginPermissionKo("ACTIONS_RUN");
    self.hasAutomationsEnablePermission = self.hasPluginPermissionKo("AUTOMATIONS_ENABLE");

    self.isOperational = ko.pureComputed(function () {
      return self.hasActionsRunPermission() && self.printerStateViewModel.isOperational();
    });

    self.shownTarget = function (thermostat) {
      var target = thermostat.target();
      if (target === null) return "off";
      return thermostat.temp_ctr_type() == "dehumidifier" ? target : self.fromCelsius(target);
    };

    self.shownDutyCycle = function (duty_cycle) {
      return duty_cycle == 0 ? "off" : duty_cycle;
    };

    self.inputStates = {};
    self.outputStates = {};

    self.newInputState = function () {
      return {
        temperature: ko.observable(null),
        humidity: ko.observable(null)
      };
    };

    self.newOutputState = function () {
      var state = {
        on: ko.observable(false),
        duty_cycle: ko.observable(0),
        new_duty_cycle: ko.observable(""),
        color: ko.observable("#000000"),
        new_color: ko.observable(""),
        target: ko.observable(null),
        new_target: ko.observable("")
      };
      state.shown_color = ko.pureComputed({
        read: function () {
          return state.new_color() || state.color();
        },
        write: state.new_color
      });
      return state;
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
    };

    self.onUserPermissionsChanged = self.onUserLoggedIn = self.onUserLoggedOut = function () {
      self.refreshState();
    };

    self.notifyGpioAlert = function () {
      var gpioAlert = $(".enclosure-gpio-alert").first();
      if (gpioAlert.length) {
        self.notify(gpioAlert.text(), "error", {hide: false});
      }
    };

    self.onSettingsShown = function () {
      self.settingsOpen = true;
    };

    self.onSettingsHidden = function () {
      self.settingsOpen = false;
      self.refreshState();
    };

    self.onServerReconnect = function () {
      self.refreshState();
    };

    self.setTarget = function (item, form) {
      if (form !== undefined) {
        $(form).find("input").blur();
      }

      if (!self.isNumeric(item.new_target())) {
        self.notify("Invalid set temperature", "error");
        return;
      }

      var target = parseFloat(item.new_target());
      if (item.temp_ctr_type() != "dehumidifier") {
        target = self.toCelsius(target);
      }
      self.setOutput(item, {target: target})
        .done(function () {
          item.new_target("");
        })
        .fail(function () {
          self.notify("Error setting temperature", "error");
        });
    };

    self.nextIndexId = function (items) {
      var indexes = items.map(function (item) {
        return parseInt(item.index_id(), 10) || 0;
      });
      return indexes.length == 0 ? 1 : Math.max.apply(null, indexes) + 1;
    };

    self.addRpiInput = function () {
      var nextIndex = self.nextIndexId(self.settingsViewModel.settings.plugins.enclosure.rpi_inputs());

      self.settingsViewModel.settings.plugins.enclosure.rpi_inputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Input " + nextIndex),
        input_type: ko.observable(""),
        gpio_pin: ko.observable(0),
        input_pull_resistor: ko.observable("input_pull_up"),
        temp_sensor_type: ko.observable(""),
        temp_sensor_address: ko.observable(""),
        ds18b20_serial: ko.observable(""),
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

    self.addRpiOutput = function () {
      var nextIndex = self.nextIndexId(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs());

      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Output " + nextIndex),
        output_type: ko.observable(""),
        gpio_pin: ko.observable(0),
        hide_btn_ui: ko.observable(false),
        active_low: ko.observable(true),
        linked_temp_sensor: ko.observable(""),
        temp_ctr_type: ko.observable(""),
        temp_ctr_deadband: ko.observable(0),
        temp_ctr_max_temp: ko.observable(null),
        pwm_frequency: ko.observable(50),
        neopixel_count: ko.observable(0),
        neopixel_brightness: ko.observable(255),
        neopixel_dma: ko.observable(10),
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
        gpio_i2c_register_status: ko.observable(1)
      });

    };

    self.removeRpiOutput = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.remove(data);
    };

    self.addAction = function () {
      var nextIndex = self.nextIndexId(self.settingsViewModel.settings.plugins.enclosure.actions());

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
      var nextIndex = self.nextIndexId(self.settingsViewModel.settings.plugins.enclosure.automations());

      self.settingsViewModel.settings.plugins.enclosure.automations.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Automation " + nextIndex),
        enabled: ko.observable(true),
        show_in_tab: ko.observable(false),
        automation_type: ko.observable(""),
        trigger_type: ko.observable(""),
        input: ko.observable(""),
        edge: ko.observable("fall"),
        linked_temp_sensor: ko.observable(""),
        alarm_set_temp: ko.observable(""),
        repeat_while_above: ko.observable(false),
        octoprint_events: ko.observableArray([]),
        delay: ko.observable(0),
        at: ko.observable(""),
        conditions: ko.observableArray([]),
        reactions: ko.observableArray([self.newReaction()]),
        action: ko.observable(""),
        output: ko.observable(""),
        toggle_timer_on: ko.observable(0),
        toggle_timer_off: ko.observable(0),
        duty_cycle: ko.observable(0),
        color: ko.observable(""),
        target: ko.observable(null),
        temperature_a: ko.observable(0),
        duty_a: ko.observable(0),
        temperature_b: ko.observable(0),
        duty_b: ko.observable(0)
      });
    };

    self.removeAutomation = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.automations.remove(data);
    };

    self.ruleTimings = new WeakMap();

    self.ruleTiming = function (rule) {
      var timing = self.ruleTimings.get(rule);
      if (!timing) {
        timing = ko.observable(rule.at() !== "" ? "at" : parseFloat(rule.delay()) > 0 ? "delay" : "now");
        timing.subscribe(function (value) {
          if (value !== "delay") {
            rule.delay(0);
          }
          if (value !== "at") {
            rule.at("");
          }
        });
        self.ruleTimings.set(rule, timing);
      }
      return timing;
    };

    self.printingOptions = [
      {value: true, label: "Printing"},
      {value: false, label: "Not printing"}
    ];

    self.newCondition = function () {
      return {
        condition_type: ko.observable(""),
        printing: ko.observable(true)
      };
    };

    self.addCondition = function (automation) {
      automation.conditions.push(self.newCondition());
    };

    self.removeCondition = function (automation, condition) {
      automation.conditions.remove(condition);
    };

    self.newReaction = function () {
      return {
        reaction_type: ko.observable(""),
        controlled_io: ko.observable(""),
        controlled_io_set_state: ko.observable("on"),
        duty_cycle: ko.observable(0),
        color: ko.observable(""),
        target: ko.observable(null),
        action: ko.observable("")
      };
    };

    self.addReaction = function (automation) {
      automation.reactions.push(self.newReaction());
    };

    self.removeReaction = function (automation, reaction) {
      automation.reactions.remove(reaction);
    };

    self.setOutput = function (item, body) {
      return OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id()), body);
    };

    self.turnOffThermostat = function (item) {
      self.setOutput(item, {target: null});
    };

    self.toggleOutput = function (item) {
      self.setOutput(item, {on: !item.on()});
    };

    self.setDutyCycle = function (item) {
      var duty_cycle = parseInt(item.new_duty_cycle());

      if (isNaN(duty_cycle) || duty_cycle < 0 || duty_cycle > 100) {
        item.new_duty_cycle("");
        self.notify("Duty Cycle value needs to be between 0 and 100!", "error");
        return;
      }

      self.setOutput(item, {duty_cycle: duty_cycle}).done(function () {
        item.new_duty_cycle("");
      });
    };

    self.setColor = function (item) {
      self.setOutput(item, {color: item.shown_color()}).done(function () {
        item.new_color("");
      });
    };

    self.runAction = function (item) {
      OctoPrint.post(self.buildPluginUrl("actions/" + item.index_id() + "/run"));
    };

    self.switchAutomation = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("automations/" + item.index_id()), {enabled: !item.enabled()});
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
    dependencies: ["settingsViewModel", "loginStateViewModel", "accessViewModel", "printerStateViewModel"],
    elements: ["#tab_plugin_enclosure", "#tab_plugin_enclosure_link", "#settings_plugin_enclosure", "#navbar_plugin_enclosure_1", "#navbar_plugin_enclosure_2"]
  });

});
