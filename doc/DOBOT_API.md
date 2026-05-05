# pydobotplus API Reference

Complete reference for the `pydobotplus` library (v0.1.2) as installed in this project.

---

## Quick Start

```python
from pydobotplus import Dobot

# Auto-detect port (matches VID 4292 or 6790)
arm = Dobot()

# Explicit port
arm = Dobot(port="COM3")   # Windows
arm = Dobot(port="/dev/ttyUSB0")  # Linux

arm.close()
```

> **Windows note:** The constructor takes ~2.5 seconds to connect. DTR and RTS must be asserted and the device needs time to settle before it will respond.

---

## Data Types

### `Position`
Named tuple with fields `x, y, z, r` (all `float`, in mm / degrees).

### `Joints`
Named tuple with fields `j1, j2, j3, j4` (degrees).
- `.in_radians()` → returns a new `Joints` with values converted to radians.

### `Pose`
Named tuple: `Pose(position: Position, joints: Joints)`

### `MODE_PTP`
IntEnum for point-to-point motion modes, passed to `move_to(mode=...)`:

| Name | Value | Description |
|------|-------|-------------|
| `JUMP_XYZ` | 0 | Jump motion in Cartesian space |
| `MOVJ_XYZ` | 1 | Joint interpolation to XYZ target **(default)** |
| `MOVL_XYZ` | 2 | Linear interpolation to XYZ target |
| `JUMP_ANGLE` | 3 | Jump motion in joint space |
| `MOVJ_ANGLE` | 4 | Joint interpolation to joint angle target |
| `MOVL_ANGLE` | 5 | Linear interpolation to joint angle target |
| `MOVJ_INC` | 6 | Joint interpolation, incremental |
| `MOVL_INC` | 7 | Linear interpolation, incremental |
| `MOVJ_XYZ_INC` | 8 | Joint interpolation, XYZ incremental |
| `JUMP_MOVL_XYZ` | 9 | Jump + linear motion |

### `DobotException`
Raised on connection failure or when the device returns no response.

### `Alarm`
IntEnum with ~80 alarm codes. Key ones:

| Name | Meaning |
|------|---------|
| `PLAN_INV_LIMIT` | Target position out of reach |
| `MOVE_INV_LIMIT` | Limit hit during movement |
| `OVERSPEED_AXIS1–4` | Motor overspeed |
| `LIMIT_AXIS*_POS/NEG` | Axis hit positive/negative limit |
| `LOSE_STEP_AXIS1–4` | Stepper motor lost steps |
| `MOTOR_*_OVERHEAT` | Motor overheating |

---

## Connection

### `Dobot(port=None)`
Opens the serial connection and initialises the arm.

- `port` — COM port string (e.g. `"COM3"`). If `None`, auto-detects by USB VID.
- Raises `DobotException` if the port cannot be opened or the device does not respond.
- On init, automatically: starts queue execution, clears queue, sets default PTP/jump params, clears any existing alarms.

### `close()`
Closes the serial port. Always call this when done.

```python
arm.close()
```

---

## Pose & Position

### `get_pose() → Pose`
Returns the current end-effector position and joint angles.

```python
pose = arm.get_pose()

pose.position.x   # mm
pose.position.y   # mm
pose.position.z   # mm
pose.position.r   # degrees (tool rotation)

pose.joints.j1    # degrees
pose.joints.j2    # degrees
pose.joints.j3    # degrees
pose.joints.j4    # degrees
pose.joints.in_radians()  # same values in radians
```

---

## Movement

All movement methods return a **command index** (int) that can be passed to `wait_for_cmd()`.

### `move_to(x=None, y=None, z=None, r=0, wait=True, mode=None, position=None)`
Move end-effector to an absolute Cartesian position.

- `x, y, z` — target in mm. Any `None` axis keeps its current value.
- `r` — tool rotation in degrees (default 0).
- `wait` — if `True`, blocks until the move completes.
- `mode` — `MODE_PTP` value (default `MOVJ_XYZ`).
- `position` — pass a `Position` object instead of x/y/z/r.

```python
arm.move_to(200, 0, 50)
arm.move_to(200, 0, 50, r=45)
arm.move_to(200, 0, 50, wait=False)               # non-blocking
arm.move_to(200, 0, 50, mode=MODE_PTP.MOVL_XYZ)  # linear path
arm.move_to(position=Position(200, 0, 50, 0))
```

### `move_rel(x=0, y=0, z=0, r=0, wait=True)`
Move relative to the current position.

```python
arm.move_rel(z=20)        # up 20 mm
arm.move_rel(x=10, y=-5)  # relative XY
```

### `home()`
Run the homing sequence. Returns command index.

```python
cmd = arm.home()
arm.wait_for_cmd(cmd)
```

### `set_home(x, y, z, r=0.)`
Set a custom home position (does not move, just stores it).

```python
arm.set_home(200, 0, 50)
```

### `go_arc(x, y, z, r, cir_x, cir_y, cir_z, cir_r)`
Move along a circular arc.

- `x, y, z, r` — arc **end** point.
- `cir_x, cir_y, cir_z, cir_r` — a point on the arc (defines the circle).

Returns command index.

```python
cmd = arm.go_arc(150, 50, 50, 0,   # end point
                 150, 0, 50, 0)     # circle point
arm.wait_for_cmd(cmd)
```

---

## Jogging (Continuous Motion)

Jogging moves continuously at a set velocity. Call `_set_jog_command(0)` to stop.

### `jog_x(v)` / `jog_y(v)` / `jog_z(v)` / `jog_r(v)`
Jog along a single Cartesian axis. `v` is the velocity (positive or negative). Blocks until complete.

```python
arm.jog_x(50)   # move +X at 50 mm/s until limit or stop
arm.jog_x(-50)  # move -X
arm.jog_x(0)    # stop X jog
```

### Low-level jog control (used in GUI)

#### `_set_jog_coordinate_params(vx, vy, vz, vr, ax=100, ay=100, az=100, ar=100)`
Set per-axis jog velocities (mm/s) and accelerations. Only the relevant axis needs a non-zero value.

```python
arm._set_jog_coordinate_params(50, 0, 0, 0)  # 50 mm/s on X
```

#### `_set_jog_command(cmd)`
Send a raw jog direction command. Non-blocking.

| `cmd` | Action |
|-------|--------|
| 0 | Stop |
| 1 | X+ |
| 2 | X− |
| 3 | Y+ |
| 4 | Y− |
| 5 | Z+ |
| 6 | Z− |
| 7 | R+ |
| 8 | R− |

```python
arm._set_jog_coordinate_params(80, 0, 0, 0)
arm._set_jog_command(1)   # start moving X+
time.sleep(0.5)
arm._set_jog_command(0)   # stop
```

---

## Speed & Acceleration

### `speed(velocity=100., acceleration=100.)`
Set global PTP velocity and acceleration (mm/s and mm/s²). Blocks until applied.

```python
arm.speed(velocity=150, acceleration=80)
```

### `_set_ptp_common_params(velocity, acceleration)`
Set percentage-based velocity/acceleration for all PTP moves (0–100%).

### `_set_ptp_coordinate_params(velocity, acceleration)`
Set absolute Cartesian velocity (mm/s) and acceleration (mm/s²).

### `_set_ptp_joint_params(v_x, v_y, v_z, v_r, a_x, a_y, a_z, a_r)`
Set per-joint velocity and acceleration independently.

### `_set_ptp_jump_params(jump, limit)`
Set the jump height and max height for JUMP mode moves.

---

## End Effectors

All effector commands return a command index.

### `suck(enable: bool)`
Control the suction cup.

```python
arm.suck(True)   # vacuum on
arm.suck(False)  # vacuum off
```

### `grip(enable: bool)`
Control the gripper.

```python
arm.grip(True)   # close gripper
arm.grip(False)  # open gripper
```

### `laze(power=0, enable=False)`
Control the laser engraver attachment.

- `power` — 0–255.
- `enable` — `True` to turn laser on.

```python
arm.laze(power=200, enable=True)
arm.laze(enable=False)  # off
```

---

## IO & Sensors

### `set_io(address: int, state: bool)`
Set a GPIO output pin. Address must be 1–22.

```python
arm.set_io(1, True)   # pin 1 high
arm.set_io(5, False)  # pin 5 low
```

### `set_hht_trig_output(state: bool)`
Set the HHT (handheld teaching) trigger output.

### `get_hht_trig_output() → bool`
Read the HHT trigger output state.

---

## Sensors (Add-on modules)

Port constants: `Dobot.PORT_GP1` (0), `PORT_GP2` (1), `PORT_GP4` (2), `PORT_GP5` (3)

### `set_color(enable=True, port=PORT_GP2, version=0x1)`
Enable the colour sensor on a GP port.

```python
arm.set_color(enable=True, port=Dobot.PORT_GP2)
```

