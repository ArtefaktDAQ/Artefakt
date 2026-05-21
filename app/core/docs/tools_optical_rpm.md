# Optical RPM & Event Sensor

The Optical Tool uses computer vision to turn any camera into a measurement device. It is specifically optimized for high-speed event detection and rotation (RPM) analysis.

## Detection Modes

### 🔁 Optical RPM
- **How it works**: Analyzes brightness fluctuations in a Region of Interest (ROI).
- **Pulses per Rev**: Set this to the number of blades or markers on your rotating object.
- **Frequency Analysis**: Uses an internal FFT to find the dominant rotation frequency.

### ☀️ Brightness Monitoring
- Measures **Mean, Max, Min, and Std Dev** of brightness in the ROI.
- Useful for detecting flashes, shadows, or ambient light changes.

### ✨ Particle Counter
- Counts distinct bright objects (contours) in the frame.
- **Filters**: Set Min/Max pixel sizes to ignore noise or large objects.

### 💡 Light Events
- Optimized for "Scintillation" style events (sudden, brief flashes).
- **Thresholds**:
    - **Absolute**: Fixed brightness level.
    - **Relative (Sigma)**: Automatically adapts to background noise. `3-Sigma` is the recommended scientific standard.

## Setup Tips

1.  **ROI (Region of Interest)**: Draw a box around the area you want to monitor. Avoid including moving backgrounds or flickering lights.
2.  **Exposure**: For best results, lock your camera's exposure to Manual. Auto-exposure will fight the sensor's brightness readings.
3.  **Frame Rate**: Higher FPS (30+) is required for accurate RPM measurements of fast-moving objects.
4.  **Dark Background**: When counting particles or detecting flashes, a dark, non-reflective background is essential.
