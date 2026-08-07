import time

import lcd_1inch14
import machine
from support_functions import crc16, out_of_limits, signed_int, unsigned_int


def loop_with_condition(array, condition, func) -> None:
    """Loop throught pins and set it based on provided function"""
    for pin in array:
        if condition(pin):
            func(pin)
            break


def turn_off_last(pins: list) -> None:
    """Set pin off() for first in array with lowest priority that is active."""
    loop_with_condition(pins[::-1], lambda pin: pin.value(), lambda pin: pin.off())


class OutputHeaters:
    """Pin output control class."""

    def __init__(self, pins, indexes_L1: list[int], indexes_L2: list[int]) -> None:
        self.pins = pins
        self.indexes_L1 = indexes_L1
        self.indexes_L2 = indexes_L2

    def set_pins(
        self,
        enable: bool,
        overpower_L1: int | None,
        overpower_L2: int | None,
        control: int,
    ) -> None:
        """Set output pins based on preset variables from ControlLogic"""
        if enable:
            if overpower_L1 == -1:
                array = [self.pins[index] for index in self.indexes_L1]
                turn_off_last(array)
            if overpower_L2 == -1:
                array = [self.pins[index] for index in self.indexes_L2]
                turn_off_last(array)
            if control > 0:
                possible_indexes = []
                if overpower_L1 is None:
                    possible_indexes += self.indexes_L1
                if overpower_L2 is None:
                    possible_indexes += self.indexes_L2
                possible_pins = [
                    pin
                    for index, pin in enumerate(self.pins)
                    if index in possible_indexes
                ]
                loop_with_condition(
                    possible_pins, lambda pin: not pin.value(), lambda pin: pin.on()
                )
            elif control < 0:
                turn_off_last(self.pins)
        else:
            for heater in self.pins:
                heater.off()


class Counter:
    """Counter class with pin.irq."""

    def __init__(self, pin: machine.Pin):
        self.pin = pin
        self.pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.trigger_count)
        self.counter = 0

    def trigger_count(self, _: machine.Pin) -> None:
        """Count up counter"""
        self.counter += 1

    def zero_counter(self) -> None:
        """Zero counter."""
        self.counter = 0

    def get_count(self) -> int:
        """Get counter and zero it."""
        count = self.counter
        self.zero_counter()
        return count


class ControlLogic:
    """Desides how to set output based on inputs."""

    def __init__(self) -> None:
        self.heaters_enabled = False
        self.off_grid_enabled = False
        self.overpower_L1 = None
        self.overpower_L2 = None

    @staticmethod
    def soc_enabled(
        enabled: bool, soc: float, enable_above: int, disable_below: int
    ) -> bool:
        """Battery status of charge logic."""
        if not enabled and soc > enable_above:
            return True
        if enabled and soc < disable_below:
            return False
        return enabled

    @staticmethod
    def overpower_logic(count: int) -> int | None:
        """Overpower on phase line logic."""
        if count > 26:
            return -1
        if count >= 12:
            return 0
        return None

    def heaters_logic(
        self, soc: float, current: float, count_L1: int, count_L2: int
    ) -> tuple[bool, None | int, None | int, int]:
        """Set output variables based on provided arguments for heaters controler."""
        self.heaters_enabled = self.soc_enabled(self.heaters_enabled, soc, 90, 83)
        control = 0
        overpower_L1 = None
        overpower_L2 = None
        if self.heaters_enabled:
            overpower_L1 = self.overpower_logic(count_L1)
            overpower_L2 = self.overpower_logic(count_L2)
            if overpower_L1 != -1 and overpower_L2 != -1:
                if current > 22 or (-6 <= current <= 6 and soc > 97):
                    control = 1
                elif current < -35:
                    control = -1
        return self.heaters_enabled, overpower_L1, overpower_L2, control

    def off_grid_logic(self, soc: float) -> int:
        """Disconnect PV inverters from grid."""
        self.off_grid_enabled = self.soc_enabled(self.off_grid_enabled, soc, 40, 30)
        return 1 if self.off_grid_enabled else 0


