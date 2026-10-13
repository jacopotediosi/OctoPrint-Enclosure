from __future__ import annotations


def crc16_modbus(data: bytes) -> int:
    """Calculate the CRC-16/MODBUS of some data.

    Args:
        data (bytes): The data.

    Returns:
        int: The CRC-16/MODBUS of the data.

    Examples:
        >>> hex(crc16_modbus(b"123456789"))
        '0x4b37'

    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc
