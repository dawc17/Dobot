"""
IR sensor protocol probe.

Tries every plausible param format for IR sensor on a chosen port,
prints raw responses. Run with the sensor in a known state (clear, then blocked).

Usage: python ir_probe.py [PORT_NAME]
       PORT_NAME in {GP1, GP2, GP4, GP5}, default GP4.
"""

import sys
import time
from pydobotplus import Dobot
from pydobotplus.message import Message

COM = "COM6"
PORT_MAP = {"GP1": 0, "GP2": 1, "GP4": 2, "GP5": 3}
port_name = sys.argv[1] if len(sys.argv) > 1 else "GP4"
PORT = PORT_MAP[port_name]
print(f"Probing IR sensor on {port_name} (port byte = 0x{PORT:02x})")

d = Dobot(port=COM)
print("Connected.")


def send(label, ctrl, params):
    msg = Message()
    msg.id = 138
    msg.ctrl = ctrl
    msg.params = bytearray(params)
    try:
        r = d._send_command(msg)
        hex_out = " ".join(f"{b:02x}" for b in r.params)
        print(
            f"  {label:50s} sent ctrl={ctrl:#04x} params={[f'{b:#04x}' for b in params]}  ->  [{hex_out}]"
        )
        return r
    except Exception as e:
        print(f"  {label:50s} ERROR: {e}")
        return None


print("\n=== ENABLE attempts ===")
send("V1 set ctrl=0x02 [enable, port]", 0x02, [1, PORT])
time.sleep(0.2)
send("V1 set ctrl=0x03 [enable, port]", 0x03, [1, PORT])
time.sleep(0.2)
send("V2 set ctrl=0x02 [enable, port, ver=1]", 0x02, [1, PORT, 0x01])
time.sleep(0.2)
send("V2 set ctrl=0x03 [enable, port, ver=1]", 0x03, [1, PORT, 0x01])
time.sleep(0.2)
send("V2 set ctrl=0x03 [enable, port, 0x01, ver=1]", 0x03, [1, PORT, 0x01, 0x01])
time.sleep(0.5)

print("\n=== READ attempts (please ensure NOTHING is in front of sensor) ===")
input("Press Enter when sensor is CLEAR (nothing in front)...")
print("\n--- Sensor CLEAR ---")
send("V1 get [port]", 0x00, [PORT])
send("V2 get [port, ver=1]", 0x00, [PORT, 0x01])
send("V2 get [port, 0x01, ver=1]", 0x00, [PORT, 0x01, 0x01])
send("V2 get [ver=1, port]", 0x00, [0x01, PORT])

input("\nNow PLACE AN OBJECT in front of sensor and press Enter...")
print("\n--- Sensor BLOCKED ---")
send("V1 get [port]", 0x00, [PORT])
send("V2 get [port, ver=1]", 0x00, [PORT, 0x01])
send("V2 get [port, 0x01, ver=1]", 0x00, [PORT, 0x01, 0x01])
send("V2 get [ver=1, port]", 0x00, [0x01, PORT])

print("\nDone.")
d.close()