### `get_color(port=PORT_GP2, version=0x1) → [r, g, b]`
Read RGB values from the colour sensor. Returns a list of 3 booleans (threshold detections, not raw values).

```python
r, g, b = arm.get_color()
```

### `set_ir(enable=True, port=PORT_GP4)`
Enable the IR proximity sensor on a GP port.

```python
arm.set_ir(enable=True, port=Dobot.PORT_GP4)
```

### `get_ir(port=PORT_GP4) → bool`
Read the IR sensor state. Returns `True` if object detected.

```python
detected = arm.get_ir()
```

---

## Conveyor Belt

### `conveyor_belt(speed, direction=1, interface=0)`
Run the conveyor belt continuously.

- `speed` — 0.0–1.0 (fraction of max speed).
- `direction` — `1` (forward) or `-1` (reverse).
- `interface` — 0 or 1 (which stepper port).

```python
arm.conveyor_belt(0.5)          # half speed forward
arm.conveyor_belt(0.3, direction=-1)  # reverse
arm.conveyor_belt(0)            # stop
```

### `conveyor_belt_distance(speed_mm_per_sec, distance_mm, direction=1, interface=0)`
Move the conveyor belt a specific distance. Max speed 100 mm/s.

```python
arm.conveyor_belt_distance(50, 200)         # 200 mm forward at 50 mm/s
arm.conveyor_belt_distance(30, 100, direction=-1)  # 100 mm reverse
```

---

## Laser Engraving

### `engrave(image, pixel_size, low=0.0, high=40.0, velocity=5, acceleration=5, actual_acceleration=5)`
Engrave a grayscale image using the laser attachment. Starts from the current XY position.

- `image` — NumPy array (grayscale, 0–255). Darker pixels = higher laser power.
- `pixel_size` — mm per pixel.
- `low` / `high` — laser power range mapped from image brightness.
- `velocity` / `acceleration` / `actual_acceleration` — CP motion parameters.

```python
import numpy as np
img = np.array([[0, 128], [255, 64]], dtype=np.uint8)
arm.move_to(150, 0, 30)
arm.engrave(img, pixel_size=1.0)
```

---

## Alarms

### `get_alarms() → Set[Alarm]`
Returns the set of currently active alarms.

```python
alarms = arm.get_alarms()
if alarms:
    print("Active alarms:", alarms)
```

### `clear_alarms()`
Clear all active alarms.

```python
arm.clear_alarms()
```

---

## Queue Management

The Dobot has an internal command queue (max 32 commands). Normally this is managed automatically.

### `wait_for_cmd(cmd_id: int)`
Block until the Dobot has executed up to the given command index.

```python
cmd = arm.move_to(200, 0, 50, wait=False)
# ... do other things ...
arm.wait_for_cmd(cmd)  # now wait for it
```

### `_set_queued_cmd_start_exec()`
Start executing queued commands (called automatically on init).

### `_set_queued_cmd_stop_exec()`
Pause queue execution.

### `_set_queued_cmd_clear()`
Clear all pending commands from the queue.

### `_get_queued_cmd_current_index() → int`
Return the index of the most recently completed command.

---

## Continuous Path (CP) — Internal

Used internally by `engrave()`. Available for advanced use.

### `_set_cp_params(velocity, acceleration, period)`
Set CP mode parameters.

### `_set_cp_cmd(x, y, z)`
Queue a CP waypoint (relative, with laser off).

### `_set_cple_cmd(x, y, z, power, absolute=False)`
Queue a CP waypoint with laser power. `power` is 0–100.

---

## Usage Patterns

### Non-blocking move with callback check
```python
cmd = arm.move_to(200, 50, 30, wait=False)
while arm._get_queued_cmd_current_index() < cmd:
    # update GUI, check sensors, etc.
    time.sleep(0.05)
```

### Pick and place
```python
arm.speed(100, 80)
arm.move_to(200, 0, 80)    # above pick point
arm.move_to(200, 0, 20)    # down to pick
arm.suck(True)
arm.move_to(200, 0, 80)    # lift
arm.move_to(150, 100, 80)  # above place point
arm.move_to(150, 100, 20)  # down to place
arm.suck(False)
arm.move_to(150, 100, 80)  # lift
```

### Jogging with manual stop
```python
arm._set_jog_coordinate_params(60, 0, 0, 0, ax=80)
arm._set_jog_command(1)   # X+ at 60 mm/s
time.sleep(1.0)
arm._set_jog_command(0)   # stop
```
