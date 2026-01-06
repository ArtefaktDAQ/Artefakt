"""
Data Flow Controller

Tracks and visualizes real-time data flow statistics across all interfaces.
Provides monitoring for data rates, file sizes, and command outputs.
"""

import time
import collections
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QMutex


class DataFlowController(QObject):
    """Controller for tracking and displaying data flow statistics"""
    
    # Signals for UI updates
    stats_updated = pyqtSignal()  # Emitted when statistics are updated
    outbound_command_sent = pyqtSignal(dict)  # Emitted when a command is sent to a device
    
    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self._mutex = QMutex()
        
        # Statistics tracking
        self._init_stats()
        
        # Outbound command log (last 50 commands)
        self.outbound_log = collections.deque(maxlen=50)
        
        # Timing for rate calculations using rolling window
        self._last_update_time = time.time()
        
        # Use rolling window for rate calculation (last 5 seconds of timestamps)
        self._sample_timestamps = {
            'arduino': collections.deque(maxlen=100),
            'labjack': collections.deque(maxlen=100),
            'other_serial': collections.deque(maxlen=100),
            'camera': collections.deque(maxlen=100),
            'audio': collections.deque(maxlen=100),
            'optical': collections.deque(maxlen=100),
            'csv_input': collections.deque(maxlen=100),
            'remote_daq': collections.deque(maxlen=100),
            'mqtt': collections.deque(maxlen=100),
        }
        self._byte_timestamps = {
            'arduino': collections.deque(maxlen=100),  # (timestamp, bytes) tuples
            'labjack': collections.deque(maxlen=100),
            'other_serial': collections.deque(maxlen=100),
            'camera': collections.deque(maxlen=100),
            'audio': collections.deque(maxlen=100),
            'optical': collections.deque(maxlen=100),
            'csv': collections.deque(maxlen=100),
            'csv_input': collections.deque(maxlen=100),
            'remote_daq': collections.deque(maxlen=100),
            'mqtt': collections.deque(maxlen=100),
        }
        
        # Rolling average buffers for smoothing (store last N rate values)
        self._rolling_window_size = 10  # Number of recent values to average
        self._rolling_sample_rates = {
            'arduino': collections.deque(maxlen=self._rolling_window_size),
            'labjack': collections.deque(maxlen=self._rolling_window_size),
            'other_serial': collections.deque(maxlen=self._rolling_window_size),
            'camera': collections.deque(maxlen=self._rolling_window_size),
            'audio': collections.deque(maxlen=self._rolling_window_size),
            'optical': collections.deque(maxlen=self._rolling_window_size),
            'csv_input': collections.deque(maxlen=self._rolling_window_size),
            'remote_daq': collections.deque(maxlen=self._rolling_window_size),
            'mqtt': collections.deque(maxlen=self._rolling_window_size),
        }
        self._rolling_byte_rates = {
            'arduino': collections.deque(maxlen=self._rolling_window_size),
            'labjack': collections.deque(maxlen=self._rolling_window_size),
            'other_serial': collections.deque(maxlen=self._rolling_window_size),
            'camera': collections.deque(maxlen=self._rolling_window_size),
            'audio': collections.deque(maxlen=self._rolling_window_size),
            'optical': collections.deque(maxlen=self._rolling_window_size),
            'csv': collections.deque(maxlen=self._rolling_window_size),
            'csv_input': collections.deque(maxlen=self._rolling_window_size),
            'remote_daq': collections.deque(maxlen=self._rolling_window_size),
            'mqtt': collections.deque(maxlen=self._rolling_window_size),
        }
        
        # Update timer (1 Hz for display updates)
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._calculate_rates)
        self._update_timer.start(1000)
        
    def _init_stats(self):
        """Initialize statistics structure"""
        self.stats = {
            'arduino': {
                'connected': False,
                'sensor_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'labjack': {
                'connected': False,
                'channel_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'other_serial': {
                'connected': False,
                'device_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'camera': {
                'connected': False,
                'resolution': (0, 0),
                'fps': 0.0,
                'bytes_per_sec': 0.0,
                'frame_count': 0,
                'last_update': None,
            },
            'audio': {
                'connected': False,
                'sensor_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'optical': {
                'connected': False,
                'sensor_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'csv_input': {
                'connected': False,
                'file_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'remote_daq': {
                'connected': False,
                'is_client': False,
                'is_master': False,
                'sensor_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'mqtt': {
                'connected': False,
                'topic_count': 0,
                'samples_per_sec': 0.0,
                'bytes_per_sec': 0.0,
                'total_samples': 0,
                'last_update': None,
            },
            'recorder': {
                'recording': False,
                'duration_sec': 0.0,
                'file_size_bytes': 0,
                'file_path': '',
                'bitrate_kbps': 0.0,
            },
            'csv': {
                'writing': False,
                'file_path': '',
                'file_size_bytes': 0,
                'row_count': 0,
                'write_rate_bytes': 0.0,
            },
            'data_manager': {
                'buffer_size': 0,
                'points_per_sec': 0.0,
                'total_points': 0,
            },
            'stream': {
                'active': False,
                'is_master': False,
                'client_count': 0,
                'bytes_out_per_sec': 0.0,
                'stream_name': '',
            },
            'automations': {
                'active_count': 0,
                'total_count': 0,
                'running_names': [],
            },
            'outbound': {
                'arduino': {'count': 0, 'last_command': '', 'last_time': None, 'last_source': ''},
                'labjack': {'count': 0, 'last_channel': '', 'last_value': None, 'last_time': None, 'last_source': ''},
                'serial': {'count': 0, 'last_port': '', 'last_command': '', 'last_time': None, 'last_source': ''},
            },
        }
    
    def _calculate_rates(self):
        """Calculate data rates - simple count-based approach"""
        current_time = time.time()
        window_seconds = 5.0  # Look at last 5 seconds of data
        
        self._mutex.lock()
        try:
            # Calculate sample rates for each device
            for key in ['arduino', 'labjack', 'other_serial', 'csv_input', 'remote_daq', 'mqtt']:
                # Remove old timestamps outside the window
                while (self._sample_timestamps[key] and 
                       current_time - self._sample_timestamps[key][0] > window_seconds):
                    self._sample_timestamps[key].popleft()
                
                timestamps = list(self._sample_timestamps[key])
                num_samples = len(timestamps)
                
                if num_samples >= 2:
                    # Calculate rate from interval between consecutive samples
                    # For 1Hz: samples at t=0, t=1, t=2 -> intervals are [1, 1] -> avg = 1s -> rate = 1Hz
                    intervals = [timestamps[i+1] - timestamps[i] for i in range(num_samples - 1)]
                    avg_interval = sum(intervals) / len(intervals)
                    if avg_interval > 0:
                        new_rate = 1.0 / avg_interval
                    else:
                        new_rate = 0.0
                elif num_samples == 1:
                    # Single sample - if recent, keep previous rate or show 0
                    if current_time - timestamps[0] < 3.0:
                        new_rate = self.stats[key]['samples_per_sec']
                    else:
                        new_rate = 0.0
                else:
                    new_rate = 0.0
                
                # Use rolling average for smoothing
                self._rolling_sample_rates[key].append(new_rate)
                if len(self._rolling_sample_rates[key]) > 0:
                    self.stats[key]['samples_per_sec'] = sum(self._rolling_sample_rates[key]) / len(self._rolling_sample_rates[key])
                else:
                    self.stats[key]['samples_per_sec'] = 0.0
                
                # Calculate bytes rate
                while (self._byte_timestamps[key] and 
                       current_time - self._byte_timestamps[key][0][0] > window_seconds):
                    self._byte_timestamps[key].popleft()
                
                byte_entries = list(self._byte_timestamps[key])
                if len(byte_entries) >= 2:
                    time_span = byte_entries[-1][0] - byte_entries[0][0]
                    total_bytes = sum(b[1] for b in byte_entries)
                    new_byte_rate = total_bytes / time_span if time_span > 0 else 0.0
                else:
                    new_byte_rate = 0.0
                
                # Use rolling average for smoothing
                self._rolling_byte_rates[key].append(new_byte_rate)
                if len(self._rolling_byte_rates[key]) > 0:
                    self.stats[key]['bytes_per_sec'] = sum(self._rolling_byte_rates[key]) / len(self._rolling_byte_rates[key])
                else:
                    self.stats[key]['bytes_per_sec'] = 0.0
            
            # Camera FPS
            while (self._sample_timestamps['camera'] and 
                   current_time - self._sample_timestamps['camera'][0] > window_seconds):
                self._sample_timestamps['camera'].popleft()
            
            cam_timestamps = list(self._sample_timestamps['camera'])
            if len(cam_timestamps) >= 2:
                intervals = [cam_timestamps[i+1] - cam_timestamps[i] for i in range(len(cam_timestamps) - 1)]
                avg_interval = sum(intervals) / len(intervals)
                new_fps = 1.0 / avg_interval if avg_interval > 0 else 0.0
            elif len(cam_timestamps) == 1 and current_time - cam_timestamps[0] < 1.0:
                new_fps = self.stats['camera']['fps']
            else:
                new_fps = 0.0
            
            # Use rolling average for smoothing
            self._rolling_sample_rates['camera'].append(new_fps)
            if len(self._rolling_sample_rates['camera']) > 0:
                self.stats['camera']['fps'] = sum(self._rolling_sample_rates['camera']) / len(self._rolling_sample_rates['camera'])
            else:
                self.stats['camera']['fps'] = 0.0
            
            # Camera bytes
            while (self._byte_timestamps['camera'] and 
                   current_time - self._byte_timestamps['camera'][0][0] > window_seconds):
                self._byte_timestamps['camera'].popleft()
            
            cam_byte_entries = list(self._byte_timestamps['camera'])
            if len(cam_byte_entries) >= 2:
                time_span = cam_byte_entries[-1][0] - cam_byte_entries[0][0]
                total_bytes = sum(b[1] for b in cam_byte_entries)
                new_cam_rate = total_bytes / time_span if time_span > 0 else 0.0
            else:
                new_cam_rate = 0.0
            
            # Use rolling average for smoothing
            self._rolling_byte_rates['camera'].append(new_cam_rate)
            if len(self._rolling_byte_rates['camera']) > 0:
                self.stats['camera']['bytes_per_sec'] = sum(self._rolling_byte_rates['camera']) / len(self._rolling_byte_rates['camera'])
            else:
                self.stats['camera']['bytes_per_sec'] = 0.0
            
            # CSV write rate
            while (self._byte_timestamps['csv'] and 
                   current_time - self._byte_timestamps['csv'][0][0] > window_seconds):
                self._byte_timestamps['csv'].popleft()
            
            csv_byte_entries = list(self._byte_timestamps['csv'])
            if len(csv_byte_entries) >= 2:
                time_span = csv_byte_entries[-1][0] - csv_byte_entries[0][0]
                total_bytes = sum(b[1] for b in csv_byte_entries)
                new_csv_rate = total_bytes / time_span if time_span > 0 else 0.0
            else:
                new_csv_rate = 0.0
            
            # Use rolling average for smoothing
            self._rolling_byte_rates['csv'].append(new_csv_rate)
            if len(self._rolling_byte_rates['csv']) > 0:
                self.stats['csv']['write_rate_bytes'] = sum(self._rolling_byte_rates['csv']) / len(self._rolling_byte_rates['csv'])
            else:
                self.stats['csv']['write_rate_bytes'] = 0.0
            
            # Calculate audio sensor rates
            for key in ['audio', 'optical']:
                # Remove old timestamps outside the window
                while (self._sample_timestamps[key] and 
                       current_time - self._sample_timestamps[key][0] > window_seconds):
                    self._sample_timestamps[key].popleft()
                
                timestamps = list(self._sample_timestamps[key])
                num_samples = len(timestamps)
                
                if num_samples >= 2:
                    intervals = [timestamps[i+1] - timestamps[i] for i in range(num_samples - 1)]
                    avg_interval = sum(intervals) / len(intervals)
                    if avg_interval > 0:
                        new_rate = 1.0 / avg_interval
                    else:
                        new_rate = 0.0
                elif num_samples == 1:
                    if current_time - timestamps[0] < 3.0:
                        new_rate = self.stats[key]['samples_per_sec']
                    else:
                        new_rate = 0.0
                else:
                    new_rate = 0.0
                
                # Use rolling average for smoothing
                self._rolling_sample_rates[key].append(new_rate)
                if len(self._rolling_sample_rates[key]) > 0:
                    self.stats[key]['samples_per_sec'] = sum(self._rolling_sample_rates[key]) / len(self._rolling_sample_rates[key])
                else:
                    self.stats[key]['samples_per_sec'] = 0.0
                
                # Calculate bytes rate
                while (self._byte_timestamps[key] and 
                       current_time - self._byte_timestamps[key][0][0] > window_seconds):
                    self._byte_timestamps[key].popleft()
                
                byte_entries = list(self._byte_timestamps[key])
                if len(byte_entries) >= 2:
                    time_span = byte_entries[-1][0] - byte_entries[0][0]
                    total_bytes = sum(b[1] for b in byte_entries)
                    new_byte_rate = total_bytes / time_span if time_span > 0 else 0.0
                else:
                    new_byte_rate = 0.0
                
                # Use rolling average for smoothing
                self._rolling_byte_rates[key].append(new_byte_rate)
                if len(self._rolling_byte_rates[key]) > 0:
                    self.stats[key]['bytes_per_sec'] = sum(self._rolling_byte_rates[key]) / len(self._rolling_byte_rates[key])
                else:
                    self.stats[key]['bytes_per_sec'] = 0.0
            
            # Calculate data manager points per second (sum of all input rates)
            self.stats['data_manager']['points_per_sec'] = (
                self.stats['arduino']['samples_per_sec'] +
                self.stats['labjack']['samples_per_sec'] +
                self.stats['other_serial']['samples_per_sec'] +
                self.stats['audio']['samples_per_sec'] +
                self.stats['optical']['samples_per_sec'] +
                self.stats['csv_input']['samples_per_sec'] +
                self.stats['remote_daq']['samples_per_sec'] +
                self.stats['mqtt']['samples_per_sec']
            )
            
        finally:
            self._mutex.unlock()
        
        self._last_update_time = current_time
        
        # Update from controllers
        self._update_from_controllers()
        
        # Emit update signal
        self.stats_updated.emit()
    
    def _update_from_controllers(self):
        """Pull current status from main window controllers"""
        if not self.main_window:
            return
        
        self._mutex.lock()
        try:
            # Data Collection Controller stats
            if hasattr(self.main_window, 'data_collection_controller'):
                dcc = self.main_window.data_collection_controller
                
                # Arduino
                self.stats['arduino']['connected'] = dcc.interfaces.get('arduino', {}).get('connected', False)
                
                # LabJack
                self.stats['labjack']['connected'] = dcc.interfaces.get('labjack', {}).get('connected', False)
                
                # Other Serial
                self.stats['other_serial']['connected'] = dcc.interfaces.get('other_serial', {}).get('connected', False)
                
                # CSV stats
                self.stats['csv']['writing'] = dcc.collecting_data
                if dcc.csv_filename:
                    self.stats['csv']['file_path'] = dcc.csv_filename
                    try:
                        import os
                        if os.path.exists(dcc.csv_filename):
                            self.stats['csv']['file_size_bytes'] = os.path.getsize(dcc.csv_filename)
                    except:
                        pass
                
                # Data manager buffer size
                if hasattr(dcc, 'historical_buffer'):
                    total_points = sum(len(buf) for buf in dcc.historical_buffer.values())
                    self.stats['data_manager']['buffer_size'] = total_points
                    self.stats['data_manager']['total_points'] = total_points
            
            # Sensor Controller stats
            if hasattr(self.main_window, 'sensor_controller'):
                sc = self.main_window.sensor_controller
                arduino_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'Arduino'])
                labjack_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'LabJack'])
                other_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'OtherSerial'])
                audio_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'AudioSensor'])
                optical_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'OpticalSensor'])
                csv_input_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'CSVInterface'])
                remote_daq_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'remote_stream'])
                mqtt_sensors = len([s for s in sc.sensors if getattr(s, 'interface_type', '') == 'MQTT'])
                
                self.stats['arduino']['sensor_count'] = arduino_sensors
                self.stats['labjack']['channel_count'] = labjack_sensors
                self.stats['other_serial']['device_count'] = other_sensors
                self.stats['audio']['sensor_count'] = audio_sensors
                self.stats['optical']['sensor_count'] = optical_sensors
                self.stats['csv_input']['file_count'] = csv_input_sensors
                self.stats['remote_daq']['sensor_count'] = remote_daq_sensors
                self.stats['mqtt']['topic_count'] = mqtt_sensors
                
                # Check if audio sensors are connected
                if hasattr(sc, 'audio_sensor_interfaces') and sc.audio_sensor_interfaces:
                    connected_audio = sum(1 for interface in sc.audio_sensor_interfaces.values() 
                                        if interface and getattr(interface, 'connected', False))
                    self.stats['audio']['connected'] = connected_audio > 0
                else:
                    self.stats['audio']['connected'] = False
                
                # Check if optical sensors are connected
                if hasattr(sc, 'optical_sensor_interfaces') and sc.optical_sensor_interfaces:
                    connected_optical = sum(1 for interface in sc.optical_sensor_interfaces.values() 
                                           if interface and getattr(interface, 'connected', False))
                    self.stats['optical']['connected'] = connected_optical > 0
                else:
                    self.stats['optical']['connected'] = False

            # MQTT & CSV Input Support
            if hasattr(self.main_window, 'data_collection_controller'):
                dcc = self.main_window.data_collection_controller
                if hasattr(dcc, 'mqtt_thread') and dcc.mqtt_thread:
                    self.stats['mqtt']['connected'] = getattr(dcc.mqtt_thread, 'connected', False)
                else:
                    self.stats['mqtt']['connected'] = False
                
                if hasattr(dcc, 'csv_thread') and dcc.csv_thread:
                    # CSV thread is considered connected if it has any active interfaces
                    self.stats['csv_input']['connected'] = len(dcc.csv_thread.interfaces) > 0
                else:
                    self.stats['csv_input']['connected'] = False
            
            # Camera Controller stats
            if hasattr(self.main_window, 'camera_controller'):
                cc = self.main_window.camera_controller
                self.stats['camera']['connected'] = cc.is_connected
                self.stats['recorder']['recording'] = cc.is_recording
                
                if cc.is_connected and hasattr(cc, 'camera_thread') and cc.camera_thread:
                    # Get resolution from camera thread if available
                    if hasattr(cc.camera_thread, 'frame_width') and hasattr(cc.camera_thread, 'frame_height'):
                        self.stats['camera']['resolution'] = (
                            cc.camera_thread.frame_width,
                            cc.camera_thread.frame_height
                        )
                
                # Recording stats
                if cc.is_recording and hasattr(cc, 'camera_thread') and cc.camera_thread:
                    if hasattr(cc.camera_thread, 'recording_file'):
                        self.stats['recorder']['file_path'] = cc.camera_thread.recording_file or ''
                        try:
                            import os
                            if cc.camera_thread.recording_file and os.path.exists(cc.camera_thread.recording_file):
                                self.stats['recorder']['file_size_bytes'] = os.path.getsize(cc.camera_thread.recording_file)
                        except:
                            pass
                    
                    if hasattr(cc.camera_thread, 'recording_start_time') and cc.camera_thread.recording_start_time:
                        self.stats['recorder']['duration_sec'] = time.time() - cc.camera_thread.recording_start_time
            
            # Stream Controller stats
            if hasattr(self.main_window, 'stream_controller'):
                stream = self.main_window.stream_controller
                self.stats['stream']['active'] = stream.is_master or stream.is_client
                self.stats['stream']['is_master'] = stream.is_master
                self.stats['stream']['stream_name'] = stream.current_stream_name
                # Client count would need to be tracked in the stream controller
                
                self.stats['remote_daq']['connected'] = stream.is_client or stream.is_master
                self.stats['remote_daq']['is_client'] = stream.is_client
                self.stats['remote_daq']['is_master'] = stream.is_master
            
            # Automation Controller stats
            if hasattr(self.main_window, 'automation_controller'):
                ac = self.main_window.automation_controller
                if hasattr(ac, 'manager'):
                    running = [seq.name for seq in ac.manager.sequences if seq.is_running]
                    self.stats['automations']['running_names'] = running
                    self.stats['automations']['active_count'] = len(running)
                    self.stats['automations']['total_count'] = len(ac.manager.sequences)
        
        finally:
            self._mutex.unlock()
    
    # --- Methods to record data flow events ---
    
    def record_arduino_data(self, data_dict, byte_size=0):
        """Record incoming Arduino data (1 sample per data event, not per sensor)"""
        current_time = time.time()
        self._mutex.lock()
        try:
            # Add timestamp for rate calculation (1 sample per data event)
            self._sample_timestamps['arduino'].append(current_time)
            
            # Add byte count with timestamp
            actual_bytes = byte_size if byte_size else len(str(data_dict))
            self._byte_timestamps['arduino'].append((current_time, actual_bytes))
            
            self.stats['arduino']['total_samples'] += 1
            self.stats['arduino']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_labjack_data(self, data_dict, byte_size=0):
        """Record incoming LabJack data (1 sample per data event, not per channel)"""
        current_time = time.time()
        self._mutex.lock()
        try:
            # Add timestamp for rate calculation (1 sample per data event)
            self._sample_timestamps['labjack'].append(current_time)
            
            # Add byte count with timestamp
            actual_bytes = byte_size if byte_size else len(str(data_dict))
            self._byte_timestamps['labjack'].append((current_time, actual_bytes))
            
            self.stats['labjack']['total_samples'] += 1
            self.stats['labjack']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_other_serial_data(self, data_dict, byte_size=0):
        """Record incoming Other Serial data (1 sample per data event)"""
        current_time = time.time()
        self._mutex.lock()
        try:
            # Add timestamp for rate calculation (1 sample per data event)
            self._sample_timestamps['other_serial'].append(current_time)
            
            # Add byte count with timestamp
            actual_bytes = byte_size if byte_size else len(str(data_dict))
            self._byte_timestamps['other_serial'].append((current_time, actual_bytes))
            
            self.stats['other_serial']['total_samples'] += 1
            self.stats['other_serial']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_camera_frame(self, byte_size=0):
        """Record camera frame received"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['camera'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['camera'].append((current_time, byte_size))
            self.stats['camera']['frame_count'] += 1
            self.stats['camera']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_audio_sensor_data(self, byte_size=0):
        """Record audio sensor data received"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['audio'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['audio'].append((current_time, byte_size))
            self.stats['audio']['total_samples'] += 1
            self.stats['audio']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_optical_sensor_data(self, byte_size=0):
        """Record optical sensor data received"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['optical'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['optical'].append((current_time, byte_size))
            self.stats['optical']['total_samples'] += 1
            self.stats['optical']['last_update'] = current_time
        finally:
            self._mutex.unlock()
            
    def record_csv_input_data(self, byte_size=0):
        """Record data received from CSV input interface"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['csv_input'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['csv_input'].append((current_time, byte_size))
            self.stats['csv_input']['total_samples'] += 1
            self.stats['csv_input']['last_update'] = current_time
        finally:
            self._mutex.unlock()
            
    def record_remote_daq_data(self, byte_size=0):
        """Record data received from remote DAQ stream"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['remote_daq'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['remote_daq'].append((current_time, byte_size))
            self.stats['remote_daq']['total_samples'] += 1
            self.stats['remote_daq']['last_update'] = current_time
        finally:
            self._mutex.unlock()
            
    def record_mqtt_data(self, byte_size=0):
        """Record data received from MQTT topics"""
        current_time = time.time()
        self._mutex.lock()
        try:
            self._sample_timestamps['mqtt'].append(current_time)
            if byte_size > 0:
                self._byte_timestamps['mqtt'].append((current_time, byte_size))
            self.stats['mqtt']['total_samples'] += 1
            self.stats['mqtt']['last_update'] = current_time
        finally:
            self._mutex.unlock()
    
    def record_csv_write(self, byte_size, row_count=1):
        """Record CSV data written"""
        current_time = time.time()
        self._mutex.lock()
        try:
            if byte_size > 0:
                self._byte_timestamps['csv'].append((current_time, byte_size))
            self.stats['csv']['row_count'] += row_count
        finally:
            self._mutex.unlock()
    
    def record_outbound_command(self, target, command, source_automation='Manual', **kwargs):
        """
        Record an outbound command sent to a device
        
        Args:
            target: 'arduino', 'labjack', or 'serial'
            command: The command string or value sent
            source_automation: Name of the automation that triggered it
            **kwargs: Additional info (channel, port, value, etc.)
        """
        entry = {
            'timestamp': time.time(),
            'target': target,
            'command': str(command),
            'source': source_automation,
            **kwargs
        }
        
        self._mutex.lock()
        try:
            self.outbound_log.append(entry)
            
            # Update stats
            if target in self.stats['outbound']:
                self.stats['outbound'][target]['count'] += 1
                self.stats['outbound'][target]['last_command'] = str(command)
                self.stats['outbound'][target]['last_time'] = entry['timestamp']
                self.stats['outbound'][target]['last_source'] = source_automation
                
                if 'channel' in kwargs:
                    self.stats['outbound'][target]['last_channel'] = kwargs['channel']
                if 'value' in kwargs:
                    self.stats['outbound'][target]['last_value'] = kwargs['value']
                if 'port' in kwargs:
                    self.stats['outbound'][target]['last_port'] = kwargs['port']
        finally:
            self._mutex.unlock()
        
        # Emit signal for UI update
        self.outbound_command_sent.emit(entry)
    
    def get_outbound_log(self):
        """Get a copy of the outbound command log"""
        self._mutex.lock()
        try:
            return list(self.outbound_log)
        finally:
            self._mutex.unlock()
    
    def get_stats(self):
        """Get a copy of current statistics"""
        self._mutex.lock()
        try:
            import copy
            return copy.deepcopy(self.stats)
        finally:
            self._mutex.unlock()
    
    def format_bytes(self, bytes_value):
        """Format bytes to human-readable string"""
        if bytes_value < 1024:
            return f"{bytes_value:.0f} B"
        elif bytes_value < 1024 * 1024:
            return f"{bytes_value / 1024:.1f} KB"
        elif bytes_value < 1024 * 1024 * 1024:
            return f"{bytes_value / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_value / (1024 * 1024 * 1024):.2f} GB"
    
    def format_rate(self, bytes_per_sec):
        """Format bytes per second to human-readable string"""
        return self.format_bytes(bytes_per_sec) + "/s"
    
    def format_time_ago(self, timestamp):
        """Format timestamp as 'X ago' string"""
        if timestamp is None:
            return "Never"
        
        elapsed = time.time() - timestamp
        if elapsed < 1:
            return "Just now"
        elif elapsed < 60:
            return f"{elapsed:.0f}s ago"
        elif elapsed < 3600:
            return f"{elapsed / 60:.0f}m ago"
        else:
            return f"{elapsed / 3600:.1f}h ago"

