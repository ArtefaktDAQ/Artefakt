# Sensors and Hardware Guide (Main)

The system supports a wide range of hardware interfaces. Each sensor is represented by a `SensorModel` and managed by the `SensorController`.

## Interface Selection

| Interface | Best For | Documentation Topic |
| :--- | :--- | :--- |
| **Arduino** | Standard DAQ boards with Master-Slave protocol. | `sensors_arduino` |
| **Serial** | Custom protocols, non-standard devices, probing. | `sensors_serial` |
| **LabJack** | Industrial-grade analog/digital I/O (T-Series). | `sensors_labjack` |
| **MQTT** | IoT devices, remote sensors over network. | `sensors_mqtt` |
| **Read CSV** | Static log files, simulation data. | `sensors_csv` |
| **Remote DAQ** | Distributed gRPC streaming (LAN/VPN). | `sensors_remote_daq` |
| **Optical** | Visual analysis (Color, ROI, Motion). | `sensors_advanced` |
| **Audio** | Sound levels, frequency band analysis (FFT). | `sensors_advanced` |

**CRITICAL: If you need specific details on how to configure or parse data for an interface, you MUST call `get_documentation(topic="...")` using the topic name from the table above.**

## Core Concepts

### Calibration and Processing
Each sensor applies the formula: $V_{processed} = (V_{raw} \times factor) + offset$.
Advanced calibration uses polynomial coefficients. See `topic="tools_calibration"` for manual calibration guide.

### Styling and Display
You can change sensor colors and axis assignments using `update_sensor_settings`.
- **Color**: `color="#RRGGBB"` (e.g., "#FF0000" for Red).
- **Secondary Y-Axis**: `use_secondary_axis=True` moves the sensor to the right-side Y-axis.
- **Show in Graph**: `show_in_graph=False` hides the sensor from plots without disabling data recording.

The system accepts both the **Display Name** (e.g., "Temperature") or the **Internal ID** (e.g., "arduino_ai0") for the `sensor_name` parameter.
Valid colors are Hex strings.

### Data Flow
1. **Acquisition**: Hardware interfaces poll at the global sampling rate.
2. **Buffering**: Data is stored in the `historical_buffer` (RAM).
3. **Storage**: Data is streamed to CSV files in the project's run directory.

## AI Management Protocol (MANDATORY)

1.  **Observe First**: Always query existing state (`get_project_config`, `get_available_sensors`) before making changes.
2.  **Use Tools directly**: Never ask the user to configure sensors or run sequences. You have the tools: `add_sensor`, `remove_sensor`, `edit_sensor`, `configure_interface`, `configure_serial_sequence`, and `get_serial_sequence`.
3.  **Discovery Workflow**: For any serial device, use `test_serial_command` to see raw data before attempting to write a sequence, then verify with `get_serial_sequence`.
4.  **No Tool Syntax in Chat**: Communicate in plain English. Perform the tool calls silently and report results.

**NOTE**: For detailed Serial (OtherSerial) protocol rules (Wait steps, Publish steps, exact JSON), see `topic="sensors_serial"`. Serial sequences are NOT Automations — do not use `get_automation_info` to inspect them.
