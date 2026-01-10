"""
Audio Sensor Configuration Dialog

Dialog for configuring audio sensor settings including:
- Device selection
- Measurement mode (RMS, Peak, Frequency, etc.)
- Output rate
- Frequency band settings
- Live level meter preview
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QGroupBox, QCheckBox,
    QTabWidget, QWidget, QMessageBox, QSlider, QFrame,
    QGridLayout, QProgressBar, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush

from app.ui.theme import ButtonStyles, GroupBoxStyles, COLORS, DialogStyles
from app.ui.tools.help_panel import HelpPanel, get_help_content

import numpy as np

# Try to import audio interface
try:
    from app.core.interfaces.audio_interface import AudioSensorThread, AUDIO_SENSOR_AVAILABLE
except ImportError:
    AUDIO_SENSOR_AVAILABLE = False
    AudioSensorThread = None


class LevelMeter(QFrame):
    """Custom widget for displaying audio level"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 30)
        self.setMaximumHeight(40)
        
        self._rms_level = 0.0
        self._peak_level = 0.0
        self._peak_hold = 0.0
        
        # Colors
        self._bg_color = QColor("#1a1a2e")
        self._green = QColor("#4CAF50")
        self._yellow = QColor("#FFC107")
        self._red = QColor("#F44336")
        
    def set_levels(self, rms, peak_hold):
        """Update the displayed levels"""
        self._rms_level = min(1.0, rms)  # Clamp to 0-1
        self._peak_hold = min(1.0, peak_hold)
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        margin = 2
        
        # Background
        painter.fillRect(rect, self._bg_color)
        
        # Draw scale marks
        painter.setPen(QPen(QColor("#444"), 1))
        for i in range(11):
            x = margin + (rect.width() - 2 * margin) * i / 10
            painter.drawLine(int(x), rect.height() - 5, int(x), rect.height())
        
        # Draw meter bar
        bar_rect = rect.adjusted(margin, margin, -margin, -10)
        bar_width = bar_rect.width()
        
        # RMS level (main bar)
        rms_width = int(bar_width * self._rms_level)
        if rms_width > 0:
            # Gradient effect: green -> yellow -> red
            gradient_rect = bar_rect.adjusted(0, 0, -(bar_width - rms_width), 0)
            
            if self._rms_level < 0.6:
                color = self._green
            elif self._rms_level < 0.85:
                color = self._yellow
            else:
                color = self._red
            
            painter.fillRect(gradient_rect, color)
        
        # Peak hold marker
        if self._peak_hold > 0:
            peak_x = margin + int(bar_width * self._peak_hold)
            painter.setPen(QPen(QColor("#fff"), 2))
            painter.drawLine(peak_x, margin, peak_x, bar_rect.height() + margin)
        
        # Border
        painter.setPen(QPen(QColor("#555"), 1))
        painter.drawRect(bar_rect)


