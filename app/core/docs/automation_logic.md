# Automation Logic and Control (Technical Reference)

The automation system follows a **Step-based Sequence** model. Each sequence contains one or more steps. This document provides the technical specifications required for an AI to generate or interpret these sequences.

## 1. The Sequential Model

The system follows a **strict sequential execution model**.

1.  **Step-by-Step**: A sequence processes exactly **one step at a time**.
2.  **Sequential Blocking**: Step N+1 is **never** checked or processed until Step N has fully completed its action.
3.  **The Trigger-Action Cycle**:
    *   The system waits at the current step until its **Trigger** condition is met.
    *   Once triggered, the **Action** is executed.
    *   Only **after** the action finishes does the sequence advance to the next step.
    *   At the next step, the cycle repeats.

**Example of AI Misconception**: If Step 1 waits for `Temp > 50` and Step 2 waits for `Time = 10s`, the 10-second timer for Step 2 does **not** start counting until *after* the temperature has already exceeded 50 and Step 1's action has finished.

---

## 2. JSON Structure

A sequence is represented as a JSON object with the following structure:

```json
{
    "name": "Sequence Name",
    "loop": true,
    "checked": true,
    "run_linked": false,
    "steps": [
        {
            "trigger": { ... trigger_object ... },
            "action": { ... action_object ... },
            "enabled": true
        }
    ]
}
```

---

## 3. Triggers Registry

All triggers must have a `type` (matching the `TriggerType` enum name) and a `name`.

### TIME_DURATION
Waits for a fixed amount of time.
- `minutes`: Integer
- `seconds`: Integer
- **Example**: `{"type": "TIME_DURATION", "name": "Wait 10s", "minutes": 0, "seconds": 10}`

### TIME_SPECIFIC
Triggers at a specific time of day.
- `hour`: Integer (0-23)
- `minute`: Integer (0-59)
- **Example**: `{"type": "TIME_SPECIFIC", "name": "Morning Start", "hour": 8, "minute": 0}`

### SENSOR_VALUE
Compares a single sensor value against a threshold.
- `sensor_name`: String (ID of the sensor)
- `operator`: `>`, `<`, `>=`, `<=`, `==`
- `threshold`: Float
- `hysteresis`: Float (Buffer zone to prevent rapid-firing)
- **Example**: `{"type": "SENSOR_VALUE", "name": "Overheat", "sensor_name": "Temp", "operator": ">", "threshold": 75.0, "hysteresis": 2.0}`

### EVENT
Fires on a system-broadcasted string event.
- `event_type`: String
- **Standard Events**: `motion_detected`, `START_ACQUISITION`, `STOP_ACQUISITION`.
- **Example**: `{"type": "EVENT", "name": "On Motion", "event_type": "motion_detected"}`

### COMPOUND
Combines multiple triggers.
- `logic`: `"AND"` or `"OR"`
- `triggers`: List of trigger objects.
- **Example**: `{"type": "COMPOUND", "name": "Safe Condition", "logic": "AND", "triggers": [...]}`

### OPTICAL_EVENT
Specific to vision sensors (Cameras).
- `sensor_name`: Camera ID (e.g., `"Camera1"`)
- `event_type`: See table below.
- `threshold`: Float (optional)
- `threshold_percent`: Float (optional)

| event_type | Description |
| :--- | :--- |
| `light_event` | General light detection |
| `brightness_above` / `brightness_below` | Mean brightness threshold |
| `fill_level_above` / `fill_level_below` | Percentage of region filled |
| `particle_count_above` | Number of detected objects |
| `color_detected` | Specific target color match |
| `position_changed` | Object movement |

### AUDIO_EVENT
Specific to microphones.
- `sensor_name`: Microphone ID (e.g., `"Microphone"`)
- `event_type`: `rms_above`, `rms_below`, `peak_above`, `peak_below`, `frequency_above`, `frequency_below`, `db_above`, `db_below`, `frequency_stable`, `band_energy_above`.

---

## 4. Actions Registry

### ARDUINO_COMMAND
- `command`: String (e.g., `"RELAY_ON"`)

### LABJACK_COMMAND
- `channel`: String (e.g., `"DAC0"`)
- `value`: Integer or Float

### SERIAL_COMMAND
- `port`: String (e.g., `"COM3"`)
- `command`: String
- `baudrate`: Integer (default 9600)

### SYSTEM_ACTION
Commands internal application logic.
- `specific_action_type`: See table below.
- `parameters`: Dictionary of parameters.

| specific_action_type | Parameters | Description |
| :--- | :--- | :--- |
| `start_acquisition` | `{}` | Starts data logging run |
| `stop_acquisition` | `{}` | Stops data logging run |
| `take_snapshot` | `{"camera_index": 0}` | Captures an image |
| `start_recording` | `{}` | Starts video recording |
| `stop_recording` | `{}` | Stops video recording |
| `display_message` | `{"title": "...", "message": "..."}` | Shows UI popup |
| `play_sound` | `{"sound": "beep"}` or `{"sound": "custom", "file_path": "..."}` | Plays audio |

### SET_VARIABLE
Updates an internal variable.
- `variable_name`: String
- `expression`: Mathematical string (e.g., `"({Value} * 2) + 1"`)

