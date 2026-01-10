"""
Other Serial Interface

Handles communication with custom serial devices using configurable read/process sequences.
"""

import time
import re
import os
import serial
import serial.tools.list_ports
import threading
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from app.core.interfaces.base_interface import BaseInterface


class SerialStep:
    """Base class for a step in a serial sequence"""
    
    def __init__(self, step_type=""):
        self.step_type = step_type
        
    def execute(self, interface, variables):
        """Execute the step"""
        raise NotImplementedError("Subclasses must implement this method")


class SendCommandStep(SerialStep):
    """Step to send a command to the serial device"""
    
    def __init__(self, command, line_ending="None"):
        super().__init__("SendCommand")
        self.command = command
        self.line_ending = line_ending
        
    def execute(self, interface, variables):
        """Send the command to the serial device"""
        # Process any variable substitutions in the command
        command = self.command
        for var_name, var_value in variables.items():
            command = command.replace(f"{{{var_name}}}", str(var_value))
            
        # Add line ending (handle both escaped and unescaped forms)
        le = self.line_ending.lower() if self.line_ending else ""
        if "cr" in le and "lf" in le:
            # CRLF
            command += "\r\n"
        elif "lf" in le or le == "\\n" or le == "\n":
            command += "\n"
        elif "cr" in le or le == "\\r" or le == "\r":
            command += "\r"
        # else: "None" or empty -> no line ending added
        
        print(f"DEBUG SendCommandStep: Sending command '{repr(command)}' with line_ending='{self.line_ending}'")
        
        # Flush input buffer before sending to clear any stale data
        if hasattr(interface, 'serial') and interface.serial:
            try:
                interface.serial.reset_input_buffer()
            except Exception:
                pass
            
        # Send the command
        return interface.write_data(command)


class WaitStep(SerialStep):
    """Step to wait for a specified amount of time"""
    
    def __init__(self, wait_time):
        super().__init__("Wait")
        self.wait_time = wait_time  # in milliseconds
        
    def execute(self, interface, variables):
        """Wait for the specified time, but allow interruption via interface.should_stop"""
        total_wait = self.wait_time / 1000.0
        print(f"DEBUG WaitStep: Waiting for {self.wait_time}ms ({total_wait}s)...")
        waited = 0
        interval = 0.05  # 50 ms
        while waited < total_wait:
            if hasattr(interface, 'should_stop') and interface.should_stop:
                print("DEBUG WaitStep: Interrupted by should_stop flag!")
                return False
            time.sleep(interval)
            waited += interval
        # Check if any data arrived during the wait
        if hasattr(interface, 'serial') and interface.serial:
            in_waiting = interface.serial.in_waiting
            print(f"DEBUG WaitStep: Wait completed. Bytes in buffer after wait: {in_waiting}")
        return True


class ReadResponseStep(SerialStep):
    """Step to read a response from the serial device"""
    
    def __init__(self, read_type="Read Line", timeout=1000, result_var="response"):
        super().__init__("ReadResponse")
        self.read_type = read_type
        self.timeout = timeout  # in milliseconds
        self.result_var = result_var
        
    def execute(self, interface, variables):
        """Read from the serial device, but allow interruption via interface.should_stop"""
        if not interface.is_connected():
            print("DEBUG ReadResponseStep: Interface not connected!")
            return False
            
        try:
            # Set the timeout
            if hasattr(interface, 'serial'):
                interface.serial.timeout = self.timeout / 1000.0
                print(f"DEBUG ReadResponseStep: Set timeout to {self.timeout}ms, read_type='{self.read_type}', result_var='{self.result_var}'")
                # Check if there's any data waiting
                in_waiting = interface.serial.in_waiting
                print(f"DEBUG ReadResponseStep: Bytes in buffer before read: {in_waiting}")
            
            # Read based on type
            if self.read_type == "Read Line":
                # Use a loop with short timeouts to allow interruption
                response = ""
                start_time = time.time()
                while time.time() - start_time < (self.timeout / 1000.0):
                    if hasattr(interface, 'should_stop') and interface.should_stop:
                        print("DEBUG ReadResponseStep: Interrupted by should_stop flag!")
                        return False
                    line = interface.serial.readline().decode('utf-8', errors='replace')
                    if line:
                        response = line.strip()
                        break
                    time.sleep(0.01)
            elif self.read_type == "Read Until Timeout":
                response = ""
                start_time = time.time()
                while time.time() - start_time < (self.timeout / 1000.0):
                    if hasattr(interface, 'should_stop') and interface.should_stop:
                        print("DEBUG ReadResponseStep: Interrupted by should_stop flag!")
                        return False
                    if interface.serial.in_waiting > 0:
                        char = interface.serial.read(1).decode('utf-8', errors='replace')
                        response += char
                    else:
                        time.sleep(0.01)
            elif self.read_type == "Read N Bytes":
                n_bytes = 100
                response = ""
                read_bytes = 0
                while read_bytes < n_bytes:
                    if hasattr(interface, 'should_stop') and interface.should_stop:
                        print("DEBUG ReadResponseStep: Interrupted by should_stop flag!")
                        return False
                    chunk = interface.serial.read(1)
                    if not chunk:
                        time.sleep(0.01)
                        continue
                    response += chunk.decode('utf-8', errors='replace')
                    read_bytes += 1
            else:
                response = ""
                
            # Store result in variables
            variables[self.result_var] = response
            print(f"DEBUG ReadResponseStep: Read completed. response='{repr(response)}', stored in '{self.result_var}'")
            return True
        except Exception as e:
            print(f"Error reading from serial: {e}")
            return False


