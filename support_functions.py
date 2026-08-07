from ds3231 import DS3231
from machine import I2C, RTC, Pin

clock = DS3231(I2C(0, scl=Pin(21), sda=Pin(20)))
rtc = RTC()


def synchronization():
    try:
        rtc.datetime(clock.get_time())
        return False
    except BaseException:
        return True


def out_of_limits(minimum: int, value: float, maxximum: int) -> float:
    """Check value if in the limits."""
    if minimum <= value <= maxximum:
        return value
    raise ValueError(minimum, value, maxximum)


def unsigned_int(data: bytes, index: int) -> int:
    """Reads 16-bit unsigned int from register at given index."""
    return (data[2 * index] << 8) | data[2 * index + 1]


def signed_int(data: bytes, index: int) -> int:
    """Reads 16-bit signed int from register at given index."""
    return (unsigned_int(data, index) ^ 0x8000) - 0x8000


def crc16(data: bytes) -> int:
    """Modbus CRC-16 (poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc
