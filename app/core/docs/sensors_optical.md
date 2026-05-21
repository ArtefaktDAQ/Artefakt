# Optical Sensor Interface Guide

The Optical Sensor Interface allows using any USB camera or integrated webcam as a high-speed measurement sensor. Unlike standard camera slots which are for recording, the Optical Sensor processes every frame in real-time to extract data values.

## Detection Modes

| Mode | Description | Output Keys |
| :--- | :--- | :--- |
| `light_events` | Detects small, sudden bright spots (scintillation, electron impacts). | `event_count`, `max_brightness`, `mean_brightness`, `bright_pixel_count` |
| `brightness` | Measures average brightness in an ROI. | `brightness_mean`, `brightness_max`, `brightness_min`, `brightness_std` |
| `color` | Tracks RGB/HSV values of the scene or a specific target. | `red`, `green`, `blue`, `hue`, `saturation`, `value`, `target_color_percent` |
| `position` | Tracks the X/Y coordinates of the brightest or most colorful spot. | `position_x`, `position_y`, `position_x_percent`, `position_y_percent` |
| `particle_count`| Counts distinct bright objects within a size range. | `particle_count`, `total_contours` |
| `fill_level` | Detects the level of a substance in a container (horizontal/vertical). | `fill_level` |
| `rpm` | Estimates RPM from brightness modulation (frequency analysis). | `rpm`, `rpm_freq_hz`, `rpm_confidence` |

## Configuration Parameters

Use the `configure_interface` tool to update these settings for an Optical sensor.

### General Settings
- `mode`: Switch between detection modes.
- `camera_id`: (Integer) The system ID of the camera (0, 1, 2...).

### ROI (Region of Interest)
Most modes use a specific ROI to focus processing. Coordinates are in pixels relative to the frame size (default 640x480).
- `roi_x`, `roi_y`, `roi_width`, `roi_height`: Used for `fill_level`.
- `brightness_roi_x`, `brightness_roi_y`, `brightness_roi_width`, `brightness_roi_height`: Used for `brightness`.
- `rpm_roi_x`, `rpm_roi_y`, `rpm_roi_width`, `rpm_roi_height`: Used for `rpm`.

### Light Events & Particles
- `brightness_threshold`: (Int) Minimum brightness above baseline to trigger detection.
- `min_pixels`, `max_pixels`: (Int) Size range for objects/events.
- `cooldown_ms`: (Int) Minimum time between event triggers.
- `threshold_mode`: `"absolute"` or `"relative"`.

### Color Tracking
- `target_hue`: (0-179) HSV hue to track.
- `hue_tolerance`: (Int) Width of the hue range.
- `saturation_min`: (0-255) Minimum saturation for a pixel to count.

### RPM Estimation
- `rpm_min_hz`, `rpm_max_hz`: Frequency range to search.
- `rpm_pulses_per_rev`: Number of pulses expected per full revolution.

## AI Interaction Protocol

1. **Discovery**: Use `list_camera_sources` to find available camera IDs.
2. **Setup**: Add an Optical sensor using `add_sensor(interface_name='Optical', ...)`.
3. **Configuration**: If the user wants to measure a specific area, ask for coordinates or suggest using `get_optical_sensor_preview` (if available) to see the frame.
4. **Optimization**: If readings are noisy, suggest adjusting the `brightness_threshold` or `roi`.
