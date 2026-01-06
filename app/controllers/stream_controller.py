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
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread
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
        self.grpc_thread = None
        self.client_stub = None
        
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
            self.is_master = True
            
            # Start gRPC server
            self.start_grpc_server(stream_name, password, description,
                                 enable_sensors, enable_video, enable_audio)
            
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
            self.logger.log(f"Failed to start streaming: {str(e)}", "ERROR")
            self.error_occurred.emit(f"Failed to start streaming: {str(e)}")
            return False, str(e)
    
    def connect_to_master_stream(self, master_address, stream_name, password, 
                               client_name, request_sensors=True, request_video=True,
                               request_audio=False):
        """Connect as client to a master stream"""
        try:
            self.is_client = True
            
            # Create gRPC channel
            channel = grpc.insecure_channel(f"{master_address}:50051")
            self.client_stub = daq_service_pb2_grpc.DAQServiceStub(channel)
            
            # Connect to stream
            request = daq_service_pb2.ConnectRequest(
                master_address=master_address,
                stream_name=stream_name,
                password=password,
                request_sensors=request_sensors,
                request_video=request_video,
                client_name=client_name,
                request_audio=request_audio
            )
            
            response = self.client_stub.ConnectToStream(request)
            
            if response.success:
                self.connected_streams[stream_name] = channel
                # Store current connection info
                self.current_master_address = master_address
                self.current_stream_name = stream_name
                self.current_stream_password = password
                self.current_client_name = client_name
                self.current_request_audio = request_audio
                
                self.logger.log(f"Connected to stream: {stream_name}", "INFO")
                self.stream_connected.emit(stream_name)
                self.status_changed.emit()
                

                
                # Start receiving data
                if request_sensors:
                    self.start_sensor_streaming(stream_name)
                if request_video:
                    self.start_video_streaming(stream_name)
                if request_audio:
                    self.start_audio_streaming(stream_name)
                
                return True, "Connected successfully"
            else:
                return False, response.message
                
        except Exception as e:
            self.logger.log(f"Failed to connect to stream: {str(e)}", "ERROR")
            self.error_occurred.emit(f"Connection failed: {str(e)}")
            return False, str(e)
    
    def start_grpc_server(self, stream_name, password, description,
                         enable_sensors, enable_video, enable_audio):
        """Start gRPC server for streaming"""
        if daq_service_pb2_grpc is None:
            raise ImportError("gRPC protobuf files not available")
        
        # Create server
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        
        # Add service
        service_servicer = DAQServiceServicer(self.main_window, stream_name, password, enable_audio=enable_audio)
        daq_service_pb2_grpc.add_DAQServiceServicer_to_server(service_servicer, self.grpc_server)
        
        # Start server
        port = 50051
        self.grpc_server.add_insecure_port(f'[::]:{port}')
        self.grpc_server.start()
        
        self.logger.log(f"gRPC server started on port {port}", "INFO")
    
    def start_sensor_streaming(self, stream_name):
        """Start receiving sensor data from stream"""
        if not self.client_stub:
            return
        
        def receive_sensor_data():
            try:
                request = daq_service_pb2.StreamRequest()
                for sensor_data in self.client_stub.StreamSensorData(request):
                    # Process received sensor data
                    self.process_remote_sensor_data(sensor_data)
            except Exception as e:
                self.logger.log(f"Sensor streaming error: {str(e)}", "ERROR")
        
        # Start in separate thread
        sensor_thread = threading.Thread(target=receive_sensor_data, daemon=True)
        sensor_thread.start()
    
    def start_video_streaming(self, stream_name):
        """Start receiving video data from stream"""
        if not self.client_stub:
            return
        
        def receive_video_data():
            try:
                request = daq_service_pb2.VideoRequest()
                for video_frame in self.client_stub.StreamVideo(request):
                    # Process received video frame
                    self.process_remote_video_frame(video_frame)
            except Exception as e:
                self.logger.log(f"Video streaming error: {str(e)}", "ERROR")
        
        # Start in separate thread
        video_thread = threading.Thread(target=receive_video_data, daemon=True)
        video_thread.start()

    def start_audio_streaming(self, stream_name):
        """Start receiving audio data from stream and play back locally"""
        if not self.client_stub:
            return
        
        def receive_audio_data():
            try:
                try:
                    import sounddevice as sd
                except ImportError:
                    self.logger.log("Audio streaming requires 'sounddevice' package", "ERROR")
                    return
                
                audio_request = daq_service_pb2.AudioRequest()
                output_stream = None
                
                for audio_frame in self.client_stub.StreamAudio(audio_request):
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
                self.logger.log(f"Audio streaming error: {str(e)}", "ERROR")
            
            finally:
                try:
                    if 'output_stream' in locals() and output_stream:
                        output_stream.stop()
                        output_stream.close()
                except Exception:
                    pass
        
        audio_thread = threading.Thread(target=receive_audio_data, daemon=True)
        audio_thread.start()
    
    def process_remote_sensor_data(self, sensor_data):
        """Process received sensor data and add to local sensors"""
        # Record in data flow controller
        if self.main_window and hasattr(self.main_window, 'data_flow_controller'):
            self.main_window.data_flow_controller.record_remote_daq_data(len(str(sensor_data)))

        # Create or update remote sensor
        remote_sensor = RemoteSensor(
            id=sensor_data.sensor_id,
            name=sensor_data.sensor_name,
            unit=sensor_data.unit,
            current_value=sensor_data.value,
            interface_type="remote_stream",
            available=True,
            color="#FF6B6B"  # Red for remote sensors
        )
        
        self.remote_sensors[sensor_data.sensor_id] = remote_sensor
        
        # Add to local sensor controller if not already present
        if hasattr(self.main_window, 'sensor_controller'):
            self.add_remote_sensor_to_local(remote_sensor)
    
    def process_remote_video_frame(self, video_frame):
        """Process received video frame"""
        # Record in data flow controller
        if self.main_window and hasattr(self.main_window, 'data_flow_controller'):
            self.main_window.data_flow_controller.record_remote_daq_data(len(video_frame.frame_data))

        # Convert bytes to numpy array
        import numpy as np
        import cv2
        
        frame_array = np.frombuffer(video_frame.frame_data, dtype=np.uint8)
        frame = frame_array.reshape((video_frame.height, video_frame.width, video_frame.channels))
        
        # Convert to Qt format and display
        if hasattr(self.main_window, 'camera_controller'):
            self.main_window.camera_controller.display_remote_frame(frame)
    
    def add_remote_sensor_to_local(self, remote_sensor):
        """Add remote sensor to local sensor controller"""
        if not hasattr(self.main_window, 'sensor_controller'):
            return
        
        # Check if sensor already exists
        existing_sensor = self.main_window.sensor_controller.get_sensor_by_name(
            f"Remote: {remote_sensor.name}"
        )
        
        if not existing_sensor:
            # Create new sensor
            from app.models.sensor_model import SensorModel
            
            sensor = SensorModel(
                name=f"Remote: {remote_sensor.name}",
                interface_type="remote_stream",
                unit=remote_sensor.unit,
                color=remote_sensor.color
            )
            sensor.is_remote = True
            sensor.remote_id = remote_sensor.id
            
            self.main_window.sensor_controller.sensors.append(sensor)
            self.main_window.sensor_controller.update_sensor_table()
    
    def disconnect_from_stream(self, stream_name):
        """Disconnect from a stream"""
        try:
            if stream_name in self.connected_streams:
                channel = self.connected_streams[stream_name]
                channel.close()
                del self.connected_streams[stream_name]
            
            self.is_client = False
            self.client_stub = None
            
            # Clear current connection info
            self.current_master_address = ""
            self.current_stream_name = ""
            self.current_stream_password = ""
            self.current_client_name = ""
            self.current_request_audio = False
            
            self.logger.log(f"Disconnected from stream: {stream_name}", "INFO")
            self.stream_disconnected.emit()
            self.status_changed.emit()
            

            
            return True, "Disconnected successfully"
            
        except Exception as e:
            self.logger.log(f"Failed to disconnect: {str(e)}", "ERROR")
            return False, str(e)
    
    def stop_master_streaming(self):
        """Stop master streaming"""
        try:
            if self.grpc_server:
                self.grpc_server.stop(0)
                self.grpc_server = None
            
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
            else:
                # Only clear if we're not streaming (don't override other status messages)
                if not self.is_master and not self.is_client:
                    self.main_window.statusBar().showMessage("Ready")
    
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
    
    def __init__(self, main_window, stream_name, password, enable_audio=False):
        self.main_window = main_window
        self.stream_name = stream_name
        self.password = password
        self.connected_clients = {}
        self.logger = Logger("DAQServiceServicer")
        self.enable_audio = enable_audio
    
    def ConnectToStream(self, request, context):
        """Handle client connection requests"""
        if request.password != self.password:
            return daq_service_pb2.ConnectResponse(
                success=False,
                message="Invalid password"
            )
        
        # Add client to connected list
        client_id = f"{request.client_name}_{int(time.time())}"
        self.connected_clients[client_id] = {
            "name": request.client_name,
            "connected_at": time.time(),
            "request_sensors": request.request_sensors,
            "request_video": request.request_video,
            "request_audio": getattr(request, "request_audio", False)
        }
        
        # Get available sensors
        available_sensors = []
        if hasattr(self.main_window, 'sensor_controller'):
            for sensor in self.main_window.sensor_controller.sensors:
                # Create a unique ID for the sensor
                sensor_id = f"{sensor.interface_type}_{sensor.name}"
                available_sensors.append(daq_service_pb2.RemoteSensor(
                    id=sensor_id,
                    name=sensor.name,
                    unit=sensor.unit or "",
                    current_value=sensor.current_value or 0.0,
                    interface_type=sensor.interface_type,
                    available=sensor.enabled,
                    color=sensor.color
                ))
        
        # Check if video/audio are available
        video_available = hasattr(self.main_window, 'camera_controller') and \
                         self.main_window.camera_controller.is_connected
        audio_available = bool(self.enable_audio)
        
        return daq_service_pb2.ConnectResponse(
            success=True,
            message="Connected successfully",
            session_id=client_id,
            available_sensors=available_sensors,
            video_available=video_available,
            audio_available=audio_available
        )
    
    def StreamSensorData(self, request, context):
        """Stream sensor data to clients"""
        while context.is_active():
            if hasattr(self.main_window, 'sensor_controller'):
                for sensor in self.main_window.sensor_controller.sensors:
                    if sensor.enabled and sensor.current_value is not None:
                        # Create a unique ID for the sensor
                        sensor_id = f"{sensor.interface_type}_{sensor.name}"
                        yield daq_service_pb2.SensorData(
                            sensor_id=sensor_id,
                            value=sensor.current_value,
                            unit=sensor.unit or "",
                            timestamp=int(time.time() * 1000),
                            sensor_name=sensor.name
                        )
            time.sleep(0.1)  # 10 FPS
    
    def StreamVideo(self, request, context):
        """Stream video data to clients"""
        while context.is_active():
            if hasattr(self.main_window, 'camera_controller') and \
               self.main_window.camera_controller.is_connected:
                
                # Get current frame from camera
                frame = self.main_window.camera_controller.get_current_frame()
                if frame is not None:
                    yield daq_service_pb2.VideoFrame(
                        frame_data=frame.tobytes(),
                        timestamp=int(time.time() * 1000),
                        width=frame.shape[1],
                        height=frame.shape[0],
                        channels=frame.shape[2] if len(frame.shape) > 2 else 1
                    )
            time.sleep(0.033)  # ~30 FPS

    def StreamAudio(self, request, context):
        """Stream audio data (PCM) to clients when enabled"""
        if not self.enable_audio:
            self.logger.log("Audio streaming requested but not enabled on server", "WARNING")
            return
        
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
                    # Ensure we push a copy (int16) to the queue
                    audio_queue.put_nowait(indata.copy())
                except queue.Full:
                    # Drop if clients cannot keep up
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
        
        success, message = self.stream_controller.connect_to_master_stream(
            master_address=master_address,
            stream_name=stream_name,
            password=password,
            client_name=client_name,
            request_sensors=self.request_sensors_check.isChecked(),
            request_video=self.request_video_check.isChecked(),
            request_audio=self.request_audio_check.isChecked()
        )
        
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
        """Disconnect from stream"""
        # Get current stream name (simplified)
        stream_name = self.client_stream_name_edit.text().strip()
        
        success, message = self.stream_controller.disconnect_from_stream(stream_name)
        
        if success:
            self.status_label.setText("Disconnected")
            self.update_ui_from_stream_status()
            QMessageBox.information(self, "Success", "Disconnected from stream")
        else:
            QMessageBox.critical(self, "Error", f"Failed to disconnect: {message}") 