"""
Hardware Diagnostics Tool

Diagnostics and monitoring for connected hardware:
- Connection status and tests
- Data rate monitoring
- Serial console/monitor
- Hardware information display
- Latency measurement
"""

import time
import serial.tools.list_ports
from datetime import datetime
from typing import Dict, Optional
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QGroupBox, QTableWidget, QTableWidgetItem,
    QFrame, QHeaderView, QTextEdit, QSplitter, QProgressBar,
    QComboBox, QLineEdit, QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QColor, QTextCursor

import pyqtgraph as pg

from app.ui.theme import ButtonStyles, CardStyles, GraphStyles


class DeviceStatusCard(QFrame):
    """Card showing status of a connected device"""
    
    def __init__(self, device_name: str, device_type: str, icon: str = "🔌", parent=None):
        super().__init__(parent)
        self.device_name = device_name
        self.device_type = device_type
        self.icon = icon
        self._is_connected = False
        
        self.setMinimumSize(200, 150)
        self.setMaximumWidth(250)
        self._setup_ui()
        self._update_style()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        
        # Header
        header_layout = QHBoxLayout()
        
        self.icon_label = QLabel(self.icon)
        self.icon_label.setFont(QFont("Segoe UI Emoji", 20))
        header_layout.addWidget(self.icon_label)
        
        title_layout = QVBoxLayout()
        self.name_label = QLabel(self.device_name)
        self.name_label.setStyleSheet("color: #fff; font-weight: bold; font-size: 13px;")
        title_layout.addWidget(self.name_label)
        
        self.type_label = QLabel(self.device_type)
        self.type_label.setStyleSheet("color: #888; font-size: 10px;")
        title_layout.addWidget(self.type_label)
        header_layout.addLayout(title_layout)
        
        header_layout.addStretch()
        
        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont("Segoe UI", 16))
        self.status_indicator.setStyleSheet("color: #666;")
        header_layout.addWidget(self.status_indicator)
        
        layout.addLayout(header_layout)
        
        # Info grid
        self.info_layout = QGridLayout()
        self.info_layout.setSpacing(3)
        self.info_labels = {}
        layout.addLayout(self.info_layout)
        
        layout.addStretch()
        
        # Test button
        self.test_btn = QPushButton("🔍 Test Connection")
        self.test_btn.setStyleSheet(ButtonStyles.info("small"))
        layout.addWidget(self.test_btn)
    
    def add_info_row(self, key: str, label: str, value: str = "--"):
        """Add an info row to the card"""
        row = len(self.info_labels)
        
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 10px;")
        self.info_layout.addWidget(lbl, row, 0)
        
        val = QLabel(value)
        val.setStyleSheet("color: #fff; font-size: 10px; font-weight: bold;")
        self.info_layout.addWidget(val, row, 1)
        
        self.info_labels[key] = val
    
    def update_info(self, key: str, value: str):
        """Update an info value"""
        if key in self.info_labels:
            self.info_labels[key].setText(value)
    
    def set_connected(self, connected: bool):
        """Set connection status"""
        self._is_connected = connected
        self._update_style()
    
    def _update_style(self):
        """Update card style based on connection status"""
        if self._is_connected:
            self.setStyleSheet(CardStyles.device_card(connected=True))
            self.status_indicator.setStyleSheet("color: #4CAF50;")
        else:
            self.setStyleSheet(CardStyles.device_card(connected=False))
            self.status_indicator.setStyleSheet("color: #666;")


