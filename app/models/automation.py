"""
Automation Models

Defines the core data structures for automation triggers, actions, steps, and sequences.
"""
import time
import datetime
import json
import os
import traceback
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from enum import Enum

# --- Triggers ---
class TriggerType(Enum):
    TIME_DURATION = 1
    TIME_SPECIFIC = 2
    SENSOR_VALUE = 3
    EVENT = 4

class BaseTrigger(QObject):
    triggered = pyqtSignal(object) # Signal when trigger condition is met

    def __init__(self, name, trigger_type):
        super().__init__()
        self.name = name
        self.trigger_type = trigger_type
        self.description = "Base Trigger" # Provide a default description

    def check(self, context): # context might contain sensor values, events, etc.
        """Check if the trigger condition is met."""
        raise NotImplementedError
    
    def to_dict(self):
        """Serialize trigger to a dictionary"""
        return {
            'type': self.trigger_type.name,
            'name': self.name
            # Subclasses will add their specific attributes
        }

    @staticmethod
    def from_dict(data):
        """Deserialize trigger from a dictionary"""
        trigger_type_name = data.get('type')
        name = data.get('name')
        
        if trigger_type_name == TriggerType.TIME_DURATION.name:
            return TimeDurationTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.TIME_SPECIFIC.name:
            return TimeSpecificTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.SENSOR_VALUE.name:
            return SensorValueTrigger.from_dict(data)
        elif trigger_type_name == TriggerType.EVENT.name:
            return EventTrigger.from_dict(data)
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type_name}")
            

class TimeDurationTrigger(BaseTrigger):
    def __init__(self, name, minutes, seconds):
        super().__init__(name, TriggerType.TIME_DURATION)
        self.minutes = int(minutes)
        self.seconds = int(seconds)
        self.duration = self.minutes * 60 + self.seconds
        self.start_time = None
        self.description = f"Wait for {self.minutes}m {self.seconds}s"
        
    def start(self):
        """Record the start time when the step begins."""
        self.start_time = time.monotonic()
        print(f"TimeDurationTrigger started: {self.description}, duration={self.duration}s, start_time={self.start_time}")
        
    def check(self, context=None): # Context not strictly needed here
        if self.start_time is None:
            # Start time hasn't been set - this is abnormal, so set it now
            print(f"WARNING: TimeDurationTrigger was checked without start_time being set. Setting it now.")
            self.start_time = time.monotonic()
            return False # Don't trigger immediately
            
        elapsed = time.monotonic() - self.start_time
        is_triggered = elapsed >= self.duration
        
        # Add debug output every 5 seconds
        if int(elapsed) % 5 == 0:
            remaining = max(0, self.duration - elapsed)
            print(f"TimeDurationTrigger check: elapsed={elapsed:.1f}s, remaining={remaining:.1f}s, triggered={is_triggered}")
            
        return is_triggered
        
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'minutes': self.minutes,
            'seconds': self.seconds
        })
        return data

    @staticmethod
    def from_dict(data):
        return TimeDurationTrigger(data['name'], data['minutes'], data['seconds'])

class TimeSpecificTrigger(BaseTrigger):
    def __init__(self, name, hour, minute):
        super().__init__(name, TriggerType.TIME_SPECIFIC)
        self.hour = int(hour)
        self.minute = int(minute)
        self.triggered_today = False
        self.description = f"At time {self.hour:02d}:{self.minute:02d}"
        
    def check(self, context=None): # Context not needed
        now = datetime.datetime.now().time()
        target_time = datetime.time(self.hour, self.minute)
        
        # Check if current time is at or past the target time
        if now >= target_time:
            if not self.triggered_today:
                self.triggered_today = True
                return True
        else:
            # Reset flag if time has passed midnight
            self.triggered_today = False 
            
        return False
        
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'hour': self.hour,
            'minute': self.minute
        })
        return data

    @staticmethod
    def from_dict(data):
        return TimeSpecificTrigger(data['name'], data['hour'], data['minute'])

class SensorValueTrigger(BaseTrigger):
    def __init__(self, name, sensor_name, operator, threshold):
        super().__init__(name, TriggerType.SENSOR_VALUE)
        self.sensor_name = str(sensor_name) # Ensure it's a string
        self.operator = str(operator)
        self.threshold = float(threshold)
        self.description = f"When {self.sensor_name} {self.operator} {self.threshold}"
        
    def check(self, context):
        if context is None or 'sensors' not in context:
            return False
            
        sensor_value = context['sensors'].get(self.sensor_name) 
        if sensor_value is None:
            return False # Sensor not found or value unavailable
            
        try:
            current_value = float(sensor_value)
        except (ValueError, TypeError):
            return False # Cannot compare if value is not a number
            
        # Evaluate condition
        if self.operator == '>':
            return current_value > self.threshold
        elif self.operator == '<':
            return current_value < self.threshold
        elif self.operator == '==':
            # Use approximate comparison for floats
            return abs(current_value - self.threshold) < 1e-6
        elif self.operator == '>=':
            return current_value >= self.threshold
        elif self.operator == '<=':
            return current_value <= self.threshold
        else:
            return False # Unknown operator
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'sensor_name': self.sensor_name,
            'operator': self.operator,
            'threshold': self.threshold
        })
        return data

    @staticmethod
    def from_dict(data):
        return SensorValueTrigger(data['name'], data['sensor_name'], data['operator'], data['threshold'])

