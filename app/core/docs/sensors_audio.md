# Audio Sensor Interface Guide

The Audio Sensor Interface transforms any connected microphone into a multi-purpose measurement tool. It samples high-frequency audio data and reduces it to low-bandwidth measurement streams (e.g., 10 Hz) suitable for graphing and automation.

## Measurement Modes

While the interface always calculates all values, the "Mode" setting in the UI primarily configures the default behavior and primary display.

| Mode | Description | Primary Output Keys |
| :--- | :--- | :--- |
| `rms` | Root Mean Square level (average energy/loudness). | `rms`, `db_level` |
| `peak` | Maximum absolute amplitude in the window. | `peak`, `peak_hold` |
| `frequency` | Dominant frequency detected via FFT. | `dominant_frequency` |
| `rpm` | Estimates RPM from dominant frequency. | `rpm` |
| `band_energy`| Energy within a specific frequency range. | `band_energy` |
| `zero_crossing`| Rate of zero-axis crossings (pitch indicator). | `zero_crossing_rate` |

## Output Keys (Available for all modes)
- `rms`: Average loudness (0.0 to 1.0).
- `peak`: Max amplitude in latest chunk.
- `peak_hold`: Max peak over a rolling window (see `peak_hold_ms`).
- `db_level`: Decibels relative to full scale (logarithmic).
- `dominant_frequency`: The strongest frequency (Hz).
- `rpm`: Calculated as `(frequency * 60) / pulses_per_rev`.
- `band_energy`: Energy in the band defined by `band_low` and `band_high`.
- `zero_crossing_rate`: Number of times the signal crosses zero per second.

## Configuration Parameters

Use the `configure_interface` tool to update these settings for an Audio sensor.

### General Settings
- `noise_gate`: (0.0 to 1.0) Signals below this RMS level are treated as silence (output 0).
- `smoothing`: (0.0 to 1.0) Exponential moving average factor. 0 = raw, 0.9 = heavy lag.
- `output_rate`: (Hz) How often to emit measurement values to the system.

### Frequency & RPM
- `min_frequency_hz`: Minimum frequency to consider (filters out low-frequency rumble).
- `rpm_pulses_per_rev`: Number of signal pulses expected per full revolution.

### Band Analysis
- `band_low`, `band_high`: (Hz) The frequency range for `band_energy` calculations.

## AI Interaction Protocol

1. **Setup**: Use `add_sensor(interface_name='Audio', ...)` to create a sensor.
2. **Analysis**: Use `get_audio_sensor_preview` to see the current spectrum (FFT) and levels. This helps determine the `noise_gate` and `band` settings.
3. **RPM Calibration**: If using for RPM, ask the user for the number of blades or pulses per revolution (`rpm_pulses_per_rev`).
4. **Triggering**: Audio values can be used in automation (e.g., "If RMS > 0.5, stop acquisition").
