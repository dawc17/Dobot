#!/usr/bin/env python3
"""
Dobot Raylib GUI Controller  
A modern GUI for controlling Dobot robotic arm using raylib
"""

import logging
import threading
import time
from typing import Optional, Tuple
from serial.tools import list_ports
from pydobotplus import Dobot
import pyray as rl
from pyray import *

# Helper functions are not needed with pyray - it has proper Python classes
# Color definitions (colors are Color objects in pyray)
COLOR_BG = Color(30, 30, 40, 255)
COLOR_PANEL = Color(45, 45, 55, 255)
COLOR_PANEL_DARK = Color(35, 35, 45, 255)
COLOR_TEXT = Color(220, 220, 220, 255)
COLOR_TEXT_DIM = Color(150, 150, 150, 255)
COLOR_CONNECTED = Color(50, 200, 100, 255)
COLOR_DISCONNECTED = Color(200, 50, 50, 255)
COLOR_BUTTON = Color(60, 120, 180, 255)
COLOR_BUTTON_HOVER = Color(80, 140, 200, 255)
COLOR_BUTTON_ACTIVE = Color(40, 100, 160, 255)
COLOR_SLIDER_TRACK = Color(80, 80, 90, 255)
COLOR_SLIDER_THUMB = Color(100, 150, 200, 255)
COLOR_SLIDER_ACTIVE = Color(120, 170, 220, 255)

# GUI Layout constants
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 950
PADDING = 10
BUTTON_HEIGHT = 30
INPUT_HEIGHT = 25

# UI Panel positioning - centered
UI_LEFT_MARGIN = (WINDOW_WIDTH - 400) // 2  # Center the 400px wide UI


class LogHandler(logging.Handler):
    """Custom logging handler that stores recent log messages"""
    def __init__(self, max_lines=100):
        super().__init__()
        self.messages = []
        self.max_lines = max_lines
        
    def emit(self, record):
        msg = self.format(record)
        self.messages.append(msg)
        if len(self.messages) > self.max_lines:
            self.messages.pop(0)


class Button:
    """Simple button class"""
    def __init__(self, x, y, width, height, text):
        self.rect = Rectangle(x, y, width, height)
        self.text = text
        self.enabled = True
        
    def draw(self):
        mouse_pos = get_mouse_position()
        is_hover = check_collision_point_rec(mouse_pos, self.rect) and self.enabled
        is_pressed = is_hover and is_mouse_button_down(MOUSE_BUTTON_LEFT)
        
        # Choose color based on state
        if not self.enabled:
            color = Color(50, 50, 50, 255)
        elif is_pressed:
            color = COLOR_BUTTON_ACTIVE
        elif is_hover:
            color = COLOR_BUTTON_HOVER
        else:
            color = COLOR_BUTTON
            
        draw_rectangle_rec(self.rect, color)
        draw_rectangle_lines_ex(self.rect, 1, Color(100, 100, 110, 255))
        
        # Center text
        text_width = measure_text(self.text, 16)
        text_x = self.rect.x + (self.rect.width - text_width) / 2
        text_y = self.rect.y + (self.rect.height - 16) / 2
        
        text_color = COLOR_TEXT if self.enabled else COLOR_TEXT_DIM
        draw_text(self.text, int(text_x), int(text_y), 16, text_color)
        
    def is_clicked(self):
        if not self.enabled:
            return False
        mouse_pos = get_mouse_position()
        return (check_collision_point_rec(mouse_pos, self.rect) and 
                is_mouse_button_pressed(MOUSE_BUTTON_LEFT))


