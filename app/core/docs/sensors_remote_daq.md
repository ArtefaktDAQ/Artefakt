# Remote DAQ (gRPC) Interface

Remote DAQ allows distributed data acquisition by streaming live sensor data, video feeds, and audio between different Artefakt DAQ instances over a network. It uses the high-performance gRPC protocol for efficient, bidirectional communication.

## Core Concepts

- **Master (Server)**: The instance that has the hardware connected and "broadcasts" the data.
- **Client**: The instance that connects to a Master to receive and record/visualize the data.
- **Protocol**: gRPC (Google Remote Procedure Call).
- **Network Scope**: Designed for Local Area Networks (LAN) or VPNs. Direct internet use requires a secure tunnel (e.g., VPN or SSH port forward).

## Capabilities

| Feature | Description |
| :--- | :--- |
| **Sensor Streaming** | Real-time transmission of all active sensor values with millisecond-accurate timestamps. |
| **Video Streaming** | Live camera feeds with overlays, compressed for network efficiency. |
| **Audio Streaming** | PCM audio data for remote acoustic monitoring. |
| **Bidirectional** | Supports multi-client connections to a single master. |

## Configuration

### Starting a Master (Streamer)
1.  Open the **Remote gRPC** dialog from the Devices section.
2.  In the **Master** tab, enter a **Stream Name** and optional **Password**.
3.  Select which data types to stream (Sensors, Video, Audio).
4.  Click **Start Streaming**. The server will listen on the default port (**50051**).

### Connecting as a Client
1.  Open the **Remote gRPC** dialog on the client machine.
2.  In the **Client** tab, enter the **Master Address** (IP or hostname).
3.  Enter the **Stream Name** and **Password** set by the master.
4.  Select the data you wish to receive.
5.  Click **Connect to Stream**.

## AI Protocol

As the AI Assistant, you can:
- **Guide the User**: Explain how to set up the connection between two machines.
- **Troubleshoot**: If the connection fails, suggest checking the IP address, firewall settings (Port 50051), or VPN status.
- **Analyze Remote Data**: Once connected, remote sensors appear just like local sensors in the `get_available_sensors` list. You can query and analyze them normally.

## Troubleshooting

- **Connection Timeout**: Ensure both machines are on the same subnet or connected via VPN.
- **Port Blocked**: Verify that Port 50051 is open in the Windows Firewall or network router.
- **Bandwidth Issues**: If the video stream is laggy, ensure you are on a wired Gigabit connection or a strong 5GHz Wi-Fi signal.
