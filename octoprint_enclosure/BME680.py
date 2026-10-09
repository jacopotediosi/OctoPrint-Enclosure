import sys

import bme680


def get_gas_reference():
    # Now run the sensor for a burn-in period, then use combination of relative humidity
    # and gas resistance to estimate indoor air quality as a percentage.
    readings = 10
    gas_reference = 0
    while True:
        sensor.get_sensor_data()
        if sensor.data.heat_stable:
            for _ in range(1, readings):  # // read gas for 10 x 0.150mS = 1.5secs
                sensor.get_sensor_data()
                gas_reference = gas_reference + sensor.data.gas_resistance
            return gas_reference / readings


if __name__ == "__main__":
    try:
        sensor = bme680.BME680(bme680.I2C_ADDR_PRIMARY)
    except RuntimeError:
        try:
            sensor = bme680.BME680(bme680.I2C_ADDR_SECONDARY)
        except Exception as ex:
            print(ex)
            sys.exit(-1)

    sensor.set_humidity_oversample(bme680.OS_2X)
    sensor.set_pressure_oversample(bme680.OS_2X)
    sensor.set_temperature_oversample(bme680.OS_2X)
    sensor.set_filter(bme680.FILTER_SIZE_3)

    sensor.get_sensor_data()
    temperature = sensor.data.temperature
    humidity = sensor.data.humidity

    sensor.set_gas_heater_temperature(320)
    sensor.set_gas_heater_duration(150)
    sensor.select_gas_heater_profile(0)
    sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)

    hum_reference = float(40)

    # Calculate humidity contribution to IAQ index
    current_humidity = float(humidity)
    if current_humidity >= 38 and current_humidity <= 42:
        hum_score = float(0.25 * 100)  # Humidity +/-5% around optimum
    elif current_humidity < 38:
        hum_score = float(0.25 / hum_reference * current_humidity * 100)  # sub-optimal
    else:
        hum_score = ((-0.25 / (100 - hum_reference) * current_humidity) + 0.416666) * 100  # sub-optimal

    # Calculate gas contribution to IAQ index
    gas_lower_limit = float(5000)  # Bad air quality limit
    gas_upper_limit = float(50000)  # Good air quality limit

    gas_reference = get_gas_reference()

    gas_reference = min(gas_reference, gas_upper_limit)
    gas_reference = max(gas_reference, gas_lower_limit)

    gas_score = float(
        (
            0.75 / (gas_upper_limit - gas_lower_limit) * gas_reference
            - (gas_lower_limit * (0.75 / (gas_upper_limit - gas_lower_limit)))
        )
        * 100,
    )

    # Combine results for the final IAQ index value (0-100% where 100% is good quality air)
    air_quality_score = float(hum_score + gas_score)

    print(f"{temperature:0.1f}|{humidity:0.1f}|{air_quality_score:0.1f}")
