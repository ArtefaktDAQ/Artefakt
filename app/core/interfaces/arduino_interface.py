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
        self.baud_rate = baud_rate
        self.mode = mode
        self.poll_interval = float(poll_interval)
        self.serial = None
        self.last_poll_time = 0
        self.last_data_time = 0  # Track the last time data was actually processed
        
    def connect(self):
        """
        Connect to the Arduino device
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            self.serial = serial.Serial(self.port, self.baud_rate, timeout=1)
            time.sleep(2)  # Wait for Arduino to reset
            self.connected = True
            self.error_message = ""
            return True
        except Exception as e:
            self.error_message = f"Failed to connect to Arduino: {e}"
            self.connected = False
            return False
            
    def disconnect(self):
        """Disconnect from the Arduino device"""
        if self.serial and self.connected:
            self.serial.close()
            self.serial = None
            self.connected = False
            
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        return self.connected and self.serial is not None
        
    def read_data(self):
        """
        Read data from the Arduino
        
        Returns:
            Dictionary with sensor values or None if failed
        """
        if not self.is_connected():
            return None
            
        # Handle polling mode
        if self.mode.lower() == "polled":
            current_time = time.time()
            
            # Read any data that might be in the buffer
            try:
                if self.serial.in_waiting > 0:
                    line = self.serial.readline().decode('utf-8', errors='replace').strip()
                    
                    # Only process the data if enough time has passed since last processing
                    # This effectively throttles the data to match the poll interval
                    if current_time - self.last_data_time >= self.poll_interval:
                        self.last_data_time = current_time
                        
                        # Actually poll at the specified interval regardless of incoming data
                        if current_time - self.last_poll_time >= self.poll_interval:
                            self.last_poll_time = current_time
                            # Send poll command
                            self.serial.write(b'POLL\n')
                        
                        # Only process data if we have a valid line
                        if line:
                            return self._parse_data(line)
                    return None
                else:
                    # If no data is waiting but it's time to poll, send the command
                    if current_time - self.last_poll_time >= self.poll_interval:
                        self.last_poll_time = current_time
                        # Send poll command
                        self.serial.write(b'POLL\n')
                        # Try to read response after sending command
                        time.sleep(0.1)  # Small delay to allow Arduino to respond
                        line = self.serial.readline().decode('utf-8', errors='replace').strip()
                        if line:
                            self.last_data_time = current_time
                            return self._parse_data(line)
            except Exception as e:
                print(f"Error reading from Arduino: {e}")
                return None
            
            return None
            
        # Continuous mode (read whatever is available)
        try:
            if self.serial.in_waiting > 0:
                line = self.serial.readline().decode('utf-8', errors='replace').strip()
                if line:
                    return self._parse_data(line)
            return None
        except Exception as e:
            print(f"Error reading from Arduino: {e}")
            return None
            
    def _parse_data(self, line):
        """Parse data line from Arduino into a dictionary"""
        # Parse data
        data = {}
            
        # Split by semicolons for different sensors
        try:
            pairs = line.split(';')
            for pair in pairs:
                if ":" in pair:
                    name, value = pair.split(':', 1)
                    # Try to convert to float if possible
                    try:
                        value = float(value)
                    except ValueError:
                        # Keep as string if not a number
                        pass
                    data[name] = value
            return data
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