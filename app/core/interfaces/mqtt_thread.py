"""
MQTT Interface Thread

Handles communication with MQTT brokers in a separate thread.
"""

import time
import threading
import queue
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from app.core.interfaces.mqtt_interface import MQTTInterface


class MQTTDataThread(QThread):
    """Thread for handling MQTT communication"""
    
    # Define signals for thread-safe communication
    data_received_signal = pyqtSignal(dict)  # Signal emitted when new data is received
    connection_status_signal = pyqtSignal(bool, str)  # For connection status updates
    error_signal = pyqtSignal(str)  # For error notifications
    connection_lost_signal = pyqtSignal(str)  # Signal when connection is unexpectedly lost
    
    # Thread termination timeout in milliseconds
    THREAD_STOP_TIMEOUT_MS = 3000
    
    def __init__(self, parent=None):
        """Initialize the MQTT interface thread"""
        super().__init__(parent)
        
        # Create MQTT interface
        self.mqtt = None
        
        # Thread control
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        
        self.monitoring_only = False
        self.mutex = QMutex()
        
        # Data collection settings
        self.poll_interval = 0.1  # Check buffer every 100ms
        self.auto_reconnect = True
        self._last_reconnect_attempt = 0
        self._reconnect_interval = 5.0
        
        # Data buffer for external access
        self.data_queue = queue.Queue(maxsize=1000)
        self._dropped_data_count = 0
        
        # Latest data storage
        self.latest_data = {}
        self.data_mutex = QMutex()
        
        # Store connection params for auto-reconnect
        self.connection_params = {}

    @property
    def running(self):
        return not self._stop_event.is_set()

    @property
    def paused(self):
        return not self._pause_event.is_set()

    def _on_connection_lost(self, error_message):
        """Callback when MQTT connection is lost"""
        print(f"MQTTThread: Connection lost - {error_message}")
        self.connection_lost_signal.emit(error_message)
        self.connection_status_signal.emit(False, f"Connection lost: {error_message}")

    def connect(self, broker="localhost", port=1883, client_id="ArtefaktDAQ", 
                username=None, password=None, keepalive=60):
        """Connect to the MQTT broker"""
        try:
            print(f"MQTTThread: Attempting to connect to MQTT broker at {broker}:{port}")
            
            # Save params for reconnect
            self.connection_params = {
                'broker': broker,
                'port': port,
                'client_id': client_id,
                'username': username,
                'password': password,
                'keepalive': keepalive
            }
            
            # Create interface
            self.mqtt = MQTTInterface(**self.connection_params)
            self.mqtt.on_connection_lost = self._on_connection_lost
            
            success = self.mqtt.connect()
            if success:
                print(f"MQTTThread: Successfully connected to MQTT broker")
                self.connection_status_signal.emit(True, f"Connected to {broker}")
                
                # Start the polling thread
                if not self.isRunning():
                    self._stop_event.clear()
                    self._pause_event.set()
                    self.monitoring_only = True
                    self.start()
                
                return True
            else:
                error_msg = self.mqtt.get_error()
                print(f"MQTTThread: Failed to connect: {error_msg}")
                self.connection_status_signal.emit(False, error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Failed to connect to MQTT: {str(e)}"
            print(f"MQTTThread: Exception during connect: {error_msg}")
            self.connection_status_signal.emit(False, error_msg)
            return False

    def disconnect(self):
        """Disconnect from the MQTT broker"""
        if self.mqtt:
            print("MQTTThread: Disconnecting from MQTT broker")
            self._stop_event.set()
            self._pause_event.set()
            
            if self.isRunning():
                if not self.wait(self.THREAD_STOP_TIMEOUT_MS):
                    self.terminate()
                    self.wait(1000)
            
            self.mqtt.disconnect()
            self.connection_status_signal.emit(False, "Disconnected from MQTT")
            
            with QMutexLocker(self.data_mutex):
                self.latest_data = {}

    def is_connected(self):
        return self.mqtt and self.mqtt.is_connected()

    def subscribe(self, topic):
        """Subscribe to a topic"""
        if self.mqtt:
            return self.mqtt.subscribe(topic)
        return False

    def unsubscribe(self, topic):
        """Unsubscribe from a topic"""
        if self.mqtt:
            return self.mqtt.unsubscribe(topic)
        return False

    def publish(self, topic, payload):
        """Publish a message"""
        if self.mqtt:
            return self.mqtt.write_data((topic, payload))
        return False

    def run(self):
        """Thread main loop for polling the MQTT buffer"""
        print("MQTT thread started")
        
        while not self._stop_event.is_set():
            loop_start = time.time()
            
            try:
                if not self._pause_event.wait(timeout=0.1):
                    continue
                
                if self._stop_event.is_set():
                    break
                
                if not self.is_connected():
                    if self.auto_reconnect:
                        current_time = time.time()
                        if current_time - self._last_reconnect_attempt >= self._reconnect_interval:
                            self._last_reconnect_attempt = current_time
                            print("MQTTThread: Connection lost, attempting reconnect...")
                            if self.mqtt.connect():
                                print("MQTTThread: Reconnected successfully")
                                self.connection_status_signal.emit(True, f"Reconnected to {self.mqtt.broker}")
                            else:
                                print("MQTTThread: Reconnect failed")
                        
                        self._stop_event.wait(timeout=1.0)
                        continue
                    else:
                        break
                
                # Read data from the MQTT interface buffer
                data = self.mqtt.read_data()
                
                if data:
                    # Update latest data
                    with QMutexLocker(self.data_mutex):
                        self.latest_data.update(data)
                    
                    # Add timestamp
                    data['timestamp'] = time.time()
                    
                    # Emit signal
                    self.data_received_signal.emit(data)
                    
                    # Queue for recording if not monitoring only
                    with QMutexLocker(self.mutex):
                        is_monitoring_only = self.monitoring_only
                        
                    if not is_monitoring_only:
                        try:
                            self.data_queue.put_nowait(data)
                        except queue.Full:
                            self._dropped_data_count += 1
                            try:
                                self.data_queue.get_nowait()
                                self.data_queue.put_nowait(data)
                            except:
                                pass
                
                # Small sleep to avoid spinning too fast
                elapsed = time.time() - loop_start
                remaining = self.poll_interval - elapsed
                if remaining > 0:
                    self._stop_event.wait(timeout=remaining)
                    
            except Exception as e:
                error_msg = f"Error in MQTT thread: {str(e)}"
                print(error_msg)
                self.error_signal.emit(error_msg)
                self._stop_event.wait(timeout=1.0)
        
        print("MQTT thread stopped")
