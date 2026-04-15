#!/usr/bin/env python3
"""Dobot Raylib GUI Controller with Sequence Editor"""

import copy
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional, List
from serial.tools import list_ports
from pydobotplus import Dobot
import pyray as rl
from pyray import *

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG         = Color(22,  22,  30,  255)
C_PANEL      = Color(32,  32,  44,  255)
C_PANEL_DARK = Color(26,  26,  36,  255)
C_BORDER     = Color(52,  52,  70,  255)
C_SEP        = Color(48,  48,  65,  255)
C_TEXT       = Color(225, 225, 235, 255)
C_DIM        = Color(140, 140, 158, 255)
C_MUTED      = Color(82,  82,  100, 255)
C_ACCENT     = Color(65,  125, 195, 255)
C_ACCENT_H   = Color(85,  145, 215, 255)
C_ACCENT_P   = Color(48,  105, 172, 255)
C_DANGER     = Color(175, 58,  58,  255)
C_DANGER_H   = Color(198, 75,  75,  255)
C_DANGER_P   = Color(150, 42,  42,  255)
C_SUCCESS    = Color(48,  172, 95,  255)
C_SUCCESS_H  = Color(65,  192, 112, 255)
C_TRACK      = Color(45,  45,  60,  255)
C_THUMB      = Color(85,  135, 190, 255)
C_THUMB_A    = Color(108, 160, 215, 255)
C_OK         = Color(48,  195, 98,  255)
C_BAD        = Color(195, 68,  68,  255)
C_WARN       = Color(205, 158, 52,  255)
C_ERR        = Color(215, 75,  75,  255)

# ── Layout ────────────────────────────────────────────────────────────────────
W, H      = 1280, 860
PAD       = 12
HDR_H     = 96
COL_W     = 450
COL_RX    = PAD + COL_W + PAD        # 474
COL_RW    = 298                       # narrowed for sequence panel
SEQ_X     = COL_RX + COL_RW + PAD    # 784
SEQ_W     = W - SEQ_X - PAD          # 484
LOG_Y     = 548
LOG_H     = H - LOG_Y - PAD
ROUND     = 0.12
FSM       = 13
FMD       = 15
FLG       = 17
BTN_H     = 30
INP_H     = 28

# Sequence list geometry
SEQ_LIST_Y  = 196
SEQ_LIST_H  = 248
SEQ_ROW_H   = 28
SEQ_MAX_VIS = SEQ_LIST_H // SEQ_ROW_H  # 8

# Sequences directory
SEQUENCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sequences")

# ── Step helpers ──────────────────────────────────────────────────────────────

STEP_TYPES = [
    "move_to", "move_rel", "suction", "gripper",
    "wait", "home", "speed", "set_io",
]

STEP_TYPE_COLORS = {
    "move_to": C_ACCENT, "move_rel": C_ACCENT_H,
    "suction": C_SUCCESS, "gripper": C_SUCCESS_H,
    "wait": C_WARN, "home": C_DIM,
    "speed": C_THUMB, "set_io": C_ERR,
}


def step_label(step: dict) -> str:
    t, p = step["type"], step["params"]
    if t == "move_to":   return f"Move To  ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f})"
    if t == "move_rel":  return f"Move Rel ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}, {p['r']:.1f})"
    if t == "suction":   return f"Suction {'ON' if p['on'] else 'OFF'}"
    if t == "gripper":   return f"Gripper {'ON' if p['on'] else 'OFF'}"
    if t == "wait":      return f"Wait {p['seconds']:.1f}s"
    if t == "home":      return "Home"
    if t == "speed":     return f"Speed {p['velocity']:.0f} mm/s"
    if t == "set_io":    return f"IO #{p['address']} {'ON' if p['state'] else 'OFF'}"
    return t


# ── Log ───────────────────────────────────────────────────────────────────────
@dataclass
class LogEntry:
    level: str
    msg: str
    ts: str


class LogHandler(logging.Handler):
    def __init__(self, cap=150):
        super().__init__()
        self.entries: List[LogEntry] = []
        self._cap = cap

    def emit(self, record):
        self.entries.append(LogEntry(record.levelname, self.format(record), time.strftime("%H:%M:%S")))
        if len(self.entries) > self._cap:
            self.entries.pop(0)


# ── Widgets ───────────────────────────────────────────────────────────────────

def _rrec(x, y, w, h): return Rectangle(float(x), float(y), float(w), float(h))


def draw_panel(x, y, w, h, title=""):
    draw_rectangle_rounded(_rrec(x, y, w, h), ROUND, 6, C_PANEL)
    draw_rectangle_rounded_lines_ex(_rrec(x, y, w, h), ROUND, 6, 1.0, C_BORDER)
    if title:
        draw_text(title, x + 10, y + 9, FSM, C_DIM)
        draw_line(x + 8, y + 27, x + w - 8, y + 27, C_SEP)


def dlabel(text, x, y, color=None, size=FSM):
    draw_text(text, int(x), int(y), size, color or C_DIM)


class Button:
    NORMAL  = "normal"
    DANGER  = "danger"
    SUCCESS = "success"
    GHOST   = "ghost"

    def __init__(self, x, y, w, h, text, style=NORMAL):
        self.rect  = _rrec(x, y, w, h)
        self.text  = text
        self.style = style
        self.enabled = True

    def _cols(self):
        if self.style == self.DANGER:  return C_DANGER,  C_DANGER_H,  C_DANGER_P
        if self.style == self.SUCCESS: return C_SUCCESS,  C_SUCCESS_H, C_SUCCESS
        if self.style == self.GHOST:   return Color(0,0,0,0), C_BORDER, C_PANEL_DARK
        return C_ACCENT, C_ACCENT_H, C_ACCENT_P

    def draw(self):
        mp = get_mouse_position()
        hov = check_collision_point_rec(mp, self.rect) and self.enabled
        prs = hov and is_mouse_button_down(MOUSE_BUTTON_LEFT)
        b, h_, a = self._cols()
        col = (Color(40, 40, 52, 255) if not self.enabled
               else a if prs else h_ if hov else b)
        draw_rectangle_rounded(self.rect, 0.22, 4, col)
        if self.style == self.GHOST:
            lc = C_DIM if hov else C_BORDER
            draw_rectangle_rounded_lines_ex(self.rect, 0.22, 4, 1.0, lc)
        tw = measure_text(self.text, FMD)
        tx = int(self.rect.x + (self.rect.width  - tw) / 2)
        ty = int(self.rect.y + (self.rect.height - FMD) / 2)
        draw_text(self.text, tx, ty, FMD, C_TEXT if self.enabled else C_MUTED)

    def clicked(self):
        if not self.enabled:
            return False
        mp = get_mouse_position()
        return (check_collision_point_rec(mp, self.rect)
                and is_mouse_button_pressed(MOUSE_BUTTON_LEFT))

    def move(self, x, y):
        self.rect.x, self.rect.y = float(x), float(y)