class EventTrigger(BaseTrigger):
    def __init__(self, name, event_type):
        super().__init__(name, TriggerType.EVENT)
        self.event_type = str(event_type)
        self.description = f"On event: {self.event_type}"
        self.triggered_event = False # Flag to trigger only once per event occurrence
        
    def check(self, context):
        if context is None or 'events' not in context:
            return False
            
        # Check if the specific event occurred recently
        if self.event_type in context['events']:
            if not self.triggered_event:
                 self.triggered_event = True # Set flag
                 return True
        else:
             # Reset the flag if the event is no longer in the current context
             self.triggered_event = False
             
        return False
        
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'event_type': self.event_type
        })
        return data

    @staticmethod
    def from_dict(data):
        return EventTrigger(data['name'], data['event_type'])

# --- Actions ---
class ActionType(Enum):
    ARDUINO_COMMAND = 1
    LABJACK_COMMAND = 2
    SERIAL_COMMAND = 3
    SYSTEM_ACTION = 4
    SET_VARIABLE = 5 # Added for variable support

class BaseAction(QObject):
    action_completed = pyqtSignal(object) # Signal when action is done
    action_failed = pyqtSignal(object, str) # Signal on failure (self, reason)

    def __init__(self, name, action_type):
        super().__init__()
        self.name = name
        self.action_type = action_type
        self.description = "Base Action"

    def execute(self, context): # context provides access to interfaces (arduino, labjack, etc.)
        """Execute the action."""
        raise NotImplementedError
        
    def to_dict(self):
        """Serialize action to a dictionary"""
        return {
            'type': self.action_type.name,
            'name': self.name
            # Subclasses add their specific attributes
        }

    @staticmethod
    def from_dict(data):
        """Deserialize action from a dictionary"""
        action_type_name = data.get('type')
        
        if action_type_name == ActionType.ARDUINO_COMMAND.name:
            return ArduinoCommandAction.from_dict(data)
        elif action_type_name == ActionType.LABJACK_COMMAND.name:
            return LabJackCommandAction.from_dict(data)
        elif action_type_name == ActionType.SERIAL_COMMAND.name:
            return SerialCommandAction.from_dict(data)
        elif action_type_name == ActionType.SYSTEM_ACTION.name:
            return SystemAction.from_dict(data)
        elif action_type_name == ActionType.SET_VARIABLE.name:
            return SetVariableAction.from_dict(data)
        else:
            raise ValueError(f"Unknown action type: {action_type_name}")

