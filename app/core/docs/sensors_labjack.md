# LabJack Interface Guide

The system supports LabJack T-Series (T4, T7) devices using the LJM library.

## Configuration

- **Connection**: Can be USB, Ethernet, or WiFi.
- **Channels**: Supports Analog Inputs (AIN), Digital I/O (FIO, EIO, CIO, MIO), and Counter inputs.

## High-Speed Acquisition

LabJack supports much higher sampling rates than standard serial devices. The `sampling_rate` in `configure_interface` affects how often the system pulls data from the LJM buffer.

## Adding Sensors

1.  **Connect**: `toggle_interface_connection(interface_name="LabJack", action="connect")`.
2.  **Mapping**: Use the standard LJM register names or aliases (e.g., `AIN0`, `FIO4`).
3.  **Setup**: `add_sensor(interface_name="LabJack", sensor_name="Pressure", mapping="AIN0")`.
