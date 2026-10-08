from gpiozero import CPUTemperature


class PiTemp:
    def get_temp(self):
        temp = CPUTemperature()
        return f"{temp.temperature:0.1f}"