class ArduinoCommandAction(BaseAction):
    def __init__(self, name, command):
        super().__init__(name, ActionType.ARDUINO_COMMAND)
        self.command = str(command)
        self.description = f"Send Arduino: '{self.command}'"
        
    def execute(self, context):
        arduino_interface = context.get('interfaces', {}).get('arduino')
        if arduino_interface and arduino_interface.is_connected():
            try:
                # Substitute variables if present
                resolved_command = context.get('resolve_variables', lambda x: x)(self.command)
                # Send command (assuming a method like send_command exists)
                arduino_interface.send_command(resolved_command) 
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send Arduino command: {e}")
        else:
            self.action_failed.emit(self, "Arduino not connected or available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({'command': self.command})
        return data

    @staticmethod
    def from_dict(data):
        return ArduinoCommandAction(data['name'], data['command'])

class LabJackCommandAction(BaseAction):
    def __init__(self, name, channel, value):
        super().__init__(name, ActionType.LABJACK_COMMAND)
        self.channel = str(channel)
        self.value = value # Can be int (digital) or float (analog)
        self.description = f"Set LabJack {self.channel} to {self.value}"
        
    def execute(self, context):
        labjack_interface = context.get('interfaces', {}).get('labjack')
        if labjack_interface and labjack_interface.is_connected():
            try:
                # Substitute variables if present in channel or value
                resolved_channel = context.get('resolve_variables', lambda x: x)(self.channel)
                
                # Attempt to resolve value if it's a string (might be a variable)
                if isinstance(self.value, str):
                    resolved_value_str = context.get('resolve_variables', lambda x: x)(self.value)
                    # Try converting resolved value to float/int
                    try:
                        resolved_value = float(resolved_value_str)
                        # Convert to int if it looks like one
                        if resolved_value == int(resolved_value):
                             resolved_value = int(resolved_value)
                    except ValueError:
                         raise ValueError(f"Could not convert resolved variable '{resolved_value_str}' to a number for LabJack value")
                else:
                     resolved_value = self.value # Use original numeric value
                
                # Send command (assuming a method like write_channel exists)
                labjack_interface.write_channel(resolved_channel, resolved_value)
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send LabJack command: {e}")
        else:
            self.action_failed.emit(self, "LabJack not connected or available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({'channel': self.channel, 'value': self.value})
        return data

    @staticmethod
    def from_dict(data):
        # Value could be saved as float or int, handle both
        value = data['value']
        return LabJackCommandAction(data['name'], data['channel'], value)

class SerialCommandAction(BaseAction):
    def __init__(self, name, port, command, baudrate=9600, timeout=1):
        super().__init__(name, ActionType.SERIAL_COMMAND)
        self.port = str(port)
        self.command = str(command)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        # Ensure command ends with newline? Often required for serial.
        if not self.command.endswith('\n'):
             self.command += '\n'
        self.description = f"Send Serial '{self.command.strip()}' to {self.port}"
        
    def execute(self, context):
        # This requires a generic serial interface manager in the context
        serial_manager = context.get('interfaces', {}).get('serial_manager') 
        if serial_manager:
            try:
                # Substitute variables if present
                resolved_port = context.get('resolve_variables', lambda x: x)(self.port)
                resolved_command = context.get('resolve_variables', lambda x: x)(self.command)
                
                # Send command using the manager
                serial_manager.send_command(resolved_port, resolved_command, self.baudrate, self.timeout)
                self.action_completed.emit(self)
            except Exception as e:
                self.action_failed.emit(self, f"Failed to send Serial command to {self.port}: {e}")
        else:
            self.action_failed.emit(self, "Serial manager not available")
            
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'port': self.port,
            'command': self.command,
            'baudrate': self.baudrate,
            'timeout': self.timeout
        })
        return data

    @staticmethod
    def from_dict(data):
        return SerialCommandAction(
            data['name'], data['port'], data['command'],
            data.get('baudrate', 9600), data.get('timeout', 1)
        )

class SystemAction(BaseAction):
    def __init__(self, name, action_type, parameters=None):
        # Call BaseAction init with the correct ENUM type
        super().__init__(name, ActionType.SYSTEM_ACTION)
        # Store the specific system action type (e.g., "start_recording") separately
        self.specific_action_type = str(action_type) 
        self.parameters = parameters if parameters else {}
        self.description = f"System: {self.specific_action_type}"
        if self.specific_action_type == "display_message":
            self.description += f" ('{self.parameters.get('message', '')[:20]}...')"
        elif self.specific_action_type == "play_sound":
             self.description += f" ({self.parameters.get('sound', 'beep')})"
             
    def execute(self, context):
        main_window = context.get('main_window')
        if not main_window:
            self.action_failed.emit(self, "Main window context not available")
            return

        try:
             # Substitute variables in parameters
             resolved_params = {} 
             resolve_func = context.get('resolve_variables', lambda x: x)
             for key, value in self.parameters.items():
                 if isinstance(value, str):
                     resolved_params[key] = resolve_func(value)
                 else:
                     resolved_params[key] = value # Keep non-strings as is

             # Find the appropriate controller/method on main_window or its controllers
             # This is a simplified example; a more robust system might use signals/slots
             # or a dedicated system action handler.
             if self.specific_action_type == "start_recording" and hasattr(main_window, 'data_logger'):
                 main_window.data_logger.start_recording()
             elif self.specific_action_type == "stop_recording" and hasattr(main_window, 'data_logger'):
                 main_window.data_logger.stop_recording()
             elif self.specific_action_type == "take_snapshot" and hasattr(main_window, 'camera_controller'):
                 main_window.camera_controller.take_snapshot() # Assuming method exists
             elif self.specific_action_type == "display_message":
                 from PyQt6.QtWidgets import QMessageBox
                 QMessageBox.information(main_window, 
                                         resolved_params.get("title", "Automation Message"), 
                                         resolved_params.get("message", ""))
             elif self.specific_action_type == "play_sound":
                  # Requires a sound playing utility
                  sound_player = context.get('sound_player')
                  if sound_player:
                       sound = resolved_params.get("sound", "beep")
                       if sound == "custom":
                            file_path = resolved_params.get("file_path")
                            if file_path and os.path.exists(file_path):
                                 sound_player.play_wav(file_path)
                            else:
                                 raise ValueError(f"Custom sound file not found or specified: {file_path}")
                       elif sound == "beep":
                            sound_player.play_beep()
                       # Add other standard sounds if needed
                  else:
                       print("Warning: Sound player not available in context.")
                       # Optionally, play a system beep as fallback
                       try:
                           import winsound # Windows only
                           winsound.MessageBeep()
                       except ImportError:
                           print("\a", end='') # Generic terminal bell
             else:
                 raise NotImplementedError(f"System action '{self.specific_action_type}' not implemented")
                 
             self.action_completed.emit(self)
             
        except Exception as e:
             self.action_failed.emit(self, f"Failed to execute system action '{self.specific_action_type}': {e}")
             
    def to_dict(self):
        # Get base dictionary (which includes the correct 'type': ActionType.SYSTEM_ACTION.name)
        data = super().to_dict() 
        # Add the specific action type and parameters
        data.update({
            'specific_action_type': self.specific_action_type,
            'parameters': self.parameters
        })
        return data

    @staticmethod
    def from_dict(data):
        # Extract the specific action type and parameters
        specific_action_type = data.get('specific_action_type') # Use the new key
        if not specific_action_type:
             # Backwards compatibility: Try the old 'action_type' key if specific isn't found
             specific_action_type = data.get('action_type') 
        
        if not specific_action_type:
             raise ValueError("Missing 'specific_action_type' in SystemAction data")
             
        # Create the object using the specific type
        return SystemAction(data['name'], specific_action_type, data.get('parameters'))

