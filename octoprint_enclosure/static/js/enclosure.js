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

    self.observableOf = function (value) {
      return Array.isArray(value) ? ko.observableArray(value.slice()) : ko.observable(value);
    };

    self.formFields = function (form) {
      var fields = [];
      var addField = function (field) {
        var isNew = fields.every(function (added) {
          return added.name !== field.name;
        });
        if (isNew) {
          fields.push(field);
        }
      };
      form.forEach(function (field) {
        addField({
          name: field.name,
          default: field.default,
          empty: field.empty,
          fields: field.list_item_form === undefined ? null : self.formFields(field.list_item_form),
        });
        (field.variants || []).forEach(function (variant) {
          self.formFields(variant.form).forEach(addField);
        });
      });
      return fields;
    };

    self.newItem = function (fields) {
      var item = {};
      fields.forEach(function (field) {
        item[field.name] = self.observableOf(field.default === null ? field.empty : field.default);
      });
      return item;
    };

    self.completeItems = function (fields, items) {
      items.forEach(function (item) {
        fields.forEach(function (field) {
          var isList = field.fields !== null;
          if (item[field.name] === undefined || (isList && !Array.isArray(ko.unwrap(item[field.name])))) {
            item[field.name] = self.observableOf(field.empty);
          }
          if (isList) {
            self.completeItems(field.fields, item[field.name]());
          }
        });
      });
    };

    self.completeSettings = function () {
      Object.keys(self.settingsFields).forEach(function (listName) {
        var items = self.settingsViewModel.settings.plugins.enclosure[listName]();
        self.completeItems(self.settingsFields[listName], items);
      });
    };

    self.onBeforeBinding = function () {
      var forms = JSON.parse($("#enclosure-settings-forms").text());
      self.settingsFields = {};
      Object.keys(forms).forEach(function (listName) {
        self.settingsFields[listName] = self.formFields(forms[listName]);
      });

      self.completeSettings();
      Object.keys(self.settingsFields).forEach(function (listName) {
        self.settingsViewModel.settings.plugins.enclosure[listName].subscribe(self.completeSettings);
      });

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

    self.addItem = function (listName, labelPrefix) {
      var items = self.settingsViewModel.settings.plugins.enclosure[listName];
      var item = self.newItem(self.settingsFields[listName]);
      item.index_id(self.nextIndexId(items()));
      item.label(labelPrefix + " " + item.index_id());
      items.push(item);
      return item;
    };

    self.addRpiInput = function () {
      self.addItem("rpi_inputs", "Input");
    };

    self.removeRpiInput = function (definition) {
      self.settingsViewModel.settings.plugins.enclosure.rpi_inputs.remove(definition);
    };

    self.addRpiOutput = function () {
      self.addItem("rpi_outputs", "Output");
    };

    self.removeRpiOutput = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.remove(data);
    };

    self.addAction = function () {
      self.addItem("actions", "Action");
    };

    self.removeAction = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.actions.remove(data);
    };

    self.addAutomation = function () {
      self.addNestedItem(self.addItem("automations", "Automation"), "reactions");
    };

    self.removeAutomation = function (data) {
      self.settingsViewModel.settings.plugins.enclosure.automations.remove(data);
    };

    self.addNestedItem = function (automation, listName) {
      var list = ko.utils.arrayFirst(self.settingsFields.automations, function (field) {
        return field.name === listName;
      });
      automation[listName].push(self.newItem(list.fields));
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
