from PyQt6.QtCore import QThread, pyqtSignal
import time
import logging

logger = logging.getLogger(__name__)

class PluginPollingThread(QThread):
    """
    A dedicated thread for polling custom plugin interfaces.

    Unlike Arduino/MQTT threads, plugins always poll and emit live values.
    monitoring_only tracks run vs monitor mode for API parity with other
    threads; it does not suppress reads (live UI must keep updating).
    """
    data_received_signal = pyqtSignal(dict)
    connection_status_signal = pyqtSignal(str, bool)
    error_signal = pyqtSignal(str, str)

    def __init__(self, interface_instance, name, poll_rate_hz=10.0):
        super().__init__()
        self.interface = interface_instance
        self.interface_name = name
        self.poll_rate_hz = poll_rate_hz
        self.poll_interval = 1.0 / max(0.1, poll_rate_hz)
        self.running = False
        # True while no active run; False during a collection run.
        # Kept for status/API parity — does not gate read_data().
        self.monitoring_only = True
        self._disconnect_on_stop = False
        self._is_connected = self.interface.is_connected()

    def set_poll_rate(self, hz):
        self.poll_rate_hz = hz
        self.poll_interval = 1.0 / max(0.1, hz)

    def start_data_collection(self):
        """Mark thread as part of an active run (polling continues either way)."""
        self.monitoring_only = False

    def stop_data_collection(self):
        """Mark thread as monitor-only after a run (polling continues for live UI)."""
        self.monitoring_only = True

    def run(self):
        self.running = True
        self._disconnect_on_stop = False
        logger.info(f"Starting polling thread for plugin: {self.interface_name} (initial state: {'connected' if self._is_connected else 'not connected'})")

        try:
            while self.running:
                try:
                    if not self._is_connected:
                        if self.interface.connect():
                            self._is_connected = True
                            self.connection_status_signal.emit(self.interface_name, True)
                        else:
                            time.sleep(2.0) # Wait before retry
                            continue

                    # Double-check interface still thinks it's connected
                    if not self.interface.is_connected():
                        self._is_connected = False
                        self.connection_status_signal.emit(self.interface_name, False)
                        continue

                    # Always poll: live values and automation need fresh data
                    # even when monitoring_only is True (no active run).
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
                        try:
                            self.interface.disconnect()
                        except Exception as disconnect_err:
                            logger.error(
                                f"Error disconnecting plugin {self.interface_name} after poll error: {disconnect_err}"
                            )

                time.sleep(self.poll_interval)
        finally:
            if self._disconnect_on_stop:
                try:
                    self.interface.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting plugin {self.interface_name}: {e}")
                finally:
                    self._is_connected = False
                    self.connection_status_signal.emit(self.interface_name, False)

    def stop(self, disconnect_interface=False):
        self._disconnect_on_stop = disconnect_interface
        self.running = False
        if self._is_connected and disconnect_interface:
            self._is_connected = False
            self.connection_status_signal.emit(self.interface_name, False)
        # Don't wait here to avoid blocking UI, 
        # let the caller decide if they want to wait.
        
    def is_connected(self):
        return self._is_connected