# --- Variable Action ---
class SetVariableAction(BaseAction):
    def __init__(self, name, variable_name, expression):
        super().__init__(name, ActionType.SET_VARIABLE)
        self.variable_name = str(variable_name).strip()
        self.expression = str(expression).strip()
        self.description = f"Set variable '{self.variable_name}' = '{self.expression}'"
        
    def execute(self, context):
        variable_manager = context.get('variable_manager')
        resolve_func = context.get('resolve_variables', lambda x: x)
        
        if not variable_manager:
             self.action_failed.emit(self, "Variable manager not available in context")
             return
             
        if not self.variable_name:
             self.action_failed.emit(self, "Variable name cannot be empty")
             return
             
        try:
             # 1. Resolve any variables within the expression first
             resolved_expression = resolve_func(self.expression)
             
             # 2. Evaluate the resolved expression (safely!)
             # For now, let's treat it as a literal string or number assignment
             # A safe evaluation (like ast.literal_eval or a custom parser) is needed 
             # for arithmetic or sensor-based expressions. 
             # TODO: Implement safe evaluation for expressions
             value_to_set = resolved_expression # Basic assignment for now
             
             # Try converting to number if possible
             try:
                 value_to_set = float(resolved_expression)
                 if value_to_set == int(value_to_set):
                      value_to_set = int(value_to_set)
             except ValueError:
                 pass # Keep as string if not a number

             # 3. Set the variable in the manager
             variable_manager.set_variable(self.variable_name, value_to_set)
             self.action_completed.emit(self)
             
        except Exception as e:
             self.action_failed.emit(self, f"Failed to set variable '{self.variable_name}': {e}")
             
    def to_dict(self):
        data = super().to_dict()
        data.update({
            'variable_name': self.variable_name,
            'expression': self.expression
        })
        return data

    @staticmethod
    def from_dict(data):
        return SetVariableAction(data['name'], data['variable_name'], data['expression'])

# --- Step and Sequence ---
class AutomationStep(QObject):
    step_started = pyqtSignal(object)
    step_completed = pyqtSignal(object)
    step_failed = pyqtSignal(object, str)

    def __init__(self, trigger, action, enabled=True):
        super().__init__()
        if not isinstance(trigger, BaseTrigger):
             raise TypeError("trigger must be an instance of BaseTrigger")
        if not isinstance(action, BaseAction):
             raise TypeError("action must be an instance of BaseAction")
             
        self.trigger = trigger
        self.action = action
        self.enabled = bool(enabled)
        self.is_running = False # Tracks if action is currently executing
        
        # Connect signals
        self.action.action_completed.connect(self._on_action_completed)
        self.action.action_failed.connect(self._on_action_failed)
        
    def check_trigger(self, context):
        """Check if the step's trigger condition is met."""
        if not self.enabled or self.is_running:
            return False
        return self.trigger.check(context)
        
    def execute_action(self, context):
        """Execute the step's action."""
        if not self.enabled:
            self.step_failed.emit(self, "Step is disabled")
            return
            
        if self.is_running:
             print(f"Warning: Action '{self.action.name}' already running for step.")
             return
             
        self.is_running = True
        self.step_started.emit(self)
        
        # If it's a time duration trigger, start its timer now
        if isinstance(self.trigger, TimeDurationTrigger):
            self.trigger.start()
            
        # Execute the action
        self.action.execute(context)
        
    def _on_action_completed(self, action_obj):
        if action_obj == self.action:
            self.is_running = False
            self.step_completed.emit(self)
            
    def _on_action_failed(self, action_obj, reason):
        if action_obj == self.action:
            self.is_running = False
            self.step_failed.emit(self, reason)

    def to_dict(self):
        return {
            'trigger': self.trigger.to_dict(),
            'action': self.action.to_dict(),
            'enabled': self.enabled
        }
        
    @staticmethod
    def from_dict(data):
        trigger = BaseTrigger.from_dict(data['trigger'])
        action = BaseAction.from_dict(data['action'])
        return AutomationStep(trigger, action, data.get('enabled', True))

