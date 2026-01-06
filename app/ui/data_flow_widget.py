"""
Data Flow Widget

Visual representation of real-time data flow through the DAQ system.
Shows input sources, central data manager, and output destinations.
"""

import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QFrame, QScrollArea, QGroupBox, QSizePolicy, QGraphicsDropShadowEffect,
    QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPainterPath

from app.ui.theme import CardStyles, COLORS


class FlowCard(QFrame):
    """A styled card widget for displaying data flow information"""
    
    def __init__(self, title, icon_emoji="📊", parent=None):
        super().__init__(parent)
        self.title = title
        self.icon_emoji = icon_emoji
        self._is_active = False
        self._pulse_opacity = 0
        
        self.setFrameShape(QFrame.Shape.Box)
        self.setMinimumSize(180, 120)
        self.setMaximumWidth(220)
        
        self._setup_ui()
        self._apply_inactive_style()
        
        # Pulse animation timer
        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self._update_pulse)
        
    def _setup_ui(self):
        """Setup the card UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        # Header with icon and title
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        self.icon_label = QLabel(self.icon_emoji)
        self.icon_label.setFont(QFont("Segoe UI Emoji", 16))
        header_layout.addWidget(self.icon_label)
        
        self.title_label = QLabel(self.title)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #FFFFFF;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        
        # Status indicator
        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont("Segoe UI", 14))
        self.status_indicator.setStyleSheet("color: #666666;")
        header_layout.addWidget(self.status_indicator)
        
        layout.addLayout(header_layout)
        
        # Content area for stats
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 4, 0, 0)
        self.content_layout.setSpacing(2)
        
        # Stats labels (will be populated by subclasses or updates)
        self.stat_labels = {}
        
        layout.addWidget(self.content_widget)
        layout.addStretch()
        
    def add_stat_line(self, key, label_text, value_text="--"):
        """Add a statistic line to the card"""
        line_layout = QHBoxLayout()
        line_layout.setSpacing(4)
        
        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 9))
        label.setStyleSheet("color: #AAAAAA;")
        line_layout.addWidget(label)
        
        value = QLabel(value_text)
        value.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        value.setStyleSheet("color: #DDDDDD;")
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        line_layout.addWidget(value)
        
        self.content_layout.addLayout(line_layout)
        self.stat_labels[key] = value
        
    def update_stat(self, key, value_text):
        """Update a statistic value"""
        if key in self.stat_labels:
            self.stat_labels[key].setText(str(value_text))
    
    def set_active(self, active):
        """Set the active state of the card"""
        self._is_active = active
        if active:
            self._apply_active_style()
            self.status_indicator.setStyleSheet("color: #4CAF50;")  # Green
            self._pulse_timer.start(50)
        else:
            self._apply_inactive_style()
            self.status_indicator.setStyleSheet("color: #666666;")  # Gray
            self._pulse_timer.stop()
    
    def _apply_active_style(self):
        """Apply active/connected style"""
        self.setStyleSheet(CardStyles.status("connected").replace("QFrame", "FlowCard"))
    
    def _apply_inactive_style(self):
        """Apply inactive/disconnected style"""
        self.setStyleSheet(CardStyles.device_card(connected=False).replace("QFrame", "FlowCard"))
    
    def set_recording(self):
        """Apply recording style (red tint)"""
        self.setStyleSheet(CardStyles.status("disconnected").replace("QFrame", "FlowCard"))
        self.status_indicator.setStyleSheet(f"color: {COLORS.ERROR};")
    
    def set_streaming(self):
        """Apply streaming style (blue tint)"""
        self.setStyleSheet(CardStyles.status("info").replace("QFrame", "FlowCard"))
        self.status_indicator.setStyleSheet(f"color: {COLORS.INFO};")
    
    def _update_pulse(self):
        """Update pulse animation"""
        # Simple pulse effect - could be enhanced
        pass


class CommandLogWidget(QFrame):
    """Widget showing recent outbound commands"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setMinimumHeight(200)
        self.setMaximumHeight(300)
        
        self._setup_ui()
        self._apply_style()
        
        # Store command entries
        self.command_entries = []
        self.max_entries = 50  # Maximum commands to show
        
    def _setup_ui(self):
        """Setup the command log UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        
        # Header
        header_layout = QHBoxLayout()
        
        header_label = QLabel("📤 OUTBOUND COMMANDS")
        header_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        header_label.setStyleSheet("color: #FFFFFF;")
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        self.count_label = QLabel("0 commands")
        self.count_label.setFont(QFont("Segoe UI", 9))
        self.count_label.setStyleSheet("color: #888888;")
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        # Scrollable command list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2D2D2D;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self.commands_container = QWidget()
        self.commands_layout = QVBoxLayout(self.commands_container)
        self.commands_layout.setContentsMargins(0, 0, 0, 0)
        self.commands_layout.setSpacing(4)
        self.commands_layout.addStretch()
        
        scroll_area.setWidget(self.commands_container)
        layout.addWidget(scroll_area)
        
        # Empty state message
        self.empty_label = QLabel("No commands sent yet")
        self.empty_label.setFont(QFont("Segoe UI", 9))
        self.empty_label.setStyleSheet("color: #666666;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.commands_layout.insertWidget(0, self.empty_label)
        
    def _apply_style(self):
        """Apply widget styling"""
        self.setStyleSheet(CardStyles.elevated().replace("QFrame", "CommandLogWidget"))
    
    def add_command(self, entry):
        """
        Add a command entry to the log
        
        Args:
            entry: dict with keys: timestamp, target, command, source, etc.
        """
        # Hide empty state if showing
        self.empty_label.hide()
        
        # Create command widget
        cmd_widget = self._create_command_widget(entry)
        
        # Insert at top (after stretch is at bottom)
        self.commands_layout.insertWidget(0, cmd_widget)
        self.command_entries.insert(0, cmd_widget)
        
        # Remove old entries if over limit
        while len(self.command_entries) > self.max_entries:
            old_widget = self.command_entries.pop()
            old_widget.deleteLater()
        
        # Update count
        self.count_label.setText(f"{len(self.command_entries)} commands")
    
    def _create_command_widget(self, entry):
        """Create a widget for a command entry"""
        widget = QFrame()
        widget.setStyleSheet(CardStyles.status("connected"))
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        
        # First line: timestamp and target
        top_layout = QHBoxLayout()
        
        # Time
        time_str = time.strftime("%H:%M:%S", time.localtime(entry.get('timestamp', time.time())))
        time_label = QLabel(f"🟢 {time_str}")
        time_label.setFont(QFont("Segoe UI", 9))
        time_label.setStyleSheet("color: #4CAF50;")
        top_layout.addWidget(time_label)
        
        # Target
        target = entry.get('target', 'Unknown').capitalize()
        target_label = QLabel(f"→ {target}")
        target_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        target_label.setStyleSheet("color: #FFFFFF;")
        top_layout.addWidget(target_label)
        
        top_layout.addStretch()
        
        # Command
        command = entry.get('command', '')
        if len(command) > 30:
            command = command[:27] + "..."
        cmd_label = QLabel(f'"{command}"')
        cmd_label.setFont(QFont("Consolas", 9))
        cmd_label.setStyleSheet("color: #FFC107;")
        top_layout.addWidget(cmd_label)
        
        layout.addLayout(top_layout)
        
        # Second line: source automation
        source = entry.get('source', 'Manual')
        source_label = QLabel(f"└─ Triggered by: {source}")
        source_label.setFont(QFont("Segoe UI", 8))
        source_label.setStyleSheet("color: #888888;")
        layout.addWidget(source_label)
        
        return widget
    
    def clear_log(self):
        """Clear all command entries"""
        for widget in self.command_entries:
            widget.deleteLater()
        self.command_entries.clear()
        self.empty_label.show()
        self.count_label.setText("0 commands")


class DataFlowWidget(QWidget):
    """Main data flow visualization widget"""
    
    def __init__(self, data_flow_controller=None, parent=None):
        super().__init__(parent)
        self.controller = data_flow_controller
        
        self._setup_ui()
        
        # Connect to controller signals
        if self.controller:
            self.controller.stats_updated.connect(self._update_display)
            self.controller.outbound_command_sent.connect(self._on_command_sent)
    
    def set_controller(self, controller):
        """Set the data flow controller after initialization"""
        self.controller = controller
        if controller:
            controller.stats_updated.connect(self._update_display)
            controller.outbound_command_sent.connect(self._on_command_sent)
    
    def _setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Title
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(10, 5, 10, 5)
        
        title_label = QLabel("📊 DATA FLOW MONITOR")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #FFFFFF;")
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        # Hint about keyboard shortcut
        hint_label = QLabel("Press Ctrl+Shift+D or click status bar to toggle")
        hint_label.setFont(QFont("Segoe UI", 9))
        hint_label.setStyleSheet("color: #666666;")
        title_layout.addWidget(hint_label)
        
        main_layout.addLayout(title_layout)
        
        # Create Scroll Area for the content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
            }
            QWidget#scroll_content {
                background: transparent;
            }
            QScrollBar:vertical {
                background-color: rgba(45, 45, 75, 0.3);
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(85, 85, 125, 0.6);
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setObjectName("scroll_content")
        content_vlayout = QVBoxLayout(scroll_content)
        content_vlayout.setContentsMargins(10, 10, 10, 10)
        content_vlayout.setSpacing(20)
        
        # Main content area (Horizontal: Inputs | Manager | Outputs)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(30)
        
        # LEFT COLUMN: Input Sources
        left_column = QVBoxLayout()
        left_column.setSpacing(15)
        
        inputs_label = QLabel("📥 DATA SOURCES")
        inputs_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        inputs_label.setStyleSheet("color: #AAAAAA;")
        left_column.addWidget(inputs_label)
        
        # Grid layout for source cards (2 columns, multiple rows)
        sources_grid = QGridLayout()
        sources_grid.setSpacing(15)
        
        # Row 1: Arduino, LabJack
        # Arduino card
        self.arduino_card = FlowCard("Arduino", "🔌")
        self.arduino_card.add_stat_line("sensors", "Sensors:")
        self.arduino_card.add_stat_line("rate", "Sample Rate:")
        self.arduino_card.add_stat_line("data_rate", "Data Rate:")
        self.arduino_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.arduino_card, 0, 0)
        
        # LabJack card
        self.labjack_card = FlowCard("LabJack", "📟")
        self.labjack_card.add_stat_line("channels", "Channels:")
        self.labjack_card.add_stat_line("rate", "Sample Rate:")
        self.labjack_card.add_stat_line("data_rate", "Data Rate:")
        self.labjack_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.labjack_card, 0, 1)
        
        # Row 2: Serial Sensors, Camera
        # Serial card
        self.other_card = FlowCard("Serial Sensors", "🔗")
        self.other_card.add_stat_line("devices", "Devices:")
        self.other_card.add_stat_line("rate", "Sample Rate:")
        self.other_card.add_stat_line("data_rate", "Data Rate:")
        sources_grid.addWidget(self.other_card, 1, 0)
        
        # Camera card
        self.camera_card = FlowCard("Camera", "📷")
        self.camera_card.add_stat_line("resolution", "Resolution:")
        self.camera_card.add_stat_line("fps", "Frame Rate:")
        self.camera_card.add_stat_line("data_rate", "Data Rate:")
        self.camera_card.add_stat_line("frames", "Total Frames:")
        sources_grid.addWidget(self.camera_card, 1, 1)
        
        # Row 3: Audio Sensor, Optical Sensor
        # Audio Sensor card
        self.audio_card = FlowCard("Audio Sensor", "🎤")
        self.audio_card.add_stat_line("sensors", "Sensors:")
        self.audio_card.add_stat_line("rate", "Sample Rate:")
        self.audio_card.add_stat_line("data_rate", "Data Rate:")
        self.audio_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.audio_card, 2, 0)
        
        # Optical Sensor card
        self.optical_card = FlowCard("Optical Sensor", "📹")
        self.optical_card.add_stat_line("sensors", "Sensors:")
        self.optical_card.add_stat_line("rate", "Sample Rate:")
        self.optical_card.add_stat_line("data_rate", "Data Rate:")
        self.optical_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.optical_card, 2, 1)

        # Row 4: CSV Input, MQTT
        # CSV Input card
        self.csv_input_card = FlowCard("CSV Interface", "📂")
        self.csv_input_card.add_stat_line("files", "Files:")
        self.csv_input_card.add_stat_line("rate", "Sample Rate:")
        self.csv_input_card.add_stat_line("data_rate", "Data Rate:")
        self.csv_input_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.csv_input_card, 3, 0)
        
        # MQTT card
        self.mqtt_card = FlowCard("MQTT", "🌐")
        self.mqtt_card.add_stat_line("topics", "Topics:")
        self.mqtt_card.add_stat_line("rate", "Sample Rate:")
        self.mqtt_card.add_stat_line("data_rate", "Data Rate:")
        self.mqtt_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.mqtt_card, 3, 1)

        # Row 5: Remote DAQ
        self.remote_daq_card = FlowCard("Remote DAQ", "📡")
        self.remote_daq_card.add_stat_line("status", "Status:")
        self.remote_daq_card.add_stat_line("sensors", "Sensors:")
        self.remote_daq_card.add_stat_line("rate", "Sample Rate:")
        self.remote_daq_card.add_stat_line("total", "Total Samples:")
        sources_grid.addWidget(self.remote_daq_card, 4, 0, 1, 2) # Span across 2 columns
        
        left_column.addLayout(sources_grid)
        left_column.addStretch()
        content_layout.addLayout(left_column)
        
        # CENTER COLUMN: Data Manager
        center_column = QVBoxLayout()
        center_column.setSpacing(15)
        
        center_label = QLabel("⚙️ DATA MANAGER")
        center_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        center_label.setStyleSheet("color: #AAAAAA;")
        center_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_column.addWidget(center_label)
        
        # Data manager card (larger, central)
        self.data_manager_card = FlowCard("Data Hub", "🔄")
        self.data_manager_card.setMinimumSize(200, 140)
        self.data_manager_card.add_stat_line("buffer", "Buffer Size:")
        self.data_manager_card.add_stat_line("throughput", "Throughput:")
        self.data_manager_card.add_stat_line("total", "Total Points:")
        center_column.addWidget(self.data_manager_card, alignment=Qt.AlignmentFlag.AlignCenter)
        
        center_column.addStretch()
        
        # Automations section
        auto_label = QLabel("🤖 AUTOMATIONS")
        auto_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        auto_label.setStyleSheet("color: #AAAAAA;")
        auto_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_column.addWidget(auto_label)
        
        self.automation_card = FlowCard("Sequences", "⚡")
        self.automation_card.add_stat_line("active", "Running:")
        self.automation_card.add_stat_line("total", "Total:")
        self.automation_card.add_stat_line("names", "Active:")
        center_column.addWidget(self.automation_card, alignment=Qt.AlignmentFlag.AlignCenter)
        
        center_column.addStretch()
        content_layout.addLayout(center_column)
        
        # RIGHT COLUMN: Outputs
        right_column = QVBoxLayout()
        right_column.setSpacing(15)
        
        outputs_label = QLabel("📤 DATA OUTPUTS")
        outputs_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        outputs_label.setStyleSheet("color: #AAAAAA;")
        right_column.addWidget(outputs_label)
        
        # CSV Output card
        self.csv_card = FlowCard("CSV File", "📄")
        self.csv_card.add_stat_line("file", "File:")
        self.csv_card.add_stat_line("size", "Size:")
        self.csv_card.add_stat_line("rows", "Rows:")
        self.csv_card.add_stat_line("rate", "Write Rate:")
        right_column.addWidget(self.csv_card)
        
        # Video Output card
        self.video_card = FlowCard("Video Recording", "🎬")
        self.video_card.add_stat_line("file", "File:")
        self.video_card.add_stat_line("size", "Size:")
        self.video_card.add_stat_line("duration", "Duration:")
        self.video_card.add_stat_line("bitrate", "Bitrate:")
        right_column.addWidget(self.video_card)
        
        # Remote Stream card
        self.stream_card = FlowCard("Remote Stream", "🌐")
        self.stream_card.add_stat_line("status", "Status:")
        self.stream_card.add_stat_line("name", "Stream:")
        self.stream_card.add_stat_line("clients", "Clients:")
        self.stream_card.add_stat_line("rate", "Out Rate:")
        right_column.addWidget(self.stream_card)
        
        # Graphs display (not really an output but shows data usage)
        self.graphs_card = FlowCard("Live Graphs", "📈")
        self.graphs_card.add_stat_line("status", "Status:")
        self.graphs_card.add_stat_line("refresh", "Refresh:")
        right_column.addWidget(self.graphs_card)
        
        right_column.addStretch()
        content_layout.addLayout(right_column)
        
        content_vlayout.addLayout(content_layout)
        
        # BOTTOM: Command Log
        self.command_log = CommandLogWidget()
        content_vlayout.addWidget(self.command_log)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # Apply dark theme
        self.setStyleSheet("""
            DataFlowWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:0.5 #16213e, stop:1 #1a1a2e);
            }
        """)
        
        # Apply dark theme
        self.setStyleSheet("""
            DataFlowWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:0.5 #16213e, stop:1 #1a1a2e);
            }
        """)
    
    def _update_display(self):
        """Update all display elements from controller stats"""
        if not self.controller:
            return
        
        stats = self.controller.get_stats()
        
        # Arduino
        arduino = stats['arduino']
        self.arduino_card.set_active(arduino['connected'])
        self.arduino_card.update_stat("sensors", str(arduino['sensor_count']))
        self.arduino_card.update_stat("rate", f"{arduino['samples_per_sec']:.1f} Hz")
        self.arduino_card.update_stat("data_rate", self.controller.format_rate(arduino['bytes_per_sec']))
        self.arduino_card.update_stat("total", str(arduino['total_samples']))
        
        # LabJack
        labjack = stats['labjack']
        self.labjack_card.set_active(labjack['connected'])
        self.labjack_card.update_stat("channels", str(labjack['channel_count']))
        self.labjack_card.update_stat("rate", f"{labjack['samples_per_sec']:.1f} Hz")
        self.labjack_card.update_stat("data_rate", self.controller.format_rate(labjack['bytes_per_sec']))
        self.labjack_card.update_stat("total", str(labjack['total_samples']))
        
        # Serial Sensors
        other = stats['other_serial']
        self.other_card.set_active(other['connected'])
        self.other_card.update_stat("devices", str(other['device_count']))
        self.other_card.update_stat("rate", f"{other['samples_per_sec']:.1f} Hz")
        self.other_card.update_stat("data_rate", self.controller.format_rate(other['bytes_per_sec']))
        
        # Camera
        camera = stats['camera']
        self.camera_card.set_active(camera['connected'])
        res = camera['resolution']
        self.camera_card.update_stat("resolution", f"{res[0]}x{res[1]}" if res[0] > 0 else "--")
        self.camera_card.update_stat("fps", f"{camera['fps']:.1f} FPS")
        self.camera_card.update_stat("data_rate", self.controller.format_rate(camera['bytes_per_sec']))
        self.camera_card.update_stat("frames", str(camera['frame_count']))
        
        # Audio Sensor
        audio = stats['audio']
        self.audio_card.set_active(audio['connected'])
        self.audio_card.update_stat("sensors", str(audio['sensor_count']))
        self.audio_card.update_stat("rate", f"{audio['samples_per_sec']:.1f} Hz")
        self.audio_card.update_stat("data_rate", self.controller.format_rate(audio['bytes_per_sec']))
        self.audio_card.update_stat("total", str(audio['total_samples']))
        
        # Optical Sensor
        optical = stats['optical']
        self.optical_card.set_active(optical['connected'])
        self.optical_card.update_stat("sensors", str(optical['sensor_count']))
        self.optical_card.update_stat("rate", f"{optical['samples_per_sec']:.1f} Hz")
        self.optical_card.update_stat("data_rate", self.controller.format_rate(optical['bytes_per_sec']))
        self.optical_card.update_stat("total", str(optical['total_samples']))

        # CSV Input
        csv_in = stats['csv_input']
        self.csv_input_card.set_active(csv_in['connected'])
        self.csv_input_card.update_stat("files", str(csv_in['file_count']))
        self.csv_input_card.update_stat("rate", f"{csv_in['samples_per_sec']:.1f} Hz")
        self.csv_input_card.update_stat("data_rate", self.controller.format_rate(csv_in['bytes_per_sec']))
        self.csv_input_card.update_stat("total", str(csv_in['total_samples']))
        
        # MQTT
        mqtt = stats['mqtt']
        self.mqtt_card.set_active(mqtt['connected'])
        self.mqtt_card.update_stat("topics", str(mqtt['topic_count']))
        self.mqtt_card.update_stat("rate", f"{mqtt['samples_per_sec']:.1f} Hz")
        self.mqtt_card.update_stat("data_rate", self.controller.format_rate(mqtt['bytes_per_sec']))
        self.mqtt_card.update_stat("total", str(mqtt['total_samples']))
        
        # Remote DAQ
        remote = stats['remote_daq']
        self.remote_daq_card.set_active(remote['connected'])
        status_text = "Idle"
        if remote['is_master']: status_text = "Streaming (Master)"
        elif remote['is_client']: status_text = "Receiving (Client)"
        self.remote_daq_card.update_stat("status", status_text)
        self.remote_daq_card.update_stat("sensors", str(remote['sensor_count']))
        self.remote_daq_card.update_stat("rate", f"{remote['samples_per_sec']:.1f} Hz")
        self.remote_daq_card.update_stat("total", str(remote['total_samples']))
        
        # Data Manager
        dm = stats['data_manager']
        self.data_manager_card.set_active(dm['points_per_sec'] > 0)
        self.data_manager_card.update_stat("buffer", f"{dm['buffer_size']:,} pts")
        self.data_manager_card.update_stat("throughput", f"{dm['points_per_sec']:.1f} pts/s")
        self.data_manager_card.update_stat("total", f"{dm['total_points']:,}")
        
        # CSV
        csv = stats['csv']
        self.csv_card.set_active(csv['writing'])
        file_name = csv['file_path'].split('\\')[-1].split('/')[-1] if csv['file_path'] else "--"
        if len(file_name) > 20:
            file_name = file_name[:17] + "..."
        self.csv_card.update_stat("file", file_name)
        self.csv_card.update_stat("size", self.controller.format_bytes(csv['file_size_bytes']))
        self.csv_card.update_stat("rows", f"{csv['row_count']:,}")
        self.csv_card.update_stat("rate", self.controller.format_rate(csv['write_rate_bytes']))
        
        # Video
        rec = stats['recorder']
        if rec['recording']:
            self.video_card.set_recording()
        else:
            self.video_card.set_active(False)
        file_name = rec['file_path'].split('\\')[-1].split('/')[-1] if rec['file_path'] else "--"
        if len(file_name) > 20:
            file_name = file_name[:17] + "..."
        self.video_card.update_stat("file", file_name)
        self.video_card.update_stat("size", self.controller.format_bytes(rec['file_size_bytes']))
        
        # Format duration
        duration = rec['duration_sec']
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        self.video_card.update_stat("duration", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.video_card.update_stat("bitrate", f"{rec['bitrate_kbps']:.0f} kbps" if rec['bitrate_kbps'] > 0 else "--")
        
        # Stream
        stream = stats['stream']
        if stream['active']:
            self.stream_card.set_streaming()
            self.stream_card.update_stat("status", "Master" if stream['is_master'] else "Client")
        else:
            self.stream_card.set_active(False)
            self.stream_card.update_stat("status", "Inactive")
        self.stream_card.update_stat("name", stream['stream_name'] or "--")
        self.stream_card.update_stat("clients", str(stream['client_count']))
        self.stream_card.update_stat("rate", self.controller.format_rate(stream['bytes_out_per_sec']))
        
        # Automations
        auto = stats['automations']
        self.automation_card.set_active(auto['active_count'] > 0)
        self.automation_card.update_stat("active", str(auto['active_count']))
        self.automation_card.update_stat("total", str(auto['total_count']))
        running_names = ", ".join(auto['running_names'][:3])
        if len(auto['running_names']) > 3:
            running_names += f" +{len(auto['running_names']) - 3}"
        self.automation_card.update_stat("names", running_names or "None")
        
        # Graphs - active when any data is flowing
        any_data_flowing = (
            arduino['samples_per_sec'] > 0.1 or 
            labjack['samples_per_sec'] > 0.1 or 
            other['samples_per_sec'] > 0.1 or 
            camera['fps'] > 0.1 or
            audio['samples_per_sec'] > 0.1 or
            optical['samples_per_sec'] > 0.1 or
            csv_in['samples_per_sec'] > 0.1 or
            mqtt['samples_per_sec'] > 0.1 or
            remote['samples_per_sec'] > 0.1
        )
        self.graphs_card.set_active(any_data_flowing)
        self.graphs_card.update_stat("status", "Active" if any_data_flowing else "Idle")
        self.graphs_card.update_stat("refresh", "~10 FPS" if any_data_flowing else "--")
    
    def _on_command_sent(self, entry):
        """Handle outbound command signal"""
        self.command_log.add_command(entry)
    
    def load_existing_commands(self):
        """Load existing commands from controller log"""
        if self.controller:
            for entry in self.controller.get_outbound_log():
                self.command_log.add_command(entry)

