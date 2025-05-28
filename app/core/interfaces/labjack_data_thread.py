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

    def __init__(self, labjack_interface=None, sampling_rate=10, parent=None):
        super().__init__(parent)
        self._labjack_interface = labjack_interface
        self._sampling_rate = sampling_rate
        self._running = False
        self._connected = False
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
        if not LabJackInterface:
             self.error_signal.emit("LabJackInterface library not available.")
             self.connection_status_signal.emit(False, "LabJack library missing")
             return False
             
        if not self._labjack_interface:
            self.error_signal.emit("LabJack interface object not set.")
            self.connection_status_signal.emit(False, "Interface not set")
            return False
            
        try:
            print("DEBUG LabJackThread: Attempting connection...")
            self._labjack_interface.connect()
            self._connected = True
            print("DEBUG LabJackThread: Connection successful.")
            self.connection_status_signal.emit(True, "Connected successfully")
            return True
        except Exception as e:
            error_msg = f"LabJackThread connection error: {e}"
            print(f"ERROR: {error_msg}")
            self.error_signal.emit(error_msg)
            self.connection_status_signal.emit(False, f"Connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """Disconnects from the LabJack device."""
        print("DEBUG LabJackThread: Disconnect called.")
        self.stop() # Signal the run loop to stop
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
        
        read_interval = 1.0 / self._sampling_rate if self._sampling_rate > 0 else 1.0 # seconds

        while not self._stop_event.is_set():
            loop_start_time = time.time()
            
            if not self._connected or not self._labjack_interface:
                print("DEBUG LabJackThread: Exiting run loop - not connected or no interface.") # Added exit reason
                break # Exit loop if disconnected or interface lost

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
                    print(f"DEBUG LabJackThread: Emitting data_received_signal with keys: {list(data.keys())}")
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