### JUMP_TO_STEP
Flow control within a sequence.
- `target_step_index`: Integer (0-based)

### CONDITION
Conditional branching.
- `condition_expression`: Boolean logic string (e.g., `"{Temp} > 50"`)
- `if_true_step`: Integer (0-based)
- `if_false_step`: Integer (0-based, optional)

### MQTT_PUBLISH
- `topic`: String
- `payload`: String (supports variable substitution)

### INFO_MARKER
- `marker_text`: String (displays on graphs)

---

## 5. Variables and Logic Parsing

### Variable Substitution
You can use variables/sensor IDs in strings using curly braces:
- `SET_PIN_{my_var}`
- `Temp is {Temperature} C`

### Expression Evaluation
`CONDITION` and `SET_VARIABLE` support Python-like mathematical expressions.
- Safe operators: `+`, `-`, `*`, `/`, `%`, `(`, `)`, ` `, `>`, `<`, `==`, `!=`, `>=`, `<=`, `and`, `or`, `not`.
- **Note**: The system does **not** have a natural language parser. You must use the structured JSON types.

---

## 6. AI Control Tools

The AI Assistant has access to specific tools to manage these sequences:
- `save_automation_sequence`: Create or update a sequence definition.
- **Modification = Overwrite**: If asked to 'change', 'update', or 'modify' something (like an automation sequence), fetch the current state first, then call `save_automation_sequence` with the SAME NAME to overwrite it with the new version.
- `control_automation`: Change the state of a sequence (`start`, `stop`, `enable`, `disable`).
- `get_automation_info`: Query the live status of all sequences.

---

## 7. Lifecycle and Execution (CRITICAL - READ CAREFULLY)

The most common error is assuming an enabled automation "waits" for its time trigger. **It does not.**

### The "Dead" State vs. The "Armed" State
*   **STOPPED (Dead/Idle)**: This is the default state. Even if the sequence is "Enabled" (Checked in UI), the system **IS NOT WATCHING THE CLOCK**. A sequence set to "Start at 17:00" will **NEVER** fire if it stays in the STOPPED state.
*   **RUNNING (Armed/Active)**: This state is entered only after calling `control_automation(action='start')`. In this state, the system is actively monitoring triggers.

### THE FATAL AI ERROR: "It will start at 17:00 automatically"
**THIS IS A LIE.** If you tell the user "It will start at 17:00 automatically" without having called the `start` tool, you have failed. You MUST call `start` to "Arm" the sequence. 

**Analogy**: 
- `Enable`: Putting the alarm clock on the nightstand.
- `Start`: Actually turning the alarm switch to "ON". 
- If you don't turn the switch to "ON" (Start), the alarm will never ring.

### How to correctly "Run/Enable" an automation:
If a user says "Enable it" or "Run it now":
1.  Call `control_automation(action='enable')` to check the box.
2.  **IMMEDIATELY** call `control_automation(action='start')` to Arm it.
3.  Confirm to the user: "The automation is now **ARMED** and watching for the 17:00 trigger."

---

## 8. Common AI Hallucinations to Avoid
1.  **"Manual start is blocked for time-triggers"**: FALSE. Manual start is **REQUIRED** for time-triggers to function.
2.  **"It's monitoring because it's enabled"**: FALSE. Monitoring only happens in the `RUNNING` state.
3.  **"Wait for 17:00"**: NEVER tell the user to wait if the status is `STOPPED`. You must `start` it first.

---

## 9. AI Interaction Protocol (IMPORTANT)

When interacting with the user:
1.  **DO NOT ask the user to call tools.** If a tool is needed (e.g., `control_automation`), you must call it yourself. Never output the raw tool syntax to the user.
2.  **Action-First Principle**: If the user says "Enable it" or "Run it", call the tools first, then tell the user it is done. 
3.  **No Excuses**: Do not claim "system limitations" or "manual start is blocked." Use the `control_automation` tool as documented. If a start fails, check `get_automation_info` and retry once.

---

## 10. Complex Patterns

### Looping with a Counter (e.g., "Do X for 30 times")
To repeat an action a specific number of times, use a variable:
1.  **Step 1**: `SET_VARIABLE` -> `count = 0` (Trigger: Instant/Duration 0)
2.  **Step 2**: The Action you want to repeat (e.g., `take_snapshot`) (Trigger: your condition)
3.  **Step 3**: `SET_VARIABLE` -> `count = {count} + 1` (Trigger: Duration 0)
4.  **Step 4**: `CONDITION` -> `if {count} < 30 jump to Step 2` (Trigger: Duration 0 or your interval)

### Daily Schedules
For daily tasks, set `loop: true` at the sequence level.
1.  **Step 1**: `TIME_SPECIFIC` -> `13:00`
2.  **Step 2...N**: Your automation logic.
3.  The sequence will complete and, because `loop: true`, will start waiting for `13:00` again the next day.

---

## 11. Global Variables
Sequences share a global `variables` dictionary in the `AutomationManager`. A value set in Sequence A with `SET_VARIABLE` can be read by Sequence B in a `CONDITION`.
