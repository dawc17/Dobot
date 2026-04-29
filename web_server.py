#!/usr/bin/env python3
"""Dobot Web UI — python web_server.py [port]"""

import copy
import json
import logging
import os
import queue
import sys
import threading
import time
from typing import List, Optional

from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from pydobotplus import Dobot
from serial.tools import list_ports

SEQUENCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sequences")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
POSITIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "positions.json"
)

# ── Step label ────────────────────────────────────────────────────────────────


def step_label(step: dict) -> str:
    t, p = step["type"], step["params"]
    speed_suffix = f" @{p['speed']:.0f}mm/s" if p.get("speed") else ""
    if t == "move_to":
        return f"Move To ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f}){speed_suffix}"
    if t == "move_rel":
        return f"Move Rel ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f}){speed_suffix}"
    if t == "move_to_named":
        offs = [
            f"d{a}{p[k]:+.1f}"
            for a, k in [("X", "dx"), ("Y", "dy"), ("Z", "dz"), ("R", "dr")]
            if p.get(k, 0)
        ]
        speed_suffix = f" @{p['speed']:.0f}mm/s" if p.get("speed") else ""
        return (
            f"→ '{p.get('name', '?')}'"
            + (f" {' '.join(offs)}" if offs else "")
            + speed_suffix
        )
    if t == "suction":
        return f"Suction {'ON' if p['on'] else 'OFF'}"
    if t == "gripper":
        return f"Gripper {'ON' if p['on'] else 'OFF'}"
    if t == "wait":
        return f"Wait {p['seconds']:.1f}s"
    if t == "home":
        return "Home"
    if t == "speed":
        return f"Speed {p['velocity']:.0f} mm/s"
    if t == "set_io":
        return f"IO #{p['address']} {'ON' if p['state'] else 'OFF'}"
    if t == "conveyor_belt":
        d = "FWD" if p["direction"] > 0 else "REV"
        dur = f" {p['duration']:.1f}s" if p["duration"] > 0 else " cont."
        return f"Belt {int(p['speed'] * 100)}% {d}{dur}"
    if t == "conveyor_belt_distance":
        d = "FWD" if p["direction"] > 0 else "REV"
        return f"Belt {p['distance']:.0f}mm@{p['speed']:.0f}mm/s {d}"
    if t == "color_branch":
        parts = []
        if p.get("on_red", 0) > 0:
            parts.append(f"R→{p['on_red']}")
        if p.get("on_green", 0) > 0:
            parts.append(f"G→{p['on_green']}")
        if p.get("on_blue", 0) > 0:
            parts.append(f"B→{p['on_blue']}")
        return f"Color Branch {', '.join(parts) if parts else '(no branches set)'}"
    if t == "wait_for_color":
        colors = [
            c
            for c, k in [("R", "wait_r"), ("G", "wait_g"), ("B", "wait_b")]
            if p.get(k)
        ]
        to = f" {p.get('timeout', 10):.0f}s" if p.get("timeout", 10) > 0 else " ∞"
        return f"Wait Color {'|'.join(colors) or '?'}{to}"
    if t == "loop_n":
        return f"Loop {p.get('count', 1)} times"
    if t == "wait_io":
        return f"Wait IO #{p.get('address', 1)} {'HIGH' if p.get('state', True) else 'LOW'}"
    if t == "run_sequence":
        return f"Run Sequence '{p.get('filename', '?')}'"
    return t


# ── SSE broadcast ─────────────────────────────────────────────────────────────


class SseHub:
    def __init__(self):
        self._qs: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._qs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            try:
                self._qs.remove(q)
            except ValueError:
                pass

    def push(self, data: dict):
        with self._lock:
            if not self._qs:
                return
            qs = list(self._qs)
        msg = json.dumps(data)
        dead = []
        for q in qs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)


hub = SseHub()

# ── DobotCore ─────────────────────────────────────────────────────────────────


