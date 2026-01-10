from PyQt6.QtCore import QThread, pyqtSignal
import time
import logging

logger = logging.getLogger(__name__)

class PluginPollingThread(QThread):
    """
    A dedicated thread for polling custom plugin interfaces.
    Following the blueprint for new data interfaces.
    """
    data_received_signal = pyqtSignal(dict)
    connection_status_signal = pyqtSignal(str, bool)
    error_signal = pyqtSignal(str, str)

    def __init__(self, interface_instance, name, poll_rate_hz=10.0):
        super().__init__()
        self.interface = interface_instance
        self.interface_name = name
        self.poll_interval = 1.0 / max(0.1, poll_rate_hz)
        self.running = False
        self._is_connected = False

    def set_poll_rate(self, hz):
        self.poll_interval = 1.0 / max(0.1, hz)

    def run(self):
        self.running = True
        logger.info(f"Starting polling thread for plugin: {self.interface_name}")
        
        while self.running:
            try:
                if not self._is_connected:
                    if self.interface.connect():
                        self._is_connected = True
                        self.connection_status_signal.emit(self.interface_name, True)
                    else:
                        time.sleep(2.0) # Wait before retry
                        continue

                data = self.interface.read_data()
                if data:
                    self.data_received_signal.emit(data)
                
            except Exception as e:
                logger.error(f"Error in plugin thread {self.interface_name}: {e}")
                self.error_signal.emit(self.interface_name, str(e))
                # If error occurred, assume connection might be lost
                if self._is_connected:
                    self._is_connected = False
                    self.connection_status_signal.emit(self.interface_name, False)
                
            time.sleep(self.poll_interval)

    def stop(self):
        self.running = False
        if self._is_connected:
            self._is_connected = False
            self.connection_status_signal.emit(self.interface_name, False)
        # Don't wait here to avoid blocking UI, 
        # let the caller decide if they want to wait.
        
    def is_connected(self):
        return self._is_connected
