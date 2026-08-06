# Serial Interface Guide (OtherSerial)

The **Serial** interface (internally referred to as **OtherSerial**) is a generic interface for custom protocols. It is used when a device does not follow the standard Arduino master-slave protocol.

**Important:** Serial protocol sequences are **not** Automations. Use `get_serial_sequence` to inspect them. `get_automation_info` will not show them.

## Protocol Pipeline (CRITICAL)

A functional sequence for a serial sensor MUST follow this exact pattern in `configure_serial_sequence`:

1.  **SendCommand**: (Optional) Use if the hardware requires a request string (e.g., `?`, `GET`, `DAQ:1`).
    - **CRITICAL**: Most devices require a line ending. Set `line_ending` to `LF`, `CR`, or `CRLF` (match what worked in `test_serial_command`).
2.  **Wait**: (MANDATORY) Use at least **300ms** via `wait_time`. Hardware needs time to process the command and send a response.
3.  **ReadResponse**: Captures the raw hardware output into `result_var` (e.g., `raw_data`).
    - **read_type**: Usually `"Read Line"`.
4.  **ParseValue**: Extracts numeric data from `source_var` into `result_var`.
    - Preferred method: `"Between Markers"` with `start_marker` / `end_marker`.
    - Markers are case-sensitive. For `Humidity:45.0;...` use `start_marker="Humidity:"` and `end_marker=";"`.
5.  **publish** (MANDATORY): Maps `source_var` (the ParseValue `result_var`) to `target` (the sensor display name / key).

**Do NOT put unused fields on a step.** Each step object should only contain fields for its `type`. Extra empty fields confuse verification and are stripped by the tool.

## Exact Tool Call Example (copy this structure)

For a response like `Humidity:74.0;Temperature:27.0;;;` after sending `DAQ:1` with CR:

```json
{
  "port": "COM4",
  "sequence_name": "ArduinoSerial",
  "poll_interval": 1.0,
  "steps": [
    {"type": "SendCommand", "command": "DAQ:1", "line_ending": "CR"},
    {"type": "Wait", "wait_time": 300},
    {"type": "ReadResponse", "read_type": "Read Line", "timeout": 1000, "result_var": "raw_data"},
    {
      "type": "ParseValue",
      "source_var": "raw_data",
      "parse_method": "Between Markers",
      "start_marker": "Humidity:",
      "end_marker": ";",
      "result_type": "Number (Float)",
      "result_var": "h_val"
    },
    {"type": "publish", "source_var": "h_val", "target": "ser_Humidity"},
    {
      "type": "ParseValue",
      "source_var": "raw_data",
      "parse_method": "Between Markers",
      "start_marker": "Temperature:",
      "end_marker": ";",
      "result_type": "Number (Float)",
      "result_var": "t_val"
    },
    {"type": "publish", "source_var": "t_val", "target": "ser_Temperature"}
  ]
}
```

Then add sensors:

```json
{"interface_name": "Serial", "sensor_name": "ser_Humidity", "unit": "%", "params": {"port": "COM4", "mapping": "ArduinoSerial:ser_Humidity"}}
{"interface_name": "Serial", "sensor_name": "ser_Temperature", "unit": "C", "params": {"port": "COM4", "mapping": "ArduinoSerial:ser_Temperature"}}
```

If `publish.target` already equals the sensor display name, `add_sensor` can auto-link the mapping.

## Multi-Sensor Sequences (CRITICAL)

If a single response line contains multiple values, use separate `ParseValue` + `publish` pairs for EACH value (see example above).

**WARNING**: Do NOT use `"Entire Response"` if the line contains multiple numbers. It will only extract the first number.

## Field Names (use these exact keys)

| Step | Required fields |
| :--- | :--- |
| `SendCommand` | `command`, `line_ending` |
| `Wait` | `wait_time` (ms, >= 300) |
| `ReadResponse` | `result_var`, optional `read_type`, `timeout` |
| `ParseValue` | `source_var`, `result_var`, `parse_method`, `start_marker`, `end_marker`, `result_type` |
| `publish` | `source_var`, `target` |

Legacy shorthand (`source`/`start`/`end`/`ms`) is accepted and rewritten, but prefer the table above.

## Discovery Workflow (STRICTLY MANDATORY)

1.  **Observe**: Use `test_serial_command(command="", timeout=5.0)` first to see what the device sends on its own.
2.  **Probe**: If no data, try triggers like `?`, `V`, `GET`, `HELP`, `POLL`, or `DAQ:1` with an appropriate `line_ending`.
3.  **Analyze**: Identify markers from the raw tool result.
4.  **Implement**: Call `configure_serial_sequence`.
5.  **Verify**: Call `get_serial_sequence` and confirm the returned `steps` match what you intended. The configure tool also echoes normalized `steps` and `notes`.

## Sensor Mapping

Live data keys look like `SequenceName:publish_target` (e.g. `ArduinoSerial:ser_Humidity`).

After publishing, add the sensor with:
- **Interface**: `Serial` (not `Arduino`)
- **Mapping**: `SequenceName:publish_target`
- **Display name**: usually the same as `publish.target` when using custom names

## Arduino vs Serial on the same COM port

`Arduino` and `Serial` are different drivers. Disconnect the Arduino interface before using the same port as Serial, and vice versa.
