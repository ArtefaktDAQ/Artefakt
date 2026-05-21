# Vision and Graph Analysis Guide

The AI Assistant has "eyes" through the `get_graph_screenshot` tool and the "Attach Graph" feature in the UI.

## Graph Layout
- **X-Axis**: Represents time. By default, it shows "Time Since Start" in seconds or absolute system time.
- **Y-Axis**: Represents the sensor value in its configured unit (e.g., Volts, Celsius, PSI).
- **Multiple Axes**: Some graphs use a secondary Y-axis (right side) for sensors with different scales.

## Visual Analysis Tips
- **Noise**: Rapid, small fluctuations. If excessive, suggest checking hardware shielding or increasing smoothing.
- **Drift**: A slow, steady increase or decrease not related to the experiment.
- **Spikes**: Sudden, extreme values that usually indicate electrical interference or a loose connection.
- **Correlation**: Look for sensors that move in sync (e.g., Pressure drops as Valve opens).

## Motion Detection
The camera view can detect motion. These events are logged as `MOTION_DETECTED` and can be used as automation triggers.
- **Visuals**: The motion overlay shows a **RED** dot when motion is detected, and a **GREEN** dot when the scene is idle.
- **Sensitivity**: 0-100 scale.
- **Min Area**: Minimum size of a moving object to trigger an event.

## AI Interaction Protocol (CRITICAL)
1. **Never ask the user to call tools**: You must capture screenshots and frames yourself using `get_graph_screenshot` or `get_camera_frame`.
2. **Action-First Principle**: If the user asks "What do the graphs look like?", capture the screenshot **first**, analyze it, and then reply.
3. **No tool syntax in chat**: Do not output code like `get_camera_frame(slot=0)` to the user. Just describe what you see.
