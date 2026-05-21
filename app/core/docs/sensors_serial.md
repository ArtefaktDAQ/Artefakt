# Serial Interface Guide (OtherSerial)

The **Serial** interface (internally referred to as **OtherSerial**) is a generic interface for custom protocols. It is used when a device does not follow the standard Arduino master-slave protocol.

## Protocol Pipeline (CRITICAL)

A functional sequence for a serial sensor MUST follow this exact pattern in `configure_serial_sequence`:

1.  **SendCommand**: (Optional) Use if the hardware requires a request string (e.g., `?`, `GET`, `V`).
    - **CRITICAL**: Most devices (like Arduino) require a line ending to process a command. Ensure you select `LF (\n)` or `CRLF (\r\n)` in the `line_ending` parameter.
    - If you are testing via `test_serial_command`, use its `line_ending` parameter.
2.  **Wait**: (MANDATORY) Use at least **300ms**. Hardware needs time to process the command and send a response. Without this, the read step may fail.
3.  **ReadResponse**: Captures the raw hardware output into a variable (e.g., `raw_data`).
    - **Read Type**: Usually "Read Line" (for `\n` terminated text).
4.  **ParseValue**: Extracts the numeric data from the captured variable.
    - **Parse Methods**:
        - `Between Markers`: (Safest) Extracts text between two strings. 
        - **WARNING**: Markers are case-sensitive and must be unique. If the device sends `Humidity:45.0`, use `Start: "Humidity:"` and `End: ";"` (or empty if at end). Do NOT use `H:` if it overlaps with other text.
        - `Regex Pattern`: (Advanced) Requires a capture group `()`. Example: `Humidity:([\d.]+)`.
        - `After Marker`: Extracts everything after the marker.
    - **Result Type**: Set to `Number (Float)` or `Number (Integer)` for sensors.
5.  **publish** (MANDATORY): Maps the parsed variable to a target key (e.g., `humidity`).

## Multi-Sensor Sequences (CRITICAL)

If a single response line contains multiple values (e.g., `Humidity:45.2;Temperature:22.1`), you **must** use separate `ParseValue` and `publish` steps for EACH value:

1. **ParseValue** (source: `raw_data`, start: `Humidity:`, end: `;`, result_var: `h_val`) -> **publish** (source_var: `h_val`, target: `Humidity`)
2. **ParseValue** (source: `raw_data`, start: `Temperature:`, end: ``, result_var: `t_val`) -> **publish** (source_var: `t_val`, target: `Temperature`)

**WARNING**: Do NOT use "Entire Response" if the line contains multiple numbers. It will only extract the first number it finds.

## Discovery Workflow (STRICTLY MANDATORY)

1.  **Observe**: Use `test_serial_command(command="", timeout=5.0)` first to see what the device sends on its own.
    - If no data is received, the device may require a specific baud rate or a trigger command.
2.  **Probe**: If no data, try common trigger commands like `?`, `V`, `GET`, `HELP`, or `POLL`.
    - **Note**: `POLL` is the standard trigger for Artefakt Arduino devices.
    - **CRITICAL**: Use the `line_ending` parameter in `test_serial_command` (e.g., `line_ending="LF (\n)"`) as many devices won't respond without it.
3.  **Analyze**: Look at the raw output in the tool result to identify markers. `test_serial_command` now captures multiple lines of response.
4.  **Implement**: Only then call `configure_serial_sequence`.

## Sensor Mapping

After publishing a variable (e.g., `temp_val`) in a sequence named `MyArduino`, add the sensor using:
- **Interface**: `Serial`
- **Mapping**: `MyArduino:temp_val`
