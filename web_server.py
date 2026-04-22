#!/usr/bin/env python3
"""Dobot Web UI — python web_server.py [port]"""

import copy, json, logging, os, queue, sys, threading, time
from typing import Optional, List

from serial.tools import list_ports
from pydobotplus import Dobot
from flask import Flask, Response, request, jsonify, stream_with_context, send_file

SEQUENCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sequences")
STATIC_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ── Step label ────────────────────────────────────────────────────────────────

def step_label(step: dict) -> str:
    t, p = step["type"], step["params"]
    if t == "move_to":   return f"Move To ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f})"
    if t == "move_rel":  return f"Move Rel ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f})"
    if t == "suction":   return f"Suction {'ON' if p['on'] else 'OFF'}"
    if t == "gripper":   return f"Gripper {'ON' if p['on'] else 'OFF'}"
    if t == "wait":      return f"Wait {p['seconds']:.1f}s"
    if t == "home":      return "Home"
    if t == "speed":     return f"Speed {p['velocity']:.0f} mm/s"
    if t == "set_io":    return f"IO #{p['address']} {'ON' if p['state'] else 'OFF'}"
    if t == "conveyor_belt":
        d   = "FWD" if p["direction"] > 0 else "REV"
        dur = f" {p['duration']:.1f}s" if p["duration"] > 0 else " cont."
        return f"Belt {int(p['speed']*100)}% {d}{dur}"
    if t == "conveyor_belt_distance":
        d = "FWD" if p["direction"] > 0 else "REV"
        return f"Belt {p['distance']:.0f}mm@{p['speed']:.0f}mm/s {d}"
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
            try: self._qs.remove(q)
            except ValueError: pass

    def push(self, data: dict):
        with self._lock:
            if not self._qs:
                return
            qs = list(self._qs)
        msg = json.dumps(data)
        dead = []
        for q in qs:
            try: q.put_nowait(msg)
            except queue.Full: dead.append(q)
        for q in dead:
            self.unsubscribe(q)

hub = SseHub()

# ── DobotCore ─────────────────────────────────────────────────────────────────

