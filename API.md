# API Reference

The API is located at \<OctoPrintURL>/plugin/enclosure. This needs to be added before each endpoint in order for the API to function properly. The API either returns a `application/json` body or an empty body for a successful request.

A failed request returns an error code and the body `{"errors": [string]}`, with one message for each problem found.

## List all inputs

Endpoint: **GET** `/inputs`

Response (200): the inputs, ordered by id, each as in **GET** `/inputs/<id>`.

Error Responses:
 - none

## Get an input

Endpoint: **GET** `/inputs/<id>`

Response (200), for an input with a temperature sensor:
```
{
    "id": number,
    "type": "temperature_sensor",
    "label": string,
    "temperature": number (in Celsius), or null if the sensor has none,
    "humidity": number (relative, in percent), or null if the sensor has none,
    "air_quality": number, or null if the sensor has none
}
```

Response (200), for a GPIO input:
```
{
    "id": number,
    "type": "gpio",
    "label": string,
    "active": boolean (with a pull-up resistor the input is active when its pin is low), or null if the pin can't be read
}
```

Error Responses:
 - 404 if no input is set up with that id

## List all outputs

Endpoint: **GET** `/outputs`

Response (200): the outputs that are set up, ordered by id, each as in **GET** `/outputs/<id>`.

Error Responses:
 - none

## Get an output

Endpoint: **GET** `/outputs/<id>`

Response (200), for a regular output:
```
{
    "id": number,
    "type": "regular",
    "label": string,
    "on": boolean, or null if the output can't be read
}
```

Response (200), for a PWM output:
```
{
    "id": number,
    "type": "pwm",
    "label": string,
    "on": boolean, or null if the output can't be read,
    "duty_cycle": number (0-100)
}
```

Response (200), for an output that has a color (e.g. an RGB LED strip, a NeoPixel, etc.):
```
{
    "id": number,
    "type": string ("ledstrip", "neopixel_direct" or "neopixel_indirect"),
    "label": string,
    "on": boolean, or null if the output can't be read,
    "color": string ("#rrggbb")
}
```

Response (200), for a thermostat:
```
{
    "id": number,
    "type": "temp_hum_control",
    "label": string,
    "on": boolean (whether its device, like a heater, is on), or null if the output can't be read,
    "target": number (the temperature in Celsius, or the relative humidity in percent), or null if the thermostat is off,
    "measurement": string ("temperature" or "humidity")
}
```

Error Responses:
 - 404 if no output is set up with that id

## Control an output

Endpoint: **PATCH** `/outputs/<id>`

Body (Content-Type: `application/json`), with exactly one of these attributes:
```
{
    "on": boolean (false turns any output off; true turns on a regular output only),
    "duty_cycle": number (0-100; for a PWM output),
    "color": string ("#rrggbb"; for an output that has a color, e.g. an RGB LED strip, a NeoPixel, etc.),
    "target": number (the temperature in Celsius, or the relative humidity in percent; for a thermostat), or null to turn the thermostat off
}
```

Response (200): the output, as in **GET** `/outputs/<id>`.

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or its attributes are unknown, missing, invalid or not valid for the type of the output
- 404 - no output is set up with that id

## List all actions

Endpoint: **GET** `/actions`

Response (200): the actions, ordered by id, each as in **GET** `/actions/<id>`.

Error Responses:
 - none

## Get an action

Endpoint: **GET** `/actions/<id>`

Response (200):
```
{
    "id": number,
    "type": string ("gcode_output", "shell_output" or "printer"),
    "label": string
}
```

Error Responses:
 - 404 if no action is set up with that id

## Run an action

Endpoint: **POST** `/actions/<id>/run`

Body: empty

Response (204): No-Content

Error Responses:
- 404 - no action is set up with that id
- 409 - the action can't be run, because its settings are not valid

## List all automations

Endpoint: **GET** `/automations`

Response (200): the automations, ordered by id, each as in **GET** `/automations/<id>`.

Error Responses:
 - none

## Get an automation

Endpoint: **GET** `/automations/<id>`

Response (200):
```
{
    "id": number,
    "type": string ("rule", "filament", "pwm_temperature_linked" or "toggle_timer"),
    "label": string,
    "enabled": boolean
}
```

Error Responses:
 - 404 if no automation is set up with that id

## Enable or disable an automation

Endpoint: **PATCH** `/automations/<id>`

Body (Content-Type: `application/json`):
```
{
    "enabled": boolean
}
```

Response (200): the automation, as in **GET** `/automations/<id>`.

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or its attributes are unknown, missing or invalid
- 404 - no automation is set up with that id

## Push messages

The plugin also sends its state over the OctoPrint push socket, as plugin messages of the plugin `enclosure`. A message has one of these attributes:
 - `inputs`: the inputs, ordered by id, each as in **GET** `/inputs/<id>`
 - `outputs`: the outputs that are set up, ordered by id, each as in **GET** `/outputs/<id>`
 - `automations`: the automations, ordered by id, each as in **GET** `/automations/<id>`
