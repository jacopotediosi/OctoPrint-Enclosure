# API Reference v2.0

The API is located at \<OctoPrintURL>/plugin/enclosure. This needs to be added before each endpoint in order for the API to function properly. The API either returns a `application/json` body or an empty body for a successful request.

A failed request will return an error code as well as a short error description.

## List all inputs

Endpoint: **GET** `/inputs`

Response (200):

```
[
    {
        "index_id": number,
        "label": string,
        "GPIO_Pin": number (null for non-GPIO inputs),
        "State": string ("ON", "OFF" or "ERROR: Unable to read pin"; null for non-GPIO inputs)
    }
]
```

Error Responses:
 - none

## Get an input

Endpoint: **GET** `/inputs/<id>`

*Note: id needs to be int (index_id)*

Response (200):
```
{
    "controlled_io": number, or "" if not set, or null without an automation,
    "filament_sensor_timeout": number, or null without an automation,
    "filament_sensor_enabled": boolean, or null without an automation,
    "temp_sensor_address": string,
    "printer_action": string, or null without an automation,
    "controlled_io_set_state": string, or null without an automation,
    "temp_sensor_type": string,
    "temp_sensor_i2cbus": number,
    "temp_i2c_bus": number,
    "temp_i2c_address": number,
    "temp_i2c_register": number,
    "show_graph_temp": boolean,
    "show_graph_humidity": boolean,
    "temp_sensor_navbar": boolean,
    "temp_sensor_humidity": number, or "" without a reading,
    "edge": string, or null without an automation,
    "ds18b20_serial": string,
    "action_type": string, or null without an automation,
    "input_pull_resistor": string,
    "input_type": string,
    "temp_sensor_temp": number, or "" without a reading,
    "label": string,
    "index_id": number,
    "use_fahrenheit": boolean,
    "gpio_pin": string
}
```

Error Responses:
 - 404 if specified id cannot be found

## List all outputs

Endpoint: **GET** `/outputs`

*Note: lists the regular outputs only*

Response (200):
```
[
    {
        "index_id": number,
        "label": string,
        "GPIO_Pin": number,
        "State": string ("ON", "OFF" or "ERROR: Unable to read pin")
    }
]
```

Error Responses:
 - none

## Get an output

Endpoint: **GET** `/outputs/<id>`

*Note: id needs to be int (index_id)*


Response (200):
```
{
    "linked_temp_sensor": string,
    "ledstrip_gpio_dat": string,
    "startup_time": number,
    "temp_ctr_deadband": number,
    "neopixel_brightness": number,
    "gpio_pin": number,
    "gpio_i2c_enabled": boolean,
    "gpio_i2c_bus": number,
    "gpio_i2c_address": number,
    "gpio_i2c_register": number,
    "gpio_i2c_data_on": number,
    "gpio_i2c_data_off": number,
    "gpio_i2c_register_status": number,
    "default_duty_cycle": number,
    "neopixel_color": string,
    "hide_btn_ui": boolean,
    "temp_ctr_set_value": number,
    "temp_ctr_default_value": number,
    "default_neopixel_color": string,
    "controlled_io_set_state": string,
    "auto_shutdown": boolean,
    "shell_script": string,
    "label": string,
    "default_ledstrip_color": string,
    "duty_a": number,
    "toggle_timer_off": number,
    "alarm_set_temp": number,
    "ledstrip_gpio_clk": string,
    "auto_startup": boolean,
    "controlled_io": number,
    "shutdown_time": number,
    "temp_ctr_type": string,
    "gcode": string,
    "current_value": boolean,
    "shutdown_on_failed": boolean,
    "shutdown_on_error": boolean,
    "temperature_b": number,
    "ledstrip_color": string,
    "temperature_a": number,
    "neopixel_count": number,
    "neopixel_dma": number,
    "duty_cycle": number,
    "toggle_timer_on": number,
    "show_on_navbar": boolean,
    "duty_b": number,
    "toggle_timer": boolean,
    "gpio_status": boolean,
    "pwm_frequency": number,
    "startup_with_server": boolean,
    "active_low": boolean,
    "temp_ctr_max_temp": number,
    "pwm_temperature_linked": boolean,
    "output_type": string,
    "microcontroller_address": number,
    "index_id": number
}
```

Error Responses:
 - 404 if specified id cannot be found

## Switch an output

Endpoint: **PATCH** `/outputs/<id>`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "status": boolean
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Enable the auto-startup of an output

Endpoint: **PATCH** `/outputs/<id>/auto-startup`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "status": boolean
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Enable the auto-shutdown of an output

Endpoint: **PATCH** `/outputs/<id>/auto-shutdown`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "status": boolean
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Set the target of a thermostat

Endpoint: **PATCH** `/temperature/<id>`

*Note: id needs to be int (index_id) of a thermostat output*

Body (Content-Type: `application/json`):
```
{
    "temperature": number (the target temperature, or humidity for a dehumidifier; 0 turns the thermostat off)
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Enable the filament sensor of an input

Endpoint: **PATCH** `/filament/<id>`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "status": boolean
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Set the duty cycle of a PWM output

Endpoint: **PATCH** `/pwm/<id>`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "duty_cycle": number (0-100)
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Set the color of an RGB LED strip

Endpoint: **PATCH** `/rgb-led/<id>`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "rgb": string ("rgb(r,g,b)", with r, g and b from 0 to 255)
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Set the color of a NeoPixel output

Endpoint: **PATCH** `/neopixel/<id>`

*Note: id needs to be int (index_id)*

Body (Content-Type: `application/json`):
```
{
    "red": number (0-255),
    "green": number (0-255),
    "blue": number (0-255)
}
```

Response (204): No-Content

Error Responses:
- 415 - Content-Type is not application/json
- 400 - malformed JSON
- 422 - body is not a JSON object, or attributes are missing or invalid (all of them are listed in the response body)

## Refresh the UI

Endpoint: **POST** `/update`

Body: empty

Response (204): No-Content

Error Responses:
- none

## Run a shell action

Endpoint: **POST** `/shell/<id>`

*Note: id needs to be int (index_id) of a shell action*

Body: empty

Response (204): No-Content

Error Responses:
- none

## Run a G-code action

Endpoint: **POST** `/gcode/<id>`

*Note: id needs to be int (index_id) of a G-code action*

Body: empty

Response (204): No-Content

Error Responses:
- none

## Run a printer action

Endpoint: **POST** `/printer/<id>`

*Note: id needs to be int (index_id) of a printer action*

Body: empty

Response (204): No-Content

Error Responses:
- none