class ParseValueStep(SerialStep):
    """Step to parse a value from a previous response"""
    
    def __init__(self, source_var="response", parse_method="Entire Response", 
                 start_marker="", end_marker="", result_type="Number (Float)", result_var="value"):
        super().__init__("ParseValue")
        self.source_var = source_var
        self.parse_method = parse_method
        self.start_marker = start_marker
        self.end_marker = end_marker
        self.result_type = result_type
        self.result_var = result_var
        
    def execute(self, interface, variables):
        """Parse a value from a response"""
        if self.source_var not in variables:
            return False
            
        source_text = variables[self.source_var]
        result = None
        
        # Parse based on method
        if self.parse_method == "Entire Response":
            result = source_text
        elif self.parse_method == "Between Markers":
            start_pos = source_text.find(self.start_marker)
            if start_pos >= 0:
                start_pos += len(self.start_marker)
                if self.end_marker:
                    end_pos = source_text.find(self.end_marker, start_pos)
                    if end_pos >= 0:
                        result = source_text[start_pos:end_pos]
                else:
                    result = source_text[start_pos:]
        elif self.parse_method == "After Marker":
            start_pos = source_text.find(self.start_marker)
            if start_pos >= 0:
                start_pos += len(self.start_marker)
                result = source_text[start_pos:]
        elif self.parse_method == "Before Marker":
            if self.end_marker:
                end_pos = source_text.find(self.end_marker)
                if end_pos >= 0:
                    result = source_text[:end_pos]
        elif self.parse_method == "Regex Pattern":
            if self.start_marker:  # Using start_marker as regex pattern
                match = re.search(self.start_marker, source_text)
                if match:
                    if match.groups():
                        result = match.group(1)  # Get first capture group
                    else:
                        result = match.group(0)  # Get entire match
        
        # Convert result based on type
        if result is not None:
            try:
                if self.result_type == "Number (Float)":
                    # Find the first floating point number in the string
                    number_match = re.search(r'[-+]?\d*\.\d+|\d+', result)
                    if number_match:
                        result = float(number_match.group(0))
                    else:
                        result = 0.0
                elif self.result_type == "Number (Integer)":
                    # Find the first integer in the string
                    number_match = re.search(r'[-+]?\d+', result)
                    if number_match:
                        result = int(number_match.group(0))
                    else:
                        result = 0
                # Text type just stays as is
            except (ValueError, TypeError):
                # If conversion fails, return original string
                pass
                
            # Store result
            variables[self.result_var] = result
            return True
        
        return False


