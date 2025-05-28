"""
Data Collection Controller

Manages data collection from various hardware interfaces.
"""

import os
import time
import threading
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer, QMutex
import queue
import collections # Import collections for deque
import numpy as np
import csv # <-- Add import for csv module
import glob
import json

from app.core.interfaces.arduino_master_slave import ArduinoMasterSlaveThread
from app.core.interfaces.other_serial_interface import OtherSerialThread, SerialSequence, SendCommandStep, WaitStep, ReadResponseStep, ParseValueStep, PublishValueStep
from app.core.interfaces.labjack_data_thread import LabJackDataThread

# Import LabJackInterface from the app.core.interfaces package
try:
    from app.core.interfaces.labjack_interface import LabJackInterface
except ImportError as e:
    print(f"ERROR: Failed to import LabJackInterface in DataCollectionController: {e}")
    LabJackInterface = None

class DataCollectionController(QObject):
    """
    Controller for managing data collection from hardware interfaces
    """
    
    # Define signals
    data_received_signal = pyqtSignal(dict)  # Signal for new data from any interface
    combined_data_signal = pyqtSignal(dict)  # Signal for combined data from all interfaces
    status_update_signal = pyqtSignal(str, str)  # Signal for status updates (message, level)
    interface_status_signal = pyqtSignal(str, bool)  # Signal for interface connection status updates
    
    def __init__(self, main_window=None):
        """Initialize the data collection controller"""
        super().__init__()
        
        # Store reference to main window
        self.main_window = main_window
        
        # Initialize interfaces dictionary
        self.interfaces = {
            'arduino': {'connected': False},
            'labjack': {'connected': False},
            'other_serial': {'connected': False}
        }
        
        # Add a flag to track manual disconnection of other serial devices
        self.other_serial_manually_disconnected = False
        
        self.main_window = main_window
        
        # Hardware interfaces
        self.interface_threads = {}  # Dictionary of interface threads
        
        # Data collection state
        self.collecting_data = False
        self.run_directory = ""
        self.sampling_rate = 10  # Default global sampling rate (Hz)
        
        # Combined data buffers
        self.combined_data = {}  # Dictionary to store latest data from all interfaces
        self.combined_data_mutex = QMutex()  # Mutex for thread-safe access to combined data
        
        # Add buffer for historical data
        self.historical_buffer = collections.defaultdict(lambda: collections.deque(maxlen=10000)) # Store last 10000 points per sensor
        self.historical_buffer_mutex = QMutex()
        
        # --- CSV Writing Attributes ---
        self.csv_file = None
        self.csv_writer = None
        self.csv_header = []
        self.csv_filename = ""
        # ---------------------------
        
        # Setup Arduino interface
        self.arduino_thread = ArduinoMasterSlaveThread()
        self.arduino_thread.data_received_signal.connect(self.handle_arduino_data)
        self.arduino_thread.connection_status_signal.connect(self.handle_arduino_status)
        self.arduino_thread.error_signal.connect(self.handle_arduino_error)
        
        # Setup Other Serial interface
        self.other_serial_thread = OtherSerialThread()
        self.other_serial_thread.data_received_signal.connect(self.handle_other_serial_data)
        self.other_serial_thread.connection_status_signal.connect(self.handle_other_serial_status)
        self.other_serial_thread.error_signal.connect(self.handle_other_serial_error)
        
        # --- Setup LabJack interface using the new thread ---
        self.labjack_thread = LabJackDataThread(sampling_rate=self.sampling_rate)
        self.labjack_thread.data_received_signal.connect(self.handle_labjack_data)
        self.labjack_thread.connection_status_signal.connect(self.handle_labjack_status) # Need to create this handler
        self.labjack_thread.error_signal.connect(self.handle_labjack_error) # Need to create this handler
        # --------------------------------------------------
        
        # Create a timer for combined data emission
        self.combined_data_timer = QTimer()
        self.combined_data_timer.timeout.connect(self.emit_combined_data)
        
        # Create a timer for UI updates 
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_sensor_display)
        self.update_timer.setInterval(500)  # Update UI every 500ms
        
    def initialize(self):
        """Initialize the controller"""
        print("DEBUG: DataCollectionController.initialize() called")
        self.log("Data collection controller initialized")
        
        # Do not start timers automatically to prevent data collection at program start
        # Timers will be started when Start button is clicked
        print("DEBUG: Timers will be started on Start button click")
        self.log("Timers for data collection will start on user command")
        
        # Check if self.start_time is initialized
        if not hasattr(self, 'start_time'):
            self.start_time = time.time()
            print(f"DEBUG: Initialized start_time to {self.start_time}")
            
        # Load and store historical data from the last run's CSV file if available
        self.csv_historical_data = self.read_historical_data_from_csv()
        
        # Display historical data from the last run's CSV file if available
        if self.main_window and hasattr(self.main_window, 'graph_controller'):
            if self.csv_historical_data:
                print("DEBUG: Loading historical data from CSV at program start")
                print(f"DEBUG: Historical data keys: {list(self.csv_historical_data.keys())}")
                for key, data in self.csv_historical_data.items():
                    print(f"DEBUG: Sensor {key} has {len(data['time'])} data points")
                self.log("Loading historical data from CSV for display")
                try:
                    self.main_window.graph_controller.plot_historical_data(self.csv_historical_data)
                    print("DEBUG: Successfully plotted historical data from CSV")
                    self.log("Historical data plotted successfully")
                except AttributeError:
                    print("DEBUG: plot_historical_data method not found in graph_controller")
                    self.log("Could not display historical data: plot_historical_data method not available", "WARNING")
                except Exception as e:
                    print(f"DEBUG: Error plotting historical data: {str(e)}")
                    self.log(f"Error plotting historical data: {str(e)}", "ERROR")
            else:
                print("DEBUG: No historical CSV data to display at program start")
                self.log("No historical CSV data available to display")
        
        # Verify the graph controller state if available
        if self.main_window and hasattr(self.main_window, 'graph_controller'):
            gc = self.main_window.graph_controller
            print(f"DEBUG: Graph controller found: live_plotting_active={gc.live_plotting_active}, dashboard_start_time={gc.dashboard_start_time}")
        
    def shutdown(self):
        """Shut down the controller and all interfaces"""
        self.log("Shutting down data collection controller")
        
        # Stop timers
        self.update_timer.stop()
        self.combined_data_timer.stop()
        
        # Stop data collection if running
        if self.collecting_data:
            self.stop_data_collection()
            
        # Disconnect all interfaces
        self.disconnect_all_interfaces()
            
    def connect_arduino(self, port, baud_rate=9600, poll_interval=None):
        """
        Connect to Arduino device
        
        Args:
            port: Serial port
            baud_rate: Baud rate
            poll_interval: Polling interval in seconds (deprecated, uses global sampling rate if None)
            
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            # Use global sampling rate if poll_interval is None
            if poll_interval is None:
                # Convert Hz to seconds
                poll_interval = 1.0 / self.sampling_rate
            
            # Set Arduino parameters
            self.arduino_thread.set_poll_interval(poll_interval)
            
            # Connect to Arduino without starting data collection
            success = self.arduino_thread.connect(port, baud_rate)
            
            if success:
                self.log(f"Connected to Arduino on {port}")
                # Add to interfaces dictionary
                self.interfaces['arduino'] = {
                    'type': 'arduino',
                    'port': port,
                    'baud_rate': baud_rate,
                    'poll_interval': poll_interval,
                    'connected': True
                }
                print(f"SUCCESS! Emitting interface_status_signal('arduino', True)")
                self.interface_status_signal.emit('arduino', True)
                
                # Set Arduino thread to monitoring-only mode until data collection starts
                self.arduino_thread.monitoring_only = True
                self.log("Arduino thread set to monitoring-only mode until data collection starts")
                
                # Direct UI update via the new method if available
                if self.main_window:
                    if hasattr(self.main_window, 'update_arduino_connected_status'):
                        print("Using direct update_arduino_connected_status method")
                        self.main_window.update_arduino_connected_status(True)
                    elif hasattr(self.main_window, 'update_device_connection_status_ui'):
                        print("Using update_device_connection_status_ui method")
                        self.main_window.update_device_connection_status_ui('arduino', True)
                        
                    # Force start Arduino monitoring in the sensor controller only if data collection is active
                    if hasattr(self.main_window, 'sensor_controller') and self.collecting_data:
                        print("Forcing sensor controller to start Arduino monitoring")
                        if hasattr(self.main_window.sensor_controller, '_start_arduino_monitoring'):
                            self.main_window.sensor_controller._start_arduino_monitoring()
                            # Force an immediate update of Arduino sensor values
                            if hasattr(self.main_window.sensor_controller, 'force_update_arduino_status'):
                                self.main_window.sensor_controller.force_update_arduino_status()
                        else:
                            print("ERROR: sensor_controller does not have _start_arduino_monitoring method")
                    else:
                        print("Data collection not active, skipping Arduino monitoring start")
                return success
            else:
                self.log(f"Failed to connect to Arduino on {port}", "ERROR")
                print(f"FAILURE: Emitting interface_status_signal('arduino', False)")
                self.interface_status_signal.emit('arduino', False)
                
                # Update UI for failed connection
                if self.main_window and hasattr(self.main_window, 'update_arduino_connected_status'):
                    self.main_window.update_arduino_connected_status(False)
                
            return success
            
        except Exception as e:
            self.log(f"Error connecting to Arduino: {str(e)}", "ERROR")
            print(f"EXCEPTION: Emitting interface_status_signal('arduino', False) due to exception: {str(e)}")
            self.interface_status_signal.emit('arduino', False)
            
            # Update UI for failed connection
            if self.main_window and hasattr(self.main_window, 'update_arduino_connected_status'):
                self.main_window.update_arduino_connected_status(False)
            
            return False
            
    def disconnect_arduino(self):
        """Disconnect from Arduino device"""
        try:
            if 'arduino' in self.interfaces:
                # Stop data collection if running
                if self.collecting_data and self.arduino_thread.running:
                    self.arduino_thread.stop_data_collection()
                
                # Disconnect from Arduino
                self.arduino_thread.disconnect()
                
                # Update interface status
                self.interfaces['arduino']['connected'] = False
                print("Emitting arduino disconnected signal")
                self.interface_status_signal.emit('arduino', False)
                
                # Direct UI update
                if self.main_window and hasattr(self.main_window, 'update_arduino_connected_status'):
                    print("Using direct update_arduino_connected_status method for disconnect")
                    self.main_window.update_arduino_connected_status(False)
                
                self.log("Disconnected from Arduino")
                
        except Exception as e:
            self.log(f"Error disconnecting from Arduino: {str(e)}", "ERROR")
            
    def connect_other_serial(self, port, baud_rate=9600, data_bits=8, parity="None", 
                            stop_bits=1, poll_interval=1.0, sequence=None):
        """
        Connect to Other Serial device
        
        Args:
            port: Serial port
            baud_rate: Baud rate
            data_bits: Data bits
            parity: Parity setting
            stop_bits: Stop bits
            poll_interval: Polling interval in seconds
            sequence: SerialSequence to execute
            
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            # Check if manually disconnected and this is an auto-reconnect attempt
            if self.other_serial_manually_disconnected and not getattr(self, '_explicit_reconnect', False):
                print("DEBUG connect_other_serial: Skipping auto-reconnect because of manual disconnect")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log("Skipping auto-reconnect of Other Serial - manually disconnected", "INFO")
                return False
            
            # Reset the manual disconnect flag if this is an explicit reconnect
            if getattr(self, '_explicit_reconnect', False):
                self.other_serial_manually_disconnected = False
                self._explicit_reconnect = False
            
            # Debug: Print sequence details before connecting
            if sequence is not None:
                steps = getattr(sequence, 'steps', None) or getattr(sequence, 'actions', None)
                print(f"DEBUG connect_other_serial: Sequence to be used: {getattr(sequence, 'name', 'Unnamed')}, steps: {steps}")
                if steps is not None:
                    print(f"DEBUG connect_other_serial: Number of steps: {len(steps)}")
                else:
                    print("DEBUG connect_other_serial: Sequence has no steps or actions attribute!")
            else:
                print("DEBUG connect_other_serial: No sequence provided!")
            
            # Disconnect if already connected
            if 'other_serial' in self.interfaces and self.interfaces['other_serial']['connected']:
                self.other_serial_thread.disconnect()
                
            # Update the thread's poll interval
            self.other_serial_thread.poll_interval = poll_interval
            
            # Connect to the device without starting data collection
            success = self.other_serial_thread.connect(
                port=port,
                baud_rate=baud_rate,
                data_bits=data_bits,
                parity=parity,
                stop_bits=stop_bits,
                poll_interval=poll_interval,
                sequence=sequence
            )
            
            if success:
                # Create or update the interface entry
                self.interfaces['other_serial'] = {
                    'type': 'other_serial',
                    'connected': True,
                    'port': port,
                    'baud_rate': baud_rate,
                    'data_bits': data_bits,
                    'parity': parity,
                    'stop_bits': stop_bits,
                    'poll_interval': poll_interval
                }
                
                # Explicitly emit connection status to update UI
                self.interface_status_signal.emit('other', True)
                
                # Direct UI update
                if self.main_window:
                    if hasattr(self.main_window, 'update_device_connection_status_ui'):
                        print(f"Direct UI update: update_device_connection_status_ui('other', True)")
                        self.main_window.update_device_connection_status_ui('other', True)
                    elif hasattr(self.main_window, 'update_other_connected_status'):
                        print(f"Direct UI update: update_other_connected_status(True)")
                        self.main_window.update_other_connected_status(True)
                
                self.log(f"Connected to serial device on port {port}")
                return True
            else:
                self.log(f"Failed to connect to serial device on port {port}", "ERROR")
                
                # Explicitly set connected to False in case it was previously True
                if 'other_serial' in self.interfaces:
                    self.interfaces['other_serial']['connected'] = False
                    
                # Emit connection status to update UI
                self.interface_status_signal.emit('other', False)
                
                # Direct UI update for failed connection
                if self.main_window:
                    if hasattr(self.main_window, 'update_device_connection_status_ui'):
                        self.main_window.update_device_connection_status_ui('other', False)
                    elif hasattr(self.main_window, 'update_other_connected_status'):
                        self.main_window.update_other_connected_status(False)
                        
                return False
                
        except Exception as e:
            self.log(f"Error connecting to serial device: {str(e)}", "ERROR")
            
            # Explicitly set connected to False in case of error
            if 'other_serial' in self.interfaces:
                self.interfaces['other_serial']['connected'] = False
                
            # Emit connection status to update UI
            self.interface_status_signal.emit('other', False)
            
            # Direct UI update for connection error
            if self.main_window:
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('other', False)
                elif hasattr(self.main_window, 'update_other_connected_status'):
                    self.main_window.update_other_connected_status(False)
                    
            return False
            
    def disconnect_other_serial(self):
        """Disconnect from Other Serial device"""
        try:
            if 'other_serial' in self.interfaces and self.interfaces['other_serial']['connected']:
                self.other_serial_thread.disconnect()
                self.interfaces['other_serial']['connected'] = False
                
                # Emit connection status to update UI
                self.interface_status_signal.emit('other', False)
                
                # Direct UI update for disconnection
                if self.main_window:
                    if hasattr(self.main_window, 'update_device_connection_status_ui'):
                        self.main_window.update_device_connection_status_ui('other', False)
                    elif hasattr(self.main_window, 'update_other_connected_status'):
                        self.main_window.update_other_connected_status(False)
                        
                # Set all OtherSerial sensor values to None
                if hasattr(self.main_window, 'sensor_controller'):
                    for sensor in self.main_window.sensor_controller.sensors:
                        if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                            # Set current_value to None so it displays as "--"
                            sensor.current_value = None
                    # Force update of sensor values in UI
                    self.main_window.sensor_controller.update_sensor_values()
                
                self.log("Disconnected from serial device")
                return True
            return False
        except Exception as e:
            self.log(f"Error disconnecting from serial device: {str(e)}", "ERROR")
            
            # Explicitly set connected to False in case of error
            if 'other_serial' in self.interfaces:
                self.interfaces['other_serial']['connected'] = False
            
            # Emit connection status to update UI
            self.interface_status_signal.emit('other', False)
            
            # Direct UI update for disconnection error
            if self.main_window:
                if hasattr(self.main_window, 'update_device_connection_status_ui'):
                    self.main_window.update_device_connection_status_ui('other', False)
                elif hasattr(self.main_window, 'update_other_connected_status'):
                    self.main_window.update_other_connected_status(False)
                    
            return False

    def disconnect_other_serial_all(self):
        """Disconnect all OtherSerial connections"""
        print("DEBUG DataCollectionController: Disconnecting all OtherSerial connections")
        
        # Set the manual disconnect flag to prevent auto-reconnection
        self.other_serial_manually_disconnected = True
        
        # Provide immediate UI feedback before disconnection
        # Emit interface status signal immediately
        self.interface_status_signal.emit('other', False)
        
        # Update UI immediately - do this first for responsive UX
        if self.main_window:
            if hasattr(self.main_window, 'update_device_connection_status_ui'):
                self.main_window.update_device_connection_status_ui('other', False)
                print("DEBUG DataCollectionController: Updated device_connection_status_ui")
            elif hasattr(self.main_window, 'update_other_connected_status'):
                self.main_window.update_other_connected_status(False)
                print("DEBUG DataCollectionController: Updated other_connected_status")
        
        if 'other_serial' not in self.interfaces:
            print("DEBUG DataCollectionController: No other_serial interfaces to disconnect")
            return True
        
        # First check if the other_serial interface is just a simple dictionary with a 'connected' key
        if isinstance(self.interfaces['other_serial'], dict) and 'connected' in self.interfaces['other_serial']:
            print("DEBUG DataCollectionController: Found simple other_serial interface structure")
            # Simple case - just set connected to False
            self.interfaces['other_serial']['connected'] = False
            
            # Stop the thread if it's running - do this in parallel if possible
            if self.other_serial_thread and self.other_serial_thread.isRunning():
                self.other_serial_thread.disconnect()
                print("DEBUG DataCollectionController: Stopped other_serial_thread")
            
            # Reset OtherSerial sensor values to show "--"
            if hasattr(self, 'main_window') and hasattr(self.main_window, 'sensor_controller'):
                for sensor in self.main_window.sensor_controller.sensors:
                    if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                        # Set current_value to None so it displays as "--"
                        sensor.current_value = None
                # Force update of sensor values in UI
                self.main_window.sensor_controller.update_sensor_values()
                print("DEBUG DataCollectionController: Reset all OtherSerial sensor values to display '--'")
            
            return True
            
        # More complex case - a dictionary of port:interface items
        if isinstance(self.interfaces['other_serial'], dict):
            for port_name, interface in list(self.interfaces['other_serial'].items()):
                try:
                    # Skip non-dictionary items or special keys
                    if not isinstance(interface, dict):
                        print(f"DEBUG DataCollectionController: Skipping non-dict item '{port_name}' in other_serial interfaces")
                        continue
                        
                    print(f"DEBUG DataCollectionController: Disconnecting OtherSerial on port {port_name}")
                    if interface.get('connected', False):
                        # Stop the polling thread
                        if 'thread' in interface and interface['thread']:
                            interface['thread'].stop()
                            # Don't wait for thread to join - let it terminate in background
                            print(f"DEBUG DataCollectionController: Stopped polling thread for port {port_name}")
                        
                        # Close the serial port
                        if 'serial' in interface and interface['serial']:
                            interface['serial'].close()
                            print(f"DEBUG DataCollectionController: Closed serial port {port_name}")
                        
                        # Update the connection status
                        interface['connected'] = False
                        
                        # Log the disconnection
                        if hasattr(self, 'main_window') and hasattr(self.main_window, 'logger'):
                            self.main_window.logger.log(f"Disconnected OtherSerial from port {port_name}", "INFO")
                except Exception as e:
                    print(f"DEBUG DataCollectionController: Error disconnecting OtherSerial on port {port_name}: {e}")
                    if hasattr(self, 'main_window') and hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"Error disconnecting OtherSerial on port {port_name}: {e}", "ERROR")
        
        # Update overall connected status to False
        if isinstance(self.interfaces['other_serial'], dict):
            self.interfaces['other_serial']['connected'] = False
        
        # Reset OtherSerial sensor values to show "--"
        if hasattr(self, 'main_window') and hasattr(self.main_window, 'sensor_controller'):
            for sensor in self.main_window.sensor_controller.sensors:
                if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                    # Set current_value to None so it displays as "--"
                    sensor.current_value = None
            # Force update of sensor values in UI
            self.main_window.sensor_controller.update_sensor_values()
            print("DEBUG DataCollectionController: Reset all OtherSerial sensor values to display '--'")
        
        print("DEBUG DataCollectionController: Completed disconnection of all OtherSerial connections")
        return True
        
    def test_other_serial_step(self, step_config):
        """
        Test a single step from a serial sequence
        
        Args:
            step_config: Dictionary with step configuration
            
        Returns:
            The response from executing the step
        """
        try:
            if 'other_serial' not in self.interfaces or not self.interfaces['other_serial']['connected']:
                raise Exception("Device is not connected")
                
            step_type = step_config.get("type", "")
            
            if step_type == "send_command":
                command = step_config.get("command", "")
                if not command:
                    raise Exception("No command specified")
                    
                return self.other_serial_thread.send_command(command)
                
            elif step_type == "wait":
                delay = float(step_config.get("delay", 0))
                time.sleep(delay)
                return f"Waited for {delay} seconds"
                
            elif step_type == "read_response":
                timeout = float(step_config.get("timeout", 1.0))
                return self.other_serial_thread.read_response(timeout)
                
            elif step_type == "parse_value":
                data = step_config.get("data", "")
                prefix = step_config.get("prefix", "")
                suffix = step_config.get("suffix", "")
                
                # Simple parsing for test purposes
                if not data:
                    data = self.other_serial_thread.last_response
                    
                if prefix and data.find(prefix) >= 0:
                    data = data[data.find(prefix) + len(prefix):]
                    
                if suffix and data.find(suffix) >= 0:
                    data = data[:data.find(suffix)]
                    
                return f"Parsed value: {data}"
                
            else:
                raise Exception(f"Unknown step type: {step_type}")
                
        except Exception as e:
            self.log(f"Error testing step: {str(e)}", "ERROR")
            raise
            
    def test_other_serial_manual_command(self, command):
        """
        Test a manual command for the Other Serial interface
        
        Args:
            command: Command string to send (including line endings)
            
        Returns:
            The response from the device
        """
        try:
            if 'other_serial' not in self.interfaces or not self.interfaces['other_serial']['connected']:
                raise Exception("Device is not connected")
                
            if not command:
                raise Exception("No command specified")
                
            # Send the command and wait for a response
            result = self.other_serial_thread.send_command(command)
            
            # Read any remaining data after a short delay
            time.sleep(0.1)
            additional_data = self.other_serial_thread.read_response(0.5)
            
            if additional_data:
                result += additional_data
                
            return result
                
        except Exception as e:
            self.log(f"Error sending manual command: {str(e)}", "ERROR")
            raise
        
    def create_serial_sequence(self, name, actions):
        """Create a SerialSequence object from JSON-formatted actions
        
        Args:
            name (str): The name of the sequence
            actions (list): List of action dictionaries
            
        Returns:
            SerialSequence: The configured SerialSequence object
        """
        try:
            print(f"DEBUG create_serial_sequence: Called for '{name}' with {len(actions) if actions else 0} actions")
            print(f"DEBUG create_serial_sequence: Actions data: {actions}")
            
            # Import necessary classes
            from app.core.interfaces.other_serial_interface import SerialSequence, SendCommandStep, WaitStep, ReadResponseStep, ParseValueStep, PublishValueStep
            
            # Create the sequence
            sequence = SerialSequence(name=name)
            sequence.steps = []  # Explicitly initialize steps list
            
            # Add steps based on the actions
            for i, action in enumerate(actions):
                action_type = action.get('type', '')
                print(f"DEBUG create_serial_sequence: Processing action {i+1}: type={action_type}")
                
                if action_type == 'send':
                    step = SendCommandStep(
                        command=action.get('command', ''),
                        line_ending=action.get('line_ending', 'None')
                    )
                    sequence.steps.append(step)
                    print(f"DEBUG create_serial_sequence: Added SendCommandStep with command '{action.get('command', '')}'")
                    
                elif action_type == 'wait':
                    wait_ms = int(action.get('ms', 1000))
                    step = WaitStep(wait_time=wait_ms)
                    sequence.steps.append(step)
                    print(f"DEBUG create_serial_sequence: Added WaitStep with {wait_ms}ms")
                    
                elif action_type == 'read':
                    step = ReadResponseStep(
                        read_type=action.get('read_type', 'Read Line'),
                        timeout=int(action.get('timeout', 1000)),
                        result_var=action.get('target', 'response')
                    )
                    sequence.steps.append(step)
                    print(f"DEBUG create_serial_sequence: Added ReadResponseStep to store in '{action.get('target', 'response')}'")
                    
                elif action_type == 'parse':
                    # Get parse mode and parameters
                    parse_mode = action.get('parse_mode', 'entire')
                    parse_method = ''
                    start_marker = ''
                    end_marker = ''
                    
                    if parse_mode == 'after':
                        parse_method = 'After Marker'
                        start_marker = action.get('start', '')
                    elif parse_mode == 'between':
                        parse_method = 'Between Markers'
                        start_marker = action.get('start', '')
                        end_marker = action.get('end', '')
                    elif parse_mode == 'before':
                        parse_method = 'Before Marker'
                        end_marker = action.get('end', '')
                    else:  # entire
                        parse_method = 'Entire Response'
                    
                    step = ParseValueStep(
                        source_var=action.get('source', 'response'),
                        parse_method=parse_method,
                        start_marker=start_marker,
                        end_marker=end_marker,
                        result_type=action.get('result_type', 'Number (Float)'),
                        result_var=action.get('target', 'value')
                    )
                    sequence.steps.append(step)
                    print(f"DEBUG create_serial_sequence: Added ParseValueStep from '{action.get('source', 'response')}' to '{action.get('target', 'value')}'")
                    
                elif action_type == 'publish':
                    step = PublishValueStep(
                        source_var=action.get('source', 'value'),
                        target=action.get('target', 'output')
                    )
                    sequence.steps.append(step)
                    print(f"DEBUG create_serial_sequence: Added PublishValueStep from '{action.get('source', 'value')}' to '{action.get('target', 'output')}'")
            
            print(f"DEBUG create_serial_sequence: Completed sequence '{name}' with {len(sequence.steps)} steps")
            
            # Verify steps were added correctly
            if not sequence.steps:
                print(f"WARNING create_serial_sequence: No steps were added to sequence '{name}'! Original actions: {actions}")
                # Add a dummy step that publishes a value so we see something
                if not actions:
                    print(f"WARNING create_serial_sequence: Adding a dummy publish step since no actions were provided")
                    dummy_step = PublishValueStep(source_var="value", target="output")
                    sequence.steps.append(dummy_step)
            
            return sequence
            
        except Exception as e:
            print(f"ERROR create_serial_sequence: Failed to create sequence '{name}': {e}")
            import traceback
            traceback.print_exc()
            
            # Create a minimal working sequence instead of returning None
            try:
                fallback_sequence = SerialSequence(name=f"{name}_fallback")
                fallback_sequence.steps = [PublishValueStep(source_var="value", target="output")]
                print(f"DEBUG create_serial_sequence: Created fallback sequence with 1 step")
                return fallback_sequence
            except:
                print(f"CRITICAL ERROR: Even fallback sequence creation failed!")
                return None

    def disconnect_all_interfaces(self):
        """Disconnect from all hardware interfaces"""
        print("DEBUG: disconnect_all_interfaces called")
        self.disconnect_arduino()
        self.disconnect_other_serial()
        self.disconnect_labjack()
        self.log("Disconnected all interfaces.")
        
    def start_data_collection(self, run_dir):
        """
        Start collecting data from all connected interfaces and prepare CSV logging.
        
        Args:
            run_dir: Directory to store collected data
            
        Returns:
            True if data collection started successfully, False otherwise
        """
        try:
            # Make sure run directory exists
            if not os.path.exists(run_dir):
                os.makedirs(run_dir)
                
            self.run_directory = run_dir
            
            # Clear historical buffer for new run
            self.historical_buffer_mutex.lock()
            try:
                self.historical_buffer.clear()
                print("DEBUG: Cleared historical data buffer for new run")
                self.log("Historical data buffer cleared for new run")
            finally:
                self.historical_buffer_mutex.unlock()
            
            # Clear graph display for new run
            if self.main_window and hasattr(self.main_window, 'graph_controller'):
                try:
                    self.main_window.graph_controller.clear_graphs()
                    print("DEBUG: Cleared graph display for new run")
                    self.log("Graph display cleared for new run")
                except AttributeError:
                    print("DEBUG: clear_graphs method not found in graph_controller")
                    self.log("Could not clear graph display: clear_graphs method not available", "WARNING")
            
            # --- Setup CSV File --- 
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.csv_filename = os.path.join(self.run_directory, f"rundata_{timestamp}.csv")
            self.log(f"Initializing CSV file: {self.csv_filename}")
            
            # Determine header from enabled sensors in SensorController
            self.csv_header = ['timestamp'] # Always include timestamp
            sensor_controller = getattr(self.main_window, 'sensor_controller', None)
            enabled_sensor_ids = []
            if sensor_controller:
                for sensor in sensor_controller.sensors:
                    if getattr(sensor, 'enabled', False):
                        # Use the prefixed key consistent with historical buffer/combined data
                        sensor_id = sensor_controller.get_historical_buffer_key(sensor)
                        if sensor_id:
                            enabled_sensor_ids.append(sensor_id)
                            
            # Sort sensor IDs alphabetically for consistent column order
            enabled_sensor_ids.sort()
            self.csv_header.extend(enabled_sensor_ids)
            self.log(f"CSV Header determined: {self.csv_header}")
            
            # Open file and write header
            try:
                # Ensure any previous file handle is closed
                self._close_csv_file()
                
                # Open in write mode with newline='' to prevent extra blank rows
                self.csv_file = open(self.csv_filename, 'w', newline='')
                self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=self.csv_header)
                self.csv_writer.writeheader()
                self.log("CSV file opened and header written.")
            except IOError as e:
                self.log(f"Error opening or writing header to CSV file {self.csv_filename}: {e}", "ERROR")
                self._close_csv_file() # Ensure cleanup if header write fails
                return False # Prevent starting collection if CSV setup fails
            # ---------------------

            # Set collecting_data to True before starting threads and timers
            self.collecting_data = True
            self.log("Data collection flag set to True")

            # --- Start Interface Threads (if not already started) --- 
            # (Existing logic for starting Arduino/OtherSerial/LabJack threads if needed)
            # Note: ArduinoMasterSlaveThread.start_data_collection is no longer needed for CSV.
            # We might just need to ensure the threads are running if they were previously only monitoring.
            
            # Example for Arduino (adjust as needed for other interfaces):
            if 'arduino' in self.interfaces and self.interfaces['arduino']['connected']:
                if not self.arduino_thread.isRunning():
                    self.log("Starting Arduino thread for data collection.")
                    self.arduino_thread.start() # Simplified start, remove run_dir arg if not needed
                else:
                     # Ensure it's not in monitoring_only mode
                     self.arduino_thread.monitoring_only = False 
                     self.log("Arduino thread switched from monitoring to full data collection")
            
            # Example for Other Serial:
            if 'other_serial' in self.interfaces and self.interfaces['other_serial']['connected']:
                if not self.other_serial_thread.isRunning():
                    self.log("Starting Other Serial thread for data collection.")
                    self.other_serial_thread.start()
                else:
                    self.other_serial_thread.monitoring_only = False
                    self.log("Other Serial thread switched from monitoring to full data collection")

            # Example for LabJack:
            if 'labjack' in self.interfaces and self.interfaces['labjack']['connected']:
                if not self.labjack_thread.isRunning():
                    self.log("Starting LabJack thread for data collection.")
                    self.labjack_thread.start()
                else:
                    self.labjack_thread.monitoring_only = False
                    self.log("LabJack thread switched from monitoring to full data collection")
            # -----------------------------------------------------
            
            # Start timers for data collection if not already running
            if not self.update_timer.isActive():
                self.update_timer.start()
                print(f"DEBUG: Started update_timer with interval {self.update_timer.interval()}ms")
                self.log("Started UI update timer")
            
            if not self.combined_data_timer.isActive():
                timer_interval = int(1000 / self.sampling_rate)  # Convert Hz to ms
                self.combined_data_timer.setInterval(timer_interval)
                self.combined_data_timer.start()
                print(f"DEBUG: Started combined_data_timer with interval {timer_interval}ms (sampling rate: {self.sampling_rate}Hz, active={self.combined_data_timer.isActive()})")
                self.log(f"Combined data timer started with interval {timer_interval}ms (sampling rate: {self.sampling_rate}Hz)")
            
            self.log(f"Data collection started - logging to {self.csv_filename}")
            self.status_update_signal.emit("Data collection started", "INFO")
            
            return True
            
        except Exception as e:
            self.log(f"Error starting data collection: {str(e)}", "ERROR")
            self.status_update_signal.emit(f"Error starting data collection: {str(e)}", "ERROR")
            self._close_csv_file() # Ensure file is closed on error
            return False
            
    def stop_data_collection(self):
        """Stop data collection from all interfaces and close CSV file"""
        try:
            self.collecting_data = False
            
            # --- Stop Interface Threads --- 
            # (Existing logic to stop threads or switch to monitoring mode)
            # Example for Arduino:
            if 'arduino' in self.interfaces and self.arduino_thread.isRunning():
                 # Decide if you want to stop the thread or switch to monitoring
                 # self.arduino_thread.stop() # If stopping entirely
                 self.arduino_thread.monitoring_only = True # If switching back to monitoring
                 self.log("Stopped Arduino data collection (switched to monitoring)." if self.arduino_thread.monitoring_only else "Stopped Arduino thread.")
            
            # (Add similar logic for OtherSerial/LabJack)
            # ----------------------------

            # --- Close CSV File --- 
            self._close_csv_file()
            self.log("Data collection stopped.")
            # ---------------------
            
            self.status_update_signal.emit("Data collection stopped", "INFO")
            
        except Exception as e:
            self.log(f"Error stopping data collection: {str(e)}", "ERROR")
            self.status_update_signal.emit(f"Error stopping data collection: {str(e)}", "ERROR")
            self._close_csv_file() # Ensure file is closed on error
            
    def _close_csv_file(self):
        """Helper method to safely close the CSV file and reset writer/file handle."""
        if self.csv_writer:
            self.csv_writer = None
        if self.csv_file:
            try:
                self.csv_file.close()
                self.log(f"Closed CSV file: {self.csv_filename}")
            except IOError as e:
                self.log(f"Error closing CSV file {self.csv_filename}: {e}", "ERROR")
            finally:
                self.csv_file = None
                self.csv_filename = ""
                self.csv_header = [] # Clear header when file is closed

    def pause_data_collection(self):
        """Pause data collection from all interfaces"""
        try:
            # Pause Arduino data collection if running
            if 'arduino' in self.interfaces and self.arduino_thread.running:
                self.arduino_thread.pause_data_collection()
                self.log("Paused Arduino data collection")
            
            # Pause Other Serial data collection if running
            if 'other_serial' in self.interfaces and self.other_serial_thread.running:
                self.other_serial_thread.pause_data_collection()
                self.log("Paused Other Serial data collection")
            
            # Add more interfaces as needed
            
            self.log("Data collection paused")
            self.status_update_signal.emit("Data collection paused", "INFO")
            
        except Exception as e:
            self.log(f"Error pausing data collection: {str(e)}", "ERROR")
            
    def resume_data_collection(self):
        """Resume data collection from all interfaces"""
        try:
            # Resume Arduino data collection if paused
            if 'arduino' in self.interfaces and self.arduino_thread.running:
                self.arduino_thread.resume_data_collection()
                self.log("Resumed Arduino data collection")
            
            # Resume Other Serial data collection if paused
            if 'other_serial' in self.interfaces and self.other_serial_thread.running:
                self.other_serial_thread.resume_data_collection()
                self.log("Resumed Other Serial data collection")
            
            # Add more interfaces as needed
            
            self.log("Data collection resumed")
            self.status_update_signal.emit("Data collection resumed", "INFO")
            
        except Exception as e:
            self.log(f"Error resuming data collection: {str(e)}", "ERROR")
    
    @pyqtSlot(dict)
    def handle_arduino_data(self, data):
        """Handle data received from Arduino"""
        # print(f"DEBUG: handle_arduino_data called with keys: {list(data.keys())}") # Verbose

        # Discard data for storage if collection is not active, but allow monitoring for UI updates
        store_data = self.collecting_data
        if not store_data:
            print("DEBUG: Not storing Arduino data as data collection is not active, but processing for UI updates")

        # First make sure the data includes a timestamp
        if 'timestamp' not in data:
            data['timestamp'] = time.time()
            # print(f"DEBUG: Added missing timestamp to Arduino data: {data['timestamp']}") # Verbose
        elif isinstance(data['timestamp'], str):
            # Convert string timestamp to float
            try:
                data['timestamp'] = float(data['timestamp'])
                # print(f"DEBUG: Converted Arduino string timestamp to float: {data['timestamp']}") # Verbose
            except ValueError:
                # If conversion fails, use current time
                data['timestamp'] = time.time()
                # print(f"DEBUG: Replaced invalid Arduino timestamp with current time: {data['timestamp']}") # Verbose

        # --- Apply Sensor Offset and Conversion ---
        corrected_data = {'timestamp': data['timestamp']} # Start with timestamp
        sensor_controller = getattr(self.main_window, 'sensor_controller', None)
        sensors_found = {}
        if sensor_controller:
            # Arduino data keys are the sensor names
            sensors_found = {s.name: s for s in sensor_controller.sensors if getattr(s, 'interface_type', '') == 'Arduino'}
            # print(f"DEBUG Arduino Handler: Found {len(sensors_found)} Arduino sensors for lookup.") # Debug

        for key, raw_value in data.items():
            if key == 'timestamp':
                continue # Skip timestamp

            sensor = sensors_found.get(key)
            if sensor:
                try:
                    # Get offset and conversion factor from the sensor model
                    offset = float(getattr(sensor, 'offset', 0.0))
                    conversion_factor = float(getattr(sensor, 'conversion_factor', 1.0))
                    # Ensure raw_value is float before calculation
                    corrected_value = (float(raw_value) * conversion_factor) + offset
                    corrected_data[key] = corrected_value
                    # print(f"DEBUG Arduino Correct: {key} Raw={raw_value}, Offset={offset}, Factor={conversion_factor}, Corrected={corrected_value}") # Debug
                except (ValueError, TypeError) as e:
                    # Log error if conversion fails, keep raw value
                    print(f"WARN: Could not apply correction to Arduino {key} value '{raw_value}': {e}")
                    corrected_data[key] = raw_value # Keep raw value on error
            else:
                # If no matching sensor found, keep the raw value
                # print(f"DEBUG Arduino Handler: No matching sensor found for key '{key}'. Using raw value.") # Debug
                corrected_data[key] = raw_value

        # Use the corrected data dictionary from now on
        data = corrected_data
        # ------------------------------------------

        # Store data in combined data buffer with "arduino_" prefix only if collecting data
        if store_data:
            self.combined_data_mutex.lock()
            try:
                # print(f"DEBUG: Adding Arduino data to combined_data with keys: {list(data.keys())}") # Verbose
                for key, value in data.items():
                    if key != 'timestamp':  
                        prefixed_key = f"arduino_{key}"
                        self.combined_data[prefixed_key] = value
                        # print(f"DEBUG: Added {prefixed_key} = {value} to combined_data") # Verbose
                    else:
                        self.combined_data['arduino_timestamp'] = value 
                        if 'timestamp' not in self.combined_data or value > self.combined_data['timestamp']:
                            self.combined_data['timestamp'] = value
            finally:
                self.combined_data_mutex.unlock()
        
        # Process the data through SensorController for UI updates
        if self.main_window and hasattr(self.main_window, 'sensor_controller'):
            # print("DEBUG: Calling sensor_controller.update_sensor_data with Arduino data") # Verbose
            # Let SensorController process the *corrected* data
            self.main_window.sensor_controller.update_sensor_data(data)
        else:
            print("DEBUG: Cannot process Arduino data - sensor_controller not available")
        
        # --- Store in historical buffer only if collecting data --- 
        if store_data:
            self.historical_buffer_mutex.lock()
            try:
                # Use corrected data for historical buffer
                ts = data.get('timestamp')
                if ts is not None:
                    for key, value in data.items():
                        if key != 'timestamp': 
                            sensor_id = f"arduino_{key}" # Use prefixed key
                            try:
                                float_value = float(value)
                                self.historical_buffer[sensor_id].append((ts, float_value))
                                # print(f"DEBUG HIST: Added {sensor_id}: ({ts}, {float_value})") # Very verbose
                            except (ValueError, TypeError):
                                self.log(f"Could not store non-numeric value '{value}' for {sensor_id} in historical buffer", "WARNING")
            except Exception as e:
                 self.log(f"Error storing Arduino data in historical buffer: {e}", "ERROR")
            finally:
                self.historical_buffer_mutex.unlock()
        # ----------------------------------
        
    @pyqtSlot(bool, str)
    def handle_arduino_status(self, connected, message):
        """Handle Arduino connection status updates"""
        print(f"DataCollectionController.handle_arduino_status: connected={connected}, message='{message}'")
        
        if 'arduino' in self.interfaces:
            self.interfaces['arduino']['connected'] = connected
            print(f"DataCollectionController: Updated 'arduino' in interfaces: connected={connected}")
        else:
            # If not in interfaces yet but successfully connected, create the entry
            if connected:
                print(f"DataCollectionController: Arduino not in interfaces dict but connected=True. Creating entry.")
                self.interfaces['arduino'] = {
                    'type': 'arduino',
                    'connected': True
                }
            else:
                print(f"DataCollectionController: Arduino not in interfaces dict and connected=False.")
        
        print(f"DataCollectionController: Emitting interface_status_signal('arduino', {connected})")
        self.interface_status_signal.emit('arduino', connected)
        
        # Direct UI update
        if self.main_window and hasattr(self.main_window, 'update_arduino_connected_status'):
            print(f"Using direct update_arduino_connected_status({connected}) from handle_arduino_status")
            self.main_window.update_arduino_connected_status(connected)
        
        self.log(f"Arduino status: {message}")
        
    @pyqtSlot(str)
    def handle_arduino_error(self, error_message):
        """Handle Arduino errors"""
        self.log(f"Arduino error: {error_message}", "ERROR")
        self.status_update_signal.emit(f"Arduino error: {error_message}", "ERROR")
        
    @pyqtSlot(dict)
    def handle_other_serial_data(self, data):
        """Handle data received from OtherSerial devices.
        
        Args:
            data (dict): Data received from the OtherSerial interface
        """
        if not data:
            return
            
        print(f"DEBUG DataCollectionController: handle_other_serial_data called with data: {data}")
        
        # First, check if we have a timestamp in the data
        if 'timestamp' not in data:
            # Add a timestamp if none is provided
            data['timestamp'] = time.time()
            
        ts = data['timestamp']
        
        # Look up sensors by name for lookup values
        data_keys = [key for key in data.keys() if key != 'timestamp']
        print(f"DEBUG DataCollectionController: Processing data keys: {data_keys}")
        
        other_serial_sensors = []
        
        # Access sensors through main_window instead of directly
        if hasattr(self, 'main_window') and hasattr(self.main_window, 'sensor_controller'):
            for sensor in self.main_window.sensor_controller.sensors:
                if getattr(sensor, 'interface_type', '') == 'OtherSerial':
                    mapping = getattr(sensor, 'mapping', None) or getattr(sensor, 'published_variable', None)
                    other_serial_sensors.append(sensor)
                    print(f"DEBUG DataCollectionController: Found OtherSerial sensor '{sensor.name}' with mapping '{mapping}'")
            print(f"DEBUG DataCollectionController: Found {len(other_serial_sensors)} OtherSerial sensors for lookup: {[s.name for s in other_serial_sensors]}")
        else:
            print("DEBUG DataCollectionController: No sensor_controller available through main_window")
        
        # Create a copy of the data to send to the sensor controller
        corrected_data = {'timestamp': ts}
        
        # For each OtherSerial sensor, use its mapping (published variable) to extract the value
        for sensor in other_serial_sensors:
            published_var = getattr(sensor, 'mapping', None) or getattr(sensor, 'published_variable', None)
            print(f"DEBUG DataCollectionController: Processing sensor '{sensor.name}' with mapping '{published_var}'")
            
            if published_var and published_var in data:
                corrected_data[sensor.name] = data[published_var]
                print(f"DEBUG DataCollectionController: ✓ Mapped value {data[published_var]} from '{published_var}' to sensor '{sensor.name}'")
            else:
                # Check for partial matches (like "output" in the data might match "Sequence1:output" in mapping)
                matched = False
                for key in data_keys:
                    # Check if we have a full or partial match
                    if published_var and key in published_var:
                        corrected_data[sensor.name] = data[key]
                        print(f"DEBUG DataCollectionController: ✓ Partial match! Mapped value {data[key]} from '{key}' to sensor '{sensor.name}' via '{published_var}'")
                        matched = True
                        break
                
                if not matched:
                    corrected_data[sensor.name] = None
                    print(f"DEBUG DataCollectionController: ✗ No matching data found for sensor '{sensor.name}' with mapping '{published_var}'")
        
        print(f"DEBUG DataCollectionController: Final corrected data: {corrected_data}")
        
        # Only update combined_data if collecting
        if self.collecting_data:
            self.combined_data_mutex.lock()
            try:
                # Store data in combined_data with "other_serial_" prefix
                for key, value in corrected_data.items():
                    if key != 'timestamp':
                        prefixed_key = f"other_serial_{key}"
                        self.combined_data[prefixed_key] = value
                    else:
                        self.combined_data['other_serial_timestamp'] = value
                        if 'timestamp' not in self.combined_data or value > self.combined_data['timestamp']:
                            self.combined_data['timestamp'] = value
            finally:
                self.combined_data_mutex.unlock()
            
            # Store in historical buffer for graphing
            self.historical_buffer_mutex.lock()
            try:
                # Use corrected data for historical buffer
                ts = corrected_data.get('timestamp')
                if ts is not None:
                    for key, value in corrected_data.items():
                        if key != 'timestamp':
                            sensor_id = f"other_serial_{key}"  # Use prefixed key
                            try:
                                float_value = float(value) if value is not None else None
                                if float_value is not None:
                                    self.historical_buffer[sensor_id].append((ts, float_value))
                                    print(f"DEBUG HIST: Added {sensor_id}: ({ts}, {float_value})")
                            except (ValueError, TypeError):
                                self.log(f"Could not store non-numeric value '{value}' for {sensor_id} in historical buffer", "WARNING")
            except Exception as e:
                self.log(f"Error storing OtherSerial data in historical buffer: {e}", "ERROR")
            finally:
                self.historical_buffer_mutex.unlock()
        else:
            print("DEBUG DataCollectionController: Not collecting data, skipped updating combined_data")
        
        # Update the UI with the corrected data
        print(f"DEBUG DataCollectionController: Calling sensor_controller.update_other_serial_data with data: {corrected_data}")
        if hasattr(self, 'main_window') and hasattr(self.main_window, 'sensor_controller'):
            self.main_window.sensor_controller.update_other_serial_data(corrected_data)
            print("DEBUG DataCollectionController: Completed sensor_controller.update_other_serial_data call")
            # Also update the sensor values in the UI
            print("DEBUG DataCollectionController: Calling sensor_controller.update_sensor_values()")
            self.main_window.sensor_controller.update_sensor_values()
            print("DEBUG DataCollectionController: Completed sensor_controller.update_sensor_values() call")
        else:
            print("ERROR: sensor_controller not found on main_window in handle_other_serial_data")
        
        # Emit data signal - this should always happen even if not collecting data
        print("DEBUG DataCollectionController: Emitting data_received_signal with data")
        self.data_received_signal.emit(corrected_data)
        print("DEBUG DataCollectionController: Completed data_received_signal emission")

    @pyqtSlot(bool, str)
    def handle_other_serial_status(self, connected, message):
        """Handle Other Serial connection status updates"""
        print(f"DataCollectionController.handle_other_serial_status: connected={connected}, message='{message}'")
        
        if 'other_serial' in self.interfaces:
            self.interfaces['other_serial']['connected'] = connected
            print(f"DataCollectionController: Updated 'other_serial' in interfaces: connected={connected}")
        else:
            # If not in interfaces yet but successfully connected, create the entry
            if connected:
                print(f"DataCollectionController: Other Serial not in interfaces dict but connected=True. Creating entry.")
                self.interfaces['other_serial'] = {
                    'type': 'other_serial',
                    'connected': True
                }
            else:
                print(f"DataCollectionController: Other Serial not in interfaces dict and connected=False.")
        
        print(f"DataCollectionController: Emitting interface_status_signal('other', {connected})")
        # Use 'other' not 'other_serial' to match what MainWindow expects
        self.interface_status_signal.emit('other', connected)
        
        # Direct UI update
        if self.main_window:
            # Try multiple methods for backward compatibility - use 'other' as device type
            if hasattr(self.main_window, 'update_device_connection_status_ui'):
                print(f"Using direct update_device_connection_status_ui('other', {connected}) from handle_other_serial_status")
                self.main_window.update_device_connection_status_ui('other', connected)
            elif hasattr(self.main_window, 'update_other_connected_status'):
                print(f"Using direct update_other_connected_status({connected}) from handle_other_serial_status")
                self.main_window.update_other_connected_status(connected)
        
        self.log(f"Other Serial status: {message}")
        
    @pyqtSlot(str)
    def handle_other_serial_error(self, error_message):
        """Handle Other Serial errors"""
        self.log(f"Other Serial error: {error_message}", "ERROR")
        self.status_update_signal.emit(f"Other Serial error: {error_message}", "ERROR")
        
    def update_sensor_display(self):
        """Placeholder method - UI updates are now driven by MainWindow's timer calling SensorController"""
        # This method is no longer responsible for directly updating the UI table.
        # MainWindow.update_sensor_values (connected to a timer) calls
        # SensorController.update_sensor_values() which updates the table.
        # We keep this method connected to the DataCollectionController's update_timer 
        # in case we need it for other periodic background tasks later.
        # print("DEBUG DataCollectionController: update_sensor_display tick") # Optional: uncomment for low-frequency debug
        pass
        
    def get_arduino_ports(self):
        """Get list of available Arduino ports"""
        return ArduinoMasterSlaveThread.list_ports()
        
    def get_other_serial_ports(self):
        """Get list of available serial ports for other devices"""
        print("DataCollectionController.get_other_serial_ports() called")
        ports = self.other_serial_thread.list_ports()
        print(f"DataCollectionController.get_other_serial_ports() received: {ports}")
        return ports
        
    def get_available_sensor_names(self):
        """
        Get a list of available sensor names from connected Arduino
        
        Returns:
            List of sensor names or empty list if not connected
        """
        try:
            if 'arduino' in self.interfaces and self.interfaces['arduino']['connected']:
                return self.arduino_thread.get_available_sensor_names()
            return []
        except Exception as e:
            self.log(f"Error getting available sensor names: {str(e)}", "ERROR")
            return []
        
    def send_arduino_command(self, command, device=None, value=None):
        """
        Send a command to the Arduino to control a device
        
        Args:
            command: Command type (e.g. "LED", "MOTOR", "RELAY")
            device: Device identifier (e.g. device number or name)
            value: Value to set (e.g. "ON", "OFF", "100", etc.)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if 'arduino' not in self.interfaces or not self.interfaces['arduino']['connected']:
                self.log("Cannot send command - Arduino not connected", "ERROR")
                return False
                
            success = self.arduino_thread.send_command(command, device, value)
            
            if success:
                self.log(f"Sent command to Arduino: {command} {device if device else ''} {value if value else ''}")
            else:
                self.log("Failed to send command to Arduino", "ERROR")
                
            return success
            
        except Exception as e:
            self.log(f"Error sending command to Arduino: {str(e)}", "ERROR")
            return False
            
    def control_device(self, device_type, device_id, action, value=None):
        """
        Higher-level method to control a device via Arduino
        
        Args:
            device_type: Type of device (LED, MOTOR, RELAY, etc.)
            device_id: Identifier for the device
            action: Action to perform (ON, OFF, SET, etc.)
            value: Optional value for the action
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Normalize inputs
            device_type = device_type.upper()
            action = action.upper() if action else ""
            device_id = str(device_id).strip()
            
            # For actions that are actually values (e.g., for motors or servos)
            # If action is a number, treat it as a value
            try:
                numeric_action = float(action)
                # If this succeeds, action is a numeric value
                value = action
                action = "SET"  # Default action for numeric values
            except (ValueError, TypeError):
                # Not a number, continue with original action
                pass
                
            # Map device type and action to Arduino command
            if device_type == "LED":
                if action in ["ON", "1", "TRUE"]:
                    return self.send_arduino_command("LED", device_id, "ON")
                elif action in ["OFF", "0", "FALSE"]:
                    return self.send_arduino_command("LED", device_id, "OFF")
                elif action == "TOGGLE":
                    return self.send_arduino_command("LED", device_id, "TOGGLE")
                elif action == "BLINK":
                    # If value is provided, use it as blink rate
                    if value:
                        return self.send_arduino_command("LED", device_id, f"BLINK:{value}")
                    else:
                        return self.send_arduino_command("LED", device_id, "BLINK")
                else:
                    self.log(f"Unknown LED action: {action}", "ERROR")
                    return False
                    
            elif device_type == "RELAY":
                if action in ["ON", "1", "TRUE"]:
                    return self.send_arduino_command("RELAY", device_id, "ON")
                elif action in ["OFF", "0", "FALSE"]:
                    return self.send_arduino_command("RELAY", device_id, "OFF")
                elif action == "TOGGLE":
                    return self.send_arduino_command("RELAY", device_id, "TOGGLE")
                elif action == "PULSE":
                    # If value is provided, use it as pulse duration
                    if value:
                        return self.send_arduino_command("RELAY", device_id, f"PULSE:{value}")
                    else:
                        return self.send_arduino_command("RELAY", device_id, "PULSE")
                else:
                    self.log(f"Unknown RELAY action: {action}", "ERROR")
                    return False
                    
            elif device_type == "MOTOR":
                if action == "STOP" or action == "OFF" or action == "0":
                    return self.send_arduino_command("MOTOR", device_id, "0")
                elif action == "SPEED" or action == "SET":
                    if value is not None:
                        return self.send_arduino_command("MOTOR", device_id, value)
                    else:
                        self.log("Missing value for MOTOR SPEED command", "ERROR")
                        return False
                # If action is a numeric value (speed), handle it
                elif action.isdigit() or (action.replace('.', '', 1).isdigit() and action.count('.') <= 1):
                    return self.send_arduino_command("MOTOR", device_id, action)
                else:
                    self.log(f"Unknown MOTOR action: {action}", "ERROR")
                    return False
                    
            elif device_type == "SERVO":
                if action == "POSITION" or action == "SET":
                    if value is not None:
                        return self.send_arduino_command("SERVO", device_id, value)
                    else:
                        self.log("Missing value for SERVO POSITION command", "ERROR")
                        return False
                # If action is a numeric value (position), handle it
                elif action.isdigit() or (action.replace('.', '', 1).isdigit() and action.count('.') <= 1):
                    return self.send_arduino_command("SERVO", device_id, action)
                elif action == "CENTER":
                    return self.send_arduino_command("SERVO", device_id, "90")
                elif action == "MIN" or action == "LEFT":
                    return self.send_arduino_command("SERVO", device_id, "0")
                elif action == "MAX" or action == "RIGHT":
                    return self.send_arduino_command("SERVO", device_id, "180")
                else:
                    self.log(f"Unknown SERVO action: {action}", "ERROR")
                    return False
                
            # Add more device types and actions as needed
            
            # If no matching device type
            self.log(f"Unsupported device type: {device_type}", "ERROR")
            return False
            
        except Exception as e:
            self.log(f"Error in control_device: {str(e)}", "ERROR")
            return False
        
    def log(self, message, level="INFO"):
        """Log a message with a specified level"""
        if level not in ["INFO", "WARNING", "ERROR", "DEBUG"]:
            level = "INFO"
            
        # Emit signal for logging
        self.status_update_signal.emit(message, level)
        
        # Print to console
        print(f"[{level}] {message}")
        
    def add_other_sensor(self, name, unit, offset, port, baud_rate, data_bits, parity,
                         stop_bits, poll_interval, steps):
        """
        Add a new Other Serial sensor to the sensor collection
        
        Args:
            name: Sensor name
            unit: Measurement unit
            offset: Calibration offset
            port: Serial port
            baud_rate: Baud rate
            data_bits: Data bits
            parity: Parity setting
            stop_bits: Stop bits
            poll_interval: Poll interval in seconds
            steps: List of step configurations for the sequence
            
        Returns:
            True if sensor was added successfully, False otherwise
        """
        try:
            # Check if we have a sensor controller
            if not hasattr(self.main_window, 'sensor_controller'):
                self.log(f"Cannot add other sensor '{name}': No sensor controller available", "ERROR")
                return False
                
            # Create a sequence for the sensor
            sequence = self.create_serial_sequence(name, steps)
            
            # Create a sequence configuration to save with the sensor
            sequence_config = {
                'port': port,
                'baud_rate': baud_rate,
                'data_bits': data_bits,
                'parity': parity,
                'stop_bits': stop_bits,
                'poll_interval': poll_interval,
                'steps': steps
            }
            
            # Add the sensor to the sensor controller
            success = self.main_window.sensor_controller.add_other_serial_sensor(
                name=name,
                unit=unit,
                offset=offset,
                port=port,
                baud_rate=baud_rate,
                data_bits=data_bits,
                parity=parity,
                stop_bits=stop_bits,
                poll_interval=poll_interval,
                sequence=sequence,
                sequence_config=sequence_config
            )
            
            if success:
                self.log(f"Added new OtherSerial sensor: {name}")
                return True
            else:
                self.log(f"Failed to add OtherSerial sensor: {name}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"Error adding OtherSerial sensor '{name}': {str(e)}", "ERROR")
            return False
            
    def update_other_sensor(self, sensor):
        """
        Update an existing Other Serial sensor
        
        Args:
            sensor: The sensor object to update
            
        Returns:
            True if sensor was updated successfully, False otherwise
        """
        try:
            # Ensure sensor controller exists
            if not hasattr(self.main_window, 'sensor_controller'):
                self.log(f"Cannot update sensor '{sensor.name}': No sensor controller available", "ERROR")
                return False
            
            # Get the sequence configuration from the sensor
            config = sensor.sequence_config
            
            # Create a new sequence with the updated configuration
            sequence = self.create_serial_sequence(
                name=sensor.name, 
                steps_data=config.get('steps', [])
            )
            
            # Update the sensor's sequence
            sensor.sequence = sequence
            
            # Update the sensor in the sensor controller
            success = self.main_window.sensor_controller.update_sensor(sensor)
            
            if success:
                self.log(f"Updated OtherSerial sensor: {sensor.name}")
                return True
            else:
                self.log(f"Failed to update OtherSerial sensor: {sensor.name}", "ERROR")
                return False
                
        except Exception as e:
            if hasattr(sensor, 'name'):
                self.log(f"Error updating OtherSerial sensor '{sensor.name}': {str(e)}", "ERROR")
            else:
                self.log(f"Error updating OtherSerial sensor: {str(e)}", "ERROR")
            return False
        
    def get_sampling_rate(self):
        """Get the current sampling rate"""
        return self.sampling_rate
        
    def set_sampling_rate(self, rate):
        """Set the sampling rate"""
        self.sampling_rate = rate
        
        # Update timer interval for combined data emission
        timer_interval = int(1000 / self.sampling_rate)  # Convert Hz to ms
        self.combined_data_timer.setInterval(timer_interval)
        self.log(f"Updated combined data timer interval to {timer_interval}ms (sampling rate: {self.sampling_rate}Hz)")
        
        # Update Arduino polling interval if connected
        if 'arduino' in self.interfaces and self.interfaces['arduino']['connected']:
            # Convert Hz to seconds for poll interval
            poll_interval = 1.0 / self.sampling_rate
            self.arduino_thread.set_poll_interval(poll_interval)
            self.log(f"Updated Arduino polling interval to {poll_interval}s")
            
        # Update LabJack thread sampling rate
        if hasattr(self, 'labjack_thread'):
            self.labjack_thread.set_sampling_rate(self.sampling_rate)
            self.log(f"Updated LabJack thread sampling rate to {self.sampling_rate}Hz")
        
    def connect_labjack(self, device_type="ANY", connection_type="ANY"):
        """Connect to LabJack device using LabJackDataThread"""
        print(f"DEBUG: connect_labjack called with device='{device_type}', connection='{connection_type}'")
        
        if not LabJackInterface:
            self.log("LabJackInterface library not imported successfully.", "ERROR")
            return False
            
        try:
            if 'labjack' in self.interfaces and self.interfaces['labjack']['connected']:
                self.log("LabJack already connected")
                return True

            # --- Use LabJackDataThread --- 
            # 1. Create the actual interface object
            lj_interface = LabJackInterface(device_type, connection_type)
            
            # 2. Set the interface and sampling rate for the thread
            self.labjack_thread.set_interface(lj_interface)
            self.labjack_thread.set_sampling_rate(self.sampling_rate)
            
            # 3. Call the thread's connect method (which connects the interface)
            #    This happens *within* the thread's context if called before start,
            #    or needs careful handling if called after. Let's connect first.
            #    Connect attempts are better handled directly for immediate feedback.
            lj_interface.connect() # Connect directly first
            # Set the thread's internal connected flag since we connected outside it
            self.labjack_thread._connected = True 
            print("DEBUG: Manually set labjack_thread._connected = True")
            # Call handler to update controller state
            self._handle_labjack_connection_result(True, lj_interface, "Connection successful (pending thread confirmation)") 
            
            # 4. Start the thread's run loop for monitoring purposes, but set to monitoring-only mode
            if not self.labjack_thread.isRunning():
                print("DEBUG: Starting LabJackDataThread for monitoring...")
                self.labjack_thread.monitoring_only = True
                self.labjack_thread.start()
                self.log("LabJack thread started in monitoring-only mode for UI updates")
            else:
                print("DEBUG: LabJackDataThread already running.")
                self.labjack_thread.monitoring_only = True
                self.log("LabJack thread set to monitoring-only mode for UI updates")
            # ---------------------------
            
            # Note: Connection status is now handled by handle_labjack_status slot
            return True # Indicate attempt started

        except Exception as e:
            self.log(f"Error initiating LabJack connection: {str(e)}", "ERROR")
            self._handle_labjack_connection_result(False, None, str(e))
            return False
            
    def disconnect_labjack(self):
        """Disconnect from LabJack device via LabJackDataThread"""
        print("DEBUG: disconnect_labjack called")
        try:
            # Check if the interface exists and is marked as connected in our state
            if 'labjack' in self.interfaces and self.interfaces['labjack'].get('connected', False):
                # --- Stop the LabJack Thread ---
                if self.labjack_thread and self.labjack_thread.isRunning():
                    print("DEBUG: Stopping LabJackDataThread...")
                    # Call the thread's disconnect method, which handles stopping the loop
                    # and disconnecting the underlying interface.
                    self.labjack_thread.disconnect() 
                    
                    # Ask the Qt event loop to quit cleanly
                    self.labjack_thread.quit() 
                    
                    # Wait for the thread to finish execution
                    if not self.labjack_thread.wait(3000): # Wait up to 3 seconds
                        print("WARNING: LabJackDataThread did not finish gracefully within 3 seconds. Terminating.")
                        self.labjack_thread.terminate() # Force terminate if stuck
                    else:
                        print("DEBUG: LabJackDataThread finished gracefully.")
                # -----------------------------
                
                # Update internal state and UI immediately after stopping thread
                # Use the internal handler for consistency
                self._handle_labjack_connection_result(False, None, "Disconnected by user")
                
                self.log("Disconnected from LabJack")
                return True
            else:
                # If not in interfaces or not marked as connected, assume already disconnected
                print("DEBUG: LabJack interface not found or already marked as disconnected.")
                # Ensure thread is stopped if it somehow still exists and is running
                if self.labjack_thread and self.labjack_thread.isRunning():
                     print("WARNING: LabJack thread was running despite interface being marked disconnected. Stopping now.")
                     self.labjack_thread.disconnect()
                     self.labjack_thread.quit()
                     if not self.labjack_thread.wait(3000):
                         self.labjack_thread.terminate()
                return False # Indicate no action was needed or already disconnected
        except Exception as e:
            # Log any unexpected errors during disconnection
            self.log(f"Error disconnecting LabJack: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
            # Attempt to update state to disconnected even if error occurs
            self._handle_labjack_connection_result(False, None, f"Error during disconnect: {str(e)}")
            return False
            
    # --- Handlers for LabJackDataThread signals --- 
    @pyqtSlot(bool, str)
    def handle_labjack_status(self, connected, message):
        """Handle LabJack connection status updates from the thread."""
        print(f"DEBUG: handle_labjack_status received: connected={connected}, message='{message}'")
        self._handle_labjack_connection_result(connected, self.labjack_thread._labjack_interface if connected else None, message)
        
    def _handle_labjack_connection_result(self, connected, interface_obj, message):
        """Centralized logic to update state based on connection result."""
        if connected and interface_obj:
            self.interfaces['labjack'] = {
                'interface': interface_obj, # Store the interface passed from thread/connect
                'connected': True,
                'thread': self.labjack_thread
            }
            device_info_str = str(getattr(interface_obj, 'device_info', 'N/A'))
            self.log(f"LabJack connection successful. Info: {device_info_str}")
            self.status_update_signal.emit(f"LabJack connected: {device_info_str}", "INFO")
        else:
            if 'labjack' in self.interfaces:
                self.interfaces['labjack']['connected'] = False
                # Don't nullify interface here, disconnect should handle it via thread
            self.log(f"LabJack disconnected or connection failed: {message}", "INFO" if message == "Disconnected by user" else "ERROR")
            self.status_update_signal.emit(f"LabJack disconnected: {message}", "ERROR")

        self.interface_status_signal.emit('labjack', connected) # Signal for UI updates

    @pyqtSlot(str)
    def handle_labjack_error(self, error_message):
        """Handle LabJack errors from the thread."""
        self.log(f"LabJack error: {error_message}", "ERROR")
        self.status_update_signal.emit(f"LabJack error: {error_message}", "ERROR")
    # ---------------------------------------------
    
    def handle_labjack_data(self, data):
        """Handle data received from LabJack thread"""
        # --- ADDED: Log signal reception ---
        # print(f"DEBUG DataCollectionController: handle_labjack_data SLOT TRIGGERED with keys: {list(data.keys())}") # Verbose
        # ---------------------------------

        # Discard data if collection is not active, but allow monitoring for UI updates
        if not self.collecting_data and not (hasattr(self.labjack_thread, 'monitoring_only') and self.labjack_thread.monitoring_only):
            print("DEBUG: Discarding LabJack data as data collection is not active and not in monitoring mode")
            return

        # Ensure timestamp is a float
        if 'timestamp' not in data:
            data['timestamp'] = time.time()
        elif isinstance(data['timestamp'], str):
            try:
                data['timestamp'] = float(data['timestamp'])
            except ValueError:
                data['timestamp'] = time.time()

        # --- Apply Sensor Offset and Conversion ---
        corrected_data = {'timestamp': data['timestamp']} # Start with timestamp
        sensor_controller = getattr(self.main_window, 'sensor_controller', None)
        sensors_found = {}
        if sensor_controller:
            sensors_found = {s.port: s for s in sensor_controller.sensors if getattr(s, 'interface_type', '') == 'LabJack'}
            # print(f"DEBUG LJ Handler: Found {len(sensors_found)} LabJack sensors for lookup.") # Debug

        for key, raw_value in data.items():
            if key == 'timestamp':
                continue # Skip timestamp

            sensor = sensors_found.get(key)
            if sensor:
                try:
                    # Get offset and conversion factor from the sensor model
                    offset = float(getattr(sensor, 'offset', 0.0))
                    conversion_factor = float(getattr(sensor, 'conversion_factor', 1.0))
                    # Ensure raw_value is float before calculation
                    corrected_value = (float(raw_value) * conversion_factor) + offset
                    corrected_data[key] = corrected_value
                    # print(f"DEBUG LJ Correct: {key} Raw={raw_value}, Offset={offset}, Factor={conversion_factor}, Corrected={corrected_value}") # Debug
                except (ValueError, TypeError) as e:
                    # Log error if conversion fails, keep raw value
                    print(f"WARN: Could not apply correction to LabJack {key} value '{raw_value}': {e}")
                    corrected_data[key] = raw_value # Keep raw value on error
            else:
                # If no matching sensor found, keep the raw value
                # print(f"DEBUG LJ Handler: No matching sensor found for key '{key}'. Using raw value.") # Debug
                corrected_data[key] = raw_value

        # Use the corrected data dictionary from now on
        data = corrected_data
        # ------------------------------------------

        # Store data in combined data buffer with "labjack_" prefix only if collecting data
        if self.collecting_data:
            self.combined_data_mutex.lock()
            try:
                # print(f"DEBUG: Adding LabJack data to combined_data with keys: {list(data.keys())}") # Too frequent
                for key, value in data.items():
                    if key != 'timestamp':  
                        prefixed_key = f"labjack_{key}"
                        self.combined_data[prefixed_key] = value
                        # print(f"DEBUG: Added {prefixed_key} = {value} to combined_data") # Too frequent
                    else:
                        self.combined_data['labjack_timestamp'] = value 
                        if 'timestamp' not in self.combined_data or value > self.combined_data['timestamp']:
                            self.combined_data['timestamp'] = value
            finally:
                self.combined_data_mutex.unlock()
        
        # Process the data through SensorController for UI updates
        if self.main_window and hasattr(self.main_window, 'sensor_controller'):
            # print("DEBUG: Calling sensor_controller.update_labjack_data with LabJack data") # Too frequent
            try:
                # Let SensorController process the data (with original non-prefixed keys)
                # Pass the *corrected* data here
                self.main_window.sensor_controller.update_labjack_data(data)
            except Exception as e:
                 print(f"ERROR calling sensor_controller.update_labjack_data: {e}") # Log any error here
                 import traceback
                 traceback.print_exc()
        # else: # Too frequent
            # print("DEBUG: Cannot process LabJack data - sensor_controller not available")

        # --- Store in historical buffer only if collecting data --- 
        if self.collecting_data:
            self.historical_buffer_mutex.lock()
            try:
                # Use the corrected data for historical buffer
                ts = data.get('timestamp')
                if ts is not None:
                    for key, value in data.items():
                        if key != 'timestamp': 
                            sensor_id = f"labjack_{key}" # Use prefixed key
                            try:
                                float_value = float(value)
                                self.historical_buffer[sensor_id].append((ts, float_value))
                                # print(f"DEBUG HIST LJ: Added {sensor_id}: ({ts}, {float_value})") # Very verbose
                            except (ValueError, TypeError):
                                self.log(f"Could not store non-numeric value '{value}' for {sensor_id} in historical buffer", "WARNING")
            except Exception as e:
                 self.log(f"Error storing LabJack data in historical buffer: {e}", "ERROR")
            finally:
                self.historical_buffer_mutex.unlock()
        # ----------------------------------

    def emit_combined_data(self):
        """Emit the combined data from all interfaces at the specified sampling rate"""
        # print("DEBUG: emit_combined_data called") # <<< COMMENTED OUT
        
        # Do not process or emit data if collection is not active
        if not self.collecting_data:
            print("DEBUG: Skipping emit_combined_data as data collection is not active")
            return
        
        if not self.combined_data:
            # print("DEBUG: emit_combined_data called but combined_data is empty, returning") # <<< COMMENTED OUT
            return
            
        current_emit_time = time.time() # Get current time for this emission cycle
        # print(f"DEBUG: Current emit time: {current_emit_time}") # <<< COMMENTED OUT
            
        self.combined_data_mutex.lock()
        try:
            # Make a copy of the combined data to emit
            combined_data_copy = self.combined_data.copy()
            
            # --- Force Update Timestamp --- 
            original_ts = combined_data_copy.get('timestamp')
            combined_data_copy['timestamp'] = current_emit_time
            # print(f"DEBUG: Overwriting timestamp. Original: {original_ts}, New: {combined_data_copy['timestamp']}") # <<< COMMENTED OUT
            # ----------------------------- 
            
            # print(f"DEBUG: Combined data keys (pre-unprefix): {list(combined_data_copy.keys())}") # <<< COMMENTED OUT
            # print(f"DEBUG: Combined data timestamp (forced): {combined_data_copy.get('timestamp', 'No timestamp')}") # <<< COMMENTED OUT
            
            arduino_keys = [k for k in combined_data_copy.keys() if k.startswith('arduino_') and not k.endswith('_timestamp')]
            labjack_keys = [k for k in combined_data_copy.keys() if k.startswith('labjack_') and not k.endswith('_timestamp')]
            other_serial_keys = [k for k in combined_data_copy.keys() if k.startswith('other_serial_') and not k.endswith('_timestamp')]
            # print(f"DEBUG: Arduino data keys: {arduino_keys}") # <<< COMMENTED OUT
            # print(f"DEBUG: LabJack data keys: {labjack_keys}") # <<< COMMENTED OUT
            # print(f"DEBUG: OtherSerial data keys: {other_serial_keys}") # <<< COMMENTED OUT
            
            keys_to_unprefix = arduino_keys + labjack_keys + other_serial_keys
            for prefixed_key in keys_to_unprefix:
                unprefixed_key = None
                if prefixed_key.startswith('arduino_'):
                    unprefixed_key = prefixed_key[len('arduino_'):]
                elif prefixed_key.startswith('labjack_'):
                    unprefixed_key = prefixed_key[len('labjack_'):]
                elif prefixed_key.startswith('other_serial_'):
                    unprefixed_key = prefixed_key[len('other_serial_'):]
                    
                if unprefixed_key and unprefixed_key not in combined_data_copy:
                     if prefixed_key in combined_data_copy: 
                        combined_data_copy[unprefixed_key] = combined_data_copy[prefixed_key]
                        # print(f"DEBUG: Added unprefixed key '{unprefixed_key}' = {combined_data_copy[unprefixed_key]}") # <<< COMMENTED OUT
                     else:
                        # print(f"DEBUG WARNING: Prefixed key '{prefixed_key}' not found in combined_data_copy during unprefixing.") # <<< COMMENTED OUT
                        pass # Keep quiet in release
            
            # print(f"DEBUG: Final combined_data_copy keys before emit: {list(combined_data_copy.keys())}") # <<< COMMENTED OUT
            
        finally:
            self.combined_data_mutex.unlock()
            
        # --- Write data to CSV if collecting and file is open ---
        if self.collecting_data and self.csv_writer and self.csv_file:
            try:
                # Create a dictionary for the row containing only keys present in the header
                row_data = {key: combined_data_copy.get(key, '') for key in self.csv_header}
                
                # Ensure the timestamp format is suitable for CSV (e.g., ISO 8601 or just the float)
                # Using the raw float timestamp generated earlier
                row_data['timestamp'] = combined_data_copy.get('timestamp', time.time()) 
                
                self.csv_writer.writerow(row_data)
            except Exception as e:
                self.log(f"Error writing data row to CSV {self.csv_filename}: {e}", "ERROR")
                # Consider stopping collection or closing file if write errors persist
        # --------------------------------------------------------
            
        # print(f"DEBUG: Emitting combined_data_signal with {len(combined_data_copy)} items") # <<< COMMENTED OUT
        # --- RE-ENABLE SIGNAL EMISSION --- 
        # print("DEBUG: Skipping combined_data_signal emit for freeze test") # <<< COMMENTED OUT
        self.combined_data_signal.emit(combined_data_copy) 
        # ----------------------------------
        
        # --- RE-ENABLE GRAPH PLOTTING CALL --- 
        if self.main_window and hasattr(self.main_window, 'graph_controller') and self.collecting_data:
            # print("DEBUG: Skipping graph update call for freeze test") # <<< COMMENTED OUT
            self.main_window.graph_controller.plot_new_data(combined_data_copy)
        # ------------------------------------
        
        # Update graphs directly if the graph controller is available
        if self.main_window and hasattr(self.main_window, 'graph_controller'):
            # print(f"DEBUG: Calling plot_new_data on graph_controller") # <<< COMMENTED OUT
            if self.collecting_data and not self.main_window.graph_controller.live_plotting_active:
                print("DEBUG: Activating live plotting as data collection is active")
                self.start_time = time.time() if not hasattr(self, 'start_time') or self.start_time is None else self.start_time
                print(f"DEBUG: Using start_time {self.start_time} for graph init")
                self.main_window.graph_controller.start_live_dashboard_update(self.start_time)
            
            gc = self.main_window.graph_controller
            # print(f"DEBUG: Before plot_new_data - live_plotting_active={gc.live_plotting_active}, dashboard_start_time={gc.dashboard_start_time}") # <<< COMMENTED OUT
            
            if gc.dashboard_start_time is None and self.collecting_data:
                print("DEBUG WARNING: dashboard_start_time is None but collecting data. Attempting to restart live dashboard.")
                start_ts = self.start_time if hasattr(self, 'start_time') and self.start_time is not None else current_emit_time
                gc.start_live_dashboard_update(start_ts)
                
            # --- REMOVE TEMPORARY DISABLE BLOCK --- 
            # print("DEBUG: Skipping graph update call for freeze test") 
            if self.collecting_data:
                self.main_window.graph_controller.plot_new_data(combined_data_copy)
            # -------------------------------------
            
        # else: # <<< COMMENTED OUT
            # print(f"DEBUG: Cannot call plot_new_data on graph_controller - not available") # <<< COMMENTED OUT 

    # --- ADDED: Method to retrieve historical data --- 
    def get_historical_data(self, sensor_ids=None, timespan_seconds=None):
        """
        Retrieve historical data for specified sensors and timespan.

        Args:
            sensor_ids (list[str], optional): List of sensor identifiers (e.g., 'arduino_temp1', 'labjack_AIN0'). 
                                            If None or empty, returns data for all sensors.
            timespan_seconds (float, optional): How far back in seconds to retrieve data from the current time. 
                                                If None, retrieves all available data within the buffer limit.

        Returns:
            dict[str, dict[str, list]]: Data in the format {sensor_id: {'time': [...], 'value': [...]}}
        """
        self.log(f"get_historical_data called for sensors: {sensor_ids}, timespan: {timespan_seconds}s", "DEBUG")
        results = collections.defaultdict(lambda: {'time': [], 'value': []})
        current_time = time.time()

        # Determine the cutoff time if a timespan is specified
        cutoff_time = None
        if timespan_seconds is not None:
            try:
                cutoff_time = current_time - float(timespan_seconds)
            except ValueError:
                 self.log(f"Invalid timespan_seconds value: {timespan_seconds}", "ERROR")
                 return {}

        # First, try to get data from the live historical buffer
        historical_buffer_data = self._get_data_from_historical_buffer(sensor_ids, cutoff_time)
        
        # If there's no data in the historical buffer (because data collection hasn't started yet),
        # use the data loaded from the CSV file during initialization
        if not historical_buffer_data and hasattr(self, 'csv_historical_data') and self.csv_historical_data:
            print(f"DEBUG: No data in historical buffer, using data from CSV file")
            
            # Determine which sensors to process from CSV data
            csv_data = {}
            if sensor_ids:
                # For each requested sensor ID, check if it exists in CSV data
                for sensor_id in sensor_ids:
                    if sensor_id in self.csv_historical_data:
                        # Direct match
                        csv_data[sensor_id] = self.csv_historical_data[sensor_id]
                    else:
                        # Try to find a matching key for sensors with multiple representations
                        for csv_key in self.csv_historical_data.keys():
                            # For example, 'arduino_K-Type1' in CSV might match 'arduino_k-type1' in request
                            if sensor_id.lower() == csv_key.lower() or sensor_id in csv_key or csv_key in sensor_id:
                                csv_data[sensor_id] = self.csv_historical_data[csv_key]
                                print(f"DEBUG: Matched requested sensor {sensor_id} to CSV key {csv_key}")
                                break
            else:
                # If no specific sensors requested, use all CSV data
                csv_data = self.csv_historical_data
            
            # Apply timespan filter if specified
            if cutoff_time is not None and csv_data:
                for sensor_id, data in csv_data.items():
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    # Find indices where time >= cutoff_time
                    indices = np.where(times >= cutoff_time)[0]
                    if len(indices) > 0:
                        results[sensor_id]['time'] = times[indices].tolist()
                        results[sensor_id]['value'] = values[indices].tolist()
            else:
                # No timespan filter, use all CSV data
                for sensor_id, data in csv_data.items():
                    results[sensor_id]['time'] = data['time']
                    results[sensor_id]['value'] = data['value']
        else:
            # Use data from historical buffer
            results.update(historical_buffer_data)
            
        # Calculate relative time if data exists
        self._calculate_relative_time(results)
            
        # Convert defaultdict to regular dict for return
        return dict(results)
        
    def _get_data_from_historical_buffer(self, sensor_ids=None, cutoff_time=None):
        """Helper method to get data from the historical buffer."""
        results = collections.defaultdict(lambda: {'time': [], 'value': []})
        
        self.historical_buffer_mutex.lock()
        try:
            # Determine which sensors to process
            sensors_to_process = sensor_ids
            if not sensors_to_process: # If None or empty list, get all sensors
                sensors_to_process = list(self.historical_buffer.keys())
            
            self.log(f"Processing historical data for: {sensors_to_process}", "DEBUG")

            for sensor_id in sensors_to_process:
                if sensor_id in self.historical_buffer:
                    data_deque = self.historical_buffer[sensor_id]
                    
                    # Efficiently filter deque based on timestamp
                    if cutoff_time is not None:
                        # Iterate from right (newest) and stop when timestamp is too old
                        for ts, val in reversed(data_deque):
                            try:
                                # Ensure timestamp is float before comparison
                                float_ts = float(ts) 
                                if float_ts >= cutoff_time:
                                    results[sensor_id]['time'].append(float_ts) # Store as float
                                    results[sensor_id]['value'].append(val)
                                else:
                                    break # Deque is ordered by time, no need to check further back
                            except (ValueError, TypeError):
                                self.log(f"Skipping historical data point for {sensor_id} due to invalid timestamp: {ts}", "WARNING")
                                continue # Skip this point
                        # Reverse the lists to maintain chronological order
                        results[sensor_id]['time'].reverse()
                        results[sensor_id]['value'].reverse()
                    else:
                        # No timespan filter, get all data from deque
                        for ts, val in data_deque:
                            try:
                                # Ensure timestamp is float before adding
                                float_ts = float(ts)
                                results[sensor_id]['time'].append(float_ts) # Store as float
                                results[sensor_id]['value'].append(val)
                            except (ValueError, TypeError):
                                self.log(f"Skipping historical data point for {sensor_id} due to invalid timestamp: {ts}", "WARNING")
                                continue # Skip this point
                            
                    # Debug log for retrieved data points
                    # self.log(f"Retrieved {len(results[sensor_id]['time'])} points for {sensor_id}") 

        except Exception as e:
            self.log(f"Error retrieving historical data: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            return {} # Return empty on error
        finally:
            self.historical_buffer_mutex.unlock()
            
        return results
        
    def _calculate_relative_time(self, results):
        """Helper method to calculate relative time for the data."""
        min_time = None
        if results:
            all_times = []
            for sensor_id in results:
                if results[sensor_id]['time']:
                    all_times.extend(results[sensor_id]['time'])
            if all_times:
                min_time = min(all_times)
        
        if min_time is not None:
            for sensor_id in results:
                if results[sensor_id]['time']:
                     # Use numpy for efficient subtraction
                    times_array = np.array(results[sensor_id]['time'], dtype=float)
                    relative_times = times_array - min_time
                    results[sensor_id]['time'] = relative_times.tolist() # Convert back to list
        # ---------------------------------------------
            
        # Convert defaultdict back to regular dict for return
        return dict(results)
    # -------------------------------------------------- 

    def read_historical_data_from_csv(self):
        """
        Read historical data from the most recent CSV file in the run directory.
        
        Returns:
            dict: Historical data in the format {sensor_id: {'time': [...], 'value': [...]}}
        """
        import glob
        import json
        
        try:
            # Determine the run directory by reading settings.json
            # settings.json is in the parent directory of the app folder, where main.py is
            program_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            settings_path = os.path.join(program_dir, 'settings.json')
            run_dir = None
            
            print(f"DEBUG: Looking for settings.json at: {settings_path}")
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, 'r') as settings_file:
                        settings = json.load(settings_file)
                        default_project_dir = settings.get('default_project_dir', '')
                        last_project = settings.get('last_project', '')
                        last_test_series = settings.get('last_test_series', '')
                        
                        print(f"DEBUG: Settings loaded - Default Project Dir: {default_project_dir}, Last Project: {last_project}, Last Test Series: {last_test_series}")
                        self.log(f"Settings loaded from {settings_path}")
                        
                        # Construct the path to the test series folder
                        if default_project_dir and last_project and last_test_series:
                            project_path = os.path.join(default_project_dir, last_project)
                            test_series_path = os.path.join(project_path, last_test_series)
                            print(f"DEBUG: Constructed test series path: {test_series_path}")
                            
                            if os.path.exists(test_series_path):
                                # Find the newest run folder in the test series path
                                run_dirs = glob.glob(os.path.join(test_series_path, 'run_*'))
                                if run_dirs:
                                    run_dir = max(run_dirs, key=os.path.getmtime)
                                    print(f"DEBUG: Selected most recent run directory: {run_dir}")
                                    self.log(f"Using most recent run directory: {run_dir}")
                                else:
                                    print(f"DEBUG: No run directories found in {test_series_path}")
                                    self.log(f"No run directories found in {test_series_path}", "WARNING")
                            else:
                                print(f"DEBUG: Test series path does not exist: {test_series_path}")
                                self.log(f"Test series path does not exist: {test_series_path}", "WARNING")
                        else:
                            print("DEBUG: Incomplete settings data for constructing path")
                            self.log("Incomplete settings data for constructing path", "WARNING")
                except json.JSONDecodeError as jde:
                    print(f"DEBUG: Error decoding settings.json: {str(jde)}")
                    self.log(f"Error decoding settings.json: {str(jde)}", "ERROR")
            else:
                print(f"DEBUG: settings.json not found at {settings_path}")
                self.log(f"settings.json not found at {settings_path}", "WARNING")
            
            # If run_dir is still not set, fall back to previous logic
            if not run_dir or not os.path.exists(run_dir):
                print("DEBUG: Falling back to previous run directory search logic")
                self.log("Falling back to previous run directory search logic", "WARNING")
                # If run_directory is not set, try to find the most recent run folder
                base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'runs')
                print(f"DEBUG: Checking base directory for runs: {base_dir}")
                if not os.path.exists(base_dir):
                    self.log(f"Run directory not found: {base_dir}", "WARNING")
                    print(f"DEBUG: Base directory does not exist: {base_dir}")
                    # Try alternative paths
                    base_dir_alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')
                    print(f"DEBUG: Trying alternative base directory: {base_dir_alt}")
                    if not os.path.exists(base_dir_alt):
                        self.log(f"Alternative run directory not found: {base_dir_alt}", "WARNING")
                        print(f"DEBUG: Alternative base directory does not exist: {base_dir_alt}")
                        return {}
                    else:
                        base_dir = base_dir_alt
                        self.log(f"Using alternative base directory: {base_dir}")
                
                run_dirs = glob.glob(os.path.join(base_dir, 'run_*'))
                if not run_dirs:
                    self.log("No run directories found", "WARNING")
                    print(f"DEBUG: No run directories found in {base_dir}")
                    return {}
                
                run_dir = max(run_dirs, key=os.path.getmtime)
                self.log(f"Using most recent run directory: {run_dir}")
                print(f"DEBUG: Selected most recent run directory: {run_dir}")
            
            # Find the most recent CSV file in the run directory
            csv_files = glob.glob(os.path.join(run_dir, 'rundata_*.csv'))
            if not csv_files:
                self.log(f"No CSV files found in {run_dir}", "WARNING")
                print(f"DEBUG: No CSV files found in {run_dir}")
                # Try a broader search in case naming convention differs
                csv_files = glob.glob(os.path.join(run_dir, '*.csv'))
                if not csv_files:
                    self.log(f"No CSV files of any name found in {run_dir}", "WARNING")
                    print(f"DEBUG: No CSV files of any name found in {run_dir}")
                    return {}
                else:
                    self.log(f"Found CSV files with different naming: {csv_files}")
                    print(f"DEBUG: Found CSV files with different naming: {csv_files}")
            
            latest_csv = max(csv_files, key=os.path.getmtime)
            self.log(f"Reading historical data from CSV: {latest_csv}")
            print(f"DEBUG: Reading from latest CSV: {latest_csv}")
            
            # Read the CSV file
            historical_data = collections.defaultdict(lambda: {'time': [], 'value': []})
            row_count = 0
            with open(latest_csv, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                headers = reader.fieldnames
                print(f"DEBUG: CSV headers: {headers}")
                for row in reader:
                    row_count += 1
                    try:
                        timestamp = float(row['timestamp'])
                        for key, value in row.items():
                            if key != 'timestamp':
                                try:
                                    float_value = float(value)
                                    historical_data[key]['time'].append(timestamp)
                                    historical_data[key]['value'].append(float_value)
                                except ValueError:
                                    continue  # Skip non-numeric values
                    except (ValueError, KeyError):
                        continue  # Skip rows with invalid timestamp
            
            print(f"DEBUG: Read {row_count} rows from CSV")
            for key in historical_data:
                print(f"DEBUG: Sensor {key} has {len(historical_data[key]['time'])} data points from CSV")
            self.log(f"Successfully read historical data from {latest_csv} with {row_count} rows")
            # Convert defaultdict to regular dict for return
            return dict(historical_data)
        except Exception as e:
            self.log(f"Error reading historical data from CSV: {str(e)}", "ERROR")
            print(f"DEBUG: Exception in read_historical_data_from_csv: {str(e)}")
            import traceback
            print(f"DEBUG: Traceback: {traceback.format_exc()}")
            return {}
    # -------------------------------------------------- 

    # Add a method to explicitly reconnect (used when user clicks Connect button)
    def explicit_reconnect_other_serial(self, port, baud_rate=9600, data_bits=8, parity="None", 
                                      stop_bits=1, poll_interval=1.0, sequence=None):
        """Explicitly reconnect to Other Serial device (user initiated)"""
        self._explicit_reconnect = True
        result = self.connect_other_serial(port, baud_rate, data_bits, parity, stop_bits, poll_interval, sequence)
        self._explicit_reconnect = False
        return result