class Slider:
    def __init__(self, x, y, w, mn, mx, val, auto_center=False):
        self.x, self.y, self.w = x, y, w
        self.h = 6
        self.mn, self.mx, self.value = mn, mx, val
        self.auto_center = auto_center
        self.dragging = False

    def _n(self): return (self.value - self.mn) / (self.mx - self.mn)

    def draw(self):
        draw_rectangle_rounded(_rrec(self.x, self.y, self.w, self.h), 1.0, 4, C_TRACK)
        fw = self._n() * self.w
        if fw > 1:
            draw_rectangle_rounded(_rrec(self.x, self.y, fw, self.h), 1.0, 4, C_ACCENT)

        tx = self.x + self._n() * self.w
        tr = _rrec(tx - 9, self.y - 8, 18, self.h + 16)
        mp = get_mouse_position()
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and check_collision_point_rec(mp, tr):
            self.dragging = True
        if is_mouse_button_released(MOUSE_BUTTON_LEFT):
            self.dragging = False
            if self.auto_center:
                self.value = 0
        if self.dragging:
            self.value = self.mn + max(0.0, min(1.0, (mp.x - self.x) / self.w)) * (self.mx - self.mn)

        tc = C_THUMB_A if self.dragging else C_THUMB
        draw_circle(int(tx), int(self.y + self.h / 2), 9, tc)
        draw_circle_lines(int(tx), int(self.y + self.h / 2), 9, C_BORDER)
        draw_text(f"{self.value:.0f}", int(self.x + self.w + 10), int(self.y - 4), FMD, C_TEXT)

    def get(self): return self.value


class InputField:
    def __init__(self, x, y, w, initial=""):
        self.rect = _rrec(x, y, w, INP_H)
        self.text = initial
        self.active = False
        self.max_len = 10

    def draw(self):
        mp = get_mouse_position()
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
            self.active = check_collision_point_rec(mp, self.rect)
        bg  = Color(42, 42, 57, 255) if self.active else Color(34, 34, 47, 255)
        brd = C_ACCENT if self.active else C_BORDER
        draw_rectangle_rounded(self.rect, 0.2, 4, bg)
        draw_rectangle_rounded_lines_ex(self.rect, 0.2, 4, 1.5 if self.active else 1.0, brd)
        if self.active:
            k = get_char_pressed()
            while k > 0:
                if 32 <= k <= 126 and len(self.text) < self.max_len:
                    self.text += chr(k)
                k = get_char_pressed()
            if is_key_pressed(KEY_BACKSPACE) and self.text:
                self.text = self.text[:-1]
        draw_text(self.text, int(self.rect.x + 8), int(self.rect.y + (INP_H - FMD) / 2), FMD, C_TEXT)
        if self.active and int(get_time() * 2) % 2 == 0:
            cx = int(self.rect.x + 8 + measure_text(self.text, FMD))
            draw_line(cx, int(self.rect.y + 5), cx, int(self.rect.y + INP_H - 5), C_TEXT)

    def get(self):  return self.text
    def set(self, v): self.text = str(v)


class Joystick:
    def __init__(self, cx, cy, radius):
        self.cx, self.cy, self.r = cx, cy, radius
        self.vx = self.vy = 0.0
        self.active = False

    def draw(self):
        draw_circle(int(self.cx), int(self.cy), self.r, C_PANEL_DARK)
        draw_circle_lines(int(self.cx), int(self.cy), self.r, C_BORDER)
        for rr in (self.r * 0.5, self.r * 0.85):
            draw_circle_lines(int(self.cx), int(self.cy), rr, C_SEP)
        draw_line(int(self.cx), int(self.cy - self.r + 6),
                  int(self.cx), int(self.cy + self.r - 6), C_SEP)
        draw_line(int(self.cx - self.r + 6), int(self.cy),
                  int(self.cx + self.r - 6), int(self.cy), C_SEP)

        mp = get_mouse_position()
        in_r = check_collision_point_circle(mp, Vector2(self.cx, self.cy), self.r)
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and in_r:
            self.active = True
        if is_mouse_button_released(MOUSE_BUTTON_LEFT):
            self.active = False
            self.vx = self.vy = 0.0
        if self.active:
            dx, dy = mp.x - self.cx, mp.y - self.cy
            d = (dx*dx + dy*dy) ** 0.5
            max_d = self.r - 16
            if d > max_d:
                s = max_d / d; dx *= s; dy *= s
            self.vx = dx / max_d
            self.vy = dy / max_d

        sx = self.cx + self.vx * (self.r - 16)
        sy = self.cy + self.vy * (self.r - 16)
        draw_circle(int(sx) + 2, int(sy) + 2, 15, Color(0, 0, 0, 80))
        sc = C_THUMB_A if self.active else C_THUMB
        draw_circle(int(sx), int(sy), 15, sc)
        draw_circle_lines(int(sx), int(sy), 15, Color(160, 160, 180, 200))

        dlabel("X+", self.cx + self.r + 6, self.cy - 6, C_MUTED)
        dlabel("X−", self.cx - self.r - 22, self.cy - 6, C_MUTED)
        dlabel("Y+", self.cx - 8, self.cy - self.r - 16, C_MUTED)
        dlabel("Y−", self.cx - 8, self.cy + self.r + 4, C_MUTED)

    def set_kb(self, vx, vy):
        if not self.active:
            self.vx = max(-1.0, min(1.0, vx))
            self.vy = max(-1.0, min(1.0, vy))


# ── Main app ──────────────────────────────────────────────────────────────────

