import time

import ds3231
import lcd_1inch14
import machine

import models


def init_counters() -> tuple[models.Counter, models.Counter]:
    """Inits counter objects."""
    counter_l1 = models.Counter(machine.Pin(26, machine.Pin.IN, machine.Pin.PULL_DOWN))
    counter_l2 = models.Counter(machine.Pin(27, machine.Pin.IN, machine.Pin.PULL_DOWN))
    return counter_l1, counter_l2


def init_battery() -> models.Battery:
    rs485 = machine.UART(
        0,
        baudrate=19200,
        tx=machine.Pin(0),
        rx=machine.Pin(1),
        timeout=600,
        timeout_char=20,
        rxbuf=512,
    )
    return models.Battery(rs485)


def init_heaters() -> models.OutputHeaters:
    pin_indexes_L1 = [0, 2]
    pin_indexes_L2 = [1]
    pins = [machine.Pin(pin, machine.Pin.OUT, value=0) for pin in [6, 7, 14]]
    return models.OutputHeaters(pins, pin_indexes_L1, pin_indexes_L2)


def synchronization(time: list[int]) -> str | None:
    """Synchronize Pico RTC with external clock."""
    try:
        machine.RTC().datetime(time)
        return None
    except BaseException:
        return "Clock synchronization"


def init_clock() -> ds3231.DS3231:
    clock = ds3231.DS3231(machine.I2C(0, scl=machine.Pin(21), sda=machine.Pin(20)))
    if synchronization(clock.get_time()) is not None:
        raise BaseException
    return clock


def update_if_changed(
    data: dict[str, int | None | str | float],
    cycles_record: dict[str, int | list[int]],
    config: models.Config,
    logger: models.DataLogger,
) -> dict[str, int | list[int]]:
    number = data.get("cycles")
    num_list = cycles_record["last_three"]
    if all(item == number for item in num_list):
        if cycles_record["count"] != number:
            config.set("cycles", number)
            # logger.log(data)
            cycles_record["count"] = number
    else:
        num_list.pop(0)
        num_list.append(number)
    cycles_record["last_three"] = num_list
    return cycles_record


def main() -> None:
    # Init start
    counter_L1, counter_L2 = init_counters()
    batery = init_battery()
    heaters = init_heaters()
    grid_connector = machine.Pin(22, machine.Pin.OUT, value=0)
    data = {
        "enabled": False,
        "error": None,
        "soc": 0,
        "current": 0,
        "voltage": 0,
        "cycles": 0,
        "off_grid": 0,
    }
    lcd = models.LCD(lcd_1inch14.LCD_1inch14(), machine.Timer(), data)
    clock = init_clock()
    control = models.ControlLogic()
    last_sync = time.localtime()[2]
    last_cycle = time.time()
    # Init end
    while True:
        while data["error"] is None:
            if time.time() - last_cycle >= 2:
                actual_time = time.localtime()
                battery_data = batery.read_battery_parameters(heaters)
                data |= battery_data | {
                    "count_L1": counter_L1.get_count(),
                    "count_L2": counter_L2.get_count(),
                }

                control_args_heaters = control.heaters_logic(
                    data["soc"], data["current"], data["count_L1"], data["count_L2"]
                )
                heaters.set_pins(*control_args_heaters)
                data["enabled"] = control_args_heaters[0]

                control_off_grid = control.off_grid_logic(data["soc"])
                grid_connector.value(control_off_grid)
                data["off_grid"] = control_off_grid

                if last_sync != actual_time[2] and 19 < actual_time[3]:
                    data["error"] = synchronization(clock.get_time())
                    last_sync = actual_time[2]

                lcd.update_values(data)
                last_cycle = time.time()
            else:
                time.sleep(0.2)
        grid_connector.value(0)
        heaters.set_pins(False, None, None, 0)
        if "Battery data" not in data["error"]:
            break
        else:
            time.sleep(3)
            data["error"] = None


if __name__ == "__main__":
    main()
