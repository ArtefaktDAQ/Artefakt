# AI Camera & Vision System Manual

This document explains how the AI Assistant can manage cameras, video recordings, and overlays in the Artefakt DAQ system.

## Camera Management

The system supports up to 4 simultaneous camera slots (`cam1`, `cam2`, `cam3`, `cam4`), which correspond to slot indices 0, 1, 2, and 3.

**Slot Indexing (STRICTLY MANDATORY)**:
- UI 'Slot 1' = 'cam1' = tool `slot_index: 0`
- UI 'Slot 2' = 'cam2' = tool `slot_index: 1`
- UI 'Slot 3' = 'cam3' = tool `slot_index: 2`
- UI 'Slot 4' = 'cam4' = tool `slot_index: 3`

**WARNING**: The system uses 0-based indexing for tools. 
- If you use `slot_index: 1`, you are connecting to **Cam 2**. 
- If you use `slot_index: 2`, you are connecting to **Cam 3**. 
- Never guess the index; always use the mapping above. If the user says "Cam 2", you MUST pass `slot_index: 1`.

### Connecting Cameras
You can connect both local USB/Integrated webcams and NDI (Network Device Interface) streams.

**CRITICAL: Tool Parameters for Connection**:
- **Local Cameras**: 
    - `source`: Integer index (0, 1, 2...).
    - `mode`: **0** (MANDATORY for Local).
    - Note: Virtual NDI drivers (like "NDI Webcam Video 1") are Local (Mode 0).
- **NDI Cameras**: 
    - `source`: Network name string (e.g., "DESKTOP-ABC (OBS)").
    - `mode`: **1** (MANDATORY for NDI). 
    - Note: These are network-based streams and should be preferred for high-quality remote video.

When connecting a camera:
- If a slot index is specified, the camera is connected to that slot.
- If no slot is specified, the system automatically uses the next available (free) slot.
- For Local cameras, you can specify resolution (e.g., "1280x720") and FPS.
- For NDI cameras, resolution and FPS are handled automatically by the stream.

### Tools for Cameras
- `list_camera_sources`: Use this to find what cameras are physically connected or available on the network.
- `connect_camera`: Connects a source to a slot.
- `disconnect_camera`: Disconnects a specific slot.
- `get_camera_frame`: Captures a live frame from a camera (Base64). Essential for visual analysis.
- `take_camera_snapshot`: Captures a high-quality frame and saves it to the project's `Snapshots` folder.
- `set_camera_properties`: Adjust hardware settings like focus and exposure.
    - `manual_focus`: Boolean.
    - `focus_value`: 0-255.
    - `manual_exposure`: Boolean.
    - `exposure_value`: Usually -5 to -13 for webcams.

### Verification & Troubleshooting
**IMPORTANT**: Some camera sources (especially virtual NDI cameras or OBS virtual cameras) may connect successfully but only display a **black screen** or a "No Signal" image. Virtual cameras from NDI can also be in the normal camera source list.

#### Troubleshooting Protocol:
1.  **Visual Check**: After calling `connect_camera`, you **MUST** call `get_camera_frame` to visually verify that the camera is actually working and showing the intended subject.
2.  **Handling Black Frames**: If `get_camera_frame` returns `is_dark_frame: true` or you see a black screen:
    -   **ABANDON IMMEDIATELY**: If a camera shows black, it is likely a virtual driver or a disconnected cable. Do not waste time analyzing it.
    -   **Try other indices**: If index `0` shows a black screen, try index `1`, `2`, etc. Webcams often shift indices if multiple devices are plugged in.
    -   **Check NDI**: If you are looking for an NDI source, ensure it's not actually showing up as a local camera index (some NDI tools create virtual webcams).
3.  **Speed Optimization**: To keep interactions fast, the system automatically resizes images for you. Do not request high resolution frames unless absolutely necessary for measurement.
4.  **Handling Connection Failures**: If `connect_camera` returns an error about "driver lock" or "busy":
    -   Wait 2 seconds and try again.
    -   Try a different slot index (0-3).
