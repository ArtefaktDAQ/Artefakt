import threading
import time
import queue
import logging

from app.core.interfaces.base_interface import BaseInterface

logger = logging.getLogger(__name__)

# Try to import LabJack LJM library (Windows only, or Linux with manual driver setup)
LABJACK_AVAILABLE = False
ljm = None

# Create a dummy LJMError class for exception handling when library is not available
class DummyLJMError(Exception):
    """Placeholder exception class when LJM library is not installed"""
    pass

# Create a dummy ljm module for when the library is not available
class DummyLJM:
    """Dummy LJM module that provides the LJMError attribute"""
    LJMError = DummyLJMError

try:
    from labjack import ljm as _ljm
    ljm = _ljm
    LABJACK_AVAILABLE = True
    logger.info("LabJack LJM library found and imported successfully.")
except ImportError:
    logger.warning("LabJack LJM library not found. LabJack support will be disabled.")
    logger.warning("To enable LabJack support:")
    logger.warning("  1. Install LabJack drivers from https://labjack.com/support/software/installers")
    logger.warning("  2. pip install labjack-ljm")
    # Use the dummy module so ljm.LJMError references work
    ljm = DummyLJM()


class LabJackInterface(BaseInterface):
    """Interface for LabJack T-series devices
    
    Thread-safe implementation with proper locking for handle access,
    bounded queues, and optional auto-reconnect behavior.
    """
    
    # Maximum queue sizes to prevent memory exhaustion
    MAX_STATUS_QUEUE_SIZE = 100
    MAX_DATA_QUEUE_SIZE = 1000
    
    # Cache timeout for EF channels (seconds)
    EF_CACHE_TIMEOUT = 30.0
    
    def __init__(self, port="ANY", connection_type="ANY", device_type="T7", 
                 sampling_rate=1000, auto_reconnect=False):
        """
        Initialize the LabJack interface
        
        Args:
            port: Port/identifier (or "ANY" for auto-detect)
            connection_type: Connection type ("USB", "TCP", "ETHERNET", "WIFI", or "ANY")
            device_type: Device type ("T7", "T4", or "ANY")
            sampling_rate: Sampling rate in Hz
            auto_reconnect: Whether to automatically try to reconnect on disconnect (default False)
        """
        super().__init__(name="LabJack")
        
        if not LABJACK_AVAILABLE:
            self.error_message = "LabJack LJM library not installed"
            logger.warning("LabJackInterface created but LJM library not available")
            
        self.port = port
        self.connection_type = connection_type
        self.device_type = device_type
        self.sampling_rate = sampling_rate
        self.auto_reconnect = auto_reconnect
        
        # Handle and connection state - protected by lock
        self._handle = None
        self._handle_lock = threading.RLock()  # Reentrant lock for handle access
        
        self.device_info = {}
        self._status_thread = None
        self._data_thread = None
        
        # Bounded queues to prevent memory exhaustion
        self._status_queue = queue.Queue(maxsize=self.MAX_STATUS_QUEUE_SIZE)
        self._data_queue = queue.Queue(maxsize=self.MAX_DATA_QUEUE_SIZE)
        self._stop_event = threading.Event()
        
        # EF channel cache for optimization
        self._ef_channels_cache = []
        self._ef_cache_time = 0
        self._tc_channels_cache = []
        self._tc_cache_time = 0
        
        # Connection health tracking
        self._last_successful_read = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        
    @property
    def handle(self):
        """Thread-safe access to the device handle"""
        with self._handle_lock:
            return self._handle
    
    @handle.setter
    def handle(self, value):
        """Thread-safe setting of the device handle"""
        with self._handle_lock:
            self._handle = value
        
    def connect(self, device_identifier=None):
        """
        Connect to the LabJack device
        
        Args:
            device_identifier: Optional identifier to use instead of the stored port
        
        Returns:
            True if connected successfully, False otherwise
        """
        if not LABJACK_AVAILABLE:
            self.error_message = "LabJack LJM library not available"
            logger.error("Cannot connect: LabJack LJM library not installed")
            return False
        
        with self._handle_lock:
            try:
                # Use provided device_identifier if available
                connection_id = device_identifier if device_identifier is not None else self.port
                
                # Try to open the device using the specified parameters
                self._handle = ljm.openS(self.device_type, self.connection_type, connection_id)
                info = ljm.getHandleInfo(self._handle)
                
                # Store device information
                self.device_info = {
                    "device_type": info[0],  # Device type
                    "connection_type": info[1], # 0=USB, 1=TCP, 2=Ethernet, 3=WiFi
                    "serial_number": info[2],
                    "ip_address": ljm.numberToIP(info[3]),
                    "port": info[4],
                    "max_bytes_per_mb": info[5]
                }
                
                # Read additional information
                try:
                    # Read firmware version
                    logger.debug("Reading FIRMWARE_VERSION...")
                    firmware_version = ljm.eReadName(self._handle, "FIRMWARE_VERSION")
                    self.device_info["firmware_version"] = f"{firmware_version:.4f}"
                    
                    # Read hardware version
                    logger.debug("Reading HARDWARE_VERSION...")
                    hw_version = ljm.eReadName(self._handle, "HARDWARE_VERSION")
                    self.device_info["hardware_version"] = f"{hw_version:.4f}"
                    
                    # Read device name
                    logger.debug("Reading DEVICE_NAME_DEFAULT...")
                    device_name_address = ljm.eReadName(self._handle, "DEVICE_NAME_DEFAULT")
                    self.device_info["device_name"] = f"{device_name_address}"
                    
                    # Translate Device Type
                    device_type_code = self.device_info.get("device_type", -1)
                    device_type_map = {7: "T7", 4: "T4", 3: "U3", 6: "U6", 9: "UE9"}
                    self.device_info["type"] = device_type_map.get(device_type_code, f"Unknown({device_type_code})")
                    logger.debug(f"Translated device type {device_type_code} to {self.device_info['type']}")
                    
                except ljm.LJMError as e:
                    logger.warning(f"Warning getting device info details: {e}")
                
                # Set connected flag
                self.connected = True
                self.error_message = ""
                self._consecutive_errors = 0
                self._last_successful_read = time.time()
                
                # Clear caches on new connection
                self._ef_channels_cache = []
                self._ef_cache_time = 0
                self._tc_channels_cache = []
                self._tc_cache_time = 0
                
                logger.info(f"LabJack Connected: {self.device_info}")
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Failed to connect to LabJack: {e}"
                self.connected = False
                self._handle = None
                self.device_info = {}
                logger.error(f"LabJack Connection Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error: {e}"
                self.connected = False
                self._handle = None
                self.device_info = {}
                logger.error(f"LabJack Unexpected Error: {e}")
                return False
            
    def disconnect(self):
        """Disconnect from the LabJack device"""
        # First stop the background thread to prevent reconnection attempts
        self.stop_background_thread()
        
        with self._handle_lock:
            if self._handle:
                try:
                    ljm.close(self._handle)
                    logger.info("LabJack Disconnected")
                except ljm.LJMError as e:
                    self.error_message = f"Error disconnecting: {e}"
                    logger.error(f"LabJack Disconnect Error: {e}")
                except Exception as e:
                    self.error_message = f"Unexpected error disconnecting: {e}"
                    logger.error(f"LabJack Unexpected Disconnect Error: {e}")
                finally:
                    self._handle = None
                    self.device_info = {}
                    self.connected = False
                    # Clear caches
                    self._ef_channels_cache = []
                    self._tc_channels_cache = []
                
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        with self._handle_lock:
            return self.connected and self._handle is not None
        
    def read_data(self):
        """
        Read data from the LabJack device using optimized bulk reads
        
        Returns:
            Dictionary with sensor values or None if failed
        """
        if not self.is_connected():
            return None
        
        with self._handle_lock:
            if self._handle is None:
                return None
                
            try:
                read_start_time = time.time()
                data = {}
                
                # 1. Collect all names we want to read
                # Always read AIN0-AIN3 as "standard" defaults
                standard_names = ["AIN0", "AIN1", "AIN2", "AIN3"]
                
                # Add EF channels from cache
                ef_channels = self.get_ef_channels()
                ef_names = [channel['name'] for channel in ef_channels]
                
                # Combine all names for a single bulk read
                all_names_to_read = standard_names + ef_names
                
                if not all_names_to_read:
                    return {}
                
                try:
                    num_frames = len(all_names_to_read)
                    results = ljm.eReadNames(self._handle, num_frames, all_names_to_read)
                    
                    # Map results back to the dictionary
                    for i, name in enumerate(all_names_to_read):
                        data[name] = results[i]
                        
                except ljm.LJMError as e:
                    logger.warning(f"Error during bulk LabJack read: {e}")
                    # Fallback to individual reads if bulk fails (rare)
                    for name in all_names_to_read:
                        try:
                            data[name] = ljm.eReadName(self._handle, name)
                        except ljm.LJMError:
                            continue
                
                # Update health tracking
                self._last_successful_read = time.time()
                self._consecutive_errors = 0
                
                # Log slow reads to help debug timing issues
                read_duration = time.time() - read_start_time
                if read_duration > 0.5:
                    logger.debug(f"LabJack read took {read_duration:.3f}s for {len(all_names_to_read)} channels")
                    
                return data
                
            except ljm.LJMError as e:
                self._consecutive_errors += 1
                self.error_message = f"Error reading data: {e}"
                logger.error(f"LabJack Read Error: {e}")
                return None
            except Exception as e:
                self._consecutive_errors += 1
                self.error_message = f"Unexpected error reading data: {e}"
                logger.error(f"LabJack Unexpected Read Error: {e}")
                return None
            
    def read_channel(self, channel):
        """
        Read a specific channel from the LabJack device
        
        Args:
            channel (str): Channel name to read (e.g. "AIN0", "FIO1", etc.)
            
        Returns:
            float: Value read from the channel, or None if failed
        """
        if not self.is_connected():
            return None
        
        with self._handle_lock:
            if self._handle is None:
                return None
                
            try:
                # Read the value from the specified channel
                value = ljm.eReadName(self._handle, channel)
                self._consecutive_errors = 0
                return value
            except ljm.LJMError as e:
                self._consecutive_errors += 1
                self.error_message = f"Error reading channel {channel}: {e}"
                logger.error(f"LabJack Read Channel Error ({channel}): {e}")
                return None
            except Exception as e:
                self._consecutive_errors += 1
                self.error_message = f"Unexpected error reading channel {channel}: {e}"
                logger.error(f"LabJack Unexpected Read Channel Error ({channel}): {e}")
                return None
            
    def write_data(self, data):
        """
        Write data to the LabJack device
        
        Args:
            data: Dictionary with address:value pairs to write
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Handle different input formats
                if isinstance(data, dict):
                    # Dictionary format with address:value pairs
                    addresses = list(data.keys())
                    values = list(data.values())
                    ljm.eWriteNames(self._handle, len(addresses), addresses, values)
                    return True
                elif isinstance(data, str):
                    # Single string command with format "address=value"
                    if "=" in data:
                        address, value_str = data.split("=", 1)
                        try:
                            value = float(value_str.strip())
                            ljm.eWriteName(self._handle, address.strip(), value)
                            return True
                        except ValueError:
                            self.error_message = f"Invalid value format: {value_str}"
                            return False
                    else:
                        self.error_message = "Invalid command format. Use 'address=value'"
                        return False
                else:
                    self.error_message = "Unsupported data format"
                    return False
            except ljm.LJMError as e:
                self.error_message = f"Error writing data: {e}"
                logger.error(f"LabJack Write Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error writing data: {e}"
                logger.error(f"LabJack Unexpected Write Error: {e}")
                return False
    
    def start_background_thread(self):
        """Start background thread for polling data"""
        if self._status_thread is None or not self._status_thread.is_alive():
            self._stop_event.clear()
            self._status_thread = threading.Thread(target=self._background_worker, daemon=True)
            self._status_thread.start()
            return True
        return False
        
    def stop_background_thread(self):
        """Stop the background thread"""
        if self._status_thread and self._status_thread.is_alive():
            self._stop_event.set()
            self._status_thread.join(timeout=2.0)
            return True
        return False
        
    def set_sampling_rate(self, rate):
        """Set the sampling rate for data acquisition
        
        Args:
            rate: Sampling rate in Hz
        """
        if rate > 0:
            self.sampling_rate = rate
            logger.info(f"LabJack sampling rate set to {rate} Hz")
            return True
        return False
        
    def _background_worker(self):
        """Background worker thread for monitoring connection status and reading data"""
        last_ef_check_time = 0
        last_status_emit_time = 0
        last_data_read_time = 0
        status_interval = 5.0  # Status update interval in seconds
        
        while not self._stop_event.is_set():
            try:
                if self.is_connected():
                    current_time = time.time()
                    
                    # Calculate sleep interval based on sampling rate (in seconds)
                    # Minimum sleep is 0.001 seconds (1000Hz) to prevent excessive CPU usage
                    # We recalculate this inside the loop so it responds to changes
                    sleep_interval = max(1.0 / self.sampling_rate, 0.001)
                    
                    # Only emit status periodically (not every iteration)
                    if current_time - last_status_emit_time >= status_interval:
                        try:
                            # Put current status to queue for UI updates (non-blocking)
                            self._safe_queue_put(self._status_queue, {
                                "type": "status", 
                                "message": "Connected",
                                "connected": True,
                                "device_info": self.device_info
                            })
                            
                            # Refresh EF channels (uses cache)
                            ef_channels = self.get_ef_channels(force_refresh=False)
                            
                            if ef_channels:
                                # Simplify channel data before sending to main thread
                                simplified_channels = []
                                for ch in ef_channels:
                                    simplified_channels.append({
                                        "name": ch["name"],
                                        "type": ch.get("type", "unknown"),
                                        "description": ch.get("description", "")
                                    })
                                
                                # Put simplified EF channel data in status queue
                                self._safe_queue_put(self._status_queue, {
                                    "type": "ef_channels",
                                    "channels": simplified_channels
                                })
                        except Exception as e:
                            logger.warning(f"Error refreshing status: {e}")
                        last_status_emit_time = current_time
                    
                    # Read data from device at the specified sampling rate
                    if current_time - last_data_read_time >= sleep_interval:
                        data = self.read_data()
                        if data:
                            # Put data in queue for retrieval by main application (non-blocking)
                            self._safe_queue_put(self._data_queue, data)
                        last_data_read_time = current_time
                        
                    # Check for too many consecutive errors
                    if self._consecutive_errors >= self._max_consecutive_errors:
                        logger.warning(f"Too many consecutive errors ({self._consecutive_errors}), disconnecting...")
                        self._safe_queue_put(self._status_queue, {
                            "type": "status", 
                            "message": f"Connection lost (too many errors)",
                            "connected": False
                        })
                        self._disconnect_internal()
                        
                elif self.auto_reconnect:
                    # Only try to reconnect if auto_reconnect is enabled
                    logger.info("Attempting auto-reconnect...")
                    if self.connect():
                        self._safe_queue_put(self._status_queue, {
                            "type": "status", 
                            "message": "Reconnected",
                            "connected": True,
                            "device_info": self.device_info
                        })
                    else:
                        # Wait longer before next reconnect attempt
                        time.sleep(5)
                        
            except ljm.LJMError as e:
                # Handle connection errors
                logger.error(f"LabJack Background Error: {e}")
                self._safe_queue_put(self._status_queue, {
                    "type": "status", 
                    "message": f"Error: {e}",
                    "connected": False
                })
                self._disconnect_internal()
                if self.auto_reconnect:
                    time.sleep(5)  # Wait before trying to reconnect
            except Exception as e:
                logger.error(f"LabJack Background Unexpected Error: {e}")
                self._safe_queue_put(self._status_queue, {
                    "type": "status", 
                    "message": f"Unexpected Error: {e}",
                    "connected": False
                })
                
            # Sleep for a short time (10ms) to prevent busy-waiting
            # This ensures we can respond to stop events quickly
            time.sleep(0.01)
    
    def _disconnect_internal(self):
        """Internal disconnect without stopping the background thread"""
        with self._handle_lock:
            if self._handle:
                try:
                    ljm.close(self._handle)
                except Exception:
                    pass
                finally:
                    self._handle = None
                    self.connected = False
    
    def _safe_queue_put(self, q, item):
        """Safely put an item in a queue without blocking
        
        If the queue is full, the oldest item is discarded.
        """
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                # Discard oldest item and try again
                q.get_nowait()
                q.put_nowait(item)
            except queue.Empty:
                pass
    
    def get_status_queue(self):
        """Get the status queue for receiving status updates"""
        return self._status_queue
        
    def get_data_queue(self):
        """Get the data queue for receiving sensor data"""
        return self._data_queue
        
    @staticmethod
    def list_devices():
        """
        List available LabJack devices
        
        Returns:
            List of dictionaries containing information about available devices
        """
        if not LABJACK_AVAILABLE:
            logger.warning("Cannot list devices: LabJack LJM library not installed")
            return []
            
        devices = []
        try:
            # Get the number of available LabJack devices
            device_count = ljm.listAll(0, 0)
            
            if device_count[0] > 0:
                # Query information for all devices found
                info = ljm.listAll(device_count[0], device_count[0])
                
                # Organize device information
                for i in range(device_count[0]):
                    device_info = {
                        "device_type": info[0][i],       # Device type (7 for T7, 4 for T4)
                        "connection_type": info[1][i],   # Connection type
                        "serial_number": info[2][i],     # Serial number
                        "ip_address": ljm.numberToIP(info[3][i]), # IP address
                    }
                    
                    # Map device type to human-readable name
                    if device_info["device_type"] == 7:
                        device_info["name"] = "T7"
                    elif device_info["device_type"] == 4:
                        device_info["name"] = "T4"
                    else:
                        device_info["name"] = f"Unknown ({device_info['device_type']})"
                    
                    # Map connection type to human-readable name
                    conn_map = {0: "USB", 1: "TCP", 2: "Ethernet", 3: "WiFi"}
                    device_info["connection_name"] = conn_map.get(device_info["connection_type"], 
                                                                 f"Unknown ({device_info['connection_type']})")
                    
                    devices.append(device_info)
                    
            return devices
        except ljm.LJMError as e:
            logger.error(f"Error listing LabJack devices: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing devices: {e}")
            return []

    def get_labjack_channels(self):
        """Get available LabJack channels
        
        Returns:
            list: List of dictionaries containing information about available channels
        """
        channels = []
        
        # Add analog inputs (AIN0-AIN13 for T7)
        for i in range(14):
            channels.append({"name": f"AIN{i}", "type": "analog_input", "description": f"Analog Input {i}"})
            
        # Add digital I/O (FIO0-FIO7, EIO0-EIO7, CIO0-CIO3)
        for i in range(8):
            channels.append({"name": f"FIO{i}", "type": "digital_io", "description": f"Flexible IO {i}"})
        for i in range(8):
            channels.append({"name": f"EIO{i}", "type": "digital_io", "description": f"Extended IO {i}"})
        for i in range(4):
            channels.append({"name": f"CIO{i}", "type": "digital_io", "description": f"Control IO {i}"})
            
        # Add EF channels - these are extended feature modes for digital lines
        ef_channels = self.get_ef_channels()
        channels.extend(ef_channels)
            
        # Add DAC outputs
        channels.append({"name": "DAC0", "type": "analog_output", "description": "Analog Output 0"})
        channels.append({"name": "DAC1", "type": "analog_output", "description": "Analog Output 1"})
        
        return channels
        
    def get_ef_channels(self, force_refresh=False):
        """Get available Extended Feature (EF) channels
        
        Uses caching to reduce unnecessary device queries.
        
        Args:
            force_refresh: Force refresh the cache even if not expired
        
        Returns:
            list: List of dictionaries containing information about available EF channels
        """
        # Only attempt to read EF configurations if we're connected
        if not self.is_connected():
            return []
        
        # Check cache validity
        current_time = time.time()
        if not force_refresh and self._ef_channels_cache and \
           (current_time - self._ef_cache_time) < self.EF_CACHE_TIMEOUT:
            return self._ef_channels_cache
            
        ef_channels = []
        
        with self._handle_lock:
            if self._handle is None:
                return ef_channels
                
            try:
                # Check for known thermocouple registers (directly configured in Kipling)
                # Check AIN0-AIN13 (full range for T7)
                try:
                    for i in range(14):  # Increased from 4 to 14 to support more thermocouples
                        try:
                            # Try the standard EF_READ_A format first
                            temp_register = f"AIN{i}_EF_READ_A"
                            value = ljm.eReadName(self._handle, temp_register)
                            
                            # If reading succeeded, check the EF type
                            try:
                                type_register = f"AIN{i}_EF_INDEX"
                                ef_index = int(ljm.eReadName(self._handle, type_register))
                            except Exception:
                                ef_index = 21  # Assume K-type thermocouple
                            
                            # Map EF index to sensor type
                            sensor_type, description = self._get_temperature_sensor_info(ef_index)
                            
                            ef_channels.append({
                                "name": temp_register,
                                "type": f"ef_temp_{sensor_type}",
                                "description": f"{description} on AIN{i}",
                                "ain": f"AIN{i}",
                                "ef_index": ef_index
                            })
                        except ljm.LJMError:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking for temperature sensors: {e}")
                
                # Check DIO lines for EF configurations
                dio_lines = [f"FIO{i}" for i in range(8)] + \
                           [f"EIO{i}" for i in range(8)] + \
                           [f"CIO{i}" for i in range(4)]
                           
                for dio in dio_lines:
                    try:
                        ef_index_addr = f"{dio}_EF_INDEX"
                        ef_index = int(ljm.eReadName(self._handle, ef_index_addr))
                        
                        if ef_index != 0:
                            ef_type = self._get_ef_type(ef_index)
                            ef_channels.extend(self._get_ef_channels_for_type(dio, ef_type, ef_index))
                    except ljm.LJMError:
                        continue
                        
            except Exception as e:
                logger.warning(f"Error getting EF channels: {e}")
        
        # Update cache
        self._ef_channels_cache = ef_channels
        self._ef_cache_time = current_time
            
        return ef_channels
    
    def _get_temperature_sensor_info(self, ef_index):
        """Get temperature sensor type and description based on EF index
        
        Args:
            ef_index: The EF index value
            
        Returns:
            tuple: (sensor_type, description)
        """
        sensor_map = {
            20: ("thermocouple_K", "K-Type Thermocouple"),
            21: ("thermocouple_K", "K-Type Thermocouple"),
            22: ("thermocouple_E", "E-Type Thermocouple"),
            23: ("thermocouple_T", "T-Type Thermocouple"),
            24: ("thermocouple_R", "R-Type Thermocouple"),
            25: ("thermocouple_S", "S-Type Thermocouple"),
            26: ("rtd_pt100", "PT100 RTD"),
            60: ("rtd_pt100", "PT100 RTD"),
            61: ("rtd_pt500", "PT500 RTD"),
            62: ("rtd_pt1000", "PT1000 RTD"),
        }
        return sensor_map.get(ef_index, ("unknown", "Temperature Sensor"))
    
    def _get_ef_channels_for_type(self, dio, ef_type, ef_index):
        """Get EF channel definitions for a specific type
        
        Args:
            dio: The DIO line name
            ef_type: The EF type string
            ef_index: The EF index value
            
        Returns:
            list: List of channel definitions
        """
        channels = []
        
        if ef_type == "counter":
            channels.append({
                "name": f"{dio}_EF_READ_A",
                "type": "ef_counter",
                "description": f"Counter on {dio}",
                "dio": dio,
                "ef_index": ef_index
            })
        elif ef_type == "quadrature":
            channels.append({
                "name": f"{dio}_EF_READ_A",
                "type": "ef_quadrature_position",
                "description": f"Quadrature Position on {dio}",
                "dio": dio,
                "ef_index": ef_index
            })
            channels.append({
                "name": f"{dio}_EF_READ_B",
                "type": "ef_quadrature_velocity",
                "description": f"Quadrature Velocity on {dio}",
                "dio": dio,
                "ef_index": ef_index
            })
        elif ef_type == "pwm_in":
            channels.append({
                "name": f"{dio}_EF_READ_A",
                "type": "ef_pwm_duty_cycle",
                "description": f"PWM Duty Cycle on {dio}",
                "dio": dio,
                "ef_index": ef_index
            })
            channels.append({
                "name": f"{dio}_EF_READ_B", 
                "type": "ef_pwm_frequency",
                "description": f"PWM Frequency on {dio}",
                "dio": dio,
                "ef_index": ef_index
            })
        else:
            channels.append({
                "name": f"{dio}_EF_READ_A",
                "type": "ef_generic",
                "description": f"EF Read A on {dio} (Type: {ef_type})",
                "dio": dio,
                "ef_index": ef_index
            })
            
        return channels
    
    def _get_ef_type(self, ef_index):
        """Get the type of Extended Feature based on its index
        
        Args:
            ef_index: The EF index value
            
        Returns:
            str: The type of EF as a string
        """
        ef_types = {
            0: "none",
            1: "pwm_out",
            2: "pwm_in",
            3: "frequency_out",
            4: "quadrature",
            5: "timer_counter",
            6: "counter",
            7: "frequency_in",
            8: "pulse_out",
            9: "soft_counter",
            10: "soft_timer",
            11: "conditional_reset"
        }
        return ef_types.get(ef_index, f"unknown_{ef_index}")
    
    def read_ef_channel(self, channel_name):
        """Read an Extended Feature channel
        
        Args:
            channel_name (str): The name of the EF channel to read (e.g., "FIO0_EF_READ_A")
            
        Returns:
            float: The value read from the channel, or None if failed
        """
        if not self.is_connected():
            return None
        
        with self._handle_lock:
            if self._handle is None:
                return None
                
            try:
                value = ljm.eReadName(self._handle, channel_name)
                return value
            except ljm.LJMError as e:
                self.error_message = f"Error reading EF channel {channel_name}: {e}"
                logger.error(f"LabJack Read EF Channel Error ({channel_name}): {e}")
                return None
            except Exception as e:
                self.error_message = f"Unexpected error reading EF channel {channel_name}: {e}"
                logger.error(f"LabJack Unexpected Read EF Channel Error ({channel_name}): {e}")
                return None
            
    def configure_ef(self, dio, ef_type, ef_options=None):
        """Configure an Extended Feature on a digital I/O line
        
        Args:
            dio (str): The DIO line to configure (e.g., "FIO0")
            ef_type (str): The type of EF to configure (e.g., "counter", "pwm_out")
            ef_options (dict, optional): Additional options for the EF configuration
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        if ef_options is None:
            ef_options = {}
            
        ef_type_map = {
            "none": 0,
            "pwm_out": 1,
            "pwm_in": 2,
            "frequency_out": 3,
            "quadrature": 4,
            "timer_counter": 5,
            "counter": 6,
            "frequency_in": 7,
            "pulse_out": 8,
            "soft_counter": 9,
            "soft_timer": 10,
            "conditional_reset": 11
        }
        
        ef_index = ef_type_map.get(ef_type.lower(), 0)
        if ef_index == 0 and ef_type.lower() != "none":
            self.error_message = f"Unknown EF type: {ef_type}"
            logger.error(f"Unknown EF type: {ef_type}")
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Set EF to 0 first to disable any current configuration
                ljm.eWriteName(self._handle, f"{dio}_EF_INDEX", 0)
                
                if ef_index == 0:
                    # Invalidate cache since we changed EF config
                    self._ef_cache_time = 0
                    return True
                    
                # Configure the EF based on the type
                if ef_type.lower() == "counter":
                    if "config_a" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                    if "value" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_B", ef_options["value"])
                    ljm.eWriteName(self._handle, f"{dio}_EF_INDEX", ef_index)
                    
                elif ef_type.lower() == "pwm_out":
                    freq = ef_options.get("frequency", 1000)
                    ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_A", freq)
                    duty = ef_options.get("duty_cycle", 50)
                    ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_B", duty)
                    ljm.eWriteName(self._handle, f"{dio}_EF_INDEX", ef_index)
                    
                elif ef_type.lower() == "quadrature":
                    if "config_a" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                    if "config_b" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_B", ef_options["config_b"])
                    ljm.eWriteName(self._handle, f"{dio}_EF_INDEX", ef_index)
                    
                else:
                    if "config_a" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                    if "config_b" in ef_options:
                        ljm.eWriteName(self._handle, f"{dio}_EF_CONFIG_B", ef_options["config_b"])
                    ljm.eWriteName(self._handle, f"{dio}_EF_INDEX", ef_index)
                
                # Invalidate cache since we changed EF config
                self._ef_cache_time = 0
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error configuring EF on {dio}: {e}"
                logger.error(f"LabJack EF Configuration Error ({dio}): {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error configuring EF on {dio}: {e}"
                logger.error(f"LabJack Unexpected EF Configuration Error ({dio}): {e}")
                return False

    def _scan_for_thermocouples(self):
        """Scan for directly configured thermocouples
        
        Uses caching to reduce unnecessary device queries.
        
        Returns:
            list: List of thermocouple channel dictionaries
        """
        # Check cache validity
        current_time = time.time()
        if self._tc_channels_cache and \
           (current_time - self._tc_cache_time) < self.EF_CACHE_TIMEOUT * 2:
            return self._tc_channels_cache
            
        tc_channels = []
        
        with self._handle_lock:
            if self._handle is None:
                return tc_channels
                
            try:
                # Only check AIN0-AIN3 with single pattern to reduce queries
                for i in range(4):
                    try:
                        register = f"AIN{i}_EF_READ_A"
                        value = ljm.eReadName(self._handle, register)
                        
                        tc_channels.append({
                            "name": register,
                            "type": "ef_temp_thermocouple_K",
                            "description": f"K-Type Thermocouple on AIN{i}",
                            "ain": f"AIN{i}",
                            "ef_index": 21
                        })
                    except ljm.LJMError:
                        continue
                        
            except Exception as e:
                logger.debug(f"Error in thermocouple scan: {e}")
        
        # Update cache
        self._tc_channels_cache = tc_channels
        self._tc_cache_time = current_time
                
        return tc_channels

    # =========================================================================
    # ANALOG INPUT CONFIGURATION (Feature #6)
    # =========================================================================
    
    def configure_ain(self, channel, range_v=10.0, resolution_index=0, settling_us=0, 
                     negative_channel=199, differential=False):
        """Configure analog input settings for a specific channel
        
        Args:
            channel (int or str): AIN channel number (0-13) or name (e.g., "AIN0")
            range_v (float): Input range in volts. Valid values:
                - T7: ±10, ±1, ±0.1, ±0.01
                - T4: 0-2.5 (single-ended), ±2.5 (differential)
            resolution_index (int): Resolution setting (0-8 for T7, 0-5 for T4)
                Higher values = more resolution but slower sampling
            settling_us (float): Settling time in microseconds (0 = auto)
            negative_channel (int): Negative channel for differential measurement
                199 = single-ended (GND reference), or channel number for differential
            differential (bool): If True, configure for differential measurement
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        # Parse channel number
        if isinstance(channel, str):
            channel = int(channel.replace("AIN", ""))
            
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Set the input range
                ljm.eWriteName(self._handle, f"AIN{channel}_RANGE", range_v)
                logger.debug(f"Set AIN{channel}_RANGE to {range_v}")
                
                # Set resolution index
                ljm.eWriteName(self._handle, f"AIN{channel}_RESOLUTION_INDEX", resolution_index)
                logger.debug(f"Set AIN{channel}_RESOLUTION_INDEX to {resolution_index}")
                
                # Set settling time
                ljm.eWriteName(self._handle, f"AIN{channel}_SETTLING_US", settling_us)
                logger.debug(f"Set AIN{channel}_SETTLING_US to {settling_us}")
                
                # Set negative channel (single-ended vs differential)
                if differential:
                    ljm.eWriteName(self._handle, f"AIN{channel}_NEGATIVE_CH", negative_channel)
                    logger.debug(f"Set AIN{channel}_NEGATIVE_CH to {negative_channel}")
                else:
                    ljm.eWriteName(self._handle, f"AIN{channel}_NEGATIVE_CH", 199)  # GND
                    logger.debug(f"Set AIN{channel}_NEGATIVE_CH to 199 (GND)")
                
                logger.info(f"Configured AIN{channel}: range={range_v}V, resolution={resolution_index}, "
                           f"settling={settling_us}us, differential={differential}")
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error configuring AIN{channel}: {e}"
                logger.error(f"LabJack AIN Configuration Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error configuring AIN{channel}: {e}"
                logger.error(f"LabJack Unexpected AIN Configuration Error: {e}")
                return False
    
    def get_ain_config(self, channel):
        """Get the current configuration for an analog input channel
        
        Args:
            channel (int or str): AIN channel number (0-13) or name (e.g., "AIN0")
            
        Returns:
            dict: Configuration dictionary or None if failed
        """
        if not self.is_connected():
            return None
        
        # Parse channel number
        if isinstance(channel, str):
            channel = int(channel.replace("AIN", ""))
        
        with self._handle_lock:
            if self._handle is None:
                return None
                
            try:
                config = {
                    "channel": channel,
                    "range": ljm.eReadName(self._handle, f"AIN{channel}_RANGE"),
                    "resolution_index": int(ljm.eReadName(self._handle, f"AIN{channel}_RESOLUTION_INDEX")),
                    "settling_us": ljm.eReadName(self._handle, f"AIN{channel}_SETTLING_US"),
                    "negative_channel": int(ljm.eReadName(self._handle, f"AIN{channel}_NEGATIVE_CH")),
                }
                config["differential"] = config["negative_channel"] != 199
                return config
                
            except ljm.LJMError as e:
                self.error_message = f"Error reading AIN{channel} config: {e}"
                logger.error(f"LabJack AIN Config Read Error: {e}")
                return None
            except Exception as e:
                self.error_message = f"Unexpected error reading AIN{channel} config: {e}"
                logger.error(f"LabJack Unexpected AIN Config Read Error: {e}")
                return None
    
    def configure_ain_all(self, range_v=10.0, resolution_index=0, settling_us=0):
        """Configure all analog inputs with the same settings
        
        Args:
            range_v (float): Input range in volts
            resolution_index (int): Resolution setting
            settling_us (float): Settling time in microseconds
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Use the global AIN settings
                ljm.eWriteName(self._handle, "AIN_ALL_RANGE", range_v)
                ljm.eWriteName(self._handle, "AIN_ALL_RESOLUTION_INDEX", resolution_index)
                ljm.eWriteName(self._handle, "AIN_ALL_SETTLING_US", settling_us)
                ljm.eWriteName(self._handle, "AIN_ALL_NEGATIVE_CH", 199)  # Single-ended
                
                logger.info(f"Configured all AINs: range={range_v}V, resolution={resolution_index}, "
                           f"settling={settling_us}us")
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error configuring all AINs: {e}"
                logger.error(f"LabJack AIN_ALL Configuration Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error configuring all AINs: {e}"
                logger.error(f"LabJack Unexpected AIN_ALL Configuration Error: {e}")
                return False

    # =========================================================================
    # NETWORK CONFIGURATION (Feature #7)
    # =========================================================================
    
    def configure_ethernet(self, ip=None, subnet=None, gateway=None, dns=None, dhcp=True):
        """Configure Ethernet network settings
        
        Args:
            ip (str): Static IP address (e.g., "192.168.1.100")
            subnet (str): Subnet mask (e.g., "255.255.255.0")
            gateway (str): Default gateway (e.g., "192.168.1.1")
            dns (str): DNS server address (e.g., "8.8.8.8")
            dhcp (bool): Enable DHCP (if True, static settings are ignored)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                if dhcp:
                    # Enable DHCP
                    ljm.eWriteName(self._handle, "ETHERNET_DHCP_ENABLE", 1)
                    logger.info("Enabled Ethernet DHCP")
                else:
                    # Disable DHCP and set static configuration
                    ljm.eWriteName(self._handle, "ETHERNET_DHCP_ENABLE", 0)
                    
                    if ip:
                        ip_num = ljm.ipToNumber(ip)
                        ljm.eWriteName(self._handle, "ETHERNET_IP", ip_num)
                        logger.debug(f"Set Ethernet IP to {ip}")
                        
                    if subnet:
                        subnet_num = ljm.ipToNumber(subnet)
                        ljm.eWriteName(self._handle, "ETHERNET_SUBNET", subnet_num)
                        logger.debug(f"Set Ethernet Subnet to {subnet}")
                        
                    if gateway:
                        gateway_num = ljm.ipToNumber(gateway)
                        ljm.eWriteName(self._handle, "ETHERNET_GATEWAY", gateway_num)
                        logger.debug(f"Set Ethernet Gateway to {gateway}")
                        
                    if dns:
                        dns_num = ljm.ipToNumber(dns)
                        ljm.eWriteName(self._handle, "ETHERNET_DNS", dns_num)
                        logger.debug(f"Set Ethernet DNS to {dns}")
                    
                    logger.info(f"Configured Ethernet: IP={ip}, Subnet={subnet}, Gateway={gateway}, DNS={dns}")
                
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error configuring Ethernet: {e}"
                logger.error(f"LabJack Ethernet Configuration Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error configuring Ethernet: {e}"
                logger.error(f"LabJack Unexpected Ethernet Configuration Error: {e}")
                return False
    
    def configure_wifi(self, ssid=None, password=None, ip=None, subnet=None, 
                       gateway=None, dns=None, dhcp=True):
        """Configure WiFi network settings
        
        Note: WiFi configuration changes typically require a device reboot to take effect.
        
        Args:
            ssid (str): WiFi network name
            password (str): WiFi password
            ip (str): Static IP address (e.g., "192.168.1.100")
            subnet (str): Subnet mask (e.g., "255.255.255.0")
            gateway (str): Default gateway (e.g., "192.168.1.1")
            dns (str): DNS server address (e.g., "8.8.8.8")
            dhcp (bool): Enable DHCP (if True, static IP settings are ignored)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Set WiFi SSID if provided
                if ssid:
                    # Write SSID as a string (requires special handling)
                    ljm.eWriteNameString(self._handle, "WIFI_SSID_DEFAULT", ssid)
                    logger.debug(f"Set WiFi SSID to {ssid}")
                
                # Set WiFi password if provided
                if password:
                    ljm.eWriteNameString(self._handle, "WIFI_PASSWORD_DEFAULT", password)
                    logger.debug("Set WiFi password")
                
                if dhcp:
                    # Enable DHCP
                    ljm.eWriteName(self._handle, "WIFI_DHCP_ENABLE_DEFAULT", 1)
                    logger.debug("Enabled WiFi DHCP")
                else:
                    # Disable DHCP and set static configuration
                    ljm.eWriteName(self._handle, "WIFI_DHCP_ENABLE_DEFAULT", 0)
                    
                    if ip:
                        ip_num = ljm.ipToNumber(ip)
                        ljm.eWriteName(self._handle, "WIFI_IP_DEFAULT", ip_num)
                        logger.debug(f"Set WiFi IP to {ip}")
                        
                    if subnet:
                        subnet_num = ljm.ipToNumber(subnet)
                        ljm.eWriteName(self._handle, "WIFI_SUBNET_DEFAULT", subnet_num)
                        logger.debug(f"Set WiFi Subnet to {subnet}")
                        
                    if gateway:
                        gateway_num = ljm.ipToNumber(gateway)
                        ljm.eWriteName(self._handle, "WIFI_GATEWAY_DEFAULT", gateway_num)
                        logger.debug(f"Set WiFi Gateway to {gateway}")
                        
                    if dns:
                        dns_num = ljm.ipToNumber(dns)
                        ljm.eWriteName(self._handle, "WIFI_DNS_DEFAULT", dns_num)
                        logger.debug(f"Set WiFi DNS to {dns}")
                
                logger.info(f"Configured WiFi: SSID={ssid}, DHCP={dhcp}")
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error configuring WiFi: {e}"
                logger.error(f"LabJack WiFi Configuration Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error configuring WiFi: {e}"
                logger.error(f"LabJack Unexpected WiFi Configuration Error: {e}")
                return False
    
    def get_network_config(self):
        """Get current network configuration for both Ethernet and WiFi
        
        Returns:
            dict: Network configuration dictionary or None if failed
        """
        if not self.is_connected():
            return None
        
        with self._handle_lock:
            if self._handle is None:
                return None
                
            config = {
                "ethernet": {},
                "wifi": {}
            }
            
            try:
                # Read Ethernet configuration
                try:
                    config["ethernet"]["dhcp_enabled"] = bool(ljm.eReadName(self._handle, "ETHERNET_DHCP_ENABLE"))
                    config["ethernet"]["ip"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "ETHERNET_IP")))
                    config["ethernet"]["subnet"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "ETHERNET_SUBNET")))
                    config["ethernet"]["gateway"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "ETHERNET_GATEWAY")))
                    config["ethernet"]["dns"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "ETHERNET_DNS")))
                except ljm.LJMError:
                    config["ethernet"]["error"] = "Ethernet not available on this device"
                
                # Read WiFi configuration
                try:
                    config["wifi"]["dhcp_enabled"] = bool(ljm.eReadName(self._handle, "WIFI_DHCP_ENABLE_DEFAULT"))
                    config["wifi"]["ip"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "WIFI_IP_DEFAULT")))
                    config["wifi"]["subnet"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "WIFI_SUBNET_DEFAULT")))
                    config["wifi"]["gateway"] = ljm.numberToIP(int(ljm.eReadName(self._handle, "WIFI_GATEWAY_DEFAULT")))
                    config["wifi"]["status"] = int(ljm.eReadName(self._handle, "WIFI_STATUS"))
                    config["wifi"]["rssi"] = ljm.eReadName(self._handle, "WIFI_RSSI")
                except ljm.LJMError:
                    config["wifi"]["error"] = "WiFi not available on this device"
                
                return config
                
            except Exception as e:
                self.error_message = f"Error reading network config: {e}"
                logger.error(f"LabJack Network Config Read Error: {e}")
                return None
    
    def apply_network_settings(self):
        """Apply network configuration changes and reboot the device
        
        Note: This will disconnect the device. You will need to reconnect after
        the device reboots (typically takes 5-10 seconds).
        
        Returns:
            bool: True if reboot command was sent successfully
        """
        if not self.is_connected():
            return False
        
        with self._handle_lock:
            if self._handle is None:
                return False
                
            try:
                # Trigger a device reboot to apply settings
                ljm.eWriteName(self._handle, "SYSTEM_REBOOT", 0x4C4A0000)
                logger.info("Device reboot command sent. Device will restart to apply network settings.")
                
                # The device will disconnect, so update our state
                self._handle = None
                self.connected = False
                
                return True
                
            except ljm.LJMError as e:
                self.error_message = f"Error sending reboot command: {e}"
                logger.error(f"LabJack Reboot Error: {e}")
                return False
            except Exception as e:
                self.error_message = f"Unexpected error sending reboot command: {e}"
                logger.error(f"LabJack Unexpected Reboot Error: {e}")
                return False
    
    def get_connection_info(self):
        """Get information about the current connection
        
        Returns:
            dict: Connection information dictionary
        """
        if not self.is_connected():
            return {"connected": False}
        
        with self._handle_lock:
            if self._handle is None:
                return {"connected": False}
                
            try:
                info = ljm.getHandleInfo(self._handle)
                
                conn_types = {0: "USB", 1: "TCP", 2: "Ethernet", 3: "WiFi"}
                
                return {
                    "connected": True,
                    "device_type": self.device_info.get("type", "Unknown"),
                    "serial_number": info[2],
                    "connection_type": conn_types.get(info[1], f"Unknown ({info[1]})"),
                    "ip_address": ljm.numberToIP(info[3]),
                    "port": info[4],
                    "max_bytes_per_mb": info[5],
                    "firmware_version": self.device_info.get("firmware_version", "Unknown"),
                    "hardware_version": self.device_info.get("hardware_version", "Unknown"),
                }
                
            except Exception as e:
                logger.error(f"Error getting connection info: {e}")
                return {"connected": True, "error": str(e)}