class DobotCore:
    def __init__(self):
        self.device: Optional[Dobot] = None
        self.is_connected = False
        self.connecting   = False
        self.available_ports: List[str] = []
        self.port_index = 0
        self.pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "R": 0.0}
        self.running = True

        self.vacuum_on      = False
        self.conv_running   = False
        self.conv_direction = 1
        self.conv_interface = 0

        self.alarms: set = set()
        self._jog_lock  = threading.Lock()
        self._last_jog  = (0.0, 0.0, 0.0)

        self.sequence: List[dict] = []
        self.seq_playing  = False
        self.seq_paused   = False
        self.seq_looping  = False
        self.seq_current  = -1
        self.seq_stop_evt  = threading.Event()
        self.seq_pause_evt = threading.Event()

        self.log_entries: List[dict] = []
        self._setup_logger()
        self.refresh_ports()

    # ── Logger ────────────────────────────────────────────────────────────────

    class _LogHandler(logging.Handler):
        def __init__(self, core):
            super().__init__()
            self._c = core

        def emit(self, record):
            entry = {"level": record.levelname,
                     "msg":   self.format(record),
                     "ts":    time.strftime("%H:%M:%S")}
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
            "type":           "state",
            "connected":      self.is_connected,
            "connecting":     self.connecting,
            "ports":          self.available_ports,
            "port_index":     self.port_index,
            "pos":            self.pos,
            "vacuum":         self.vacuum_on,
            "conv_running":   self.conv_running,
            "conv_direction": self.conv_direction,
            "conv_interface": self.conv_interface,
            "seq_playing":    self.seq_playing,
            "seq_paused":     self.seq_paused,
            "seq_looping":    self.seq_looping,
            "seq_current":    self.seq_current,
            "steps":          self.sequence,
            "logs":           self.log_entries[-80:],
        }

    def _push_state(self):
        hub.push(self.get_state())

    # ── Connection ────────────────────────────────────────────────────────────

    def refresh_ports(self):
        infos = list_ports.comports()
        self.available_ports = [p.device for p in infos]
        if self.available_ports:
            usb = [p.device for p in infos if
                   "USB" in (p.hwid or "").upper() or
                   "USB" in (p.description or "").upper()]
            if usb:
                self.port_index = self.available_ports.index(usb[0])
            self.logger.info(f"Found {len(self.available_ports)} port(s)")
        else:
            self.logger.warning("No COM ports found")
        hub.push({"type": "ports", "ports": self.available_ports, "index": self.port_index})

    def connect(self, port: Optional[str] = None):
        if not self.available_ports and not port:
            self.logger.error("No ports available"); return
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
            try: self.device.close()
            except: pass
        self.device = None
        self.is_connected = False
        self.conv_running = False
        self.logger.info("Disconnected")
        self._push_state()

    def _fetch_pos(self):
        if not (self.is_connected and self.device): return
        try:
            p = self.device.get_pose().position
            self.pos = {"X": p.x, "Y": p.y, "Z": p.z, "R": p.r}
            hub.push({"type": "pos", **self.pos})
        except Exception as e:
            self.logger.warning(f"Pos update failed: {e}")

    def _check_alarms(self):
        if not (self.is_connected and self.device): return
        try:
            self.alarms = self.device.get_alarms()
            if self.alarms:
                self.device.clear_alarms()
                self.logger.warning(f"Cleared alarms: {', '.join(str(a) for a in self.alarms)}")
                self.alarms = set()
        except Exception: pass

    def _start_pos_thread(self):
        def _loop():
            tick = 0
            while self.running and self.is_connected:
                self._fetch_pos()
                tick += 1
                if tick % 4 == 0: self._check_alarms()
                time.sleep(0.5)
        threading.Thread(target=_loop, daemon=True).start()

    def cmd_clear_alarms(self):
        if not self.is_connected: return
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
            if self.device.get_alarms(): self.device.clear_alarms()
            self.device.move_to(x, y, z, r)
        except Exception as e:
            self.logger.error(f"Move failed: {e}")

    def cmd_move_to(self, x, y, z, r):
        if not self.is_connected: return
        self.logger.info(f"Move → X{x:.1f} Y{y:.1f} Z{z:.1f} R{r:.1f}")
        threading.Thread(target=lambda: self._safe_move(x, y, z, r), daemon=True).start()

    def cmd_home(self):
        if not self.is_connected: self.logger.warning("Not connected"); return
        self.logger.info("Homing…")
        threading.Thread(target=self.device.home, daemon=True).start()

    def cmd_jog_step(self, axis: str, sign: int, step: float):
        if not self.is_connected: return
        x = self.pos["X"] + (step * sign if axis == "x" else 0)
        y = self.pos["Y"] + (step * sign if axis == "y" else 0)
        z = self.pos["Z"] + (step * sign if axis == "z" else 0)
        r = self.pos["R"]
        self.logger.info(f"Step {axis.upper()}{'+' if sign > 0 else '-'}{step:.0f} mm")
        threading.Thread(target=lambda: self._safe_move(x, y, z, r), daemon=True).start()

    def handle_jog(self, vx: float, vy: float, vz: float, speed: float):
        if not (self.is_connected and self.device): return
        dz = 0.04
        if abs(vx) < dz: vx = 0
        if abs(vy) < dz: vy = 0
        if abs(vz) < dz: vz = 0
        cur = (round(vx, 3), round(vy, 3), round(vz, 3))
        if cur == self._last_jog: return
        self._last_jog = cur

        def _do():
            if not self._jog_lock.acquire(blocking=False): return
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
                self._jog_lock.release()

        threading.Thread(target=_do, daemon=True).start()

    def toggle_vacuum(self):
        if not self.is_connected: return
        self.vacuum_on = not self.vacuum_on
        state = self.vacuum_on
        threading.Thread(target=lambda: self.device.suck(state), daemon=True).start()
        self.logger.info(f"Vacuum {'ON' if self.vacuum_on else 'OFF'}")
        hub.push({"type": "vacuum", "on": self.vacuum_on})

    def cmd_conveyor(self, speed: float, direction: int, interface: int):
        if not self.is_connected: return
        self.conv_running   = speed > 0
        self.conv_direction = direction
        self.conv_interface = interface
        d, i = direction, interface
        threading.Thread(target=lambda: self.device.conveyor_belt(speed, d, i),
                         daemon=True).start()
        if speed > 0:
            self.logger.info(f"Conveyor {int(speed*100)}% {'FWD' if direction > 0 else 'REV'} iface={interface}")
        else:
            self.logger.info("Conveyor stopped")
        hub.push({"type": "conveyor", "running": self.conv_running,
                  "speed": speed, "direction": direction, "interface": interface})

    # ── Sequence management ───────────────────────────────────────────────────

    def _push_steps(self):
        hub.push({"type": "steps", "steps": self.sequence})

    def seq_insert(self, idx: int, step: dict):
        self.sequence.insert(idx, step); self._push_steps()

    def seq_delete(self, idx: int):
        if 0 <= idx < len(self.sequence):
            self.sequence.pop(idx); self._push_steps()

    def seq_update(self, idx: int, step: dict):
        if 0 <= idx < len(self.sequence):
            self.sequence[idx] = step; self._push_steps()

    def seq_move(self, idx: int, delta: int):
        ni = idx + delta
        if 0 <= ni < len(self.sequence):
            self.sequence[idx], self.sequence[ni] = self.sequence[ni], self.sequence[idx]
            self._push_steps()

    def seq_dup(self, idx: int):
        if 0 <= idx < len(self.sequence):
            self.sequence.insert(idx + 1, copy.deepcopy(self.sequence[idx]))
            self._push_steps()

    def seq_clear(self):
        self.sequence.clear(); self._push_steps()

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
            self.logger.error(f"Load failed: {e}"); return None

    def seq_files(self) -> List[str]:
        if not os.path.isdir(SEQUENCES_DIR): return []
        return sorted(f for f in os.listdir(SEQUENCES_DIR) if f.endswith(".json"))

    def seq_play(self):
        if not self.is_connected: self.logger.warning("Not connected"); return
        if not self.sequence:     self.logger.warning("Sequence empty"); return
        if self.seq_playing: return
        threading.Thread(target=self._seq_run, daemon=True).start()

    def seq_pause_toggle(self):
        if not self.seq_playing: return
        self.seq_paused = not self.seq_paused
        if self.seq_paused: self.seq_pause_evt.clear()
        else:               self.seq_pause_evt.set()
        self._push_seq_state()

    def seq_stop(self):
        self.seq_stop_evt.set(); self.seq_pause_evt.set()

    def seq_loop_toggle(self) -> bool:
        self.seq_looping = not self.seq_looping
        return self.seq_looping

    def _push_seq_state(self):
        hub.push({"type": "seq_state",
                  "playing": self.seq_playing,  "paused":  self.seq_paused,
                  "current": self.seq_current,  "looping": self.seq_looping})

    def _seq_run(self):
        self.seq_playing = True
        self.seq_stop_evt.clear(); self.seq_pause_evt.set()
        steps = list(self.sequence)
        try:
            self.device.clear_alarms()
            self.device._set_queued_cmd_stop_exec()
            self.device._set_queued_cmd_clear()
            self.device._set_queued_cmd_start_exec()
            time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"Queue reset: {e}")
        try:
            while True:
                for i, step in enumerate(steps):
                    if self.seq_stop_evt.is_set(): return
                    self.seq_pause_evt.wait()
                    if self.seq_stop_evt.is_set(): return
                    self.seq_current = i; self._push_seq_state()
                    self.logger.info(f"Step {i+1}/{len(steps)}: {step_label(step)}")
                    self._seq_exec(step)
                if not self.seq_looping: break
                try:
                    self.device.clear_alarms()
                    self.device._set_queued_cmd_stop_exec()
                    self.device._set_queued_cmd_clear()
                    self.device._set_queued_cmd_start_exec()
                    time.sleep(0.1)
                except Exception: pass
        except Exception as e:
            self.logger.error(f"Playback error at step {self.seq_current + 1}: {e}")
        finally:
            self.seq_playing = False; self.seq_paused = False; self.seq_current = -1
            self._push_seq_state()

    def _seq_exec(self, step):
        t, p = step["type"], step["params"]
        try:
            if self.device.get_alarms(): self.device.clear_alarms()
        except Exception: pass

        if t == "move_to":
            self._seq_wait(self.device.move_to(p["x"], p["y"], p["z"], p["r"], wait=False))
        elif t == "move_rel":
            c = self.device.get_pose().position
            self._seq_wait(self.device.move_to(
                c.x + p["x"], c.y + p["y"], c.z + p["z"], c.r + p["r"], wait=False))
        elif t == "suction":  self.device.suck(p["on"]); time.sleep(0.3)
        elif t == "gripper":  self.device.grip(p["on"]); time.sleep(0.3)
        elif t == "wait":     self.seq_stop_evt.wait(timeout=p["seconds"])
        elif t == "home":     self._seq_wait(self.device.home())
        elif t == "speed":    self.device.speed(p["velocity"], p["acceleration"])
        elif t == "set_io":   self.device.set_io(p["address"], p["state"])
        elif t == "conveyor_belt":
            spd = p["speed"]
            self.conv_running   = spd > 0
            self.conv_direction = p["direction"]
            self.conv_interface = p["interface"]
            hub.push({"type": "conveyor", "running": self.conv_running,
                      "speed": spd, "direction": p["direction"], "interface": p["interface"]})
            self.device.conveyor_belt(spd, p["direction"], p["interface"])
            if p["duration"] > 0:
                self.seq_stop_evt.wait(timeout=p["duration"])
                self.device.conveyor_belt(0, p["direction"], p["interface"])
                self.conv_running = False
                hub.push({"type": "conveyor", "running": False,
                          "speed": 0, "direction": p["direction"], "interface": p["interface"]})
        elif t == "conveyor_belt_distance":
            self.conv_running   = True
            self.conv_direction = p["direction"]
            self.conv_interface = p["interface"]
            hub.push({"type": "conveyor", "running": True,
                      "speed": p["speed"], "direction": p["direction"], "interface": p["interface"]})
            self.device.conveyor_belt_distance(
                p["speed"], p["distance"], p["direction"], p["interface"])
            self.conv_running = False
            hub.push({"type": "conveyor", "running": False,
                      "speed": 0, "direction": p["direction"], "interface": p["interface"]})

    def _seq_wait(self, cmd_idx):
        if cmd_idx is None: return
        self.seq_stop_evt.wait(timeout=0.15)
        if self.seq_stop_evt.is_set(): return
        timeout = time.time() + 120
        while not self.seq_stop_evt.is_set():
            try:
                if self.device._get_queued_cmd_current_index() >= cmd_idx: return
            except Exception: return
            if time.time() > timeout:
                self.logger.warning("Step timed out"); return
            self.seq_stop_evt.wait(timeout=0.1)


