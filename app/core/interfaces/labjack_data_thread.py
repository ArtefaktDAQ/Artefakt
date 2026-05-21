import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, QMutex

# Import LabJackInterface from the app.core.interfaces package
try:
    from app.core.interfaces.labjack_interface import LabJackInterface
except ImportError as e:
    print(f"ERROR: Failed to import LabJackInterface in LabJackDataThread: {e}")
    LabJackInterface = None # Allow importing the file but indicate missing dependency


class LabJackDataThread(QThread):
    """Handles LabJack communication in a separate thread."""
    data_received_signal = pyqtSignal(dict)
    connection_status_signal = pyqtSignal(bool, str) # connected (bool), message (str)
    error_signal = pyqtSignal(str)

    def __init__(self, labjack_interface=None, sampling_rate=1, parent=None):
        super().__init__(parent)
        self._labjack_interface = labjack_interface
        self._sampling_rate = sampling_rate
        self.device_type = "ANY"
        self.connection_type = "ANY"
        self.port = "ANY"
        self.auto_reconnect = False
        self._running = False
        self._connected = False
        self._last_error = ""
        self._mutex = QMutex()
        self._stop_event = threading.Event()

    def set_interface(self, interface):
        """Set the LabJack interface object."""
        self._labjack_interface = interface

    def set_sampling_rate(self, rate):
        """Set the sampling rate (Hz)."""
        self._sampling_rate = rate

    def connect(self):
        """Connects to the LabJack device within the thread."""
        self._last_error = ""
        if not LabJackInterface:
             self._last_error = "LabJackInterface library not available."
             self.error_signal.emit(self._last_error)
             self.connection_status_signal.emit(False, "LabJack library missing")
             return False
             
        if not self._labjack_interface:
            try:
                # If no interface set, create one using thread's attributes
                # This happens when connecting from the settings dialog for the first time
                self._labjack_interface = LabJackInterface(
                    device_type=self.device_type, 
                    connection_type=self.connection_type, 
                    port=self.port,
                    auto_reconnect=self.auto_reconnect
                )
                print(f"DEBUG LabJackThread: Created new LabJackInterface: {self.device_type}/{self.connection_type}/{self.port}")
            except Exception as e:
                self._last_error = f"Failed to initialize LabJack interface: {e}"
                print(f"ERROR: {self._last_error}")
                self.error_signal.emit(self._last_error)
                self.connection_status_signal.emit(False, self._last_error)
                return False
            
        try:
            # Sync thread attributes to interface before connecting if they changed from UI
            self._labjack_interface.device_type = self.device_type
            self._labjack_interface.connection_type = self.connection_type
            self._labjack_interface.identifier = self.port
            self._labjack_interface.auto_reconnect = self.auto_reconnect
            
            print(f"DEBUG LabJackThread: Attempting connection to {self.device_type} via {self.connection_type} ({self.port})...")
            success = self._labjack_interface.connect()
            if success:
                self._connected = True
                print("DEBUG LabJackThread: Connection successful.")
                self.connection_status_signal.emit(True, "Connected successfully")
                
                # Automatically start the thread if not running
                if not self.isRunning():
                    print("DEBUG LabJackThread: Starting thread for data reading")
                    self.start()
                    
                return True
            else:
                self._last_error = getattr(self._labjack_interface, 'error_message', "Connection failed")
                print(f"DEBUG LabJackThread: Connection failed: {self._last_error}")
                self._connected = False
                self.connection_status_signal.emit(False, "Connection failed")
                return False
        except Exception as e:
            self._last_error = f"LabJackThread connection error: {e}"
            print(f"ERROR: {self._last_error}")
            self.error_signal.emit(self._last_error)
            self.connection_status_signal.emit(False, f"Connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """Disconnects from the LabJack device."""
        print("DEBUG LabJackThread: Disconnect called.")
        self.stop() # Signal the run loop to stop
        if self.isRunning():
            # Wait briefly for the run loop to exit to avoid concurrent access on reconnect
            self.wait(2000)
        if self._labjack_interface and self._connected:
            try:
                self._labjack_interface.disconnect()
                print("DEBUG LabJackThread: Interface disconnected.")
            except Exception as e:
                 error_msg = f"LabJackThread disconnect error: {e}"
                 print(f"ERROR: {error_msg}")
                 self.error_signal.emit(error_msg)
        self._connected = False
        self.connection_status_signal.emit(False, "Disconnected")

    def is_connected(self):
        """Check if connected to LabJack"""
        return self._connected and self._labjack_interface and self._labjack_interface.is_connected()
        
    @property
    def error_message(self):
        """Get the last error message from the interface"""
        if self._last_error:
            return self._last_error
        if not LabJackInterface:
            return "LabJack library (labjack-ljm) not installed or drivers missing."
        if self._labjack_interface:
            return getattr(self._labjack_interface, 'error_message', "Unknown error")
        return "Interface not initialized"

    def get_error(self):
        """Get the last error message (legacy)"""
        return self.error_message

    def run(self):
        """Main thread loop for reading data."""
        # --- RE-CHECK CONNECTION AT START --- 
        if not self._labjack_interface:
            print("DEBUG LabJackThread: run() called but no interface set. Exiting thread.")
            return
            
        if not self._connected:
             # Maybe the connection happened outside, let's check the interface object
             if hasattr(self._labjack_interface, 'connected') and self._labjack_interface.connected:
                 print("DEBUG LabJackThread: Interface was connected externally, setting flag and proceeding.")
                 self._connected = True
             else:
                 print("DEBUG LabJackThread: run() called but not connected. Exiting thread.")
                 return # Still exit if not connected
        # ---------------------------------

        print(f"DEBUG LabJackThread: Starting run loop with sampling rate {self._sampling_rate} Hz.")
        self._running = True
        self._stop_event.clear()
        
        while not self._stop_event.is_set():
            # Calculate interval inside the loop so it responds to changes
            read_interval = 1.0 / self._sampling_rate if self._sampling_rate > 0 else 1.0 # seconds
            
            loop_start_time = time.time()
            
            if not self._labjack_interface:
                print("DEBUG LabJackThread: Exiting run loop - no interface.")
                break

            # Handle reconnection if needed
            if not self._connected or not self._labjack_interface.is_connected():
                if getattr(self._labjack_interface, 'auto_reconnect', False):
                    print("DEBUG LabJackThread: Connection lost, attempting reconnect...")
                    if self._labjack_interface.connect():
                        self._connected = True
                        print("DEBUG LabJackThread: Reconnected successfully.")
                        self.connection_status_signal.emit(True, "Reconnected successfully")
                    else:
                        # Wait a bit before next attempt
                        self._stop_event.wait(5.0)
                        continue
                else:
                    print("DEBUG LabJackThread: Exiting run loop - not connected.")
                    self.connection_status_signal.emit(False, "Connection lost")
                    break

            try:
                # --- Read Data ---
                # print("DEBUG LabJackThread: Calling read_data()") # Optional: Very frequent log
                data = self._labjack_interface.read_data()
                # ---------------
                
                if data:
                    # print(f"DEBUG LabJackThread: Read data: {list(data.keys())}") # Verbose
                    if 'timestamp' not in data:
                        data['timestamp'] = time.time()
                    
                    # --- ADDED: Log before emit --- 
                    # print(f"DEBUG LabJackThread: Emitting data_received_signal with keys: {list(data.keys())}")
                    self.data_received_signal.emit(data)
                    # -----------------------------
                # else: # Optional: Log when no data is read
                    # print("DEBUG LabJackThread: read_data() returned no data.") 
                    
            except Exception as e:
                error_msg = f"LabJackThread error reading data: {e}"
                print(f"ERROR: {error_msg}")
                self.error_signal.emit(error_msg)
                time.sleep(0.5) # Pause briefly after error
                
            # Calculate sleep time to maintain sampling rate
            loop_end_time = time.time()
            elapsed = loop_end_time - loop_start_time
            sleep_time = max(0, read_interval - elapsed) 
            
            if sleep_time > 0:
                self._stop_event.wait(sleep_time) # Use wait for better interruptibility

        self._running = False
        print("DEBUG LabJackThread: Run loop finished.")

    def stop(self):
        """Signals the run loop to stop."""
        print("DEBUG LabJackThread: Stop requested.")
        self._stop_event.set()

    # Add start_data_collection / stop_data_collection if needed for file logging etc.
    # For now, the thread starts reading immediately upon connection. 