class DobotController:

    def __init__(self):
        init_window(W, H, "Dobot Controller")
        set_target_fps(60)

        self.device: Optional[Dobot] = None
        self.is_connected = False
        self.connecting   = False
        self.available_ports: List[str] = []
        self.port_index = 0

        self.pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "R": 0.0}
        self.running = True

        self.logger = logging.getLogger("dobot")
        self.logger.setLevel(logging.INFO)
        self.log_handler = LogHandler()
        self.log_handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(self.log_handler)

        self.vacuum_on = False
        self.jog_step  = 20.0
        self.last_jog  = (0.0, 0.0, 0.0)
        self._kb_vx    = 0.0
        self._kb_vy    = 0.0
        self.alarms: set = set()
        self._jog_lock = threading.Lock()  # serialize jog commands off main thread

        # ── Sequence state ────────────────────────────────────────────────────
        self.sequence: List[dict] = []
        self.seq_selected    = -1
        self.seq_scroll      = 0
        self.seq_playing     = False
        self.seq_paused      = False
        self.seq_looping     = False
        self.seq_current     = -1      # step index during playback
        self.seq_stop_evt    = threading.Event()
        self.seq_pause_evt   = threading.Event()
        self.seq_editing     = -1      # step index being edited inline
        self.seq_edit_fields: List[InputField] = []
        self.seq_load_picker = False   # True when file picker is open
        self.seq_files: List[str] = []
        self.seq_file_scroll = 0

        self._build_ui()
        self.refresh_ports()
        self.logger.info("Controller started")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        lx = PAD
        rx = COL_RX

        # ── Header ────────────────────────────────────────────────────────────
        self.btn_port_prev = Button(lx,               62, 26, 26, "<", Button.GHOST)
        self.btn_port_next = Button(lx + 26 + 108 + 4, 62, 26, 26, ">", Button.GHOST)
        ref_x = lx + 26 + 108 + 4 + 26 + 6
        self.btn_refresh   = Button(ref_x, 62, 78, 26, "Refresh", Button.GHOST)
        self.btn_connect   = Button(W - PAD - 88 - PAD - 88, 62, 88, 26, "Connect")
        self.btn_home      = Button(W - PAD - 88,            62, 88, 26, "Home", Button.GHOST)

        # ── Move To ───────────────────────────────────────────────────────────
        iw = 95
        self.inp_x = InputField(lx + 48,       228, iw, "200")
        self.inp_y = InputField(lx + 48 + 178, 228, iw, "0")
        self.inp_z = InputField(lx + 48,       268, iw, "50")
        self.inp_r = InputField(lx + 48 + 178, 268, iw, "0")
        self.btn_use_curr = Button(lx + 8,   306, 148, BTN_H, "Use Current", Button.GHOST)
        self.btn_move     = Button(lx + 162, 306, 130, BTN_H, "Move To")

        # ── Quick Jog ─────────────────────────────────────────────────────────
        sw, sg = 50, 6
        self.step_btns = [
            (5.0,  Button(lx + 8 + 0*(sw+sg), 404, sw, 26, "5",  Button.GHOST)),
            (10.0, Button(lx + 8 + 1*(sw+sg), 404, sw, 26, "10", Button.GHOST)),
            (20.0, Button(lx + 8 + 2*(sw+sg), 404, sw, 26, "20", Button.GHOST)),
            (50.0, Button(lx + 8 + 3*(sw+sg), 404, sw, 26, "50", Button.GHOST)),
        ]
        bw, bh, bg = 66, 30, 5
        self.jog_row1 = [Button(lx + 8 + i*(bw+bg), 438, bw, bh, t)
                         for i, t in enumerate(["X −", "X +", "Y −", "Y +"])]
        self.btn_zm = Button(lx + 8,       476, bw, bh, "Z −")
        self.btn_zp = Button(lx + 8+bw+bg, 476, bw, bh, "Z +")

        # ── Joystick (right col) ──────────────────────────────────────────────
        joy_cx = rx + COL_RW // 2
        joy_cy = 100 + 36 + 100
        self.joystick = Joystick(joy_cx, joy_cy, 96)

        # ── Controls (right col) ──────────────────────────────────────────────
        cw = COL_RW - 60
        self.z_slider     = Slider(rx + 12, 406, cw, -100, 100,  0, auto_center=True)
        self.speed_slider = Slider(rx + 12, 454, cw,    5, 200, 50)
        self.btn_vacuum   = Button(rx + 12, 496, 130, BTN_H, "Vacuum OFF")
        self.btn_clear_alarms = Button(rx + 150, 496, 130, BTN_H, "Clear Alarms", Button.DANGER)

        # ── Sequence panel ────────────────────────────────────────────────────
        sx = SEQ_X
        inner = SEQ_W - 16
        bw4 = (inner - 3 * 6) // 4   # ~112px per button

        # Record buttons row 1 (y=132)
        self.btn_add_pos  = Button(sx+8,             132, bw4, 26, "+ Position", Button.GHOST)
        self.btn_add_suck = Button(sx+8+(bw4+6),     132, bw4, 26, "+ Suction",  Button.GHOST)
        self.btn_add_grip = Button(sx+8+2*(bw4+6),   132, bw4, 26, "+ Gripper",  Button.GHOST)
        self.btn_add_wait = Button(sx+8+3*(bw4+6),   132, bw4, 26, "+ Wait",     Button.GHOST)
        # Record buttons row 2 (y=162)
        self.btn_add_home = Button(sx+8,             162, bw4, 26, "+ Home",     Button.GHOST)
        self.btn_add_spd  = Button(sx+8+(bw4+6),     162, bw4, 26, "+ Speed",    Button.GHOST)
        self.btn_add_io   = Button(sx+8+2*(bw4+6),   162, bw4, 26, "+ IO",       Button.GHOST)
        self.btn_add_rel  = Button(sx+8+3*(bw4+6),   162, bw4, 26, "+ Relative", Button.GHOST)
        self.seq_add_btns = [
            self.btn_add_pos, self.btn_add_suck, self.btn_add_grip, self.btn_add_wait,
            self.btn_add_home, self.btn_add_spd, self.btn_add_io, self.btn_add_rel,
        ]

        # Edit/reorder bar (y=448)
        self.btn_del_step = Button(sx+8,           448, bw4, 26, "Delete",  Button.DANGER)
        self.btn_move_up  = Button(sx+8+(bw4+6),   448, bw4, 26, "Up",      Button.GHOST)
        self.btn_move_dn  = Button(sx+8+2*(bw4+6), 448, bw4, 26, "Down",    Button.GHOST)
        self.btn_dup_step = Button(sx+8+3*(bw4+6), 448, bw4, 26, "Duplicate", Button.GHOST)

        # Playback controls (y=478)
        self.btn_seq_play = Button(sx+8,       478, 152, BTN_H, "Play", Button.SUCCESS)
        self.btn_seq_stop = Button(sx+8+158,   478, 100, BTN_H, "Stop", Button.DANGER)
        self.btn_seq_loop = Button(sx+8+264,   478, inner-264, BTN_H, "Loop: OFF", Button.GHOST)

        # Save/Load bar (y=512)
        self.btn_seq_save  = Button(sx+8,       512, 72, 26, "Save",  Button.GHOST)
        self.btn_seq_load  = Button(sx+8+78,    512, 72, 26, "Load",  Button.GHOST)
        self.btn_seq_clear = Button(sx+8+156,   512, 72, 26, "Clear", Button.DANGER)
        self.inp_seq_name  = InputField(sx+8+234, 513, inner-234, "untitled")
        self.inp_seq_name.max_len = 30

    # ── Connection ────────────────────────────────────────────────────────────

    def refresh_ports(self):
        infos = list_ports.comports()
        self.available_ports = [p.device for p in infos]
        if self.available_ports:
            usb = [p.device for p in infos
                   if 'USB' in (p.hwid or '').upper()
                   or 'USB' in (p.description or '').upper()]
            if usb:
                self.port_index = self.available_ports.index(usb[0])
            self.logger.info(f"Found {len(self.available_ports)} port(s)")
        else:
            self.logger.warning("No COM ports found")

    def connect(self):
        if not self.available_ports:
            self.logger.error("No ports available")
            return
        port = self.available_ports[self.port_index]
        self.connecting = True
        self.btn_connect.enabled = False

        def _do():
            try:
                self.logger.info(f"Connecting to {port}...")
                self.device = Dobot(port=port)
                self.is_connected = True
                self.btn_connect.text  = "Disconnect"
                self.btn_connect.style = Button.DANGER
                self.logger.info("Connected successfully")
                self.device.clear_alarms()
                time.sleep(0.3)
                self._fetch_pos()
                self._start_pos_thread()
            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
                self.btn_connect.text  = "Connect"
                self.btn_connect.style = Button.NORMAL
            finally:
                self.btn_connect.enabled = True
                self.connecting = False

        threading.Thread(target=_do, daemon=True).start()

    def disconnect(self):
        if self.device:
            try: self.device.close()
            except: pass
        self.device = None
        self.is_connected = False
        self.btn_connect.text  = "Connect"
        self.btn_connect.style = Button.NORMAL
        self.logger.info("Disconnected")

    def _fetch_pos(self):
        if not (self.is_connected and self.device):
            return
        try:
            p = self.device.get_pose().position
            self.pos = {"X": p.x, "Y": p.y, "Z": p.z, "R": p.r}
        except Exception as e:
            self.logger.warning(f"Pos update failed: {e}")

    def _check_alarms(self):
        if not (self.is_connected and self.device):
            return
        try:
            self.alarms = self.device.get_alarms()
            if self.alarms:
                self.device.clear_alarms()
                self.logger.warning(f"Cleared alarms: {', '.join(str(a) for a in self.alarms)}")
                self.alarms = set()
        except Exception:
            pass

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

    def _start_pos_thread(self):
        def _loop():
            tick = 0
            while self.running and self.is_connected:
                self._fetch_pos()
                tick += 1
                if tick % 4 == 0:  # check alarms every ~2s
                    self._check_alarms()
                time.sleep(0.5)
        threading.Thread(target=_loop, daemon=True).start()

    # ── Manual commands ───────────────────────────────────────────────────────

    def _safe_move(self, x, y, z, r):
        """Move with alarm auto-clear. Runs on a background thread."""
        try:
            alarms = self.device.get_alarms()
            if alarms:
                self.device.clear_alarms()
            self.device.move_to(x, y, z, r)
        except Exception as e:
            self.logger.error(f"Move failed: {e}")

    def cmd_move_to(self):
        if not self.is_connected: return
        try:
            x, y, z, r = (float(f.get()) for f in
                          (self.inp_x, self.inp_y, self.inp_z, self.inp_r))
            self.logger.info(f"Move → X{x:.1f} Y{y:.1f} Z{z:.1f} R{r:.1f}")
            threading.Thread(target=lambda: self._safe_move(x, y, z, r),
                             daemon=True).start()
        except ValueError:
            self.logger.error("Invalid coordinate value")
        except Exception as e:
            self.logger.error(f"Move failed: {e}")

    def use_current(self):
        self.inp_x.set(f"{self.pos['X']:.2f}")
        self.inp_y.set(f"{self.pos['Y']:.2f}")
        self.inp_z.set(f"{self.pos['Z']:.2f}")
        self.inp_r.set(f"{self.pos['R']:.2f}")

    def jog_step_move(self, axis, sign):
        if not self.is_connected: return
        x = self.pos["X"] + (self.jog_step * sign if axis == 'x' else 0)
        y = self.pos["Y"] + (self.jog_step * sign if axis == 'y' else 0)
        z = self.pos["Z"] + (self.jog_step * sign if axis == 'z' else 0)
        r = self.pos["R"]
        arrow = "+" if sign > 0 else "−"
        self.logger.info(f"Step {axis.upper()}{arrow}{self.jog_step:.0f} mm")
        threading.Thread(target=lambda: self._safe_move(x, y, z, r),
                         daemon=True).start()

    def toggle_vacuum(self):
        if not self.is_connected: return
        try:
            self.vacuum_on = not self.vacuum_on
            state = self.vacuum_on
            threading.Thread(target=lambda: self.device.suck(state),
                             daemon=True).start()
            self.btn_vacuum.text  = "Vacuum ON"  if self.vacuum_on else "Vacuum OFF"
            self.btn_vacuum.style = Button.SUCCESS if self.vacuum_on else Button.NORMAL
            self.logger.info(f"Vacuum {'ON' if self.vacuum_on else 'OFF'}")
        except Exception as e:
            self.logger.error(f"Vacuum error: {e}")

    def cmd_home(self):
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        self.logger.info("Homing...")
        threading.Thread(target=self.device.home, daemon=True).start()

    def _handle_jog(self):
        if not (self.is_connected and self.device): return
        vx, vy = self.joystick.vx, self.joystick.vy
        vz = self.z_slider.get() / 100.0
        dz = 0.04
        if abs(vx) < dz: vx = 0
        if abs(vy) < dz: vy = 0
        if abs(vz) < dz: vz = 0
        cur = (round(vx, 3), round(vy, 3), round(vz, 3))
        if cur == self.last_jog: return
        self.last_jog = cur
        spd = self.speed_slider.get()
        # Run serial jog commands off the main/render thread
        def _do_jog():
            if not self._jog_lock.acquire(blocking=False):
                return  # skip if previous jog command still in flight
            try:
                if vx == 0 and vy == 0 and vz == 0:
                    self.device._set_jog_command(0)
                elif abs(vx) >= abs(vy) and abs(vx) >= abs(vz):
                    self.device._set_jog_coordinate_params(abs(vx * spd), 0, 0, 0)
                    self.device._set_jog_command(1 if vx > 0 else 2)
                elif abs(vy) >= abs(vz):
                    self.device._set_jog_coordinate_params(0, abs(vy * spd), 0, 0)
                    self.device._set_jog_command(3 if vy > 0 else 4)
                else:
                    self.device._set_jog_coordinate_params(0, 0, abs(vz * spd), 0)
                    self.device._set_jog_command(5 if vz > 0 else 6)
            except Exception as e:
                self.logger.error(f"Jog error: {e}")
            finally:
                self._jog_lock.release()
        threading.Thread(target=_do_jog, daemon=True).start()

    # ── Sequence: add steps ───────────────────────────────────────────────────

    def _seq_insert(self, step):
        idx = self.seq_selected + 1 if self.seq_selected >= 0 else len(self.sequence)
        self.sequence.insert(idx, step)
        self.seq_selected = idx
        self._seq_auto_scroll()

    def _seq_auto_scroll(self):
        if self.seq_selected < self.seq_scroll:
            self.seq_scroll = self.seq_selected
        elif self.seq_selected >= self.seq_scroll + SEQ_MAX_VIS:
            self.seq_scroll = self.seq_selected - SEQ_MAX_VIS + 1

    def seq_add_position(self):
        self._seq_insert({"type": "move_to", "params": {
            "x": round(self.pos["X"], 2), "y": round(self.pos["Y"], 2),
            "z": round(self.pos["Z"], 2), "r": round(self.pos["R"], 2)}})
        p = self.sequence[self.seq_selected]["params"]
        self.logger.info(f"Recorded pos: X{p['x']:.1f} Y{p['y']:.1f} Z{p['z']:.1f}")

    def seq_add_suction(self):
        on = True
        for s in reversed(self.sequence):
            if s["type"] == "suction":
                on = not s["params"]["on"]
                break
        self._seq_insert({"type": "suction", "params": {"on": on}})

    def seq_add_gripper(self):
        on = True
        for s in reversed(self.sequence):
            if s["type"] == "gripper":
                on = not s["params"]["on"]
                break
        self._seq_insert({"type": "gripper", "params": {"on": on}})

    def seq_add_wait(self):
        self._seq_insert({"type": "wait", "params": {"seconds": 1.0}})

    def seq_add_home(self):
        self._seq_insert({"type": "home", "params": {}})

    def seq_add_speed(self):
        v = self.speed_slider.get()
        self._seq_insert({"type": "speed", "params": {"velocity": v, "acceleration": v}})

    def seq_add_io(self):
        self._seq_insert({"type": "set_io", "params": {"address": 1, "state": True}})

    def seq_add_rel(self):
        self._seq_insert({"type": "move_rel", "params": {"x": 0, "y": 0, "z": 0, "r": 0}})

    # ── Sequence: inline editing ──────────────────────────────────────────────

    def _seq_start_edit(self, idx):
        if idx < 0 or idx >= len(self.sequence):
            return
        self.seq_editing = idx
        step = self.sequence[idx]
        t, p = step["type"], step["params"]
        sx = SEQ_X + 8
        ew = 64
        eg = 4
        ey = SEQ_LIST_Y + SEQ_LIST_H + 4  # just below the list

        fields = []
        if t in ("move_to", "move_rel"):
            for i, k in enumerate(["x", "y", "z", "r"]):
                f = InputField(sx + i * (ew + eg), ey, ew, f"{p[k]:.1f}")
                f.max_len = 8
                fields.append((k, f))
        elif t in ("suction", "gripper"):
            bk = "on"
            f = InputField(sx, ey, 50, "1" if p[bk] else "0")
            f.max_len = 1
            fields.append((bk, f))
        elif t == "wait":
            f = InputField(sx, ey, 60, f"{p['seconds']:.1f}")
            f.max_len = 6
            fields.append(("seconds", f))
        elif t == "speed":
            f1 = InputField(sx, ey, 60, f"{p['velocity']:.0f}")
            f1.max_len = 6
            f2 = InputField(sx + 64, ey, 60, f"{p['acceleration']:.0f}")
            f2.max_len = 6
            fields.append(("velocity", f1))
            fields.append(("acceleration", f2))
        elif t == "set_io":
            f1 = InputField(sx, ey, 40, str(p["address"]))
            f1.max_len = 3
            f2 = InputField(sx + 44, ey, 40, "1" if p["state"] else "0")
            f2.max_len = 1
            fields.append(("address", f1))
            fields.append(("state", f2))
        # home has no params

        self.seq_edit_fields = fields

    def _seq_apply_edit(self):
        if self.seq_editing < 0 or self.seq_editing >= len(self.sequence):
            self.seq_editing = -1
            return
        step = self.sequence[self.seq_editing]
        p = step["params"]
        try:
            for key, field in self.seq_edit_fields:
                val = field.get().strip()
                if key in ("x", "y", "z", "r", "seconds", "velocity", "acceleration"):
                    p[key] = float(val)
                elif key == "address":
                    p[key] = int(val)
                elif key in ("on", "state"):
                    p[key] = val not in ("0", "false", "False", "off", "OFF", "")
        except (ValueError, KeyError):
            self.logger.error("Invalid edit value")
        self.seq_editing = -1
        self.seq_edit_fields = []

    def _seq_cancel_edit(self):
        self.seq_editing = -1
        self.seq_edit_fields = []

    # ── Sequence: playback ────────────────────────────────────────────────────

    def _seq_play(self):
        self.seq_playing = True
        self.seq_stop_evt.clear()
        self.seq_pause_evt.set()
        steps = list(self.sequence)  # snapshot

        # Reset queue so command indices start fresh and are predictable
        try:
            self.device.clear_alarms()
            self.device._set_queued_cmd_stop_exec()
            self.device._set_queued_cmd_clear()
            self.device._set_queued_cmd_start_exec()
            time.sleep(0.1)  # let Dobot settle after queue reset
        except Exception as e:
            self.logger.error(f"Queue reset failed: {e}")

        try:
            while True:
                for i, step in enumerate(steps):
                    if self.seq_stop_evt.is_set():
                        return
                    self.seq_pause_evt.wait()
                    if self.seq_stop_evt.is_set():
                        return
                    self.seq_current = i
                    self.logger.info(f"Step {i+1}/{len(steps)}: {step_label(step)}")
                    self._seq_exec_step(step)
                if not self.seq_looping:
                    break
                # Reset queue between loops to keep indices predictable
                try:
                    self.device.clear_alarms()
                    self.device._set_queued_cmd_stop_exec()
                    self.device._set_queued_cmd_clear()
                    self.device._set_queued_cmd_start_exec()
                    time.sleep(0.1)
                except Exception:
                    pass
        except Exception as e:
            self.logger.error(f"Playback error at step {self.seq_current+1}: {e}")
        finally:
            self.seq_playing = False
            self.seq_paused  = False
            self.seq_current = -1
            self.btn_seq_play.text  = "Play"
            self.btn_seq_play.style = Button.SUCCESS

    def _seq_exec_step(self, step):
        t, p = step["type"], step["params"]
        # Clear any alarms that might block execution
        try:
            alarms = self.device.get_alarms()
            if alarms:
                self.device.clear_alarms()
                self.logger.warning(f"Cleared alarms before step: {', '.join(str(a) for a in alarms)}")
        except Exception:
            pass

        if t == "move_to":
            cmd = self.device.move_to(p["x"], p["y"], p["z"], p["r"], wait=False)
            self._seq_wait_cmd(cmd)
        elif t == "move_rel":
            # move_rel doesn't return cmd index, so compute absolute target ourselves
            cur = self.device.get_pose().position
            cmd = self.device.move_to(cur.x + p["x"], cur.y + p["y"],
                                      cur.z + p["z"], cur.r + p["r"], wait=False)
            self._seq_wait_cmd(cmd)
        elif t == "suction":
            self.device.suck(p["on"])
            time.sleep(0.3)  # give actuator time to engage/disengage
        elif t == "gripper":
            self.device.grip(p["on"])
            time.sleep(0.3)
        elif t == "wait":
            self.seq_stop_evt.wait(timeout=p["seconds"])
        elif t == "home":
            cmd = self.device.home()
            self._seq_wait_cmd(cmd)
        elif t == "speed":
            self.device.speed(p["velocity"], p["acceleration"])
        elif t == "set_io":
            self.device.set_io(p["address"], p["state"])

    def _seq_wait_cmd(self, cmd_idx):
        """Poll for command completion, checking stop event every 100ms."""
        if cmd_idx is None:
            return
        # Small delay to let the Dobot start processing the command
        self.seq_stop_evt.wait(timeout=0.15)
        if self.seq_stop_evt.is_set():
            return
        # Poll until the executed index catches up
        timeout = time.time() + 120  # 2 min max per step
        while not self.seq_stop_evt.is_set():
            try:
                cur = self.device._get_queued_cmd_current_index()
                if cur >= cmd_idx:
                    return
            except Exception:
                return
            if time.time() > timeout:
                self.logger.warning("Step timed out (2 min)")
                return
            self.seq_stop_evt.wait(timeout=0.1)

    def seq_on_play_pause(self):
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        if not self.sequence:
            self.logger.warning("Sequence is empty")
            return
        if not self.seq_playing:
            threading.Thread(target=self._seq_play, daemon=True).start()
            self.btn_seq_play.text  = "Pause"
            self.btn_seq_play.style = Button.NORMAL
        elif self.seq_paused:
            self.seq_paused = False
            self.seq_pause_evt.set()
            self.btn_seq_play.text = "Pause"
        else:
            self.seq_paused = True
            self.seq_pause_evt.clear()
            self.btn_seq_play.text = "Resume"

    def seq_on_stop(self):
        self.seq_stop_evt.set()
        self.seq_pause_evt.set()

    def seq_on_loop_toggle(self):
        self.seq_looping = not self.seq_looping
        self.btn_seq_loop.text  = f"Loop: {'ON' if self.seq_looping else 'OFF'}"
        self.btn_seq_loop.style = Button.SUCCESS if self.seq_looping else Button.GHOST

    # ── Sequence: persistence ─────────────────────────────────────────────────

    def seq_save(self):
        name = self.inp_seq_name.get().strip() or "untitled"
        name = "".join(c for c in name if c.isalnum() or c in "-_ ")
        os.makedirs(SEQUENCES_DIR, exist_ok=True)
        path = os.path.join(SEQUENCES_DIR, f"{name}.json")
        data = {"name": name, "version": 1, "steps": self.sequence}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.logger.info(f"Saved: {name} ({len(self.sequence)} steps)")

    def seq_load_file(self, filename):
        path = os.path.join(SEQUENCES_DIR, filename)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.sequence = data.get("steps", [])
            name = data.get("name", filename.replace(".json", ""))
            self.inp_seq_name.set(name)
            self.seq_selected = -1
            self.seq_scroll = 0
            self.logger.info(f"Loaded: {name} ({len(self.sequence)} steps)")
        except Exception as e:
            self.logger.error(f"Load failed: {e}")
        self.seq_load_picker = False

    def seq_show_load_picker(self):
        if os.path.isdir(SEQUENCES_DIR):
            self.seq_files = sorted(f for f in os.listdir(SEQUENCES_DIR) if f.endswith(".json"))
        else:
            self.seq_files = []
        if not self.seq_files:
            self.logger.warning("No saved sequences found")
            return
        self.seq_load_picker = True
        self.seq_file_scroll = 0

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_header(self):
        title = "DOBOT CONTROLLER"
        tw = measure_text(title, 20)
        draw_text(title, (W - tw) // 2, 11, 20, C_TEXT)

        dot = C_OK if self.is_connected else (C_WARN if self.connecting else C_BAD)
        if self.connecting:
            dots = "." * (int(get_time() * 2) % 4)
            status = f"CONNECTING{dots:<3}"
        else:
            status = "CONNECTED" if self.is_connected else "DISCONNECTED"
        sw = measure_text(status, FSM)
        sx = (W - sw - 14) // 2
        draw_circle(sx + 5, 40, 5, dot)
        draw_text(status, sx + 14, 34, FSM, dot)

        lx = PAD
        port_name = self.available_ports[self.port_index] if self.available_ports else "No ports"
        draw_text(port_name, lx + 30, 68, FMD, C_TEXT)
        self.btn_port_prev.draw()
        self.btn_port_next.draw()
        self.btn_refresh.draw()
        self.btn_connect.draw()
        self.btn_home.draw()

        draw_line(0, HDR_H - 2, W, HDR_H - 2, C_BORDER)

    def _draw_left(self):
        lx = PAD
        draw_panel(lx, 100, COL_W, 80, "Current Position")
        for i, (k, lbl) in enumerate([("X","X"), ("Y","Y"), ("Z","Z"), ("R","R")]):
            cx = lx + 10 + i * 110
            dlabel(lbl, cx, 131, C_DIM)
            draw_text(f"{self.pos[k]:8.2f}", cx, 147, FLG, C_TEXT)

        draw_panel(lx, 188, COL_W, 158, "Move To")
        dlabel("X", lx + 12, 230); dlabel("Y", lx + 190, 230)
        dlabel("Z", lx + 12, 270); dlabel("R", lx + 190, 270)
        self.inp_x.draw(); self.inp_y.draw()
        self.inp_z.draw(); self.inp_r.draw()
        self.btn_use_curr.draw()
        self.btn_move.draw()

        draw_panel(lx, 358, COL_W, 182, "Quick Jog")
        dlabel("Step (mm):", lx + 10, 390)
        for step, btn in self.step_btns:
            btn.style = Button.NORMAL if step == self.jog_step else Button.GHOST
            btn.draw()
        for btn in self.jog_row1:
            btn.draw()
        self.btn_zm.draw()
        self.btn_zp.draw()

    def _draw_right(self):
        rx = COL_RX
        draw_panel(rx, 100, COL_RW, 250, "XY Jog  (arrows)")
        self.joystick.draw()
        draw_panel(rx, 358, COL_RW, 182, "Z Jog & Speed")
        dlabel("Z Jog  (PgUp / PgDn)", rx + 12, 390)
        self.z_slider.draw()
        dlabel("Speed (mm/s)", rx + 12, 438)
        self.speed_slider.draw()
        self.btn_vacuum.draw()
        self.btn_clear_alarms.draw()

    def _draw_sequence(self):
        draw_panel(SEQ_X, 100, SEQ_W, 440, "Sequence Editor")
        # Step count
        count_txt = f"{len(self.sequence)} steps"
        ctw = measure_text(count_txt, FSM)
        draw_text(count_txt, SEQ_X + SEQ_W - ctw - 12, 109, FSM, C_MUTED)

        # Record buttons
        for btn in self.seq_add_btns:
            btn.draw()

        # Step list or load picker
        if self.seq_load_picker:
            self._draw_load_picker()
        else:
            self._draw_seq_list()

        # Edit bar
        self.btn_del_step.draw()
        self.btn_move_up.draw()
        self.btn_move_dn.draw()
        self.btn_dup_step.draw()

        # Inline edit fields (drawn below list)
        if self.seq_editing >= 0 and self.seq_edit_fields:
            ey = SEQ_LIST_Y + SEQ_LIST_H + 4
            labels = {"x":"X","y":"Y","z":"Z","r":"R","on":"ON?","seconds":"Sec",
                      "velocity":"Vel","acceleration":"Accel","address":"Pin","state":"ON?"}
            for key, field in self.seq_edit_fields:
                lbl = labels.get(key, key)
                dlabel(lbl, field.rect.x, ey - 14, C_DIM)
                field.draw()

        # Playback
        self.btn_seq_play.draw()
        self.btn_seq_stop.draw()
        self.btn_seq_loop.draw()

        # Save/Load
        self.btn_seq_save.draw()
        self.btn_seq_load.draw()
        self.btn_seq_clear.draw()
        self.inp_seq_name.draw()

    def _draw_seq_list(self):
        lx = SEQ_X + 8
        ly = SEQ_LIST_Y
        lw = SEQ_W - 16
        lh = SEQ_LIST_H

        begin_scissor_mode(lx, ly, lw, lh)
        for vi in range(SEQ_MAX_VIS + 1):
            idx = self.seq_scroll + vi
            if idx >= len(self.sequence):
                break
            step = self.sequence[idx]
            ry = ly + vi * SEQ_ROW_H

            # Row background
            if idx == self.seq_current and self.seq_playing:
                draw_rectangle(lx, ry, lw, SEQ_ROW_H, Color(48, 172, 95, 40))
            elif idx == self.seq_selected:
                draw_rectangle(lx, ry, lw, SEQ_ROW_H, Color(65, 125, 195, 40))
            elif vi % 2 == 1:
                draw_rectangle(lx, ry, lw, SEQ_ROW_H, Color(28, 28, 38, 255))

            # Step number
            draw_text(f"{idx+1:02d}", lx + 4, ry + 7, FSM, C_MUTED)
            # Type dot
            dot_col = STEP_TYPE_COLORS.get(step["type"], C_DIM)
            draw_circle(lx + 30, ry + 14, 4, dot_col)
            # Label
            draw_text(step_label(step), lx + 40, ry + 7, FSM, C_TEXT)
        end_scissor_mode()

        # Scrollbar
        total = len(self.sequence)
        if total > SEQ_MAX_VIS:
            bar_h = max(16, int(lh * SEQ_MAX_VIS / total))
            bar_y = ly + int((lh - bar_h) * self.seq_scroll / max(1, total - SEQ_MAX_VIS))
            draw_rectangle_rounded(_rrec(lx + lw - 5, bar_y, 5, bar_h), 1.0, 4, C_MUTED)

        # Empty state
        if not self.sequence:
            msg = "Click + buttons above to add steps"
            mw = measure_text(msg, FSM)
            draw_text(msg, lx + (lw - mw) // 2, ly + lh // 2 - 8, FSM, C_MUTED)

    def _draw_load_picker(self):
        lx = SEQ_X + 8
        ly = SEQ_LIST_Y
        lw = SEQ_W - 16
        lh = SEQ_LIST_H

        draw_rectangle(lx, ly, lw, lh, C_PANEL_DARK)
        dlabel("Select a sequence to load:", lx + 8, ly + 4, C_DIM)

        begin_scissor_mode(lx, ly + 22, lw, lh - 22)
        for vi in range(SEQ_MAX_VIS):
            idx = self.seq_file_scroll + vi
            if idx >= len(self.seq_files):
                break
            fname = self.seq_files[idx]
            ry = ly + 22 + vi * SEQ_ROW_H
            mp = get_mouse_position()
            row_rect = _rrec(lx, ry, lw, SEQ_ROW_H)
            if check_collision_point_rec(mp, row_rect):
                draw_rectangle(lx, ry, lw, SEQ_ROW_H, Color(65, 125, 195, 30))
            draw_text(fname.replace(".json", ""), lx + 8, ry + 7, FSM, C_TEXT)
        end_scissor_mode()

    def _draw_log(self):
        draw_panel(PAD, LOG_Y, W - PAD * 2, LOG_H, "Log")
        line_h = 17
        max_lines = (LOG_H - 36) // line_h
        visible = self.log_handler.entries[-max_lines:]
        for i, e in enumerate(visible):
            y = LOG_Y + 34 + i * line_h
            ts_w = measure_text(e.ts, FSM) + 6
            draw_text(e.ts, PAD + 8, y, FSM, C_MUTED)
            lc = C_ERR if e.level == "ERROR" else C_WARN if e.level == "WARNING" else C_DIM
            draw_text(e.msg, PAD + 8 + ts_w, y, FSM, lc)

    def _draw(self):
        clear_background(C_BG)
        self._draw_header()
        self._draw_left()
        self._draw_right()
        self._draw_sequence()
        self._draw_log()

    # ── Input handling ────────────────────────────────────────────────────────

    def _handle_input(self):
        # Port navigation
        if self.btn_port_prev.clicked() and self.available_ports:
            self.port_index = (self.port_index - 1) % len(self.available_ports)
        if self.btn_port_next.clicked() and self.available_ports:
            self.port_index = (self.port_index + 1) % len(self.available_ports)

        if self.btn_refresh.clicked():  self.refresh_ports()
        if self.btn_connect.clicked():
            self.disconnect() if self.is_connected else self.connect()
        if self.btn_home.clicked():     self.cmd_home()
        if self.btn_use_curr.clicked(): self.use_current()
        if self.btn_move.clicked():     self.cmd_move_to()

        for step, btn in self.step_btns:
            if btn.clicked(): self.jog_step = step

        xm, xp, ym, yp = self.jog_row1
        if xm.clicked(): self.jog_step_move('x', -1)
        if xp.clicked(): self.jog_step_move('x',  1)
        if ym.clicked(): self.jog_step_move('y', -1)
        if yp.clicked(): self.jog_step_move('y',  1)
        if self.btn_zm.clicked(): self.jog_step_move('z', -1)
        if self.btn_zp.clicked(): self.jog_step_move('z',  1)
        if self.btn_vacuum.clicked(): self.toggle_vacuum()
        if self.btn_clear_alarms.clicked(): self.cmd_clear_alarms()

        # Keyboard jog (only when no input field is active)
        any_input_active = any(f.active for f in
            [self.inp_x, self.inp_y, self.inp_z, self.inp_r, self.inp_seq_name]
            + [f for _, f in self.seq_edit_fields])

        if not any_input_active:
            step = 0.06
            if   is_key_down(KEY_RIGHT): self._kb_vx = min(1.0, self._kb_vx + step)
            elif is_key_down(KEY_LEFT):  self._kb_vx = max(-1.0, self._kb_vx - step)
            elif (is_key_released(KEY_RIGHT) or is_key_released(KEY_LEFT)): self._kb_vx = 0.0

            if   is_key_down(KEY_DOWN): self._kb_vy = min(1.0, self._kb_vy + step)
            elif is_key_down(KEY_UP):   self._kb_vy = max(-1.0, self._kb_vy - step)
            elif (is_key_released(KEY_UP) or is_key_released(KEY_DOWN)): self._kb_vy = 0.0

            if self._kb_vx != 0 or self._kb_vy != 0:
                self.joystick.set_kb(self._kb_vx, self._kb_vy)

            if   is_key_down(KEY_PAGE_UP):   self.z_slider.value = min(100, self.z_slider.value + 4)
            elif is_key_down(KEY_PAGE_DOWN):  self.z_slider.value = max(-100, self.z_slider.value - 4)
            elif (is_key_released(KEY_PAGE_UP) or is_key_released(KEY_PAGE_DOWN)):
                self.z_slider.value = 0

            # Delete key for selected step
            if is_key_pressed(KEY_DELETE) and self.seq_selected >= 0 and not self.seq_playing:
                self.sequence.pop(self.seq_selected)
                self.seq_selected = min(self.seq_selected, len(self.sequence) - 1)

        self._handle_jog()
        self._handle_seq_input()

    def _handle_seq_input(self):
        editing_ok = not self.seq_playing
        for btn in self.seq_add_btns:
            btn.enabled = editing_ok
        self.btn_del_step.enabled = editing_ok and self.seq_selected >= 0
        self.btn_move_up.enabled  = editing_ok and self.seq_selected > 0
        self.btn_move_dn.enabled  = editing_ok and 0 <= self.seq_selected < len(self.sequence) - 1
        self.btn_dup_step.enabled = editing_ok and self.seq_selected >= 0
        self.btn_seq_clear.enabled = editing_ok

        # Record buttons
        if self.btn_add_pos.clicked():  self.seq_add_position()
        if self.btn_add_suck.clicked(): self.seq_add_suction()
        if self.btn_add_grip.clicked(): self.seq_add_gripper()
        if self.btn_add_wait.clicked(): self.seq_add_wait()
        if self.btn_add_home.clicked(): self.seq_add_home()
        if self.btn_add_spd.clicked():  self.seq_add_speed()
        if self.btn_add_io.clicked():   self.seq_add_io()
        if self.btn_add_rel.clicked():  self.seq_add_rel()

        # Load picker interaction
        if self.seq_load_picker:
            lx, ly, lw = SEQ_X + 8, SEQ_LIST_Y + 22, SEQ_W - 16
            mp = get_mouse_position()
            if is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
                list_rect = _rrec(lx, ly, lw, SEQ_LIST_H - 22)
                if check_collision_point_rec(mp, list_rect):
                    vi = int((mp.y - ly) // SEQ_ROW_H)
                    idx = self.seq_file_scroll + vi
                    if 0 <= idx < len(self.seq_files):
                        self.seq_load_file(self.seq_files[idx])
                elif not check_collision_point_rec(mp, _rrec(SEQ_X, SEQ_LIST_Y, SEQ_W, SEQ_LIST_H)):
                    self.seq_load_picker = False

            # Scroll in picker
            picker_rect = _rrec(SEQ_X, SEQ_LIST_Y, SEQ_W, SEQ_LIST_H)
            if check_collision_point_rec(mp, picker_rect):
                wheel = get_mouse_wheel_move()
                if wheel:
                    max_scroll = max(0, len(self.seq_files) - SEQ_MAX_VIS)
                    self.seq_file_scroll = max(0, min(max_scroll, self.seq_file_scroll - int(wheel)))
            return  # don't process list clicks while picker is open

        # Step list click
        mp = get_mouse_position()
        list_rect = _rrec(SEQ_X + 8, SEQ_LIST_Y, SEQ_W - 16, SEQ_LIST_H)
        if check_collision_point_rec(mp, list_rect) and is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
            vi = int((mp.y - SEQ_LIST_Y) // SEQ_ROW_H)
            idx = self.seq_scroll + vi
            if 0 <= idx < len(self.sequence):
                if idx == self.seq_selected and editing_ok:
                    # Second click → edit
                    self._seq_start_edit(idx)
                else:
                    self.seq_selected = idx
                    self._seq_cancel_edit()

        # Scroll in step list
        if check_collision_point_rec(mp, list_rect):
            wheel = get_mouse_wheel_move()
            if wheel:
                max_scroll = max(0, len(self.sequence) - SEQ_MAX_VIS)
                self.seq_scroll = max(0, min(max_scroll, self.seq_scroll - int(wheel)))

        # Reorder / delete
        if self.btn_del_step.clicked() and self.seq_selected >= 0:
            self.sequence.pop(self.seq_selected)
            self.seq_selected = min(self.seq_selected, len(self.sequence) - 1)
            self._seq_cancel_edit()
        if self.btn_move_up.clicked() and self.seq_selected > 0:
            i = self.seq_selected
            self.sequence[i-1], self.sequence[i] = self.sequence[i], self.sequence[i-1]
            self.seq_selected -= 1
            self._seq_cancel_edit()
        if self.btn_move_dn.clicked() and self.seq_selected < len(self.sequence) - 1:
            i = self.seq_selected
            self.sequence[i], self.sequence[i+1] = self.sequence[i+1], self.sequence[i]
            self.seq_selected += 1
            self._seq_cancel_edit()
        if self.btn_dup_step.clicked() and self.seq_selected >= 0:
            dup = copy.deepcopy(self.sequence[self.seq_selected])
            self.sequence.insert(self.seq_selected + 1, dup)
            self.seq_selected += 1
            self._seq_cancel_edit()

        # Inline edit: Enter to apply, Escape to cancel
        if self.seq_editing >= 0:
            if is_key_pressed(KEY_ENTER):
                self._seq_apply_edit()
            elif is_key_pressed(KEY_ESCAPE):
                self._seq_cancel_edit()

        # Playback
        if self.btn_seq_play.clicked(): self.seq_on_play_pause()
        if self.btn_seq_stop.clicked(): self.seq_on_stop()
        if self.btn_seq_loop.clicked(): self.seq_on_loop_toggle()

        # Save / Load / Clear
        if self.btn_seq_save.clicked():  self.seq_save()
        if self.btn_seq_load.clicked():  self.seq_show_load_picker()
        if self.btn_seq_clear.clicked():
            self.sequence.clear()
            self.seq_selected = -1
            self.seq_scroll = 0
            self._seq_cancel_edit()
            self.logger.info("Sequence cleared")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        try:
            while not window_should_close():
                self._handle_input()
                begin_drawing()
                self._draw()
                end_drawing()
        finally:
            self.running = False
            if self.seq_playing:
                self.seq_on_stop()
            if self.is_connected:
                self.disconnect()
            close_window()


def main():
    DobotController().run()


if __name__ == "__main__":
    main()
