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

  function EnclosureViewModel(parameters) {
    var self = this;

    self.pluginName = "enclosure";

    self.settingsViewModel = parameters[0];
    self.connectionViewModel = parameters[1];
    self.printerStateViewModel = parameters[2];

    self.rpi_outputs = ko.observableArray();
    self.rpi_inputs = ko.observableArray();

    self.settingsOpen = false;

    self.settings_outputs_regular = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs(), function (item) {
        return (item.output_type() === "regular" && !item.toggle_timer());
      });
    });

    self.settings_possible_outputs = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs(), function (item) {
        return ((item.output_type() === "regular" && !item.toggle_timer()) || item.output_type() === "gcode_output" || item.output_type() === "shell_output");
      });
    });

    self.rpi_inputs_temperature_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_inputs(), function (item) {
        return (item.input_type() === "temperature_sensor");
      });
    });

    self.navbar_outputs = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
        return (["regular", "gcode_output", "shell_output"].indexOf(item.output_type()) >= 0 && item.show_on_navbar());
      });
    });

    self.navbar_temperature_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_inputs_temperature_sensors(), function (item) {
        return (item.temp_sensor_navbar());
      });
    });

    self.tab_temperature_table_rows = ko.pureComputed(function () {
      var rows = [];
      self.rpi_inputs_temperature_sensors().forEach(function (sensor) {
        var controls = self.linkedTemperatureControl(sensor.index_id())();
        var rowspan = Math.max(controls.length, 1);
        if (controls.length === 0) {
          rows.push({sensor: sensor, control: null, first: true, rowspan: rowspan});
        }
        controls.forEach(function (control, index) {
          rows.push({sensor: sensor, control: control, first: index === 0, rowspan: rowspan});
        });
      });
      return rows;
    });

    self.tab_outputs = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_outputs(), function (item) {
        return (!item.hide_btn_ui());
      });
    });

    self.tab_filament_sensors = ko.pureComputed(function () {
      return ko.utils.arrayFilter(self.rpi_inputs(), function (item) {
        return (item.input_type() === "gpio" && item.action_type() === "printer_control" && item.printer_action() === "filament");
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

    self.use_sudo = ko.observable();
    self.gcode_control = ko.observable();
    self.neopixel_dma = ko.observable();
    self.debug = ko.observable();
    self.debug_temperature_log = ko.observable();
    self.use_board_pin_number = ko.observable();
    self.filament_sensor_gcode = ko.observable();
    self.notification_provider = ko.observable();
    self.notification_event_name = ko.observable();
    self.notification_api_key = ko.observable();
    self.notifications = ko.observableArray([]);

    self.humidityCapableSensor = function(sensor){
      if (['11', '20', '22', '2302', 'bme280', 'bme680', 'am2320', 'aht10' , 'si7021', 'hum_raw_i2c', 'temp_raw_i2c'].indexOf(sensor) >= 0){
        return true;
      }
      return false;
    };

    self.isRegularOutput = function(index_id){
      return_value = false;
      if (typeof index_id != 'undefined'){
        self.settingsViewModel.settings.plugins.enclosure.rpi_outputs().forEach(function (output) {
          if (output.index_id() == index_id && output.output_type() == "regular") {
            return_value = true;
            return false;
          }
        });
      }
      return return_value;
    };

    self.linkedTemperatureControl = function(sensor_index){
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

    self.hasAnySensorWithHumidity = function(){
      return_value = false;
      self.rpi_inputs_temperature_sensors().forEach(function (sensor) {
        if (self.humidityCapableSensor(sensor.temp_sensor_type())) {
          return_value = true;
          return false;
        }
      });
      return return_value;
    };

    self.hasAnyTemperatureControl = function(){
      return_value = false
      self.rpi_outputs().forEach(function (output) {
        if (output.output_type()=="temp_hum_control") {
          return_value = true
          return false;
        }
      });
      return return_value;
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
            linked_temp_sensor.temp_sensor_temp(sensor_data['temperature'])
            linked_temp_sensor.temp_sensor_humidity(sensor_data['humidity'])
          }
        })
      }

      if (data.hasOwnProperty("set_temperature")) {
        data.set_temperature.forEach(function (set_temperature) {
          var linked_temp_control = ko.utils.arrayFilter(self.rpi_outputs(), function (temp_control) {
            return (set_temperature['index_id'] == temp_control.index_id());
          }).pop();
          if (linked_temp_control) {
            linked_temp_control.temp_ctr_set_value(set_temperature['set_temperature'])
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

      if (data.hasOwnProperty("rpi_output_temp_hum_ctrl")) {
        data.rpi_output_temp_hum_ctrl.forEach(function (output) {
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
          var linked_filament_sensor = ko.utils.arrayFilter(self.rpi_inputs(), function (item) {
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
          text: data.msg,
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

    self.bindFromSettings = function(){
      self.rpi_outputs(self.settingsViewModel.settings.plugins.enclosure.rpi_outputs());
      self.rpi_inputs(self.settingsViewModel.settings.plugins.enclosure.rpi_inputs());
      self.use_sudo(self.settingsViewModel.settings.plugins.enclosure.use_sudo());
      self.gcode_control(self.settingsViewModel.settings.plugins.enclosure.gcode_control());
      self.neopixel_dma(self.settingsViewModel.settings.plugins.enclosure.neopixel_dma());
      self.debug(self.settingsViewModel.settings.plugins.enclosure.debug());
      self.debug_temperature_log(self.settingsViewModel.settings.plugins.enclosure.debug_temperature_log());
      self.use_board_pin_number(self.settingsViewModel.settings.plugins.enclosure.use_board_pin_number());
      self.filament_sensor_gcode(self.settingsViewModel.settings.plugins.enclosure.filament_sensor_gcode());
      self.notification_provider(self.settingsViewModel.settings.plugins.enclosure.notification_provider());
      self.notification_event_name(self.settingsViewModel.settings.plugins.enclosure.notification_event_name());
      self.notification_api_key(self.settingsViewModel.settings.plugins.enclosure.notification_api_key());
      self.notifications(self.settingsViewModel.settings.plugins.enclosure.notifications());
    };

    self.onBeforeBinding = function () {
      self.bindFromSettings();
    };

    self.onSettingsBeforeSave = function() {
      self.bindFromSettings();
    };

    self.onStartupComplete = function () {
      self.settingsOpen = false;
    };

    self.onSettingsShown = function () {
      self.settingsOpen = true;
    };

    self.onSettingsHidden = function () {
      self.settingsOpen = false;
    };

    self.getRegularOutputs = function () {
      return self.rpi_outputs().filter(function (rpi_outputs) {
        return rpi_outputs.output_type == 'regular';
      });
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
            item.temp_ctr_set_value(newSetTemperature);
            self.getUpdateUI();
          })
          .fail(function () {
            new PNotify({
              title: "Enclosure",
              text: "Error setting temperature",
              type: "error"
            });
          });
      }else{
        new PNotify({
          title: "Enclosure",
          text: "Invalid set temperature",
          type: "error"
        });
      }
    };

    self.addRpiOutput = function () {

      var arrRelaysLength = self.settingsViewModel.settings.plugins.enclosure.rpi_outputs().length;

      var nextIndex = arrRelaysLength == 0 ? 1 : self.settingsViewModel.settings.plugins.enclosure.rpi_outputs()[arrRelaysLength - 1].index_id() + 1;

      self.settingsViewModel.settings.plugins.enclosure.rpi_outputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Output " + nextIndex),
        output_type: ko.observable("regular"),
        shell_script: ko.observable(""),
        gpio_pin: ko.observable(0),
        gpio_status: ko.observable(false),
        hide_btn_ui: ko.observable(false),
        active_low: ko.observable(true),
        pwm_temperature_linked: ko.observable(false),
        toggle_timer: ko.observable(false),
        toggle_timer_on: ko.observable(0),
        toggle_timer_off: ko.observable(0),
        startup_with_server: ko.observable(false),
        auto_startup: ko.observable(false),
        controlled_io: ko.observable(0),
        controlled_io_set_value: ko.observable("Low"),
        startup_time: ko.observable(0),
        auto_shutdown: ko.observable(false),
        shutdown_on_failed: ko.observable(false),
        shutdown_time: ko.observable(0),
        linked_temp_sensor: ko.observable(""),
        alarm_set_temp: ko.observable(0),
        temp_ctr_type: ko.observable("heater"),
        temp_ctr_deadband: ko.observable(0),
        temp_ctr_set_value: ko.observable(0),
        temp_ctr_new_set_value: ko.observable(""),
        temp_ctr_default_value: ko.observable(0),
        temp_ctr_max_temp: ko.observable(0),
        pwm_frequency: ko.observable(50),
        pwm_status: ko.observable(50),
        duty_cycle: ko.observable(0),
        duty_a: ko.observable(0),
        duty_b: ko.observable(0),
        temperature_a: ko.observable(0),
        temperature_b: ko.observable(0),
        default_duty_cycle: ko.observable(0),
        new_duty_cycle: ko.observable(""),
        neopixel_color: ko.observable("rgb(0,0,0)"),
        default_neopixel_color: ko.observable(""),
        new_neopixel_color: ko.observable(""),
        neopixel_count: ko.observable(0),
        neopixel_brightness: ko.observable(255),
        ledstrip_color: ko.observable("rgb(0,0,0)"),
        default_ledstrip_color: ko.observable(""),
        new_ledstrip_color: ko.observable(""),
        ledstrip_gpio_clk: ko.observable(""),
        ledstrip_gpio_dat: ko.observable(""),
        microcontroller_address: ko.observable(0),
        gcode: ko.observable(""),
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

    self.addRpiInput = function () {

      var arrRelaysLength = self.settingsViewModel.settings.plugins.enclosure.rpi_inputs().length;

      var nextIndex = arrRelaysLength == 0 ? 1 : self.settingsViewModel.settings.plugins.enclosure.rpi_inputs()[arrRelaysLength - 1].index_id() + 1;

      self.settingsViewModel.settings.plugins.enclosure.rpi_inputs.push({
        index_id: ko.observable(nextIndex),
        label: ko.observable("Input " + nextIndex),
        input_type: ko.observable("gpio"),
        gpio_pin: ko.observable(0),
        input_pull_resistor: ko.observable("input_pull_up"),
        temp_sensor_type: ko.observable("DS18B20"),
        temp_sensor_address: ko.observable(""),
        temp_sensor_temp: ko.observable(""),
        temp_sensor_humidity: ko.observable(""),
        ds18b20_serial: ko.observable(""),
        use_fahrenheit: ko.observable(false),
        action_type: ko.observable("output_control"),
        controlled_io: ko.observable(""),
        controlled_io_set_value: ko.observable("low"),
        edge: ko.observable("fall"),
        printer_action: ko.observable("filament"),
        temp_sensor_navbar: ko.observable(true),
        filament_sensor_timeout: ko.observable(120),
        filament_sensor_enabled: ko.observable(true),
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

    self.turnOffHeater = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("temperature/" + item.index_id()), {temperature: 0})
        .done(function () {
          self.getUpdateUI();
        });
    };

    self.clearGPIOMode = function () {
      OctoPrint.post(self.buildPluginUrl("clear-gpio"))
        .done(function () {
          new PNotify({
            title: "Enclosure",
            text: "GPIO Mode cleared successfully",
            type: "success"
          });
        });
    };

    self.getUpdateUI = function () {
      OctoPrint.post(self.buildPluginUrl("update"));
    };

    self.handleIO = function (item, form) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id()), {status: !item.gpio_status()})
        .done(function () {
          self.getUpdateUI();
        });
    };

    self.handleGcode = function (item, form) {
      OctoPrint.post(self.buildPluginUrl("gcode/" + item.index_id()));
    };

    self.handleShellOutput = function (item, form) {
      OctoPrint.post(self.buildPluginUrl("shell/" + item.index_id()));
    };

    self.switchAutoStartUp = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id() + "/auto-startup"), {status: !item.auto_startup()})
        .done(function () {
          self.getUpdateUI();
        });
    };

    self.switchAutoShutdown = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("outputs/" + item.index_id() + "/auto-shutdown"), {status: !item.auto_shutdown()})
        .done(function () {
          self.getUpdateUI();
        });
    };

    self.switchFilamentSensor = function (item) {
      OctoPrint.patchJson(self.buildPluginUrl("filament/" + item.index_id()), {status: !item.filament_sensor_enabled()})
        .done(function () {
          self.getUpdateUI();
        });
    };

    self.handlePWM = function (item) {
      var pwm_value = item.new_duty_cycle();

      pwm_value = parseInt(pwm_value);

      if (pwm_value < 0 || pwm_value > 100 || isNaN(pwm_value)) {
        item.new_duty_cycle("")
        new PNotify({
          title: "Enclosure",
          text: "Duty Cycle value needs to be between 0 and 100!",
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("pwm/" + item.index_id()), {duty_cycle: pwm_value})
          .done(function () {
            item.new_duty_cycle("");
            item.duty_cycle(pwm_value);
            self.getUpdateUI();
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
          text: "Color needs to follow the format rgb(value_red,value_green,value_blue)!",
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("neopixel/" + index), {red: r, green: g, blue: b})
          .done(function () {
            item.new_neopixel_color("");
            self.getUpdateUI();
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
          text: "Color needs to follow the format rgb(value_red,value_green,value_blue)!",
          type: "error"
        });
      } else {
        OctoPrint.patchJson(self.buildPluginUrl("rgb-led/" + index), {rgb: or_tempStr})
          .done(function () {
            item.new_ledstrip_color("");
            self.getUpdateUI();
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
