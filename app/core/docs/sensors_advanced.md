# Advanced Sensors Guide (Optical & Audio)

## Optical Sensors (Computer Vision)

Optical sensors use a camera feed to extract data (e.g., color intensity, movement, position).

- **ROI (Region of Interest)**: Defined by `x, y, width, height`.
- **Thresholds**: Used to distinguish signal from background.
- **Configuration**: Use `configure_interface(interface_name="Optical", params={...})`.

## Audio Sensors

Audio sensors capture microphone data and can perform real-time FFT (Fast Fourier Transform) to monitor specific frequency bands.

- **Bands**: Configure `band_low` and `band_high`.
- **Noise Gate**: Filters out background hum.
- **Configuration**: Use `configure_interface(interface_name="Audio", params={...})`.