# ── Flask app ─────────────────────────────────────────────────────────────────

core = DobotCore()
app  = Flask(__name__)


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

def ok(): return jsonify(ok=True)


@app.post("/api/refresh")
def api_refresh():
    core.refresh_ports(); return ok()

@app.post("/api/connect")
def api_connect():
    d = request.get_json(force=True) or {}
    core.connect(d.get("port")); return ok()

@app.post("/api/disconnect")
def api_disconnect():
    core.disconnect(); return ok()

@app.post("/api/home")
def api_home():
    core.cmd_home(); return ok()

@app.post("/api/clear_alarms")
def api_clear_alarms():
    core.cmd_clear_alarms(); return ok()

@app.post("/api/move_to")
def api_move_to():
    d = request.json
    core.cmd_move_to(d["x"], d["y"], d["z"], d["r"]); return ok()

@app.post("/api/jog_step")
def api_jog_step():
    d = request.json
    core.cmd_jog_step(d["axis"], d["sign"], d["step"]); return ok()

@app.post("/api/jog")
def api_jog():
    d = request.json
    core.handle_jog(d["vx"], d["vy"], d["vz"], d["speed"])
    return "", 204

@app.post("/api/vacuum")
def api_vacuum():
    core.toggle_vacuum(); return jsonify(on=core.vacuum_on)