class SerialMonitor(QFrame):
    """Serial console/monitor widget"""
    
    line_received = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        self._setup_ui()
        
        self.max_lines = 1000
        self.auto_scroll = True
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("📟 Serial Monitor")
        title.setStyleSheet("color: #03A9F4; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Auto-scroll checkbox
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        self.auto_scroll_cb.setStyleSheet("color: #888;")
        self.auto_scroll_cb.stateChanged.connect(lambda s: setattr(self, 'auto_scroll', s == Qt.CheckState.Checked.value))
        header_layout.addWidget(self.auto_scroll_cb)
        
        # Clear button
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.setStyleSheet(ButtonStyles.secondary("small"))
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)
        
        layout.addLayout(header_layout)
        
        # Console output
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d1a;
                color: #0f0;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.console)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Send command...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #222;
                color: #fff;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        self.input_field.returnPressed.connect(self._send_command)
        input_layout.addWidget(self.input_field)
        
        send_btn = QPushButton("📤 Send")
        send_btn.setStyleSheet(ButtonStyles.success("small"))
        send_btn.clicked.connect(self._send_command)
        input_layout.addWidget(send_btn)
        
        layout.addLayout(input_layout)
    
    def append_line(self, text: str, color: str = "#0f0"):
        """Append a line to the console"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = f'<span style="color: #666;">[{timestamp}]</span> <span style="color: {color};">{text}</span>'
        self.console.append(html)
        
        if self.auto_scroll:
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.console.setTextCursor(cursor)
    
    def append_sent(self, text: str):
        """Append a sent command"""
        self.append_line(f"→ {text}", "#FFC107")
    
    def append_received(self, text: str):
        """Append received data"""
        self.append_line(f"← {text}", "#4CAF50")
    
    def append_error(self, text: str):
        """Append error message"""
        self.append_line(f"✖ {text}", "#F44336")
    
    def append_info(self, text: str):
        """Append info message"""
        self.append_line(f"ℹ {text}", "#03A9F4")
    
    def clear(self):
        """Clear the console"""
        self.console.clear()
    
    def _send_command(self):
        """Send command from input field"""
        text = self.input_field.text().strip()
        if text:
            self.append_sent(text)
            self.line_received.emit(text)
            self.input_field.clear()


class DiagnosticsTool(QWidget):
    """Hardware Diagnostics Tool"""
    
    # Signal for thread-safe port list updates
    ports_scanned = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.sensor_controller = None
        
        # Device cards
        self.device_cards: Dict[str, DeviceStatusCard] = {}
        
        # Data rate tracking
        self.data_rate_history = deque(maxlen=60)  # Last 60 seconds
        self.last_sample_counts = {}
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_diagnostics)
        self.update_timer.setInterval(1000)
        
        self._setup_ui()
        
        # Connect signal for thread-safe updates
        self.ports_scanned.connect(self._do_update_ports_table)
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
        if hasattr(main_window, 'sensor_controller'):
            self.sensor_controller = main_window.sensor_controller
        self._populate_devices()
        self._scan_serial_ports()
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("🔌 Hardware Diagnostics")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #FF9800;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Scan ports button
        self.scan_btn = QPushButton("🔍 Scan Ports")
        self.scan_btn.setStyleSheet(ButtonStyles.info("small"))
        self.scan_btn.clicked.connect(self._scan_serial_ports)
        header_layout.addWidget(self.scan_btn)
        
        # Start monitoring button
        self.monitor_btn = QPushButton("▶ Start Monitoring")
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setStyleSheet(ButtonStyles.toggle("small"))
        self.monitor_btn.clicked.connect(self._toggle_monitoring)
        header_layout.addWidget(self.monitor_btn)
        
        main_layout.addLayout(header_layout)
        
        # Main splitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # === Top Section: Device Cards ===
        devices_frame = QFrame()
        devices_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        devices_layout = QVBoxLayout(devices_frame)
        devices_layout.setContentsMargins(10, 10, 10, 10)
        
        devices_title = QLabel("📡 Connected Devices")
        devices_title.setStyleSheet("color: #888; font-weight: bold;")
        devices_layout.addWidget(devices_title)
        
        self.devices_container = QHBoxLayout()
        self.devices_container.setSpacing(10)
        self.devices_container.addStretch()
        devices_layout.addLayout(self.devices_container)
        
        splitter.addWidget(devices_frame)
        
        # === Middle Section: Serial Ports & Data Rate ===
        middle_widget = QWidget()
        middle_layout = QHBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(10)
        
        # Serial Ports Table
        ports_frame = QFrame()
        ports_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        ports_layout = QVBoxLayout(ports_frame)
        ports_layout.setContentsMargins(10, 10, 10, 10)
        
        ports_title = QLabel("🔌 Available Serial Ports")
        ports_title.setStyleSheet("color: #888; font-weight: bold;")
        ports_layout.addWidget(ports_title)
        
        self.ports_table = QTableWidget()
        self.ports_table.setColumnCount(4)
        self.ports_table.setHorizontalHeaderLabels(["Port", "Description", "VID:PID", "Status"])
        self.ports_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ports_table.setStyleSheet("""
            QTableWidget {
                background-color: #222;
                color: #ddd;
                gridline-color: #444;
                border: none;
            }
            QHeaderView::section {
                background-color: #333;
                color: #fff;
                padding: 5px;
                border: 1px solid #444;
            }
        """)
        ports_layout.addWidget(self.ports_table)
        middle_layout.addWidget(ports_frame, stretch=1)
        
        # Data Rate Graph
        rate_frame = QFrame()
        rate_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border-radius: 8px; }")
        rate_layout = QVBoxLayout(rate_frame)
        rate_layout.setContentsMargins(10, 10, 10, 10)
        
        rate_title = QLabel("📊 Data Rate (samples/sec)")
        rate_title.setStyleSheet("color: #888; font-weight: bold;")
        rate_layout.addWidget(rate_title)
        
        self.rate_plot = pg.PlotWidget()
        GraphStyles.apply_realtime_theme(self.rate_plot)
        self.rate_plot.setLabel('bottom', 'Time', 's')
        self.rate_plot.setLabel('left', 'Samples/s')
        self.rate_plot.setYRange(0, 100)
        rate_layout.addWidget(self.rate_plot)
        
        # Current rate display
        rate_info_layout = QHBoxLayout()
        rate_info_layout.addWidget(QLabel("Current Rate:"))
        self.current_rate_label = QLabel("-- samples/s")
        self.current_rate_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        rate_info_layout.addWidget(self.current_rate_label)
        rate_info_layout.addStretch()
        
        rate_info_layout.addWidget(QLabel("Peak:"))
        self.peak_rate_label = QLabel("--")
        self.peak_rate_label.setStyleSheet("color: #FFC107; font-weight: bold;")
        rate_info_layout.addWidget(self.peak_rate_label)
        
        rate_info_layout.addWidget(QLabel("Avg:"))
        self.avg_rate_label = QLabel("--")
        self.avg_rate_label.setStyleSheet("color: #03A9F4; font-weight: bold;")
        rate_info_layout.addWidget(self.avg_rate_label)
        
        rate_layout.addLayout(rate_info_layout)
        middle_layout.addWidget(rate_frame, stretch=1)
        
        splitter.addWidget(middle_widget)
        
        # === Bottom Section: Serial Monitor ===
        self.serial_monitor = SerialMonitor()
        self.serial_monitor.line_received.connect(self._on_command_sent)
        splitter.addWidget(self.serial_monitor)
        
        # Set splitter sizes
        splitter.setSizes([150, 200, 200])
        main_layout.addWidget(splitter)
    
    def _populate_devices(self):
        """Populate device cards based on connected hardware. Reuses existing cards if possible."""
        # Check if cards already exist to avoid unnecessary widget churn
        if not self.device_cards:
            # Arduino card
            arduino_card = DeviceStatusCard("Arduino", "Serial Device", "🔌")
            arduino_card.add_info_row("port", "Port:", "--")
            arduino_card.add_info_row("baud", "Baud Rate:", "--")
            arduino_card.add_info_row("sensors", "Sensors:", "0")
            arduino_card.add_info_row("rate", "Data Rate:", "0 Hz")
            arduino_card.test_btn.clicked.connect(lambda: self._test_device("arduino"))
            self.devices_container.insertWidget(0, arduino_card)
            self.device_cards["arduino"] = arduino_card
            
            # LabJack card
            labjack_card = DeviceStatusCard("LabJack", "USB DAQ", "📟")
            labjack_card.add_info_row("model", "Model:", "--")
            labjack_card.add_info_row("serial", "Serial:", "--")
            labjack_card.add_info_row("channels", "Channels:", "0")
            labjack_card.add_info_row("rate", "Sample Rate:", "0 Hz")
            labjack_card.test_btn.clicked.connect(lambda: self._test_device("labjack"))
            self.devices_container.insertWidget(1, labjack_card)
            self.device_cards["labjack"] = labjack_card
            
            # Camera card
            camera_card = DeviceStatusCard("Camera", "USB Camera", "📷")
            camera_card.add_info_row("name", "Name:", "--")
            camera_card.add_info_row("resolution", "Resolution:", "--")
            camera_card.add_info_row("fps", "FPS:", "0")
            camera_card.add_info_row("backend", "Backend:", "--")
            camera_card.test_btn.clicked.connect(lambda: self._test_device("camera"))
            self.devices_container.insertWidget(2, camera_card)
            self.device_cards["camera"] = camera_card
        
        # Update device status (now has robust error handling)
        self._update_device_status()
    
    def _scan_serial_ports(self):
        """Scan available serial ports in a background thread to prevent UI freeze."""
        self.ports_table.setRowCount(0)
        self.serial_monitor.append_info("Scanning serial ports...")
        
        from threading import Thread
        
        def scan_task():
            try:
                import serial.tools.list_ports
                ports = list(serial.tools.list_ports.comports())
                self.ports_scanned.emit(ports)
            except Exception as e:
                print(f"Error scanning serial ports: {e}")
                self.ports_scanned.emit([])

        Thread(target=scan_task, daemon=True).start()

    @pyqtSlot(list)
    def _do_update_ports_table(self, ports):
        """Actual UI update for ports table."""
        self.ports_table.setRowCount(0)
        for port in ports:
            row = self.ports_table.rowCount()
            self.ports_table.insertRow(row)
            
            # Port name
            self.ports_table.setItem(row, 0, QTableWidgetItem(port.device))
            
            # Description
            self.ports_table.setItem(row, 1, QTableWidgetItem(port.description))
            
            # VID:PID
            vid_pid = f"{port.vid:04X}:{port.pid:04X}" if port.vid and port.pid else "--"
            self.ports_table.setItem(row, 2, QTableWidgetItem(vid_pid))
            
            # Status (check if in use)
            status = "Available"
            if self.main_window and hasattr(self.main_window, 'sensor_controller'):
                sc = self.main_window.sensor_controller
                if hasattr(sc, 'arduino_port') and sc.arduino_port == port.device:
                    status = "In Use (Arduino)"
            
            status_item = QTableWidgetItem(status)
            if "In Use" in status:
                status_item.setForeground(QColor("#4CAF50"))
            self.ports_table.setItem(row, 3, status_item)
        
        self.serial_monitor.append_info(f"Found {len(ports)} serial port(s)")
    
    def _toggle_monitoring(self):
        """Toggle monitoring mode"""
        if self.monitor_btn.isChecked():
            self.monitor_btn.setText("⏹ Stop Monitoring")
            self.update_timer.start()
            self.serial_monitor.append_info("Monitoring started")
        else:
            self.monitor_btn.setText("▶ Start Monitoring")
            self.update_timer.stop()
            self.serial_monitor.append_info("Monitoring stopped")
    
    def _update_diagnostics(self):
        """Update diagnostic information"""
        self._update_device_status()
        self._update_data_rate()
    
    def _update_device_status(self):
        """Update device status cards with robust error handling"""
        if not self.main_window:
            return
            
        try:
            # Arduino status
            if "arduino" in self.device_cards:
                card = self.device_cards["arduino"]
                dcc = getattr(self.main_window, 'data_collection_controller', None)
                sc = getattr(self.main_window, 'sensor_controller', None)
                
                # Check Arduino connection via data_collection_controller.interfaces
                is_connected = False
                try:
                    if dcc and hasattr(dcc, 'interfaces') and 'arduino' in dcc.interfaces:
                        is_connected = dcc.interfaces['arduino'].get('connected', False)
                except (RuntimeError, AttributeError):
                    # Handle dictionary modification during access
                    pass
                
                card.set_connected(is_connected)
                
                if is_connected and dcc:
                    try:
                        # Get port and baud from data collection controller
                        arduino_interface = dcc.interfaces.get('arduino', {})
                        port = arduino_interface.get('port', '--')
                        baud = arduino_interface.get('baud_rate', 9600)
                        card.update_info("port", str(port))
                        card.update_info("baud", str(baud))
                    except (RuntimeError, AttributeError):
                        pass
                    
                    # Count Arduino sensors
                    if sc:
                        try:
                            # Use list() to avoid RuntimeError if sensors changed during iteration
                            arduino_sensors = sum(1 for s in list(sc.sensors) if getattr(s, 'interface_type', '') == 'Arduino')
                            card.update_info("sensors", str(arduino_sensors))
                        except (RuntimeError, TypeError):
                            pass
            
            # LabJack status
            if "labjack" in self.device_cards:
                card = self.device_cards["labjack"]
                sc = getattr(self.main_window, 'sensor_controller', None)
                
                is_connected = False
                lj = None
                
                if sc:
                    try:
                        # Check via labjack_interface
                        if hasattr(sc, 'labjack_interface') and sc.labjack_interface:
                            lj = sc.labjack_interface
                            if hasattr(lj, 'is_connected'):
                                is_connected = lj.is_connected()
                            elif hasattr(lj, 'connected'):
                                is_connected = lj.connected
                    except Exception:
                        pass
                
                card.set_connected(is_connected)
                
                if is_connected and lj:
                    card.update_info("model", str(getattr(lj, 'device_type', 'T7')))
                    card.update_info("serial", str(getattr(lj, 'serial_number', '--')))
                    
                    # Count LabJack sensors
                    if sc:
                        try:
                            # Use list() to avoid RuntimeError if sensors changed during iteration
                            lj_sensors = sum(1 for s in list(sc.sensors) if getattr(s, 'interface_type', '') == 'LabJack')
                            card.update_info("channels", str(lj_sensors))
                        except (RuntimeError, TypeError):
                            pass
            
            # Camera status
            if "camera" in self.device_cards:
                card = self.device_cards["camera"]
                cc = getattr(self.main_window, 'camera_controller', None)
                
                if cc:
                    # Use is_connected attribute which is managed by CameraController
                    is_connected = getattr(cc, 'is_connected', False)
                    card.set_connected(is_connected)
                    
                    if is_connected:
                        card.update_info("name", str(getattr(cc, 'camera_name', 'Camera')))
                        
                        width = getattr(cc, 'frame_width', 0)
                        height = getattr(cc, 'frame_height', 0)
                        if width and height:
                            card.update_info("resolution", f"{int(width)}x{int(height)}")
                        
                        fps = getattr(cc, 'current_fps', 0)
                        card.update_info("fps", f"{fps:.1f}")
        except Exception as e:
            print(f"Error in DiagnosticsTool._update_device_status: {e}")

    def _update_data_rate(self):
        """Update data rate graph with robust error handling"""
        if not self.main_window:
            return
            
        try:
            # Calculate current data rate
            total_samples = 0
            dc = getattr(self.main_window, 'data_collection_controller', None)
            
            if dc and hasattr(dc, 'collected_data'):
                # Safely iterate over dictionary items
                try:
                    # Create a static copy of items to avoid RuntimeError during iteration
                    items = list(dc.collected_data.items())
                    for sensor_key, data in items:
                        try:
                            current_count = len(data.get('time', []))
                            
                            if sensor_key in self.last_sample_counts:
                                diff = current_count - self.last_sample_counts[sensor_key]
                                total_samples += max(0, diff)
                            
                            self.last_sample_counts[sensor_key] = current_count
                        except (AttributeError, TypeError, RuntimeError):
                            continue
                except RuntimeError:
                    # If dictionary changed size during items() call
                    pass
            
            # Add to history
            self.data_rate_history.append(total_samples)
            
            # Update graph
            self.rate_plot.clear()
            if len(self.data_rate_history) > 1:
                x = list(range(-len(self.data_rate_history) + 1, 1))
                y = list(self.data_rate_history)
                self.rate_plot.plot(x, y, pen=pg.mkPen('#4CAF50', width=2), fillLevel=0, 
                                   brush=pg.mkBrush(76, 175, 80, 50))
            
            # Update labels
            self.current_rate_label.setText(f"{total_samples} samples/s")
            
            if self.data_rate_history:
                peak = max(self.data_rate_history)
                avg = sum(self.data_rate_history) / len(self.data_rate_history)
                self.peak_rate_label.setText(f"{peak}")
                self.avg_rate_label.setText(f"{avg:.1f}")
            
            # Update Arduino card rate
            if "arduino" in self.device_cards:
                self.device_cards["arduino"].update_info("rate", f"{total_samples} Hz")
        except Exception as e:
            print(f"Error in DiagnosticsTool._update_data_rate: {e}")
    
    def _test_device(self, device_type: str):
        """Test a specific device connection"""
        self.serial_monitor.append_info(f"Testing {device_type} connection...")
        
        if device_type == "arduino":
            self._test_arduino()
        elif device_type == "labjack":
            self._test_labjack()
        elif device_type == "camera":
            self._test_camera()
    
    def _test_arduino(self):
        """Test Arduino connection with robust error handling"""
        if not self.main_window:
            self.serial_monitor.append_error("Main window not available")
            return
        
        try:
            dcc = getattr(self.main_window, 'data_collection_controller', None)
            sc = getattr(self.main_window, 'sensor_controller', None)
            
            if not dcc:
                self.serial_monitor.append_error("Data collection controller not available")
                return
            
            # Check Arduino connection via data_collection_controller.interfaces
            is_connected = False
            arduino_interface = {}
            if hasattr(dcc, 'interfaces') and 'arduino' in dcc.interfaces:
                arduino_interface = dcc.interfaces['arduino']
                is_connected = arduino_interface.get('connected', False)
            
            if is_connected:
                self.serial_monitor.append_received("Arduino is connected")
                port = arduino_interface.get('port', 'Unknown')
                baud = arduino_interface.get('baud_rate', 'Unknown')
                self.serial_monitor.append_info(f"Port: {port}")
                self.serial_monitor.append_info(f"Baud Rate: {baud}")
                
                # Count sensors
                if sc:
                    try:
                        arduino_sensors = [s for s in list(sc.sensors) if getattr(s, 'interface_type', '') == 'Arduino']
                        self.serial_monitor.append_info(f"Active sensors: {len(arduino_sensors)}")
                        
                        for sensor in arduino_sensors:
                            try:
                                val = getattr(sensor, 'current_value', None)
                                val_str = f"{val:.3f}" if val is not None else "N/A"
                                self.serial_monitor.append_info(f"  • {getattr(sensor, 'name', 'Unknown')}: {val_str} {getattr(sensor, 'unit', '')}")
                            except (AttributeError, ValueError):
                                continue
                    except RuntimeError:
                        self.serial_monitor.append_info("Sensors list busy, could not count all.")
            else:
                self.serial_monitor.append_error("Arduino is not connected")
        except Exception as e:
            self.serial_monitor.append_error(f"Test error: {e}")
    
    def _test_labjack(self):
        """Test LabJack connection with robust error handling"""
        if not self.main_window:
            self.serial_monitor.append_error("Main window not available")
            return
        
        try:
            sc = getattr(self.main_window, 'sensor_controller', None)
            if not sc:
                self.serial_monitor.append_error("Sensor controller not available")
                return
            
            is_connected = False
            lj = None
            
            # Check via labjack_interface
            if hasattr(sc, 'labjack_interface') and sc.labjack_interface:
                lj = sc.labjack_interface
                try:
                    if hasattr(lj, 'is_connected'):
                        is_connected = lj.is_connected()
                    elif hasattr(lj, 'connected'):
                        is_connected = lj.connected
                except Exception:
                    pass
            
            if is_connected and lj:
                self.serial_monitor.append_received("LabJack is connected")
                self.serial_monitor.append_info(f"Model: {getattr(lj, 'device_type', 'T7')}")
                self.serial_monitor.append_info(f"Serial: {getattr(lj, 'serial_number', 'Unknown')}")
                
                # Count sensors
                try:
                    lj_sensors = [s for s in list(sc.sensors) if getattr(s, 'interface_type', '') == 'LabJack']
                    self.serial_monitor.append_info(f"Active channels: {len(lj_sensors)}")
                    
                    for sensor in lj_sensors:
                        try:
                            val = getattr(sensor, 'current_value', None)
                            val_str = f"{val:.3f}" if val is not None else "N/A"
                            self.serial_monitor.append_info(f"  • {getattr(sensor, 'name', 'Unknown')}: {val_str} {getattr(sensor, 'unit', '')}")
                        except (AttributeError, ValueError):
                            continue
                except RuntimeError:
                    self.serial_monitor.append_info("Channels list busy, could not count all.")
            else:
                self.serial_monitor.append_error("LabJack is not connected")
        except Exception as e:
            self.serial_monitor.append_error(f"Test error: {e}")
    
    def _test_camera(self):
        """Test camera connection with robust error handling"""
        if not self.main_window:
            self.serial_monitor.append_error("Main window not available")
            return
        
        try:
            cc = getattr(self.main_window, 'camera_controller', None)
            if not cc:
                self.serial_monitor.append_error("Camera controller not available")
                return
            
            if getattr(cc, 'camera_connected', False):
                self.serial_monitor.append_received("Camera is connected")
                self.serial_monitor.append_info(f"Name: {getattr(cc, 'camera_name', 'Camera')}")
                
                width = getattr(cc, 'frame_width', 0)
                height = getattr(cc, 'frame_height', 0)
                if width and height:
                    self.serial_monitor.append_info(f"Resolution: {int(width)}x{int(height)}")
                
                fps = getattr(cc, 'current_fps', 0)
                self.serial_monitor.append_info(f"FPS: {fps:.1f}")
            else:
                self.serial_monitor.append_error("Camera is not connected")
        except Exception as e:
            self.serial_monitor.append_error(f"Test error: {e}")
    
    def _on_command_sent(self, command: str):
        """Handle command sent from serial monitor"""
        # This could be extended to actually send commands to devices
        self.serial_monitor.append_info(f"Command '{command}' - not implemented yet")
    
    def stop(self):
        """Stop monitoring"""
        self.update_timer.stop()

