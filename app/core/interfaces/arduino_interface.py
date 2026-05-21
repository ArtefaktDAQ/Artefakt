"""
Arduino Interface

Handles communication with Arduino devices.
"""

import time
import serial
import serial.tools.list_ports
from app.core.interfaces.base_interface import BaseInterface


class ArduinoInterface(BaseInterface):
    """Interface for Arduino devices"""
    
    DISPLAY_NAME = "Arduino"
    DESCRIPTION = "Standard Arduino communication over Serial"
    ICON = "Arduino.png"
    
    HELP_TEXT = """
    <h3>Arduino Interface</h3>
    <p>Handles communication with Arduino devices over Serial.</p>
    <p><b>How to use:</b></p>
    <ol>
        <li>Upload the provided Arduino example code to your board.</li>
        <li>Connect via USB and select the correct COM port and baud rate.</li>
        <li>Data format: <code>SensorName1:value;SensorName2:value;...</code></li>
    </ol>
    """
    
    CONFIG_SCHEMA = {
        "port": {
            "type": "list", 
            "label": "Serial Port", 
            "options_cmd": "list_ports",
            "required": True
        },
        "baud_rate": {
            "type": "list", 
            "label": "Baud Rate", 
            "options": [9600, 19200, 38400, 57600, 115200],
            "default": 9600
        },
        "mode": {
            "type": "list",
            "label": "Mode",
            "options": ["continuous", "polled"],
            "default": "polled"
        },
        "poll_interval": {
            "type": "number",
            "label": "Poll Interval (s)",
            "default": 1.0,
            "condition": {"mode": "polled"} # Only show if mode is polled
        }
    }

    # Connection lost callback - can be set by parent thread
    on_connection_lost = None
    
    def __init__(self, port="COM3", baud_rate=9600, mode="continuous", poll_interval=1.0):
        """
        Initialize the Arduino interface
        
        Args:
            port: Serial port
            baud_rate: Baud rate
            mode: Operating mode ("continuous" or "polled")
            poll_interval: Polling interval in seconds
        """
        super().__init__(name="Arduino")
        self.port = port
        self.baud_rate = int(baud_rate) if baud_rate else 9600
        self.mode = mode
        self.poll_interval = float(poll_interval)
        self.serial = None
        self.last_poll_time = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 3  # Disconnect after this many consecutive errors
        self._discovered_sensors = set()

    @classmethod
    def get_output_keys(cls):
        """Return a list of available sensor names for this interface type.
        Note: For Arduino, this is dynamic and requires a connection.
        """
        return []

    def get_instance_output_keys(self):
        """Return a list of sensor names discovered during the current connection."""
        return sorted(list(self._discovered_sensors))
    
    @classmethod
    def get_ui_options(cls, field_name):
        """Provide dynamic options for the UI"""
        if field_name == "port":
            return cls.list_ports()
        return []
        
    def connect(self, wait_for_reset=True):
        """
        Connect to the Arduino device
        
        Args:
            wait_for_reset: If True, wait for Arduino to reset after connection.
                           Set to False for faster connection if Arduino doesn't reset.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            # Close any existing connection first
            if self.serial:
                try:
                    self.serial.close()
                except Exception:
                    pass
                self.serial = None
            
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=1,
                write_timeout=1  # Add write timeout to prevent blocking
            )
            
            # Wait for Arduino to reset if needed (DTR causes reset on most Arduinos)
            # Can be reduced or skipped if using Arduino with disabled auto-reset
            if wait_for_reset:
                # Use shorter wait - 1 second is usually enough for most Arduinos
                time.sleep(1.0)
            else:
                # Minimal wait to ensure port is ready
                time.sleep(0.1)
            
            # Clear any garbage in the buffer from reset
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            
            self.connected = True
            self._consecutive_errors = 0
            self.error_message = ""
            return True
            
        except serial.SerialException as e:
            err_str = str(e)
            if "FileNotFoundError" in err_str or "system cannot find the file specified" in err_str:
                self.error_message = f"Port {self.port} not found. Please check if the Arduino is connected and you selected the correct port."
            elif "PermissionError" in err_str or "Access is denied" in err_str:
                self.error_message = f"Access to {self.port} denied. The port might be in use by another program."
            else:
                self.error_message = f"Serial error: {err_str}"
            
            self.connected = False
            self.serial = None
            return False
        except Exception as e:
            self.error_message = f"Failed to connect: {str(e)}"
            self.connected = False
            self.serial = None
            return False
            
    def disconnect(self):
        """Disconnect from the Arduino device"""
        self.connected = False
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass  # Ignore errors during close
            self.serial = None
            
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        if not self.connected or self.serial is None:
            return False
        
        # Verify the serial port is actually open
        try:
            return self.serial.is_open
        except Exception:
            self.connected = False
            return False
    
    def _handle_serial_error(self, error):
        """
        Handle serial communication errors
        
        Args:
            error: The exception that occurred
            
        Returns:
            True if connection was lost and should stop, False otherwise
        """
        self._consecutive_errors += 1
        print(f"Arduino serial error ({self._consecutive_errors}/{self._max_consecutive_errors}): {error}")
        
        if self._consecutive_errors >= self._max_consecutive_errors:
            print("Arduino: Too many consecutive errors, marking as disconnected")
            self.connected = False
            self.error_message = f"Connection lost: {error}"
            
            # Notify parent if callback is set
            if self.on_connection_lost:
                try:
                    self.on_connection_lost(self.error_message)
                except Exception as e:
                    print(f"Error in connection_lost callback: {e}")
            
            return True
        return False
        
    def read_data(self):
        """
        Read data from the Arduino
        
        Returns:
            Dictionary with sensor values or None if failed
        """
        if not self.is_connected():
            return None
        
        try:
            # Handle polling mode
            if self.mode.lower() == "polled":
                return self._read_polled()
            else:
                return self._read_continuous()
                
        except serial.SerialException as e:
            if self._handle_serial_error(e):
                return None
            return None
        except OSError as e:
            # OSError can occur when device is unplugged
            if self._handle_serial_error(e):
                return None
            return None
        except Exception as e:
            print(f"Unexpected error reading from Arduino: {e}")
            return None
    
    def _read_polled(self):
        """Read data in polled mode - simplified logic"""
        current_time = time.time()
        
        # Check if it's time to poll
        if current_time - self.last_poll_time >= self.poll_interval:
            self.last_poll_time = current_time
            
            # Clear any old data in buffer before polling
            if self.serial.in_waiting > 0:
                self.serial.reset_input_buffer()
            
            # Send poll command
            self.serial.write(b'POLL\n')
            self.serial.flush()
            
            # Read response with timeout (already set in serial config)
            line = self.serial.readline().decode('utf-8', errors='replace').strip()
            
            if line:
                self._consecutive_errors = 0  # Reset error counter on successful read
                return self._parse_data(line)
        
        return None
    
    def _read_continuous(self):
        """Read data in continuous mode"""
        if self.serial.in_waiting > 0:
            line = self.serial.readline().decode('utf-8', errors='replace').strip()
            if line:
                self._consecutive_errors = 0  # Reset error counter on successful read
                return self._parse_data(line)
        return None
            
    def _parse_data(self, line):
        """Parse data line from Arduino into a dictionary"""
        data = {}
            
        # Split by semicolons for different sensors
        try:
            pairs = line.split(';')
            for pair in pairs:
                pair = pair.strip()
                if not pair:
                    continue
                if ":" in pair:
                    name, value = pair.split(':', 1)
                    name = name.strip()
                    value = value.strip()
                    # Track discovered sensor name
                    if name:
                        self._discovered_sensors.add(name)
                    # Try to convert to float if possible
                    try:
                        value = float(value)
                    except ValueError:
                        # Keep as string if not a number
                        pass
                    data[name] = value
            return data if data else None
        except Exception as e:
            print(f"Error parsing Arduino data: {e} - Line: {line}")
            return None
            
    def write_data(self, data):
        """
        Write data to the Arduino
        
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
                self.serial.write(data)
            # Flush the write buffer to ensure data is sent
            self.serial.flush()
            self._consecutive_errors = 0  # Reset error counter on successful write
            return True
            
        except serial.SerialException as e:
            self.error_message = f"Serial error writing data: {e}"
            self._handle_serial_error(e)
            return False
        except OSError as e:
            self.error_message = f"OS error writing data: {e}"
            self._handle_serial_error(e)
            return False
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
