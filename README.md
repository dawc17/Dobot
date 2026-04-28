# Dobot Magician Web Controller

A comprehensive web-based controller for the Dobot Magician robot arm with advanced sequence programming, color sorting, and teach mode capabilities.

## Features

### Basic Control
- Manual jogging with keyboard (arrow keys and X/Z) or web UI
- Real-time position monitoring 
- Suction cup and gripper control
- Conveyor belt control with speed and direction
- Digital I/O control

### Sequence Programming
- Visual sequence editor with drag & drop
- Multiple step types:
  - **Move To**: Absolute positioning with optional speed override
  - **Move Rel**: Relative movement
  - **Move To Named**: Reference saved positions by name with offsets
  - **Suction/Gripper**: End effector control
  - **Wait**: Timed delays
  - **Speed**: Change velocity and acceleration
  - **IO Control**: Set digital outputs
  - **Conveyor**: Belt control with duration or distance
  - **Color Branch**: Conditional branching based on color sensor
  - **Wait for Color**: Pause until specific color detected
  - **Wait IO**: Pause until digital input condition met
  - **Loop N**: Repeat sequence sections N times
  - **Run Sequence**: Execute another saved sequence file

### Named Position Bank
- Save frequently used positions with descriptive names (e.g., \"above conveyor\", \"red bin\", \"home\")
- Reference positions by name in sequences instead of raw coordinates
- Easy to update when positions shift - just update the named position
- Positions persist between sessions in `positions.json`

### Teach Mode
- **Record Button**: Manually move the arm and capture waypoints
- Automatically generates Move To sequences from real positions
- Eliminates need to manually enter coordinates
- Essential for precise positioning tasks

### Color Sort Wizard  
- One-click generation of complete sorting sequences
- Automatically creates: wait for object → read color → pick → sort to bin
- Just teach the bin positions and the wizard builds the sequence
- Perfect for conveyor sorting applications

### Speed Profiles
- Set custom speeds for individual move steps
- Override global speed settings per step
- Useful for fast travel moves + slow precise operations
- Speed shown in step labels (e.g., \"Move To (100, 50, 80) @150mm/s\")

### Advanced Sequence Features
- **Sequence Chaining**: Call sub-sequences as reusable routines
- **Loop Control**: Loop sequences N times or forever
- **Conditional Logic**: Branch based on color sensor readings
- **IO Integration**: Trigger on external sensors and buttons
- **Real-time Monitoring**: Live position updates during playback

## How to Run

### Setup
1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\\Scripts\\activate     # Windows
   ```

2. Install dependencies:
   ```bash
   pip install flask pydobotplus pyserial
   ```

3. Start the web server:
   ```bash
   python web_server.py [port]
   ```

4. Open browser to `http://localhost:5000` (or specified port)

### Quick Start Guide

1. **Connect**: Select COM port and click Connect
2. **Home**: Click Home to calibrate the arm
3. **Teach Mode**: 
   - Click \"Start Teach\" to begin recording
   - Manually jog the arm to desired positions
   - Click \"Capture\" at each waypoint
   - Click \"Stop Teach\" when done
4. **Named Positions**: Save frequently used positions for easy reference
5. **Sequences**: Build complex automation by combining steps
6. **Color Sorting**: Use the wizard to generate sorting sequences automatically

## File Structure
- `web_server.py` - Main web server and robot control logic
- `static/index.html` - Web UI interface  
- `sequences/` - Saved sequence files (JSON format)
- `positions.json` - Named position bank
- `dobot_raylib.py` - Alternative raylib-based controller (legacy)

## API Endpoints
The web server exposes a RESTful API for all robot functions:
- `/api/connect` - Connect to robot
- `/api/move` - Manual positioning
- `/api/sequence/*` - Sequence management
- `/api/positions/*` - Named position management
- `/api/teach/*` - Teach mode control
- `/events` - Server-sent events for real-time updates

## Sequence File Format
Sequences are stored as JSON with this structure:
```json
{
  \"name\": \"My Sequence\",
  \"version\": 1,
  \"steps\": [
    {\"type\": \"move_to\", \"params\": {\"x\": 200, \"y\": 0, \"z\": 50, \"r\": 0, \"speed\": 100}},
    {\"type\": \"suction\", \"params\": {\"on\": true}},
    {\"type\": \"move_to_named\", \"params\": {\"name\": \"dropoff\", \"dx\": 0, \"dy\": 0, \"dz\": 10, \"dr\": 0}}
  ]
}
```

## Safety Notes
- Always ensure adequate workspace clearance
- Test sequences at slow speeds initially  
- Use emergency stop if available
- Monitor the robot during automated sequences

## Troubleshooting
- **Connection Issues**: Check COM port, ensure no other software is using the port
- **Sequence Errors**: Check step parameters and ensure named positions exist
- **Color Sensor**: Verify sensor is enabled and properly positioned
- **Performance**: Reduce UI update frequency for older computers