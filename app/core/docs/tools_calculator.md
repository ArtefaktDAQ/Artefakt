# Engineering Calculator

A collection of utility calculators for common engineering tasks related to DAQ and sensor setup.

## 1. Unit Converter
Convert between standard SI and Imperial units for:
- **Temperature**: C, F, K.
- **Pressure**: bar, psi, Pa, atm, mmHg.
- **Frequency**: Hz, kHz, MHz, RPM.
- **Electrical**: V, A, Ohms, Watts.

## 2. RTD & NTC Calculator
Calculate Temperature from Resistance (or vice versa) for:
- **RTDs**: PT100, PT1000 (using Callendar-Van Dusen).
- **NTCs**: 10k, 100k Thermistors (using Steinhart-Hart).

## 3. Electrical (Ohm's Law)
Quick solver for $V = I \times R$ and $P = V \times I$. Enter any two values to find the others.

## 4. Signal Scaling
Helps you determine the Factor and Offset for a new sensor.
- **Input Range**: (e.g., 0V to 5V from a sensor).
- **Output Range**: (e.g., 0 bar to 10 bar).
- **Result**: Provides the `Factor` (Slope) and `Offset` to use in the sensor configuration.

## 5. dB Calculator
Convert between linear ratios and Decibels.
- Supports both **Voltage (20 log)** and **Power (10 log)** modes.
