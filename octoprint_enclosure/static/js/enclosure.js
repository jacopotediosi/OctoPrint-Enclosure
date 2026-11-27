/* global $, _, gettext, ko, OctoPrint, OCTOPRINT_VIEWMODELS, PNotify, showConfirmationDialog */

$(function () {
  // ##########
  // ### Knockout bindings
  // ##########

  /**
   * Shows a temperature saved in Celsius in the unit chosen in the settings, and saves what is typed back in Celsius.
   * With `temperatureInterval: true` the value is a difference between two temperatures, e.g. a deadband.
   */
  ko.bindingHandlers.temperature = {
    init: function (element, valueAccessor, allBindings, viewModel, bindingContext) {
      ko.utils.registerEventHandler(element, 'change', function () {
        const value = parseFloat(element.value)
        valueAccessor()(isNaN(value) ? null : bindingContext.$root.toCelsius(value, allBindings.get('temperatureInterval')))
      })
    },
    update: function (element, valueAccessor, allBindings, viewModel, bindingContext) {
      const value = parseFloat(ko.unwrap(valueAccessor()))
      element.value = isNaN(value) ? '' : bindingContext.$root.fromCelsius(value, allBindings.get('temperatureInterval'))
    }
  }

  /**
   * Shows the placeholder of a select, its first option, when the saved value is not one of its options.
   */
  ko.bindingHandlers.placeholderWhenUnset = {
    after: ['options', 'value'],
    update: function (element, valueAccessor, allBindings) {
      ko.unwrap(allBindings.get('value'))
      ko.unwrap(allBindings.get('options'))
      setTimeout(function () {
        if (element.selectedIndex === -1) {
          element.selectedIndex = 0
        }
      }, 0)
    }
  }

  /**
   * Selects several of `choices` into `selected`, with a text field that suggests the choices not selected yet.
   */
  ko.bindingHandlers.multiselect = {
    init: function (element, valueAccessor) {
      // Get selected, unselected, and all choices
      const selected = valueAccessor().selected
      const choices = valueAccessor().choices
      const unselectedChoices = function () {
        return choices.filter(function (choice) {
          return selected.indexOf(choice) < 0
        })
      }

      // Create Bootstrap's typeahead: it suggests the unselected choices that contain what is typed, and selects the one picked
      $(element).typeahead({
        source: unselectedChoices,
        items: choices.length,
        matcher: function (choice) {
          return choice.toLowerCase().indexOf(this.query.toLowerCase()) >= 0
        },
        highlighter: function (choice) {
          return this.query ? $.fn.typeahead.Constructor.prototype.highlighter.call(this, choice) : choice
        },
        updater: function (choice) {
          selected.push(choice)
          return ''
        }
      })
      const typeahead = $(element).data('typeahead')

      // Bootstrap's typeahead shows nothing for an empty field: give it every unselected choice, filtered by what is
      // typed
      $(element).on('click', function () {
        typeahead.query = element.value
        typeahead.process(unselectedChoices())
      })

      // Bootstrap's typeahead opens below the field: scroll the box that scrolls the field, if needed, so that the whole
      // menu is visible
      const show = typeahead.show
      typeahead.show = function () {
        show.call(this)
        let box = element.parentElement
        while (box && !/auto|scroll/.test(window.getComputedStyle(box).overflowY)) {
          box = box.parentElement
        }
        if (box) {
          const hiddenHeight = this.$menu[0].getBoundingClientRect().bottom - box.getBoundingClientRect().bottom
          box.scrollTop += Math.max(hiddenHeight, 0)
        }
        return this
      }

      // Close the menu when the field leaves the visible part of the page
      const observer = new window.IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting) {
          typeahead.hide()
        }
      })
      observer.observe(element)
      ko.utils.domNodeDisposal.addDisposeCallback(element, function () {
        observer.disconnect()
      })
    }
  }

  // ##########
  // ### View model
  // ##########

  function EnclosureViewModel (parameters) {
    const self = this

    // ##########
    // ### Dependencies and state
    // ##########

    // OctoPrint view models
    self.settingsViewModel = parameters[0]
    self.loginStateViewModel = parameters[1]
    self.accessViewModel = parameters[2]
    self.printerStateViewModel = parameters[3]

    // Items shown in the tab and in the navbar
    self.inputs = ko.observableArray()
    self.outputs = ko.observableArray()
    self.actions = ko.observableArray()
    self.automations = ko.observableArray()

    // Whether the settings dialog is open
    self.isSettingsOpen = false

    // Items of the settings lists whose card is open
    self.openItems = ko.observableArray()

    // Runtime state of inputs and outputs, by id
    self.inputStates = {}
    self.outputStates = {}

    // Number of frontend pushes received, by kind of state
    self.pushCounts = { inputs: 0, outputs: 0, automations: 0 }

    // Fields that the items of each settings list have, as the backend describes them
    self.settingsFields = {}

    // The settings forms as the backend describes them, by their path in the forms, e.g.
    // "automations.automation_type=rule.reactions[]" for the form of an automation rule reaction
    self.settingsFormsByPath = {}

    // The name of each settings item that is not valid
    self.invalidSettingsItemNames = ko.observable([])

    // Types of sensor that read each kind of measurement, as the backend declares them
    self.sensorTypesByMeasurementType = {}

    // Temperature units by name, each with its symbol and how it converts from Celsius, as the backend declares them
    self.temperatureUnits = {}

    // ##########
    // ### Helpers
    // ##########

    self.pluginSettings = function () {
      return self.settingsViewModel.settings.plugins.enclosure
    }

    self.buildPluginUrl = function (path) {
      return OctoPrint.getBlueprintUrl('enclosure') + path
    }

    self.notify = function (text, type, options) {
      // eslint-disable-next-line no-new
      new PNotify($.extend({
        title: 'Enclosure',
        title_escape: true,
        text,
        text_escape: true,
        type
      }, options))
    }

    self.notifyRequestError = function (response) {
      const errors = (response.responseJSON && response.responseJSON.errors) || [gettext('The request failed.')]
      self.notify(errors.join(' '), 'error')
    }

    self.isSameId = function (firstId, secondId) {
      return String(firstId) === String(secondId)
    }

    // ##########
    // ### Permissions
    // ##########

    self.hasPluginPermissionKo = function (key) {
      return ko.pureComputed(function () {
        return self.loginStateViewModel.hasPermission(self.accessViewModel.permissions['PLUGIN_ENCLOSURE_' + key])
      })
    }

    self.hasStatusPermission = self.hasPluginPermissionKo('STATUS')
    self.hasOutputsControlPermission = self.hasPluginPermissionKo('OUTPUTS_CONTROL')
    self.hasActionsRunPermission = self.hasPluginPermissionKo('ACTIONS_RUN')
    self.hasAutomationsEnablePermission = self.hasPluginPermissionKo('AUTOMATIONS_ENABLE')

    self.canSendGcode = ko.pureComputed(function () {
      return self.hasActionsRunPermission() && self.printerStateViewModel.isOperational()
    })

    // ##########
    // ### Temperatures
    // ##########

    self.temperatureUnit = ko.pureComputed(function () {
      return self.temperatureUnits[self.pluginSettings().temperature_unit()] || self.temperatureUnits.celsius
    })

    self.temperatureUnitSymbol = ko.pureComputed(function () {
      return self.temperatureUnit().symbol
    })

    self.fromCelsius = function (celsius, isInterval) {
      const unit = self.temperatureUnit()
      if (celsius === null || unit === self.temperatureUnits.celsius) return celsius
      return Math.round((celsius * unit.scale + (isInterval ? 0 : unit.offset)) * 10) / 10
    }

    self.toCelsius = function (temperature, isInterval) {
      const unit = self.temperatureUnit()
      if (unit === self.temperatureUnits.celsius) return temperature
      return Math.round((temperature - (isInterval ? 0 : unit.offset)) / unit.scale * 100) / 100
    }

    // ##########
    // ### Settings forms
    // ##########

    self.formFields = function (form) {
      const fields = []
      const addField = function (field) {
        const isNew = fields.every(function (added) {
          return added.name !== field.name
        })
        if (isNew) {
          fields.push(field)
        }
      }
      form.forEach(function (field) {
        addField({
          name: field.name,
          default: field.default,
          empty: field.empty,
          fields: field.list_item_form === undefined ? null : self.formFields(field.list_item_form)
        });
        (field.variants || []).forEach(function (variant) {
          self.formFields(variant.form).forEach(addField)
        })
      })
      return fields
    }

    self.newItem = function (fields) {
      const item = {}
      fields.forEach(function (field) {
        item[field.name] = ko.mapping.fromJS(field.default === null ? field.empty : field.default)
      })
      return item
    }

    self.addMissingKeys = function (fields, items) {
      items.forEach(function (item) {
        fields.forEach(function (field) {
          const isList = field.fields !== null
          if (item[field.name] === undefined || (isList && !Array.isArray(ko.unwrap(item[field.name])))) {
            item[field.name] = ko.mapping.fromJS(field.empty)
          }
          if (isList) {
            self.addMissingKeys(field.fields, item[field.name]())
          }
        })
      })
    }

    self.addMissingKeysToSettings = function () {
      Object.keys(self.settingsFields).forEach(function (listName) {
        const items = self.pluginSettings()[listName]()
        self.addMissingKeys(self.settingsFields[listName], items)
      })
    }

    self.nextIndexId = function (items) {
      const indexes = items.map(function (item) {
        return parseInt(item.index_id(), 10) || 0
      })
      return indexes.length === 0 ? 1 : Math.max.apply(null, indexes) + 1
    }

    self.addItem = function (listName, labelPrefix) {
      const items = self.pluginSettings()[listName]
      const item = self.newItem(self.settingsFields[listName])
      item.index_id(self.nextIndexId(items()))
      item.label(labelPrefix + ' ' + item.index_id())
      self.openItems.push(item)
      items.push(item)
      return item
    }

    self.removeItem = function (listName, item) {
      showConfirmationDialog({
        message: _.sprintf(gettext('"%(label)s" will be removed.'), { label: _.escape(item.label()) }),
        proceed: gettext('Remove'),
        onproceed: function () {
          self.pluginSettings()[listName].remove(item)
          self.openItems.remove(item)
        }
      })
    }

    self.isItemOpen = function (item) {
      return self.openItems.indexOf(item) >= 0
    }

    self.toggleItem = function (item) {
      if (self.isItemOpen(item)) {
        self.openItems.remove(item)
      } else {
        self.openItems.push(item)
      }
    }

    self.addAutomation = function () {
      self.addNestedItem(self.addItem('automations', gettext('Automation')), 'reactions')
    }

    self.addNestedItem = function (automation, listName) {
      const list = ko.utils.arrayFirst(self.settingsFields.automations, function (field) {
        return field.name === listName
      })
      automation[listName].push(self.newItem(list.fields))
    }

    self.settingsGpioInputs = ko.pureComputed(function () {
      return self.pluginSettings().rpi_inputs().filter(function (item) {
        return item.input_type() === 'gpio'
      })
    })

    self.settingsTemperatureSensors = ko.pureComputed(function () {
      return self.pluginSettings().rpi_inputs().filter(function (item) {
        return item.input_type() === 'temperature_sensor'
      })
    })

    self.settingsHumiditySensors = ko.pureComputed(function () {
      return self.settingsTemperatureSensors().filter(function (sensor) {
        return self.measuresHumidity(sensor.temp_sensor_type())
      })
    })

    self.measuresHumidity = function (sensorType) {
      return self.sensorTypesByMeasurementType.humidity.indexOf(sensorType) >= 0
    }

    self.disablePlaceholderOption = function (option, item) {
      if (item === undefined) {
        option.disabled = true
      }
    }

    self.settingsPwmOutputs = ko.pureComputed(function () {
      return self.pluginSettings().rpi_outputs().filter(function (item) {
        return item.output_type() === 'pwm'
      })
    })

    self.findSettingsOutput = function (outputId) {
      return ko.utils.arrayFirst(self.pluginSettings().rpi_outputs(), function (output) {
        return self.isSameId(output.index_id(), outputId)
      })
    }

    self.registerSettingsForms = function (form, formPath) {
      // Register the form
      self.settingsFormsByPath[formPath] = form

      // Register the forms that its fields contain
      form.forEach(function (field) {
        const fieldPath = formPath + '.' + field.name

        // Register the form of the items of a list
        if (field.list_item_form !== undefined) {
          self.registerSettingsForms(field.list_item_form, fieldPath + '[]')
        }

        // Register the form that each choice of a field shows
        ;(field.variants || []).forEach(function (variant) {
          self.registerSettingsForms(variant.form, fieldPath + '=' + variant.value)
        })
      })
    }

    self.findSettingsField = function (fieldPath) {
      const formPath = fieldPath.slice(0, fieldPath.lastIndexOf('.'))
      const fieldName = fieldPath.slice(fieldPath.lastIndexOf('.') + 1)
      return self.settingsFormsByPath[formPath].filter(function (field) {
        return field.name === fieldName
      })[0]
    }

    self.linkableSettingsItems = function (fieldPath, item) {
      const field = self.findSettingsField(fieldPath)

      // Give the sensors that read what the device of a thermostat acts on, for the sensor of the thermostat
      if (field.widget === 'thermostat_sensor') {
        const deviceType = ko.unwrap(item[field.device_type_field])
        const deviceTypes = field.device_types_by_measurement_type
        if (deviceTypes.humidity.indexOf(deviceType) >= 0) return self.settingsHumiditySensors()
        return deviceTypes.temperature.indexOf(deviceType) >= 0 ? self.settingsTemperatureSensors() : []
      }

      // Give the PWM outputs, for the output of a PWM curve
      if (field.widget === 'pwm_output') return self.settingsPwmOutputs()

      // Give the items of the kind of the link, for any other link
      return {
        SensorInputId: self.settingsTemperatureSensors,
        GpioInputId: self.settingsGpioInputs,
        OutputId: self.pluginSettings().rpi_outputs,
        ActionId: self.pluginSettings().actions
      }[field.type]()
    }

    self.outputType = function (outputId) {
      const output = self.findSettingsOutput(outputId)
      return output ? output.output_type() : ''
    }

    self.thermostatDeviceType = function (outputId) {
      const output = self.findSettingsOutput(outputId)
      return output ? output.temp_ctr_type() : ''
    }

    // ##########
    // ### Invalid settings
    // ##########

    self.isSettingsFieldUsed = function (field, item) {
      const visibleIf = field.visible_if || {}
      const visibleIfOutputType = field.visible_if_output_type || {}
      return Object.keys(visibleIf).every(function (name) {
        return visibleIf[name].indexOf(ko.unwrap(item[name])) >= 0
      }) && Object.keys(visibleIfOutputType).every(function (name) {
        return visibleIfOutputType[name].indexOf(self.outputType(ko.unwrap(item[name]))) >= 0
      })
    }

    self.settingsFieldProblem = function (fieldPath, item) {
      const field = self.findSettingsField(fieldPath)

      // If the field is not used, there cannot be any problems
      if (!self.isSettingsFieldUsed(field, item)) return ''

      // Check that the field is set, unless it is optional
      const value = ko.unwrap(item[field.name])
      if (value === '' || value === null || value === undefined || (Array.isArray(value) && value.length === 0)) {
        return field.optional ? '' : gettext('Cannot be empty.')
      }

      // Check the type, the linked item and the choices
      const text = String(value).trim()
      const number = field.type === 'HexInt' ? parseInt(text, 16) : Number(text)
      const isNumberText = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(text)
      const isNotOfType = {
        int: !isNumberText || !Number.isInteger(number),
        float: !isNumberText || !isFinite(number),
        HexInt: !/^(0x)?[0-9a-f]+$/i.test(text),
        Rgb: !/^#[0-9a-f]{6}$/i.test(text),
        TimeOfDay: !/^([01]?\d|2[0-3]):[0-5]?\d$/.test(text)
      }
      const typeProblems = {
        int: gettext('Must be a whole number.'),
        float: gettext('Must be a number.'),
        HexInt: gettext('Must be a hexadecimal number.'),
        Rgb: gettext('Must be a color.'),
        TimeOfDay: gettext('Must be a time of day.')
      }
      if (isNotOfType[field.type]) return typeProblems[field.type]
      if (['SensorInputId', 'GpioInputId', 'OutputId', 'ActionId'].indexOf(field.type) >= 0) {
        const isLinked = self.linkableSettingsItems(fieldPath, item).some(function (linkable) {
          return self.isSameId(linkable.index_id(), value)
        })
        return isLinked ? '' : gettext('Must be one of the choices.')
      }
      if (field.choices && !field.choices.some(function (choice) { return String(choice[0]) === text })) {
        return gettext('Must be one of the choices.')
      }

      // Check the limits
      const isTemperature = ['temperature', 'temperature_interval'].indexOf(field.widget) >= 0
      const shownLimit = function (limit) {
        if (!isTemperature) return limit
        return self.fromCelsius(limit, field.widget === 'temperature_interval') + ' ' + self.temperatureUnitSymbol()
      }
      if (field.min_value !== null && number < field.min_value) {
        return _.sprintf(gettext('Must be at least %(limit)s.'), { limit: shownLimit(field.min_value) })
      }
      if (field.max_value !== null && number > field.max_value) {
        return _.sprintf(gettext('Must be at most %(limit)s.'), { limit: shownLimit(field.max_value) })
      }
      return ''
    }

    self.isSettingsInvalid = function (formPath, item) {
      // Check each field of the form, and the forms it contains
      return self.settingsFormsByPath[formPath].some(function (field) {
        const fieldPath = formPath + '.' + field.name

        // Check the settings of each item of a list
        if (field.list_item_form !== undefined) {
          return item[field.name]().some(function (listItem) {
            return self.isSettingsInvalid(fieldPath + '[]', listItem)
          })
        }

        // Check any other field, and the form it shows for the value chosen, if it has choices
        const variant = (field.variants || []).filter(function (variant) {
          return String(variant.value) === String(ko.unwrap(item[field.name]))
        })[0]
        return self.settingsFieldProblem(fieldPath, item) !== '' ||
          (variant !== undefined && self.isSettingsInvalid(fieldPath + '=' + variant.value, item))
      })
    }

    self.reportInvalidSettingsItems = function () {
      // Find the items that are not valid, in every settings list, by their kind and id
      const kindByListName = {
        rpi_inputs: gettext('Input'),
        rpi_outputs: gettext('Output'),
        actions: gettext('Action'),
        automations: gettext('Automation')
      }
      const names = []
      Object.keys(kindByListName).forEach(function (listName) {
        self.pluginSettings()[listName]().forEach(function (item) {
          if (self.isSettingsInvalid(listName, item)) {
            names.push(kindByListName[listName] + ' ' + ko.unwrap(item.index_id))
          }
        })
      })
      self.invalidSettingsItemNames(names)

      // Notify the user
      const invalidSettingsAlert = $('#enclosure-invalid-settings-alert')
      if (names.length && invalidSettingsAlert.length) {
        self.notify(invalidSettingsAlert.text(), 'error', { hide: false })
      }
    }

    // ##########
    // ### Runtime state
    // ##########

    self.newInputState = function () {
      return {
        temperature: ko.observable(null),
        humidity: ko.observable(null)
      }
    }

    self.newOutputState = function () {
      const state = {
        on: ko.observable(false),
        duty_cycle: ko.observable(0),
        typed_duty_cycle: ko.observable(''),
        color: ko.observable('#000000'),
        typed_color: ko.observable(''),
        target: ko.observable(null),
        typed_target: ko.observable(''),
        measurement: ko.observable(null)
      }
      state.shown_color = ko.pureComputed({
        read: function () {
          return state.typed_color() || state.color()
        },
        write: state.typed_color
      })
      return state
    }

    self.attachStates = function (items, states, newState) {
      const kept = {}
      const wrapped = items.map(function (item) {
        const indexId = item.index_id()
        kept[indexId] = states[indexId] || newState()
        return $.extend({}, item, kept[indexId])
      })
      return { states: kept, items: wrapped }
    }

    self.loadItemsFromSettings = function () {
      const settings = self.pluginSettings()
      const inputs = self.attachStates(settings.rpi_inputs(), self.inputStates, self.newInputState)
      const outputs = self.attachStates(settings.rpi_outputs(), self.outputStates, self.newOutputState)
      self.inputStates = inputs.states
      self.outputStates = outputs.states
      self.inputs(inputs.items)
      self.outputs(outputs.items)
      self.actions(settings.actions())
      self.automations(settings.automations())
    }

    self.applyState = function (data) {
      const states = { inputs: self.inputStates, outputs: self.outputStates, automations: {} }
      self.automations().forEach(function (automation) {
        states.automations[automation.index_id()] = { enabled: automation.enabled }
      })

      Object.keys(states).forEach(function (kind) {
        (data[kind] || []).forEach(function (item) {
          const state = states[kind][item.id] || {}
          Object.keys(state).forEach(function (key) {
            if (Object.prototype.hasOwnProperty.call(item, key)) {
              state[key](item[key])
            }
          })
        })
      })
    }

    self.refreshState = function () {
      if (!self.hasStatusPermission()) {
        return
      }

      Object.keys(self.pushCounts).forEach(function (kind) {
        const pushCount = self.pushCounts[kind]
        OctoPrint.get(self.buildPluginUrl(kind)).done(function (items) {
          if (self.isSettingsOpen || self.pushCounts[kind] !== pushCount) {
            return
          }
          const data = {}
          data[kind] = items
          self.applyState(data)
        })
      })
    }

    // ##########
    // ### Tab and navbar
    // ##########

    self.temperatureSensors = ko.pureComputed(function () {
      return self.inputs().filter(function (item) {
        return item.input_type() === 'temperature_sensor'
      })
    })

    self.navbarTemperatureSensors = ko.pureComputed(function () {
      return self.temperatureSensors().filter(function (item) {
        return item.temp_sensor_navbar()
      })
    })

    self.navbarItems = ko.pureComputed(function () {
      const outputs = self.outputs().filter(function (item) {
        return item.output_type() === 'regular' && item.show_on_navbar()
      })
      const actions = self.actions().filter(function (item) {
        return item.action_type() !== '' && item.show_on_navbar()
      })
      return outputs.concat(actions)
    })

    self.navbarItemType = function (item) {
      return ko.unwrap(item.output_type || item.action_type)
    }

    self.tabTemperatureTableRows = ko.pureComputed(function () {
      const rows = []
      self.temperatureSensors().forEach(function (sensor) {
        const thermostats = self.linkedThermostats(sensor.index_id());
        (thermostats.length ? thermostats : [null]).forEach(function (thermostat, index) {
          rows.push({ sensor, thermostat, first: index === 0, rowspan: Math.max(thermostats.length, 1) })
        })
      })
      return rows
    })

    self.tabOutputs = ko.pureComputed(function () {
      return self.outputs().filter(function (item) {
        return item.output_type() !== '' && !item.hide_btn_ui()
      })
    })

    self.tabActions = ko.pureComputed(function () {
      return self.actions().filter(function (item) {
        return item.action_type() !== '' && !item.hide_btn_ui()
      })
    })

    self.tabFilamentSensors = ko.pureComputed(function () {
      return self.automations().filter(function (item) {
        return item.automation_type() === 'filament' && item.input() !== '' && item.show_in_tab()
      })
    })

    self.tabAutomations = ko.pureComputed(function () {
      return self.automations().filter(function (item) {
        return item.show_in_tab() && item.automation_type() !== 'filament' && self.controlledOutputIds(item).length !== 1
      })
    })

    self.hasActiveTemperatureCurve = function (outputId) {
      return self.automations().some(function (automation) {
        return automation.automation_type() === 'pwm_temperature_linked' && self.isSameId(automation.output(), outputId) && automation.enabled()
      })
    }

    self.isTurnedOffAtPrintEnd = function (outputId) {
      return self.automations().some(function (automation) {
        return automation.automation_type() === 'rule' && automation.enabled() && automation.trigger_type() === 'octoprint_event' &&
          automation.octoprint_events().indexOf('PrintDone') >= 0 &&
          automation.reactions().some(function (reaction) {
            return reaction.reaction_type() === 'output_control' && self.isSameId(reaction.controlled_io(), outputId) &&
              reaction.controlled_io_set_state() === 'off'
          })
      })
    }

    self.controlledOutputIds = function (automation) {
      let outputIds = []
      if (automation.automation_type() === 'pwm_temperature_linked' || automation.automation_type() === 'toggle_timer') {
        outputIds = [automation.output()]
      } else if (automation.automation_type() === 'rule') {
        outputIds = automation.reactions().filter(function (reaction) {
          return reaction.reaction_type() === 'output_control'
        }).map(function (reaction) {
          return reaction.controlled_io()
        })
      }
      return outputIds.filter(function (outputId, index) {
        return outputIds.indexOf(outputId) === index && self.outputs().some(function (output) {
          return self.isSameId(output.index_id(), outputId)
        })
      })
    }

    self.tabAutomationsOfOutput = function (outputId) {
      return self.automations().filter(function (automation) {
        const outputIds = self.controlledOutputIds(automation)
        return automation.show_in_tab() && outputIds.length === 1 && self.isSameId(outputIds[0], outputId)
      })
    }

    self.linkedThermostats = function (sensorId) {
      return self.outputs().filter(function (item) {
        return self.isSameId(item.linked_temp_sensor(), sensorId) && item.output_type() === 'temp_hum_control'
      })
    }

    self.hasAnySensorWithHumidity = function () {
      return self.temperatureSensors().some(function (sensor) {
        return self.measuresHumidity(sensor.temp_sensor_type())
      })
    }

    self.hasAnyThermostat = function () {
      return self.outputs().some(function (output) {
        return output.output_type() === 'temp_hum_control'
      })
    }

    self.measurementSymbol = function (measurement) {
      const symbols = { temperature: self.temperatureUnitSymbol(), humidity: '%' }
      return symbols[measurement] || ''
    }

    self.shownTarget = function (thermostat) {
      const target = thermostat.target()
      if (target === null) return gettext('off')
      return thermostat.measurement() === 'temperature' ? self.fromCelsius(target) : target
    }

    self.shownDutyCycle = function (dutyCycle) {
      return dutyCycle === 0 ? gettext('off') : dutyCycle
    }

    // ##########
    // ### Commands
    // ##########

    self.patchOutput = function (output, body) {
      return OctoPrint.patchJson(self.buildPluginUrl('outputs/' + output.index_id()), body).fail(self.notifyRequestError)
    }

    self.turnOffThermostat = function (thermostat) {
      self.patchOutput(thermostat, { target: null })
    }

    self.toggleOutput = function (output) {
      self.patchOutput(output, { on: !output.on() })
    }

    self.setDutyCycle = function (output) {
      self.patchOutput(output, { duty_cycle: Number(output.typed_duty_cycle()) }).done(function () {
        output.typed_duty_cycle('')
      })
    }

    self.setColor = function (output) {
      self.patchOutput(output, { color: output.shown_color() }).done(function () {
        output.typed_color('')
      })
    }

    self.setTarget = function (thermostat, form) {
      $(form).find('input').blur()

      const typed = Number(thermostat.typed_target())
      const target = thermostat.measurement() === 'temperature' ? self.toCelsius(typed) : typed
      self.patchOutput(thermostat, { target }).done(function () {
        thermostat.typed_target('')
      })
    }

    self.runAction = function (action) {
      OctoPrint.post(self.buildPluginUrl('actions/' + action.index_id() + '/run')).fail(self.notifyRequestError)
    }

    self.toggleAutomation = function (automation) {
      OctoPrint.patchJson(self.buildPluginUrl('automations/' + automation.index_id()), { enabled: !automation.enabled() })
        .fail(self.notifyRequestError)
    }

    // ##########
    // ### OctoPrint callbacks
    // ##########

    self.onBeforeBinding = function () {
      self.sensorTypesByMeasurementType = JSON.parse($('#enclosure-sensor-types-by-measurement-type').text())
      self.temperatureUnits = JSON.parse($('#enclosure-temperature-units').text())

      const forms = JSON.parse($('#enclosure-settings-forms').text())
      Object.keys(forms).forEach(function (listName) {
        self.settingsFields[listName] = self.formFields(forms[listName])
        self.registerSettingsForms(forms[listName], listName)
      })

      self.addMissingKeysToSettings()
      Object.keys(self.settingsFields).forEach(function (listName) {
        self.pluginSettings()[listName].subscribe(self.addMissingKeysToSettings)
      })

      self.loadItemsFromSettings()
    }

    self.onSettingsBeforeSave = function () {
      self.loadItemsFromSettings()
      self.reportInvalidSettingsItems()
    }

    self.onStartupComplete = function () {
      const gpioAlert = $('.enclosure-gpio-alert').first()
      if (gpioAlert.length) {
        self.notify(gpioAlert.text(), 'error', { hide: false })
      }
      self.reportInvalidSettingsItems()
    }

    self.onUserPermissionsChanged = self.onUserLoggedIn = self.onUserLoggedOut = self.onServerReconnect = self.refreshState

    self.onSettingsShown = function () {
      self.isSettingsOpen = true
      self.openItems.removeAll()
    }

    self.onSettingsHidden = function () {
      self.isSettingsOpen = false
      self.refreshState()
    }

    self.onDataUpdaterPluginMessage = function (plugin, data) {
      if (plugin !== 'enclosure' || self.isSettingsOpen) {
        return
      }

      Object.keys(self.pushCounts).forEach(function (kind) {
        if (Object.prototype.hasOwnProperty.call(data, kind)) {
          self.pushCounts[kind]++
        }
      })
      self.applyState(data)

      if (data.is_msg) {
        self.notify(data.msg, data.msg_type)
      }
    }
  }

  // ##########
  // ### Registration
  // ##########

  OCTOPRINT_VIEWMODELS.push({
    construct: EnclosureViewModel,
    dependencies: ['settingsViewModel', 'loginStateViewModel', 'accessViewModel', 'printerStateViewModel'],
    elements: ['#tab_plugin_enclosure', '#tab_plugin_enclosure_link', '#settings_plugin_enclosure', '#navbar_plugin_enclosure_1', '#navbar_plugin_enclosure_2']
  })
})
