from serial.tools import list_ports


def discover_serial():
    devices = []
    for p in list_ports.comports():
        label = f"{p.description} {p.manufacturer or ''}".lower()
        likely = p.vid in (0x1A86, 0x0403, 0x0483) or any(
            t in label for t in ("ch340", "ch341", "feetech", "waveshare")
        )
        devices.append(
            {
                "port": p.device,
                "description": p.description,
                "serial_number": p.serial_number,
                "likely_servo_adapter": likely,
                "follower_verified": False,
                "note": "USB identity cannot distinguish a leader from a follower; operator must select",
            }
        )
    return devices
