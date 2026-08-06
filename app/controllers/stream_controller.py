"""
Stream Controller

Manages remote DAQ stream connections for distributed data acquisition.
Provides easy-to-use interface for both master (streaming) and client (receiving) modes.
"""

import time
import threading
import queue
import grpc
from concurrent import futures
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread, QMutexLocker
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QLineEdit, QCheckBox, QTextEdit,
                            QMessageBox, QTableWidget, QTableWidgetItem,
                            QHeaderView, QGroupBox, QFormLayout, QSpinBox,
                            QComboBox, QProgressBar, QTabWidget, QWidget,
                            QFrame, QGridLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from app.core.logger import Logger
from app.ui.theme import GroupBoxStyles, ButtonStyles, CardStyles, COLORS
from app.utils.common_types import StatusState

GRPC_CHANNEL_OPTIONS = [
    ('grpc.keepalive_time_ms', 10000),
    ('grpc.keepalive_timeout_ms', 5000),
    ('grpc.http2.max_pings_without_data', 0),
    ('grpc.keepalive_permit_without_calls', 1),
]
GRPC_CONNECT_TIMEOUT = 5.0
DEFAULT_GRPC_PORT = 50051


def _parse_grpc_target(master_address, default_port=DEFAULT_GRPC_PORT):
    """Return host:port, preserving an explicit port in master_address."""
    address = master_address.strip()
    if ':' in address:
        host, port = address.rsplit(':', 1)
        return f"{host}:{port}"
    return f"{address}:{default_port}"


# Import protobuf generated files
try:
    from app.proto import daq_service_pb2
    from app.proto import daq_service_pb2_grpc
except ImportError:
    # Fallback for development
    daq_service_pb2 = None
    daq_service_pb2_grpc = None

