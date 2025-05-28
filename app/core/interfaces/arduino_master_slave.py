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
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from app.core.interfaces.arduino_interface import ArduinoInterface


class ArduinoMasterSlaveThread(QThread):
    """Thread for handling Arduino master-slave communication"""
    
    # Define signals for thread-safe communication
    data_received_signal = pyqtSignal(dict)  # Signal emitted when new data is received
    connection_status_signal = pyqtSignal(bool, str)  # For connection status updates
    error_signal = pyqtSignal(str)  # For error notifications
    
    def __init__(self, parent=None):
        """Initialize the Arduino master-slave interface thread"""
        super().__init__(parent)
        
        # Create Arduino interface
        self.arduino = ArduinoInterface()
        
        # Thread control
        self.running = False
        self.paused = False
        self.monitoring_only = False  # Flag to indicate monitoring mode (no CSV writing)
        self.mutex = QMutex()
        
        # Data collection settings
        self.poll_interval = 1.0  # Default polling interval in seconds
        
        # Data buffer
        self.data_queue = queue.Queue(maxsize=100)  # Queue for thread-safe data access
        
        # Thread-safe data access
        self.latest_data = {}  # Latest data received
        self.data_mutex = QMutex()  # Mutex for thread-safe access to latest_data
        
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
            
    def connect(self, port, baud_rate=9600):
        """Connect to the Arduino master"""
        try:
            print(f"ArduinoMasterSlaveThread: Attempting to connect to Arduino on {port} with baud rate {baud_rate}")
            self.arduino = ArduinoInterface(port=port, baud_rate=baud_rate, 
                                          mode="polled", poll_interval=self.poll_interval)
            
            success = self.arduino.connect()
            if success:
                print(f"ArduinoMasterSlaveThread: Successfully connected to Arduino on {port}")
                self.connection_status_signal.emit(True, f"Connected to Arduino on {port}")
                
                # Start a basic monitoring thread to receive sensor data
                # (without CSV writing or full data collection)
                if not self.running:
                    self.running = True
                    self.paused = False
                    self.monitoring_only = True  # Flag to indicate monitoring mode only
                    self.start()
                
                return True
            else:
                error_msg = self.arduino.get_error()
                print(f"ArduinoMasterSlaveThread: Failed to connect to Arduino: {error_msg}")
                self.connection_status_signal.emit(False, error_msg)
                return False
        except Exception as e:
            error_msg = f"Failed to connect to Arduino: {str(e)}"
            print(f"ArduinoMasterSlaveThread: Exception during connect: {error_msg}")
            self.connection_status_signal.emit(False, error_msg)
            return False
            
    def disconnect(self):
        """Disconnect from the Arduino master"""
        if self.arduino:
            print("ArduinoMasterSlaveThread: Disconnecting from Arduino")
            # Stop the thread if running
            if self.running:
                self.running = False
                self.wait()  # Wait for thread to finish
                
            self.arduino.disconnect()
            print("ArduinoMasterSlaveThread: Emitting disconnection status")
            self.connection_status_signal.emit(False, "Disconnected from Arduino")
            
            # Clear latest data
            self.data_mutex.lock()
            self.latest_data = {}
            self.data_mutex.unlock()
        else:
            print("ArduinoMasterSlaveThread: disconnect called but no Arduino interface exists")
            
    def is_connected(self):
        """Check if connected to Arduino"""
        return self.arduino and self.arduino.is_connected()
        
    def start_data_collection(self, run_dir):
        """Start collecting data from Arduino (no CSV writing here)"""
        if not self.is_connected():
            self.error_signal.emit("Cannot start data collection - not connected to Arduino")
            return False
            
        self.mutex.lock()
        # Switch from monitoring mode to full data collection
        self.monitoring_only = False
        
        # Check if thread is already running from monitoring mode
        already_running = self.running
        self.mutex.unlock()
        
        # Start the thread if not already running
        if not already_running:
            self.running = True
            self.paused = False
            self.start()
        
        return True
        
    def stop_data_collection(self):
        """Stop data collection thread"""
        self.running = False
        
        # Wait for thread to finish
        self.wait()
        
    def pause_data_collection(self):
        """Pause data collection"""
        self.mutex.lock()
        self.paused = True
        self.mutex.unlock()
        
    def resume_data_collection(self):
        """Resume data collection"""
        self.mutex.lock()
        self.paused = False
        self.mutex.unlock()
        
    def get_available_sensor_names(self):
        """
        Get a list of available sensor names from the current data
        
        Returns:
            List of sensor names
        """
        self.data_mutex.lock()
        try:
            # Return the keys of the latest data dictionary
            return list(self.latest_data.keys()) if self.latest_data else []
        finally:
            self.data_mutex.unlock()
            
    def get_latest_data(self):
        """
        Get the latest data from the Arduino
        
        Returns:
            Dictionary with sensor values or empty dict if no data
        """
        self.data_mutex.lock()
        try:
            return self.latest_data.copy()
        finally:
            self.data_mutex.unlock()
        
    def run(self):
        """Thread main method - runs when thread.start() is called"""
        print("Arduino master-slave thread started")
        self.running = True
        
        while self.running:
            try:
                # Check if thread is paused
                self.mutex.lock()
                is_paused = self.paused
                is_monitoring_only = self.monitoring_only
                self.mutex.unlock()
                
                if is_paused:
                    time.sleep(0.1)
                    continue
                
                # Read data from Arduino
                data = self.arduino.read_data()
                
                if data:
                    # Update latest data (thread-safe)
                    self.data_mutex.lock()
                    self.latest_data = data
                    self.data_mutex.unlock()
                    
                    # Add timestamp to data
                    data['timestamp'] = time.time()
                    
                    # Emit signal with the data
                    self.data_received_signal.emit(data)
                    
                    # Only handle CSV and data buffer in full data collection mode
                    if not is_monitoring_only:
                        # Put data in queue for other parts of the application to access
                        try:
                            self.data_queue.put_nowait(data)
                        except queue.Full:
                            # Queue is full, remove oldest item
                            try:
                                self.data_queue.get_nowait()
                                self.data_queue.put_nowait(data)
                            except (queue.Empty, queue.Full):
                                pass
                
                # Sleep for polling interval (adjusted to account for processing time)
                time.sleep(max(0.01, self.poll_interval - 0.01))
                
            except Exception as e:
                error_msg = f"Error in Arduino thread: {str(e)}"
                print(error_msg)
                self.error_signal.emit(error_msg)
                time.sleep(1.0)  # Sleep longer on error to avoid high CPU
        
        print("Arduino master-slave thread stopped")
        
    @staticmethod
    def list_ports():
        """
        List available serial ports
        
        Returns:
            List of available ports
        """
        return ArduinoInterface.list_ports()

    def stop_processing_thread(self):
        """Stop the frame processing thread"""
        self.processing_running = False
        if self.processing_thread:
            self.processing_thread.join()
    
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