# Hardware Diagnostics

The Diagnostics tool is used for troubleshooting connection issues, discovering hardware, and monitoring raw data streams.

## Components

### 1. Interface Status Cards
Displays the real-time health of Arduinos, LabJacks, Cameras, and other interfaces.
- **Green**: Connected and active.
- **Red/Gray**: Disconnected or error state.
- **Test Connection**: Sends a ping or health check to the device.

### 2. Serial Port Scanner
Scans the computer for all available COM/TTY ports.
- Shows **VID/PID** (Vendor and Product IDs) to help identify specific Arduino models.
- Indicates if a port is currently **In Use** by the system or available.

### 3. Data Rate Monitor
Visualizes the incoming data throughput (Samples per Second).
- **Consistent Rate**: Good connection.
- **Dropping/Erratic Rate**: Potential serial buffer issues, bad cables, or EMI interference.

### 4. Serial Monitor (Console)
A terminal for raw communication with devices.
- **Green (<-)**: Data received from hardware.
- **Yellow (->)**: Commands sent to hardware.
- **Auto-scroll**: Keeps the latest data in view.

## Troubleshooting Protocol

1.  **Scanner**: Use "Scan Ports" to see if your USB device is even seen by the OS.
2.  **Status**: Check if the interface card is Green.
3.  **Monitor**: Open the Serial Monitor to see if the device is sending garbage data or error strings.
4.  **Baud Rate**: Verify the baud rate in Diagnostics matches the device's firmware.
