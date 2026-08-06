# Arduino Interface Guide

The **Arduino** interface is designed for devices running the standard Artefakt Master-Slave protocol.

## Protocol Details

- **Format**: Data is expected as `Key:Value;` pairs (e.g., `A0:45.2;A1:1023;`).
- **No Sequence Required**: Unlike the generic Serial interface, the Arduino interface handles polling and parsing automatically.
- **Master-Slave**: The system usually sends a poll command and the Arduino responds with all its active channels.

## Adding Sensors

To add an Arduino sensor:
1.  **Identify Port**: Use `list_serial_ports`.
2.  **Connect**: Use `toggle_interface_connection(interface_name="Arduino", action="connect", params={"port": "COMx"})`.
3.  **Add Sensor**: Use `add_sensor(interface_name="Arduino", sensor_name="MySensor", mapping="A0")` (where `A0` is the key sent by the Arduino).

## Comparison with Serial Interface

| Feature | Arduino Interface | Serial Interface (OtherSerial) |
| :--- | :--- | :--- |
| **Parsing** | Automatic (`Key:Value;`) | Custom (Regex, Markers) |
| **Protocol** | Standard Fixed | Fully Configurable Sequence |
| **Complexity** | Low | High |
| **Best For** | Standard Arduino DAQ | Third-party Sensors, Custom Protocols |
