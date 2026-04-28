"""
Diagnostic: find which serial config gets a real AA AA protocol response from the Dobot.
"""

import time

import serial

PORT = "COM6"
BAUD = 115200

# Command 246 (get queue index, read-only): AA AA 02 F6 00 0A
CMD_GET_INDEX = bytes([0xAA, 0xAA, 0x02, 0xF6, 0x00, 0x0A])
# Command 240 (queue start exec): AA AA 02 F0 01 0F
CMD_START_EXEC = bytes([0xAA, 0xAA, 0x02, 0xF0, 0x01, 0x0F])
# Command 10 (get pose): AA AA 02 0A 00 F4
CMD_GET_POSE = bytes([0xAA, 0xAA, 0x02, 0x0A, 0x00, 0xF4])


def has_aa_aa(data: bytearray) -> bool:
    for i in range(len(data) - 1):
        if data[i] == 0xAA and data[i + 1] == 0xAA:
            return True
    return False


def try_config(label, dtr, rts, delay, cmd, wait=4.0):
    print(f"\n--- {label} ---")
    try:
        ser = serial.Serial(
            PORT,
            baudrate=BAUD,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1,
        )
        ser.dtr = dtr
        ser.rts = rts

        if delay > 0:
            print(f"  Waiting {delay}s for device to boot...")
            time.sleep(delay)

        # Drain any startup bytes
        startup = bytes()
        t0 = time.time()
        while time.time() - t0 < 0.3:
            chunk = ser.read(ser.in_waiting or 0)
            startup += chunk
            if chunk:
                time.sleep(0.05)
        if startup:
            print(f"  Startup bytes (drained): {startup.hex(' ')}")

        print(f"  Sending: {cmd.hex(' ')}")
        ser.write(cmd)

        deadline = time.time() + wait
        received = bytearray()
        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                received.extend(chunk)

        ser.close()

        if received:
            ok = has_aa_aa(received)
            tag = "AA AA RESPONSE" if ok else "raw bytes only"
            print(f"  RESPONSE [{tag}] ({len(received)} bytes): {received.hex(' ')}")
            return ok
        else:
            print("  No response.")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# Test all configs — do NOT stop at the first one that gets any bytes.
# We need a config that returns AA AA (a real Dobot protocol response).
configs = [
    # label                                   dtr    rts    delay  cmd
    ("DTR=T  RTS=T  delay=0s  GET_INDEX", True, True, 0, CMD_GET_INDEX),
    ("DTR=T  RTS=T  delay=2s  GET_INDEX", True, True, 2, CMD_GET_INDEX),
    ("DTR=T  RTS=T  delay=3s  GET_INDEX", True, True, 3, CMD_GET_INDEX),
    ("DTR=F  RTS=F  delay=0s  GET_INDEX", False, False, 0, CMD_GET_INDEX),
    ("DTR=F  RTS=F  delay=1s  GET_INDEX", False, False, 1, CMD_GET_INDEX),
    ("DTR=T  RTS=T  delay=0s  START_EXEC", True, True, 0, CMD_START_EXEC),
    ("DTR=T  RTS=T  delay=2s  START_EXEC", True, True, 2, CMD_START_EXEC),
    ("DTR=F  RTS=F  delay=0s  START_EXEC", False, False, 0, CMD_START_EXEC),
    ("DTR=T  RTS=T  delay=0s  GET_POSE", True, True, 0, CMD_GET_POSE),
    ("DTR=T  RTS=T  delay=2s  GET_POSE", True, True, 2, CMD_GET_POSE),
]

winner = None
for label, dtr, rts, delay, cmd in configs:
    if try_config(label, dtr, rts, delay, cmd):
        winner = label
        print(f"\n*** First AA AA response from: {label} ***")
        break  # stop at first real protocol response

if winner is None:
    print("\n\nNo config produced an AA AA protocol response.")
    print("Check: Dobot Studio fully closed? Dobot powered on? Correct COM port?")