class StreamController(QObject):
    """Manages remote DAQ stream connections with user-friendly interface"""
    
    # Signals for UI updates
    stream_connected = pyqtSignal(str)  # Stream name
    stream_disconnected = pyqtSignal()
    remote_sensors_available = pyqtSignal(list)  # List of RemoteSensor
    remote_video_available = pyqtSignal(bool)
    status_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)  # Error message
    connect_finished = pyqtSignal(bool, str)
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.logger = Logger("StreamController")
        print("StreamController: Initializing...")  # Debug output
        
        # Connection state
        self.is_master = False
        self.is_client = False
        self.connected_streams = {}  # {stream_name: grpc_channel}
        self.remote_sensors = {}     # {sensor_id: RemoteSensor}
        self.permission_level = 1    # Default: view only
        
        # Current stream info (for UI persistence)
        self.current_stream_name = ""
        self.current_stream_password = ""
        self.current_stream_description = ""
        self.current_master_address = ""
        self.current_client_name = ""
        self.current_stream_options = {
            'enable_sensors': True,
            'enable_video': True,
            'enable_audio': False,
            'enable_remote_control': False
        }
        self.current_request_audio = False
        
        # gRPC components
        self.grpc_server = None
        self.grpc_executor = None
        self.service_servicer = None
        self.grpc_thread = None
        self.client_stub = None
        self.client_session_id = None
        self.client_stop_event = threading.Event()
        self.receive_threads = []
        self._connect_worker = None
        self._pending_available_sensors = []
        
        # Coalesced remote UI updates (GRPC-10)
        self._pending_sensor_data = {}
        self._pending_video_frame = None
        self._ui_coalesce_timer = QTimer()
        self._ui_coalesce_timer.setInterval(50)
        self._ui_coalesce_timer.timeout.connect(self._drain_pending_remote_ui)
        
        # UI elements
        self.setup_ui()
        
        # Status timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # Update every second
        
        self.logger.log("Stream controller initialized", "INFO")
    
    def setup_ui(self):
        """Setup UI elements for stream functionality"""
        # This method is called during initialization, but UI elements might not be ready yet
        pass
    
    def add_stream_button_to_ui(self):
        """Add the stream button to the UI after it's fully initialized"""
        try:
            # Check if main_window has the devices_cards_layout (vertical layout)
            if hasattr(self.main_window, 'devices_cards_layout'):
                layout = self.main_window.devices_cards_layout
                
                # Check if Remote DAQ container already exists
                if hasattr(self, 'remote_container') and self.remote_container:
                    return True
                
                # Get the card style and size from main_window
                card_style = getattr(self.main_window, 'device_card_style', CardStyles.device_card(False))
                card_size = getattr(self.main_window, 'device_card_size', (100, 85))
                
                # Create the remote DAQ container with matching style
                remote_container = QFrame()
                remote_container.setFixedSize(card_size[0], card_size[1])
                remote_container.setStyleSheet(card_style)
                remote_container.setCursor(Qt.CursorShape.PointingHandCursor)
                
                # Create layout for the remote container
                remote_layout = QVBoxLayout(remote_container)
                remote_layout.setContentsMargins(6, 6, 6, 6)
                remote_layout.setSpacing(2)
                
                # Add icon
                # Use a network icon to avoid implying public internet
                remote_icon = QLabel("🖧")
                remote_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                remote_icon.setStyleSheet("font-size: 28px; background-color: transparent; border: none;")
                remote_layout.addWidget(remote_icon)
                
                # Add label
                remote_label = QLabel("Remote gRPC")
                remote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                remote_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #fff; border: none; background-color: transparent;")
                remote_layout.addWidget(remote_label)
                
                # Add status label
                self.remote_status_label = QLabel("LAN / VPN only")
                self.remote_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.remote_status_label.setStyleSheet("font-size: 9px; color: #888; border: none; background-color: transparent;")
                remote_layout.addWidget(self.remote_status_label)
                
                # Add click event to open stream dialog
                remote_container.setToolTip("gRPC link for local/LAN use; for internet use VPN/SSH tunnels.")
                remote_container.mousePressEvent = lambda event: self.show_stream_dialog()
                
                # Store reference to remote container for status updates
                self.remote_container = remote_container
                
                # Add at the end of the vertical layout (after MQTT)
                # Insert before the stretch if it exists, otherwise just add
                item_count = layout.count()
                if item_count > 0:
                    # Check if last item is a stretch (spacer item)
                    last_item = layout.itemAt(item_count - 1)
                    if last_item and last_item.spacerItem():
                        layout.insertWidget(item_count - 1, remote_container)
                    else:
                        layout.addWidget(remote_container)
                else:
                    layout.addWidget(remote_container)
                
                self.logger.log("Remote DAQ button added to devices cards", "INFO")
                return True
            
            self.logger.log("Could not find devices_cards_layout", "WARNING")
            return False
            
        except Exception as e:
            self.logger.log(f"Error adding stream button: {str(e)}", "ERROR")
            return False
    
    def show_stream_dialog(self):
        """Show the main stream connection dialog"""
        dialog = StreamConnectionDialog(self)
        dialog.exec()
    
    def start_master_streaming(self, stream_name, password, description, 
                             enable_sensors=True, enable_video=True,
                             enable_audio=False):
        """Start streaming as master (data source)"""
        try:
            # STR-R-11: mutual exclusion with client mode
            if self.is_client:
                self.disconnect_from_stream(self.current_stream_name)
            if self.grpc_server:
                self.stop_master_streaming()
            
            # Start gRPC server
            self.start_grpc_server(stream_name, password, description,
                                 enable_sensors, enable_video, enable_audio)
            
            self.is_master = True
            
            # Store current stream info
            self.current_stream_name = stream_name
            self.current_stream_password = password
            self.current_stream_description = description
            self.current_stream_options = {
                'enable_sensors': enable_sensors,
                'enable_video': enable_video,
                'enable_audio': enable_audio
            }
            
            self.logger.log(f"Started master streaming: {stream_name}", "INFO")
            self.stream_connected.emit(stream_name)
            self.status_changed.emit()
            

            
            return True, "Streaming started successfully"
            
        except Exception as e:
            self.is_master = False
            self.logger.log(f"Failed to start streaming: {str(e)}", "ERROR")
            self.error_occurred.emit(f"Failed to start streaming: {str(e)}")
            return False, str(e)
    
    def connect_to_master_stream(self, master_address, stream_name, password, 
                               client_name, request_sensors=True, request_video=True,
                               request_audio=False):
        """Connect as client to a master stream (blocking, main-thread safe)."""
        # Mutual exclusion when called synchronously from UI thread
        if self.is_master:
            self.stop_master_streaming()
        if self.is_client:
            self.disconnect_from_stream(self.current_stream_name)
        success, message = self._connect_to_master_stream_sync(
            master_address, stream_name, password, client_name,
            request_sensors, request_video, request_audio
        )
        if success:
            self._apply_pending_available_sensors()
        return success, message

    def begin_connect_to_master_stream(self, master_address, stream_name, password,
                                       client_name, request_sensors=True, request_video=True,
                                       request_audio=False):
        """Start non-blocking connect in a background thread (GRPC-03)."""
        if self._connect_worker and self._connect_worker.isRunning():
            return False
        # Mutual exclusion / reconnect cleanup must run on the UI thread
        if self.is_master:
            self.stop_master_streaming()
        if self.is_client:
            self.disconnect_from_stream(self.current_stream_name)

        self._connect_worker = _ConnectWorker(
            self, master_address, stream_name, password, client_name,
            request_sensors, request_video, request_audio
        )
        self._connect_worker.finished_with_result.connect(self._on_async_connect_finished)
        self._connect_worker.start()
        return True

    def _on_async_connect_finished(self, success, message):
        """Main-thread follow-up after background connect (sensor ingest is UI-bound)."""
        if success:
            self._apply_pending_available_sensors()
        self.connect_finished.emit(success, message)

    def _apply_pending_available_sensors(self):
        """Register sensors advertised at connect time (must run on main thread)."""
        available = getattr(self, '_pending_available_sensors', None) or []
        self._pending_available_sensors = []
        if not available:
            return
        for rs in available:
            self._ingest_remote_sensor(
                sensor_id=rs.id,
                name=rs.name,
                unit=rs.unit,
                value=rs.current_value,
                timestamp_ms=None,
                update_table_on_create=False,
            )
        self.remote_sensors_available.emit(available)
        if hasattr(self.main_window, 'sensor_controller'):
            self.main_window.sensor_controller.update_sensor_table()

    def _connect_to_master_stream_sync(self, master_address, stream_name, password,
                                       client_name, request_sensors=True, request_video=True,
                                       request_audio=False):
        """Internal synchronous connect with timeout. Avoid Qt UI work here (may run off main thread)."""
        if daq_service_pb2 is None or daq_service_pb2_grpc is None:
            return False, "gRPC protobuf files not available"

        channel = None
        try:
            target = _parse_grpc_target(master_address)
            channel = grpc.insecure_channel(target, options=GRPC_CHANNEL_OPTIONS)
            client_stub = daq_service_pb2_grpc.DAQServiceStub(channel)

            request = daq_service_pb2.ConnectRequest(
                master_address=master_address,
                stream_name=stream_name,
                password=password,
                request_sensors=request_sensors,
                request_video=request_video,
                client_name=client_name,
                request_audio=request_audio
            )

            response = client_stub.ConnectToStream(request, timeout=GRPC_CONNECT_TIMEOUT)

            if response.success:
                self.is_client = True
                self.client_stub = client_stub
                self.client_session_id = response.session_id
                self.connected_streams[stream_name] = channel
                self.client_stop_event.clear()
                self.receive_threads.clear()
                self.current_master_address = master_address
                self.current_stream_name = stream_name
                self.current_stream_password = password
                self.current_client_name = client_name
                self.current_request_audio = request_audio

                # Defer SensorModel/UI ingest to main thread (see _on_async_connect_finished)
                self._pending_available_sensors = list(response.available_sensors) if response.available_sensors else []

                self.logger.log(f"Connected to stream: {stream_name}", "INFO")
                self.stream_connected.emit(stream_name)
                self.status_changed.emit()

                if request_sensors:
                    self.start_sensor_streaming(stream_name)
                if request_video:
                    self.start_video_streaming(stream_name)
                if request_audio:
                    self.start_audio_streaming(stream_name)

                return True, "Connected successfully"
            else:
                channel.close()
                return False, response.message

        except Exception as e:
            self.is_client = False
            self.client_stub = None
            self.client_session_id = None
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            self.logger.log(f"Failed to connect to stream: {str(e)}", "ERROR")
            self.error_occurred.emit(f"Connection failed: {str(e)}")
            return False, str(e)
    
    def start_grpc_server(self, stream_name, password, description,
                         enable_sensors, enable_video, enable_audio):
        """Start gRPC server for streaming"""
        if daq_service_pb2_grpc is None:
            raise ImportError("gRPC protobuf files not available")
        
        self.grpc_executor = futures.ThreadPoolExecutor(max_workers=10)
        self.grpc_server = grpc.server(self.grpc_executor)
        
        self.service_servicer = DAQServiceServicer(
            self.main_window, stream_name, password,
            enable_sensors=enable_sensors,
            enable_video=enable_video,
            enable_audio=enable_audio
        )
        daq_service_pb2_grpc.add_DAQServiceServicer_to_server(
            self.service_servicer, self.grpc_server
        )
        
        port = DEFAULT_GRPC_PORT
        bound = self.grpc_server.add_insecure_port(f'[::]:{port}')
        if bound == 0:
            raise RuntimeError(f"Failed to bind gRPC port {port}")
        self.grpc_server.start()
        
        self.logger.log(f"gRPC server started on port {port}", "INFO")
    
    def _stream_metadata(self):
        """Client metadata for authenticated stream RPCs."""
        if self.client_session_id:
            return (('session-id', self.client_session_id),)
        return ()
    
    def _on_client_stream_lost(self):
        """Handle unexpected client stream disconnect (GRPC-12)."""
        if self.is_client:
            self.logger.log("Client stream connection lost", "WARNING")
            self.disconnect_from_stream(self.current_stream_name)
    
    def start_sensor_streaming(self, stream_name):
        """Start receiving sensor data from stream"""
        if not self.client_stub:
            return
        
        metadata = self._stream_metadata()
        
        def receive_sensor_data():
            try:
                request = daq_service_pb2.StreamRequest()
                for sensor_data in self.client_stub.StreamSensorData(request, metadata=metadata):
                    if self.client_stop_event.is_set():
                        break
                    self.process_remote_sensor_data(sensor_data)
            except Exception as e:
                if not self.client_stop_event.is_set():
                    self.logger.log(f"Sensor streaming error: {str(e)}", "ERROR")
                    QTimer.singleShot(0, self._on_client_stream_lost)
        
        sensor_thread = threading.Thread(target=receive_sensor_data, daemon=True)
        self.receive_threads.append(sensor_thread)
        sensor_thread.start()
    
    def start_video_streaming(self, stream_name):
        """Start receiving video data from stream"""
        if not self.client_stub:
            return
        
        metadata = self._stream_metadata()
        
        def receive_video_data():
            try:
                request = daq_service_pb2.VideoRequest()
                for video_frame in self.client_stub.StreamVideo(request, metadata=metadata):
                    if self.client_stop_event.is_set():
                        break
                    self.process_remote_video_frame(video_frame)
            except Exception as e:
                if not self.client_stop_event.is_set():
                    self.logger.log(f"Video streaming error: {str(e)}", "ERROR")
                    QTimer.singleShot(0, self._on_client_stream_lost)
        
        video_thread = threading.Thread(target=receive_video_data, daemon=True)
        self.receive_threads.append(video_thread)
        video_thread.start()

    def start_audio_streaming(self, stream_name):
        """Start receiving audio data from stream and play back locally"""
        if not self.client_stub:
            return
        
        metadata = self._stream_metadata()
        
        def receive_audio_data():
            try:
                try:
                    import sounddevice as sd
                except ImportError:
                    self.logger.log("Audio streaming requires 'sounddevice' package", "ERROR")
                    return
                
                audio_request = daq_service_pb2.AudioRequest()
                output_stream = None
                
                for audio_frame in self.client_stub.StreamAudio(audio_request, metadata=metadata):
                    if self.client_stop_event.is_set():
                        break
                    # Lazily create output stream using first frame parameters
                    if output_stream is None:
                        sample_rate = audio_frame.sample_rate or 44100
                        channels = audio_frame.channels or 1
                        output_stream = sd.RawOutputStream(
                            samplerate=sample_rate,
                            channels=channels,
                            dtype='int16',
                        )
                        output_stream.start()
                    
                    if output_stream:
                        try:
                            output_stream.write(audio_frame.pcm_data)
                        except Exception as write_error:
                            self.logger.log(f"Audio playback error: {write_error}", "ERROR")
                            break
            
            except Exception as e:
                if not self.client_stop_event.is_set():
                    self.logger.log(f"Audio streaming error: {str(e)}", "ERROR")
                    QTimer.singleShot(0, self._on_client_stream_lost)
            
            finally:
                try:
                    if 'output_stream' in locals() and output_stream:
                        output_stream.stop()
                        output_stream.close()
                except Exception:
                    pass
        
        audio_thread = threading.Thread(target=receive_audio_data, daemon=True)
        self.receive_threads.append(audio_thread)
        audio_thread.start()
    
    def process_remote_sensor_data(self, sensor_data):
        """Queue sensor data for coalesced UI update (GRPC-10)."""
        self._pending_sensor_data[sensor_data.sensor_id] = sensor_data
        if not self._ui_coalesce_timer.isActive():
            self._ui_coalesce_timer.start()

    def process_remote_video_frame(self, video_frame):
        """Queue latest video frame for coalesced UI update (GRPC-10)."""
        self._pending_video_frame = video_frame
        if not self._ui_coalesce_timer.isActive():
            self._ui_coalesce_timer.start()

    def _drain_pending_remote_ui(self):
        """Drain coalesced remote updates on the main thread."""
        pending_sensors = self._pending_sensor_data
        pending_video = self._pending_video_frame
        self._pending_sensor_data = {}
        self._pending_video_frame = None
        if not pending_sensors and pending_video is None:
            self._ui_coalesce_timer.stop()
            return
        for sensor_data in pending_sensors.values():
            self._process_remote_sensor_data_ui(sensor_data)
        if pending_video is not None:
            self._process_remote_video_frame_ui(pending_video)
        if not self._pending_sensor_data and self._pending_video_frame is None:
            self._ui_coalesce_timer.stop()

    def _process_remote_sensor_data_ui(self, sensor_data):
        if self.main_window and hasattr(self.main_window, 'data_flow_controller'):
            self.main_window.data_flow_controller.record_remote_daq_data(len(str(sensor_data)))

        timestamp_ms = getattr(sensor_data, 'timestamp', None)
        self._ingest_remote_sensor(
            sensor_id=sensor_data.sensor_id,
            name=sensor_data.sensor_name,
            unit=sensor_data.unit,
            value=sensor_data.value,
            timestamp_ms=timestamp_ms,
        )

    def _process_remote_video_frame_ui(self, video_frame):
        # Record in data flow controller
        if self.main_window and hasattr(self.main_window, 'data_flow_controller'):
            self.main_window.data_flow_controller.record_remote_daq_data(len(video_frame.frame_data))

        # Convert bytes to numpy array
        import numpy as np
        import cv2
        
        expected_len = video_frame.height * video_frame.width * video_frame.channels
        if len(video_frame.frame_data) != expected_len:
            self.logger.log(
                f"Remote video frame size mismatch: got {len(video_frame.frame_data)}, expected {expected_len}",
                "ERROR"
            )
            return
        
        frame_array = np.frombuffer(video_frame.frame_data, dtype=np.uint8)
        frame = frame_array.reshape((video_frame.height, video_frame.width, video_frame.channels))
        
        # Convert to Qt format and display
        if hasattr(self.main_window, 'camera_controller'):
            self.main_window.camera_controller.display_remote_frame(frame)
    
    def add_remote_sensor_to_local(self, remote_sensor):
        """Add or update a remote sensor in the local sensor controller (main thread)."""
        self._ingest_remote_sensor(
            sensor_id=remote_sensor.id,
            name=remote_sensor.name,
            unit=remote_sensor.unit,
            value=remote_sensor.current_value,
            timestamp_ms=None,
        )

    def _find_local_remote_sensor(self, remote_id, name):
        """Find an existing local SensorModel for a remote sensor."""
        if not hasattr(self.main_window, 'sensor_controller'):
            return None
        sc = self.main_window.sensor_controller
        for sensor in sc.sensors:
            if getattr(sensor, 'is_remote', False) and getattr(sensor, 'remote_id', None) == remote_id:
                return sensor
        return sc.get_sensor_by_name(f"Remote: {name}")

    def _ingest_remote_sensor(self, sensor_id, name, unit, value, timestamp_ms=None,
                              update_table_on_create=True):
        """Create/update SensorModel and push sample into the DCC pipeline."""
        sample_ts = (timestamp_ms / 1000.0) if timestamp_ms else time.time()

        remote_sensor = RemoteSensor(
            id=sensor_id,
            name=name,
            unit=unit or "",
            current_value=value,
            interface_type="remote_stream",
            available=True,
            color="#FF6B6B",
        )
        self.remote_sensors[sensor_id] = remote_sensor

        if not hasattr(self.main_window, 'sensor_controller'):
            return

        sc = self.main_window.sensor_controller
        sensor = self._find_local_remote_sensor(sensor_id, name)
        created = False

        if sensor:
            if unit and sensor.unit != unit:
                sensor.unit = unit
        else:
            from app.models.sensor_model import SensorModel

            sensor = SensorModel(
                name=f"Remote: {name}",
                interface_type="remote_stream",
                unit=unit or "",
                color="#FF6B6B",
            )
            sensor.is_remote = True
            sensor.remote_id = sensor_id
            sc.sensors.append(sensor)
            created = True

        if value is not None:
            sensor.set_value(value)
            sensor.last_update_time = sample_ts
            self._push_remote_sample_to_dcc(sensor, value, sample_ts)

        if created and update_table_on_create:
            sc.update_sensor_table()

    def _push_remote_sample_to_dcc(self, sensor, value, sample_ts):
        """Write remote sample into combined_data and historical_buffer (mirror MQTT path)."""
        if not hasattr(self.main_window, 'data_collection_controller'):
            return

        dcc = self.main_window.data_collection_controller
        sc = self.main_window.sensor_controller
        key = sc.get_historical_buffer_key(sensor)
        if not key:
            return

        store_data = dcc.collecting_data

        with QMutexLocker(dcc.combined_data_mutex):
            dcc.combined_data[key] = value
            dcc._last_sensor_update[key] = sample_ts

            if store_data:
                with QMutexLocker(dcc.historical_buffer_mutex):
                    try:
                        dcc.historical_buffer[key].append((sample_ts, float(value)))
                    except (ValueError, TypeError):
                        pass
                if 'timestamp' not in dcc.combined_data or sample_ts > dcc.combined_data.get('timestamp', 0):
                    dcc.combined_data['timestamp'] = sample_ts
    
    def disconnect_from_stream(self, stream_name=None):
        """Disconnect from a stream (STR-R-08: empty/mismatch closes all)."""
        try:
            self.client_stop_event.set()

            # Notify master before tearing down channel
            if self.client_stub and self.client_session_id:
                try:
                    metadata = self._stream_metadata()
                    self.client_stub.DisconnectFromStream(
                        daq_service_pb2.DisconnectRequest(), timeout=3, metadata=metadata
                    )
                except Exception:
                    pass

            targets = []
            if stream_name and stream_name in self.connected_streams:
                targets = [stream_name]
            elif self.connected_streams:
                targets = list(self.connected_streams.keys())

            for name in targets:
                channel = self.connected_streams.pop(name, None)
                if channel is not None:
                    try:
                        channel.close()
                    except Exception:
                        pass

            self.is_client = False
            self.client_stub = None
            self.client_session_id = None
            self.receive_threads.clear()

            self._cleanup_remote_sensors()
            self._pending_sensor_data.clear()
            self._pending_video_frame = None
            self._ui_coalesce_timer.stop()

            disconnected_name = stream_name or self.current_stream_name or "stream"
            self.current_master_address = ""
            self.current_stream_name = ""
            self.current_stream_password = ""
            self.current_client_name = ""
            self.current_request_audio = False

            self.logger.log(f"Disconnected from stream: {disconnected_name}", "INFO")
            self.stream_disconnected.emit()
            self.status_changed.emit()

            return True, "Disconnected successfully"

        except Exception as e:
            self.logger.log(f"Failed to disconnect: {str(e)}", "ERROR")
            return False, str(e)

    def _cleanup_remote_sensors(self):
        """Remove remote sensors from local controller and clear remote registry."""
        if hasattr(self.main_window, 'sensor_controller'):
            sc = self.main_window.sensor_controller
            sc.sensors = [s for s in sc.sensors if not getattr(s, 'is_remote', False)]
            sc.update_sensor_table()
        self.remote_sensors.clear()
    
    def stop_master_streaming(self):
        """Stop master streaming"""
        try:
            if self.grpc_server:
                self.grpc_server.stop(0)
                self.grpc_server = None
            if self.grpc_executor:
                self.grpc_executor.shutdown(wait=False)
                self.grpc_executor = None
            self.service_servicer = None

            self.is_master = False
            
            # Clear current stream info
            self.current_stream_name = ""
            self.current_stream_password = ""
            self.current_stream_description = ""
            self.current_stream_options = {
                'enable_sensors': True,
                'enable_video': True,
                'enable_audio': False,
                'enable_remote_control': False
            }
            
            self.logger.log("Stopped master streaming", "INFO")
            self.stream_disconnected.emit()
            self.status_changed.emit()
            

            
            return True, "Streaming stopped successfully"
            
        except Exception as e:
            self.logger.log(f"Failed to stop streaming: {str(e)}", "ERROR")
            return False, str(e)
    
    def update_status(self):
        """Update connection status"""
        # REM-UI-01: update remote card label text
        if hasattr(self, 'remote_status_label') and self.remote_status_label:
            if self.is_master:
                self.remote_status_label.setText(f"Master: {self.current_stream_name}")
            elif self.is_client:
                self.remote_status_label.setText(f"Client: {self.current_stream_name}")
            else:
                self.remote_status_label.setText("LAN / VPN only")

        # REM-UI-03: track remote_stream interface connection
        if hasattr(self.main_window, 'interface_connections'):
            self.main_window.interface_connections['remote_stream'] = self.is_client or self.is_master

        # Update the remote DAQ button text to show status
        if hasattr(self, 'remote_container') and self.remote_container:
            if self.is_master:
                self.remote_container.setStyleSheet(CardStyles.device_card(connected=True))
            elif self.is_client:
                # Use a blue version for client mode - similar to status("info") but matching device_card layout
                base_bottom = "rgba(35, 35, 55, 0.85)"
                self.remote_container.setStyleSheet(f"""
                    QFrame {{
                        background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                            stop:0 rgba(33, 150, 243, 0.2),
                            stop:1 {base_bottom});
                        border-radius: 8px;
                        border: 2px solid {COLORS.INFO};
                    }}
                    QFrame:hover {{
                        background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                            stop:0 rgba(33, 150, 243, 0.3),
                            stop:1 rgba(45, 45, 75, 0.95));
                        border: 2px solid {COLORS.INFO_BRIGHT};
                    }}
                    QLabel {{
                        background: transparent;
                        border: none;
                    }}
                """)
            else:
                self.remote_container.setStyleSheet(CardStyles.device_card(connected=False))
        
        # Update main window status bar with prominent indicator
        if hasattr(self.main_window, 'statusBar'):
            if self.is_master:
                self.main_window.statusBar().showMessage(f"🟢 STREAMING: {self.current_stream_name} (Master Mode)")
            elif self.is_client:
                self.main_window.statusBar().showMessage(f"🔵 CONNECTED: {self.current_stream_name} (Client Mode)")
    
    def get_status(self):
        """Get current streaming status"""
        if self.is_master:
            return StatusState.ACTIVE
        elif self.is_client:
            return StatusState.ACTIVE
        else:
            return StatusState.OPTIONAL


