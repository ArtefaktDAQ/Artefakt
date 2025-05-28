import threading
import time
import queue
from labjack import ljm
from app.core.interfaces.base_interface import BaseInterface

class LabJackInterface(BaseInterface):
    """Interface for LabJack T-series devices"""
    
    def __init__(self, port="ANY", connection_type="ANY", device_type="T7", sampling_rate=1000):
        """
        Initialize the LabJack interface
        
        Args:
            port: Port/identifier (or "ANY" for auto-detect)
            connection_type: Connection type ("USB", "TCP", "ETHERNET", "WIFI", or "ANY")
            device_type: Device type ("T7", "T4", or "ANY")
            sampling_rate: Sampling rate in Hz
        """
        super().__init__(name="LabJack")
        self.port = port
        self.connection_type = connection_type
        self.device_type = device_type
        self.sampling_rate = sampling_rate
        self.handle = None
        self.device_info = {}
        self._status_thread = None
        self._data_thread = None
        self._status_queue = queue.Queue()
        self._data_queue = queue.Queue()
        self._stop_event = threading.Event()
        
    def connect(self, device_identifier=None):
        """
        Connect to the LabJack device
        
        Args:
            device_identifier: Optional identifier to use instead of the stored port
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            # Use provided device_identifier if available
            connection_id = device_identifier if device_identifier is not None else self.port
            
            # Try to open the device using the specified parameters
            self.handle = ljm.openS(self.device_type, self.connection_type, connection_id)
            info = ljm.getHandleInfo(self.handle)
            
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
                print("DEBUG INTERFACE: Reading FIRMWARE_VERSION...")
                firmware_version = ljm.eReadName(self.handle, "FIRMWARE_VERSION")
                print(f"DEBUG INTERFACE: Got Firmware: {firmware_version:.4f}")
                self.device_info["firmware_version"] = f"{firmware_version:.4f}"
                
                # Read hardware version
                print("DEBUG INTERFACE: Reading HARDWARE_VERSION...")
                hw_version = ljm.eReadName(self.handle, "HARDWARE_VERSION")
                print(f"DEBUG INTERFACE: Got Hardware: {hw_version:.4f}")
                self.device_info["hardware_version"] = f"{hw_version:.4f}"
                
                # Read device name
                print("DEBUG INTERFACE: Reading DEVICE_NAME_DEFAULT...")
                device_name_address = ljm.eReadName(self.handle, "DEVICE_NAME_DEFAULT")
                print(f"DEBUG INTERFACE: Got Device Name: {device_name_address}")
                self.device_info["device_name"] = f"{device_name_address}"
                
                # --- ADDED: Translate Device Type --- 
                device_type_code = self.device_info.get("device_type", -1)
                device_type_map = {7: "T7", 4: "T4", 3: "U3", 6: "U6", 9: "UE9"} # Add U3, U6, UE9 if needed
                self.device_info["type"] = device_type_map.get(device_type_code, f"Unknown({device_type_code})")
                print(f"DEBUG INTERFACE: Translated device type {device_type_code} to {self.device_info['type']}")
                # ------------------------------------
                
            except ljm.LJMError as e:
                print(f"DEBUG INTERFACE: Warning getting device info details: {e}")
            
            # Set connected flag
            self.connected = True
            self.error_message = ""
            
            print(f"LabJack Connected: {self.device_info}")
            return True
        except ljm.LJMError as e:
            self.error_message = f"Failed to connect to LabJack: {e}"
            self.connected = False
            self.handle = None
            self.device_info = {}
            print(f"LabJack Connection Error: {e}")
            return False
        except Exception as e:
            self.error_message = f"Unexpected error: {e}"
            self.connected = False
            self.handle = None
            self.device_info = {}
            print(f"LabJack Unexpected Error: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from the LabJack device"""
        # First stop the background thread to prevent reconnection attempts
        self.stop_background_thread()
        
        if self.handle:
            try:
                ljm.close(self.handle)
                print("LabJack Disconnected")
            except ljm.LJMError as e:
                self.error_message = f"Error disconnecting: {e}"
                print(f"LabJack Disconnect Error: {e}")
            finally:
                self.handle = None
                self.device_info = {}
                self.connected = False
                
    def is_connected(self):
        """
        Check if the interface is connected
        
        Returns:
            True if connected, False otherwise
        """
        return self.connected and self.handle is not None
        
    def read_data(self):
        """
        Read data from the LabJack device
        
        Returns:
            Dictionary with sensor values or None if failed
        """
        if not self.is_connected():
            return None
            
        try:
            data = {}
            
            # Read standard analog inputs
            try:
                channels = ["AIN0", "AIN1", "AIN2", "AIN3"]
                num_frames = len(channels)
                results = ljm.eReadNames(self.handle, num_frames, channels)
                
                # Add to data dictionary
                for i, channel in enumerate(channels):
                    data[channel] = results[i]
            except ljm.LJMError as e:
                print(f"Error reading AIN channels: {e}")
            
            # Read EF channels that might be configured
            try:
                ef_channels = self.get_ef_channels()
                for channel in ef_channels:
                    try:
                        # Read the channel value
                        channel_name = channel['name']
                        value = ljm.eReadName(self.handle, channel_name)
                        
                        # Add to data dictionary
                        data[channel_name] = value
                    except ljm.LJMError as e:
                        # Skip this channel if read fails
                        print(f"Error reading EF channel {channel['name']}: {e}")
                        continue
            except Exception as e:
                print(f"Error reading EF channels: {e}")
                
            return data
        except Exception as e:
            self.error_message = f"Unexpected error reading data: {e}"
            print(f"LabJack Unexpected Read Error: {e}")
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
            
        try:
            # Read the value from the specified channel
            value = ljm.eReadName(self.handle, channel)
            return value
        except ljm.LJMError as e:
            self.error_message = f"Error reading channel {channel}: {e}"
            print(f"LabJack Read Channel Error ({channel}): {e}")
            return None
        except Exception as e:
            self.error_message = f"Unexpected error reading channel {channel}: {e}"
            print(f"LabJack Unexpected Read Channel Error ({channel}): {e}")
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
            
        try:
            # Handle different input formats
            if isinstance(data, dict):
                # Dictionary format with address:value pairs
                addresses = list(data.keys())
                values = list(data.values())
                ljm.eWriteNames(self.handle, len(addresses), addresses, values)
                return True
            elif isinstance(data, str):
                # Single string command with format "address=value"
                if "=" in data:
                    address, value_str = data.split("=", 1)
                    try:
                        value = float(value_str.strip())
                        ljm.eWriteName(self.handle, address.strip(), value)
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
            print(f"LabJack Write Error: {e}")
            return False
        except Exception as e:
            self.error_message = f"Unexpected error writing data: {e}"
            print(f"LabJack Unexpected Write Error: {e}")
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
            print(f"LabJack sampling rate set to {rate} Hz")
            return True
        return False
        
    def _background_worker(self):
        """Background worker thread for monitoring connection status and reading data"""
        last_ef_check_time = 0
        last_tc_check_time = 0
        last_ef_channels_count = 0
        last_data_read_time = 0
        
        # Calculate sleep interval based on sampling rate (in seconds)
        # Minimum sleep is 0.01 seconds (100Hz) to prevent excessive CPU usage
        sleep_interval = max(1.0 / self.sampling_rate, 0.01)
        
        while not self._stop_event.is_set():
            try:
                if self.is_connected():
                    # Check device connection with a simple read
                    ljm.eReadName(self.handle, "FIRMWARE_VERSION")
                    
                    current_time = time.time()
                    
                    # Periodically refresh EF channels list to detect changes made in Kipling
                    if current_time - last_ef_check_time > 5.0:  # Check every 5 seconds
                        try:
                            # Put current status to queue for UI updates
                            self._status_queue.put({
                                "type": "status", 
                                "message": "Connected",
                                "connected": True,
                                "device_info": self.device_info
                            })
                            
                            # Refresh EF channels (might have been configured externally in Kipling)
                            ef_channels = self.get_ef_channels()
                            
                            # Only send updates if the channels actually changed (count or content)
                            if ef_channels and (len(ef_channels) != last_ef_channels_count):
                                # Update our cache
                                last_ef_channels_count = len(ef_channels)
                                
                                # Simplify channel data before sending to main thread
                                # Include minimal information to reduce processing load
                                simplified_channels = []
                                for ch in ef_channels:
                                    simplified_channels.append({
                                        "name": ch["name"],
                                        "type": ch.get("type", "unknown"),
                                        "description": ch.get("description", "")
                                    })
                                
                                # Put simplified EF channel data in status queue
                                self._status_queue.put({
                                    "type": "ef_channels",
                                    "channels": simplified_channels
                                })
                        except Exception as e:
                            print(f"Error refreshing EF channels: {e}")
                        last_ef_check_time = current_time
                    
                    # Check specifically for K-type thermocouples every 15 seconds
                    if current_time - last_tc_check_time > 15.0:
                        try:
                            # Try to find any K-type thermocouples by directly checking addresses
                            tc_channels = self._scan_for_thermocouples()
                            if tc_channels:
                                # Simplify thermocouple data before sending to main thread
                                simplified_tc = []
                                for ch in tc_channels:
                                    simplified_tc.append({
                                        "name": ch["name"],
                                        "type": ch.get("type", "thermocouple"),
                                        "description": ch.get("description", "")
                                    })
                                
                                # Send only simplified data to avoid UI thread processing
                                self._status_queue.put({
                                    "type": "ef_channels",
                                    "channels": simplified_tc
                                })
                        except Exception as e:
                            print(f"Error in thermocouple scan: {e}")
                        last_tc_check_time = current_time
                    
                    # Read data from device at the specified sampling rate
                    if current_time - last_data_read_time >= sleep_interval:
                        data = self.read_data()
                        if data:
                            # Put data in queue for retrieval by main application
                            self._data_queue.put(data)
                        last_data_read_time = current_time
                else:
                    # Try to reconnect if disconnected
                    self.connect()
                    # If successful, send status
                    if self.is_connected():
                        self._status_queue.put({
                            "type": "status", 
                            "message": "Connected",
                            "connected": True,
                            "device_info": self.device_info
                        })
            except ljm.LJMError as e:
                # Handle connection errors
                print(f"LabJack Background Error: {e}")
                self._status_queue.put({
                    "type": "status", 
                    "message": f"Error: {e}",
                    "connected": False
                })
                self.disconnect()  # Close bad handle
                time.sleep(5)  # Wait before trying to reconnect
            except Exception as e:
                print(f"LabJack Background Unexpected Error: {e}")
                self._status_queue.put({
                    "type": "status", 
                    "message": f"Unexpected Error: {e}",
                    "connected": False
                })
                
            # Sleep for a short time (10ms) to prevent busy-waiting
            # This ensures we can respond to stop events quickly
            time.sleep(0.01)
    
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
            print(f"Error listing LabJack devices: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error listing devices: {e}")
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
        
    def get_ef_channels(self):
        """Get available Extended Feature (EF) channels
        
        Returns:
            list: List of dictionaries containing information about available EF channels
        """
        ef_channels = []
        
        # Only attempt to read EF configurations if we're connected
        if not self.is_connected():
            return ef_channels
            
        try:
            # First, check for known thermocouple registers (directly configured in Kipling)
            # These are special EF features that may use a different naming convention
            try:
                # Try to detect thermocouples on AIN channels (quietly)
                for i in range(14):  # Check AIN0-AIN13
                    # Try several possible register patterns for temperature sensors
                    possible_registers = [
                        f"AIN{i}_EF_READ_A_F",      # Standard format
                        f"AIN{i}_EF_READ_A",        # Alternative format
                        f"AIN{i}_TEMPERATURE",      # Direct temperature reading
                        f"AIN{i}_TC"                # Direct thermocouple reading
                    ]
                    
                    for temp_register in possible_registers:
                        try:
                            # Try to read temperature register (quietly, no debug prints)
                            value = ljm.eReadName(self.handle, temp_register)
                            
                            # If reading succeeded, it's likely a temperature sensor
                            try:
                                type_register = f"AIN{i}_EF_INDEX"
                                ef_index = int(ljm.eReadName(self.handle, type_register))
                            except Exception:
                                # If we can't read the EF index but the temperature reading worked,
                                # assume it's a K-type thermocouple (most common)
                                ef_index = 21  # K-type thermocouple
                            
                            # Map EF index to likely temperature sensor type
                            sensor_type = "unknown"
                            description = "Temperature Sensor"
                            
                            # Common EF indices for temperature sensors
                            if ef_index == 20 or ef_index == 21:
                                sensor_type = "thermocouple_K"
                                description = "K-Type Thermocouple"
                            elif ef_index == 22:
                                sensor_type = "thermocouple_E"
                                description = "E-Type Thermocouple"
                            elif ef_index == 23:
                                sensor_type = "thermocouple_T"
                                description = "T-Type Thermocouple"
                            elif ef_index == 24:
                                sensor_type = "thermocouple_R"
                                description = "R-Type Thermocouple"
                            elif ef_index == 25:
                                sensor_type = "thermocouple_S"
                                description = "S-Type Thermocouple"
                            elif ef_index == 26 or ef_index == 60:
                                sensor_type = "rtd_pt100"
                                description = "PT100 RTD"
                            elif ef_index == 61:
                                sensor_type = "rtd_pt500"
                                description = "PT500 RTD"
                            elif ef_index == 62:
                                sensor_type = "rtd_pt1000"
                                description = "PT1000 RTD"
                            
                            # If it's a temperature register directly, default to K-type TC
                            if "TEMPERATURE" in temp_register or "_TC" in temp_register:
                                sensor_type = "thermocouple_K"
                                description = "K-Type Thermocouple"
                                
                            # Add to channels list
                            ef_channels.append({
                                "name": temp_register,
                                "type": f"ef_temp_{sensor_type}",
                                "description": f"{description} on AIN{i}",
                                "ain": f"AIN{i}",
                                "ef_index": ef_index
                            })
                            
                            # Since we found a working register for this AIN, no need to check other patterns
                            break
                        except ljm.LJMError:
                            # This register doesn't exist or isn't configured for this AIN (silent failure)
                            continue
            except Exception as e:
                # Only log errors, not diagnostic traces
                print(f"Error checking for temperature sensors: {e}")
            
            # For each possible DIO line (FIO, EIO, CIO), check if it's configured as an EF
            dio_lines = []
            for i in range(8):
                dio_lines.append(f"FIO{i}")
            for i in range(8):
                dio_lines.append(f"EIO{i}")
            for i in range(4):
                dio_lines.append(f"CIO{i}")
                
            for dio in dio_lines:
                try:
                    # Read the EF index for this DIO line (0 means no EF configured)
                    ef_index_addr = f"{dio}_EF_INDEX"
                    ef_index = int(ljm.eReadName(self.handle, ef_index_addr))
                    
                    # If EF index is not 0, this line is configured as an EF
                    if ef_index != 0:
                        ef_type = self._get_ef_type(ef_index)
                        
                        # Read the relevant EF registers based on type
                        if ef_type == "counter":
                            # For counters, we need to read the counter value register
                            ef_name = f"{dio}_EF_READ_A"
                            ef_channels.append({
                                "name": ef_name,
                                "type": "ef_counter",
                                "description": f"Counter on {dio}",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                            
                        elif ef_type == "quadrature":
                            # For quadrature, we need to read both position and velocity registers
                            ef_channels.append({
                                "name": f"{dio}_EF_READ_A",
                                "type": "ef_quadrature_position",
                                "description": f"Quadrature Position on {dio}",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                            ef_channels.append({
                                "name": f"{dio}_EF_READ_B",
                                "type": "ef_quadrature_velocity",
                                "description": f"Quadrature Velocity on {dio}",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                            
                        elif ef_type == "pwm_in":
                            # For PWM input, we read duty cycle, frequency, etc.
                            ef_channels.append({
                                "name": f"{dio}_EF_READ_A",
                                "type": "ef_pwm_duty_cycle",
                                "description": f"PWM Duty Cycle on {dio}",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                            ef_channels.append({
                                "name": f"{dio}_EF_READ_B", 
                                "type": "ef_pwm_frequency",
                                "description": f"PWM Frequency on {dio}",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                            
                        else:
                            # Generic EF type
                            ef_channels.append({
                                "name": f"{dio}_EF_READ_A",
                                "type": "ef_generic",
                                "description": f"EF Read A on {dio} (Type: {ef_type})",
                                "dio": dio,
                                "ef_index": ef_index
                            })
                except ljm.LJMError:
                    # Skip if we can't read this register - not all lines support EF
                    continue
                
        except Exception as e:
            print(f"Error getting EF channels: {e}")
            
        return ef_channels
    
    def _get_ef_type(self, ef_index):
        """Get the type of Extended Feature based on its index
        
        Args:
            ef_index: The EF index value
            
        Returns:
            str: The type of EF as a string
        """
        # Map EF indices to their types
        ef_types = {
            0: "none",
            1: "pwm_out",         # PWM Out
            2: "pwm_in",          # PWM In
            3: "frequency_out",   # Frequency Out
            4: "quadrature",      # Quadrature In
            5: "timer_counter",   # Timer/Counter
            6: "counter",         # Counter
            7: "frequency_in",    # Frequency In
            8: "pulse_out",       # Pulse Out
            9: "soft_counter",    # Software Counter
            10: "soft_timer",     # Software Timer
            11: "conditional_reset" # Conditional Reset
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
            
        try:
            # Read the EF register directly
            value = ljm.eReadName(self.handle, channel_name)
            return value
        except ljm.LJMError as e:
            self.error_message = f"Error reading EF channel {channel_name}: {e}"
            print(f"LabJack Read EF Channel Error ({channel_name}): {e}")
            return None
        except Exception as e:
            self.error_message = f"Unexpected error reading EF channel {channel_name}: {e}"
            print(f"LabJack Unexpected Read EF Channel Error ({channel_name}): {e}")
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
            
        # Map EF type string to index
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
            print(f"Unknown EF type: {ef_type}")
            return False
            
        try:
            # Set EF to 0 first to disable any current configuration
            ljm.eWriteName(self.handle, f"{dio}_EF_INDEX", 0)
            
            if ef_index == 0:
                # If we're just disabling the EF, we're done
                return True
                
            # Configure the EF based on the type
            if ef_type.lower() == "counter":
                # Configure as counter
                # Set the config register first (if options provided)
                if "config_a" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                    
                # Set the value (counter start value if provided)
                if "value" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_B", ef_options["value"])
                
                # Finally, set the EF index to enable the counter
                ljm.eWriteName(self.handle, f"{dio}_EF_INDEX", ef_index)
                
            elif ef_type.lower() == "pwm_out":
                # Configure as PWM output
                # Set frequency
                freq = ef_options.get("frequency", 1000)  # Default to 1kHz
                ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_A", freq)
                
                # Set duty cycle (0-100%)
                duty = ef_options.get("duty_cycle", 50)  # Default to 50%
                ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_B", duty)
                
                # Set the EF index to enable
                ljm.eWriteName(self.handle, f"{dio}_EF_INDEX", ef_index)
                
            elif ef_type.lower() == "quadrature":
                # Configure for quadrature encoder input
                # Optionally set configs
                if "config_a" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                if "config_b" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_B", ef_options["config_b"])
                    
                # Set the EF index to enable
                ljm.eWriteName(self.handle, f"{dio}_EF_INDEX", ef_index)
                
            else:
                # Generic configuration
                # Set configs if provided
                if "config_a" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_A", ef_options["config_a"])
                if "config_b" in ef_options:
                    ljm.eWriteName(self.handle, f"{dio}_EF_CONFIG_B", ef_options["config_b"])
                    
                # Set the EF index to enable
                ljm.eWriteName(self.handle, f"{dio}_EF_INDEX", ef_index)
                
            return True
        except ljm.LJMError as e:
            self.error_message = f"Error configuring EF on {dio}: {e}"
            print(f"LabJack EF Configuration Error ({dio}): {e}")
            return False
        except Exception as e:
            self.error_message = f"Unexpected error configuring EF on {dio}: {e}"
            print(f"LabJack Unexpected EF Configuration Error ({dio}): {e}")
            return False

    def _scan_for_thermocouples(self):
        """Scan for directly configured thermocouples using multiple naming patterns
        
        Returns:
            list: List of thermocouple channel dictionaries
        """
        tc_channels = []
        
        try:
            # Direct temperature register names for AIN channels
            ain_patterns = [
                "AIN{}_TEMPERATURE",  # Standard Kipling temperature register
                "AIN{}_TC",           # Thermocouple-specific register
                "AIN{}_K",            # K-type specific register
                "AIN{}_EF_READ_A_F",  # EF output register in Fahrenheit
                "AIN{}_EF_READ_A_C"   # EF output register in Celsius
            ]
            
            # Check each AIN channel with each pattern
            for i in range(14):  # AIN0-AIN13
                for pattern in ain_patterns:
                    register = pattern.format(i)
                    try:
                        # Attempt to read the temperature register
                        value = ljm.eReadName(self.handle, register)
                        
                        # If successful, add it to the list
                        tc_channels.append({
                            "name": register,
                            "type": "ef_temp_thermocouple_K",  # Assume K-type, most common
                            "description": f"K-Type Thermocouple on AIN{i}",
                            "ain": f"AIN{i}",
                            "ef_index": 21  # Standard K-type TC index
                        })
                        
                        # Once we find a working register for this AIN, move to next AIN
                        break
                    except ljm.LJMError:
                        # This register doesn't exist, try the next pattern
                        continue
                    
            return tc_channels
        except Exception as e:
            print(f"Error in thermocouple scan: {e}")
            return []

# Example usage (for testing purposes, remove later)
# if __name__ == "__main__":
#     status_q = queue.Queue()
#     data_q = queue.Queue()
#     lj_thread = LabJackInterface(status_q, data_q)
#     lj_thread.start()
#
#     try:
#         while True:
#             try:
#                 status = status_q.get(timeout=0.1)
#                 print(f"STATUS: {status}")
#             except queue.Empty:
#                 pass
#             # try:
#             #     data = data_q.get(timeout=0.1)
#             #     print(f"DATA: {data}")
#             # except queue.Empty:
#             #     pass
#             time.sleep(0.5)
#     except KeyboardInterrupt:
#         print("Stopping LabJack thread...")
#         lj_thread.stop()
#         lj_thread.join() # Wait for thread to finish
#         print("LabJack thread stopped.") 