class AudioSensorConfigDialog(QDialog):
    """Dialog for configuring an Audio Sensor"""
    
    # Signal emitted when settings are applied
    settings_changed = pyqtSignal(dict)
    
    # Measurement modes
    MODES = {
        "rms": {
            "name": "RMS Level",
            "icon": "📊",
            "description": "Root Mean Square - measures average signal power (perceived loudness)",
            "output_key": "rms"
        },
        "peak": {
            "name": "Peak Amplitude",
            "icon": "📈",
            "description": "Maximum amplitude in each measurement window",
            "output_key": "peak"
        },
        "frequency": {
            "name": "Dominant Frequency",
            "icon": "🎵",
            "description": "The most prominent frequency detected via FFT analysis",
            "output_key": "dominant_frequency"
        },
        "band_energy": {
            "name": "Band Energy",
            "icon": "🎚️",
            "description": "Energy in a specific frequency range (configurable)",
            "output_key": "band_energy"
        },
        "zero_crossing": {
            "name": "Zero Crossing Rate",
            "icon": "〰️",
            "description": "Rate at which the signal crosses zero - indicates pitch/noise",
            "output_key": "zero_crossing_rate"
        },
        "db_level": {
            "name": "dB Level",
            "icon": "🔊",
            "description": "Signal level in decibels (dBFS, not SPL-calibrated)",
            "output_key": "db_level"
        },
        "rpm": {
            "name": "RPM (from frequency)",
            "icon": "⚙️",
            "description": "Convert dominant frequency to RPM using pulses-per-revolution (e.g., blades or gear teeth)",
            "output_key": "rpm"
        },
    }
    
    def __init__(self, parent=None, sensor_name="Audio Sensor", current_settings=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure {sensor_name}")
        self.setMinimumSize(600, 500)
        self.sensor_name = sensor_name
        
        # Apply dark dialog style
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        # Default settings
        self.settings = {
            "mode": "rms",
            "device_id": None,  # None = default device
            "sample_rate": 44100,
            "chunk_size": 2048,
            "output_rate": 10,  # Hz
            
            # Frequency band settings
            "band_low": 100,
            "band_high": 4000,
            
            # Processing
            "noise_gate": 0.01,
            "smoothing": 0.3,
            "peak_hold_ms": 500,
            
            # RPM conversion
            "rpm_pulses_per_rev": 1.0,
            "min_frequency_hz": 5.0,
        }
        
        # Override with current settings
        if current_settings:
            self.settings.update(current_settings)
        
        # Preview state
        self.preview_thread = None
        self.preview_running = False
        
        self._setup_ui()
        self._load_settings()
        self._populate_devices()
    
    def _setup_ui(self):
        """Setup the dialog UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Header with Help Button
        header_layout = QHBoxLayout()

        header = QLabel(f"🎤 {self.sensor_name} Configuration")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        header_layout.addWidget(header)

        header_layout.addStretch()

        self.help_btn = QPushButton("❓ Help")
        self.help_btn.setCheckable(True)
        self.help_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.help_btn.clicked.connect(self._toggle_help)
        header_layout.addWidget(self.help_btn)

        main_layout.addLayout(header_layout)

        # Content splitter
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3a3a5c;
            }
        """)

        # Main content widget
        main_content = QWidget()
        content_layout = QVBoxLayout(main_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Check availability
        if not AUDIO_SENSOR_AVAILABLE:
            warning = QLabel(
                "⚠️ Audio sensor requires 'sounddevice' library.\n"
                "Install with: pip install sounddevice"
            )
            warning.setStyleSheet(f"color: {COLORS.WARNING}; font-size: 12px; padding: 10px;")
            warning.setWordWrap(True)
            main_layout.addWidget(warning)
        
        # Two column layout
        columns = QHBoxLayout()
        
        # Left column: Main settings
        left_column = QVBoxLayout()
        
        # Device selection
        device_group = QGroupBox("Audio Device")
        device_group.setStyleSheet(GroupBoxStyles.compact())
        device_layout = QFormLayout(device_group)
        
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(250)
        device_layout.addRow("Input Device:", self.device_combo)
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet(ButtonStyles.secondary("small"))
        refresh_btn.clicked.connect(self._populate_devices)
        device_layout.addRow("", refresh_btn)
        
        left_column.addWidget(device_group)
        
        # Mode selection
        mode_group = QGroupBox("Measurement Mode")
        mode_group.setStyleSheet(GroupBoxStyles.compact())
        mode_layout = QVBoxLayout(mode_group)
        
        self.mode_combo = QComboBox()
        for mode_key, mode_info in self.MODES.items():
            self.mode_combo.addItem(
                f"{mode_info['icon']} {mode_info['name']}", 
                mode_key
            )
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 11px; padding: 5px;")
        mode_layout.addWidget(self.mode_description)
        
        left_column.addWidget(mode_group)
        
        # Frequency band settings (for band_energy mode)
        self.band_group = QGroupBox("Frequency Band")
        self.band_group.setStyleSheet(GroupBoxStyles.compact())
        band_layout = QFormLayout(self.band_group)
        
        self.band_low_spin = QSpinBox()
        self.band_low_spin.setRange(20, 20000)
        self.band_low_spin.setValue(100)
        self.band_low_spin.setSuffix(" Hz")
        band_layout.addRow("Low Frequency:", self.band_low_spin)
        
        self.band_high_spin = QSpinBox()
        self.band_high_spin.setRange(20, 20000)
        self.band_high_spin.setValue(4000)
        self.band_high_spin.setSuffix(" Hz")
        band_layout.addRow("High Frequency:", self.band_high_spin)
        
        left_column.addWidget(self.band_group)
        
        # RPM settings (for RPM mode)
        self.rpm_group = QGroupBox("RPM Settings")
        self.rpm_group.setStyleSheet(GroupBoxStyles.compact())
        rpm_layout = QFormLayout(self.rpm_group)
        
        self.rpm_ppr_spin = QDoubleSpinBox()
        self.rpm_ppr_spin.setRange(0.1, 100.0)
        self.rpm_ppr_spin.setSingleStep(0.1)
        self.rpm_ppr_spin.setDecimals(2)
        self.rpm_ppr_spin.setSuffix(" pulses/rev")
        self.rpm_ppr_spin.setToolTip("Number of pulses or blades per revolution")
        rpm_layout.addRow("Pulses / Revolution:", self.rpm_ppr_spin)
        
        self.rpm_min_freq_spin = QDoubleSpinBox()
        self.rpm_min_freq_spin.setRange(0.1, 200.0)
        self.rpm_min_freq_spin.setSingleStep(0.5)
        self.rpm_min_freq_spin.setValue(5.0)
        self.rpm_min_freq_spin.setSuffix(" Hz")
        self.rpm_min_freq_spin.setToolTip("Minimum fundamental frequency to consider when estimating RPM")
        rpm_layout.addRow("Min fundamental freq:", self.rpm_min_freq_spin)
        
        left_column.addWidget(self.rpm_group)
        
        columns.addLayout(left_column)
        
        # Right column: Processing & Preview
        right_column = QVBoxLayout()
        
        # Processing settings
        proc_group = QGroupBox("Processing")
        proc_group.setStyleSheet(GroupBoxStyles.compact())
        proc_layout = QFormLayout(proc_group)
        
        self.output_rate_spin = QSpinBox()
        self.output_rate_spin.setRange(1, 100)
        self.output_rate_spin.setValue(10)
        self.output_rate_spin.setSuffix(" Hz")
        self.output_rate_spin.setToolTip("How many sensor values per second to output")
        proc_layout.addRow("Output Rate:", self.output_rate_spin)
        
        self.smoothing_slider = QSlider(Qt.Orientation.Horizontal)
        self.smoothing_slider.setRange(0, 99)
        self.smoothing_slider.setValue(30)
        self.smoothing_slider.setToolTip("Higher = smoother but slower response")
        proc_layout.addRow("Smoothing:", self.smoothing_slider)
        
        self.noise_gate_spin = QDoubleSpinBox()
        self.noise_gate_spin.setRange(0, 0.5)
        self.noise_gate_spin.setValue(0.01)
        self.noise_gate_spin.setSingleStep(0.01)
        self.noise_gate_spin.setToolTip("Ignore signals below this level")
        proc_layout.addRow("Noise Gate:", self.noise_gate_spin)
        
        self.auto_connect_cb = QCheckBox("Auto-connect on Startup")
        self.auto_connect_cb.setToolTip("Automatically connect this sensor when the application starts")
        proc_layout.addRow("", self.auto_connect_cb)
        
        right_column.addWidget(proc_group)
        
        # Live preview
        preview_group = QGroupBox("Live Preview")
        preview_group.setStyleSheet(GroupBoxStyles.compact())
        preview_layout = QVBoxLayout(preview_group)
        
        # Level meter
        self.level_meter = LevelMeter()
        preview_layout.addWidget(self.level_meter)
        
        # Preview value display
        self.preview_value = QLabel("--")
        self.preview_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_value.setStyleSheet(f"""
            font-size: 24px; 
            font-weight: bold; 
            color: {COLORS.PRIMARY}; 
            padding: 10px;
            background: {COLORS.BG_INPUT};
            border-radius: 8px;
        """)
        preview_layout.addWidget(self.preview_value)
        
        # Preview controls
        preview_controls = QHBoxLayout()
        
        self.preview_btn = QPushButton("▶️ Start Preview")
        self.preview_btn.setStyleSheet(ButtonStyles.success("medium"))
        self.preview_btn.clicked.connect(self._toggle_preview)
        preview_controls.addWidget(self.preview_btn)
        
        preview_layout.addLayout(preview_controls)
        
        right_column.addWidget(preview_group)
        right_column.addStretch()
        
        columns.addLayout(right_column)
        content_layout.addLayout(columns)

        self.content_splitter.addWidget(main_content)

        # Setup help panel
        self._setup_help_panel()

        main_layout.addWidget(self.content_splitter)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setStyleSheet(ButtonStyles.success("medium"))
        self.apply_btn.clicked.connect(self._apply_settings)
        buttons_layout.addWidget(self.apply_btn)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setStyleSheet(ButtonStyles.primary("medium"))
        self.ok_btn.clicked.connect(self._ok_clicked)
        buttons_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        self.cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(buttons_layout)
        
        # Update mode description
        self._on_mode_changed()
    
    def _populate_devices(self):
        """Populate the device dropdown"""
        self.device_combo.clear()
        self.device_combo.addItem("🎤 Default Device", None)
        
        if AUDIO_SENSOR_AVAILABLE:
            devices = AudioSensorThread.list_devices()
            for device in devices:
                self.device_combo.addItem(
                    f"🎤 {device['name']}", 
                    device['id']
                )
    
    def _on_mode_changed(self):
        """Handle mode selection change"""
        mode = self.mode_combo.currentData()
        if mode in self.MODES:
            self.mode_description.setText(self.MODES[mode]["description"])
        
        # Show/hide frequency band settings
        self.band_group.setVisible(mode == "band_energy")
        self.rpm_group.setVisible(mode == "rpm")
    
    def _toggle_preview(self):
        """Toggle live preview"""
        if self.preview_running:
            self._stop_preview()
        else:
            self._start_preview()
    
    def _start_preview(self):
        """Start audio preview"""
        if not AUDIO_SENSOR_AVAILABLE:
            QMessageBox.warning(self, "Audio Not Available", 
                               "sounddevice library is not installed.")
            return
        
        try:
            device_id = self.device_combo.currentData()
            
            self.preview_thread = AudioSensorThread()
            self.preview_thread.set_mode(self.mode_combo.currentData())
            self.preview_thread.output_rate = self.output_rate_spin.value()
            self.preview_thread.update_settings({
                "smoothing": self.smoothing_slider.value() / 100.0,
                "noise_gate": self.noise_gate_spin.value(),
                "band_low": self.band_low_spin.value(),
                "band_high": self.band_high_spin.value(),
                "rpm_pulses_per_rev": self.rpm_ppr_spin.value(),
                "min_frequency_hz": self.rpm_min_freq_spin.value(),
            })
            
            # Connect signals
            self.preview_thread.level_update.connect(self._update_level_meter)
            self.preview_thread.data_ready.connect(self._update_preview_value)
            
            if self.preview_thread.connect(device_id):
                self.preview_running = True
                self.preview_btn.setText("⏹️ Stop Preview")
                self.preview_btn.setStyleSheet(ButtonStyles.danger("medium"))
            else:
                QMessageBox.warning(self, "Connection Error", 
                                   "Could not connect to audio device.")
                
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", str(e))
    
    def _stop_preview(self):
        """Stop audio preview"""
        if self.preview_thread:
            self.preview_thread.disconnect()
            self.preview_thread = None
        
        self.preview_running = False
        self.preview_btn.setText("▶️ Start Preview")
        self.preview_btn.setStyleSheet(ButtonStyles.success("medium"))
        self.level_meter.set_levels(0, 0)
        self.preview_value.setText("--")
    
    def _update_level_meter(self, rms, peak_hold):
        """Update the level meter display"""
        self.level_meter.set_levels(rms, peak_hold)
    
    def _update_preview_value(self, data):
        """Update the preview value display"""
        mode = self.mode_combo.currentData()
        output_key = self.MODES.get(mode, {}).get("output_key", "rms")
        
        if output_key in data:
            value = data[output_key]
            
            # Format based on type
            if output_key == "dominant_frequency":
                text = f"{value:.1f} Hz"
            elif output_key == "db_level":
                text = f"{value:.1f} dB"
            elif output_key == "zero_crossing_rate":
                text = f"{value:.0f} /s"
            elif output_key == "rpm":
                text = f"{value:.0f} RPM"
            else:
                text = f"{value:.4f}"
            
            self.preview_value.setText(text)
    
    def _load_settings(self):
        """Load settings into UI"""
        # Mode
        mode_idx = self.mode_combo.findData(self.settings.get("mode", "rms"))
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)
        
        # Processing
        self.output_rate_spin.setValue(self.settings.get("output_rate", 10))
        self.smoothing_slider.setValue(int(self.settings.get("smoothing", 0.3) * 100))
        self.noise_gate_spin.setValue(self.settings.get("noise_gate", 0.01))
        self.rpm_ppr_spin.setValue(self.settings.get("rpm_pulses_per_rev", 1.0))
        self.rpm_min_freq_spin.setValue(self.settings.get("min_frequency_hz", 5.0))
        self.auto_connect_cb.setChecked(self.settings.get("auto_connect", True))
        
        # Frequency band
        self.band_low_spin.setValue(self.settings.get("band_low", 100))
        self.band_high_spin.setValue(self.settings.get("band_high", 4000))
    
    def _collect_settings(self):
        """Collect settings from UI"""
        return {
            "mode": self.mode_combo.currentData(),
            "device_id": self.device_combo.currentData(),
            "output_rate": self.output_rate_spin.value(),
            "smoothing": self.smoothing_slider.value() / 100.0,
            "noise_gate": self.noise_gate_spin.value(),
            "band_low": self.band_low_spin.value(),
            "band_high": self.band_high_spin.value(),
            "rpm_pulses_per_rev": self.rpm_ppr_spin.value(),
            "min_frequency_hz": self.rpm_min_freq_spin.value(),
            "auto_connect": self.auto_connect_cb.isChecked(),
        }
    
    def _apply_settings(self):
        """Apply settings"""
        self.settings = self._collect_settings()
        self.settings_changed.emit(self.settings)
    
    def _ok_clicked(self):
        """OK clicked - apply and close"""
        self._apply_settings()
        self.accept()
    
    def closeEvent(self, event):
        """Clean up on close"""
        self._stop_preview()
        super().closeEvent(event)
    
    def get_settings(self):
        """Get current settings"""
        return self._collect_settings()

    def _setup_help_panel(self):
        """Setup the help panel"""
        self.help_panel = HelpPanel("Audio Sensor Help")
        self.help_panel.close_requested.connect(self._toggle_help)
        self.help_panel.setVisible(False)
        self.content_splitter.addWidget(self.help_panel)

        # Load help content
        help_content = get_help_content("audio_sensor")
        self.help_panel.clear_sections()
        self.help_panel.title = help_content.get("title", "Help")

        for section in help_content.get("sections", []):
            self.help_panel.add_section(
                section.get("title", ""),
                section.get("content", ""),
                section.get("icon", "📖")
            )

        # Expand first section by default
        if self.help_panel.sections:
            self.help_panel.sections[0]._toggle()

    def _toggle_help(self):
        """Toggle help panel visibility"""
        self.help_visible = not hasattr(self, 'help_visible') or not self.help_visible
        self.help_panel.setVisible(self.help_visible)
        self.help_btn.setChecked(self.help_visible)

        if self.help_visible:
            # Set splitter sizes to show help
            total = self.content_splitter.width()
            self.content_splitter.setSizes([total - 350, 350])