5.  **Wait for Initialization**: If `get_camera_frame` says the camera is "still initializing", wait 5 seconds and try `get_camera_frame` again. DO NOT immediately call `connect_camera` again, as this will reset the connection process. High-resolution webcams often take several seconds to stabilize their drivers.

## Recording System

The system can record video and audio from any connected camera slot.

### Tools for Recording
- `start_camera_recording`: Begins recording for a specific slot or all cameras.
- `stop_camera_recording`: Stops active recordings.

Recording features:
- **Hardware Acceleration**: Automatically uses NVIDIA, Intel, or AMD encoders if available.
- **Audio**: Captures audio from the configured microphone for each slot.
- **Metadata**: Recording paths and timestamps are automatically saved to the project's metadata.

## Overlay System

Overlays are graphics or text drawn on top of the live video feed. They are applied in real-time to the UI preview, snapshots, and recorded video files.

### Overlay Types
1.  **Text**: Static text. Set `content="My Text"`.
2.  **Timestamp**: Dynamic clock. Set `content="%Y-%m-%d %H:%M:%S"`.
3.  **Sensor**: Dynamic sensor value. Set `content="Sensor Name"`. **To show live data on video, provide the EXACT sensor name (e.g. 'Load Cell') in the 'content' field.**
4.  **Rectangle**: Graphical box for highlighting.
5.  **Motion Indicator**: A status light that turns red when motion is detected, and green when the scene is idle.

### Persistence (CRITICAL)
- **Adding/Updating an overlay DOES NOT require disconnecting the camera.** Simply call `manage_camera_overlay` with `action='add'`. It will appear immediately if the camera is running.
- Overlays are saved to the project configuration and will persist across restarts.

### Positioning
Coordinates are **normalized** from `0.0` to `1.0`:
- `(0.0, 0.0)` is Top-Left.
- `(1.0, 1.0)` is Bottom-Right.
- `(0.5, 0.5)` is Center.

### Styling
- **text_color**: (B, G, R) tuple, e.g., `(255, 255, 255)` for white.
- **bg_color**: (B, G, R) tuple, e.g., `(0, 0, 0)` for black.
- **bg_alpha**: `0.0` (transparent) to `1.0` (opaque).
- **font_scale**: Size multiplier (default `0.7`).
- **thickness**: Line/font thickness (default `2`).

### Tools for Overlays
- `manage_camera_overlay`: `add`, `update`, or `remove` overlays.
- `list_camera_overlays`: Use this to find `overlay_id`s for existing overlays before updating or removing them.

## Motion Detection

Each camera has an independent motion detection engine.

### Configuration
Use `set_motion_detection_settings`:
- **sensitivity**: 0-100. Lower is more sensitive.
- **min_area**: Minimum pixel size of moving objects.

### Automation
Motion events trigger internal system signals:
- `motion_detected`: Triggered when ANY camera detects motion.
- `motion_detected_cam1`: Triggered specifically by Camera 1.
These can be used as triggers in the Automation System.

## Optical Sensors (Vision as Measurement)

Unlike standard cameras used for viewing, **Optical Sensors** use camera frames to derive numerical data (Brightness, RPM, Fill Level, etc.).

### ROI (Region of Interest)
Optical sensors rely on a specific part of the frame for measurement. You can configure this using the `configure_interface` tool.
- Parameters: `roi_x`, `roi_y`, `roi_width`, `roi_height`.
- Coordination: Use `get_camera_frame` to see the current view, then calculate the coordinates (usually based on a 640x480 resolution) to focus the sensor on a specific object (e.g., a dial, an LED, or a tank).

### Modes
- `brightness`: Returns average intensity.
- `light_events`: Counts flashes/scintillations.
- `rpm`: Estimates speed from brightness modulation.
- `fill_level`: Detects liquid level in a specified ROI.