class AutomationSequence(QObject):
    sequence_started = pyqtSignal(object)
    sequence_step_changed = pyqtSignal(object, int) # sequence, step_index
    sequence_completed = pyqtSignal(object)
    sequence_stopped = pyqtSignal(object)
    sequence_error = pyqtSignal(object, str) # sequence, error_message

    def __init__(self, name, steps=None, loop=False, checked=False):
        super().__init__()
        self.name = name
        self.steps = steps if steps else []
        self.loop = loop
        self.checked = checked
        self.current_step_index = -1
        self.is_running = False
        self._timer = None
        self._context = {} # Execution context passed to triggers/actions
        self._current_step_failed = False
        
        # Connect signals from steps
        for step in self.steps:
            step.step_completed.connect(self._handle_step_completed)
            step.step_failed.connect(self._handle_step_failed)
            
    def set_context(self, context):
        self._context = context
        
    def start(self, check_interval_ms=100):
        """Start executing the sequence."""
        if self.is_running:
            print(f"Sequence '{self.name}' is already running.")
            return
            
        if not self.steps:
             self.sequence_error.emit(self, "Cannot start sequence with no steps.")
             return
             
        self.is_running = True
        self.current_step_index = 0
        self._current_step_failed = False
        
        # Reset specific trigger types
        for step in self.steps:
             if isinstance(step.trigger, TimeSpecificTrigger):
                 step.trigger.triggered_today = False
             elif isinstance(step.trigger, EventTrigger):
                 step.trigger.triggered_event = False
             # Duration trigger's start_time is set when its step executes

        self.sequence_started.emit(self)
        self.sequence_step_changed.emit(self, self.current_step_index)
        
        # Start the main execution loop timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._run_loop)
        self._timer.start(check_interval_ms)
        
        # Immediately try to execute the first step if its trigger allows
        self._run_loop()
        
    def stop(self):
        """Stop executing the sequence."""
        if not self.is_running:
            return
            
        if self._timer:
            self._timer.stop()
            self._timer = None
            
        # Stop any currently running step action if possible (graceful stop TBD)
        if 0 <= self.current_step_index < len(self.steps):
            current_step = self.steps[self.current_step_index]
            if current_step.is_running:
                 # TODO: Need a way to signal actions to stop gracefully if needed
                 current_step.is_running = False # Force stop for now
                 print(f"Forcibly stopped action '{current_step.action.name}'")
        
        self.is_running = False
        self.current_step_index = -1
        self.sequence_stopped.emit(self)
        
    def _run_loop(self):
        """The main execution loop checked periodically by the timer."""
        if not self.is_running or self._current_step_failed:
            # Stop timer if sequence stopped or failed
            if self._timer:
                 self._timer.stop()
            return
            
        # Ensure index is valid
        if not (0 <= self.current_step_index < len(self.steps)):
             # This shouldn't happen if logic is correct, but handle defensively
             print(f"Error: Invalid step index {self.current_step_index} in sequence '{self.name}'")
             self.stop()
             self.sequence_error.emit(self, "Internal error: Invalid step index")
             return
             
        current_step = self.steps[self.current_step_index]
        
        # Only proceed if the step is not already running its action
        if not current_step.is_running:
             # Check the trigger for the current step
             if current_step.check_trigger(self._context):
                 # Trigger condition met, execute the action
                 try:
                     current_step.execute_action(self._context)
                 except Exception as e:
                     error_msg = f"Exception during action execution: {e}"
                     print(f"Error in sequence '{self.name}', step {self.current_step_index + 1}: {error_msg}")
                     traceback.print_exc() # Log the full traceback
                     # Manually trigger the failure handling
                     self._handle_step_failed(current_step, error_msg)
                     return # Stop further processing in this loop iteration

                 # Action completion/failure is handled by signals _handle_step_completed/_handle_step_failed
             else:
                  # If it's a duration trigger, start its timer when the step becomes active
                  # (even if check returns false initially)
                  if isinstance(current_step.trigger, TimeDurationTrigger) and current_step.trigger.start_time is None:
                       current_step.trigger.start()

    def _handle_step_completed(self, completed_step):
        if not self.is_running or completed_step != self.steps[self.current_step_index]:
            return # Ignore if sequence stopped or it's not the current step
            
        # Move to the next step
        self.current_step_index += 1
        
        if self.current_step_index >= len(self.steps):
            # End of sequence
            if self.loop:
                # Loop back to the beginning
                self.current_step_index = 0
                print(f"Sequence '{self.name}' looping back to step 1.")
                self.sequence_step_changed.emit(self, self.current_step_index)
                # Reset specific trigger types for the new loop
                for step in self.steps:
                    if isinstance(step.trigger, TimeSpecificTrigger):
                         step.trigger.triggered_today = False
                    elif isinstance(step.trigger, EventTrigger):
                         step.trigger.triggered_event = False
                # Immediately check the first step trigger again
                self._run_loop() 
            else:
                # Sequence finished
                print(f"Sequence '{self.name}' completed.")
                self.stop()
                self.sequence_completed.emit(self)
        else:
            # Proceed to the next step
            self.sequence_step_changed.emit(self, self.current_step_index)
            # Immediately check the next step's trigger
            self._run_loop()
            
    def _handle_step_failed(self, failed_step, reason):
         if not self.is_running or failed_step != self.steps[self.current_step_index]:
            return
            
         print(f"Error in sequence '{self.name}', step {self.current_step_index + 1} ('{failed_step.trigger.name}' -> '{failed_step.action.name}'): {reason}")
         self._current_step_failed = True # Flag to stop the run loop
         self.stop()
         self.sequence_error.emit(self, f"Step {self.current_step_index + 1} failed: {reason}")

    def to_dict(self):
        return {
            'name': self.name,
            'loop': self.loop,
            'checked': self.checked,
            'steps': [step.to_dict() for step in self.steps]
        }
        
    @staticmethod
    def from_dict(data):
        name = data.get('name', 'Unnamed Sequence')
        loop = data.get('loop', False)
        steps_data = data.get('steps', [])
        steps = [AutomationStep.from_dict(step_data) for step_data in steps_data]
        checked_state = data.get('checked', False)
        return AutomationSequence(name, steps, loop, checked_state)