class DobotCore:
    def __init__(self):
        self.device: Optional[Dobot] = None
        self.is_connected = False
        self.connecting = False
        self.available_ports: List[str] = []
        self.port_index = 0
        self.pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "R": 0.0}
        self.running = True

        self.vacuum_on = False
        self.conv_running = False
        self.conv_direction = 1
        self.conv_interface = 0

        self.alarms: set = set()
        self._dev_lock = threading.Lock()  # serialises all device serial I/O
        self._jog_lock = threading.Lock()
        self._last_jog = (0.0, 0.0, 0.0)
        self._color_enabled: Optional[int] = None
        self._ir_enabled: Optional[int] = None

        self.sequence: List[dict] = []
        self.seq_playing = False
        self.seq_paused = False
        self.seq_looping = False
        self.seq_current = -1
        self.seq_stop_evt = threading.Event()
        self.seq_pause_evt = threading.Event()
        self._seq_jump: Optional[int] = None  # set by color_branch to jump to a step

        # Teach mode
        self.teach_recording = False
        self.teach_last_pos = None

        # Loop state
        self.loop_stack = []  # Stack of {start, end, count, remaining} for nested loops

        self.named_positions: dict = {}

        self.log_entries: List[dict] = []
        self._setup_logger()
        self._load_positions()
        self.refresh_ports()

    # ── Logger ────────────────────────────────────────────────────────────────

    class _LogHandler(logging.Handler):
        def __init__(self, core):
            super().__init__()
            self._c = core

        def emit(self, record):
            entry = {
                "level": record.levelname,
                "msg": self.format(record),
                "ts": time.strftime("%H:%M:%S"),
            }
            c = self._c
            c.log_entries.append(entry)
            if len(c.log_entries) > 200:
                c.log_entries.pop(0)
            hub.push({"type": "log", **entry})

    def _setup_logger(self):
        self.logger = logging.getLogger("dobot")
        self.logger.setLevel(logging.INFO)
        h = self._LogHandler(self)
        h.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(h)

    # ── State snapshot ────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "type": "state",
            "connected": self.is_connected,
            "connecting": self.connecting,
            "ports": self.available_ports,
            "port_index": self.port_index,
            "pos": self.pos,
            "vacuum": self.vacuum_on,
            "conv_running": self.conv_running,
            "conv_direction": self.conv_direction,
            "conv_interface": self.conv_interface,
            "seq_playing": self.seq_playing,
            "seq_paused": self.seq_paused,
            "seq_looping": self.seq_looping,
            "seq_current": self.seq_current,
            "steps": self.sequence,
            "positions": self.named_positions,
            "teach_recording": self.teach_recording,
            "logs": self.log_entries[-80:],
        }

    def _push_state(self):
        hub.push(self.get_state())

    # ── Connection ────────────────────────────────────────────────────────────

    def refresh_ports(self):
        infos = list_ports.comports()
        self.available_ports = [p.device for p in infos]
        if self.available_ports:
            usb = [
                p.device
                for p in infos
                if "USB" in (p.hwid or "").upper()
                or "USB" in (p.description or "").upper()
            ]
            if usb:
                self.port_index = self.available_ports.index(usb[0])
            self.logger.info(f"Found {len(self.available_ports)} port(s)")
        else:
            self.logger.warning("No COM ports found")
        hub.push(
            {"type": "ports", "ports": self.available_ports, "index": self.port_index}
        )

    def connect(self, port: Optional[str] = None):
        if not self.available_ports and not port:
            self.logger.error("No ports available")
            return
        target = port or self.available_ports[self.port_index]
        self.connecting = True
        self._push_state()

        def _do():
            try:
                self.logger.info(f"Connecting to {target}…")
                self.device = Dobot(port=target)
                self.is_connected = True
                self.logger.info("Connected")
                self.device.clear_alarms()
                time.sleep(0.3)
                self._fetch_pos()
                self._start_pos_thread()
            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
            finally:
                self.connecting = False
                self._push_state()

        threading.Thread(target=_do, daemon=True).start()

    def disconnect(self):
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self.is_connected = False
        self.conv_running = False
        self._color_enabled = None
        self._ir_enabled = None
        self.logger.info("Disconnected")
        self._push_state()

    def _fetch_pos(self):
        if not (self.is_connected and self.device):
            return
        if not self._dev_lock.acquire(blocking=False):
            return  # a command is running; skip this poll cycle
        try:
            p = self.device.get_pose().position
            self.pos = {"X": p.x, "Y": p.y, "Z": p.z, "R": p.r}
            hub.push({"type": "pos", **self.pos})
        except Exception as e:
            self.logger.warning(f"Pos update failed: {e}")
        finally:
            self._dev_lock.release()

    def _check_alarms(self):
        if not (self.is_connected and self.device):
            return
        try:
            self.alarms = self.device.get_alarms()
            if self.alarms:
                self.device.clear_alarms()
                self.logger.warning(
                    f"Cleared alarms: {', '.join(str(a) for a in self.alarms)}"
                )
                self.alarms = set()
        except Exception:
            pass

    def _start_pos_thread(self):
        def _loop():
            tick = 0
            while self.running and self.is_connected:
                self._fetch_pos()
                tick += 1
                if tick % 4 == 0:
                    self._check_alarms()
                time.sleep(0.5)

        threading.Thread(target=_loop, daemon=True).start()

    def cmd_clear_alarms(self):
        if not self.is_connected:
            return

        def _do():
            try:
                self.device.clear_alarms()
                self.device._set_queued_cmd_clear()
                self.device._set_queued_cmd_start_exec()
                self.alarms = set()
                self.logger.info("Alarms cleared, queue reset")
            except Exception as e:
                self.logger.error(f"Clear alarms failed: {e}")

        threading.Thread(target=_do, daemon=True).start()

    # ── Manual control ────────────────────────────────────────────────────────

    def _safe_move(self, x, y, z, r):
        try:
            if self.device.get_alarms():
                self.device.clear_alarms()
            self.device.move_to(x, y, z, r)
        except Exception as e:
            self.logger.error(f"Move failed: {e}")

    def cmd_move_to(self, x, y, z, r):
        if not self.is_connected:
            return
        self.logger.info(f"Move → X{x:.1f} Y{y:.1f} Z{z:.1f} R{r:.1f}")
        threading.Thread(
            target=lambda: self._safe_move(x, y, z, r), daemon=True
        ).start()

    def cmd_home(self):
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        self.logger.info("Homing…")
        threading.Thread(target=self.device.home, daemon=True).start()

    def cmd_jog_step(self, axis: str, sign: int, step: float):
        if not self.is_connected:
            return
        x = self.pos["X"] + (step * sign if axis == "x" else 0)
        y = self.pos["Y"] + (step * sign if axis == "y" else 0)
        z = self.pos["Z"] + (step * sign if axis == "z" else 0)
        r = self.pos["R"]
        self.logger.info(f"Step {axis.upper()}{'+' if sign > 0 else '-'}{step:.0f} mm")
        threading.Thread(
            target=lambda: self._safe_move(x, y, z, r), daemon=True
        ).start()

    def handle_jog(self, vx: float, vy: float, vz: float, speed: float):
        if not (self.is_connected and self.device):
            return
        dz = 0.04
        if abs(vx) < dz:
            vx = 0
        if abs(vy) < dz:
            vy = 0
        if abs(vz) < dz:
            vz = 0
        cur = (round(vx, 3), round(vy, 3), round(vz, 3))
        if cur == self._last_jog:
            return
        self._last_jog = cur

        def _do():
            if not self._jog_lock.acquire(blocking=False):
                return
            if not self._dev_lock.acquire(blocking=False):
                self._jog_lock.release()
                return
            try:
                if vx == 0 and vy == 0 and vz == 0:
                    self.device._set_jog_command(0)
                elif abs(vx) >= abs(vy) and abs(vx) >= abs(vz):
                    self.device._set_jog_coordinate_params(abs(vx * speed), 0, 0, 0)
                    self.device._set_jog_command(1 if vx > 0 else 2)
                elif abs(vy) >= abs(vz):
                    self.device._set_jog_coordinate_params(0, abs(vy * speed), 0, 0)
                    self.device._set_jog_command(3 if vy > 0 else 4)
                else:
                    self.device._set_jog_coordinate_params(0, 0, abs(vz * speed), 0)
                    self.device._set_jog_command(5 if vz > 0 else 6)
            except Exception as e:
                self.logger.error(f"Jog error: {e}")
            finally:
                self._dev_lock.release()
                self._jog_lock.release()

        threading.Thread(target=_do, daemon=True).start()

    def set_vacuum(self, on: bool):
        if not self.is_connected:
            return
        self.vacuum_on = on
        self.logger.info(f"Vacuum {'ON' if on else 'OFF'}")
        hub.push({"type": "vacuum", "on": on})

        def _do():
            with self._dev_lock:
                try:
                    self.device.suck(on)
                except Exception as e:
                    self.logger.error(f"Vacuum error: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def cmd_conveyor(self, speed: float, direction: int, interface: int):
        if not self.is_connected:
            return
        self.conv_running = speed > 0
        self.conv_direction = direction
        self.conv_interface = interface
        d, i = direction, interface
        threading.Thread(
            target=lambda: self.device.conveyor_belt(speed, d, i), daemon=True
        ).start()
        if speed > 0:
            self.logger.info(
                f"Conveyor {int(speed * 100)}% {'FWD' if direction > 0 else 'REV'} iface={interface}"
            )
        else:
            self.logger.info("Conveyor stopped")
        hub.push(
            {
                "type": "conveyor",
                "running": self.conv_running,
                "speed": speed,
                "direction": direction,
                "interface": interface,
            }
        )

    # ── Sequence management ───────────────────────────────────────────────────

    def _push_steps(self):
        hub.push({"type": "steps", "steps": self.sequence})

    def seq_insert(self, idx: int, step: dict):
        self.sequence.insert(idx, step)
        self._push_steps()

    def seq_delete(self, idx: int):
        if 0 <= idx < len(self.sequence):
            self.sequence.pop(idx)
            self._push_steps()

    def seq_update(self, idx: int, step: dict):
        if 0 <= idx < len(self.sequence):
            self.sequence[idx] = step
            self._push_steps()

    def seq_move(self, idx: int, delta: int):
        ni = idx + delta
        if 0 <= ni < len(self.sequence):
            self.sequence[idx], self.sequence[ni] = (
                self.sequence[ni],
                self.sequence[idx],
            )
            self._push_steps()

    def seq_dup(self, idx: int):
        if 0 <= idx < len(self.sequence):
            self.sequence.insert(idx + 1, copy.deepcopy(self.sequence[idx]))
            self._push_steps()

    def seq_clear(self):
        self.sequence.clear()
        self._push_steps()

    def seq_save(self, name: str):
        name = "".join(c for c in name if c.isalnum() or c in "-_ ") or "untitled"
        os.makedirs(SEQUENCES_DIR, exist_ok=True)
        path = os.path.join(SEQUENCES_DIR, f"{name}.json")
        with open(path, "w") as f:
            json.dump({"name": name, "version": 1, "steps": self.sequence}, f, indent=2)
        self.logger.info(f"Saved: {name} ({len(self.sequence)} steps)")

    def seq_load(self, filename: str) -> Optional[str]:
        try:
            with open(os.path.join(SEQUENCES_DIR, filename)) as f:
                data = json.load(f)
            self.sequence = data.get("steps", [])
            name = data.get("name", filename.replace(".json", ""))
            self.logger.info(f"Loaded: {name} ({len(self.sequence)} steps)")
            self._push_steps()
            return name
        except Exception as e:
            self.logger.error(f"Load failed: {e}")
            return None

    def seq_files(self) -> List[str]:
        if not os.path.isdir(SEQUENCES_DIR):
            return []
        return sorted(f for f in os.listdir(SEQUENCES_DIR) if f.endswith(".json"))

    # ── Script file management ────────────────────────────────────────────────

    def script_save(self, name: str, workspace_xml: str, code: str) -> str:
        safe = "".join(c for c in str(name) if c.isalnum() or c in "-_ ") or "script"
        safe = safe.strip() or "script"
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        path = os.path.join(SCRIPTS_DIR, f"{safe}.json")
        payload = {
            "name": safe,
            "version": 1,
            "workspace_xml": str(workspace_xml or ""),
            "code": str(code or ""),
            "saved_at": int(time.time()),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        self.logger.info(f"Script saved: {safe}")
        return safe

    def script_files(self) -> List[str]:
        if not os.path.isdir(SCRIPTS_DIR):
            return []
        return sorted(f for f in os.listdir(SCRIPTS_DIR) if f.endswith(".json"))

    def script_load(self, filename: str) -> Optional[dict]:
        fn = os.path.basename(str(filename or ""))
        if not fn:
            return None
        if not fn.endswith(".json"):
            fn += ".json"
        path = os.path.join(SCRIPTS_DIR, fn)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            name = str(data.get("name") or fn.replace(".json", ""))
            workspace_xml = str(data.get("workspace_xml") or "")
            code = str(data.get("code") or "")
            self.logger.info(f"Script loaded: {name}")
            return {
                "name": name,
                "workspace_xml": workspace_xml,
                "code": code,
                "filename": fn,
            }
        except Exception as e:
            self.logger.error(f"Script load failed: {e}")
            return None

    # ── Named positions ───────────────────────────────────────────────────────

    def _load_positions(self):
        try:
            if os.path.exists(POSITIONS_FILE):
                with open(POSITIONS_FILE) as f:
                    self.named_positions = json.load(f)
        except Exception:
            self.named_positions = {}

    def _persist_positions(self):
        try:
            with open(POSITIONS_FILE, "w") as f:
                json.dump(self.named_positions, f, indent=2)
        except Exception as e:
            self.logger.error(f"Save positions failed: {e}")

    def save_named_position(self, name: str, x: float, y: float, z: float, r: float):
        name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
        if not name:
            return
        self.named_positions[name] = {"x": x, "y": y, "z": z, "r": r}
        self._persist_positions()
        hub.push({"type": "positions", "positions": self.named_positions})
        self.logger.info(
            f"Saved position '{name}': X{x:.1f} Y{y:.1f} Z{z:.1f} R{r:.1f}"
        )

    def delete_named_position(self, name: str):
        if name in self.named_positions:
            del self.named_positions[name]
            self._persist_positions()
            hub.push({"type": "positions", "positions": self.named_positions})
            self.logger.info(f"Deleted position '{name}'")

    def go_named_position(self, name: str, dx: float, dy: float, dz: float, dr: float):
        if name not in self.named_positions:
            self.logger.error(f"Position '{name}' not found")
            return
        p = self.named_positions[name]
        self.cmd_move_to(p["x"] + dx, p["y"] + dy, p["z"] + dz, p["r"] + dr)

    # ── Teach mode ────────────────────────────────────────────────────────────

    def teach_start(self):
        """Start teach mode recording"""
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        self.teach_recording = True
        self.teach_last_pos = None
        hub.push({"type": "teach_mode", "recording": True})
        self.logger.info(
            "Teach mode started - move arm and press capture to record waypoints"
        )

    def teach_stop(self):
        """Stop teach mode recording"""
        self.teach_recording = False
        self.teach_last_pos = None
        hub.push({"type": "teach_mode", "recording": False})
        self.logger.info("Teach mode stopped")

    def teach_capture(self):
        """Capture current position as a waypoint in teach mode"""
        if not self.teach_recording or not self.is_connected:
            return

        current_pos = self.pos.copy()

        # Skip if position hasn't changed significantly (< 1mm)
        if self.teach_last_pos:
            dx = abs(current_pos["X"] - self.teach_last_pos["X"])
            dy = abs(current_pos["Y"] - self.teach_last_pos["Y"])
            dz = abs(current_pos["Z"] - self.teach_last_pos["Z"])
            dr = abs(current_pos["R"] - self.teach_last_pos["R"])
            if dx < 1.0 and dy < 1.0 and dz < 1.0 and dr < 5.0:
                self.logger.info("Position unchanged - skipping waypoint")
                return

        step = {
            "type": "move_to",
            "params": {
                "x": current_pos["X"],
                "y": current_pos["Y"],
                "z": current_pos["Z"],
                "r": current_pos["R"],
            },
        }

        self.sequence.append(step)
        self.teach_last_pos = current_pos
        self._push_steps()
        self.logger.info(
            f"Waypoint captured: X{current_pos['X']:.1f} Y{current_pos['Y']:.1f} Z{current_pos['Z']:.1f} R{current_pos['R']:.1f}"
        )

    # ── Color Sort Wizard ─────────────────────────────────────────────────────

    def create_color_sort_sequence(
        self, red_pos=None, green_pos=None, blue_pos=None, pick_height=50
    ):
        """Generate a complete color sorting sequence"""
        if not red_pos and not green_pos and not blue_pos:
            self.logger.error("At least one bin position must be provided")
            return

        steps = []

        # Add home step
        steps.append({"type": "home", "params": {}})

        # Set speed for sorting
        steps.append(
            {"type": "speed", "params": {"velocity": 100, "acceleration": 100}}
        )

        # Wait for object on conveyor (IR sensor)
        steps.append(
            {
                "type": "wait_for_color",
                "params": {
                    "wait_r": True,
                    "wait_g": True,
                    "wait_b": True,
                    "timeout": 0,
                },
            }
        )

        # Read color and branch
        branches = {}
        step_num = 5  # Starting after the above steps

        if red_pos:
            branches["on_red"] = step_num
            step_num += 4  # Each color sequence takes ~4 steps
        if green_pos:
            branches["on_green"] = step_num
            step_num += 4
        if blue_pos:
            branches["on_blue"] = step_num

        steps.append({"type": "color_branch", "params": branches})

        # Add sequences for each color
        for color, pos in [("red", red_pos), ("green", green_pos), ("blue", blue_pos)]:
            if pos:
                # Move to pick position
                steps.append(
                    {
                        "type": "move_to",
                        "params": {
                            "x": pos["x"],
                            "y": pos["y"],
                            "z": pos["z"] + pick_height,
                            "r": pos["r"],
                        },
                    }
                )
                # Move down to pick
                steps.append(
                    {
                        "type": "move_to",
                        "params": {
                            "x": pos["x"],
                            "y": pos["y"],
                            "z": pos["z"],
                            "r": pos["r"],
                        },
                    }
                )
                # Turn on suction
                steps.append({"type": "suction", "params": {"on": True}})
                # Move up
                steps.append(
                    {
                        "type": "move_to",
                        "params": {
                            "x": pos["x"],
                            "y": pos["y"],
                            "z": pos["z"] + pick_height,
                            "r": pos["r"],
                        },
                    }
                )
                # Move to bin and release
                # Note: In a real implementation, you'd have separate bin positions
                steps.append({"type": "suction", "params": {"on": False}})

        # Replace current sequence
        self.sequence = steps
        self._push_steps()
        self.logger.info(f"Color sort sequence created with {len(steps)} steps")

    # ── Sequence playback ─────────────────────────────────────────────────────

    def run_script(self, code: str):
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        if self.seq_playing:
            self.logger.warning("Playback running")
            return

        def _do():
            class _ScriptStopped(Exception):
                pass

            self.seq_playing = True
            self.seq_stop_evt.clear()
            self._push_seq_state()
            script_stopped_by_user = False
            script_conv_state = {
                "cmd": None,  # tuple(speed, dir, iface)
                "managed": False,
            }

            try:
                def _check_stopped():
                    if self.seq_stop_evt.is_set():
                        raise _ScriptStopped()

                def sync_move_to(x, y, z, r):
                    _check_stopped()
                    self._safe_move(x, y, z, r)

                def sync_move_named(name, dx=0, dy=0, dz=0, dr=0):
                    _check_stopped()
                    n = str(name or "").strip()
                    pos = self.named_positions.get(n)
                    if not pos:
                        self.logger.error(f"Named position '{n}' not found")
                        return
                    try:
                        x = float(pos["x"]) + float(dx)
                        y = float(pos["y"]) + float(dy)
                        z = float(pos["z"]) + float(dz)
                        r = float(pos["r"]) + float(dr)
                    except Exception:
                        self.logger.error(
                            f"Invalid named position values for '{n}'"
                        )
                        return
                    self._safe_move(x, y, z, r)

                def script_sleep(seconds=0.0):
                    try:
                        s = max(0.0, float(seconds))
                    except Exception:
                        s = 0.0
                    self.seq_stop_evt.wait(timeout=s)
                    _check_stopped()

                def script_conveyor(speed, direction=1, interface=0):
                    _check_stopped()
                    try:
                        spd = max(0.0, min(1.0, float(speed)))
                    except Exception:
                        spd = 0.0
                    d = 1 if float(direction) >= 0 else -1
                    try:
                        i = int(interface)
                    except Exception:
                        i = 0
                    if i not in (0, 1):
                        i = 0
                    cmd = (round(spd, 4), d, i)
                    if script_conv_state["cmd"] == cmd:
                        return
                    script_conv_state["cmd"] = cmd
                    script_conv_state["managed"] = True
                    self.cmd_conveyor(spd, d, i)

                def ir_detected(port="GP4"):
                    _check_stopped()
                    port_map = {
                        "GP1": Dobot.PORT_GP1,
                        "GP2": Dobot.PORT_GP2,
                        "GP4": Dobot.PORT_GP4,
                        "GP5": Dobot.PORT_GP5,
                    }
                    p = port
                    if isinstance(port, str):
                        p = port_map.get(port.strip().upper(), Dobot.PORT_GP4)
                    elif isinstance(port, (int, float)):
                        idx = max(0, min(3, int(port)))
                        p = [
                            Dobot.PORT_GP1,
                            Dobot.PORT_GP2,
                            Dobot.PORT_GP4,
                            Dobot.PORT_GP5,
                        ][idx]
                    if self._dev_lock.acquire(timeout=2.0):
                        try:
                            if self._ir_enabled != p:
                                self.device.set_ir(enable=True, port=p)
                                time.sleep(0.15)
                                self._ir_enabled = p
                            return bool(self.device.get_ir(port=p))
                        except _ScriptStopped:
                            raise
                        except Exception as e:
                            self._ir_enabled = None
                            self.logger.warning(f"IR read: {e}")
                            return False
                        finally:
                            self._dev_lock.release()
                    return False

                def debug_ir(port="GP2"):
                    _check_stopped()
                    p = str(port or "GP2").strip().upper()
                    state = ir_detected(p)
                    self.logger.info(f"IR {p}: {'DETECTED' if state else 'clear'}")
                    return state

                def stopped():
                    return self.seq_stop_evt.is_set()

                class _ScriptDeviceProxy:
                    def __init__(self, real):
                        self._real = real

                    def conveyor_belt(self, speed, direction=1, interface=0):
                        return script_conveyor(speed, direction, interface)

                    def __getattr__(self, name):
                        return getattr(self._real, name)

                class _ScriptTimeProxy:
                    def __init__(self, real):
                        self._real = real

                    def sleep(self, seconds=0.0):
                        return script_sleep(seconds)

                    def __getattr__(self, name):
                        return getattr(self._real, name)

                env = {
                    "core": self,
                    "device": _ScriptDeviceProxy(self.device),
                    "time": _ScriptTimeProxy(time),
                    "log": self.logger.info,
                    "sync_move_to": sync_move_to,
                    "sync_move_named": sync_move_named,
                    "move_named": sync_move_named,
                    "sleep": script_sleep,
                    "script_sleep": script_sleep,
                    "script_conveyor": script_conveyor,
                    "conveyor_set": script_conveyor,
                    "named_positions": self.named_positions,
                    "ir_detected": ir_detected,
                    "read_ir": ir_detected,
                    "debug_ir": debug_ir,
                    "debug_ir_gp2": lambda: debug_ir("GP2"),
                    "stopped": stopped,
                    "Dobot": Dobot,
                }
                exec(code, env)
            except _ScriptStopped:
                script_stopped_by_user = True
                self.logger.info("Script stopped")
            except Exception as e:
                self.logger.error(f"Script error: {e}")
            finally:
                try:
                    if script_conv_state["managed"] and (
                        script_stopped_by_user or self.seq_stop_evt.is_set()
                    ):
                        last = script_conv_state["cmd"] or (0.0, 1, 0)
                        if last[0] > 0:
                            self.cmd_conveyor(0.0, last[1], last[2])
                except Exception:
                    pass
                self.seq_playing = False
                self.seq_current = -1
                self._push_seq_state()

        threading.Thread(target=_do, daemon=True).start()

    def seq_play(self):
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        if not self.sequence:
            self.logger.warning("Sequence empty")
            return
        if self.seq_playing:
            return
        threading.Thread(target=self._seq_run, daemon=True).start()

    def seq_pause_toggle(self):
        if not self.seq_playing:
            return
        self.seq_paused = not self.seq_paused
        if self.seq_paused:
            self.seq_pause_evt.clear()
        else:
            self.seq_pause_evt.set()
        self._push_seq_state()

    def seq_stop(self):
        self.seq_stop_evt.set()
        self.seq_pause_evt.set()

    def seq_loop_toggle(self) -> bool:
        self.seq_looping = not self.seq_looping
        return self.seq_looping

    def _push_seq_state(self):
        hub.push(
            {
                "type": "seq_state",
                "playing": self.seq_playing,
                "paused": self.seq_paused,
                "current": self.seq_current,
                "looping": self.seq_looping,
            }
        )

    def _seq_run(self):
        self.seq_playing = True
        self.seq_stop_evt.clear()
        self.seq_pause_evt.set()

        def _reset_queue():
            try:
                self.device.clear_alarms()
                self.device._set_queued_cmd_stop_exec()
                self.device._set_queued_cmd_clear()
                self.device._set_queued_cmd_start_exec()
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Queue reset: {e}")

        _reset_queue()
        try:
            while True:
                steps = list(self.sequence)
                i = 0
                while i < len(steps):
                    if self.seq_stop_evt.is_set():
                        return
                    self.seq_pause_evt.wait()
                    if self.seq_stop_evt.is_set():
                        return
                    self.seq_current = i
                    self._push_seq_state()
                    self.logger.info(
                        f"Step {i + 1}/{len(steps)}: {step_label(steps[i])}"
                    )
                    self._seq_jump = None
                    self._seq_exec(steps[i])
                    if self._seq_jump is not None:
                        self.logger.info(f"Branch → step {self._seq_jump + 1}")
                        i = self._seq_jump
                    else:
                        i += 1
                if not self.seq_looping:
                    break
                _reset_queue()
        except Exception as e:
            self.logger.error(f"Playback error at step {self.seq_current + 1}: {e}")
        finally:
            self.seq_playing = False
            self.seq_paused = False
            self.seq_current = -1
            self._push_seq_state()

    def _seq_exec(self, step):
        t, p = step["type"], step["params"]
        try:
            if self.device.get_alarms():
                self.device.clear_alarms()
        except Exception:
            pass

        if t == "move_to":
            if p.get("speed"):
                self.device.speed(p["speed"], 100)  # Use default acceleration
            self._seq_wait(
                self.device.move_to(p["x"], p["y"], p["z"], p["r"], wait=False)
            )
        elif t == "move_rel":
            if p.get("speed"):
                self.device.speed(p["speed"], 100)  # Use default acceleration
            c = self.device.get_pose().position
            self._seq_wait(
                self.device.move_to(
                    c.x + p["x"], c.y + p["y"], c.z + p["z"], c.r + p["r"], wait=False
                )
            )
        elif t == "suction":
            self.device.suck(p["on"])
            time.sleep(0.3)
        elif t == "gripper":
            self.device.grip(p["on"])
            time.sleep(0.3)
        elif t == "wait":
            self.seq_stop_evt.wait(timeout=p["seconds"])
        elif t == "home":
            self._seq_wait(self.device.home())
        elif t == "speed":
            self.device.speed(p["velocity"], p["acceleration"])
        elif t == "set_io":
            self.device.set_io(p["address"], p["state"])
        elif t == "conveyor_belt":
            spd = p["speed"]
            self.conv_running = spd > 0
            self.conv_direction = p["direction"]
            self.conv_interface = p["interface"]
            hub.push(
                {
                    "type": "conveyor",
                    "running": self.conv_running,
                    "speed": spd,
                    "direction": p["direction"],
                    "interface": p["interface"],
                }
            )
            self.device.conveyor_belt(spd, p["direction"], p["interface"])
            if p["duration"] > 0:
                self.seq_stop_evt.wait(timeout=p["duration"])
                self.device.conveyor_belt(0, p["direction"], p["interface"])
                self.conv_running = False
                hub.push(
                    {
                        "type": "conveyor",
                        "running": False,
                        "speed": 0,
                        "direction": p["direction"],
                        "interface": p["interface"],
                    }
                )
        elif t == "color_branch":
            _PORTS = [Dobot.PORT_GP1, Dobot.PORT_GP2, Dobot.PORT_GP4, Dobot.PORT_GP5]
            port = _PORTS[min(max(int(p.get("port", 1)), 0), 3)]
            rgb = [False, False, False]
            if self._dev_lock.acquire(timeout=2.0):
                try:
                    if self._color_enabled != port:
                        self.device.set_color(enable=True, port=port)
                        time.sleep(0.15)
                        self._color_enabled = port
                    rgb = list(self.device.get_color(port=port))
                except Exception as e:
                    self.logger.warning(f"Color read: {e}")
                finally:
                    self._dev_lock.release()
            detected = (
                "/".join(
                    c for c, v in [("R", rgb[0]), ("G", rgb[1]), ("B", rgb[2])] if v
                )
                or "none"
            )
            target = int(p.get("on_none", 0))
            if rgb[0] and int(p.get("on_red", 0)) > 0:
                target = int(p["on_red"])
            elif rgb[1] and int(p.get("on_green", 0)) > 0:
                target = int(p["on_green"])
            elif rgb[2] and int(p.get("on_blue", 0)) > 0:
                target = int(p["on_blue"])
            self.logger.info(
                f"Color: {detected} → {'step ' + str(target) if target > 0 else 'continue'}"
            )
            if target > 0:
                self._seq_jump = (
                    target - 1
                )  # stored as 1-based; convert to 0-based index
        elif t == "wait_for_color":
            _PORTS = [Dobot.PORT_GP1, Dobot.PORT_GP2, Dobot.PORT_GP4, Dobot.PORT_GP5]
            port = _PORTS[min(max(int(p.get("port", 1)), 0), 3)]
            want_r = bool(p.get("wait_r", False))
            want_g = bool(p.get("wait_g", False))
            want_b = bool(p.get("wait_b", False))
            timeout = float(p.get("timeout", 10.0))
            deadline = time.time() + timeout if timeout > 0 else None
            # enable once
            if self._dev_lock.acquire(timeout=2.0):
                try:
                    if self._color_enabled != port:
                        self.device.set_color(enable=True, port=port)
                        time.sleep(0.15)
                        self._color_enabled = port
                except Exception as e:
                    self.logger.warning(f"Color enable: {e}")
                finally:
                    self._dev_lock.release()
            while not self.seq_stop_evt.is_set():
                if deadline and time.time() > deadline:
                    self.logger.warning("wait_for_color timed out")
                    break
                if self._dev_lock.acquire(blocking=False):
                    try:
                        rgb = self.device.get_color(port=port)
                        if (
                            (want_r and rgb[0])
                            or (want_g and rgb[1])
                            or (want_b and rgb[2])
                        ):
                            detected = "/".join(
                                c
                                for c, v in [
                                    ("R", rgb[0]),
                                    ("G", rgb[1]),
                                    ("B", rgb[2]),
                                ]
                                if v
                            )
                            self.logger.info(f"Color detected: {detected}")
                            break
                    except Exception:
                        pass
                    finally:
                        self._dev_lock.release()
                self.seq_stop_evt.wait(timeout=0.1)
        elif t == "move_to_named":
            name = p.get("name", "")
            pos = self.named_positions.get(name)
            if not pos:
                self.logger.error(f"Named position '{name}' not found")
                return
            if p.get("speed"):
                self.device.speed(p["speed"], 100)  # Use default acceleration
            self._seq_wait(
                self.device.move_to(
                    pos["x"] + p.get("dx", 0),
                    pos["y"] + p.get("dy", 0),
                    pos["z"] + p.get("dz", 0),
                    pos["r"] + p.get("dr", 0),
                    wait=False,
                )
            )
        elif t == "conveyor_belt_distance":
            self.conv_running = True
            self.conv_direction = p["direction"]
            self.conv_interface = p["interface"]
            hub.push(
                {
                    "type": "conveyor",
                    "running": True,
                    "speed": p["speed"],
                    "direction": p["direction"],
                    "interface": p["interface"],
                }
            )
            self.device.conveyor_belt_distance(
                p["speed"], p["distance"], p["direction"], p["interface"]
            )
            self.conv_running = False
            hub.push(
                {
                    "type": "conveyor",
                    "running": False,
                    "speed": 0,
                    "direction": p["direction"],
                    "interface": p["interface"],
                }
            )
        elif t == "wait_io":
            address = p.get("address", 1)
            target_state = p.get("state", True)
            timeout = p.get("timeout", 0)  # 0 = no timeout
            deadline = time.time() + timeout if timeout > 0 else None
            self.logger.info(
                f"Waiting for IO #{address} {'HIGH' if target_state else 'LOW'}..."
            )
            while not self.seq_stop_evt.is_set():
                try:
                    current_state = self.device.get_io(address)
                    if current_state == target_state:
                        self.logger.info(f"IO #{address} condition met")
                        break
                except Exception as e:
                    self.logger.warning(f"IO read error: {e}")
                if deadline and time.time() > deadline:
                    self.logger.warning(f"IO wait timeout on #{address}")
                    break
                self.seq_stop_evt.wait(timeout=0.1)
        elif t == "run_sequence":
            filename = p.get("filename", "")
            if not filename.endswith(".json"):
                filename += ".json"
            seq_path = os.path.join(SEQUENCES_DIR, filename)
            if os.path.exists(seq_path):
                try:
                    with open(seq_path) as f:
                        sub_data = json.load(f)
                    sub_steps = sub_data.get("steps", [])
                    self.logger.info(
                        f"Running sub-sequence '{filename}' ({len(sub_steps)} steps)"
                    )
                    for sub_step in sub_steps:
                        if self.seq_stop_evt.is_set():
                            break
                        self.seq_pause_evt.wait()
                        if self.seq_stop_evt.is_set():
                            break
                        self._seq_exec(sub_step)
                except Exception as e:
                    self.logger.error(f"Sub-sequence '{filename}' failed: {e}")
            else:
                self.logger.error(f"Sub-sequence file not found: {filename}")
        elif t == "loop_n":
            count = p.get("count", 1)
            self.logger.info(f"Starting loop: {count} iterations")

    def _seq_wait(self, cmd_idx):
        if cmd_idx is None:
            return
        self.seq_stop_evt.wait(timeout=0.15)
        if self.seq_stop_evt.is_set():
            return
        timeout = time.time() + 120
        while not self.seq_stop_evt.is_set():
            try:
                if self.device._get_queued_cmd_current_index() >= cmd_idx:
                    return
            except Exception:
                return
            if time.time() > timeout:
                self.logger.warning("Step timed out")
                return
            self.seq_stop_evt.wait(timeout=0.1)


# ── Flask app ─────────────────────────────────────────────────────────────────

core = DobotCore()
app = Flask(__name__)


@app.route("/")
def index():
    return send_file(os.path.join(STATIC_DIR, "index.html"))


@app.route("/events")
def events():
    q = hub.subscribe()

    def stream():
        try:
            yield f"data: {json.dumps(core.get_state())}\n\n"
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            hub.unsubscribe(q)

    return Response(
        stream_with_context(stream()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── API routes ────────────────────────────────────────────────────────────────


def ok():
    return jsonify(ok=True)


@app.post("/api/refresh")
def api_refresh():
    core.refresh_ports()
    return ok()


@app.post("/api/connect")
def api_connect():
    d = request.get_json(force=True) or {}
    core.connect(d.get("port"))
    return ok()


@app.post("/api/disconnect")
def api_disconnect():
    core.disconnect()
    return ok()


@app.post("/api/home")
def api_home():
    core.cmd_home()
    return ok()


@app.post("/api/clear_alarms")
def api_clear_alarms():
    core.cmd_clear_alarms()
    return ok()


@app.post("/api/move_to")
def api_move_to():
    d = request.json
    core.cmd_move_to(d["x"], d["y"], d["z"], d["r"])
    return ok()


@app.post("/api/jog_step")
def api_jog_step():
    d = request.json
    core.cmd_jog_step(d["axis"], d["sign"], d["step"])
    return ok()


@app.post("/api/jog")
def api_jog():
    d = request.json
    core.handle_jog(d["vx"], d["vy"], d["vz"], d["speed"])
    return "", 204


@app.post("/api/vacuum")
def api_vacuum():
    d = request.get_json(force=True) or {}
    on = bool(d["on"]) if "on" in d else not core.vacuum_on
    core.set_vacuum(on)
    return jsonify(on=core.vacuum_on)


@app.post("/api/conveyor")
def api_conveyor():
    d = request.json
    core.cmd_conveyor(d["speed"], d["direction"], d["interface"])
    return ok()


# Sequence
@app.post("/api/sequence/insert")
def api_seq_insert():
    d = request.json
    core.seq_insert(d["idx"], d["step"])
    return ok()


@app.delete("/api/sequence/<int:idx>")
def api_seq_delete(idx):
    core.seq_delete(idx)
    return ok()


@app.put("/api/sequence/<int:idx>")
def api_seq_update(idx):
    core.seq_update(idx, request.json)
    return ok()


@app.post("/api/sequence/move")
def api_seq_move():
    d = request.json
    core.seq_move(d["idx"], d["delta"])
    return ok()


@app.post("/api/sequence/<int:idx>/dup")
def api_seq_dup(idx):
    core.seq_dup(idx)
    return ok()


@app.post("/api/sequence/clear")
def api_seq_clear():
    core.seq_clear()
    return ok()


@app.post("/api/sequence/save")
def api_seq_save():
    core.seq_save(request.json["name"])
    return ok()


@app.get("/api/sequence/files")
def api_seq_files():
    return jsonify(files=core.seq_files())


@app.post("/api/sequence/load")
def api_seq_load():
    name = core.seq_load(request.json["filename"])
    return jsonify(ok=name is not None, name=name, steps=core.sequence)


@app.post("/api/sequence/play")
def api_seq_play():
    core.seq_play()
    return ok()


@app.post("/api/sequence/pause")
def api_seq_pause():
    core.seq_pause_toggle()
    return ok()


@app.post("/api/run_script")
def api_run_script():
    d = request.get_json(force=True) or {}
    code = d.get("code")
    if code:
        core.run_script(code)
    return ok()


@app.post("/api/scripts/save")
def api_scripts_save():
    d = request.get_json(force=True) or {}
    name = str(d.get("name", "")).strip()
    if not name:
        return jsonify(error="name required"), 400
    saved = core.script_save(
        name=name,
        workspace_xml=str(d.get("workspace_xml", "")),
        code=str(d.get("code", "")),
    )
    return jsonify(ok=True, name=saved)


@app.get("/api/scripts/files")
def api_scripts_files():
    return jsonify(files=core.script_files())


@app.post("/api/scripts/load")
def api_scripts_load():
    d = request.get_json(force=True) or {}
    data = core.script_load(d.get("filename", ""))
    if not data:
        return jsonify(ok=False, error="not found"), 404
    return jsonify(ok=True, **data)


@app.post("/api/sequence/stop")
def api_seq_stop():
    core.seq_stop()
    return ok()


@app.post("/api/sequence/loop")
def api_seq_loop():
    looping = core.seq_loop_toggle()
    return jsonify(looping=looping)


_PORT_MAP = {
    "GP1": Dobot.PORT_GP1,
    "GP2": Dobot.PORT_GP2,
    "GP4": Dobot.PORT_GP4,
    "GP5": Dobot.PORT_GP5,
}


@app.post("/api/color_sensor")
def api_color_sensor():
    if not core.is_connected:
        return jsonify(error="Not connected"), 400
    d = request.get_json(force=True) or {}
    port = _PORT_MAP.get(d.get("port", "GP2"), Dobot.PORT_GP2)
    try:
        if core._color_enabled != port:
            core.device.set_color(enable=True, port=port)
            time.sleep(0.15)
            core._color_enabled = port
        rgb = core.device.get_color(port=port)
        return jsonify(r=bool(rgb[0]), g=bool(rgb[1]), b=bool(rgb[2]))
    except Exception as e:
        core._color_enabled = None
        return jsonify(error=str(e)), 500


@app.post("/api/ir_sensor")
def api_ir_sensor():
    if not core.is_connected:
        return jsonify(error="Not connected"), 400
    d = request.get_json(force=True) or {}
    port = _PORT_MAP.get(d.get("port", "GP4"), Dobot.PORT_GP4)
    try:
        if core._ir_enabled != port:
            core.device.set_ir(enable=True, port=port)
            time.sleep(0.15)
            core._ir_enabled = port
        detected = core.device.get_ir(port=port)
        return jsonify(detected=bool(detected))
    except Exception as e:
        core._ir_enabled = None
        return jsonify(error=str(e)), 500


@app.get("/api/positions")
def api_positions_list():
    return jsonify(positions=core.named_positions)


@app.post("/api/positions")
def api_positions_save():
    d = request.get_json(force=True) or {}
    name = str(d.get("name", "")).strip()
    if not name:
        return jsonify(error="name required"), 400
    x = float(d.get("x", core.pos["X"]))
    y = float(d.get("y", core.pos["Y"]))
    z = float(d.get("z", core.pos["Z"]))
    r = float(d.get("r", core.pos["R"]))
    core.save_named_position(name, x, y, z, r)
    return ok()


@app.delete("/api/positions/<name>")
def api_positions_delete(name):
    core.delete_named_position(name)
    return ok()


@app.post("/api/positions/<name>/go")
def api_positions_go(name):
    d = request.get_json(force=True) or {}
    core.go_named_position(
        name,
        float(d.get("dx", 0)),
        float(d.get("dy", 0)),
        float(d.get("dz", 0)),
        float(d.get("dr", 0)),
    )
    return ok()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"\n  Dobot Web UI  →  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