class LCD:
    """LCD parrent class."""

    def __init__(
        self,
        lcd: lcd_1inch14.LCD_1inch14,
        timer: machine.Timer,
        data: dict[str, int | bool | float],
    ):
        self.lcd = lcd
        self.timer = timer
        self.timer.init(
            mode=machine.Timer.PERIODIC, period=1000, callback=self._update_screen
        )
        self.blink_error = False
        self.data = data

    def _update_screen(self, timer: machine.Timer) -> None:
        """Draws new screen with configured style."""
        if self.data["error"] is not None:
            self._error_loop()
        else:
            self._data_metrics()
            self._data_heaters()
            self._data_offgrid()
            self._add_time()
        self._display()

    def _data_heaters(self) -> None:
        """Show heaters are enabled."""
        status = " Enabled" if self.data["enabled"] == 1 else "Disabled"
        self.lcd.text(f"Heaters: {status}", 12, 87, self.lcd.ORANGE)

    def _data_offgrid(self) -> None:
        """Show PV inverters are not connected to power grid."""
        grid = " True" if self.data["off_grid"] == 1 else "False"
        self.lcd.text(f"Off grid:   {grid}", 12, 107, self.lcd.GREEN)  # 0x1FF8)

    def _data_metrics(self) -> None:
        """Show battery parameters."""
        self.lcd.fill(self.lcd.BLACK)
        self.lcd.text(
            f"Voltage:   {float(self.data['voltage']):6.2f} V", 12, 7, self.lcd.BLUE
        )
        self.lcd.text(
            f"Current:   {float(self.data['current']):6.2f} A", 12, 27, self.lcd.RED
        )
        self.lcd.text(
            f"SOC:       {float(self.data['soc']):6.1f} %", 12, 47, self.lcd.GREEN
        )
        self.lcd.text(f"Cycles:      {self.data['cycles']:4d}", 12, 67, self.lcd.BLUE)

    def _add_time(self) -> None:
        """Text field with actual time and date."""
        act = time.localtime()
        time_str = f"  {act[3]:2d}:{act[4]:02d}:{act[5]:02d}        {act[2]:2d}.{act[1]:2d}.{act[0]:4d}"
        self.lcd.text(time_str, 0, 126, self.lcd.RED)

    def _display(self) -> None:
        """Display texts from buffer."""
        self.lcd.show()

    def _error_loop(self) -> None:
        """Show error on screen in infinite loop."""
        if self.blink_error:
            background_color = self.lcd.RED
            text_color = self.lcd.WHITE
        else:
            background_color = self.lcd.WHITE
            text_color = self.lcd.RED
        self.lcd.fill(background_color)
        self.lcd.text("!!! ERROR !!!", 68, 63, text_color)
        self.lcd.text(self.data["error"], 0, 83, text_color)
        self.blink_error ^= True

    def update_values(self, data: dict[str, bool | float | int]) -> None:
        """Update inner data structure."""
        self.data.update(data)


class Battery:
    """Gets telemtery data from Seplos BMS v3 (PIA block)."""

    RETRIES = 5
    HEATERS_OFF_AT = 2
    RETRY_DELAY_S = 1

    COMMAND = b"\x00\x04\x10\x00\x00\x12\x75\x16"

    def __init__(self, rs485: machine.UART) -> None:
        self.rs485 = rs485
        self.counter_connection_error = 0

    def _read_frame(self) -> bytes:
        """Send request, read and validate response. Returns register bytes."""
        while self.rs485.any():  # clean buffer
            self.rs485.read(self.rs485.any())
        self.rs485.write(self.COMMAND)
        head = self.rs485.read(3)
        if not head or len(head) != 3:
            raise ValueError("No response")
        if head[0] != self.COMMAND[0] or head[1] != self.COMMAND[1]:
            raise ValueError("Wrong head")
        rest = self.rs485.read(head[2] + 2)  # data + CRC
        if not rest or len(rest) != head[2] + 2:
            raise ValueError("Short frame")
        frame = head + rest
        if crc16(frame[:-2]) != frame[-2] | (frame[-1] << 8):
            raise ValueError("Bad CRC")
        return rest[:-2]

    @staticmethod
    def _parse(data: bytes) -> dict[str, str | None | float]:
        """Parse PIA block registers into telemetry values."""
        return {
            "error": None,
            "soc": out_of_limits(0, unsigned_int(data, 5) / 10, 100),
            "current": out_of_limits(-100, signed_int(data, 1) / 100, 100),
            "voltage": out_of_limits(0, unsigned_int(data, 0) / 100, 100),
            "cycles": unsigned_int(data, 7),
        }

    def read_battery_parameters(
        self, heaters: OutputHeaters
    ) -> dict[str, str | None | float]:
        """Read telemetry data from batter."""
        while True:
            try:
                response = self._parse(self._read_frame())
            except (TypeError, ValueError) as exc:
                if self.counter_connection_error >= self.RETRIES - 1:
                    return {
                        "error": f"Battery data: {exc}",
                        "soc": 0,
                        "current": -100,
                        "voltage": 0,
                    }
                if self.counter_connection_error == self.HEATERS_OFF_AT:
                    heaters.set_pins(False, None, None, 0)
                self.counter_connection_error += 1
                time.sleep(self.RETRY_DELAY_S)
            else:
                self.counter_connection_error = 0
                return response