# --- Automation Manager (Handles loading/saving/running sequences) ---
class AutomationManager(QObject):
    sequences_changed = pyqtSignal() # Emitted when sequences list changes
    sequence_started = pyqtSignal(object) # Re-emitted from sequence
    sequence_stopped = pyqtSignal(object) # Re-emitted from sequence
    sequence_completed = pyqtSignal(object) # Re-emitted from sequence
    sequence_step_changed = pyqtSignal(object, int) # Re-emitted from sequence
    sequence_error = pyqtSignal(object, str) # Re-emitted from sequence
    status_changed = pyqtSignal() # Generic signal for UI updates

    def __init__(self, sequences_file="automation_sequences.json", app_context=None):
        super().__init__()
        self.sequences = []
        self.active_sequences = set() # Sequences currently running
        self.sequences_file = sequences_file
        self.app_context = app_context if app_context else {}
        self.variables = {} # Dictionary to store shared variables
        self.load_sequences() # Load sequences on initialization

    def set_sequences_file(self, new_path):
        """Sets the path for the sequences JSON file."""
        if self.sequences_file != new_path:
            print(f"AutomationManager: Setting sequences file to {new_path}")
            self.sequences_file = new_path
            # Note: load_sequences is called separately after setting the path

    def get_available_sensors(self):
        """Get a list of sensor names available in the context."""
        # First check if we have a sensor_controller
        sensor_controller = self.app_context.get('sensor_controller')
        if sensor_controller:
            if hasattr(sensor_controller, 'get_sensor_names'):
                return sensor_controller.get_sensor_names()
            elif hasattr(sensor_controller, 'get_sensor_list'):
                return sensor_controller.get_sensor_list()
            elif hasattr(sensor_controller, 'get_sensors'):
                sensors = sensor_controller.get_sensors()
                if isinstance(sensors, list):
                    return [s.name for s in sensors if hasattr(s, 'name')]
                
        # Fallback to checking data_logger if sensor_controller doesn't work
        data_logger = self.app_context.get('data_logger')
        if data_logger and hasattr(data_logger, 'get_channel_names'):
             return data_logger.get_channel_names()
             
        # If we have a main_window, try to get sensor names from there
        main_window = self.app_context.get('main_window')
        if main_window and hasattr(main_window, 'sensor_controller'):
            sensor_controller = main_window.sensor_controller
            if hasattr(sensor_controller, 'get_sensor_names'):
                return sensor_controller.get_sensor_names()
            elif hasattr(sensor_controller, 'get_sensor_list'):
                return sensor_controller.get_sensor_list()
            elif hasattr(sensor_controller, 'get_sensors'):
                sensors = sensor_controller.get_sensors()
                if isinstance(sensors, list):
                    return [s.name for s in sensors if hasattr(s, 'name')]
                
        return [] # Return empty list if unavailable
        
    def get_available_serial_ports(self):
        """Get a list of available serial ports."""
        serial_manager = self.app_context.get('interfaces', {}).get('serial_manager')
        if serial_manager and hasattr(serial_manager, 'list_ports'):
            return serial_manager.list_ports()
        return []
        
    def update_context(self, context):
         """Update the context used by running sequences."""
         # Add variable management and resolution to the context
         context['variable_manager'] = self
         context['resolve_variables'] = self.resolve_variables
         context['variables'] = self.variables # Direct access (read-only recommended)
         
         self.app_context.update(context)
         # Update context for all currently running sequences
         for seq in self.active_sequences:
             seq.set_context(self.app_context)
             
    # --- Variable Management ---
    def set_variable(self, name, value):
        """Set or update an automation variable."""
        print(f"[Automation] Setting variable '{name}' = {value}")
        self.variables[name] = value
        self.status_changed.emit() # Notify UI potentially
        
    def get_variable(self, name, default=None):
        """Get the value of an automation variable."""
        return self.variables.get(name, default)
        
    def resolve_variables(self, text):
        """Replace placeholders like {var_name} in a string with variable values."""
        if not isinstance(text, str):
             return text # Only resolve in strings
             
        resolved_text = text
        # Basic placeholder replacement
        import re
        placeholders = re.findall(r"\{([^}]+)\}", text)
        for placeholder in placeholders:
            var_name = placeholder.strip()
            value = self.get_variable(var_name)
            if value is not None:
                resolved_text = resolved_text.replace(f"{{{placeholder}}}", str(value))
            else:
                 print(f"[Automation] Warning: Variable '{var_name}' not found for substitution in '{text}'")
                 # Optionally, leave the placeholder or replace with an empty string/error marker
                 # resolved_text = resolved_text.replace(f"{{{placeholder}}}", "[VAR_NOT_FOUND]")
        return resolved_text
        
    # --- Sequence Management ---
    def add_sequence(self, sequence):
        if isinstance(sequence, AutomationSequence):
            self.sequences.append(sequence)
            self._connect_sequence_signals(sequence)
            self.sequences_changed.emit()
            self.save_sequences()
        else:
            print("Error: Attempted to add non-sequence object to manager.")
            
    def remove_sequence(self, sequence_to_remove):
        if sequence_to_remove in self.active_sequences:
            self.stop_sequence(sequence_to_remove)
            
        if sequence_to_remove in self.sequences:
            self.sequences.remove(sequence_to_remove)
            self._disconnect_sequence_signals(sequence_to_remove)
            self.sequences_changed.emit()
            self.save_sequences()
            
    def update_sequence(self, original_sequence, updated_sequence_data):
        """Update an existing sequence (e.g., after editing)"""
        if original_sequence in self.sequences:
             # Re-create the sequence object from the updated data
             # This ensures signals are handled correctly if steps were added/removed
             try:
                 index = self.sequences.index(original_sequence)
                 was_running = original_sequence in self.active_sequences
                 
                 if was_running:
                      self.stop_sequence(original_sequence)
                      
                 self._disconnect_sequence_signals(original_sequence)
                 
                 # Assume updated_sequence_data is the *object* returned by SequenceDialog
                 # If it was just a dict, we'd use AutomationSequence.from_dict here
                 new_sequence = updated_sequence_data 
                 
                 self.sequences[index] = new_sequence
                 self._connect_sequence_signals(new_sequence)
                 
                 self.sequences_changed.emit()
                 self.save_sequences()
                 
                 # Optionally restart if it was running? Or leave stopped?
                 # if was_running:
                 #     self.start_sequence(new_sequence)
                     
             except Exception as e:
                  print(f"Error updating sequence '{original_sequence.name}': {e}")
        else:
             print(f"Error: Cannot update sequence '{original_sequence.name}', not found.")
            
    def start_sequence(self, sequence):
        if sequence in self.sequences and sequence not in self.active_sequences:
            self.active_sequences.add(sequence)
            # Pass the current context to the sequence
            self.update_context({}) # Ensure latest context vars are included
            sequence.set_context(self.app_context)
            sequence.start()
            self.status_changed.emit()
        elif sequence in self.active_sequences:
             print(f"Sequence '{sequence.name}' is already running.")
        else:
             print(f"Sequence '{sequence.name}' not found in manager.")
             
    def stop_sequence(self, sequence):
        if sequence in self.active_sequences:
            sequence.stop()
            # The sequence_stopped signal handler will remove it from active_sequences
            self.status_changed.emit()
        else:
            print(f"Sequence '{sequence.name}' is not currently running.")
            
    def stop_all_sequences(self):
         print("Stopping all active automation sequences...")
         # Iterate over a copy as stop_sequence modifies the set
         for seq in list(self.active_sequences):
             self.stop_sequence(seq)
         print("All sequences stopped.")

    def save_sequences(self):
        """Save the current sequences list to the JSON file."""
        if not self.sequences_file:
            print("Error: No sequence file path set for saving.")
            return

        try:
            # Ensure the directory exists
            directory = os.path.dirname(self.sequences_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            
            # Serialize sequences
            sequences_data = [seq.to_dict() for seq in self.sequences]
            
            # Write to file
            with open(self.sequences_file, 'w') as f:
                json.dump(sequences_data, f, indent=4)
            print(f"Automation sequences saved to {self.sequences_file}")

        except IOError as e:
            print(f"Error saving automation sequences to {self.sequences_file}: {e}")
            # Consider emitting an error signal or showing a message box
        except Exception as e:
            print(f"Unexpected error saving automation sequences: {e}")
            traceback.print_exc()

    def load_sequences(self):
        """Load sequences from the JSON file."""
        # Stop any currently running sequences before loading new ones
        self.stop_all_sequences() 
        
        # Clear existing sequences
        self.sequences = []
        self.active_sequences.clear()

        if not self.sequences_file:
            print("Error: No sequence file path set for loading.")
            self.sequences_changed.emit()
            self.status_changed.emit()
            return

        if not os.path.exists(self.sequences_file):
            print(f"Sequence file not found: {self.sequences_file}. No sequences loaded.")
            self.sequences_changed.emit() # Notify UI that sequences are cleared
            self.status_changed.emit()
            return

        try:
            with open(self.sequences_file, 'r') as f:
                # Handle empty file case
                content = f.read()
                if not content:
                    print(f"Sequence file is empty: {self.sequences_file}. No sequences loaded.")
                    self.sequences_changed.emit()
                    self.status_changed.emit()
                    return
                sequences_data = json.loads(content)
            
            loaded_sequences = []
            for data in sequences_data:
                try:
                    sequence = AutomationSequence.from_dict(data)
                    loaded_sequences.append(sequence)
                    self._connect_sequence_signals(sequence) # Connect signals for loaded sequence
                except Exception as e:
                    print(f"Error deserializing sequence data: {data}. Error: {e}")
                    traceback.print_exc()
                    # Skip this sequence and continue loading others
            
            self.sequences = loaded_sequences
            print(f"Loaded {len(self.sequences)} automation sequences from {self.sequences_file}")

        except FileNotFoundError:
            # This case is handled by the os.path.exists check above, but good practice
            print(f"Sequence file not found: {self.sequences_file}. No sequences loaded.")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from sequence file {self.sequences_file}: {e}")
            # File might be corrupted, leave sequences empty
        except Exception as e:
            print(f"Error loading automation sequences from {self.sequences_file}: {e}")
            traceback.print_exc()
            # Generic error, leave sequences empty
            
        # Always emit signals after attempting to load
        self.sequences_changed.emit()
        self.status_changed.emit()

    # --- Signal Handling ---
    def _connect_sequence_signals(self, sequence):
         sequence.sequence_started.connect(self.sequence_started)
         sequence.sequence_stopped.connect(self._handle_sequence_stopped)
         sequence.sequence_completed.connect(self.sequence_completed)
         sequence.sequence_step_changed.connect(self.sequence_step_changed)
         sequence.sequence_error.connect(self.sequence_error)
         
    def _disconnect_sequence_signals(self, sequence):
         # Attempt to disconnect signals safely
         try: sequence.sequence_started.disconnect(self.sequence_started)
         except TypeError: pass
         try: sequence.sequence_stopped.disconnect(self._handle_sequence_stopped)
         except TypeError: pass
         try: sequence.sequence_completed.disconnect(self.sequence_completed)
         except TypeError: pass
         try: sequence.sequence_step_changed.disconnect(self.sequence_step_changed)
         except TypeError: pass
         try: sequence.sequence_error.disconnect(self.sequence_error)
         except TypeError: pass
         
         # Also disconnect step signals within the sequence
         for step in sequence.steps:
             try: step.step_completed.disconnect(sequence._handle_step_completed)
             except TypeError: pass
             try: step.step_failed.disconnect(sequence._handle_step_failed)
             except TypeError: pass
             # Disconnect action signals within the step
             try: step.action.action_completed.disconnect(step._on_action_completed)
             except TypeError: pass
             try: step.action.action_failed.disconnect(step._on_action_failed)
             except TypeError: pass

    def _handle_sequence_stopped(self, sequence):
        """Handle sequence stopped signal to remove from active set."""
        self.active_sequences.discard(sequence)
        self.status_changed.emit()
        # Re-emit the signal from the manager
        self.sequence_stopped.emit(sequence) 