class RemoteSensor:
    """Represents a remote sensor from a stream"""
    def __init__(self, id, name, unit, current_value, interface_type, available, color):
        self.id = id
        self.name = name
        self.unit = unit
        self.current_value = current_value
        self.interface_type = interface_type
        self.available = available
        self.color = color


# Create base class for DAQServiceServicer
if daq_service_pb2_grpc is not None:
    DAQServiceBase = daq_service_pb2_grpc.DAQServiceServicer
else:
    DAQServiceBase = object

class DAQServiceServicer(DAQServiceBase):
    """gRPC service implementation for DAQ streaming"""
    
    def __init__(self, main_window, stream_name, password,
                 enable_sensors=True, enable_video=True, enable_audio=False):
        self.main_window = main_window
        self.stream_name = stream_name
        self.password = password
        self.enable_sensors = enable_sensors
        self.enable_video = enable_video
        self.enable_audio = enable_audio
        self.connected_clients = {}
        self.logger = Logger("DAQServiceServicer")

    def _get_session_id_from_metadata(self, context):
        md = dict(context.invocation_metadata())
        return md.get('session-id') or md.get('session_id')

    def _require_session(self, context):
        """GRPC-01: abort if session-id metadata is missing or unknown."""
        session_id = self._get_session_id_from_metadata(context)
        if not session_id or session_id not in self.connected_clients:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Missing or invalid session-id")
        return session_id

    def _register_stream(self, session_id):
        if session_id in self.connected_clients:
            self.connected_clients[session_id]['active_streams'] = (
                self.connected_clients[session_id].get('active_streams', 0) + 1
            )

    def _unregister_stream(self, session_id):
        if session_id not in self.connected_clients:
            return
        count = self.connected_clients[session_id].get('active_streams', 1) - 1
        if count <= 0:
            del self.connected_clients[session_id]
            self.logger.log(f"Pruned client session: {session_id}", "INFO")
        else:
            self.connected_clients[session_id]['active_streams'] = count

    def _snapshot_sensors(self):
        """GRPC-06: thread-safe snapshot of enabled sensors."""
        if not hasattr(self.main_window, 'sensor_controller'):
            return []
        try:
            sensors = list(self.main_window.sensor_controller.sensors)
            return [
                (
                    f"{s.interface_type}_{s.name}",
                    s.name,
                    s.unit or "",
                    s.current_value,
                    s.enabled,
                    getattr(s, 'last_update_time', 0),
                    s.interface_type,
                    getattr(s, 'color', '#4CAF50'),
                )
                for s in sensors
            ]
        except Exception as e:
            self.logger.log(f"Sensor snapshot error: {e}", "WARNING")
            return []

    def ConnectToStream(self, request, context):
        """Handle client connection requests"""
        # GRPC-09: validate stream name
        if not request.stream_name or request.stream_name != self.stream_name:
            return daq_service_pb2.ConnectResponse(
                success=False,
                message="Invalid stream name"
            )
        if request.password != self.password:
            return daq_service_pb2.ConnectResponse(
                success=False,
                message="Invalid password"
            )

        client_id = f"{request.client_name}_{int(time.time())}"
        self.connected_clients[client_id] = {
            "name": request.client_name,
            "connected_at": time.time(),
            "request_sensors": request.request_sensors,
            "request_video": request.request_video,
            "request_audio": getattr(request, "request_audio", False),
            "active_streams": 0,
        }

        available_sensors = []
        for sensor_id, name, unit, value, enabled, _, iface, color in self._snapshot_sensors():
            available_sensors.append(daq_service_pb2.RemoteSensor(
                id=sensor_id,
                name=name,
                unit=unit,
                current_value=value or 0.0,
                interface_type=iface,
                available=enabled,
                color=color,
            ))

        video_available = (
            self.enable_video
            and hasattr(self.main_window, 'camera_controller')
            and self.main_window.camera_controller.any_connected()
        )
        audio_available = bool(self.enable_audio)

        return daq_service_pb2.ConnectResponse(
            success=True,
            message="Connected successfully",
            session_id=client_id,
            available_sensors=available_sensors,
            video_available=video_available,
            audio_available=audio_available
        )

    def DisconnectFromStream(self, request, context):
        """REM-01: remove client session on explicit disconnect."""
        session_id = self._get_session_id_from_metadata(context)
        if session_id and session_id in self.connected_clients:
            del self.connected_clients[session_id]
            self.logger.log(f"Client disconnected: {session_id}", "INFO")
            return daq_service_pb2.DisconnectResponse(
                success=True, message="Disconnected"
            )
        return daq_service_pb2.DisconnectResponse(
            success=False, message="Session not found"
        )

    def StreamSensorData(self, request, context):
        """Stream sensor data to clients"""
        session_id = self._require_session(context)
        if not self.enable_sensors:
            return
        self._register_stream(session_id)
        try:
            while context.is_active():
                for sensor_id, name, unit, value, enabled, last_ts, _, _ in self._snapshot_sensors():
                    if enabled and value is not None:
                        ts_ms = int(last_ts * 1000) if last_ts else int(time.time() * 1000)
                        yield daq_service_pb2.SensorData(
                            sensor_id=sensor_id,
                            value=value,
                            unit=unit,
                            timestamp=ts_ms,
                            sensor_name=name
                        )
                time.sleep(0.1)
        finally:
            self._unregister_stream(session_id)

    def StreamVideo(self, request, context):
        """Stream video data to clients"""
        session_id = self._require_session(context)
        if not self.enable_video:
            return
        self._register_stream(session_id)
        try:
            while context.is_active():
                cc = getattr(self.main_window, 'camera_controller', None)
                if cc and cc.any_connected():
                    frame = cc.get_streaming_numpy_frame()
                    if frame is not None:
                        yield daq_service_pb2.VideoFrame(
                            frame_data=frame.tobytes(),
                            timestamp=int(time.time() * 1000),
                            width=frame.shape[1],
                            height=frame.shape[0],
                            channels=frame.shape[2] if len(frame.shape) > 2 else 1
                        )
                time.sleep(0.033)
        finally:
            self._unregister_stream(session_id)

    def StreamAudio(self, request, context):
        """Stream audio data (PCM) to clients when enabled"""
        session_id = self._require_session(context)
        if not self.enable_audio:
            self.logger.log("Audio streaming requested but not enabled on server", "WARNING")
            return
        self._register_stream(session_id)
        try:
            try:
                import sounddevice as sd
            except ImportError:
                self.logger.log("sounddevice not available; cannot stream audio", "ERROR")
                return

            sample_rate = 44100
            channels = 1
            blocksize = 1024
            audio_queue = queue.Queue(maxsize=10)

            def audio_callback(indata, frames, time_info, status):
                try:
                    audio_queue.put_nowait(indata.copy())
                except queue.Full:
                    pass

            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='int16',
                blocksize=blocksize,
                callback=audio_callback
            ):
                while context.is_active():
                    try:
                        chunk = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    try:
                        yield daq_service_pb2.AudioFrame(
                            pcm_data=chunk.tobytes(),
                            timestamp=int(time.time() * 1000),
                            sample_rate=sample_rate,
                            channels=channels
                        )
                    except Exception as e:
                        self.logger.log(f"Error yielding audio chunk: {e}", "ERROR")
                        break
        except Exception as e:
            self.logger.log(f"Audio streaming error: {str(e)}", "ERROR")
        finally:
            self._unregister_stream(session_id)

    # REM-01: stub unimplemented remote-control RPCs
    def StartStreaming(self, request, context):
        self.logger.log("StartStreaming RPC not implemented", "INFO")
        return daq_service_pb2.StreamingResponse(
            success=False, message="Not implemented; use local master UI"
        )

    def StopStreaming(self, request, context):
        self.logger.log("StopStreaming RPC not implemented", "INFO")
        return daq_service_pb2.StopResponse(success=False, message="Not implemented")

    def GetStreamingStatus(self, request, context):
        self.logger.log("GetStreamingStatus RPC not implemented", "INFO")
        return daq_service_pb2.StreamingStatusResponse(is_streaming=True, stream_name=self.stream_name)

    def GetAvailableSensors(self, request, context):
        self.logger.log("GetAvailableSensors RPC not implemented", "INFO")
        return daq_service_pb2.AvailableSensorsResponse()

    def GetAvailableVideo(self, request, context):
        self.logger.log("GetAvailableVideo RPC not implemented", "INFO")
        return daq_service_pb2.AvailableVideoResponse(available=self.enable_video)

    def StreamCombinedData(self, request, context):
        self.logger.log("StreamCombinedData RPC not implemented", "INFO")
        if False:
            yield None

    def SendRemoteCommand(self, request, context):
        self.logger.log("SendRemoteCommand not implemented", "INFO")
        return daq_service_pb2.CommandResponse(
            success=False, message="Remote control not implemented"
        )

    def RequestRemoteControl(self, request, context):
        self.logger.log("RequestRemoteControl not implemented", "INFO")
        return daq_service_pb2.ControlResponse(
            granted=False, message="Remote control not implemented"
        )

    def Authenticate(self, request, context):
        self.logger.log("Authenticate RPC not implemented", "INFO")
        return daq_service_pb2.AuthResponse(
            success=False, message="Use ConnectToStream for authentication"
        )

    def ValidatePermission(self, request, context):
        self.logger.log("ValidatePermission RPC not implemented", "INFO")
        return daq_service_pb2.PermissionResponse(
            granted=False, message="Not implemented"
        )