@app.post("/api/conveyor")
def api_conveyor():
    d = request.json
    core.cmd_conveyor(d["speed"], d["direction"], d["interface"]); return ok()

# Sequence
@app.post("/api/sequence/insert")
def api_seq_insert():
    d = request.json; core.seq_insert(d["idx"], d["step"]); return ok()

@app.delete("/api/sequence/<int:idx>")
def api_seq_delete(idx):
    core.seq_delete(idx); return ok()

@app.put("/api/sequence/<int:idx>")
def api_seq_update(idx):
    core.seq_update(idx, request.json); return ok()

@app.post("/api/sequence/move")
def api_seq_move():
    d = request.json; core.seq_move(d["idx"], d["delta"]); return ok()

@app.post("/api/sequence/<int:idx>/dup")
def api_seq_dup(idx):
    core.seq_dup(idx); return ok()

@app.post("/api/sequence/clear")
def api_seq_clear():
    core.seq_clear(); return ok()

@app.post("/api/sequence/save")
def api_seq_save():
    core.seq_save(request.json["name"]); return ok()

@app.get("/api/sequence/files")
def api_seq_files():
    return jsonify(files=core.seq_files())

@app.post("/api/sequence/load")
def api_seq_load():
    name = core.seq_load(request.json["filename"])
    return jsonify(ok=name is not None, name=name, steps=core.sequence)

@app.post("/api/sequence/play")
def api_seq_play():
    core.seq_play(); return ok()

@app.post("/api/sequence/pause")
def api_seq_pause():
    core.seq_pause_toggle(); return ok()

@app.post("/api/sequence/stop")
def api_seq_stop():
    core.seq_stop(); return ok()

@app.post("/api/sequence/loop")
def api_seq_loop():
    looping = core.seq_loop_toggle(); return jsonify(looping=looping)


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
    d    = request.get_json(force=True) or {}
    port = _PORT_MAP.get(d.get("port", "GP2"), Dobot.PORT_GP2)
    try:
        core.device.set_color(enable=True, port=port)
        rgb = core.device.get_color(port=port)
        return jsonify(r=bool(rgb[0]), g=bool(rgb[1]), b=bool(rgb[2]))
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.post("/api/ir_sensor")
def api_ir_sensor():
    if not core.is_connected:
        return jsonify(error="Not connected"), 400
    d    = request.get_json(force=True) or {}
    port = _PORT_MAP.get(d.get("port", "GP4"), Dobot.PORT_GP4)
    try:
        core.device.set_ir(enable=True, port=port)
        detected = core.device.get_ir(port=port)
        return jsonify(detected=bool(detected))
    except Exception as e:
        return jsonify(error=str(e)), 500


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"\n  Dobot Web UI  →  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
