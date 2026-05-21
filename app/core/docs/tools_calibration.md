# Sensor Calibration Tool

Calibration ensures that your sensor readings match real-world physical values. The Calibration Tool provides a step-by-step wizard to calculate correction factors.

## Calibration Methods

### 1. Linear (y = mx + b)
The most common method. Requires at least 2 calibration points.
- **Gain (m)**: The multiplier (slope).
- **Offset (b)**: The value added or subtracted.

### 2. Polynomial
For non-linear sensors (like NTC thermistors). Requires 3 or more points.
- Fits a curve ($y = ax^2 + bx + c$) to your data.

### 3. Manual Offset/Gain
Directly enter known calibration values (e.g., from a manufacturer's datasheet).

## Calibration Workflow

1.  **Select Sensor**: Choose from any active sensor in the dropdown.
2.  **Add Points**:
    - **Measured**: What the sensor currently shows.
    - **Actual**: The true value (from a reference standard like ice water or a calibrated gauge).
3.  **Calculate**: The tool computes the best-fit line or curve.
4.  **Check R²**:
    - **> 0.99**: Excellent fit.
    - **< 0.95**: Check for measurement errors or non-linearity.
5.  **Apply**: Saves the coefficients to the sensor configuration.

## Tips for Success

- **Wait for Stability**: Do not capture a point until the reading has fully stabilized.
- **Range Coverage**: Calibration points should span the entire range you intend to measure.
- **R² Awareness**: If R² is low, your sensor might be non-linear (try Polynomial) or the measurements were noisy.
- **Apply Settings**: Remember that after applying calibration, you may need to click "Apply Settings" in the main UI for hardware-level changes to take effect.
