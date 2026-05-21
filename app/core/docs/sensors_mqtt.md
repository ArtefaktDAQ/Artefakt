# MQTT Sensor Interface Guide

The MQTT Interface allows receiving data from any MQTT broker. It treats MQTT topics as virtual hardware ports, allowing you to map any numeric topic payload to a sensor in the system.

## How it Works
1. **Connection**: The interface connects to a broker (e.g., `localhost` or a remote IP) using a Client ID.
2. **Discovery**: As messages arrive on the broker, the interface automatically tracks all seen topics.
3. **Mapping**: To use MQTT data, you create a sensor where the **Port** is the exact MQTT topic string (e.g., `lab/sensor1/temp`).
4. **Parsing**: The interface automatically attempts to parse payloads as JSON or numbers.

## Configuration Parameters

Use the `configure_interface` tool or `update_interface_config` to adjust MQTT settings.

### Connection Settings (Interface-wide)
- `broker`: The IP address or hostname of the MQTT broker.
- `port`: The MQTT port (default `1883`).
- `client_id`: A unique string to identify this DAQ instance.
- `username`, `password`: For authenticated brokers.

### Runtime Settings
- `poll_interval`: (Seconds) How often the system checks the internal MQTT buffer for new values.

## AI Interaction Protocol

1. **Discovery**: Use `get_live_interface_data(interface_name='MQTT')` to see which topics are currently receiving data and what their latest values are.
2. **Setup**: 
   - First, ensure the interface is connected using `toggle_interface_connection(interface_name='MQTT', action='connect', params={...})`.
   - Then, use `add_sensor(interface_name='MQTT', sensor_name='MySensor', params={'port': 'actual/topic/name'})`.
3. **Verification**: After adding a sensor, use `get_available_sensors` to verify it's receiving live values from the MQTT topic.
4. **Publishing**: Use the `write_mqtt_message` tool (if available) to send commands back to devices.

## Example Payload Parsing
- **Simple Number**: A payload of `23.5` is mapped directly to the sensor value.
- **JSON Object**: If a topic `sensors/all` receives `{"temp": 22, "hum": 45}`, you can still map a sensor to `sensors/all` but you may need an extraction rule in the future. Currently, the interface prefers direct topic-to-value mapping. For complex JSON, recommend using multiple topics or a custom script.