class PublishValueStep(SerialStep):
    """Step to publish a value as the final output of the sequence"""
    
    def __init__(self, source_var="value", target="value"):
        super().__init__("publish")
        self.source_var = source_var  # Variable to publish
        self.target = target  # Name to publish as - typically the sensor name
        
    def execute(self, interface, variables):
        """Publish a value from variables"""
        print(f"DEBUG PublishValueStep.execute: Looking for source_var='{self.source_var}' in variables: {variables}")
        
        # More permissive version - try to be smart about finding the value
        if self.source_var in variables:
            # Direct match - use it
            variables[self.target] = variables[self.source_var]
            print(f"DEBUG PublishValueStep: Published '{self.source_var}' as '{self.target}': {variables[self.target]}")
            return True
        elif "value" in variables:
            # If source_var not found but 'value' exists, use that as a fallback
            variables[self.target] = variables["value"]
            print(f"DEBUG PublishValueStep: Published fallback 'value' as '{self.target}': {variables[self.target]}")
            return True
        else:
            # Look for any numeric variable if all else fails
            for var_name, var_value in variables.items():
                try:
                    if isinstance(var_value, (int, float)) or (isinstance(var_value, str) and var_value.replace('.', '', 1).isdigit()):
                        # Found a numeric value, use it
                        value = float(var_value) if not isinstance(var_value, (int, float)) else var_value
                        variables[self.target] = value
                        print(f"DEBUG PublishValueStep: Published numeric var '{var_name}' as '{self.target}': {value}")
                        return True
                except (ValueError, TypeError):
                    continue
                    
            print(f"DEBUG PublishValueStep: Source variable '{self.source_var}' not found in variables: {variables}")
            return False