class Slider:
    """Horizontal slider control"""
    def __init__(self, x, y, width, min_val, max_val, initial_val, label="", auto_center=False):
        self.x = x
        self.y = y
        self.width = width
        self.height = 20
        self.min_val = min_val
        self.max_val = max_val
        self.value = initial_val
        self.label = label
        self.dragging = False
        self.auto_center = auto_center  # If True, slider returns to 0 when released
        
    def draw(self):
        # Draw label
        if self.label:
            draw_text(self.label, int(self.x), int(self.y - 18), 14, COLOR_TEXT)
        
        # Draw track
        track = Rectangle(self.x, self.y, self.width, self.height)
        draw_rectangle_rec(track, COLOR_SLIDER_TRACK)
        draw_rectangle_lines_ex(track, 1, Color(100, 100, 110, 255))
        
        # Calculate thumb position
        normalized = (self.value - self.min_val) / (self.max_val - self.min_val)
        thumb_x = self.x + normalized * self.width
        thumb_rect = Rectangle(thumb_x - 8, self.y - 5, 16, self.height + 10)
        
        # Check interaction
        mouse_pos = get_mouse_position()
        is_hover = check_collision_point_rec(mouse_pos, thumb_rect)
        
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and is_hover:
            self.dragging = True
        
        if is_mouse_button_released(MOUSE_BUTTON_LEFT):
            self.dragging = False
            if self.auto_center:
                self.value = 0  # Return to center
            
        if self.dragging:
            # Update value based on mouse position
            mouse_x = mouse_pos.x
            normalized = (mouse_x - self.x) / self.width
            normalized = max(0, min(1, normalized))
            self.value = self.min_val + normalized * (self.max_val - self.min_val)
            
        # Draw thumb
        thumb_color = COLOR_SLIDER_ACTIVE if self.dragging else COLOR_SLIDER_THUMB
        draw_rectangle_rec(thumb_rect, thumb_color)
        draw_rectangle_lines_ex(thumb_rect, 1, Color(150, 150, 160, 255))
        
        # Draw value
        value_text = f"{int(self.value)}"
        draw_text(value_text, int(self.x + self.width + 10), int(self.y + 2), 16, COLOR_TEXT)
        
    def get_value(self):
        return self.value


class InputField:
    """Text input field"""
    def __init__(self, x, y, width, initial_value=""):
        self.rect = Rectangle(x, y, width, INPUT_HEIGHT)
        self.text = initial_value
        self.active = False
        self.max_length = 10
        
    def draw(self):
        mouse_pos = get_mouse_position()
        
        # Handle activation
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
            self.active = check_collision_point_rec(mouse_pos, self.rect)
        
        # Draw background
        bg_color = Color(60, 60, 70, 255) if self.active else Color(50, 50, 60, 255)
        draw_rectangle_rec(self.rect, bg_color)
        border_color = COLOR_BUTTON if self.active else Color(80, 80, 90, 255)
        draw_rectangle_lines_ex(self.rect, 2 if self.active else 1, border_color)
        
        # Handle text input
        if self.active:
            key = get_char_pressed()
            while key > 0:
                if 32 <= key <= 126 and len(self.text) < self.max_length:  # Printable characters
                    self.text += chr(key)
                key = get_char_pressed()
            
            # Handle backspace
            if is_key_pressed(KEY_BACKSPACE) and len(self.text) > 0:
                self.text = self.text[:-1]
        
        # Draw text
        draw_text(self.text, int(self.rect.x + 5), int(self.rect.y + 5), 16, COLOR_TEXT)
        
        # Draw cursor if active
        if self.active and (int(get_time() * 2) % 2 == 0):
            cursor_x = self.rect.x + 5 + measure_text(self.text, 16)
            draw_line(int(cursor_x), int(self.rect.y + 3), 
                     int(cursor_x), int(self.rect.y + self.rect.height - 3), COLOR_TEXT)
    
    def get_value(self):
        return self.text
    
    def set_value(self, value):
        self.text = str(value)


