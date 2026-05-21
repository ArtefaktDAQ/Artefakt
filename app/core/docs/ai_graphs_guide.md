# AI Graph Analysis & Configuration Guide

This guide describes the available graph types, styling options, and control functions available in the EvoLabs DAQ system.

## AI Interaction Protocol
1. **MANDATORY**: You MUST NOT ask the user to perform any actions (e.g., "Please select a sensor"). You have tools to do this yourself.
2. **MANDATORY**: Use the `set_graph_config` tool to apply changes to the graph view.
3. **MANDATORY**: Only change parameters explicitly requested by the user. For example, if the user asks for a graph type change, do NOT change the `style_preset` or `line_width` unless they asked for that too.
4. **MANDATORY**: Use the `get_graph_screenshot` tool to visually analyze trends before making conclusions.

## Available Graph Types

The system supports several visualization modes:

| Type | Description | Use Case |
|------|-------------|----------|
| **Standard Time Series** | Standard value vs time plot. | General monitoring. |
| **Temperature Difference** | Calculates and plots the difference between two sensors. | Delta-T analysis. |
| **Rate of Change (dT/dt)** | Calculates the first derivative of the sensor signal. | Cooling/heating rate analysis. |
| **Moving Average** | Applies a smoothing window to the data. | Filtering noisy signals. |
| **Fourier Analysis (FFT)** | Converts time-domain data to frequency-domain. | Vibration and periodic signal analysis. |
| **Histogram** | Shows the distribution of sensor values. | Statistical spread analysis. |
| **Box Plot** | Displays quartiles, median, and outliers. | Comparing data distributions. |
| **Correlation Analysis** | Plots one sensor against another (XY plot). | Finding relationships between variables. |

## Graph Functions

### Show Control Run
The `show_control_run` parameter in `set_graph_config` allows you to overlay data from a previously designated "Control Run" onto the current graph. This is essential for:
- Comparing current experiment performance against a baseline.
- Identifying deviations from expected behavior.
- Validating consistency across multiple tests.

**Style Hint**: Control run data is typically displayed as a **dashed line** to distinguish it from the active "Solid" live data.

### Control Run Offset
The `control_run_offset` parameter in `set_graph_config` allows shifting the control run data horizontally on the time axis (in seconds).
- **Positive values**: Shift the control run to the **right** (starts later).
- **Negative values**: Shift the control run to the **left** (starts earlier).
- Use this to align peaks or events between the live run and the reference data.

### Styling & Presets
The `style_preset` parameter allows switching between pre-configured visual themes:
- **Standard**: Default look with standard colors.
- **Solarized**: Low-contrast, eye-friendly theme.
- **Dark**: Dark background optimized for low-light environments.
- **High Contrast**: Maximum visibility with bold colors.
- **Pastel**: Soft color palette for better readability of many lines.
- **Colorful**: Vibrant colors for distinguishing many sensors.

### Timespan Control
The `timespan` parameter controls the horizontal axis window. Options range from **10s** to **24h**, or **All** to see the entire dataset.

## Tool Usage: `set_graph_config`

Use this tool to immediately update the user's view. 

Example: "Set graph to Fourier Analysis for sensor 'Vibration_1' with High Contrast style."
```json
{
  "graph_type": "Fourier Analysis",
  "primary_sensor": "Vibration_1",
  "style_preset": "High Contrast"
}
```

Example: "Show me the current run compared to the control run over the last 5 minutes."
```json
{
  "show_control_run": true,
  "timespan": "5min"
}
```
