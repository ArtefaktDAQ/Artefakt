# FFT Spectrum Analyzer

The FFT (Fast Fourier Transform) Spectrum Analyzer converts a time-domain signal into its frequency components. It allows you to see the "hidden" frequencies within your sensor data.

## Key Features

- **Live Spectrum**: Real-time visualization of frequencies (Hz) vs. Amplitude (dB or Linear).
- **Spectrogram (Waterfall)**: A history of how frequencies change over time, using color to represent intensity.
- **THD Calculation**: Automatically measures Total Harmonic Distortion.
- **RPM Estimation**: Estimate RPM from frequency peaks by specifying pulses per revolution.
- **Audio Support**: Can analyze live audio directly from connected microphones.

## Settings & Controls

### FFT Size (128 - 8192)
- **Larger (4096+)**: Better frequency resolution (precision), but slower update rate.
- **Smaller (1024-)**: Faster response time, but coarser frequency bins.

### Window Types
- **Hanning (Recommended)**: Best all-around for general signals.
- **Hamming**: Better for resolving two frequencies very close to each other.
- **Blackman**: Best for detecting weak signals next to very strong ones.

### Scaling
- **dB Scale**: Logarithmic amplitude. 0 dB is reference. Useful for seeing weak signals and noise floors.
- **Log Frequency**: Useful for audio analysis where Octaves are more relevant than linear Hz.

## Interpreting Results

- **Tall Peaks**: Represent dominant frequencies (e.g., motor rotation, electrical hum).
- **Harmonics**: Peaks at 2x, 3x, 4x the fundamental frequency.
- **Noise Floor**: The baseline "fuzz" at the bottom. A lower floor means a cleaner measurement.
- **Spectrogram Colors**: Brighter colors represent stronger signals at that frequency and time.
