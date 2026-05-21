"""
Arduino Master-Slave Interface

Handles communication with Arduino master-slave systems for collecting sensor data.
The master Arduino collects data from slave devices and sends it to this interface.
Data format from Arduino: SensorName1:value;SensorName2:value;...
"""

import time
import os
import threading
import queue
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from app.core.interfaces.arduino_interface import ArduinoInterface


class ArduinoMasterSlaveThread(QThread):
    """Thread for handling Arduino master-slave communication"""
    
    # Define signals for thread-safe communication
    data_received_signal = pyqtSignal(dict)  # Signal emitted when new data is received
    connection_status_signal = pyqtSignal(bool, str)  # For connection status updates
    error_signal = pyqtSignal(str)  # For error notifications
    connection_lost_signal = pyqtSignal(str)  # Signal when connection is unexpectedly lost
    
    # Thread termination timeout in milliseconds
    THREAD_STOP_TIMEOUT_MS = 3000
    
    def __init__(self, parent=None):
        """Initialize the Arduino master-slave interface thread"""
        super().__init__(parent)
        
        # Create Arduino interface
        self.arduino = ArduinoInterface()
        
        # Thread control - use threading.Event for thread-safe flag
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default (set = running)
        
        self.monitoring_only = False  # Flag to indicate monitoring mode (no CSV writing)
        self.mutex = QMutex()
        self._was_connected = False
        self._last_error = ""
        
        # Data collection settings
        self.port = "COM3"
        self.baud_rate = 9600
        self.poll_interval = 1.0  # Default polling interval in seconds
        self.auto_reconnect = True  # Enable auto-reconnect by default
        self._last_reconnect_attempt = 0
        self._reconnect_interval = 5.0  # seconds
        
        # Data buffer
        self.data_queue = queue.Queue(maxsize=100)  # Queue for thread-safe data access
        self._dropped_data_count = 0  # Counter for dropped data packets
        
        # Thread-safe data access
        self.latest_data = {}  # Latest data received
        self.data_mutex = QMutex()  # Mutex for thread-safe access to latest_data
        
    @property
    def running(self):
        """Check if thread should be running (for backwards compatibility)"""
        return not self._stop_event.is_set()
    
    @running.setter
    def running(self, value):
        """Set running state (for backwards compatibility)"""
        if value:
            self._stop_event.clear()
        else:
            self._stop_event.set()
        
    @property
    def paused(self):
        """Check if thread is paused"""
        return not self._pause_event.is_set()
    
    @paused.setter
    def paused(self, value):
        """Set paused state"""
        if value:
            self._pause_event.clear()
        else:
            self._pause_event.set()
        
    def set_poll_interval(self, interval):
        """Set the polling interval in seconds"""
        self.poll_interval = float(interval)
        if self.arduino:
            self.arduino.poll_interval = self.poll_interval
        
    def set_output_directory(self, output_dir):
        """Set the output directory (used by other parts if needed, but not for CSV here)"""
        # Create directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    
    def _on_connection_lost(self, error_message):
        """Callback when Arduino connection is lost"""
        print(f"ArduinoMasterSlaveThread: Connection lost - {error_message}")
        self.connection_lost_signal.emit(error_message)
        self.connection_status_signal.emit(False, f"Connection lost: {error_message}")
            
    def connect(self, port=None, baud_rate=None):
        """Connect to the Arduino master"""
        self._last_error = ""
        try:
            # If no port/baud provided, use existing attributes if they exist
            if port is None:
                port = getattr(self, "port", "COM3")
            else:
                self.port = port
                
            if baud_rate is None:
                baud_rate = getattr(self, "baud_rate", 9600)
            else:
                self.baud_rate = baud_rate

            print(f"ArduinoMasterSlaveThread: Attempting to connect to Arduino on {port} with baud rate {baud_rate}")
            
            # If already connected, check if it's the same port/baud. If not, disconnect first.
            if self.is_connected():
                # Ensure baud_rate is compared as integer
                try:
                    current_baud = int(self.arduino.baud_rate)
                    target_baud = int(baud_rate)
                except (ValueError, TypeError):
                    current_baud = self.arduino.baud_rate
                    target_baud = baud_rate
                    
                if str(self.arduino.port) == str(port) and current_baud == target_baud:
                    print("ArduinoMasterSlaveThread: Already connected to this device.")
                    return True
                else:
                    print(f"ArduinoMasterSlaveThread: Already connected to different device ({self.arduino.port} @ {self.arduino.baud_rate}), disconnecting first...")
                    self.disconnect()
            
            # Create new Arduino interface with settings
            self.arduino = ArduinoInterface(
                port=port, 
                baud_rate=baud_rate, 
                mode="polled", 
                poll_interval=self.poll_interval
            )
            
            # Set connection lost callback
            self.arduino.on_connection_lost = self._on_connection_lost
            
            success = self.arduino.connect()
            if success:
                print(f"ArduinoMasterSlaveThread: Successfully connected to Arduino on {port}")
                self.connection_status_signal.emit(True, f"Connected to Arduino on {port}")
                self._was_connected = True
                
                # Start the thread if not already running
                if not self.isRunning():
                    print("ArduinoMasterSlaveThread: Starting thread for monitoring")
                    self._stop_event.clear()
                    self._pause_event.set()  # Not paused
                    self.monitoring_only = True  # Flag to indicate monitoring mode only
                    self.start()
                
                return True
            else:
                self._last_error = self.arduino.get_error()
                print(f"ArduinoMasterSlaveThread: Failed to connect to Arduino: {self._last_error}")
                self.connection_status_signal.emit(False, self._last_error)
                return False
                
        except Exception as e:
            self._last_error = f"Failed to connect to Arduino: {str(e)}"
            print(f"ArduinoMasterSlaveThread: Exception during connect: {self._last_error}")
            self.connection_status_signal.emit(False, self._last_error)
            return False
            
    def disconnect(self):
        """Disconnect from the Arduino master"""
        if self.arduino:
            print("ArduinoMasterSlaveThread: Disconnecting from Arduino")
            
            # Signal thread to stop
            self._stop_event.set()
            self._pause_event.set()  # Ensure not blocked on pause
            
            # Wait for thread to finish with timeout to avoid deadlock
            if self.isRunning():
                print("ArduinoMasterSlaveThread: Waiting for thread to stop...")
                if not self.wait(self.THREAD_STOP_TIMEOUT_MS):
                    print("ArduinoMasterSlaveThread: Thread did not stop in time, forcing termination")
                    self.terminate()
                    self.wait(1000)  # Brief wait after termination
            
            # Now disconnect the Arduino
            self.arduino.disconnect()
            print("ArduinoMasterSlaveThread: Emitting disconnection status")
            self.connection_status_signal.emit(False, "Disconnected from Arduino")
            
            # Clear latest data (thread-safe)
            with QMutexLocker(self.data_mutex):
                self.latest_data = {}
                
            # Log dropped data if any
            if self._dropped_data_count > 0:
                print(f"ArduinoMasterSlaveThread: Total data packets dropped due to queue overflow: {self._dropped_data_count}")
                self._dropped_data_count = 0
        else:
            print("ArduinoMasterSlaveThread: disconnect called but no Arduino interface exists")
            
    def is_connected(self):
        """Check if connected to Arduino"""
        return self.arduino and self.arduino.is_connected()
        
    @property
    def error_message(self):
        """Get the last error message from the interface"""
        if self._last_error:
            return self._last_error
        if self.arduino:
            return self.arduino.get_error()
        return ""
        
    def start_data_collection(self, run_dir):
        """Start collecting data from Arduino (no CSV writing here)"""
        if not self.is_connected():
            self.error_signal.emit("Cannot start data collection - not connected to Arduino")
            return False
        
        with QMutexLocker(self.mutex):
            # Switch from monitoring mode to full data collection
            self.monitoring_only = False
        
        # Start the thread if not already running
        if not self.isRunning():
            self._stop_event.clear()
            self._pause_event.set()  # Not paused
            self.start()
        
        return True
        
    def stop_data_collection(self):
        """Stop data collection thread"""
        self._stop_event.set()
        
        # Wait for thread to finish with timeout
        if not self.wait(self.THREAD_STOP_TIMEOUT_MS):
            print("ArduinoMasterSlaveThread: Thread did not stop in time during stop_data_collection")
        
    def pause_data_collection(self):
        """Pause data collection"""
        self._pause_event.clear()
        
    def resume_data_collection(self):
        """Resume data collection"""
        self._pause_event.set()
        
    def get_available_sensor_names(self):
        """
        Get a list of all sensor names discovered since connection.
        
        Returns:
            List of sensor names
        """
        # First try to get from the underlying interface's discovery set
        if self.arduino and hasattr(self.arduino, 'get_instance_output_keys'):
            return self.arduino.get_instance_output_keys()
            
        # Fallback to latest data keys
        with QMutexLocker(self.data_mutex):
            return list(self.latest_data.keys()) if self.latest_data else []
            
    def get_latest_data(self):
        """
        Get the latest data from the Arduino
        
        Returns:
            Dictionary with sensor values or empty dict if no data
        """
        with QMutexLocker(self.data_mutex):
            return self.latest_data.copy()
        
    def run(self):
        """Thread main method - runs when thread.start() is called"""
        print("Arduino master-slave thread started")
        
        while not self._stop_event.is_set():
            loop_start = time.time()
            
            try:
                # Check if thread is paused - wait with timeout so we can check stop event
                if not self._pause_event.wait(timeout=0.1):
                    continue
                
                # Check stop event after pause wait
                if self._stop_event.is_set():
                    break
                
                # Check if still connected
                if not self.is_connected():
                    if self._was_connected:
                        print("Arduino master-slave thread: Connection lost!")
                        self.connection_status_signal.emit(False, "Connection lost")
                        self._was_connected = False

                    if self.auto_reconnect:
                        current_time = time.time()
                        if current_time - self._last_reconnect_attempt >= self._reconnect_interval:
                            self._last_reconnect_attempt = current_time
                            print(f"Arduino master-slave thread: Connection lost, attempting reconnect to {self.arduino.port}...")
                            if self.arduino.connect():
                                print("Arduino master-slave thread: Reconnected successfully")
                                self.connection_status_signal.emit(True, f"Reconnected to Arduino on {self.arduino.port}")
                            else:
                                print("Arduino master-slave thread: Reconnect failed")
                        
                        # Wait a bit before next check/attempt
                        self._stop_event.wait(timeout=1.0)
                        continue
                    else:
                        print("Arduino master-slave thread: Connection lost, stopping")
                        break
                
                # Get monitoring mode flag (thread-safe)
                with QMutexLocker(self.mutex):
                    is_monitoring_only = self.monitoring_only
                
                # Read data from Arduino
                data = self.arduino.read_data()
                
                if data:
                    # Update latest data (thread-safe)
                    with QMutexLocker(self.data_mutex):
                        self.latest_data = data.copy()
                    
                    # Add timestamp to data
                    data['timestamp'] = time.time()
                    
                    # Emit signal with the data
                    self.data_received_signal.emit(data)
                    
                    # Only handle data buffer in full data collection mode
                    if not is_monitoring_only:
                        # Put data in queue for other parts of the application to access
                        try:
                            self.data_queue.put_nowait(data)
                        except queue.Full:
                            # Queue is full, remove oldest item and log
                            self._dropped_data_count += 1
                            if self._dropped_data_count == 1 or self._dropped_data_count % 100 == 0:
                                print(f"ArduinoMasterSlaveThread: Queue full, dropping data (total dropped: {self._dropped_data_count})")
                            try:
                                self.data_queue.get_nowait()
                                self.data_queue.put_nowait(data)
                            except (queue.Empty, queue.Full):
                                pass
                
                # Sleep for polling interval (adjusted to account for processing time)
                elapsed = time.time() - loop_start
                remaining = self.poll_interval - elapsed
                if remaining > 0:
                    # Use Event.wait() instead of time.sleep() so we can be interrupted
                    self._stop_event.wait(timeout=remaining)
                    
            except Exception as e:
                error_msg = f"Error in Arduino thread: {str(e)}"
                print(error_msg)
                self.error_signal.emit(error_msg)
                
                # Check if this is a connection error
                if not self.is_connected():
                    print("Arduino master-slave thread: Connection lost after error, stopping")
                    break
                    
                # Sleep longer on error to avoid high CPU, but use Event.wait()
                self._stop_event.wait(timeout=1.0)
        
        print("Arduino master-slave thread stopped")
        
    @staticmethod
    def list_ports():
        """
        List available serial ports
        
        Returns:
            List of available ports
        """
        return ArduinoInterface.list_ports()
    
    def send_command(self, command, device=None, value=None):
        """
        Send a command to the Arduino master
        
        Args:
            command: Command string to send (e.g. "LED", "MOTOR", "RELAY")
            device: Device identifier (e.g. device number or name)
            value: Value to set (e.g. "ON", "OFF", "100", etc.)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            self.error_signal.emit("Cannot send command - not connected to Arduino")
            return False
            
        try:
            # Format the command based on parameters
            cmd_str = command
            if device is not None:
                cmd_str += f":{device}"
            if value is not None:
                cmd_str += f"={value}"
            
            # Add termination character
            cmd_str += ";\n"
            
            # Send the command
            success = self.arduino.write_data(cmd_str)
            
            if success:
                self.log(f"Sent command to Arduino: {cmd_str.strip()}")
            else:
                error_msg = f"Failed to send command: {self.arduino.get_error()}"
                self.error_signal.emit(error_msg)
                
            return success
            
        except Exception as e:
            error_msg = f"Error sending command to Arduino: {str(e)}"
            self.error_signal.emit(error_msg)
            return False
    
    def log(self, message, level="INFO"):
        """Log a message"""
        # Use error signal to propagate logs to the main window
        if level == "ERROR":
            self.error_signal.emit(message)
        else:
            print(f"[ArduinoThread] {message}")