class JoystickControl:
    """2D joystick control for X/Y or similar axes"""
    def __init__(self, x, y, size, label="", axis1="X", axis2="Y"):
        self.x = x
        self.y = y
        self.size = size
        self.label = label
        self.axis1 = axis1
        self.axis2 = axis2
        self.center_x = x + size / 2
        self.center_y = y + size / 2
        self.value_x = 0.0  # -1 to 1
        self.value_y = 0.0  # -1 to 1
        self.active = False
        
    def draw(self):
        # Draw label
        if self.label:
            label_width = measure_text(self.label, 16)
            draw_text(self.label, int(self.center_x - label_width/2), int(self.y - 20), 16, COLOR_TEXT)
        
        # Draw base circle
        base_rect = Rectangle(self.x, self.y, self.size, self.size)
        draw_rectangle_rec(base_rect, COLOR_PANEL_DARK)
        draw_circle(int(self.center_x), int(self.center_y), self.size/2 - 5, COLOR_SLIDER_TRACK)
        
        # Draw crosshair
        draw_line(int(self.center_x), int(self.y + 10), 
                 int(self.center_x), int(self.y + self.size - 10), Color(100, 100, 110, 100))
        draw_line(int(self.x + 10), int(self.center_y), 
                 int(self.x + self.size - 10), int(self.center_y), Color(100, 100, 110, 100))
        
        # Handle input
        mouse_pos = get_mouse_position()
        base_circle_check = check_collision_point_circle(mouse_pos, 
                                                         Vector2(self.center_x, self.center_y), 
                                                         self.size/2)
        
        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and base_circle_check:
            self.active = True
        
        if is_mouse_button_released(MOUSE_BUTTON_LEFT):
            self.active = False
            self.value_x = 0.0
            self.value_y = 0.0
        
        if self.active:
            dx = mouse_pos.x - self.center_x
            dy = mouse_pos.y - self.center_y
            distance = (dx*dx + dy*dy) ** 0.5
            max_distance = self.size / 2 - 10
            
            if distance > max_distance:
                scale = max_distance / distance
                dx *= scale
                dy *= scale
            
            self.value_x = dx / max_distance
            self.value_y = dy / max_distance
        
        # Draw stick position
        stick_x = self.center_x + self.value_x * (self.size / 2 - 10)
        stick_y = self.center_y + self.value_y * (self.size / 2 - 10)
        stick_color = COLOR_SLIDER_ACTIVE if self.active else COLOR_SLIDER_THUMB
        draw_circle(int(stick_x), int(stick_y), 15, stick_color)
        draw_circle_lines(int(stick_x), int(stick_y), 15, Color(150, 150, 160, 255))
        
        # Draw axis labels
        draw_text(f"{self.axis1}+", int(self.x + self.size + 5), int(self.center_y - 8), 12, COLOR_TEXT_DIM)
        draw_text(f"{self.axis1}-", int(self.x - 25), int(self.center_y - 8), 12, COLOR_TEXT_DIM)
        draw_text(f"{self.axis2}+", int(self.center_x - 10), int(self.y - 5), 12, COLOR_TEXT_DIM)
        draw_text(f"{self.axis2}-", int(self.center_x - 10), int(self.y + self.size + 5), 12, COLOR_TEXT_DIM)
        
    def get_values(self):
        return self.value_x, self.value_y