class SerialSequence:
    """A sequence of steps to execute on a serial device"""
    
    def __init__(self, name="", steps=None):
        self.name = name
        self.steps = steps or []
        
    def execute(self, interface):
        """Execute all steps in the sequence.
        
        Returns:
            dict: Published outputs collected from PublishValueStep targets (target -> value)
            None: If the sequence fails or produces no usable output
        """
        variables = {}  # Dictionary to store variables
        published_outputs = {}  # target -> value
        
        print(f"DEBUG SerialSequence: Executing sequence '{self.name}' with {len(self.steps)} steps")
        
        try:
            for i, step in enumerate(self.steps):
                print(f"DEBUG SerialSequence: Executing step {i+1}/{len(self.steps)}: {step.step_type}")
                success = step.execute(interface, variables)
                if not success:
                    print(f"DEBUG SerialSequence: Step {i+1} failed, aborting sequence")
                    return None
                
                # For debugging, print all variables
                print(f"DEBUG SerialSequence: Variables after step {i+1}: {variables}")
                
                # Collect outputs from publish steps. A sequence may publish multiple variables.
                if step.step_type == "publish" and isinstance(step, PublishValueStep):
                    if step.target in variables:
                        published_outputs[step.target] = variables[step.target]
                        print(f"DEBUG SerialSequence: Published output '{step.target}': {variables[step.target]}")
            
            # If nothing explicitly published, fall back to 'value' if present.
            if not published_outputs and "value" in variables:
                published_outputs["value"] = variables.get("value")
                print(f"DEBUG SerialSequence: No explicit publish; using fallback 'value': {variables.get('value')}")

            if not published_outputs:
                print(f"DEBUG SerialSequence: Sequence '{self.name}' produced no outputs")
                return None

            print(f"DEBUG SerialSequence: Sequence '{self.name}' completed with outputs: {published_outputs}")
            return published_outputs
            
        except Exception as e:
            print(f"ERROR SerialSequence: Error executing sequence '{self.name}': {e}")
            import traceback
            traceback.print_exc()
            return None
        
    def to_dict(self):
        """Convert the sequence to a dictionary for saving"""
        steps_dict = []
        for step in self.steps:
            if isinstance(step, SendCommandStep):
                steps_dict.append({
                    "type": "SendCommand",
                    "command": step.command,
                    "line_ending": step.line_ending
                })
            elif isinstance(step, WaitStep):
                steps_dict.append({
                    "type": "Wait",
                    "wait_time": step.wait_time
                })
            elif isinstance(step, ReadResponseStep):
                steps_dict.append({
                    "type": "ReadResponse",
                    "read_type": step.read_type,
                    "timeout": step.timeout,
                    "result_var": step.result_var
                })
            elif isinstance(step, ParseValueStep):
                steps_dict.append({
                    "type": "ParseValue",
                    "source_var": step.source_var,
                    "parse_method": step.parse_method,
                    "start_marker": step.start_marker,
                    "end_marker": step.end_marker,
                    "result_type": step.result_type,
                    "result_var": step.result_var
                })
            elif isinstance(step, PublishValueStep):
                steps_dict.append({
                    "type": "publish",
                    "source_var": step.source_var,
                    "target": step.target
                })
                
        return {
            "name": self.name,
            "steps": steps_dict
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create a sequence from a dictionary"""
        sequence = cls(name=data.get("name", ""))
        
        # Load steps
        for step_data in data.get("steps", []):
            step_type = step_data.get("type", "")
            
            if step_type == "SendCommand":
                step = SendCommandStep(
                    command=step_data.get("command", ""),
                    line_ending=step_data.get("line_ending", "None")
                )
            elif step_type == "Wait":
                step = WaitStep(
                    wait_time=step_data.get("wait_time", 1000)
                )
            elif step_type == "ReadResponse":
                step = ReadResponseStep(
                    read_type=step_data.get("read_type", "Read Line"),
                    timeout=step_data.get("timeout", 1000),
                    result_var=step_data.get("result_var", "response")
                )
            elif step_type == "ParseValue":
                step = ParseValueStep(
                    source_var=step_data.get("source_var", "response"),
                    parse_method=step_data.get("parse_method", "Entire Response"),
                    start_marker=step_data.get("start_marker", ""),
                    end_marker=step_data.get("end_marker", ""),
                    result_type=step_data.get("result_type", "Number (Float)"),
                    result_var=step_data.get("result_var", "value")
                )
            elif step_type == "publish":
                step = PublishValueStep(
                    source_var=step_data.get("source_var", "value"),
                    target=step_data.get("target", "value")
                )
            else:
                continue
                
            sequence.steps.append(step)
            
        return sequence


class OtherSerialInterface(BaseInterface):
    """Interface for other serial devices with custom sequences"""
    
    DISPLAY_NAME = "Serial"
    DESCRIPTION = "Custom serial device with communication sequences"
    ICON = "Other.png"
    
    HELP_TEXT = """
    <h3>Custom Serial Interface</h3>
    <p>Connects to any serial device and executes a sequence of commands to read data.</p>
    <p><b>How to use:</b></p>
    <ol>
        <li>Select the COM port and baud rate.</li>
        <li>Configure the communication sequence (Send Command, Wait, Read, Parse).</li>
        <li>The sequence will be executed periodically based on the poll interval.</li>
    </ol>
    """
    
    CONFIG_SCHEMA = {
        "port": {"type": "list", "label": "Serial Port", "options_cmd": "list_ports"},
        "baud_rate": {"type": "list", "label": "Baud Rate", "options": [9600, 19200, 38400, 57600, 115200], "default": 9600},
        "poll_interval": {"type": "number", "label": "Poll Interval (s)", "default": 1.0}
    }

    @classmethod
    def get_ui_options(cls, field_name):
        if field_name == "port":
            return cls.list_ports()
        return []

    def __init__(self, port="COM4", baud_rate=9600, data_bits=8, parity="None", 
                 stop_bits=1, poll_interval=1.0, sequence=None, sequences=None):
        """
        Initialize the interface
        
        Args:
            port: Serial port
            baud_rate: Baud rate
            data_bits: Data bits (5-8)
            parity: Parity ("None", "Even", "Odd", "Mark", "Space")
            stop_bits: Stop bits (1, 1.5, 2)
            poll_interval: Polling interval in seconds
            sequence: SerialSequence to execute (single sequence mode)
            sequences: Optional list of SerialSequence objects (multi sequence mode)
        """
        super().__init__(name="OtherSerial")
        self.port = port
        self.baud_rate = baud_rate
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.poll_interval = float(poll_interval)
        self.sequence = sequence or SerialSequence()
        self.sequences = sequences or None
        
        self.serial = None
        self.last_poll_time = 0
        self.error_message = ""
        self.connected = False
        self.should_stop = False  # Add this flag for interruption
        
    def connect(self):
        """
        Connect to the serial device
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            print(f"DEBUG OtherSerialInterface: Connecting to port {self.port} at {self.baud_rate} baud")
            
            # Map parity string to pyserial constant
            parity_map = {
                "None": serial.PARITY_NONE,
                "Even": serial.PARITY_EVEN,
                "Odd": serial.PARITY_ODD,
                "Mark": serial.PARITY_MARK,
                "Space": serial.PARITY_SPACE
            }
            
            # Map stop bits string to pyserial constant
            stop_bits_map = {
                "1": serial.STOPBITS_ONE,
                "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                "2": serial.STOPBITS_TWO
            }
            
            parity_value = parity_map.get(self.parity, serial.PARITY_NONE)
            stop_bits_value = stop_bits_map.get(str(self.stop_bits), serial.STOPBITS_ONE)
            
            # Use timeout=2 to match the Test dialog behavior
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=self.data_bits,
                parity=parity_value,
                stopbits=stop_bits_value,
                timeout=2.0  # Match Test dialog's timeout=2
            )
            
            # No sleep - just check if the port is actually open
            if not self.serial.is_open:
                self.serial.open()
            
            # Wait for Arduino to reset after DTR toggle (opening port resets Arduino)
            # This matches what happens in the Test dialog when user clicks through steps
            print("DEBUG OtherSerialInterface: Waiting 2s for Arduino to boot after reset...")
            time.sleep(2.0)
                
            # Quick test to see if the port is responding
            try:
                _ = self.serial.in_waiting
            except Exception as e:
                print(f"DEBUG OtherSerialInterface: Port test failed: {e}")
                self.disconnect()
                self.error_message = f"Port opened but not responding: {e}"
                return False
                
            self.connected = True
            self.error_message = ""
            print(f"DEBUG OtherSerialInterface: Successfully connected to port {self.port}")
            self.should_stop = False  # Reset on connect
            return True
        except serial.SerialException as e:
            err_str = str(e)
            if "FileNotFoundError" in err_str or "system cannot find the file specified" in err_str:
                self.error_message = f"Port {self.port} not found. Please check connections and port selection."
            elif "PermissionError" in err_str or "Access is denied" in err_str:
                self.error_message = f"Access to {self.port} denied. Port might be in use."
            else:
                self.error_message = f"Serial error: {err_str}"
            print(f"DEBUG OtherSerialInterface: Serial exception: {self.error_message}")
            self.connected = False
            return False
        except Exception as e:
            self.error_message = f"Failed to connect: {str(e)}"
            print(f"DEBUG OtherSerialInterface: Connection error: {self.error_message}")
            self.connected = False
            return False
            
    def disconnect(self):
        """Disconnect from the serial device"""
        if self.serial and self.connected:
            print(f"DEBUG OtherSerialInterface: Disconnecting from port {self.port}")
            self.serial.close()
            self.serial = None
            self.connected = False
            self.should_stop = True  # Set on disconnect
            
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        if self.connected and self.serial:
            try:
                # Try a simple operation to verify connection is still active
                if hasattr(self.serial, 'in_waiting'):
                    _ = self.serial.in_waiting
                return True
            except Exception:
                # If any exception occurs, port is no longer connected
                self.connected = False
                self.serial = None
                return False
        return False
        
    def read_data(self):
        """
        Read data from the serial device using the defined sequence
        
        Returns:
            Dictionary with sensor value or None if failed
        """
        def _has_steps(seq_obj):
            try:
                return bool(getattr(seq_obj, "steps", []))
            except Exception:
                return False

        sequences_to_run = self.sequences if self.sequences else ([self.sequence] if self.sequence else [])
        has_any_steps = any(_has_steps(s) for s in sequences_to_run)

        if not self.is_connected() or not has_any_steps:
            if not self.is_connected():
                print("DEBUG OtherSerialInterface.read_data: Not connected, returning None")
            elif not has_any_steps:
                print("DEBUG OtherSerialInterface.read_data: No sequence steps defined, returning None")
            return None
        
        # Check if it's time to poll
        current_time = time.time()
        if current_time - self.last_poll_time < self.poll_interval:
            # Not time to poll yet
            return None
            
        self.last_poll_time = current_time
        
        # Execute the sequence(s)
        try:
            merged = {}

            for seq in sequences_to_run:
                if not seq or not _has_steps(seq):
                    continue

                print(f"DEBUG OtherSerialInterface.read_data: Executing sequence {seq.name} at time {current_time}")
                result = seq.execute(self)

                if not result:
                    print(f"DEBUG OtherSerialInterface.read_data: Sequence {getattr(seq, 'name', 'Unnamed')} returned no data")
                    continue

                # `SerialSequence.execute` returns a dict of published targets (target -> value).
                # Prefix keys with "SequenceName:" so multiple sequences and multiple targets don't collide.
                if isinstance(result, dict):
                    outputs = result
                else:
                    # Legacy safety: map scalar to first publish target or to the sequence name.
                    target_name = None
                    for step in getattr(seq, "steps", []):
                        if isinstance(step, PublishValueStep):
                            target_name = step.target
                            break
                    if not target_name or target_name == "value":
                        target_name = seq.name
                    outputs = {target_name: result}

                for key, value in outputs.items():
                    if key is None:
                        continue
                    key_str = str(key)
                    if ":" not in key_str:
                        key_str = f"{seq.name}:{key_str}"
                    merged[key_str] = value

            if merged:
                return merged
            print("DEBUG OtherSerialInterface.read_data: No sequence produced data")
            return None
        except Exception as e:
            self.error_message = f"Error reading from serial device: {e}"
            print(f"DEBUG OtherSerialInterface.read_data: Error: {self.error_message}")
            import traceback
            traceback.print_exc()
            
        return None
        
    def write_data(self, data):
        """
        Write data to the serial device
        
        Args:
            data: Command to send (string)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            return False
            
        try:
            if isinstance(data, str):
                self.serial.write(data.encode('utf-8', errors='replace'))
            else:
                # Handle bytes directly
                self.serial.write(data)
            
            # Flush the write buffer to ensure data is sent
            self.serial.flush()
            return True
        except Exception as e:
            self.error_message = f"Error writing data: {e}"
            return False
            
    @staticmethod
    def list_ports():
        """
        List available serial ports
        
        Returns:
            List of available ports
        """
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append(port.device)
        return ports


class OtherSerialThread(QThread):
    """Thread for handling other serial device communication"""
    
    # Define signals for thread-safe communication
    data_received_signal = pyqtSignal(dict)  # Signal emitted when new data is received
    connection_status_signal = pyqtSignal(bool, str)  # For connection status updates
    error_signal = pyqtSignal(str)  # For error messages
    
    def __init__(self):
        """Initialize the thread"""
        super().__init__()
        
        self.interface = None
        self.running = True  # Start with running=True to avoid thread stopping prematurely
        self._was_connected = False
        self.poll_interval = 1.0  # Default polling interval in seconds
        self.collecting_data = False
        self.paused = False
        self.mutex = QMutex()
        self.latest_data = {}  # Latest data from the device
        self.output_directory = None  # Directory for saving data
        self.last_response = ""  # Store the last response from the device
        self.last_poll_time = 0  # Time of last poll
        self.auto_reconnect = True  # Enable auto-reconnect by default
        self._last_reconnect_attempt = 0
        self._reconnect_interval = 5.0  # seconds
        
    def run(self):
        """Main thread method"""
        print(f"DEBUG OtherSerialThread: Started with running={self.running}")
        
        while self.running:
            try:
                # Handle reconnection if needed
                if not self.paused and self.interface and not self.interface.is_connected():
                    if self._was_connected:
                        print("OtherSerialThread: Connection lost!")
                        self.connection_status_signal.emit(False, "Connection lost")
                        self._was_connected = False

                    if self.auto_reconnect:
                        current_time = time.time()
                        if current_time - self._last_reconnect_attempt >= self._reconnect_interval:
                            self._last_reconnect_attempt = current_time
                            print(f"OtherSerialThread: Connection lost, attempting reconnect to {self.interface.port}...")
                            if self.interface.connect():
                                print("OtherSerialThread: Reconnected successfully")
                                self.connection_status_signal.emit(True, f"Reconnected to serial device on {self.interface.port}")
                            else:
                                print("OtherSerialThread: Reconnect failed")
                        
                        time.sleep(1.0)
                        continue
                    else:
                        print("OtherSerialThread: Connection lost, and auto-reconnect disabled")
                        # We don't break here to allow the interface to be set again or paused/unpaused
                
                if not self.paused and self.interface and self.interface.is_connected():
                    # Check if it's time to poll based on the poll interval
                    current_time = time.time()
                    if current_time - self.last_poll_time >= self.poll_interval:
                        self.last_poll_time = current_time
                        
                        # Read data from the interface
                        print(f"DEBUG OtherSerialThread: Polling interface with poll_interval={self.poll_interval}")
                        data = self.interface.read_data()
                        
                        if data:
                            print(f"DEBUG OtherSerialThread: Received data: {data}")
                            # Update latest data
                            self.mutex.lock()
                            self.latest_data.update(data)
                            self.mutex.unlock()
                            
                            # Add timestamp if not present
                            if 'timestamp' not in data:
                                data['timestamp'] = current_time
                                
                            # Emit signal with data
                            print(f"DEBUG OtherSerialThread: Emitting data via signal: {data}")
                            self.data_received_signal.emit(data.copy())  # Copy to avoid threading issues
                            print(f"DEBUG OtherSerialThread: Signal emission completed")
                        else:
                            print("DEBUG OtherSerialThread: No data received from interface")
                    
                # Sleep to prevent high CPU usage
                time.sleep(0.1)  # Increased from 0.01 to reduce CPU load
            except Exception as e:
                print(f"ERROR OtherSerialThread.run: {e}")
                import traceback
                traceback.print_exc()
                self.error_signal.emit(f"Error in OtherSerialThread: {str(e)}")
                time.sleep(1)  # Sleep for 1 second on error to prevent rapid error loops
                
        print("DEBUG OtherSerialThread: Thread exiting")
            
    def connect(self, port=None, baud_rate=9600, data_bits=8, parity="None", 
                stop_bits=1, poll_interval=1.0, sequence=None, sequences=None):
        """Connect to a serial device"""
        try:
            # Handle case where no port is provided (e.g. from harmonized dialog)
            if port is None:
                # Try to use previously set port or config
                if hasattr(self, 'port'):
                    port = self.port
                elif self.interface:
                    port = self.interface.port
                else:
                    # Look for it in sequences if available
                    if sequences and len(sequences) > 0:
                        port = sequences[0].get('port', 'COM1')
                    else:
                        raise ValueError("No port specified for serial connection")
            else:
                self.port = port

            # Update other attributes if provided
            if baud_rate: self.baud_rate = baud_rate
            if poll_interval: self.poll_interval = float(poll_interval)
            
            print(f"DEBUG OtherSerialThread: Attempting to connect to serial device on {port} with poll_interval={self.poll_interval}")
            
            # Send immediate feedback that connection is in progress
            self.connection_status_signal.emit(False, f"Connecting to {port}...")
            
            # Create the interface if it doesn't exist or parameters changed
            self.interface = OtherSerialInterface(
                port=port,
                baud_rate=getattr(self, 'baud_rate', baud_rate),
                data_bits=data_bits,
                parity=parity,
                stop_bits=stop_bits,
                poll_interval=self.poll_interval,
                sequence=sequence,
                sequences=sequences
            )
            
            # Try to connect
            success = self.interface.connect()
            
            if success:
                print(f"DEBUG OtherSerialThread: Successfully connected to serial device on {port}")
                self.connection_status_signal.emit(True, f"Connected to serial device on {port}")
                self._was_connected = True
                
                # Reset the last poll time to ensure immediate reading
                self.last_poll_time = 0
                
                # Make sure thread is running
                self.running = True
                self.paused = False
                
                if not self.isRunning():
                    print("DEBUG OtherSerialThread: Starting thread")
                    self.start(QThread.Priority.LowPriority)
                
                # Force an immediate poll to get initial value
                try:
                    if self.interface and self.interface.is_connected():
                        print("DEBUG OtherSerialThread: Forcing initial poll")
                        data = self.interface.read_data()
                        if data:
                            print(f"DEBUG OtherSerialThread: Initial poll returned data: {data}")
                            data['timestamp'] = time.time()
                            self.data_received_signal.emit(data.copy())
                        else:
                            print("DEBUG OtherSerialThread: Initial poll returned no data")
                except Exception as e:
                    print(f"ERROR OtherSerialThread: Initial poll failed: {e}")
                
                return True
            else:
                error_msg = self.interface.error_message or "Connection failed for unknown reason"
                print(f"DEBUG OtherSerialThread: Failed to connect to serial device: {error_msg}")
                self.connection_status_signal.emit(False, error_msg)
                self.interface = None  # Clear reference to failed interface
                return False
                
        except Exception as e:
            error_msg = f"Failed to connect to serial device: {str(e)}"
            print(f"DEBUG OtherSerialThread: Exception during connect: {error_msg}")
            import traceback
            traceback.print_exc()
            self.connection_status_signal.emit(False, error_msg)
            self.interface = None  # Clear reference to failed interface
            return False
            
    def disconnect(self):
        """Disconnect from the serial device"""
        if self.interface:
            print("DEBUG OtherSerialThread: Disconnecting from serial device")
            # Set should_stop to True to interrupt any blocking step
            self.interface.should_stop = True
            try:
                self.interface.disconnect()
            except Exception as e:
                print(f"DEBUG OtherSerialThread: Error disconnecting interface: {e}")
            # Set interface to None to prevent further use
            self.interface = None
            # Signal disconnection
            self.connection_status_signal.emit(False, "Disconnected from serial device")
            # Clear latest data
            self.mutex.lock()
            self.latest_data = {}
            self.mutex.unlock()
            # Stop the thread if running
            self.running = False
            if self.isRunning():
                print("DEBUG OtherSerialThread: Stopping thread")
                self.wait(2000)  # Wait up to 2 seconds for thread to finish
                if self.isRunning():
                    print("DEBUG OtherSerialThread: Thread didn't stop cleanly, terminating")
                    self.terminate()
        else:
            print("DEBUG OtherSerialThread: disconnect called but no interface exists")
        
    def get_latest_data(self):
        """
        Get the latest data
        
        Returns:
            Dictionary with latest data
        """
        self.mutex.lock()
        data_copy = self.latest_data.copy()
        self.mutex.unlock()
        return data_copy
        
    def set_output_directory(self, output_dir):
        """Set the output directory for data files"""
        self.output_dir = output_dir
        # Create directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
    def is_connected(self):
        """Check if connected to serial device"""
        return self.interface and self.interface.is_connected()
        
    def start_data_collection(self, output_dir=None):
        """Start collecting data to files"""
        if output_dir:
            self.set_output_directory(output_dir)
            
        self.paused = False
        
    def stop_data_collection(self):
        """Stop collecting data"""
        self.paused = True
        
    def pause_data_collection(self):
        """Pause data collection"""
        self.paused = True
        
    def resume_data_collection(self):
        """Resume data collection"""
        if self.interface:
            self.collecting_data = True
        
    @staticmethod
    def list_ports():
        """
        List available serial ports
        
        Returns:
            List of port names
        """
        try:
            print("OtherSerialThread.list_ports: Getting available ports...")
            # Get ports info with a short timeout to prevent long pauses
            # when no serial devices are connected
            ports = list(serial.tools.list_ports.comports())
            print(f"OtherSerialThread.list_ports: Found {len(ports)} ports")
            
            # Process ports in parallel (future optimization) or just compile the list quickly
            port_names = [port.device for port in ports]
            print(f"OtherSerialThread.list_ports: Port names: {port_names}")
            return port_names
        except Exception as e:
            print(f"OtherSerialThread.list_ports: Error listing ports: {e}")
            return []
    
    def send_command(self, command, line_ending="None"):
        """
        Send a command to the serial device
        
        Args:
            command: Command string to send
            line_ending: Line ending to append (None, CR, LF, CRLF)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.interface or not self.interface.is_connected():
            return "Error: Device not connected"
        
        # Add line ending
        if line_ending == "CR (\\r)":
            command += "\r"
        elif line_ending == "LF (\\n)":
            command += "\n"
        elif line_ending == "CRLF (\\r\\n)":
            command += "\r\n"
        
        # Send command
        try:
            result = self.interface.write_data(command)
            return f"Command sent: {command}"
        except Exception as e:
            return f"Error sending command: {str(e)}"
        
    def read_response(self, timeout=1.0):
        """
        Read a response from the serial device
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            Response string
        """
        if not self.interface or not self.interface.is_connected():
            return "Error: Device not connected"
        
        try:
            # Store current timeout
            original_timeout = None
            if hasattr(self.interface, 'serial'):
                original_timeout = self.interface.serial.timeout
                self.interface.serial.timeout = timeout
            
            # Read response
            response = self.interface.serial.readline().decode('utf-8', errors='replace').strip()
            
            # Store response for later use
            self.last_response = response
            
            # Restore original timeout
            if original_timeout is not None:
                self.interface.serial.timeout = original_timeout
            
            return response
        except Exception as e:
            return f"Error reading response: {str(e)}" 