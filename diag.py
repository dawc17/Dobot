"""
Diagnostic: test different serial configurations to find what the Dobot responds to.
"""
import serial
import time

PORT = "COM3"
BAUD = 115200

# Command 240 (queue start exec): AA AA 02 F0 01 0F
CMD_START_EXEC = bytes([0xAA, 0xAA, 0x02, 0xF0, 0x01, 0x0F])
# Command 246 (get queue index, read-only, safer): AA AA 02 F6 00 0A
CMD_GET_INDEX   = bytes([0xAA, 0xAA, 0x02, 0xF6, 0x00, 0x0A])
# Command 10 (get device info): AA AA 02 0A 00 F4
CMD_DEVICE_INFO = bytes([0xAA, 0xAA, 0x02, 0x0A, 0x00, 0xF4])


def try_config(label, dtr, rts, delay, cmd):
    print(f"\n--- {label} ---")
    try:
        ser = serial.Serial(PORT, baudrate=BAUD,
                            parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_ONE,
                            bytesize=serial.EIGHTBITS,
                            timeout=1)
        # Set control lines BEFORE sending
        ser.dtr = dtr
        ser.rts = rts
        if delay > 0:
            print(f"  Waiting {delay}s...")
            time.sleep(delay)
        startup = ser.read(ser.in_waiting or 0)
        if startup:
            print(f"  Startup bytes: {startup.hex(' ')}")

        print(f"  Sending: {cmd.hex(' ')}")
        ser.write(cmd)

        deadline = time.time() + 3
        received = bytearray()
        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                received.extend(chunk)
        ser.close()

        if received:
            print(f"  RESPONSE ({len(received)} bytes): {received.hex(' ')}")
            return True
        else:
            print("  No response.")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


configs = [
    # label,                        dtr,   rts,   delay, cmd
    ("DTR=True  RTS=True  delay=0s",  True,  True,  0,     CMD_GET_INDEX),
    ("DTR=False RTS=False delay=0s",  False, False, 0,     CMD_GET_INDEX),
    ("DTR=False RTS=False delay=1s",  False, False, 1,     CMD_GET_INDEX),
    ("DTR=False RTS=False delay=2s",  False, False, 2,     CMD_GET_INDEX),
    ("DTR=True  RTS=True  delay=2s",  True,  True,  2,     CMD_GET_INDEX),
    ("DTR=False RTS=False delay=0s cmd=start", False, False, 0, CMD_START_EXEC),
    ("DTR=False RTS=False delay=0s cmd=info",  False, False, 0, CMD_DEVICE_INFO),
]

for label, dtr, rts, delay, cmd in configs:
    if try_config(label, dtr, rts, delay, cmd):
        print("\n*** Found working config! ***")
        break
else:
    print("\n\nNo config produced a response.")
    print("Check: is Dobot Studio fully closed? Is the Dobot powered on?")