class DobotRaylibController:
    """Main application class"""
    
    def __init__(self):
        # Initialize window
        init_window(WINDOW_WIDTH, WINDOW_HEIGHT, "Dobot Raylib Controller")
        set_target_fps(60)
        
        # Dobot connection
        self.device: Optional[Dobot] = None
        self.is_connected = False
        self.available_ports = []
        self.selected_port_index = 0
        
        # Position tracking
        self.current_pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "R": 0.0}
        self.position_update_thread = None
        self.running = True
        
        # Logging
        self.logger = logging.getLogger('dobot_raylib')
        self.logger.setLevel(logging.INFO)
        self.log_handler = LogHandler()
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.logger.addHandler(self.log_handler)
        self.logger.info("Raylib GUI started")
        
        # GUI Controls
        self.create_controls()
        
        # Initial port refresh
        self.refresh_ports()
        
        # Vacuum state
        self.vacuum_on = False
        
        # Jogging state
        self.jog_speed = 50.0
        self.last_jog_values = (0.0, 0.0, 0.0)
        
    def create_controls(self):
        """Initialize all GUI controls"""
        x_base = UI_LEFT_MARGIN
        y_pos = 65  # Start lower to avoid covering text
        
        # Connection controls - more spacing
        self.btn_refresh_ports = Button(x_base, y_pos, 120, BUTTON_HEIGHT, "Refresh")
        self.btn_connect = Button(x_base + 130, y_pos, 120, BUTTON_HEIGHT, "Connect")
        self.btn_home = Button(x_base + 260, y_pos, 100, BUTTON_HEIGHT, "Home")
        
        # Input fields for coordinates - aligned properly
        y_pos = 175
        label_x = x_base + 5
        input_x = x_base + 30
        self.input_x = InputField(input_x, y_pos, 80, "200")
        self.input_y = InputField(input_x, y_pos + 40, 80, "0")
        self.input_z = InputField(input_x, y_pos + 80, 80, "50")
        self.input_r = InputField(input_x, y_pos + 120, 80, "0")
        
        self.btn_move = Button(x_base + 150, y_pos + 45, 120, BUTTON_HEIGHT * 2 + 10, "Move To")
        
        # Quick move buttons - compact
        y_pos = 370
        btn_width = 49
        btn_height = 23
        btn_spacing = 60
        
        self.btn_x_plus = Button(x_base + btn_spacing, y_pos, btn_width, btn_height, "X +20")
        self.btn_x_minus = Button(x_base, y_pos, btn_width, btn_height, "X -20")
        self.btn_y_plus = Button(x_base + btn_spacing, y_pos + 35, btn_width, btn_height, "Y +20")
        self.btn_y_minus = Button(x_base, y_pos + 35, btn_width, btn_height, "Y -20")
        self.btn_z_plus = Button(x_base + btn_spacing, y_pos + 70, btn_width, btn_height, "Z +20")
        self.btn_z_minus = Button(x_base, y_pos + 70, btn_width, btn_height, "Z -20")
        
        # Vacuum button - repositioned
        self.btn_vacuum = Button(x_base + btn_spacing * 2 + 25, y_pos + 35, 100, BUTTON_HEIGHT, "Vacuum OFF")
        
        # Speed slider for jogging - moved down
        y_pos = 520
        self.speed_slider = Slider(x_base, y_pos, 320, 5, 200, 50, "Jog Speed (mm/s)")
        
        # Jog sliders for X, Y, Z axes (auto-center when released)
        y_pos = 575
        self.jog_x_slider = Slider(x_base, y_pos, 320, -100, 100, 0, "X Axis Jog", auto_center=True)
        self.jog_y_slider = Slider(x_base, y_pos + 55, 320, -100, 100, 0, "Y Axis Jog", auto_center=True)
        self.jog_z_slider = Slider(x_base, y_pos + 110, 320, -100, 100, 0, "Z Axis Jog", auto_center=True)
        
        # Log scroll offset
        self.log_scroll = 0
        
    def refresh_ports(self):
        """Refresh available COM ports"""
        self.available_ports = [port.device for port in list_ports.comports()]
        if self.available_ports:
            # Prefer USB ports
            usb_ports = [p for p in self.available_ports if 'USB' in p.upper()]
            if usb_ports:
                self.selected_port_index = self.available_ports.index(usb_ports[0])
            self.logger.info(f"Found {len(self.available_ports)} port(s)")
        else:
            self.logger.warning("No COM ports found")
        
    def connect_dobot(self):
        """Connect to Dobot"""
        if not self.available_ports:
            self.logger.error("No ports available")
            return
            
        port = self.available_ports[self.selected_port_index]
        try:
            self.logger.info(f"Connecting to {port}...")
            self.device = Dobot(port=port)
            self.is_connected = True
            self.btn_connect.text = "Disconnect"
            self.logger.info("Connected successfully")
            self.device.clear_alarms()
            time.sleep(0.5)
            self.update_position()
            self.start_position_updater()
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            
    def disconnect_dobot(self):
        """Disconnect from Dobot"""
        if self.device:
            try:
                self.device.close()
            except Exception as e:
                self.logger.error(f"Disconnect error: {e}")
        self.device = None
        self.is_connected = False
        self.btn_connect.text = "Connect"
        self.logger.info("Disconnected")
        
    def update_position(self):
        """Update current position from Dobot"""
        if not self.is_connected or not self.device:
            return
        try:
            pose = self.device.get_pose()
            self.current_pos["X"] = pose.position.x
            self.current_pos["Y"] = pose.position.y
            self.current_pos["Z"] = pose.position.z
            self.current_pos["R"] = pose.position.r
        except Exception as e:
            self.logger.warning(f"Position update failed: {e}")
            
    def start_position_updater(self):
        """Start background thread for position updates"""
        def updater():
            while self.running and self.is_connected:
                self.update_position()
                time.sleep(0.5)
        
        self.position_update_thread = threading.Thread(target=updater, daemon=True)
        self.position_update_thread.start()
        
    def move_to_position(self):
        """Move to specified position"""
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        try:
            x = float(self.input_x.get_value())
            y = float(self.input_y.get_value())
            z = float(self.input_z.get_value())
            r = float(self.input_r.get_value())
            
            self.logger.info(f"Moving to ({x}, {y}, {z}, {r})")
            threading.Thread(target=lambda: self.device.move_to(x, y, z, r), daemon=True).start()
        except ValueError:
            self.logger.error("Invalid coordinate values")
        except Exception as e:
            self.logger.error(f"Move error: {e}")
            
    def quick_move(self, axis: str, delta: float):
        """Quick move by delta on specified axis"""
        if not self.is_connected:
            return
        try:
            x = self.current_pos["X"]
            y = self.current_pos["Y"]
            z = self.current_pos["Z"]
            r = self.current_pos["R"]
            
            if axis == 'x': x += delta
            elif axis == 'y': y += delta
            elif axis == 'z': z += delta
            
            self.logger.info(f"Quick move {axis.upper()}{delta:+.0f}mm")
            threading.Thread(target=lambda: self.device.move_to(x, y, z, r), daemon=True).start()
        except Exception as e:
            self.logger.error(f"Quick move error: {e}")
            
    def handle_jogging(self):
        """Handle continuous jogging from joystick controls"""
        if not self.is_connected or not self.device:
            return
        
        # Get slider values (normalized to -1 to 1)
        vx = self.jog_x_slider.get_value() / 100.0
        vy = self.jog_y_slider.get_value() / 100.0
        vz = self.jog_z_slider.get_value() / 100.0
        
        # Apply deadzone
        deadzone = 0.05
        if abs(vx) < deadzone: vx = 0
        if abs(vy) < deadzone: vy = 0
        if abs(vz) < deadzone: vz = 0
        
        # Check if values changed
        current_jog = (vx, vy, vz)
        if current_jog == self.last_jog_values:
            return
        
        self.last_jog_values = current_jog
        
        try:
            if vx == 0 and vy == 0 and vz == 0:
                # Stop jogging
                self.device._set_jog_command(0)
            else:
                # Calculate velocities
                speed = self.speed_slider.get_value()
                vel_x = abs(vx * speed)
                vel_y = abs(vy * speed)
                vel_z = abs(vz * speed)
                
                # Set parameters for the dominant axis
                if abs(vx) > abs(vy) and abs(vx) > abs(vz):
                    self.device._set_jog_coordinate_params(vel_x, 0, 0, 0)
                    cmd = 1 if vx > 0 else 2
                elif abs(vy) > abs(vz):
                    self.device._set_jog_coordinate_params(0, vel_y, 0, 0)
                    cmd = 3 if vy > 0 else 4
                else:
                    self.device._set_jog_coordinate_params(0, 0, vel_z, 0)
                    cmd = 5 if vz > 0 else 6
                
                self.device._set_jog_command(cmd)
        except Exception as e:
            self.logger.error(f"Jog error: {e}")
            
    def toggle_vacuum(self):
        """Toggle vacuum on/off"""
        if not self.is_connected:
            return
        try:
            self.vacuum_on = not self.vacuum_on
            self.device.suck(self.vacuum_on)
            self.btn_vacuum.text = "Vacuum ON" if self.vacuum_on else "Vacuum OFF"
            self.logger.info(f"Vacuum {'ON' if self.vacuum_on else 'OFF'}")
        except Exception as e:
            self.logger.error(f"Vacuum error: {e}")
            
    def go_home(self):
        """Home the robot"""
        if not self.is_connected:
            self.logger.warning("Not connected")
            return
        try:
            self.logger.info("Homing...")
            threading.Thread(target=self.device.home, daemon=True).start()
        except Exception as e:
            self.logger.error(f"Home error: {e}")
            
    def draw_panel(self, x, y, width, height, title):
        """Draw a panel with title"""
        draw_rectangle(x, y, width, height, COLOR_PANEL)
        draw_rectangle_lines(x, y, width, height, Color(80, 80, 90, 255))
        if title:
            draw_text(title, x + 5, y + 5, 16, COLOR_TEXT)
            
    def draw_ui(self):
        """Draw all UI elements"""
        # Background
        clear_background(COLOR_BG)
        
        # Title - centered
        title = "DOBOT RAYLIB CONTROLLER"
        title_width = measure_text(title, 20)
        title_x = (WINDOW_WIDTH - title_width) // 2
        draw_text(title, title_x, 10, 20, COLOR_TEXT)
        
        # Connection status
        status_text = "CONNECTED" if self.is_connected else "DISCONNECTED"
        status_color = COLOR_CONNECTED if self.is_connected else COLOR_DISCONNECTED
        status_width = measure_text(status_text, 16)
        status_x = (WINDOW_WIDTH - status_width) // 2
        draw_text(status_text, status_x, 35, 16, status_color)
        
        # Port selection - centered below status
        port_label = "Port: "
        if self.available_ports:
            port_text = port_label + self.available_ports[self.selected_port_index]
        else:
            port_text = port_label + "None"
        port_width = measure_text(port_text, 14)
        port_x = (WINDOW_WIDTH - port_width) // 2
        draw_text(port_text, port_x, 50, 14, COLOR_TEXT_DIM)
        
        x_base = UI_LEFT_MARGIN
        
        # Connection buttons
        self.btn_refresh_ports.draw()
        self.btn_connect.draw()
        self.btn_home.draw()
        
        # Position display panel
        self.draw_panel(x_base, 105, 380, 40, "Current Position")
        pos_text = f"X:{self.current_pos['X']:7.2f}  Y:{self.current_pos['Y']:7.2f}  Z:{self.current_pos['Z']:7.2f}  R:{self.current_pos['R']:7.2f}"
        draw_text(pos_text, x_base + 5, 128, 13, COLOR_TEXT)
        
        # Movement input panel
        self.draw_panel(x_base, 155, 290, 175, "Movement Controls")
        draw_text("X:", x_base + 5, 180, 16, COLOR_TEXT)
        draw_text("Y:", x_base + 5, 220, 16, COLOR_TEXT)
        draw_text("Z:", x_base + 5, 260, 16, COLOR_TEXT)
        draw_text("R:", x_base + 5, 300, 16, COLOR_TEXT)
        
        self.input_x.draw()
        self.input_y.draw()
        self.input_z.draw()
        self.input_r.draw()
        self.btn_move.draw()
        
        # Quick move panel
        self.draw_panel(x_base, 340, 380, 120, "Quick Moves (±20mm)")
        self.btn_x_plus.draw()
        self.btn_x_minus.draw()
        self.btn_y_plus.draw()
        self.btn_y_minus.draw()
        self.btn_z_plus.draw()
        self.btn_z_minus.draw()
        self.btn_vacuum.draw()
        
        # Jogging panel
        self.draw_panel(x_base, 470, 380, 230, "Continuous Motion (Sliders)")
        self.speed_slider.draw()
        self.jog_x_slider.draw()
        self.jog_y_slider.draw()
        self.jog_z_slider.draw()
        
        # Log panel - centered and wide
        log_y = 710
        log_height = WINDOW_HEIGHT - log_y - PADDING
        log_width = WINDOW_WIDTH - PADDING * 2
        self.draw_panel(PADDING, log_y, log_width, log_height, "Log")
        
        # Draw log messages
        log_start_y = log_y + 25
        log_display_height = log_height - 30
        max_lines = int(log_display_height / 18)
        
        messages = self.log_handler.messages[-max_lines:]
        for i, msg in enumerate(messages):
            y = log_start_y + i * 18
            draw_text(msg[:110], PADDING + 5, y, 14, COLOR_TEXT_DIM)
        
        # Draw log messages
        log_start_y = log_y + 25
        log_display_height = log_height - 30
        max_lines = int(log_display_height / 18)
        
        messages = self.log_handler.messages[-max_lines:]
        for i, msg in enumerate(messages):
            y = log_start_y + i * 18
            draw_text(msg[:95], PADDING + 5, y, 14, COLOR_TEXT_DIM)
            
    def handle_input(self):
        """Handle user input"""
        # Keyboard controls for jog sliders
        # Left/Right arrows control Y slider
        if is_key_down(KEY_LEFT):
            self.jog_y_slider.value = max(-100, self.jog_y_slider.value - 2)
        elif is_key_down(KEY_RIGHT):
            self.jog_y_slider.value = min(100, self.jog_y_slider.value + 2)
        elif is_key_released(KEY_LEFT) or is_key_released(KEY_RIGHT):
            if self.jog_y_slider.auto_center:
                self.jog_y_slider.value = 0
        
        # Up/Down arrows control Z slider
        if is_key_down(KEY_UP):
            self.jog_z_slider.value = min(100, self.jog_z_slider.value + 2)
        elif is_key_down(KEY_DOWN):
            self.jog_z_slider.value = max(-100, self.jog_z_slider.value - 2)
        elif is_key_released(KEY_UP) or is_key_released(KEY_DOWN):
            if self.jog_z_slider.auto_center:
                self.jog_z_slider.value = 0
        
        # Z and X keys control X slider
        if is_key_down(KEY_Z):
            self.jog_x_slider.value = max(-100, self.jog_x_slider.value - 2)
        elif is_key_down(KEY_X):
            self.jog_x_slider.value = min(100, self.jog_x_slider.value + 2)
        elif is_key_released(KEY_Z) or is_key_released(KEY_X):
            if self.jog_x_slider.auto_center:
                self.jog_x_slider.value = 0
        
        # Button clicks
        if self.btn_refresh_ports.is_clicked():
            self.refresh_ports()
            
        if self.btn_connect.is_clicked():
            if self.is_connected:
                self.disconnect_dobot()
            else:
                self.connect_dobot()
                
        if self.btn_home.is_clicked():
            self.go_home()
            
        if self.btn_move.is_clicked():
            self.move_to_position()
            
        if self.btn_x_plus.is_clicked():
            self.quick_move('x', 20)
        if self.btn_x_minus.is_clicked():
            self.quick_move('x', -20)
        if self.btn_y_plus.is_clicked():
            self.quick_move('y', 20)
        if self.btn_y_minus.is_clicked():
            self.quick_move('y', -20)
        if self.btn_z_plus.is_clicked():
            self.quick_move('z', 20)
        if self.btn_z_minus.is_clicked():
            self.quick_move('z', -20)
            
        if self.btn_vacuum.is_clicked():
            self.toggle_vacuum()
            
        # Port selection with mouse wheel (when hovering over port text)
        mouse_wheel = get_mouse_wheel_move()
        if mouse_wheel != 0 and self.available_ports:
            self.selected_port_index = (self.selected_port_index + int(mouse_wheel)) % len(self.available_ports)
            
        # Handle jogging
        self.handle_jogging()
        
    def run(self):
        """Main application loop"""
        try:
            while not window_should_close():
                self.handle_input()
                
                begin_drawing()
                self.draw_ui()
                end_drawing()
        finally:
            self.running = False
            if self.is_connected:
                self.disconnect_dobot()
            close_window()


def main():
    """Entry point"""
    app = DobotRaylibController()
    app.run()


if __name__ == "__main__":
    main()
