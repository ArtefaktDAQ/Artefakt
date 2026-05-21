# Dashboard and Video Control Guide

The AI Assistant can control the Dashboard layout and manage data/video playback during replay.

## Dashboard Configuration
The AI can customize the dashboard view using the `set_dashboard_config` tool.
- **Visibility**: Toggle panels for Automation Status, System Events, Last Images, and Camera Preview.
- **Timespan**: Set the graph window (e.g., "10s", "1min", "All").
- **Camera Slots**: Enable or disable specific camera feeds (Cam 1-4).

## Playback Control (Replay Mode)
When a run is loaded for replay, the AI uses the `control_playback` tool for precise navigation.

### Key Actions
- **Play/Pause/Stop**: Control the state of synchronized data and video playback.
- **Speed**: Adjust playback rate from 0.25x to 4x.
- **Positioning**: Jump to a specific time (e.g., "12:21" or "40s").
- **Frame Stepping**: Move forward or backward by a specific number of frames. The system uses the actual recorded FPS for high precision.

### AI Interaction Protocol
1. **Seeking vs Playing**: Setting a `position` or `step_frames` will seek to that point but **will NOT** automatically start playback. If the user wants to "go to 40s and play", the AI must call the tool with both `position="40"` and `action="play"`.
2. **Precision**: Use frame stepping for detailed analysis of high-speed events.
3. **Context**: Always check if a run is loaded before attempting playback controls.

## Quick Notes
The AI can add timestamped observations using the `add_quick_note` tool.
- **Live Mode**: Uses current elapsed time.
- **Replay Mode**: Uses the current replay playhead time with a "REPLAY" prefix.
- **Usage**: "Add a quicknote that the sensor1 has some fluctuations" -> `add_quick_note(text="sensor1 has some fluctuations")`.