class AudioSensorAddDialog(QDialog):
    """Dialog for adding a new Audio Sensor"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Audio Sensor")
        self.setMinimumSize(400, 300)
        
        # Apply dark dialog style
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel("🎤 Add New Audio Sensor")
        header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        layout.addWidget(header)
        
        # Check availability
        if not AUDIO_SENSOR_AVAILABLE:
            warning = QLabel(
                "⚠️ Audio sensor requires 'sounddevice' library.\n"
                "Install with: pip install sounddevice"
            )
            warning.setStyleSheet(f"color: {COLORS.WARNING}; padding: 10px;")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        
        # Form
        form_layout = QFormLayout()
        
        # Sensor name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Microphone 1")
        form_layout.addRow("Sensor Name:", self.name_edit)
        
        # Device selection
        self.device_combo = QComboBox()
        self.device_combo.addItem("🎤 Default Device", None)
        
        if AUDIO_SENSOR_AVAILABLE:
            devices = AudioSensorThread.list_devices()
            for device in devices:
                self.device_combo.addItem(f"🎤 {device['name']}", device['id'])
        
        form_layout.addRow("Device:", self.device_combo)
        
        # Mode selection
        self.mode_combo = QComboBox()
        for mode_key, mode_info in AudioSensorConfigDialog.MODES.items():
            self.mode_combo.addItem(f"{mode_info['icon']} {mode_info['name']}", mode_key)
        form_layout.addRow("Measurement:", self.mode_combo)
        
        self.auto_connect_cb = QCheckBox("Auto-connect on Startup")
        self.auto_connect_cb.setChecked(True)
        form_layout.addRow("", self.auto_connect_cb)
        
        layout.addLayout(form_layout)
        
        # Info
        info = QLabel(
            "💡 The audio sensor converts microphone input into numeric values "
            "that can be graphed like any other sensor. Choose a measurement mode "
            "to determine what value is output."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 11px; padding: 10px;")
        layout.addWidget(info)
        
        layout.addStretch()
        
        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        
        add_btn = QPushButton("Add Sensor")
        add_btn.setStyleSheet(ButtonStyles.success("medium"))
        add_btn.clicked.connect(self._validate_and_accept)
        add_btn.setEnabled(AUDIO_SENSOR_AVAILABLE)
        buttons.addWidget(add_btn)
        
        layout.addLayout(buttons)
    
    def _validate_and_accept(self):
        """Validate and accept"""
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Please enter a sensor name.")
            return
        self.accept()
    
    def get_sensor_config(self):
        """Get the sensor configuration"""
        return {
            "name": self.name_edit.text().strip(),
            "device_id": self.device_combo.currentData(),
            "mode": self.mode_combo.currentData(),
            "auto_connect": self.auto_connect_cb.isChecked(),
        }