class _ConnectWorker(QThread):
    """Background worker for non-blocking gRPC connect (GRPC-03)."""

    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, controller, master_address, stream_name, password,
                 client_name, request_sensors, request_video, request_audio):
        super().__init__()
        self._controller = controller
        self._args = (master_address, stream_name, password, client_name,
                      request_sensors, request_video, request_audio)

    def run(self):
        success, message = self._controller._connect_to_master_stream_sync(*self._args)
        self.finished_with_result.emit(success, message)


class StreamConnectionDialog(QDialog):
    """User-friendly dialog for stream connections"""
    
    def __init__(self, stream_controller):
        super().__init__()
        self.stream_controller = stream_controller
        self.setWindowTitle("Remote DAQ (gRPC over LAN)")
        self.setModal(True)
        self.resize(500, 400)
        
        # Apply dark dialog style
        from app.ui.theme import DialogStyles
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self.setup_ui()
        self.update_ui_from_stream_status()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout()
        
        # Clarify connection scope up front
        scope_label = QLabel("Remote DAQ uses gRPC for local/LAN connections. Internet access requires a secure tunnel (e.g., VPN or SSH port forward) and is not the default use case.")
        scope_label.setWordWrap(True)
        scope_label.setStyleSheet("color: #f5c542; background-color: rgba(245, 197, 66, 0.1); border: 1px solid #f5c542; border-radius: 6px; padding: 8px; font-weight: bold;")
        layout.addWidget(scope_label)
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # Master tab (start streaming)
        master_tab = self.create_master_tab()
        tab_widget.addTab(master_tab, "Start Streaming (Master)")
        
        # Client tab (connect to stream)
        client_tab = self.create_client_tab()
        tab_widget.addTab(client_tab, "Connect to Stream (Client)")
        
        # Help tab
        help_tab = self.create_help_tab()
        tab_widget.addTab(help_tab, "Help")
        
        layout.addWidget(tab_widget)
        
        # Current stream info display
        self.stream_info_group = QGroupBox("Current Stream Status")
        self.stream_info_group.setStyleSheet(GroupBoxStyles.default())
        self.stream_info_layout = QVBoxLayout()
        
        self.stream_status_label = QLabel("No active stream")
        self.stream_status_label.setStyleSheet("color: gray; font-weight: bold; padding: 5px;")
        self.stream_info_layout.addWidget(self.stream_status_label)
        
        self.stream_details_label = QLabel("")
        self.stream_details_label.setStyleSheet("color: #666; padding: 5px;")
        self.stream_details_label.setWordWrap(True)
        self.stream_info_layout.addWidget(self.stream_details_label)
        
        self.stream_info_group.setLayout(self.stream_info_layout)
        layout.addWidget(self.stream_info_group)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: gray; padding: 5px;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
    
    def create_master_tab(self):
        """Create the master streaming tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Stream settings group
        settings_group = QGroupBox("Stream Settings")
        settings_group.setStyleSheet(GroupBoxStyles.default())
        settings_layout = QFormLayout()
        
        self.stream_name_edit = QLineEdit()
        self.stream_name_edit.setPlaceholderText("My Experiment Stream")
        settings_layout.addRow("Stream Name:", self.stream_name_edit)
        
        self.stream_password_edit = QLineEdit()
        self.stream_password_edit.setPlaceholderText("Enter password for stream access")
        self.stream_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        settings_layout.addRow("Password:", self.stream_password_edit)
        
        self.stream_description_edit = QTextEdit()
        self.stream_description_edit.setMaximumHeight(60)
        self.stream_description_edit.setPlaceholderText("Describe your experiment...")
        settings_layout.addRow("Description:", self.stream_description_edit)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Options group
        options_group = QGroupBox("Stream Options")
        options_group.setStyleSheet(GroupBoxStyles.default())
        options_layout = QVBoxLayout()
        
        self.enable_sensors_check = QCheckBox("Stream Sensor Data")
        self.enable_sensors_check.setChecked(True)
        options_layout.addWidget(self.enable_sensors_check)
        
        self.enable_video_check = QCheckBox("Stream Video")
        self.enable_video_check.setChecked(True)
        options_layout.addWidget(self.enable_video_check)
        
        self.enable_audio_check = QCheckBox("Stream Audio (PCM)")
        self.enable_audio_check.setChecked(False)
        options_layout.addWidget(self.enable_audio_check)
        

        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # Start button
        self.start_stream_btn = QPushButton("Start Streaming")
        self.start_stream_btn.setStyleSheet(ButtonStyles.success("large"))
        self.start_stream_btn.clicked.connect(self.start_streaming)
        layout.addWidget(self.start_stream_btn)
        
        # Stop button
        self.stop_stream_btn = QPushButton("Stop Streaming")
        self.stop_stream_btn.setStyleSheet(ButtonStyles.danger("large"))
        self.stop_stream_btn.clicked.connect(self.stop_streaming)
        self.stop_stream_btn.setEnabled(False)
        layout.addWidget(self.stop_stream_btn)
        

        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_client_tab(self):
        """Create the client connection tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Connection settings group
        connection_group = QGroupBox("Connection Settings")
        connection_group.setStyleSheet(GroupBoxStyles.default())
        connection_layout = QFormLayout()
        
        self.master_address_edit = QLineEdit()
        self.master_address_edit.setPlaceholderText("192.168.1.100 or localhost")
        connection_layout.addRow("Master Address:", self.master_address_edit)
        
        self.client_stream_name_edit = QLineEdit()
        self.client_stream_name_edit.setPlaceholderText("Enter stream name")
        connection_layout.addRow("Stream Name:", self.client_stream_name_edit)
        
        self.client_password_edit = QLineEdit()
        self.client_password_edit.setPlaceholderText("Enter stream password")
        self.client_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        connection_layout.addRow("Password:", self.client_password_edit)
        
        self.client_name_edit = QLineEdit()
        self.client_name_edit.setPlaceholderText("Your Name")
        connection_layout.addRow("Your Name:", self.client_name_edit)
        
        connection_group.setLayout(connection_layout)
        layout.addWidget(connection_group)
        
        # Data options group
        data_group = QGroupBox("Data Options")
        data_group.setStyleSheet(GroupBoxStyles.default())
        data_layout = QVBoxLayout()
        
        self.request_sensors_check = QCheckBox("Receive Sensor Data")
        self.request_sensors_check.setChecked(True)
        data_layout.addWidget(self.request_sensors_check)
        
        self.request_video_check = QCheckBox("Receive Video Stream")
        self.request_video_check.setChecked(True)
        data_layout.addWidget(self.request_video_check)
        
        self.request_audio_check = QCheckBox("Receive Audio Stream")
        self.request_audio_check.setChecked(False)
        data_layout.addWidget(self.request_audio_check)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # Connect button
        self.connect_btn = QPushButton("Connect to Stream")
        self.connect_btn.setStyleSheet(ButtonStyles.info("large"))
        self.connect_btn.clicked.connect(self.connect_to_stream)
        layout.addWidget(self.connect_btn)
        
        # Disconnect button
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setStyleSheet(ButtonStyles.warning("large"))
        self.disconnect_btn.clicked.connect(self.disconnect_from_stream)
        self.disconnect_btn.setEnabled(False)
        layout.addWidget(self.disconnect_btn)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_help_tab(self):
        """Create the help tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml("""
        <h2>Remote DAQ Connection Help</h2>
        <p><b>Network scope:</b> Remote DAQ runs over gRPC and is designed for local networks (LAN/VPN). Direct internet use is not typical — if required, place the connection inside a secure tunnel such as VPN or SSH port forwarding.</p>
        
        <h3>Master Mode (Start Streaming)</h3>
        <p><b>Purpose:</b> Share your DAQ data and video with others in real-time.</p>
        <ul>
            <li><b>Stream Name:</b> Choose a descriptive name for your experiment (e.g., "Temperature Study Lab 3")</li>
            <li><b>Password:</b> Protect your stream with a strong password</li>
            <li><b>Description:</b> Explain what you're measuring and any important details</li>
            <li><b>Stream Options:</b> Choose what to share (sensors, video, audio)</li>
            <li><b>Network:</b> Run on a local/VPN address (e.g., 192.168.x.x or 10.x.x.x). For internet access, configure a VPN or SSH tunnel first.</li>
        </ul>
        
        <h4>Master Mode Capabilities:</h4>
        <ul>
            <li><b>Real-time Sensor Data:</b> Stream live readings from all connected sensors (Arduino, LabJack, NDI, etc.)</li>
            <li><b>Live Video Feed:</b> Share camera feed with overlays, motion detection, and recording status</li>
            <li><b>Audio Streaming:</b> Stream audio (PCM format) from your system's microphone or audio input to connected clients</li>
            <li><b>Multi-client Support:</b> Multiple people can connect to your stream simultaneously</li>
            <li><b>Secure Access:</b> Password protection for stream access</li>
        </ul>
        
        <h3>Client Mode (Connect to Stream)</h3>
        <p><b>Purpose:</b> View and analyze data from someone else's experiment remotely.</p>
        <ul>
            <li><b>Master Address:</b> IP address of the computer running the stream (e.g., 192.168.1.100 or localhost)</li>
            <li><b>Stream Name:</b> Name of the stream you want to connect to</li>
            <li><b>Password:</b> Password provided by the stream owner</li>
            <li><b>Your Name:</b> Your name (will be shown to the stream owner for identification)</li>
            <li><b>Connectivity:</b> Connect on the same LAN/VPN. If you must connect over the internet, first establish a secure tunnel (VPN/SSH) to the remote network.</li>
        </ul>
        
        <h4>Client Mode Capabilities:</h4>
        <ul>
            <li><b>Live Data Monitoring:</b> View real-time sensor readings in tables and graphs</li>
            <li><b>Video Observation:</b> Watch live video feed from the experiment</li>
            <li><b>Audio Reception:</b> Receive and play back audio stream from the master system (requires sounddevice package)</li>
            <li><b>Data Analysis:</b> Use all local analysis tools on remote sensor data</li>
            <li><b>Remote Sensors:</b> Remote sensors appear in red in the sensor list for easy identification</li>
            <li><b>Multi-stream Support:</b> Connect to multiple experiments simultaneously</li>
        </ul>
        
        <h3>Security Features</h3>
        <ul>
            <li><b>Password Protection:</b> All streams require authentication</li>
            <li><b>View-only Access:</b> Clients can only view data, ensuring experiment safety</li>
            <li><b>Connection Logging:</b> Master can see who is connected to their stream</li>
            <li><b>Network Security:</b> Designed for trusted LAN/VPN use. For internet access, place the connection behind VPN/SSH tunnels and follow your firewall policies.</li>
        </ul>
        
        
        <h3>Tips for Best Performance</h3>
        <ul>
            <li><b>Network:</b> Use wired connections for better stability and bandwidth</li>
            <li><b>Stream Names:</b> Use descriptive, unique names for easy identification</li>
            <li><b>Passwords:</b> Use strong passwords and share them securely</li>
            <li><b>Testing:</b> Test connections on local network before going remote</li>
            <li><b>Video Quality:</b> Adjust camera settings for optimal streaming performance</li>
            <li><b>Sensor Selection:</b> Only stream sensors that are actively being used</li>
        </ul>
        
        <h3>Troubleshooting</h3>
        <ul>
            <li><b>Connection Failed:</b> Check IP address, firewall settings, and network connectivity</li>
            <li><b>No Data Received:</b> Verify stream is running, password is correct, and sensors are active</li>
            <li><b>Slow Performance:</b> Reduce video quality, disable video streaming, or check network bandwidth</li>
            <li><b>Video Issues:</b> Ensure camera is connected and working on master system</li>
            <li><b>Audio Issues:</b> Verify sounddevice package is installed, check audio input device is available, and ensure audio streaming is enabled in stream options</li>
            <li><b>Sensor Data Missing:</b> Check if sensors are connected and streaming is enabled for those sensors</li>
        </ul>
        
        <h3>Technical Details</h3>
        <ul>
            <li><b>Protocol:</b> Uses gRPC for efficient, bidirectional communication</li>
            <li><b>Data Format:</b> Sensor data transmitted as structured messages with timestamps</li>
            <li><b>Video Format:</b> Raw video frames transmitted for minimal latency</li>
            <li><b>Audio Format:</b> PCM audio data streamed in real-time (default: 44100 Hz sample rate, mono/stereo)</li>
            <li><b>Audio Requirements:</b> Master requires sounddevice package for audio capture; Client requires sounddevice for audio playback</li>
            <li><b>Port:</b> Default gRPC port 50051 (configurable)</li>
            <li><b>Compatibility:</b> Works with any DAQ system using the same protocol</li>
        </ul>
        """)
        
        layout.addWidget(help_text)
        widget.setLayout(layout)
        return widget
    
    def start_streaming(self):
        """Start streaming as master"""
        stream_name = self.stream_name_edit.text().strip()
        password = self.stream_password_edit.text().strip()
        description = self.stream_description_edit.toPlainText().strip()
        
        if not stream_name:
            QMessageBox.warning(self, "Error", "Please enter a stream name")
            return
        
        if not password:
            QMessageBox.warning(self, "Error", "Please enter a password")
            return
        
        self.status_label.setText("Starting stream...")
        self.start_stream_btn.setEnabled(False)
        
        success, message = self.stream_controller.start_master_streaming(
            stream_name=stream_name,
            password=password,
            description=description,
            enable_sensors=self.enable_sensors_check.isChecked(),
            enable_video=self.enable_video_check.isChecked(),
            enable_audio=self.enable_audio_check.isChecked()
        )
        
        if success:
            self.status_label.setText(f"Streaming: {stream_name}")
            self.update_ui_from_stream_status()
            QMessageBox.information(self, "Success", f"Streaming started: {message}")
        else:
            self.status_label.setText("Failed to start stream")
            self.start_stream_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Failed to start streaming: {message}")
    
    def stop_streaming(self):
        """Stop streaming"""
        success, message = self.stream_controller.stop_master_streaming()
        
        if success:
            self.status_label.setText("Streaming stopped")
            self.update_ui_from_stream_status()
            QMessageBox.information(self, "Success", "Streaming stopped")
        else:
            QMessageBox.critical(self, "Error", f"Failed to stop streaming: {message}")
    
    def connect_to_stream(self):
        """Connect to a master stream"""
        master_address = self.master_address_edit.text().strip()
        stream_name = self.client_stream_name_edit.text().strip()
        password = self.client_password_edit.text().strip()
        client_name = self.client_name_edit.text().strip()
        
        if not master_address:
            QMessageBox.warning(self, "Error", "Please enter master address")
            return
        
        if not stream_name:
            QMessageBox.warning(self, "Error", "Please enter stream name")
            return
        
        if not password:
            QMessageBox.warning(self, "Error", "Please enter password")
            return
        
        if not client_name:
            client_name = "Anonymous"
        
        self.status_label.setText("Connecting...")
        self.connect_btn.setEnabled(False)

        self._connect_params = (
            master_address, stream_name, password, client_name,
            self.request_sensors_check.isChecked(),
            self.request_video_check.isChecked(),
            self.request_audio_check.isChecked(),
        )
        self.stream_controller.connect_finished.connect(self._on_connect_finished)
        if not self.stream_controller.begin_connect_to_master_stream(*self._connect_params):
            self.stream_controller.connect_finished.disconnect(self._on_connect_finished)
            self.status_label.setText("Connection already in progress")
            self.connect_btn.setEnabled(True)

    def _on_connect_finished(self, success, message):
        try:
            self.stream_controller.connect_finished.disconnect(self._on_connect_finished)
        except TypeError:
            pass
        stream_name = self._connect_params[1]
        if success:
            self.status_label.setText(f"Connected to: {stream_name}")
            self.update_ui_from_stream_status()
            QMessageBox.information(self, "Success", f"Connected: {message}")
        else:
            self.status_label.setText("Connection failed")
            self.connect_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Connection failed: {message}")
    
    def update_ui_from_stream_status(self):
        """Update UI elements based on current stream status"""
        # Get current stream info from controller
        controller = self.stream_controller
        
        # Check if we're streaming as master
        if controller.is_master:
            self.stream_status_label.setText("🟢 Streaming as Master")
            self.stream_status_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
            
            # Show stream details
            details = f"Stream: {controller.current_stream_name}\n"
            details += f"Password: {'*' * len(controller.current_stream_password)}\n"
            if controller.current_stream_description:
                details += f"Description: {controller.current_stream_description}\n"
            
            # Add options info
            options = controller.current_stream_options
            details += f"Sensors: {'✓' if options['enable_sensors'] else '✗'}, "
            details += f"Video: {'✓' if options['enable_video'] else '✗'}, "
            details += f"Audio: {'✓' if options.get('enable_audio', False) else '✗'}"
            
            self.stream_details_label.setText(details)
            
            # Update master tab buttons
            self.start_stream_btn.setEnabled(False)
            self.stop_stream_btn.setEnabled(True)
            
            # Pre-fill master tab fields (but allow editing)
            self.stream_name_edit.setText(controller.current_stream_name)
            self.stream_password_edit.setText(controller.current_stream_password)
            self.stream_description_edit.setPlainText(controller.current_stream_description)
            
            # Set checkboxes
            self.enable_sensors_check.setChecked(controller.current_stream_options['enable_sensors'])
            self.enable_video_check.setChecked(controller.current_stream_options['enable_video'])
            self.enable_audio_check.setChecked(controller.current_stream_options.get('enable_audio', False))
            
        # Check if we're connected as client
        elif controller.is_client:
            self.stream_status_label.setText("🔵 Connected as Client")
            self.stream_status_label.setStyleSheet("color: blue; font-weight: bold; padding: 5px;")
            
            # Show connection details
            details = f"Connected to: {controller.current_master_address}\n"
            details += f"Stream: {controller.current_stream_name}\n"
            details += f"Name: {controller.current_client_name}\n"
            details += f"Audio: {'Requested' if controller.current_request_audio else 'Not requested'}"
            
            self.stream_details_label.setText(details)
            
            # Update client tab buttons
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            
            # Pre-fill client tab fields
            self.master_address_edit.setText(controller.current_master_address)
            self.client_stream_name_edit.setText(controller.current_stream_name)
            self.client_password_edit.setText(controller.current_stream_password)
            self.client_name_edit.setText(controller.current_client_name)
            self.request_audio_check.setChecked(controller.current_request_audio)
            
        else:
            self.stream_status_label.setText("⚪ No active stream")
            self.stream_status_label.setStyleSheet("color: gray; font-weight: bold; padding: 5px;")
            self.stream_details_label.setText("")
            
            # Reset all buttons
            self.start_stream_btn.setEnabled(True)
            self.stop_stream_btn.setEnabled(False)
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
    
    def disconnect_from_stream(self):
        """Disconnect from stream (STR-R-08: use controller state, not text field)."""
        controller = self.stream_controller
        stream_name = controller.current_stream_name or None

        success, message = controller.disconnect_from_stream(stream_name)
        
        if success:
            self.status_label.setText("Disconnected")
            self.update_ui_from_stream_status()
            QMessageBox.information(self, "Success", "Disconnected from stream")
        else:
            QMessageBox.critical(self, "Error", f"Failed to disconnect: {message}") 